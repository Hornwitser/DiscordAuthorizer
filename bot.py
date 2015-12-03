import atexit
import json
import logging
import os
from socketserver import UnixDatagramServer, BaseRequestHandler
from threading import Thread, Event

from discord import Client, utils
import pymysql


def command(func):
    func.command = None
    return func


class ForumBot(Client):
    def __init__(self, config):
        Client.__init__(self)
        self.config = config
        self.commands = []
        self.informed = set()
        self.exception = None
        for k, v in ForumBot.__dict__.items():
            if hasattr(v, 'command'):
                self.commands.append(k)

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
            if not msg.content.startswith(self.config['trigger']): return

            line = msg.content[len(self.config['trigger']):]
            if ' ' in line:
                cmd, arg = line.split(' ', 1)
            else:
                cmd, arg = line, None

            if cmd not in self.commands: return
            func = getattr(self, cmd)

            role = self.get_role(msg.author)
            if role == 'master':
                func(msg, arg)

            elif msg.channel.server.id != config['server']:
                return

            elif (role == 'admin' and cmd in self.config['admin_commands']
                  or role == 'user' and cmd in self.config['user_commands']):
                func(msg, arg)

            elif role != 'ignore' and self.config['noisy_deny']:
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

    @command
    def sync(self, message, argument):
        """- Trigger a database syncronisation"""
        changes = self.sync_database()
        if changes:
            msg = "{} user{} updated.".format(changes, 's'*(changes != 1))
        else:
            msg = "No changes."

        self.send_message(message.channel, msg)

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
    def help(self, message, argument):
        """- Show this help text."""
        role = self.get_role(message.author)
        if role == 'master':
            commands = self.commands
        elif role == 'admin':
            commands = self.config['admin_commands']
        elif role == 'user':
            commands = self.config['user_commands']

        text = "Available commands:\n"
        for command in sorted(commands):
            text += "{} {}\n".format(command, getattr(self, command).__doc__)
        self.send_message(message.channel, text)

    @command
    def whois(self, message, argument):
        matches = []
        for member in message.channel.server.members:
            if member.name == argument:
                matches.append(member)

        if matches:
            with connection.cursor() as cursor:
                names = []
                for member in matches:
                    sql = "SELECT username FROM xf_users WHERE discord_id = %s"
                    cursor.execute(sql, (member.id,))
                    if cursor.rowcount:
                        username = cursor.fetchone()['username']
                        names.append(username)
                    else:
                        names.append('*User not found*')
            connection.rollback()
            msg = '\n'.join(["{} is {}.".format(m.name, u)
                                 for m, u in zip(matches, names)])
            self.send_message(message.channel, msg)
        else:
            self.send_message(message.channel, "No match for '{}'."
                              "".format(argument))

    def add_field(self, field, field_type, channel, argument):
        if argument is None:
            self.send_message(channel, "Error: missing argument.")

        elif field_type == 'user':
            users = [u.id for u in argument]
            if len(users):
                self.config[field].update(users)
                names = ', '.join([u.name for u in argument])
                self.send_message(channel, "Added users {}.".format(names))
            else:
                self.send_message(channel, "No users mentioned to add.")

        elif field_type == 'command':
            commands = set(argument.split(' ')).intersection(self.commands)
            if len(commands):
                self.config[field].update(commands)
                cmds = ", ".join(commands)
                self.send_message(channel, "Added commands {}.".format(cmds))
            else:
                self.send_message(channel, "No matching commands to add.")

        elif field_type == 'role':
            roles = channel.server.roles
            name = argument.lower()
            matching_roles = [r for r in roles if name in r.name.lower()]
            if len(matching_roles) == 1:
                self.config[field].update([matching_roles[0].id])
                name = matching_roles[0].name
                self.send_message(channel, "Added role {}.".format(name))
            elif len(matching_roles) == 0:
                self.send_message(channel, "No roles matched {}.".format(name))
            else:
                names = ', '.join([r.name for r in matching_roles])
                self.send_message(channel, "Which one? {}.".format(names))

    def remove_field(self, field, field_type, channel, argument):
        if argument is None:
            self.send_message(channel, "Error: missing argument.")

        elif field_type == 'user':
            users = [u.id for u in argument]
            if len(users):
                self.config[field].difference_update(users)
                names = ', '.join([u.name for u in argument])
                self.send_message(channel, "Removed users {}.".format(names))
            else:
                self.send_message(channel, "No users mentioned to remove.")

        elif field_type == 'command':
            commands = set(argument.split(' ')).intersection(self.commands)
            if len(commands):
                self.config[field].difference_update(commands)
                cmds = ", ".join(commands)
                self.send_message(channel, "Removed commands {}.".format(cmds))
            else:
                self.send_message(channel, "No matching commands to remove.")

        elif field_type == 'role':
            roles = channel.server.roles
            name = argument.lower()
            matching_roles = [r for r in roles if name in r.name.lower()]
            if len(matching_roles) == 1:
                self.config[field].difference_update([matching_roles[0].id])
                name = matching_roles[0].name
                self.send_message(channel, "Removed role {}.".format(name))
            elif len(matching_roles) == 0:
                self.send_message(channel, "No roles matched {}.".format(name))
            else:
                names = ', '.join([r.name for r in matching_roles])
                self.send_message(channel, "Which one? {}".format(names))

    @command
    def add_admin(self, message, argument):
        """{user} ... - Add mentioned users to list of admins."""
        self.add_field('admins', 'user', message.channel, message.mentions)

    @command
    def remove_admin(self, message, argument):
        """{user} ... - Remove mentioned users from list of admins."""
        self.remove_field('admins', 'user', message.channel, message.mentions)

    @command
    def add_admin_role(self, message, argument):
        """{role} - Add role to admin role list."""
        self.add_field('admin_roles', 'role', message.channel, argument)

    @command
    def remove_admin_role(self, message, argument):
        """{role} - Remove role from admin role list."""
        self.remove_field('admin_roles', 'role', message.channel, argument)

    @command
    def add_user_command(self, message, argument):
        """{command} ... - Add command(s) to user command list."""
        self.add_field('user_commands', 'command', message.channel, argument)

    @command
    def remove_user_command(self, message, argument):
        """{command} ... - Remove command(s) from user command list."""
        self.remove_field('user_commands', 'command',
                          message.channel, argument)

    @command
    def add_admin_command(self, message, argument):
        """{command} ... - Add command(s) to admin command list."""
        self.add_field('admin_commands', 'command', message.channel, argument)

    @command
    def remove_admin_command(self, message, argument):
        """{command} ... - Remove command(s) from admin command list."""
        self.remove_field('admin_commands', 'command',
                          message.channel, argument)

    @command
    def debug(self, message, argument):
        """{python expression} - Evaluate an arbitrary python expression"""
        try:
            self.send_message(message.channel, eval(argument))
        except Exception as e:
            self.send_message(message.channel,
                              '{}: {}.'.format(type(e).__name__, e))

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
