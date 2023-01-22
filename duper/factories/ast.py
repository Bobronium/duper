# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

"""
Construct AST that creates a deep copy of a given object
"""
from __future__ import annotations

import ast
import linecache
import types
from collections.abc import Callable
from collections.abc import Iterable
from threading import Lock
from types import FunctionType
from typing import Any
from typing import Final
from typing import TypeVar
from typing import cast

import duper
from duper.constants import IMMUTABLE_NON_COLLECTIONS
from duper.constants import IMMUTABLE_TYPES
from duper.constants import ImmutableType
from duper.factories.runtime import debunk_reduce
from duper.factories.runtime import get_reduce
from duper.factories.runtime import reconstruct_state
from duper.fastast import Call
from duper.fastast import Constant
from duper.fastast import Dict
from duper.fastast import FunctionDef
from duper.fastast import List
from duper.fastast import Load
from duper.fastast import Module
from duper.fastast import Name
from duper.fastast import NamedExpr
from duper.fastast import Return
from duper.fastast import Set
from duper.fastast import Store
from duper.fastast import Tuple
from duper.fastast import expr
from duper.fastast import keyword
from duper.fastast import stmt


T = TypeVar("T")
E = TypeVar("E", bound=expr)

# default locations that ast sets in ast.fix_missing_locations()
# we can save a lot of time by setting them ourselves

LOAD: Final = Load()
STORE: Final = Store()
LOC: Final = dict(lineno=1, col_offset=0, end_lineno=1, end_col_offset=0)
Undefined: Final = NamedExpr(Name("UNDEFINED"), Constant(1))
CONSTANT_AST_TYPES: Final = frozenset({Name, Constant})


def __loader__() -> None:
    """Special method to tell inspect that this file has special logic for loading the code"""


class Namespace:
    def __init__(self) -> None:
        self.forbid_references: dict[int, Any] = {}
        self.names: dict[str, Any] = {}
        self.used_names: set[str] = set()
        self.vid_to_name: dict[int, str] = {}
        self.reconstructed: dict[int, expr] = {}

    def check_references(self, value: Any) -> Name | None:
        if (vid := id(value)) in self.reconstructed:
            # This is the hackiest hack, and it shouldn't be done like this
            # but this allows to make things simpler in other places
            # which is a good trade for now.
            # In later versions this will be resolved in a more general way.
            expression = self.reconstructed[vid]
            name = self.get_name(value)
            if isinstance(expression, NamedExpr):
                return Name(name)
            new_expression = NamedExpr(target=Name(name, ctx=STORE), value=duper.dupe(expression))
            expression.__dict__.clear()
            expression.__dict__.update(new_expression.__class__.__dict__)
            expression.__dict__.update(new_expression.__dict__)
            expression.__class__ = ast.NamedExpr
            return Name(name)

        if (vid := id(value)) in self.forbid_references and vid not in self.vid_to_name:
            # If we end up here, it must mean type has been referenced again before we
            # finished reconstructing an AST statement for it.
            # this can be resolved, but I don't want to overcomplicate the logic to include
            # all such interactions before releasing the PoC.
            # There are some special cases that duper handles already, like reconstruction from
            # reduce, which may require reconstructed instance value to be present
            # to reconstruct its state, but a more general approach is needed to support them all
            raise NotImplementedError(
                f"Already seen {type(value)=}, {id(value)=} self-reflexive types are not supported yet"
            )
        self.forbid_references[vid] = value
        return None

    def unlock_references(self, value: Any, expression: T) -> T:
        self.forbid_references.pop(vid := id(value), None)
        self.reconstructed[vid] = cast(expr, expression)
        return expression

    def store(self, x: T) -> Name:
        """
        Stores object as is to be available in namespace
        """
        name = self.get_name(x)
        self.names[name] = x
        return Name(id=name)

    def get_name(self, value: Any) -> str:
        """
        Assigns names and resolves collisions
        Once name is set, it's remembered in vid_to_name map

        Previously, it resolved collisions in advance by f'{type(value).__name__}{id(value)}'
        But this was quite verbose and not pleasant to read/debug
        """

        # already assigned a name previously
        if (vid := id(value)) in self.vid_to_name:
            return self.vid_to_name[vid]
        if (name := getattr(value, "__qualname__", None)) is None:
            name = type(value).__name__.lower()

        i = 1
        while name in self.used_names:
            name = f"{name}{i}"
            i += 1

        # remember assigned names for future lookup
        self.vid_to_name[vid] = name
        self.used_names.add(name)
        return name


