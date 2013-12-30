"""This file contains classes that encapsulate errors that can happen when
talking with the IMAP server, and functions that help in dealing with them.
All of this is aimed to provide Exception handling like functionality in a
callback based environment."""

from pygmail.utilities import _cmd, _log

try:
    import imaplib2 as imaplib
    imaplib.imaplib = imaplib.imaplib2
except ImportError:
    import imaplib

def check_imap_state(callback):
    """Decorator that checks to see if the given imaplib2 connection is still in
    a state where we can still make requests against it (ie its not in LOGOUT).
    If the connection is in LOGOUT, call the callback with a ConnectionError
    instance.  Otherwise, call the original function.

    Args:
        callback -- The callback specified by the client that expects a response
                    from this callback loop
    """
    def decorator(func):
        def inner(*args, **kwargs):
            conn = args[0]
            if not isinstance(conn, imaplib.IMAP4) or conn.state == imaplib.imaplib.LOGOUT:
                rs = IMAPClosedError('IMAP in state LOGOUT', func.__name__)
                if callback:
                    return _cmd(callback, rs)
                else:
                    return rs
            else:
                return func(*args, **kwargs)
        return inner
    return decorator


def check_imap_response(callback, require_ok=True):
    """Decorator that checks to see if the given imap response is an error.
    If so, it is registered as the only argument to the given callback function
    on the Torando event loop.  Otherwise, the decorated function is called
    unchanged

    Args:
       callback -- A callback function to register on the event loop
                   in case of an error

    Keyword Args:
        require_ok -- Whether responses other than "OK" from the IMAP server
                      should trigger an error
    """
    def decorator(func):
        def inner(*args, **kwargs):
            imap_response = args[0]
            if isinstance(imap_response, tuple):
                error = check_for_response_error(imap_response, require_ok=require_ok)
                if error:
                    if callback:
                        return _cmd(callback, error)
                    else:
                        return error
                else:
                    return func(*args, **kwargs)
            elif is_imap_error(imap_response) or is_auth_error(imap_response) or is_connection_closed_error(imap_response):
                if callback:
                    return _cmd(callback, imap_response)
                else:
                    return imap_response
            else:
                return func(*args, **kwargs)
        return inner
    return decorator


def check_for_response_error(imap_response, require_ok=True):
    """Checks to see if the given response, from a raw imaplib2 call,
    is an error.

    Args:
        imap_response -- The 3 part tuple (response, cb_arg, error) that
                         imaplib2 returns as a result of any callback response

    Keyword Args:
        require_ok -- Whether responses other than "OK" from the IMAP server
                      should trigger an error

    Returns:
        An IMAPError object encapsulating the error (in the case of an error),
        or None (in the case of no error).
    """
    # A three item response means a response from an async request, while
    # a two item response is a result from a standard blocking request
    if len(imap_response) == 3:
        response, cb_arg, error = imap_response
        if response is None:
            if __debug__:
                _log.error(error[1])
            return IMAPError(error[1])
        else:
            typ, data = response
            if typ != "OK" and require_ok:
                return IMAPError(desc=data, type=typ)
            else:
                return None
    else:
        typ, data = imap_response
        if typ != "OK" and require_ok:
            return IMAPError(desc=data, type=typ)
        else:
            return None


class ExceptionLike(object):
    """A simple base class to encapsulate exception like errors thrown or
    received during communication with GMail"""

    def __init__(self, desc=None, context=None):
        self.msg = desc
        self.context = context


class IMAPError(ExceptionLike):
    """An exeption-like class signifying that an IMAP level error was received
    when attempting to communicate with Gmail's IMAP server."""

    def __init__(self, desc=None, context=None, type=None):
        self.type = type
        super(IMAPError, self).__init__(desc=desc, context=context)


def is_imap_error(response):
    """Checks to see if the given object is an IMAPError instance

    Returns:
        True if the given object is an IMAPError, and False in all other
        instances
    """
    return isinstance(response, IMAPError)


class AuthError(ExceptionLike):
    """An exeption-like class signifying that an authentication attempt with the
    gmail server was not accepted. This is handled through a class instead of
    through exceptions to make things easier with the event loop."""


def is_auth_error(response):
    """Checks to see if the given object is an AuthError instance

    Returns:
        True if the given object is an AuthError, and False in all other
        instances
    """
    return isinstance(response, AuthError)


class IMAPClosedError(ExceptionLike):
    """An exception-like object used for wrapping errors where we were about
    to make a call against a closed IMAP connection"""


def is_connection_closed_error(response):
    """Checks to see if the given object is an IMAPClosedError instance

    Returns:
        True if the given object is an AuthError, and False in all other
        instances
    """
    return isinstance(response, IMAPClosedError)


def is_encoding_error(rs):
    """Checks to see if the given object is an error thrown as a result
    of trying to encode a message body as Unicode

    Returns:
        True if the given object is a Unicode error, and False in all other
        instances
    """
    return isinstance(rs, UnicodeDecodeError) or isinstance(rs, LookupError)


def is_error(response):
    """Checks to see if the given item is any of the psuedo-exception like
    objects we use for passing errors back to the main IOLoop

    Returns:
        True if the given object is an exception like error, and False in all
        other instances
    """
    return isinstance(response, ExceptionLike)
