"""This file contains classes that encapsulate errors that can happen when
talking with the IMAP server, and functions that help in dealing with them.
All of this is aimed to provide Exception handling like functionality in a
callback based environment."""

from pygmail.utilities import loop_cb_args
from tornado.log import app_log


def register_callback_if_error(imap_response, callback, require_ok=True):
    """Checks to see if the given imap response is an error.  If so,
    it is registered as the only argument to the given callback function
    on the Torando event loop.

    Args:
        imap_response -- The 3 part tuple (response, cb_arg, error) that
                         imaplib2 returns as a result of any callback response
        callback      -- A callback function to register on the event loop
                         in case of an error

    Keyword Args:
        require_ok -- Whether responses other than "OK" from the IMAP server
                      should trigger an error

    Returns:
        True if an error was encountered and the callback was queued. Otherwise
        False
    """
    if isinstance(imap_response, tuple):
        error = check_for_response_error(imap_response, require_ok=require_ok)
        if error:
            loop_cb_args(callback, error)
            return True
        else:
            return False
    elif is_imap_error(imap_response) or is_auth_error(imap_response):
        loop_cb_args(callback, error)
        return True
    else:
        return False


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
    response, cb_arg, error = imap_response
    if response is None:
        if __debug__:
            app_log.error(error[1])
        return IMAPError(error[1])
    else:
        typ, data = response
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
    return response and response.__class__ is IMAPError


def is_auth_error(response):
    """Checks to see if the given object is an AuthError instance

    Returns:
        True if the given object is an AuthError, and False in all other
        instances
    """
    return response.__class__ is AuthError


class AuthError(ExceptionLike):
    """An exeption-like class signifying that an authentication attempt with the
    gmail server was not accepted. This is handled through a class instead of
    through exceptions to make things easier with the event loop."""


def is_encoding_error(response):
    """Checks to see if the given object is an error thrown as a result
    of trying to encode a message body as Unicode

    Returns:
        True if the given object is a Unicode error, and False in all other
        instances
    """
    return response.__class__ is UnicodeDecodeError or response.__class__ is LookupError
