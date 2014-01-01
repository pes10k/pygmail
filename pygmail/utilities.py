"""Functions for interacting with the toranado IO loop and parsing responses
from the imaplib2 library"""

import logging
import time
from datetime import timedelta

def extract_first_bodystructure(structure):
    stack = 0
    index = 0
    for i in structure:
        if i == "(":
            stack += 1
        elif i == ")":
            stack -= 1
        index += 1
        if stack == 0:
            return structure[:index]
    return None


def extract_data(imap_response):
    """Returns the data section the tuple returned from an imaplib2 request.
    This function assumes that the given tuple is in the correct format
    return from an imaplib2 call: ((typ, data), cb_arg, error)

    Args:
        imap_response -- The tuple returned from an imaplib2 request

    Returns:
        The data portion of the imaplib2 request
    """
    if len(imap_response) == 3:
        return imap_response[0][1]
    else:
        return imap_response[1]


def extract_type(imap_response):
    """Returns the IMAP response type from a imaplib2 raw imap response. This
    should be "NO", "OK", "BAD", "PREAUTH", or "BYE"

    Args:
        imap_response -- The tuple returned from an imaplib2 request

    Returns:
        The type portion of the imaplib2 request
    """
    if len(imap_response) == 3:
        return imap_response[0][0]
    else:
        return imap_response[0]


def schedule_func(func, secs=None):
    """Schedules a function for future calling on the event loop.  Currently
    the only event loop supported is the tornado one.

    Args:
        func -- the function to schedule for execution

    Keyword Args:
        secs -- The number of seconds in the future that the function should
                be called on. If None, "func" function is schedule for execution
                ASAP
    """
    import tornado
    io_loop = tornado.ioloop.IOLoop.instance()
    if secs:
        io_loop.add_timeout(timedelta(seconds=secs), func)
    else:
        io_loop.add_callback(func)


def _log(msg, log_name="tornado.application"):
    """Simple point of indirection to handle all logging code in one place,
    to further lessen dependence on Tornado

    Args:
        msg -- the message to log

    Keyword Args:
        log_name -- the name of the system logger to send messages to
    """
    logging.getLogger(log_name).error(msg)


def _cmd_in(func, secs, is_async, *args, **kwargs):
    """Calls a function in a given amount of time, either by sleeping / blocking
    the thread, or by scheduling a callback on the event loop.  This funciton is
    used as the point of indirection to support both async and blocking
    functionality.

    Note that the unnamed arguments and keyword arguments will be provided
    as arguments to the main function being called

    Args:
        func        -- the main function that should be called
        secs        -- the number of seconds to wait before the "func" function
                       is called
        is_async    -- truth-y value, describing whether the function should
                       be called asyncronously (in the event loop) or
                       syncronously / blocking
    """
    if is_async:
        schedule_func(lambda: func(*args, **kwargs), secs)
    else:
        time.sleep(secs)
        return func(*args, **kwargs)


def _cmd(func=None, arg=None):
    """Point of indirection where a function is either called immediatly (with)
    the provided arguments (when called in blocking mode), or scheduled for
    future calling on the event loop (in async mode).

    Note that the unnamed arguments and keyword arguments will be provided
    as arguments to the main function being called, NOT the callback function

    Args:
        func        -- the main function that should be called

    Keyword Args:
        is_async      -- truth-y value, describing whether the function should
                         be called asyncronously (in the event loop) or
                         syncronously / blocking
    Returns:
        If being called asyncronously, nothing is returned.  If called
        syncronously, the result of the "func" function is returned
    """
    if func:
        cb = lambda: func(arg)
        schedule_func(cb)
    else:
        return arg


