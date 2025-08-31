# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""
Using these native classes is faster than using builtin ast.AST subclasses

`__class__: type[ast.expr] = ast.expr` and equivalents are used to flavour new classes enough,
so they would smell enough like ast.AST for compile()

Additionally, nodes are aware of their parents and their location,
so we could handle self-reflecting data.

This is not intended to be a full replacement to AST, instead this strives to its faster subset.

Unused, but required field are set as final class variables
to reduce amount of work required to do when initializing class.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import Generic
from typing import TypeVar
from typing import cast

from duper.constants import ImmutableCollectionType
from duper.constants import ImmutableType

if TYPE_CHECKING:
    from collections.abc import Sequence

T = TypeVar("T")
C = TypeVar("C", bound=ImmutableType | ImmutableCollectionType)
A = TypeVar("A", bound="AST")
S = TypeVar("S", bound="stmt")


class AST:
    __class__: type[ast.AST] = ast.AST  # type: ignore[assignment]
    __match_args__: Final = ()

    lineno = 1
    col_offset = 0
    end_col_offset = 0
    end_lineno = 1

    def __init__(self) -> None:
        self.parent: AST | None = None
        self.container: Sequence[AST] | AST | None = None
        self.location: int | str | None = None
        self.name: str | None = None

    def __setitem__(self, key: str, value: AST) -> None:
        setattr(self, key, value)

    def set_parent(
        self,
        parent: AST,
        container: AST | Sequence[AST],
        location: int | str,
        *,
        store_result: bool = True,
    ) -> AST:
        self.parent = parent
        self.container = container
        self.location = location
        if store_result and self.name is not None:
            self.store_result(self.name)
        return self

    def store_result(self, name: str) -> NamedExpr[expr]:
        if self.parent is None or self.container is None or self.location is None:
            raise RuntimeError(
                f"All of the following attributes must be set"
                f" {self.parent=}, {self.container=}, {self.location=}"
            )
        original_parent = self.parent
        original_container = self.container
        original_location = self.location
        new_expr = NamedExpr(Name(id=name, ctx=STORE), value=cast("expr", self))
        original_container[original_location] = new_expr  # type: ignore[index]
        new_expr.set_parent(original_parent, original_container, original_location)
        return new_expr


class expr(AST):
    __class__: type[ast.expr] = ast.expr


class stmt(AST):
    __class__: type[ast.stmt] = ast.stmt


class mod(AST):
    __class__: type[ast.mod] = ast.mod


class arg(AST):
    __class__: type[ast.arg] = ast.arg

    def __init__(self, arg: str) -> None:
        self.arg = arg

    annotation: str | None = None
    type_comment = None


class comprehension(AST):
    __class__: type[ast.comprehension] = ast.comprehension
    _fields: Final = ("target", "iter", "ifs", "is_async")

    def __init__(self, target: expr, iter: expr, ifs: list[expr], is_async: int) -> None:
        super().__init__()
        self.target = target
        self.iter = iter
        self.ifs = ifs
        self.is_async = is_async

        target.set_parent(self, self, "target")
        iter.set_parent(self, self, "iter")
        for i, cond in enumerate(ifs):
            cond.set_parent(self, ifs, i)


class expr_context(AST):
    __class__: type[ast.expr_context] = ast.expr_context


class Load(expr_context):
    __class__: type[ast.Load] = ast.Load


class Store(expr_context):
    __class__: type[ast.Store] = ast.Store


class Return(stmt, Generic[A]):
    __class__: type[ast.Return] = ast.Return

    def __init__(self, value: A) -> None:
        self.value = value


class _Comprehension(expr):
    _fields: Final = ("elt", "generators")

    def __init__(self, elt: expr, generators: list[comprehension]) -> None:
        super().__init__()
        self.elt = elt
        self.generators = generators

        elt.set_parent(self, self, "elt")
        for i, gen in enumerate(generators):
            gen.set_parent(self, gen, i)


class ListComp(_Comprehension, expr):
    __class__: type[ast.ListComp] = ast.ListComp


class GeneratorExp(_Comprehension, expr):
    __class__: type[ast.GeneratorExp] = ast.GeneratorExp


class arguments(AST):
    __class__: type[ast.arguments] = ast.arguments
    """Not used in any way other than as required arg to FunctionDef"""

    def __init__(
        self,
        posonlyargs: list[arg],
        args: list[arg],
        vararg: arg | None,
        kwonlyargs: list[arg],
        kw_defaults: list[arg],
        kwarg: arg | None,
        defaults: list[arg],
    ) -> None:
        self.posonlyargs = posonlyargs
        self.args = args
        self.vararg = vararg
        self.kwonlyargs = kwonlyargs
        self.kw_defaults = kw_defaults
        self.kwarg = kwarg
        self.defaults = defaults


class keyword(AST, Generic[A]):
    __class__: type[ast.keyword] = ast.keyword

    def __init__(self, arg: str, value: A) -> None:
        self.arg = arg
        self.value = value

        value.set_parent(self, self, "value")


LOAD: Final = Load()
STORE: Final = Store()