def reconstruct_from_reduce(
    x: T,
    namespace: Namespace,
    func: Callable[..., T],
    args: Any,
    kwargs: Any,
    state: Any = None,
    listiter: Iterable[Any] | None = None,
    dictiter: Iterable[tuple[Any, Any]] | None = None,
) -> Call:
    if state is None and listiter is None and dictiter is None:
        return Call(
            func=namespace.store(func),
            args=[reconstruct_expression(item, namespace) for item in args],
            keywords=[
                keyword(
                    arg=name,
                    value=reconstruct_expression(item, namespace),
                )
                for name, item in kwargs.items()
            ],
        )
    return Call(
        func=namespace.store(reconstruct_state),
        args=[
            # newly created instance will be referenced during reconstruction
            namespace.unlock_references(
                x,
                NamedExpr(
                    target=Name(id=namespace.get_name(x), ctx=STORE),
                    value=Call(
                        func=namespace.store(func),
                        args=[reconstruct_expression(item, namespace) for item in args],
                        keywords=[
                            keyword(
                                arg=name,
                                value=reconstruct_expression(item, namespace),
                            )
                            for name, item in kwargs.items()
                        ],
                    ),
                ),
            ),
            reconstruct_expression(state, namespace),
            Call(
                func=reconstruct_const(iter, namespace),
                args=[reconstruct_list(list(listiter) if listiter else [], namespace)],
                keywords=[],
            ),
            Call(
                func=reconstruct_const(dict.items, namespace),
                args=[reconstruct_dict(dict(dictiter) if dictiter else {}, namespace)],
                keywords=[],
            ),
        ],
        keywords=[],
    )


def reconstruct_const(x: T, namespace: Namespace) -> Name | Constant[Any]:
    return (
        # can't use Constant with types in ast (which makes sense, there's no literals for them)
        # it's possible to substitute LOAD_GLOBAL with LOAD_CONST later in the bytecode,
        # but it's quite slow (with libs from PyPi), and doesn't give a big performance uplift
        # later, so I'm ignoring this for now
        namespace.store(x)
        if type(x) not in IMMUTABLE_TYPES
        or isinstance(
            x,
            (
                type,
                types.MethodType,
                types.BuiltinMethodType,
                types.FunctionType,
                types.MethodDescriptorType,
            ),
        )
        else Constant(value=x)
    )


def reconstruct_list(x: list[Any], namespace: Namespace) -> List:
    return List([reconstruct_expression(i, namespace) for i in x])


def reconstruct_set(x: set[Any], namespace: Namespace) -> Set:
    return Set([reconstruct_expression(i, namespace) for i in x])


def reconstruct_dict(x: dict[Any, Any], namespace: Namespace) -> Dict | Call | Name:
    return Dict(
        keys=[reconstruct_expression(i, namespace) for i in x.keys()],
        values=[reconstruct_expression(i, namespace) for i in x.values()],
    )


