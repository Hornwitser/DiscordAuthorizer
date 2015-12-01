import logging

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
        for k, v in ForumBot.__dict__.items():
            if hasattr(v, 'command'):
                self.commands.append(k)

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

    def get_server(self):
         return utils.find(lambda s: s.id == self.config['server'],
                           self.servers)

    def on_message(self, msg):
        if msg.author == self.user:
            return

        elif msg.channel.is_private:
            if msg.author in self.get_server().members:
                token = msg.content.strip()
                if len(token) == 16:
                    self.try_token(msg.author, token)
                else:
                    self.send_message(msg.channel, "That does not look like "
                                      "an access token")
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

            elif msg.channel.server.id not in config['server']:
                return

            elif (role == 'admin' and cmd in self.config['admin_commands']
                  or role == 'user' and cmd in self.config['user_commands']):
                func(msg, arg)

            elif role != 'ignore' and self.config['noisy_deny']:
                self.send_message(msg.channel, "You do not have permission to "
                                  "use this command.")

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
            else:
                valid = False


        if valid:
            self.send_message(user, "Your token was valid!")
            # add role to user, revoke old user, etc
        else:
            self.send_message(user, "This token is not valid")

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


    def add_field(self, field, field_type, channel, argument):
        if argument is None:
            self.send_message(channel, "Error: missing argument")

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
                self.send_message(channel, "Added commands {}".format(cmds))
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
            self.send_message(channel, "Error: missing argument")

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
                              '{} {}'.format(type(e).__name__, e))


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
    try:
        bot.run()
    finally:
        write_config(config)
