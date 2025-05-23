"""Scrap"""

import argparse
import sys
import inspect


class NoDefault(object):
    def __repr__(self):
        return "no_default"


no_default = NoDefault()


def arg_dflt_dict_of_callable(f):
    """
    Get a {arg_name: default_val, ...} dict from a callable.
    See also :py:mint_of_callable:
    :param f: A callable (function, method, ...)
    :return:
    """
    argspec = inspect.getfullargspec(f)
    args = argspec.args or []
    defaults = argspec.defaults or []
    return {
        arg: dflt
        for arg, dflt in zip(
            args, [no_default] * (len(args) - len(defaults)) + list(defaults)
        )
    }


# TODO: Separate mint
# TODO: Make minting use a whitelist (inclusion list)


def subparser_for_func(func, subparser_handle, func_name=None):
    """

    :param func: function object
    :param subparser_handle:
    :param func_name: function name

    :return:
    """
    if func_name is None:
        func_name = func.__name__

    func_parser = subparser_handle.add_parser(func_name, help=inspect.getdoc(func))
    func_parser.set_defaults(which=func_name)

    for arg, dflt in arg_dflt_dict_of_callable(func):
        if (
            arg == "self" or arg == "cls"
        ):  # TODO: Not completely safe. Make safer. See i2i.util
            pass
        elif dflt is no_default:
            func_parser.add_argument("--" + arg)
        else:
            func_parser.add_argument("--" + arg, default=dflt)


def is_method_or_function(o):
    return inspect.ismethod(o) or inspect.isfunction(o)


def parser_for_class(o):
    parser = argparse.ArgumentParser()
    subparser_handle = parser.add_subparsers()
    info = inspect.getmembers(o, predicate=is_method_or_function)
    for func_name, func in info:
        print(func_name)
        subparser_for_func(func, subparser_handle=subparser_handle, func_name=func_name)
    return parser


def py2cli_test(cls, input_string):
    sys.argv = input_string.split(" ")
    parser = parser_for_class(cls)
    cl_in = parser.parse_args()
    # print(cl_in)
    func = getattr(cls, cl_in.which)
    del cl_in.which
    return func(**vars(cl_in))