def reconstruct_tuple(
    x: tuple[Any, ...] | frozenset[Any], namespace: Namespace
) -> Tuple | NamedExpr[Any] | Name | Constant[tuple[ImmutableType, ...]]:
    immutable = True
    values = [
        expression
        for i in x
        if (
            # this is a tuple of two expressions, always results in True
            # constructing list with list comprehension should be faster
            # than appending values, but we need to check each element as well,
            # so we're doing it with Lennon's (or Paul's?) operator.
            (expression := reconstruct_expression(i, namespace)),
            (
                immutable := immutable
                and (
                    isinstance(expression, Constant)
                    or isinstance(expression, Name)
                    # object is in the namespace, should be immutable
                    # types, functions, etc. are ending up in namespace.names
                    and namespace.names.get(expression.id) is i
                )
            ),
        )
    ]
    if immutable:
        return reconstruct_const(x, namespace)
    return Tuple(elts=values)


def reconstruct_method(x: types.MethodType, namespace: Namespace) -> Call:
    return Call(
        func=reconstruct_const(type(x), namespace),
        args=[
            reconstruct_const(x.__func__, namespace),
            reconstruct_expression(x.__self__, namespace),
        ],
        keywords=[],
    )


def reconstruct_expression(x: Any, namespace: Namespace) -> expr:
    """
    Based on copy._reconstruct
    """

    cls = type(x)
    if cls in IMMUTABLE_NON_COLLECTIONS:
        return namespace.unlock_references(x, reconstruct_const(x, namespace))

    existing = namespace.check_references(x)
    if existing is not None:
        return existing

    constructor: Callable[[Any, Namespace], expr] | None = optimized_constructors.get(cls)

    if constructor is not None:
        return namespace.unlock_references(x, constructor(x, namespace))

    if (custom_copier := getattr(x, "__deepcopy__", None)) is not None:
        return namespace.unlock_references(
            x, reconstruct_from_reduce(x, namespace, custom_copier, ({},), {}, None, None, None)
        )

    rv = get_reduce(x, cls)
    if isinstance(rv, str):  # global name
        return namespace.unlock_references(x, reconstruct_const(x, namespace))
    rv = debunk_reduce(*rv)

    return namespace.unlock_references(x, reconstruct_from_reduce(x, namespace, *rv))


def ast_factory(x: T) -> Callable[[], T]:
    return_value_ast = reconstruct_expression(x, namespace := Namespace())
    return compile_function(
        f"produce_{type(x).__name__}",
        [Return(value=return_value_ast)],
        namespace,
    )


optimized_constructors: dict[type[Any], Callable[[Any, Namespace], expr]] = {
    dict: reconstruct_dict,
    list: reconstruct_list,
    set: reconstruct_set,
    tuple: reconstruct_tuple,
    frozenset: reconstruct_tuple,
    types.ModuleType: reconstruct_const,
    types.MethodType: reconstruct_method,
    **{t: reconstruct_const for t in IMMUTABLE_NON_COLLECTIONS},
}
FUNCTION: Final = FunctionDef(
    name="FN",
    body=[],
)
MODULE: Final = Module(
    body=[FUNCTION],
)

with_source: bool = False


def compile_function(name: str, body: list[stmt], namespace: Namespace) -> FunctionType:
    global MODULE, FUNCTION
    with Lock():
        # changing variables on predefined AST is much faster
        # than constructing AST from scratch
        # locking just in case this is used in different threads
        FUNCTION.name = name
        FUNCTION.body = body
        if with_source:
            # this is most useful for debugging
            # it visualizes the AST it generated back into python syntax
            # it's also slow, so should be disabled, unless utilized
            #
            # TODO: generate this on demand (when source lines are retrieved)
            assert len(body) == 1, "Initial implementation always contained 1 line of code"
            assert isinstance(body[0], Return)
            assert body[0].value is not None

            return_value = ast.unparse(body[0].value)
            source = [name := f"lambda: {return_value}"]
            FUNCTION.name = name
            file = f"<duper {hash(return_value)}>"
            linecache.cache[file] = (0, None, source, "")
        else:
            file = "<duper factory (enable introspection to see source code)>"

        code = compile(MODULE, file, "exec")  # type: ignore[arg-type]

    full_ns = {**globals(), **namespace.names}
    exec(code, full_ns)
    function: FunctionType = full_ns[name]
    function.__module__ = __name__
    return function
