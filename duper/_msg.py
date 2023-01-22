# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

import ast
from typing import Any


_builtin_repr = repr


def repr(obj: Any) -> str:
    """
    >>> repr(1)
    '1'
    >>> repr(object())
    'object(...)'
    >>> repr((1, 2, 3))
    '(1, 2, 3)'
    >>> repr((1, 2, 3, object()))
    'tuple(...)'
    >>> import duper; repr(duper.ast_factory)
    'duper.ast_factory'
    """

    import duper

    try:
        ast.parse(_builtin_repr(obj))
        return _builtin_repr(obj)
    except SyntaxError:
        pass
    try:
        name = obj.__name__
        suffix = ""
    except AttributeError:
        name = type(obj).__name__
        obj = type(obj)
        suffix = "(...)"

    if name in duper.__dict__.keys():
        module = "duper."
    else:
        module = obj.__module__ + "." if obj.__module__ != "builtins" else ""

    return f"{module}{name}{suffix}"