def _cmd_cb(main_func, callback, is_async, *args, **kwargs):
    """Point of indirection where a function is called asyncronously (if were'
    operating in the event loop) or syncronously (if we're being called
    otherwise)

    Note that the unnamed arguments and keyword arguments will be provided
    as arguments to the main function being called, NOT the callback function

    Args:
        main_obj    -- the main object to call a method on.
        main_func   -- the main function that should be called, usually a
                       method on "main_obj".
        callback    -- the function that should receive the result of the
                       func function
        is_async    -- truth-y value, describing whether the function should
                       be called asyncronously (in the event loop) or
                       syncronously / blocking

    Keyword Args:
        callback_args -- a dictionary of values that should be passed as the
                         second argument to the callback function

    Returns:
        If being called asyncronously, nothing is returned.  If called
        syncronously, the result of the "func" function is returned
    """
    if "callback_args" in kwargs:
        callback_args = kwargs['callback_args']
        del kwargs['callback_args']
    else:
        callback_args = {}

    if is_async:
        if callback_args:
            callback_func = lambda res: schedule_func(lambda: callback(res, **callback_args))
        else:
            callback_func = lambda res: schedule_func(lambda: callback(res))

        kwargs['callback'] = callback_func
        main_func(*args, **kwargs)
    else:
        if callback_args:
            return callback(main_func(*args, **kwargs), **callback_args)
        else:
            rs = main_func(*args, **kwargs)
            return callback(rs)


### Parsing Utilities, "adapted" from
### http://pydoc.net/Python/gocept.imapapi/0.5/gocept.imapapi.parser/

"""Parsing IMAP responses."""

def iterate_pairs(iterable):
    iterable = iter(iterable)
    while True:
        yield iterable.next(), iterable.next()


ATOM_CHARS = [chr(i) for i in xrange(32, 256) if chr(i) not in r'(){%*"\ ]']


class ParseError(Exception):
    def __init__(self, msg, data):
        Exception.__init__(self, "%s in '%s' at index %s." %
                           (msg, data.string, data.index))


class LookAheadStringIter(object):
    """String iterator that allows looking one character ahead.

    >>> i = LookAheadStringIter('abxxxcd')
    >>> i.ahead
    'a'
    >>> i.next()
    'a'
    >>> i.ahead
    'b'
    >>> i.next()
    'b'
    >>> i.read(3)
    'xxx'
    >>> i.ahead
    'c'
    >>> i.next()
    'c'
    >>> i.ahead
    'd'
    >>> i.next()
    'd'
    >>> i.ahead
    >>> i.next()
    Traceback (most recent call last):
    StopIteration
    >>> i.read()
    ''
    >>> i.next()
    Traceback (most recent call last):
    StopIteration
    """

    index = 0

    def __init__(self, string):
        self.string = string

    @property
    def ahead(self):
        if self.string is not None:
            try:
                return self.string[self.index]
            except IndexError:
                pass

    def next(self):
        try:
            result = self.string[self.index]
        except IndexError:
            raise StopIteration
        self.index += 1
        return result

    def read(self, count=None):
        if count is None:
            result = self.string[self.index:]
            self.index = len(self.string)
        else:
            result = self.string[self.index:self.index+count]
            self.index += count
        return result

    def __iter__(self):
        return self

_ = LookAheadStringIter


class Atom(object):
    """An IMAP atom.

    Atoms do not know about interpretation of NIL as None and integer literals
    as numbers. Since that is context dependent, these things belong in the
    code calling the parser.

    >>> repr(Atom('foo'))
    '<IMAP atom foo>'

    >>> str(Atom('foo'))
    'foo'

    >>> Atom('NIL')
    <IMAP atom NIL>

    >>> Atom('123')
    <IMAP atom 123>

    """

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        """Test for equality of two atoms.

        >>> Atom('foo') == Atom('bar')
        False

        >>> Atom('foo') == 'foo'
        False

        >>> 'foo' == Atom('foo')
        False

        >>> Atom('foo') == Atom('foo')
        True

        """
        return type(self) is type(other) and self.value == other.value

    def __ne__(self, other):
        """Test for inequality of two atoms.

        >>> Atom('foo') != Atom('bar')
        True

        >>> Atom('foo') != 'foo'
        True

        >>> 'foo' != Atom('foo')
        True

        >>> Atom('foo') != Atom('foo')
        False

        """
        return not self.__eq__(other)

    def __repr__(self):
        return "<IMAP atom %s>" % self.value

    def __str__(self):
        return self.value


class Flag(Atom):
    """An IMAP flag.

    >>> repr(Flag('foo'))
    '<IMAP flag \\\\foo>'

    >>> str(Flag('foo'))
    '\\\\foo'

    """

    def __repr__(self):
        return "<IMAP flag \\%s>" % self.value

    def __str__(self):
        return '\\' + self.value


