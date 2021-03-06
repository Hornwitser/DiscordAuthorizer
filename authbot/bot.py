from aiohttp import ClientError
from asyncio import get_event_loop, sleep
import atexit
from inspect import signature
import json
import logging
import os
from socketserver import UnixDatagramServer, BaseRequestHandler
from threading import Thread

from discord import Channel, Client, Member, Message, Role, Server, User, \
                    utils, HTTPException, GatewayNotFound, ConnectionClosed
from discord.gateway import DiscordWebSocket, ReconnectWebSocket

import pymysql
from websockets import InvalidHandshake, WebSocketProtocolError

from utils import PeriodicTimer
from cmdsys import command, is_command, get_commands, invoke_command, split
from cmdsys import convert


class ForumBot(Client):
    def __init__(self, config):
        Client.__init__(self)
        self.config = config
        self.informed = set()
        self.exception = None

        self.sync_timer = PeriodicTimer(config['db_sync_interval'],
                                        self.dispatch, args=('sync_database',))
        self.sync_timer.start()

    # This is a hack to deal with connect() closing the Client object
    # while there being no way to unclose it, forcing one to recreate
    # the whole thing.
    async def sane_connect(self):
        self.ws = await DiscordWebSocket.from_client(self)

        while not self.is_closed:
            try:
                await self.ws.poll_event()
            except ReconnectWebSocket:
                logging.info('Reconnecting the websocket.')
                self.ws = await DiscordWebSocket.from_client(self)
            except ConnectionClosed as e:
                # yield from self.close() # This should not be done..
                if e.code != 1000:
                    raise

    # This is a rather hackish way to get arround the problem of there
    # being no sane way to propogate exception from a thread to the
    # main thread.
    def on_raise_exception(self, exception):
        self.exception = exception

    # The handle variant is internal to Client and should probably not
    # be used here.  This is also a rather dirty hack to insert an
    # action to the thread that handles this bot.
    def handle_socket_response(self, response):
        if self.exception is not None:
            raise self.exception

    def get_role(self, user):
        if user.id in self.config['masters']:
            return 'master'
        elif user.id in self.config['admins']:
            return 'admin'
        elif (isinstance(user, Member)
            and any((r.id in self.config['admin_roles'] for r in user.roles))):
                return 'admin'
        elif user.id in self.config['ignores']:
            return 'ignore'
        else:
            return 'user'

    @property
    def bot_server(self):
        return utils.find(lambda s: s.id == self.config['server'],
                          self.servers)

    def resolve_permission(self, server, role, cmd):
        if role == 'master':
            return 'allow'

        elif server.id != self.config['server']:
            return 'ignore'

        elif (role == 'admin' and cmd in self.config['admin_commands']
              or role == 'user' and cmd in self.config['user_commands']):
            return 'allow'

        elif role != 'ignore' and self.config['noisy_deny']:
            return 'deny'

        else:
            return 'ignore'

    async def on_message(self, msg):
        if msg.author == self.user:
            return

        elif msg.channel.is_private:
            if msg.author in self.bot_server.members:
                token = msg.content.strip()
                if len(token) == 16:
                    await self.try_token(msg.author, token)
                else:
                    await self.send_message(msg.channel, "That does not look "
                                            "like an access token.")
            else:
                if msg.channel.id not in self.informed:
                    await self.send_message(msg.channel, "I am a bot and I "
                                            "don't serve you.")
                    self.informed.update([msg.channel.id])

        else:
            if not msg.content.startswith(self.config['trigger']):
                return
            line = msg.content[len(self.config['trigger']):]
            parts = split(line)
            if not parts:
                return
            cmd, args = parts[0], parts[1:]
            func = getattr(self, cmd, None)
            if not is_command(func):
                return
            role = self.get_role(msg.author)
            action = self.resolve_permission(msg.server, role, cmd)
            if action == 'allow':
                try:
                    response = await invoke_command(func, msg, args)
                except Exception as e:
                    await self.send_message(msg.channel, "Error: {}".format(e))
                else:
                    if response is not None:
                        await self.send_message(msg.channel, response)

            elif action == 'deny':
                await self.send_message(msg.channel, "You do not have "
                                        "permission to use this command.")

    async def on_member_join(self, member):
        await self.refresh_id(member.id)

    async def try_token(self, user, token):
        refresh = []
        try:
            with connection.cursor() as cursor:
                sql = ("SELECT NOW() < TIMESTAMPADD(MINUTE, %s, issued) "
                       "AS valid, user_id FROM xf_da_token "
                       "WHERE token = %s")
                cursor.execute(sql, (self.config['token_timeout'], token))
                if cursor.rowcount == 1:
                    row = cursor.fetchone()
                    valid = bool(row['valid'])
                    user_id = row['user_id']

                    # Invalidate token
                    sql = "DELETE FROM xf_da_token WHERE token = %s"
                    cursor.execute(sql, (token,))
                    connection.commit()

                    if not valid:
                        await self.send_message(user, "This token is expired.")
                        return
                else:
                    await self.send_message(user, "This token is not valid.")
                    connection.rollback()
                    return

                # Check if this user is already linked to another accont
                sql = "SELECT username FROM xf_user WHERE da_discord_id = %s"
                cursor.execute(sql, (user.id,))
                if cursor.rowcount:
                    username = cursor.fetchone()['username']
                    await self.send_message(user, "This Discord account is "
                                            "already linked to '{}'."
                                            "".format(username))
                    connection.rollback()
                    return

                # Check if another user is already linked to this account
                sql = ("SELECT da_discord_id FROM xf_user "
                       "WHERE user_id = %s AND da_discord_id IS NOT NULL")
                cursor.execute(sql, (user_id,))
                if cursor.rowcount:
                    refresh.append(cursor.fetchone()['da_discord_id'])

                # Link this discord user to the account indicated by the token
                sql = ("UPDATE xf_user SET da_discord_id = %s "
                       "WHERE user_id = %s")
                cursor.execute(sql, (user.id, user_id))
                connection.commit()

                refresh.append(user.id)

        finally:
            for user_id in refresh:
                await self.refresh_id(user_id)

        await self.send_message(user, "Authorisation successful.")

    def mapped_roles(self, member, row):
        if row['is_banned']:
            return set()

        mapping = self.config['group_mapping']
        override = self.config['group_override']
        managed_roles = set(mapping.values())
        forum_ids = set([row['user_group_id']])
        if row['secondary_group_ids']:
            try:
                forum_ids |= set(map(int, row['secondary_group_ids']
                                     .split(b',')))
            except Exception as e:
                logging.error("Parsing group ids '{}' on discord user {} "
                              "failed.".format(row['secondary_group_ids'],
                                               member.id))
        override_ids = {oid for fid, overrides in override.items()
                            if fid in forum_ids for oid in overrides}
        forum_ids = {id for id in forum_ids if id not in override_ids}
        have_ids = {mapping[i] for i in forum_ids if i in mapping}

        keep = [r for r in member.roles if r.id not in managed_roles]
        have = [r for r in self.bot_server.roles if r.id in have_ids]
        return set(keep) | set(have)


    async def sync_database(self):
        if not self.is_logged_in:
            return

        with connection.cursor() as cursor:
            sql = ("SELECT da_discord_id, user_group_id, secondary_group_ids, "
                   "is_banned FROM xf_user WHERE da_discord_id IS NOT NULL")
            cursor.execute(sql)
            accounts = {row['da_discord_id']: row for row in cursor.fetchall()}

        connection.rollback()

        changes = 0
        managed_roles = set(self.config['group_mapping'].values())

        for member in self.bot_server.members:
            if member.id in accounts:
                row = accounts[member.id]
                roles = self.mapped_roles(member, row)
                if roles != set(member.roles):
                    await self.replace_roles(member, *roles)
                    changes += 1

            else:
                roles = [r for r in member.roles if r.id in managed_roles]
                if roles:
                    await self.remove_roles(member, *roles)
                    changes += 1

        return changes

    async def on_sync_database(self):
        await self.sync_database()

    @command
    async def sync(self):
        """Trigger a database syncronisation"""
        changes = await self.sync_database()
        if changes:
            return "{} user{} updated.".format(changes, 's'*(changes != 1))
        else:
            return "No changes."

    async def refresh_id(self, user_id):
        """Refresh the authorizations given to a user"""
        member = utils.find(lambda u: u.id == user_id, self.bot_server.members)
        if member is not None:
            managed_roles = set(self.config['group_mapping'].values())

            with connection.cursor() as cursor:
                sql = ("SELECT user_group_id, secondary_group_ids, is_banned "
                       "FROM xf_user WHERE da_discord_id = %s")
                cursor.execute(sql, (user_id,))
                row = cursor.fetchone()
                connection.rollback()

            if row is not None:
                # Get managed roles for the member and update if needed
                roles = self.mapped_roles(member, row)
                if roles != set(member.roles):
                    await self.replace_roles(member, *roles)
            else:
                # Member is not registered, remove all managed roles
                roles = [r for r in member.roles if r.id in managed_roles]
                if roles:
                    await self.remove_roles(member, *roles)

    async def on_refresh_id(self, user_id):
        await self.refresh_id(user_id)

    @command
    async def help(self, what: str=None, *,  author: User):
        """Show this help text."""
        role = self.get_role(author)
        if role == 'master':
            commands = get_commands(self)
        elif role == 'admin':
            commands = self.config['admin_commands']
        elif role == 'user':
            commands = self.config['user_commands']

        text = "Available commands:\n"
        for command in sorted(commands):
            if getattr(self, command).is_hidden: continue
            params = []
            for param in signature(getattr(self, command)).parameters.values():
                if (param.kind != param.POSITIONAL_OR_KEYWORD
                        and param.kind != param.VAR_POSITIONAL):
                    continue
                optional = '...' if param.kind == param.VAR_POSITIONAL else ''
                if param.default is param.empty:
                    fmt = '{{{{{{}}{}}}}} '.format(optional)
                else:
                    fmt = '[{{}}{}] '.format(optional)
                if param.annotation is not param.empty:
                    msg ='{}: {}'.format(param.name, param.annotation.__name__)
                    params.append(fmt.format(msg))
                else:
                    params.append(fmt.format(param.name))

            params = ''.join(params)
            doc = getattr(self, command).__doc__
            trigger = self.config['trigger']
            text += "{}{} {}- {}\n".format(trigger, command, params, doc)

        return text

    @command
    async def whois(self, *who: Member):
        """Tell who a user is."""
        if not who: return
        names = []
        with connection.cursor() as cursor:
            for user in who:
                if user == self.user:
                    names.append('**{}**'.format(config['bot_name']))
                    continue

                sql = "SELECT username FROM xf_user WHERE da_discord_id = %s"
                cursor.execute(sql, (user.id,))
                if cursor.rowcount:
                    names.append(cursor.fetchone()['username'])
                else:
                    names.append("*not registered*")

        connection.rollback()
        whois_list = ("{} is {}".format(u.name, f) for u, f in zip(who, names))
        return "\n".join(whois_list)

    properties = {
        "admins": {
            "type": set,
            "convert": Member,
            "key": lambda u: u.id,
        },
        "admin_roles": {
            "type": set,
            "convert": Role,
            "key": lambda u: u.id,
        },
        "user_commands": {
            "type": set,
            "check": "command",
        },
        "admin_commands": {
            "type": set,
            "check": "command",
        },
        "group_mapping": {
            "type": dict,
            "key-convert": int,
            "value-convert": Role,
            "value-key": lambda r: r.id,
        },
        "group_override": {
            "type": dict,
            "key-convert": int,
            "value-convert": int,
            "value-key": lambda l: set(l),
            "list": True,
        }
    }

    @command
    async def add(self, prop: str, *values, server: Server):
        """Add items to a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)

        desc = self.properties[prop]
        if desc['type'] != set:
            return "{} is not an addable property".format(prop)

        additions = set()
        for value in values:
            if 'check' in desc:
                if desc['check'] == 'command':
                    if not is_command(getattr(self, value, None)):
                        raise ValueError("{} is not a command.".format(value))
                else:
                    raise TypeError("Uknown check '{}'.".format(desc['check']))
            if 'convert' in desc:
                value = convert(server, 'value', desc['convert'], value)
            if 'key' in desc:
                value = desc['key'](value)
            additions.add(value)

        self.config[prop].update(additions)

        return "Added ({}) to {}.".format(", ".join(additions), prop)

    @command
    async def remove(self, prop: str, *values, server: Server):
        """Remove items from a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)

        desc = self.properties[prop]
        if desc['type'] != set:
            return "{} is not an removable property".format(prop)

        removals = set()
        for value in values:
            if 'convert' in desc:
                value = convert(server, 'value', desc['convert'], value)
            if 'key' in desc:
                value = desc['key'](value)
            removals.add(value)

        self.config[prop].difference_update(removals)

        return "Removed ({}) from {}.".format(", ".join(removals), prop)

    @command
    async def bind(self, prop: str, key, *value, server: Server):
        """Bind a value to a key in a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)

        desc = self.properties[prop]
        if desc['type'] != dict:
            return "{} is not a bindable property".format(prop)

        if 'key-convert' in desc:
            key = convert(server, 'key', desc['key-convert'], key)

        if 'value-convert' in desc:
            value = [convert(server, 'value', desc['value-convert'], v)
                         for v in value]

        if not desc.get('list', False):
            if len(value) == 1:
                value = value[0]
            else:
                return "Extranous parameters"

        if 'value-key' in desc:
            value = desc['value-key'](value)

        self.config[prop][key] = value

        return "Bound {} to {} in {}.".format(value, key, prop)

    @command
    async def unbind(self, prop: str, key):
        """Remove a key value pair in a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)

        desc = self.properties[prop]
        if desc['type'] != dict:
            return "{} is not an unbindable property".format(prop)

        if 'key-convert' in desc:
            key = convert(server, 'value', desc['key-convert'], key)

        del self.config[prop][key]

        return "Removed {} from {}.".format(key, prop)

    @command
    async def show(self, prop: str):
        """Show a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)
        else:
            return str(self.config[prop])

    @command(hidden=True)
    async def debug(self, *code: str, author: User, msg: Message, ch: Channel):
        """Evaluate an arbitrary python expression"""
        try:
            await self.send_message(ch, eval(' '.join(code)))
        except Exception as e:
            await self.send_message(ch, '{}: {}.'.format(type(e).__name__, e))

    @command(hidden=True)
    async def hack(self, *, author: User):
        import random

        return random.choice([
            "{} is now a **god**".format(author.name),
            "Promoted {} to admin".format(author.name),
            "Backdoor installed.",
            "Inz k3n3l r00tkit =D",
            "You have been reported.",
            "This bot has no backdoors.",
            "44 65 63 6F 64 65 20 74 68 69 73 !",
            "I'm sorry Dave, I'm afraid I can't do that.",
            "The Internet police has been notified.",
        ])

class DatagramHandler(BaseRequestHandler):
    def handle(self):
        request = json.loads(self.request[0].decode('utf-8'))
        if request['action'] == 'refresh':
            self.server.bot.dispatch('refresh_id', request['user_id'])
        else:
            logging.warning("Unkown request '{}'.".format(json.dumps(request)))

class SocketServer(Thread):
    def __init__(self, bot, config):
        Thread.__init__(self, daemon=True)
        self.bot = bot
        self.config = config

    def run(self):
        try:
            server = UnixDatagramServer(self.config['socket'], DatagramHandler)
            server.bot = self.bot
            atexit.register(os.unlink, self.config['socket'])
            server.serve_forever()

        except Exception:
            logging.exception("Exception occured while running SocketServer")

        except BaseException as e:
            self.bot.dispatch('raise_exception', e)

        # We should not normaly reach this point
        logging.error("SocketServer closed!")

def write_config(config):
    config_file = open('config.py', 'w')
    lines = ['    {!r}: {!r},'.format(k, config[k]) for k in sorted(config)]
    config_file.write('\n'.join(['# ForumBot config', '{']+lines+['}']))
    config_file.close()

if __name__ == '__main__':
    global connection
    config = eval(open('config.py').read())
    logging.basicConfig(level=logging.INFO)
    connection = pymysql.connect(host=config['db_host'],
                                 user=config['db_user'],
                                 password=config['db_password'],
                                 db=config['db_schema'],
                                 charset='utf8mb4',
                                 cursorclass=pymysql.cursors.DictCursor)

    bot = ForumBot(config)

    server = SocketServer(bot, config)
    server.start()

    loop = get_event_loop()

    while True:
        try:
            task = bot.login(config['bot_token'])
            loop.run_until_complete(task)

        except (HTTPException, ClientError):
            logging.exception("Failed to log in to Discord")
            loop.run_until_complete(sleep(10))

        else:
            break

    while not bot.is_closed:
        try:
            loop.run_until_complete(bot.sane_connect())

        except (HTTPException, ClientError, GatewayNotFound,
                InvalidHandshake, WebSocketProtocolError, ConnectionClosed):
            logging.exception("Lost connection with Discord")
            loop.run_until_complete(sleep(10))

        finally:
            write_config(config)
