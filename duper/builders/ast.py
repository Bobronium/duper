# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""
Construct AST that creates a deep copy of a given object
"""

from __future__ import annotations

import ast
import builtins
import importlib
import linecache
import pickle
import sys
import types
import uuid
from enum import Enum
from types import FunctionType
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import TypeVar
from typing import cast

from duper import _empty_module
from duper.builders._helpers import SentinelMemo
from duper.builders._helpers import forbid_references
from duper.builders._source import LazySourceLines
from duper.builders._tracking import ASTObjectInfo
from duper.builders.runtime import debunk_reduce
from duper.builders.runtime import get_reduce
from duper.constants import CODE_ATTRIBUTES
from duper.constants import CONST_TYPES
from duper.constants import IMMORTAL_OBJECTS
from duper.constants import IMMUTABLE_CONSTANTS_OR_IMPORTABLE
from duper.constants import IMMUTABLE_NON_COLLECTIONS
from duper.constants import ImmutableCollectionType
from duper.constants import ImmutableType
from duper.fastast import AST
from duper.fastast import LOAD
from duper.fastast import STORE
from duper.fastast import A
from duper.fastast import Assign
from duper.fastast import Attribute
from duper.fastast import Call
from duper.fastast import Constant
from duper.fastast import Dict
from duper.fastast import FunctionDef
from duper.fastast import Import
from duper.fastast import ImportFrom
from duper.fastast import List
from duper.fastast import Module
from duper.fastast import Name
from duper.fastast import NamedExpr
from duper.fastast import Return
from duper.fastast import Set
from duper.fastast import Subscript
from duper.fastast import Tuple
from duper.fastast import alias
from duper.fastast import arg
from duper.fastast import arguments
from duper.fastast import expr
from duper.fastast import keyword
from duper.fastast import stmt

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable

T = TypeVar("T")
E = TypeVar("E", bound=expr)

Undefined: Final = NamedExpr(Name("UNDEFINED"), Constant(1))
DEFAULT_NAMESPACE = {**builtins.__dict__, **_empty_module.__dict__}
IMMORTAL_CONSTANTS: Final = {id(obj): Constant(obj) for obj in IMMORTAL_OBJECTS}
BUILTIN_NAMES: Final = {
    id(obj): Name(name) for name, obj in builtins.__dict__.items() if not name.startswith("_")
}
CACHE: Final[dict[int, Name | Constant[ImmutableType | ImmutableCollectionType]]] = {
    **BUILTIN_NAMES,
    **IMMORTAL_CONSTANTS,
}
EMPTY_TUPLE_CONSTANT = Constant(())


def __loader__() -> None:  # noqa: N807
    """Special method to tell inspect that this file has special logic for loading code"""
    raise NotImplementedError


class ASTBuilder:
    def __init__(
        self,
        memo: dict[int, Any] | None,
        *,
        ignore_deepcopy_method: bool,
        interprocess: bool,
    ) -> None:
        self.objects: dict[int, ASTObjectInfo] = {}
        self.keep_by_reference: dict[int, Any] | None = memo
        self.ignore_deepcopy_method = ignore_deepcopy_method
        self.interprocess = interprocess

        self.names: dict[str, Any] = {}
        self.used_names: set[str] = {*builtins.__dict__, "None", "True", "False"}
        self.cell_helper_required: bool = False

    def get_or_create_object_info(self, value: Any) -> ASTObjectInfo:
        """Single lookup/creation point. Returns ObjectInfo for direct manipulation."""
        vid = id(value)
        obj_info = self.objects.get(vid)
        if obj_info is None:
            external_value = None
            if self.keep_by_reference is not None:
                external_value = self.keep_by_reference.get(vid)
            obj_info = ASTObjectInfo(vid, value, type(value), external_value)
            self.objects[vid] = obj_info
        return obj_info

    def check_object_state(self, obj_info: ASTObjectInfo) -> Name | None:
        """Check if object can be referenced directly or needs reconstruction."""
        if obj_info.exclusive_for:
            forbid_references(obj_info.value)

        # Already fully reconstructed - return reference
        if obj_info.expression is not None:
            if isinstance(obj_info.expression, Name):
                return obj_info.expression
            name = self.get_name(obj_info.value)
            self.store_expression(obj_info.expression, name)
            return Name(name)

        # External reference from memo
        if obj_info.external_value is not None:
            return self.store(obj_info.external_value)

        # Currently being reconstructed - this is a self-reference
        if obj_info.is_reconstructing:
            if obj_info.reflective_refs is None:
                obj_info.reflective_refs = []
            reference = Name(self.get_name(obj_info.value))
            obj_info.reflective_refs.append(reference)
            return reference

        # Mark as being reconstructed
        obj_info.is_reconstructing = True
        return None

    def finalize_object(self, obj_info: ASTObjectInfo, expression: A) -> A:
        """Mark object as reconstructed and store result."""
        obj_info.is_reconstructing = False
        obj_info.expression = expression
        return expression

    def store_expression(self, expression: AST, name: str) -> None:
        if isinstance(expression, NamedExpr):
            return
        if expression.parent is None:
            expression.name = name
        else:
            expression.store_result(name)

    def store(self, x: T) -> Name:
        """Stores object as is to be available in namespace"""
        name = self.get_name(x)
        name, *_ = name.split("[")
        self.names[name] = x
        return Name(id=name)

    def get_name(self, value: Any) -> str:
        """Assigns names and resolves collisions"""
        obj_info = self.objects.get(id(value))
        if obj_info is not None and obj_info.name is not None:
            return obj_info.name

        if (name := getattr(value, "__qualname__", None)) is None and (
            name := getattr(value, "__name__", None)
        ) is None:
            name = type(value).__name__.lower()

        # FIXME: probably better to just store via locals().__setitem__(name, value)...
        #  this is done just for sake of fast fix
        if not name.isidentifier():
            *_, name = name.split(".")

        if not name.isidentifier():
            name = name.strip("<>") + "_1"

        i = 1
        original_name = name
        while name in self.used_names and self.names.get(name) is not value:
            name = f"{original_name}_{i}"
            i += 1

        # Store name on object if it exists
        if obj_info is not None:
            obj_info.name = name
        self.used_names.add(name)
        return name

    def store_interprocess(self, value: Any) -> Name | Attribute | Subscript | Call:
        """
        Produce an interprocess-safe AST reference to `value`.
        Semantics mirror pickle's global resolution:
          - decide module with which_module-like logic,
          - import module, walk dotted path, verify identity,
          - emit either a global name (top-level) or parent.attribute chain,
          - for locals/lambdas use build_function_local,
          - for enums: Class.Member after verifying the class path.
        Raises pickle.PicklingError on 'not found' or 'not the same object' cases.
        """
        if isinstance(value, Enum):
            self._verify_same_object(value, (cls := type(value)).__name__ + f".{value._name_}")
            class_name = self.get_name(cls)
            self.names[class_name] = cls
            return Attribute(value=Name(class_name), attr=value._name_)

        if value is types.CodeType:
            self.names["types"] = types
            return Attribute(value=Name("types"), attr="CodeType")
        if value is types.MethodType:
            self.names["types"] = types
            return Attribute(value=Name("types"), attr="MethodType")

        if value is types.NoneType:
            self.names["types"] = types
            return Attribute(value=Name("types"), attr="NoneType")

        qualified_name = getattr(value, "__qualname__", None) or getattr(value, "__name__", None)
        if not qualified_name:
            # Fall back to direct module dict scan; if that fails, raise "not found"
            module_name = getattr(value, "__module__", None) or "__main__"
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: it's not found as {module_name}.{type(value).__name__}"
            )

        # Locals / lambdas: your implementation supports reconstructing them
        if isinstance(value, types.FunctionType) and (
            "<locals>" in qualified_name or "<lambda>" in qualified_name
        ):
            return self.build_function_local(value)

        # Decide module name (fast path via __module__, fallback scan like whichmodule)
        module_name = self._which_module(value, qualified_name)

        # Import and resolve dotted path against that module
        try:
            resolved, parent = self._get_attribute_from_module(module_name, qualified_name)
        except (ImportError, KeyError, AttributeError):
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: it's not found as {module_name}.{qualified_name}"
            ) from None

        # Must be exactly the same object
        if resolved is not value:
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: it's not "
                f"the same object as {module_name}.{qualified_name}"
            )

        # Emit: top-level name -> import-based global; nested -> parent.attribute
        if parent is sys.modules.get(module_name):
            # Top-level symbol; build_imports will add ImportFrom(module_name, name)
            return self.store(value)
        # Nested attribute chain: reconstruct parent expression, then leaf attribute
        leaf = qualified_name.rpartition(".")[2]
        return self._emit_parent_attribute(parent, leaf, value)

    def _emit_parent_attribute(self, parent: Any, attribute: str, child: Any) -> Attribute | Call:
        """
        Ensure `parent` is globally identical and that getattr(parent, attribute) is `child`,
        then emit Attribute(parent_expr, attribute).
        """
        self._verify_same_object(parent)
        if not attribute or getattr(parent, attribute, _nil) is not child:
            parent_module = getattr(parent, "__module__", None) or "<unknown>"
            parent_qualified = getattr(parent, "__qualname__", None) or getattr(
                parent, "__name__", "<unknown>"
            )
            raise pickle.PicklingError(
                f"Can't pickle {child!r}: it's not "
                f"the same object as {parent_module}.{parent_qualified}.{attribute or '<unknown>'}"
            )
        if attribute.isidentifier():
            return Attribute(value=self.build_expression(parent), attr=attribute)

        return Call(
            Name("getattr"), args=[self.build_expression(parent), Constant(attribute)], keywords=[]
        )

    def _get_attribute_from_module(self, module_name: str, qualified_name: str) -> tuple[Any, Any]:
        """
        Resolve `qualified_name` starting from module `module_name`, like pickle._getattribute,
        but return (resolved_object, parent_object). Forbid '<locals>' path elements.
        Raises AttributeError (with pickle-like messages) or ImportError.
        """
        module = sys.modules.get(module_name)
        if module is None:
            module = importlib.import_module(module_name)

        top = module
        obj: Any = module
        parent: Any = module

        for subpath in qualified_name.split("."):
            if subpath == "<locals>":
                msg = f"Can't get local attribute {qualified_name!r} on {top!r}"
                raise AttributeError(msg)
            try:
                parent = obj
                obj = getattr(obj, subpath)
            except AttributeError:
                msg = f"Can't get attribute {qualified_name!r} on {top!r}"
                raise AttributeError(msg) from None
        return obj, parent

    def _which_module(self, value: Any, qualified_name: str) -> str:
        """
        Pickle-like whichmodule:
          - Use value.__module__ if present.
          - Else scan a stable copy of sys.modules and return the first module where
            resolving qualified_name yields `value`.
          - If nothing matches, return '__main__' (pickle's sentinel).
        """
        module_name: str | None = getattr(value, "__module__", None)
        if module_name is not None:
            return module_name

        for name, module in sys.modules.copy().items():
            if name in ("__main__", "__mp_main__") or module is None:
                continue
            try:
                resolved, _ = self._get_attribute_from_module(name, qualified_name)
            except Exception:  # noqa: S112, BLE001
                continue
            if resolved is value:
                return name
        return "__main__"

    def _verify_same_object(self, value: Any, qualified_name: str | None = None) -> tuple[str, str]:
        """
        Verify that sys.modules[module].qualified_name is exactly `value`.
        Returns (module, qualified_name) or raises pickle.PicklingError.
        """
        module_name = getattr(value, "__module__", None)
        qualified_name = (
            qualified_name
            or getattr(value, "__qualname__", None)
            or getattr(value, "__name__", None)
        )
        if not module_name or not qualified_name:
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: attribute lookup "
                f"{module_name or '<unknown>'}.{qualified_name or '<unknown>'} failed"
            )

        try:
            resolved, _ = self._get_attribute_from_module(module_name, qualified_name)
        except Exception:  # noqa: BLE001
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: it's not found as {module_name}.{qualified_name}"
            ) from None

        if resolved is not value:
            raise pickle.PicklingError(
                f"Can't pickle {value!r}: "
                f"it's not the same object as {module_name}.{qualified_name}"
            )
        return module_name, qualified_name

    def build_make_cell_def_ast(self) -> stmt:
        """
        def make_cell(value):
            def _capture(v):
                def _inner():
                    return v
                return _inner
            return _capture(value).__closure__[0]
        """

        return FunctionDef(
            name="make_cell",
            args=arguments(
                posonlyargs=[],
                args=[arg(arg="value")],
                vararg=None,
                kwonlyargs=[],
                kw_defaults=[],
                kwarg=None,
                defaults=[],
            ),
            body=[
                FunctionDef(
                    name="_capture",
                    args=arguments(
                        posonlyargs=[],
                        args=[arg(arg="v")],
                        vararg=None,
                        kwonlyargs=[],
                        kw_defaults=[],
                        kwarg=None,
                        defaults=[],
                    ),
                    body=[
                        FunctionDef(
                            name="_inner",
                            args=arguments(
                                posonlyargs=[],
                                args=[],
                                vararg=None,
                                kwonlyargs=[],
                                kw_defaults=[],
                                kwarg=None,
                                defaults=[],
                            ),
                            body=[Return(value=Name(id="v"))],
                        ),
                        Return(value=Name(id="_inner")),
                    ],
                ),
                Return(
                    value=Subscript(
                        value=Attribute(
                            value=Call(
                                func=Name(id="_capture"),
                                args=[Name(id="value")],
                                keywords=[],
                            ),
                            attr="__closure__",
                            ctx=LOAD,
                        ),
                        slice=Constant(0),
                        ctx=LOAD,
                    )
                ),
            ],
        )

    def build_function_local(self, fn: types.FunctionType) -> Subscript:
        # We need `types.FunctionType`
        self.names["types"] = types  # triggers `import types` in repr/unparse

        # Build args for FunctionType(code, globals, name, defaults, closure)
        code_e = self.build_expression(fn.__code__)
        globals_e = Attribute(self.store_interprocess(builtins), "__dict__")
        name_e = Constant(fn.__name__)
        defaults_e = (
            Constant(None) if fn.__defaults__ is None else self.build_expression(fn.__defaults__)
        )

        if fn.__closure__ is None:
            closure_e: expr = Constant(None)
        else:
            self.cell_helper_required = True
            closure_e = Tuple(
                [
                    Call(
                        func=Name("make_cell"),
                        args=[self.build_expression(c.cell_contents)],
                        keywords=[],
                    )
                    for c in fn.__closure__
                ]
            )

        ctor = Attribute(value=Name("types"), attr="FunctionType", ctx=LOAD)
        new_name = self.get_name(fn)

        steps: list[expr] = [
            assign_name(
                new_name,
                Call(
                    func=ctor, args=[code_e, globals_e, name_e, defaults_e, closure_e], keywords=[]
                ),
            )
        ]

        # Set important slots via setattr (not __dict__): __kwdefaults__, __annotations__, __doc__
        slot_state: dict[Any, Any] = {}
        if fn.__kwdefaults__:
            slot_state["__kwdefaults__"] = fn.__kwdefaults__
        if fn.__annotations__:
            slot_state["__annotations__"] = fn.__annotations__
        if fn.__doc__ is not None:
            slot_state["__doc__"] = fn.__doc__

        if slot_state:
            steps.append(self.build_slot_setattrs(Name(new_name, ctx=LOAD), slot_state))

        return Subscript(Tuple(steps), Constant(0), ctx=LOAD)

    def build_setstate_call(self, new_instance: Name, state: Any) -> Call:
        return Call(
            func=Attribute(value=new_instance, attr="__setstate__"),
            args=[self.build_expression(state)],
            keywords=[],
        )

    def build_slot_setattrs(self, new_instance: Name, slot_state: dict[Any, Any]) -> Tuple:
        return Tuple(
            [
                Call(
                    func=Name("setattr"),
                    args=[
                        new_instance,
                        Constant(k),
                        self.build_expression(v),
                    ],
                    keywords=[],
                )
                for k, v in slot_state.items()
            ]
        )

    def build_dict_update(self, new_instance: Name, dict_state: dict[str, Any]) -> Call:
        return Call(
            func=Attribute(
                value=Attribute(value=new_instance, attr="__dict__"),
                attr="update",
                ctx=LOAD,
            ),
            args=[self.build_expression(dict_state)],
            keywords=[],
        )

    def build_list_appends(self, new_instance: Name, listiter: Iterable[Any]) -> Tuple:
        return Tuple(
            [
                Call(
                    func=Attribute(value=new_instance, attr="append"),
                    args=[self.build_expression(item)],
                    keywords=[],
                )
                for item in listiter
            ]
        )

    def build_dict_setitems(self, new_instance: Name, dictiter: Iterable[tuple[Any, Any]]) -> Tuple:
        return Tuple(
            [
                Call(
                    func=Attribute(value=new_instance, attr="__setitem__"),
                    args=[self.build_expression(k), self.build_expression(v)],
                    keywords=[],
                )
                for k, v in dictiter
            ]
        )

    def build_from_reduce(
        self,
        x: Any,
        obj_info: ASTObjectInfo,
        func: Callable[..., Any],
        args: Any,
        kwargs: Any,
        state: Any = None,
        listiter: Iterable[Any] | None = None,
        dictiter: Iterable[tuple[Any, Any]] | None = None,
    ) -> Subscript | Call:
        if state is None and listiter is None and dictiter is None:
            return Call(
                func=self.build_expression(cast("FunctionType", func)),
                args=[self.build_expression(item) for item in args],
                keywords=[
                    keyword(
                        arg=name,
                        value=self.build_expression(item),
                    )
                    for name, item in kwargs.items()
                ],
            )

        name = self.get_name(x)
        new_instance = Name(id=name)
        new_instance_assign = assign_name(
            name,
            Call(
                func=self.build_expression(cast("FunctionType", func)),
                args=[self.build_expression(arg) for arg in args],
                keywords=[
                    keyword(arg=k, value=self.build_expression(v)) for k, v in kwargs.items()
                ],
            ),
        )

        steps: list[expr] = [new_instance_assign]

        if state is not None:
            if hasattr(obj_info.value, "__setstate__"):
                steps.append(self.build_setstate_call(new_instance, state))
            else:
                if isinstance(state, tuple) and len(state) == 2:
                    dict_state, slot_state = state
                    if slot_state is not None:
                        steps.append(self.build_slot_setattrs(new_instance, slot_state))
                else:
                    dict_state = state

                if dict_state is not None:
                    steps.append(self.build_dict_update(new_instance, dict_state))

        if listiter is not None:
            steps.append(self.build_list_appends(new_instance, listiter))

        if dictiter is not None:
            steps.append(self.build_dict_setitems(new_instance, dictiter))

        return Subscript(Tuple(steps), Constant(0))

    def build_immutable(
        self, x: ImmutableType | ImmutableCollectionType, *, not_const: bool = False
    ) -> Name | Constant[ImmutableType | ImmutableCollectionType] | Attribute | Subscript | Call:
        # can't look up by value since {True: True}[1] will return True
        # could store tuple[type[T], T], but considering that these objects should be immortal
        # this should work just fine
        if (cached := CACHE.get(id(x), _nil)) is not _nil:
            return cached  # type: ignore[return-value]

        if not_const or type(x) not in CONST_TYPES:
            # can't use Constant with types in ast (which makes sense, there's no literals for them)
            # it's possible to substitute LOAD_GLOBAL with LOAD_CONST later in the bytecode,
            # but it's quite slow (with libs from PyPi), and doesn't give a big performance uplift
            # later, so I'm ignoring this for now
            return self.store_interprocess(x) if self.interprocess else self.store(x)

        return Constant(value=x)

    def build_list(self, x: list[Any], obj_info: ASTObjectInfo) -> List | Subscript:
        elts = [self.build_expression(i) for i in x]

        if obj_info.reflective_refs is None:
            return List(elts)

        return Subscript(
            value=Tuple(
                [
                    assign_name(self.get_name(x), List([])),
                    Call(
                        func=Attribute(value=Name(id=self.get_name(x)), attr="extend"),
                        args=[Tuple(elts)],
                        keywords=[],
                    ),
                ],
            ),
            slice=Constant(value=0),
        )

    def build_set(self, x: set[Any], obj_info: ASTObjectInfo) -> Set | Subscript:
        elts = [self.build_expression(i) for i in x]

        if obj_info.reflective_refs is None:
            return Set(elts)

        return Subscript(
            value=Tuple(
                elts=[
                    assign_name(self.get_name(x), Set([])),
                    Call(
                        func=Attribute(value=Name(id=self.get_name(x)), attr="update"),
                        args=[Tuple(elts)],
                        keywords=[],
                    ),
                ],
            ),
            slice=Constant(value=0),
        )

    def build_dict(self, x: dict[Any, Any], obj_info: ASTObjectInfo) -> Dict | Subscript:
        keys = [self.build_expression(i) for i in x]
        values = [self.build_expression(i) for i in x.values()]

        if obj_info.reflective_refs is None:
            return Dict(keys=keys, values=values)

        name = self.get_name(x)
        return Subscript(
            value=Tuple(
                elts=[
                    assign_name(name, Dict(keys=[], values=[])),
                    Call(
                        func=Attribute(value=Name(id=name), attr="update"),
                        args=[
                            Call(
                                func=Name(id="zip"),
                                args=[Tuple(keys), Tuple(values)],
                                keywords=[],
                            )
                        ],
                        keywords=[],
                    ),
                ],
            ),
            slice=Constant(value=0),
        )

    def build_reference_injection(self, name: str, reference: AST, value: AST) -> expr:
        """
        Emit AST that injects `value` into the `reference` location.
        Supports:
          - list/tuple elts
          - dict keys or values
          - attribute assignment (via setattr)
        """
        parent = reference.parent
        container = reference.container
        location = reference.location

        if isinstance(container, list) and isinstance(parent, List | Tuple):
            # parent is, e.g. List(elts=[...])
            return Call(
                func=Attribute(Name(name), "__setitem__"),
                args=[
                    Constant(location),  # index
                    value,
                ],
                keywords=[],
            )

        if isinstance(parent, Dict):
            if container is parent.keys:
                key = value
                val: AST = parent.values[cast("int", location)]
            else:
                key = parent.keys[cast("int", location)]
                val = value

            return Call(
                func=Attribute(Name(name), "__setitem__"),
                args=[
                    key,
                    val,
                ],
                keywords=[],
            )

        if isinstance(parent, Attribute):
            return Call(
                func=self.build_immutable(cast("ImmutableType", setattr)),
                args=[
                    Name(name),
                    Constant(parent.attr),
                    value,
                ],
                keywords=[],
            )

        raise NotImplementedError(
            f"Injection for reference inside {type(parent)} is not implemented yet"
        )

    def build_tuple(self, x: tuple[Any, ...] | frozenset[Any], obj_info: ASTObjectInfo) -> expr:
        immutable = True
        not_const = False
        values = [
            expression
            for i in x
            if (  # this is a tuple of two expressions, always results in True
                # constructing list with list comprehension should be faster
                # than appending values, but we need to check each one individually as well,
                # so we're doing it with Lennon's (or Paul's?) operator.
                (expression := self.build_expression(i)),
                (
                    immutable := immutable
                    and (
                        isinstance(expression, Constant)
                        or (
                            not_const := isinstance(expression, Name)
                            and self.names.get(expression.id) is i
                        )  # True for types and functions
                    )
                ),
            )
        ]

        if immutable and not self.interprocess:
            return self.build_immutable(x, not_const=not_const)

        if obj_info.reflective_refs is None:
            return Tuple(values)

        tuple_expr = Tuple(values)
        injections = []
        tuple_name = self.get_name(x)
        for name_reference_to_this_tuple in obj_info.reflective_refs:
            expression_that_referenced_this_tuple = name_reference_to_this_tuple.parent
            if expression_that_referenced_this_tuple is None:
                raise RuntimeError(
                    "Tuple was referenced by one of its elements, "
                    "but parent for this element wasn't set."
                    "Parent is required to store reference to this element in order "
                    "to inject tuple after its construction."
                )

            # Find the object that contains this expression
            expression_obj_info = None
            for other_obj_info in self.objects.values():
                if other_obj_info.expression is expression_that_referenced_this_tuple:
                    expression_obj_info = other_obj_info
                    break

            if expression_obj_info is None:
                raise RuntimeError("Could not find object info for referencing expression")

            name = self.get_name(expression_obj_info.value)
            self.store_expression(expression_that_referenced_this_tuple, name)

            # replace premature name reference to the tuple with None
            name_reference_to_this_tuple.container[name_reference_to_this_tuple.location] = (  # type: ignore[index]
                Constant(None)
            )

            injections.append(
                self.build_reference_injection(name, name_reference_to_this_tuple, Name(tuple_name))
            )

        return Subscript(
            value=Tuple([NamedExpr(Name(tuple_name, ctx=STORE), tuple_expr), *injections]),
            slice=Constant(0),
            ctx=LOAD,
        )

    def build_method_deep(self, x: types.MethodType, obj_info: ASTObjectInfo) -> Call:
        return Call(
            func=self.build_immutable(obj_info.cls),
            args=[
                self.build_immutable(cast("ImmutableType", x.__func__)),
                self.build_expression(x.__self__),
            ],
            keywords=[],
        )

    def build_expression(self, x: Any) -> expr:
        """"""
        cls = type(x)
        if (
            (
                cls
                in (
                    IMMUTABLE_NON_COLLECTIONS
                    if not self.interprocess
                    else IMMUTABLE_CONSTANTS_OR_IMPORTABLE
                )
            )
            or issubclass(cls, type)
            or (self.interprocess and issubclass(cls, Enum))
        ):
            return self.build_immutable(x)

        if cls is tuple and not x:  # avoid memorizing it
            return EMPTY_TUPLE_CONSTANT

        obj_info = self.get_or_create_object_info(x)
        result: expr

        existing = self.check_object_state(obj_info)
        if existing is not None:
            return existing

        # Dispatch based on type - all functions now take ObjectInfo
        if cls is dict:
            result = self.build_dict(x, obj_info)
        elif cls is list:
            result = self.build_list(x, obj_info)
        elif cls is set:
            result = self.build_set(x, obj_info)
        elif cls is tuple or cls is frozenset:
            result = self.build_tuple(x, obj_info)
            if cls is frozenset and isinstance(result, Tuple):
                result = Call(Name("frozenset"), args=[result], keywords=[])
        elif cls is types.ModuleType:
            result = self.build_immutable(x)
        elif cls is types.MethodType:
            result = self.build_method_deep(x, obj_info)
        elif cls is property:
            result = self.build_property(x, obj_info)
        elif cls is types.CodeType:
            result = self.build_from_reduce(
                x, obj_info, cls, map(x.__getattribute__, CODE_ATTRIBUTES), {}
            )
        elif (
            not (self.ignore_deepcopy_method or self.interprocess)
            and (__deepcopy__ := getattr(x, "__deepcopy__", None)) is not None
        ):
            # get a deepcopied version of the object and bake it into the blueprint
            deepcopied = __deepcopy__(SentinelMemo(obj_info.vid, self.objects, ASTObjectInfo))
            if deepcopied is x:  # no need to call __deepcopy__ on each reconstruction
                result = self.build_immutable(x)
            else:
                result = Call(self.store(deepcopied.__deepcopy__), [Dict([], [])], [])
        else:
            rv = get_reduce(x, cls)
            if isinstance(rv, str):  # global name
                result = self.build_immutable(x)
            else:
                func, args, kwargs, state, listiter, dictiter = debunk_reduce(
                    rv, cls=cls, try_simplify_call=True
                )
                result = self.build_from_reduce(
                    x, obj_info, func, args, kwargs, state, listiter, dictiter
                )

        return self.finalize_object(obj_info, result)

    def build_property(self, x: property, obj_info: ASTObjectInfo) -> Call | Attribute | Subscript:
        getter = cast("FunctionType", x.fget)
        if "." in getter.__qualname__:
            parent = getter.__globals__[getter.__qualname__.split(".")[0]]
            if getattr(parent, getter.__name__) is x:
                return Attribute(self.build_immutable(parent), getter.__name__)

        return self.build_from_reduce(
            x, obj_info, obj_info.cls, (x.fget, x.fset, x.fdel, x.__doc__), {}
        )

    def build_imports(self) -> list[Import | ImportFrom]:
        imports: list[Import | ImportFrom] = []
        for namespace_name, item in self.names.items():
            if item is types.NoneType:
                continue
            if isinstance(item, str):
                # FIXME: temp
                continue
            names = [
                alias(
                    item.__name__
                    if getattr(item, "__name__", None) and item.__name__.isidentifier()
                    else namespace_name,
                    asname=namespace_name
                    if namespace_name != getattr(item, "__name__", None)
                    and getattr(item, "__name__", "<>").isidentifier()
                    else None,
                )
            ]
            if namespace_name not in DEFAULT_NAMESPACE:
                if isinstance(item, types.ModuleType):
                    imports.append(Import(names))
                else:
                    imports.append(ImportFrom(item.__module__, names))
        return imports


_nil: Final = object()


def assign_name(name: str, value: E) -> NamedExpr[E]:
    return NamedExpr(
        target=Name(
            id=name,
            ctx=STORE,
        ),
        value=value,
    )


def build_reconstructor(
    x: T, keep_by_reference: dict[int, Any] | None = None, *, ignore_deepcopy_method: bool = False
) -> Callable[[], T]:
    ast_builder = ASTBuilder(
        keep_by_reference, ignore_deepcopy_method=ignore_deepcopy_method, interprocess=False
    )

    name = type(x).__name__.lower()
    return_value_ast = ast_builder.build_expression(x)

    return create_function(
        f"reconstruct_{name}",
        [Return(value=return_value_ast)],
        ast_builder,
    )


def create_function(name: str, body: list[stmt], builder: ASTBuilder) -> FunctionType:
    module: Final = Module(body=[function_def := FunctionDef(name=name, body=body)])
    function_def.name = name
    filename = f"<duper {uuid.uuid4()}>"
    code = compile(module, filename, "exec")  # type: ignore[call-overload]

    full_ns = {**globals(), **builder.names}
    exec(code, full_ns)  # noqa: S102 (this is trusted code that we've just compiled from AST
    function: FunctionType = full_ns[name]
    function.__module__ = __name__
    function.__ast__ = function_def  # type: ignore[attr-defined]
    linecache.cache[filename] = (0, None, LazySourceLines(function, filename), filename)  # type: ignore[assignment]
    return function


def reprx(x: T, name: str | None = None) -> str:
    """
    Generate a Python source code that would reconstruct object equivalent to `x`.
    """
    builder = ASTBuilder({}, ignore_deepcopy_method=True, interprocess=True)
    if name is None:
        name = f"reconstruct_{type(x).__name__.lower()}"
    return_value_ast = builder.build_expression(x)
    return ast.unparse(
        Module(
            body=[
                *builder.build_imports(),
                *((builder.build_make_cell_def_ast(),) if builder.cell_helper_required else ()),
                FunctionDef(  # type: ignore[arg-type]
                    [
                        Return(value=return_value_ast),
                    ],
                    name,
                ),
                Assign([Name("__duper_reconstructor__")], Name(name)),
            ]
        )
    )