class _EltsChildren(expr):
    _fields: Final = ("elts",)

    def __init__(self, elts: list[expr], ctx: Load | Store = LOAD) -> None:
        super().__init__()
        self.elts = elts
        self.ctx = ctx
        for i, el in enumerate(self.elts):
            el.set_parent(cast("AST", self), elts, i)


class Name(expr):
    __class__: type[ast.Name] = ast.Name

    def __init__(self, id: str, ctx: Load | Store = LOAD) -> None:
        self.name = None
        self.id = id
        self.ctx = ctx


class Attribute(expr):
    __class__: type[ast.Attribute] = ast.Attribute
    _fields = ("value", "attr", "ctx")

    def __init__(self, value: expr, attr: str, ctx: Load | Store = LOAD) -> None:
        super().__init__()
        self.value = value
        self.attr = attr
        self.ctx = ctx


class Constant(expr, Generic[T]):
    __class__: type[ast.Constant] = ast.Constant
    kind: Final = None

    def __init__(self, value: T) -> None:
        self.name = None
        self.value = value


class NamedExpr(expr, Generic[A]):
    __class__: type[ast.NamedExpr] = ast.NamedExpr
    _fields: Final = ("target", "value")

    def __init__(self, target: Name, value: A) -> None:
        super().__init__()
        self.target = target
        self.value = value

        target.set_parent(self, self, "target")
        value.set_parent(self, self, "value", store_result=False)


class Expression(mod, Generic[A]):
    __class__: type[ast.Expression] = ast.Expression
    _fields: Final = ("body",)

    def __init__(self, body: A) -> None:
        super().__init__()
        self.body = body
        body.set_parent(self, self, "body")


class List(_EltsChildren, expr):
    __class__: type[ast.List] = ast.List


class Tuple(_EltsChildren, expr):
    __class__: type[ast.Tuple] = ast.Tuple


class Set(_EltsChildren, expr):
    __class__: type[ast.Set] = ast.Set


class Dict(expr):
    __class__: type[ast.Dict] = ast.Dict
    _fields = ("keys", "values")

    def __init__(self, keys: list[expr], values: list[expr]) -> None:
        super().__init__()
        self.keys = keys
        self.values = values

        for i, el in enumerate(keys):
            el.set_parent(self, keys, i)

        for i, el in enumerate(values):
            el.set_parent(self, values, i)


class Call(expr):
    __class__: type[ast.Call] = ast.Call
    _fields: Final = ("func", "args", "keywords")

    def __init__(self, func: expr, args: list[AST], keywords: list[keyword[Any]]) -> None:
        super().__init__()
        self.func = func
        self.args: list[AST] = args
        self.keywords = keywords

        # func.set_parent(self, "func")  do we need it?
        for i, el in enumerate(args):
            el.set_parent(self, args, i)


class Subscript(expr):
    """Subscript(expr value, expr slice, expr_context ctx)"""

    __class__: type[ast.Subscript] = ast.Subscript
    _fields: Final = ("value", "slice", "ctx")

    def __init__(self, value: expr, slice: Constant[Any], ctx: Load | Store = LOAD) -> None:
        super().__init__()
        self.value = value
        self.slice = slice
        self.ctx = ctx


class alias(AST):
    __class__: type[ast.alias] = ast.alias

    def __init__(self, name: str, asname: str | None = None) -> None:
        self.name = name
        self.asname = asname


class ImportFrom(stmt):
    __class__: type[ast.ImportFrom] = ast.ImportFrom

    def __init__(self, module: str, names: list[alias], level: int | None = None) -> None:
        self.name = None
        self.module = module
        self.names = names
        self.level = level


class Import(stmt):
    __class__: type[ast.Import] = ast.Import

    def __init__(self, names: list[alias]) -> None:
        self.name = None
        self.names = names


class Assign(stmt):
    __class__: type[ast.Assign] = ast.Assign
    _fields = (
        "targets",
        "value",
        "type_comment",
    )
    type_comment = None

    def __init__(self, targets: list[Name], value: expr) -> None:
        self.targets = targets
        self.value = value


EMPTY_LIST: Final[list[Any]] = []  # not indented to be modified


class FunctionDef(stmt):
    __class__: type[ast.FunctionDef] = ast.FunctionDef
    """Just a blank value"""
    _fields: Final = ("name", "args", "body", "decorator_list", "returns", "type_comment")

    decorator_list: Final[list[expr]] = EMPTY_LIST
    returns: Constant[str] = Constant("Any")
    type_comment: Final = None

    def __init__(self, body: list[stmt], name: str, args: arguments | None = None) -> None:
        super().__init__()
        self.body = body
        self.name = name
        self.args = args or arguments(
            posonlyargs=EMPTY_LIST,
            args=EMPTY_LIST,
            vararg=None,
            kwonlyargs=EMPTY_LIST,
            kw_defaults=EMPTY_LIST,
            kwarg=None,
            defaults=EMPTY_LIST,
        )


class Module(mod):
    __class__: type[ast.Module] = ast.Module
    _fields: Final = ("body",)

    type_ignores: Final[list[int]] = EMPTY_LIST

    def __init__(self, body: list[S]) -> None:
        super().__init__()
        self.body = body
