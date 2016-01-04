from inspect import getattr_static, signature

from discord import Channel, Member, Message, Role, Server, User, utils


class _Literal:
    def __init__(self, characters):
        self.characters = ''
        for char in characters:
            if isinstance(char, _Literal):
                self.characters += char.characters
            else:
                self.characters += char

def split(string):
    """Parse a string into an argument list

    Splits a string of optionally quoted arguments into a list of words
    using a 3 stage process.  Escapes are done with a '\' character and
    it's effect is to turn the next character into a literal with no
    special meaning.  Quotes are then stripped out, and the content
    inside them is preserved, finally whitespace sepparates words.  Note
    that quoted text adjacant non-whitespace or escaped literal is not
    split up into separate words.

    Example: The string 'Augment\ this  "string"_\"battle\" ' is parsed
             into the list ['Augment this', 'string_"battle"'].

    """

    # Turn into a list of characters
    array = list(map(str, string))

    # Turn escaped characters into character literals
    escaped = []
    while array:
        item = array.pop(0)
        if item == '\\' and array:
            escaped.append(_Literal(array.pop(0)))
        else:
            escaped.append(item)

    # Turn quoted string into word literals.
    quoted = []
    while escaped:
        item = escaped.pop(0)
        if item == '"':
            word = []
            while escaped:
                item = escaped.pop(0)
                if item =='"':
                    quoted.append(_Literal(word))
                    break
                else:
                    word.append(item)
            else:
                raise ValueError("unmatched quote")
        else:
            quoted.append(item)

    # Join adjacent sequences of literals and characters not
    # separated by blanks.
    split = []
    word = []
    while quoted:
        item = quoted.pop(0)
        if item != " " and item != "\t":
            word.append(item)
        elif word:
            split.append(_Literal(word))
            word.clear()
    if word:
        split.append(_Literal(word))

    # Turn the sequence of literals into a list of strings
    return list(map(lambda l: l.characters, split))

def command(func=None, **kwargs):
    def dec(func):
        func.is_command = True
        func.is_hidden = kwargs.get('hidden', False)
        return func

    return dec if func is None else dec(func)

def is_command(func):
    return getattr(func, "is_command", False)

def get_commands(obj):
    return [name for name in dir(obj) if is_command(getattr_static(obj, name))]

def convert(server, name, type_,  value):
    if type_ is Channel:
        if value.startswith('<#') and value.endswith('>'):
            cid = value[2:-1]
        elif value.strip('0123456789') == '':
            cid = value
        else:
            raise ValueError("'{}' is not a channel".format(value))

        channel = utils.find(lambda c: c.id == cid, server.channels)
        if channel is None:
            raise ValueError("Channel {} not found".format(value))

        return channel

    elif type_ is Member:
        if value.startswith('<@') and value.endswith('>'):
            uid = value[2:-1]
            member = utils.find(lambda u: u.id == uid, server.members)
            if member is None:
                raise ValueError("Member {} not found".format(value))

            return member
        else:
            matches = []
            full_matches = []
            for member in server.members:
                if value == member.id:
                    return member
                elif value == member.name:
                    full_matches.append(member)
                elif value.lower() in member.name.lower():
                    matches.append(member)
            else:
                if len(full_matches) == 1:
                    return full_matches[0]
                elif full_matches:
                    raise ValueError("Multiple members Matched")
                elif len(matches) == 1:
                    return matches[0]
                elif matches:
                    raise ValueError("Multiple members matched")
                else:
                    raise ValueError("Member '{}' not found".format(value))

    elif type_ is Role:
        matches = []
        for role in server.roles:
            if role.name == value:
                return role
            elif value.lower() in role.name.lower():
                matches.append(role)
        else:
            if len(matches) == 1:
                return matches[0]
            elif matches:
                raise ValueError("Multiple roles matched")
            else:
                raise ValueError("Role not found")

    elif type_ in (int, float, str):
        return(type_(value))

    else:
        raise TypeError("Unknown type '{}'".format(type_))

def convert_param(server, param, value):
    if param.kind == param.KEYWORD_ONLY:
        raise TypeError("Can not handle keyword-only arguments")

    if param.annotation is param.empty:
        return value
    else:
        return convert(server, param.name, param.annotation, value)

def parameters(func):
    for param in signature(func).parameters.values():
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            yield param
        elif param.kind == param.VAR_POSITIONAL:
            while True:
                yield param

    raise TypeError("Extraneous parameters")

def invoke_command(func, msg, args):
    args = [convert_param(msg.server, param, value) for value, param
                in zip(args, parameters(func))]

    kwargs = {}
    for param in signature(func).parameters.values():
        if param.kind == param.KEYWORD_ONLY:
            if param.annotation is User:
                kwargs[param.name] = msg.author
            elif param.annotation is Member:
                if msg.channel.is_private:
                    raise ValueError("Private channels does not have Member")
                kwargs[param.name] = msg.author
            elif param.annotation is Channel:
                kwargs[param.name] = msg.channel
            elif param.annotation is Server:
                if msg.channel.is_private:
                    raise ValueError("Private channels does not have Server")
                kwargs[param.name] = msg.server
            elif param.annotation is Message:
                kwargs[param.name] = msg

    return func(*args, **kwargs)
