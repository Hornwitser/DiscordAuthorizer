import atexit
from inspect import signature
import json
import logging
import os
from socketserver import UnixDatagramServer, BaseRequestHandler
from threading import Thread

from discord import Channel, Client, Member, Role, Server, User, utils
import pymysql

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

    def get_role(self, member):
        if member.id in self.config['masters']:
            return 'master'
        elif member.id in self.config['admins']:
            return 'admin'
        elif any((r.id in self.config['admin_roles'] for r in member.roles)):
            return 'admin'
        elif member.id in self.config['ignores']:
            return 'ignore'
        else:
            return 'user'

    @property
    def bot_server(self):
        return utils.find(lambda s: s.id == self.config['server'],
                          self.servers)

    @property
    def auth_role(self):
        return utils.find(lambda r: r.id == self.config['role'],
                          self.bot_server.roles)

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

    def on_message(self, msg):
        if msg.author == self.user:
            return

        elif msg.channel.is_private:
            if msg.author in self.bot_server.members:
                token = msg.content.strip()
                if len(token) == 16:
                    self.try_token(msg.author, token)
                else:
                    self.send_message(msg.channel, "That does not look like "
                                      "an access token.")
            else:
                if msg.channel.id not in self.informed:
                    self.send_message(msg.channel, "I am a bot and I don't "
                                      "serve you.")
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
                    response = invoke_command(func, msg, args)
                except Exception as e:
                    self.send_message(msg.channel, "Error: {}".format(e))
                else:
                    if response is not None:
                        self.send_message(msg.channel, response)

            elif action == 'deny':
                self.send_message(msg.channel, "You do not have permission to "
                                  "use this command.")

    def on_member_join(self, member):
        with connection.cursor() as cursor:
            sql = "SELECT username FROM xf_users WHERE discord_id = %s"
            cursor.execute(sql, (member.id,))
            if cursor.rowcount:
                # Query database and check for additional roles to set
                self.add_roles(member, self.auth_role)
            connection.rollback()

    def try_token(self, user, token):
        with connection.cursor() as cursor:
            sql = ("SELECT NOW() < TIMESTAMPADD(MINUTE, %s, issued) AS valid, "
                   "user_id FROM discord_tokens WHERE token = %s")
            cursor.execute(sql, (self.config['token_timeout'], token))
            if cursor.rowcount == 1:
                row = cursor.fetchone()
                valid = bool(row['valid'])
                user_id = row['user_id']

                # Invalidate token
                sql = "DELETE FROM discord_tokens WHERE token = %s"
                cursor.execute(sql, (token,))
                connection.commit()

                if not valid:
                    self.send_message(user, "This token has expired.")
                    return
            else:
                self.send_message(user, "This token is not valid.")
                connection.rollback()
                return

            # Check if this discord user is already linked to another accont
            sql = "SELECT username FROM xf_users WHERE discord_id = %s"
            cursor.execute(sql, (user.id,))
            if cursor.rowcount:
                username = cursor.fetchone()['username']
                self.send_message(user, "This Discord account is already "
                                  "linked to '{}'.".format(username))
                connection.rollback()
                return

            # Check if another discord user is already linked to this account
            sql = "SELECT discord_id FROM xf_users WHERE user_id = %s"
            cursor.execute(sql, (user_id,))
            if cursor.rowcount:
                self.revoke_id(cursor.fetchone()['discord_id'])

            # Link this discord user to the account indicated by the token
            sql = "UPDATE xf_users SET discord_id = %s WHERE user_id = %s"
            cursor.execute(sql, (user.id, user_id))
            connection.commit()

        self.authorize_id(user.id)
        self.send_message(user, "Authorisation successful.")

    def sync_database(self):
        if not self.is_logged_in:
            return

        with connection.cursor() as cursor:
            sql = ("SELECT discord_id FROM xf_users "
                   "WHERE discord_id IS NOT NULL")
            cursor.execute(sql)
            authorized_ids = {r['discord_id'] for r in cursor.fetchall()}

        connection.rollback()

        changes = 0
        auth_role = self.auth_role
        for member in self.bot_server.members:
            if member.id in authorized_ids:
                if auth_role not in member.roles:
                    self.add_roles(member, auth_role)
                    changes += 1

            else:
                if auth_role in member.roles:
                    self.remove_roles(member, auth_role)
                    changes += 1

        return changes

    def on_sync_database(self):
        self.sync_database()

    @command
    def sync(self):
        """Trigger a database syncronisation"""
        changes = self.sync_database()
        if changes:
            return "{} user{} updated.".format(changes, 's'*(changes != 1))
        else:
            return "No changes."

    def revoke_id(self, user_id):
        """Revoke the authorization given to a user"""
        user = utils.find(lambda u: u.id == user_id, self.bot_server.members)
        if user is not None:
            # Remove additional roles that may have been granted
            self.remove_roles(user, self.auth_role)

    def on_revoke_id(self, user_id):
        self.revoke_id(user_id)

    def authorize_id(self, user_id):
        user = utils.find(lambda u: u.id == user_id, self.bot_server.members)
        if user is not None:
            # Query database and check for additional roles to set
            self.add_roles(user, self.auth_role)

    @command
    def help(self, what: str=None, *,  author: User):
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
                    params.append(fmt.format(param.annotation.__name__))
                else:
                    params.append(fmt.format(param.name))

            params = ''.join(params)
            doc = getattr(self, command).__doc__
            trigger = self.config['trigger']
            text += "{}{} {}- {}\n".format(trigger, command, params, doc)

        return text

    @command
    def whois(self, who: Member):
        """Tell who a user is."""
        with connection.cursor() as cursor:
            sql = "SELECT username FROM xf_users WHERE discord_id = %s"
            cursor.execute(sql, (who.id,))
            if cursor.rowcount:
                username = cursor.fetchone()['username']
            else:
                username = "*not registered*"

        connection.rollback()
        return "{} is {}".format(who.name, username)

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
        }
    }

    @command
    def add(self, prop: str, *values, server: Server):
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
    def remove(self, prop: str, *values, server: Server):
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
    def show(self, prop: str):
        """Show a property"""
        if prop not in self.properties:
            return "{} is not a property".format(prop)
        else:
            return str(self.config[prop])

    @command
    def debug(self, *code: str, channel: Channel):
        """Evaluate an arbitrary python expression"""
        try:
            self.send_message(channel, eval(' '.join(code)))
        except Exception as e:
            self.send_message(channel, '{}: {}.'.format(type(e).__name__, e))

class DatagramHandler(BaseRequestHandler):
    def handle(self):
        request = json.loads(self.request[0].decode('utf-8'))
        if request['action'] == 'revoke':
            self.server.bot.dispatch('revoke_id', request['user_id'])
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
            logging.exception('Exception occured while running SocketServer')

        except BaseException as e:
            self.bot.dispatch('raise_exception', e)

        # We should not normaly reach this point
        logging.error('SocketServer closed!')

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
    bot.login(config['bot_user'], config['bot_password'])

    server = SocketServer(bot, config)
    server.start()

    try:
        bot.run()
    finally:
        write_config(config)