class AttributeSpec(object):
    """A message attribute specifier: UID, BODY[HEADER.FIELDS (FROM)] etc.
    """

    def __init__(self, primary, msgtext=None, header_list=None, range=None):
        self.primary = primary
        self.msgtext = msgtext
        self.header_list = header_list
        self.range = range

    def __repr__(self):
        return '<AttributeSpec %s>' % self

    def __str__(self):
        result = str(self.primary)
        if self.msgtext is not None:
            if self.header_list is None:
                result += '[%s]' % self.msgtext
            else:
                result += '[%s (%s)]' % (
                    self.msgtext,
                    ' '.join(str(atom) for atom in self.header_list))
        if self.range is not None:
            result += self.range.value
        return result


def read_quoted(data):
    """Read a quoted string from an IMAP response.

    >>> read_quoted(_('"asdf"'))
    'asdf'

    >>> read_quoted(_('"asdf\\\\" " "foo"'))
    'asdf" '

    """
    assert data.next() == '"'
    result = ''
    for c in data:
        if c == '"':
            break
        if c == '\\' and data.ahead in ('"', '\\'):
            c = data.next()
        result += c
    else:
        raise ParseError('Unexpected end of quoted string', data)
    return result


def read_literal(data):
    r"""Read a literal string from an IMAP response.

    >>> read_literal(_('{4}\r\nasdf'))
    'asdf'

    >>> read_literal(_('{4}\r\na\\s\x1adf'))
    'a\\s\x1a'

    >>> read_literal(_('{0}\r\n'))
    ''

    """
    assert data.next() == '{'
    count = ''
    for c in data:
        if c == '}':
            break
        count += c
    if not (data.ahead and data.next() == '\r' and
            data.ahead and data.next() == '\n'):
        raise ParseError('Syntax error in literal string', data)
    try:
        count = int(count)
    except ValueError:
        raise ParseError(
            'Non-integer token for length of literal string', data)

    result = data.read(count)
    if len(result) < count:
        raise ParseError('Unexpected end of literal string', data)
    return result


def read_list(data):
    """Read a parenthesized list from an IMAP response.

    >>> read_list(_('(foo "bar")'))
    [<IMAP atom foo>, 'bar']

    >>> read_list(_('(foo "bar" (baz)) qux'))
    [<IMAP atom foo>, 'bar', [<IMAP atom baz>]]

    """
    assert data.next() == '('
    result = list(parse_recursive(data))
    if not data.ahead or data.next() != ')':
        raise ParseError('Unexpected end of list', data)
    return result


def read_atom(data):
    """Read an atom or attribute specification from an IMAP response.

    Like atoms, this internal function of the parser does not care about NIL
    and integer literals.

    >>> read_atom(_('foo'))
    <IMAP atom foo>

    >>> read_atom(_('bar baz'))
    <IMAP atom bar>

    >>> read_atom(_('NIL'))
    <IMAP atom NIL>

    >>> read_atom(_('123'))
    <IMAP atom 123>

    >>> read_atom(_('BODY[]'))
    <AttributeSpec BODY[]>

    >>> read_atom(_('BODY[HEADER]'))
    <AttributeSpec BODY[HEADER]>

    >>> read_atom(_('BODY[HEADER.FIELDS (FROM)]'))
    <AttributeSpec BODY[HEADER.FIELDS (FROM)]>

    >>> read_atom(_('BODY[HEADER.FIELDS (FROM)]<0>'))
    <AttributeSpec BODY[HEADER.FIELDS (FROM)]<0>>

    """
    assert data.ahead in ATOM_CHARS
    result = ''
    while data.ahead in ATOM_CHARS:
        c = data.next()
        if c == '[':
            break
        else:
            result += c
    else:
        return Atom(result)

    if data.ahead == ']':
        msgtext = ''
    else:
        msgtext = read_atom(data)
    if data.ahead == ' ':
        data.next()
        header_list = read_list(data)
    else:
        header_list = None
    if data.ahead != ']':
        raise ParseError('Unexpected end of header list', data)
    data.next()
    if data.ahead == '<':
        range = read_atom(data)
    else:
        range = None
    return AttributeSpec(result, msgtext, header_list, range)


def read_flag(data):
    """Read a flag from an IMAP response.

    >>> read_flag(_('\\\\Flag'))
    <IMAP flag \\Flag>

    """
    assert data.next() == '\\'
    return Flag(read_atom(data).value)


