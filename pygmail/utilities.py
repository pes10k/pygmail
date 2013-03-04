"""Functions for interacting with the toranado IO loop"""

import tornado
from datetime import timedelta


def io_loop():
    return tornado.ioloop.IOLoop.instance()


def loop_cb(callback):
    io_loop().add_callback(callback)


def loop_cb_args_delayed(callback, arg, secs=3):
    exe_time = timedelta(seconds=secs)
    loop_cb(io_loop().add_timeout(exe_time, lambda: callback(arg)))


def loop_cb_args(callback, arg):
    loop_cb(lambda: callback(arg))


def add_loop_cb(callback):
    return lambda arg: loop_cb_args(callback, arg)


def add_loop_cb_args(callback, args):
    return lambda value: loop_cb(lambda: callback(value, **args))
