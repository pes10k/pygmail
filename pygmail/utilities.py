"""Functions for interacting with the toranado IO loop"""

import tornado
from datetime import timedelta


def io_loop():
    """Returns a reference to the tornado IO Loop

    Returns:
        Shared reference to the IOLoop object
    """
    return tornado.ioloop.IOLoop.instance()


def loop_cb(callback):
    """Adds a callback function to be executed by the tornado event loop

    Args:
        callback -- a function to be executed by the torando event loop
    """
    io_loop().add_callback(callback)


def loop_cb_args(callback, arg):
    """Adds a callback function to be executed by the tornado event loop with
    a single given argument, passed through to the callback function.

    Args:
        callback -- A function to be executed by the torando event loop
        arg      -- A single argument to be passed to the callback function
    """
    loop_cb(lambda: callback(arg))


def loop_cb_args_delayed(callback, arg, secs=3):
    """Registers a function, with a given argument, to be executed by the
    tornado event loop in a given number of seconds from now.

    Args:
        callback -- A function to be executed by the torando event loop
        arg      -- A single argument to be passed to the callback function

    Keyword Args:
        secs -- The time from now, in seconds, that the callback should be
                executed
    """
    exe_time = timedelta(seconds=secs)
    loop_cb(io_loop().add_timeout(exe_time, lambda: callback(arg)))


def add_loop_cb(callback):
    """Registers a callback function to be exected by tornado event loop. This
    function isn't registered on the callback loop immediatly, but is actually
    itself a function to register a callback.  It is appropriate for use when
    you want to pass a function as an argument to another callback expecting
    function, but that function isn't tornado aware.

    Args:
        callback -- A function to be executed by the torando event loop
    """
    return lambda arg: loop_cb_args(callback, arg)


def add_loop_cb_args(callback, args):
    """Registers a callback function to be exected by tornado event loop. This
    function isn't registered on the callback loop immediatly, but is actually
    itself a function to register a callback.  It is appropriate for use when
    you want to pass a function as an argument to another callback expecting
    function, but that function isn't tornado aware.

    This function allows for a dict of arguments to be passed along to the
    callback function.

    Args:
        callback -- A function to be executed by the torando event loop
        args     -- A dict of arguments to pass along to the callback function
    """
    return lambda value: loop_cb(lambda: callback(value, **args))