def parse_recursive(data):
    """Parse an IMAP response until the end of the current nested list.

    This loop is designed in such a way that the read_* functions always
    operate on expressions that include all delimiting characters such as
    quotes, braces and parentheses, and always consume them entirely.

    """
    while True:
        c = data.ahead
        if c == '"':
            yield read_quoted(data)
        elif c == '{':
            yield read_literal(data)
        elif c == '(':
            yield read_list(data)
        elif c == '\\':
            yield read_flag(data)
        elif c in ATOM_CHARS:
            yield read_atom(data)

        c = data.ahead
        if c == ' ':
            data.next()
        elif c in (')', None):
            break
        elif c == '(':
            continue
        else:
            raise ParseError('Syntax error %s' % c, data)


def parse(data):
    r"""Parse an IMAP response with no regard to numerals and NIL.

    >>> parse('')
    []

    >>> parse('foo "bar"')
    [<IMAP atom foo>, 'bar']

    >>> parse('(\\Noselect \\Marked) "/" INBOX/Foo/bar')
    [[<IMAP flag \Noselect>, <IMAP flag \Marked>], '/',
     <IMAP atom INBOX/Foo/bar>]

    >>> parse('''(UID 17 RFC822 {58}\r\n\
    ... From: foo@example.com
    ... Subject: Test
    ...
    ... This is a test mail.
    ...  FLAGS (\\Deleted))''')
    [[<IMAP atom UID>, <IMAP atom 17>, <IMAP atom RFC822>,
     'From: foo@example.com\nSubject: Test\n\nThis is a test mail.\n',
     <IMAP atom FLAGS>, [<IMAP flag \Deleted>]]]

    >>> parse(r'(BODYSTRUCTURE ("TEXT" "PLAIN")("TEXT" "HTML"))')
    [[<IMAP atom BODYSTRUCTURE>, ['TEXT', 'PLAIN'], ['TEXT', 'HTML']]]
    >>> parse(r'(BODYSTRUCTURE ("TEXT" "PLAIN") ("TEXT" "HTML"))')
    [[<IMAP atom BODYSTRUCTURE>, ['TEXT', 'PLAIN'], ['TEXT', 'HTML']]]

    """
    data = LookAheadStringIter(data)
    result = list(parse_recursive(data))
    if data.ahead:
        raise ParseError('Inconsistent nesting of lists', data)
    return result


def astring(value):
    """Interpret a parsed value as an astring.

    An astring is a string that is either represented as a string literal or
    as an atom. It cannot be non-existent.

    >>> astring('foo')
    'foo'

    >>> astring(Atom('bar'))
    'bar'

    >>> astring(Atom('NIL'))
    'NIL'

    >>> astring(['foo', 'bar'])
    Traceback (most recent call last):
    ValueError: ['foo', 'bar'] cannot be read as an astring.

    """
    if isinstance(value, str):
        return value
    elif isinstance(value, Atom):
        return value.value
    else:
        raise ValueError('%r cannot be read as an astring.' % value)


def nstring(value):
    """Interpret a parsed value as an nstring.

    An nstring is a string that is always represented as a string literal. It
    may be non-existent which is denoted by the special form NIL (parsed as an
    atom with the value 'NIL').

    >>> nstring('foo')
    'foo'

    >>> nstring(Atom('bar'))
    Traceback (most recent call last):
    ValueError: <IMAP atom bar> cannot be read as an nstring.

    >>> repr(nstring(Atom('NIL')))
    'None'

    >>> nstring(['foo', 'bar'])
    Traceback (most recent call last):
    ValueError: ['foo', 'bar'] cannot be read as an nstring.

    """
    if isinstance(value, str):
        return value
    elif isinstance(value, Atom) and value.value == 'NIL':
        return None
    else:
        raise ValueError('%r cannot be read as an nstring.' % value)


def number(value):
    """Interpret a parsed value as a number.

    Numbers are represented by atoms whose value is a decimal representation
    of the number.

    >>> number(Atom('42'))
    42

    >>> number(Atom('foo'))
    Traceback (most recent call last):
    ValueError: <IMAP atom foo> cannot be read as a number.

    >>> number(42)
    Traceback (most recent call last):
    ValueError: 42 cannot be read as a number.

    """
    try:
        return int(value.value)
    except (AttributeError, ValueError):
        raise ValueError('%r cannot be read as a number.' % value)


NIL = Atom('NIL')
