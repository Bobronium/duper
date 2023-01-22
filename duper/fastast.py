# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

"""
These are duck-typed definitions of builtin AST classes.

I'm experimenting with speed of such alternative, when compiled to native classes.

`__class__: type[ast.expr] = ast.expr` and equivalents are used to flavour new classes enough,
so they would smell enough like ast.AST for compile()
"""
from __future__ import annotations

import ast
from typing import Any
from typing import Final
from typing import Generic
from typing import TypeVar

from mypy_extensions import trait


T = TypeVar("T")
E = TypeVar("E", bound="expr")
S = TypeVar("S", bound="stmt")


class AST:
    __class__: type[ast.AST] = ast.AST  # type: ignore[assignment]
    __match_args__: Final = ()

    lineno = 1
    col_offset = 0
    end_col_offset = 0
    end_lineno = 1


class expr(AST):
    __class__: type[ast.expr] = ast.expr

    def __setitem__(self, key: str, value: AST) -> None:
        setattr(self, key, value)


class stmt(AST):
    __class__: type[ast.stmt] = ast.stmt
    pass


class mod(AST):
    __class__: type[ast.mod] = ast.mod


class arg(AST):
    __class__: type[ast.arg] = ast.arg

    def __init__(self, arg: str) -> None:
        self.arg = arg

    annotation: str | None = None
    type_comment = None


class Load(expr):
    __class__: type[ast.Load] = ast.Load  # type: ignore[assignment]


LOAD: Final = Load()


class Store(expr):
    __class__: type[ast.Store] = ast.Store  # type: ignore[assignment]


class Return(stmt, Generic[E]):
    __class__: type[ast.Return] = ast.Return

    def __init__(self, value: E) -> None:
        self.value = value


class arguments(expr):
    __class__: type[ast.arguments] = ast.arguments  # type: ignore[assignment]
    """Not used in any way other tnen as required arg ot FunctionDef"""

    posonlyargs: Final[list[arg]] = []
    args: Final[list[arg]] = []
    vararg: Final = None  # real type is arg | None
    kwonlyargs: Final[list[arg]] = []
    kw_defaults: Final[list[arg]] = []
    kwarg: Final = None  # real type is arg | None
    defaults: Final[list[arg]] = []


class keyword(stmt, Generic[E]):
    __class__: type[ast.keyword] = ast.keyword  # type: ignore[assignment]

    def __init__(self, arg: str, value: E) -> None:
        self.arg = arg
        self.value = value


class Name(expr):
    __class__: type[ast.Name] = ast.Name

    def __init__(self, id: str, ctx: Load | Store = LOAD) -> None:
        self.id = id
        self.ctx = ctx


class Constant(expr, Generic[T]):
    __class__: type[ast.Constant] = ast.Constant
    kind: Final = None

    def __init__(self, value: T) -> None:
        self.value = value


class NamedExpr(expr, Generic[E]):
    __class__: type[ast.NamedExpr] = ast.NamedExpr

    def __init__(self, target: Name, value: E) -> None:
        self.target = target
        self.value = value


class Expression(expr, Generic[E]):
    __class__: type[ast.Expression] = ast.Expression  # type: ignore[assignment]

    def __init__(self, body: E) -> None:
        self.body = body


@trait
class _Elts:
    _fields: Final = ("elts",)

    def __init__(self, elts: list[expr]) -> None:
        self.elts = elts
        self.ctx = LOAD


class List(expr, _Elts):
    __class__: type[ast.List] = ast.List  # type: ignore[assignment]


class Tuple(expr, _Elts):
    __class__: type[ast.Tuple] = ast.Tuple  # type: ignore[assignment]


class Set(expr, _Elts):
    __class__: type[ast.Set] = ast.Set  # type: ignore[assignment]


class Dict(expr):
    __class__: type[ast.Dict] = ast.Dict

    def __init__(self, keys: list[expr], values: list[expr]) -> None:
        super().__init__()
        self.keys = keys
        self.values = values


class Call(expr):
    __class__: type[ast.Call] = ast.Call

    def __init__(
        self, func: Name | Constant[Any], args: list[expr], keywords: list[keyword[Any]]
    ) -> None:
        self.func = func
        self.args: list[expr] = args
        self.keywords = keywords


class FunctionDef(stmt):
    __class__: type[ast.FunctionDef] = ast.FunctionDef
    """Just a blank value"""

    args: Final = arguments()
    decorator_list: Final[list[expr]] = []
    returns: Constant[str] = Constant("Any")
    type_comment: Final = None

    def __init__(self, body: list[stmt], name: str) -> None:
        self.body = body
        self.name = name


class Module(mod):
    __class__: type[ast.Module] = ast.Module

    type_ignores: Final[list[int]] = []

    def __init__(self, body: list[S]) -> None:
        self.body = body
