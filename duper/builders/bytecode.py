# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""
Direct bytecode builder
"""

from __future__ import annotations

import array
import builtins
import dis
import opcode
import sys
import types
from functools import partial
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import Literal
from typing import TypeVar
from typing import cast

from duper.builders._helpers import SentinelMemo
from duper.builders._helpers import forbid_references
from duper.builders._tracking import BytecodeObjectInfo
from duper.builders.runtime import debunk_reduce
from duper.builders.runtime import get_reduce
from duper.constants import IMMUTABLE_NON_COLLECTIONS
from duper.constants import ImmutableCollectionType
from duper.constants import ImmutableType
from duper.debug import run_in_xpython

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Sequence
import warnings

warnings.warn(
    "This module is experimental and may lead to python crashes. Don't use it on production.",
    stacklevel=2,
)

RAISE_ON_REFLEXIVE: Final = True

LINETABLE: Final = b"\x00\x01" if sys.version_info >= (3, 10) else b""

T = TypeVar("T")

# Python 3.12+ opcodes
RESUME: Final = dis.opmap["RESUME"]
POP_TOP: Final = dis.opmap["POP_TOP"]
PUSH_NULL: Final = dis.opmap["PUSH_NULL"]
NOP: Final = dis.opmap["NOP"]
COPY: Final = dis.opmap["COPY"]
SWAP: Final = dis.opmap["SWAP"]
RETURN_VALUE: Final = dis.opmap["RETURN_VALUE"]
STORE_NAME: Final = dis.opmap["STORE_NAME"]
DELETE_NAME: Final = dis.opmap["DELETE_NAME"]
UNPACK_SEQUENCE: Final = dis.opmap["UNPACK_SEQUENCE"]
FOR_ITER: Final = dis.opmap["FOR_ITER"]
STORE_ATTR: Final = dis.opmap["STORE_ATTR"]
DELETE_ATTR: Final = dis.opmap["DELETE_ATTR"]
STORE_GLOBAL: Final = dis.opmap["STORE_GLOBAL"]
DELETE_GLOBAL: Final = dis.opmap["DELETE_GLOBAL"]
LOAD_CONST: Final = dis.opmap["LOAD_CONST"]
LOAD_NAME: Final = dis.opmap["LOAD_NAME"]
BUILD_TUPLE: Final = dis.opmap["BUILD_TUPLE"]
BUILD_LIST: Final = dis.opmap["BUILD_LIST"]
BUILD_SET: Final = dis.opmap["BUILD_SET"]
BUILD_MAP: Final = dis.opmap["BUILD_MAP"]
LOAD_ATTR: Final = dis.opmap["LOAD_ATTR"]
COMPARE_OP: Final = dis.opmap["COMPARE_OP"]
IMPORT_NAME: Final = dis.opmap["IMPORT_NAME"]
IMPORT_FROM: Final = dis.opmap["IMPORT_FROM"]
JUMP_FORWARD: Final = dis.opmap["JUMP_FORWARD"]
LOAD_GLOBAL: Final = dis.opmap["LOAD_GLOBAL"]
LOAD_FAST: Final = dis.opmap["LOAD_FAST"]
STORE_FAST: Final = dis.opmap["STORE_FAST"]
DELETE_FAST: Final = dis.opmap["DELETE_FAST"]
LOAD_DEREF: Final = dis.opmap["LOAD_DEREF"]
STORE_DEREF: Final = dis.opmap["STORE_DEREF"]
DELETE_DEREF: Final = dis.opmap["DELETE_DEREF"]
JUMP_BACKWARD: Final = dis.opmap["JUMP_BACKWARD"]
CALL: Final = dis.opmap["CALL"]
KW_NAMES: Final = dis.opmap["KW_NAMES"]
LIST_EXTEND: Final = dis.opmap["LIST_EXTEND"]
SET_UPDATE: Final = dis.opmap["SET_UPDATE"]
DICT_UPDATE: Final = dis.opmap["DICT_UPDATE"]
DICT_MERGE: Final = dis.opmap["DICT_MERGE"]
MAP_ADD: Final = dis.opmap["MAP_ADD"]
BINARY_SUBSCR: Final = dis.opmap["BINARY_SUBSCR"]
STORE_SUBSCR: Final = dis.opmap["STORE_SUBSCR"]
LIST_APPEND: Final = dis.opmap["LIST_APPEND"]

# Special opcodes
CACHE: Final = dis.opmap["CACHE"]
EXTENDED_ARG: Final = dis.opmap["EXTENDED_ARG"]

_inline_cache_entries: dict[int, int] | Sequence[int] = getattr(
    opcode, "_inline_cache_entries", (0,) * 256
)
if isinstance(_inline_cache_entries, dict):
    _inline_cache_entries = [_inline_cache_entries.get(op, 0) for op in range(256)]

# we could've used fixed-length tuple here, but it's actually slower:
# https://github.com/python/mypy/issues/19537
INLINE_CACHE_ENTRIES: Final[tuple[tuple[int, ...] | None, ...]] = tuple(
    [(0,) * cache_ops for cache_ops in _inline_cache_entries]
)


Const = int
Name = int
Varname = int


class Bytecode:
    def __init__(self, name: str = "<duper>") -> None:
        self.name = name
        self.units: array.array[int] = array.array("H")
        self.consts: list[Any] = []
        self.names: list[str] = []
        self.varnames: list[str] = []
        self.const_map: dict[int, Const] = {}
        self.const_value_map: dict[tuple[type, Any], Const] = {}
        self.name_map: dict[str, Name] = {}
        self.var_map: dict[str, Varname] = {}
        self.stack_size = 0
        self.max_stack_size = 0
        self._emit(RESUME, 0)

    def _emit_codeunit(self, op: int, arg: int) -> None:
        """Emit a single 16-bit code unit."""
        self.units.append((arg & 0xFF) << 8 | (op & 0xFF))

    def _emit(self, op: int, arg: int | None = None) -> None:
        """Emit an opcode with cache slots."""
        if arg is None:
            arg = 0

        hi = arg >> 8
        lo = arg & 0xFF
        if hi:
            self._emit_codeunit(EXTENDED_ARG, hi)
        self._emit_codeunit(op, lo)

        if caches := INLINE_CACHE_ENTRIES[op]:
            self.units.extend(caches)

    def add_const(self, value: Any) -> int:
        """Add constant to constants table."""
        try:
            key: tuple[type[Any], Any] = (type(value), value)
            if (idx := self.const_value_map.get(key)) is not None:
                return idx

            idx = len(self.consts)
            self.consts.append(value)
            self.const_value_map[key] = idx
        except TypeError:
            pass
        else:
            return idx

        # FIXME: the way to handle consts above should be the only one, probably
        #  The way below was my intuition about how it could be improved
        #  and it makes all stdlib tests pass, however it's inefficient for
        #  equivalent objects with different ids
        #  But the real issue here is that we're even trying to store unhashable object here
        #  (we're ending up here when trying to reconstruct WeakKeyDictionary

        vid = id(value)
        if (idx := self.const_map.get(vid)) is not None:
            return idx

        idx = len(self.consts)
        self.consts.append(value)
        self.const_map[vid] = idx
        return idx

    def add_name(self, name: str) -> int:
        """Add name to names table."""
        if (idx := self.name_map.get(name)) is not None:
            return idx

        idx = len(self.names)
        self.names.append(name)
        self.name_map[name] = idx
        return idx

    def add_var(self, name: str) -> int:
        """Add variable name."""
        if (idx := self.var_map.get(name)) is not None:
            return idx
        idx = len(self.varnames)
        self.varnames.append(name)
        self.var_map[name] = idx
        return idx

    def update_stack(self, delta: int) -> None:
        """Update stack size tracking."""
        self.stack_size += delta
        self.max_stack_size = max(self.max_stack_size, self.stack_size)

    def load_const(self, value: Any) -> None:
        """Emit LOAD_CONST for a value."""
        idx = self.add_const(value)
        self._emit(LOAD_CONST, idx)
        self.update_stack(1)

    def load_global(self, name: str) -> None:
        """Emit LOAD_GLOBAL for a global name with NULL."""
        idx = self.add_name(name)
        # LOAD_GLOBAL with low bit set pushes NULL + value for calling
        arg = (idx << 1) | 1
        self._emit(LOAD_GLOBAL, arg)
        self.update_stack(2)  # Pushes NULL + value

    def load_attr(self, name: str, *, is_method: bool = False) -> None:
        """Emit LOAD_ATTR for attribute access."""
        idx = self.add_name(name)
        # In Python 3.12, LOAD_ATTR uses the low bit to indicate method call
        # If low bit is set, it's a method call and will push NULL/self
        # If low bit is clear, it's a regular attribute access
        arg = (idx << 1) | (1 if is_method else 0)
        self._emit(LOAD_ATTR, arg)
        if is_method:
            self.update_stack(1)  # Method calls push an extra NULL/self
        # Stack: obj -> result (+ NULL/self for methods)

    def store_fast(self, name: str) -> None:
        """Store TOS in a local variable."""
        idx = self.add_var(name)
        self._emit(STORE_FAST, idx)
        self.update_stack(-1)

    def load_fast(self, name: str) -> None:
        """Load a local variable."""
        idx = self.add_var(name)
        self._emit(LOAD_FAST, idx)
        self.update_stack(1)

    def build_tuple(self, count: int) -> None:
        """Build tuple from TOS items."""
        self._emit(BUILD_TUPLE, count)
        self.update_stack(-count + 1)

    def build_list(self, count: int) -> None:
        """Build list from TOS items."""
        self._emit(BUILD_LIST, count)
        self.update_stack(-count + 1)

    def build_map(self, count: int) -> None:
        """Build dict from TOS key-value pairs."""
        self._emit(BUILD_MAP, count)
        self.update_stack(-2 * count + 1)

    def build_set(self, count: int) -> None:
        """Build set from TOS items."""
        self._emit(BUILD_SET, count)
        self.update_stack(-count + 1)

    def push_null(self) -> None:
        self._emit(PUSH_NULL)
        self.update_stack(1)

    def call(self, argc: int) -> None:
        # Ensure to PUSH_NULL before args
        # TODO: generalize and abstract this away
        self._emit(CALL, argc)
        self.update_stack(-argc - 1)

    def call_method(self, argc: int) -> None:
        # Method calls use CALL, stack has NULL + method + args from LOAD_ATTR is_method=True
        self._emit(CALL, argc)
        self.update_stack(-argc - 2)  # Remove NULL + method + args

    def kw_names(self, names: tuple[str, ...]) -> None:
        """Set keyword argument names for the next CALL."""
        idx = self.add_const(names)
        self._emit(KW_NAMES, idx)
        # KW_NAMES doesn't affect the stack

    def binary_subscr(self) -> None:
        """TOS = TOS1[TOS]."""
        self._emit(BINARY_SUBSCR)
        self.update_stack(-1)

    def store_subscr(self) -> None:
        """TOS1[TOS] = TOS2."""
        self._emit(STORE_SUBSCR)
        self.update_stack(-3)

    def pop_top(self) -> None:
        """Remove TOS."""
        self._emit(POP_TOP)
        self.update_stack(-1)

    def list_extend(self, count: int = 1) -> None:
        """Extend list on TOS1 with iterable TOS."""
        self._emit(LIST_EXTEND, count)
        self.update_stack(-1)

    def set_update(self, count: int = 1) -> None:
        """Update set on TOS1 with iterable TOS."""
        self._emit(SET_UPDATE, count)
        self.update_stack(-1)

    def dict_update(self, count: int = 1) -> None:
        """Update dict on TOS1 with dict/iterable TOS."""
        self._emit(DICT_UPDATE, count)
        self.update_stack(-1)

    def return_value(self) -> None:
        """Return TOS."""
        self._emit(RETURN_VALUE)
        self.update_stack(-1)

    def copy(self, n: int) -> None:
        """Copy the n-th item to TOS."""
        self._emit(COPY, n)
        self.update_stack(1)

    def swap(self, n: int = 2) -> None:
        """Swap TOS with the n-th item."""
        self._emit(SWAP, n)
        # No stack change

    def list_append(self, i: int = 1) -> None:
        """Append TOS to list at TOS-(i+1)."""
        self._emit(LIST_APPEND, i)
        self.update_stack(-1)

    def insert_after_position(self, pos: int, var_name: str) -> None:
        """Insert COPY 1; STORE_FAST after the given position."""
        # Create new instructions
        copy_unit = (1 << 8) | (COPY & 0xFF)
        idx = self.add_var(var_name)
        store_unit = (idx << 8) | (STORE_FAST & 0xFF)
        self.units.insert(pos + 1, copy_unit)
        self.units.insert(pos + 2, store_unit)

    def to_function(self) -> types.FunctionType:
        """Convert bytecode to a callable function."""
        self.return_value()

        # Create code object
        code = types.CodeType(  # type: ignore[call-arg, unused-ignore]
            0,  # argcount
            0,  # posonlyargcount
            0,  # kwonlyargcount
            len(self.varnames),  # nlocals
            self.max_stack_size + 10,  # stacksize (with buffer)
            3,  # flags (OPTIMIZED | NEWLOCALS)
            self.units.tobytes(),  # codestring
            tuple(self.consts),  # constants
            tuple(self.names),  # names
            tuple(self.varnames),  # varnames
            "<duper>",  # filename
            self.name,  # name
            "<duper>",  # type: ignore[arg-type, unused-ignore]
            1,  # type: ignore[arg-type, unused-ignore]
            LINETABLE,  # type: ignore[arg-type, unused-ignore]
            b"",  # type: ignore[arg-type, unused-ignore]
            (),  # freevars
            (),  # cellvars
        )

        # Create function
        return types.FunctionType(code, globals(), self.name)


class BytecodeCompiler:
    """Tracks object reconstruction state using single lookup."""

    def __init__(
        self,
        bytecode: Bytecode,
        memo: dict[int, Any] | None,
        *,
        ignore_deepcopy_method: bool,
    ) -> None:
        self.bytecode = bytecode
        self.objects: dict[int, BytecodeObjectInfo] = {}
        self.keep_by_reference = memo
        self.used_names: set[str] = set(builtins.__dict__)
        self.names: dict[str, Any] = {}  # External objects to inject
        self.ignore_deepcopy_method = ignore_deepcopy_method

    def get_or_create_object_info(self, value: Any) -> BytecodeObjectInfo:
        """Single lookup/creation point. Returns ObjectInfo for direct manipulation."""
        vid = id(value)
        obj_info = self.objects.get(vid)
        if obj_info is None:
            external_value = None
            if self.keep_by_reference is not None:
                external_value = self.keep_by_reference.get(vid)
            obj_info = BytecodeObjectInfo(vid, value, type(value), external_value)
            self.objects[vid] = obj_info
        return obj_info

    def get_name(self, obj_info: BytecodeObjectInfo) -> str:
        """Assigns names and resolves collisions using ObjectInfo directly."""
        if obj_info.name is not None:
            return obj_info.name

        name: str | None
        if (name := getattr(obj_info.value, "__qualname__", None)) is None:
            name = obj_info.cls.__name__.lower()

        i = 1
        base_name = name
        while name in self.used_names:
            name = f"{base_name}_{i}"
            i += 1

        obj_info.name = name
        self.used_names.add(name)
        return name

    def check_object_state(self, obj_info: BytecodeObjectInfo) -> str | None:
        """Check if object can be referenced directly or needs reconstruction."""
        if obj_info.exclusive_for:
            forbid_references(obj_info.value)

        # Object is stored in a variable - just load it
        if obj_info.var_name is not None:
            self.bytecode.load_fast(obj_info.var_name)
            return obj_info.var_name

        # External reference from memo
        if obj_info.external_value is not None:
            self.bytecode.load_const(obj_info.external_value)
            name = self.get_name(obj_info)
            self.bytecode.store_fast(name)
            obj_info.var_name = name
            return name

        # Currently being reconstructed - this is a self-reference
        if obj_info.is_reconstructing:
            if RAISE_ON_REFLEXIVE and isinstance(obj_info.value, list | set | dict | tuple):
                raise NotImplementedError
            name = self.get_name(obj_info)
            if obj_info.reflective_refs is None:
                obj_info.reflective_refs = []
            obj_info.reflective_refs.append(name)
            self.bytecode.load_fast(name)  # Load the reference (will be filled later)
            return name

        # Second encounter - patch first occurrence to store it
        if obj_info.first_construction_position is not None:
            name = self.get_name(obj_info)
            self.bytecode.insert_after_position(obj_info.first_construction_position, name)
            obj_info.var_name = name
            self.bytecode.load_fast(name)
            return name

        # First encounter - mark it
        obj_info.is_reconstructing = True
        return None

    def finalize_object(self, obj_info: BytecodeObjectInfo, name: str | None = None) -> None:
        """Mark object as fully reconstructed."""
        obj_info.is_reconstructing = False
        if name:
            obj_info.var_name = name
        else:
            obj_info.first_construction_position = len(self.bytecode.units) - 1

    def emit_immutable(self, x: ImmutableType | ImmutableCollectionType) -> None:
        """Emit bytecode to load an immutable object."""
        # Bytecode allows LOAD_CONST for any object, not just primitives
        self.bytecode.load_const(x)

    def emit_list(self, x: list[Any], obj_info: BytecodeObjectInfo) -> None:
        """Emit bytecode to reconstruct a list."""

        if obj_info.reflective_refs is None:
            # Simple case - build list directly
            for item in x:
                self.emit_expression(item)
            self.bytecode.build_list(len(x))
        else:
            if RAISE_ON_REFLEXIVE:
                raise NotImplementedError
            # Self-referential list - create empty first
            name = self.get_name(obj_info)
            self.bytecode.build_list(0)
            self.bytecode.store_fast(name)
            obj_info.var_name = name

            # Build items tuple
            for item in x:
                self.emit_expression(item)
            self.bytecode.build_tuple(len(x))

            # Call extend
            self.bytecode.load_fast(name)
            self.bytecode.load_attr("extend", is_method=True)
            self.bytecode.swap(2)
            self.bytecode.call_method(1)
            self.bytecode.pop_top()

            # Load result
            self.bytecode.load_fast(name)

    def emit_dict(self, x: dict[Any, Any], obj_info: BytecodeObjectInfo) -> None:
        """Emit bytecode to reconstruct a dict."""

        if obj_info.reflective_refs is None:
            # Simple case
            for key, value in x.items():
                self.emit_expression(key)
                self.emit_expression(value)
            self.bytecode.build_map(len(x))
        else:
            if RAISE_ON_REFLEXIVE:
                raise NotImplementedError
            name = self.get_name(obj_info)
            self.bytecode.build_map(0)
            self.bytecode.store_fast(name)
            obj_info.var_name = name

            # Build keys and values tuples
            for key in x:
                self.emit_expression(key)
            self.bytecode.build_tuple(len(x))

            for value in x.values():
                self.emit_expression(value)
            self.bytecode.build_tuple(len(x))

            # Call update with zip
            self.bytecode.load_fast(name)
            self.bytecode.load_attr("update", is_method=True)
            self.bytecode.load_const(zip)
            self.bytecode.swap(3)
            self.bytecode.swap(2)
            self.bytecode.call(2)
            self.bytecode.call(1)
            self.bytecode.pop_top()

            # Load result
            self.bytecode.load_fast(name)

    def emit_set(self, x: set[Any], obj_info: BytecodeObjectInfo) -> None:
        """Emit bytecode to reconstruct a set."""

        if obj_info.reflective_refs is None:
            # Simple case
            for item in x:
                self.emit_expression(item)
            self.bytecode.build_set(len(x))
        else:
            if RAISE_ON_REFLEXIVE:
                raise NotImplementedError
            name = self.get_name(obj_info)
            self.bytecode.build_set(0)
            self.bytecode.store_fast(name)
            obj_info.var_name = name

            # Build items tuple
            for item in x:
                self.emit_expression(item)
            self.bytecode.build_tuple(len(x))

            # Call update
            self.bytecode.load_fast(name)
            self.bytecode.load_attr("update", is_method=True)
            self.bytecode.swap(2)
            self.bytecode.call_method(1)
            self.bytecode.pop_top()

            # Load result
            self.bytecode.load_fast(name)

    def emit_tuple(self, x: tuple[Any, ...] | frozenset[Any], obj_info: BytecodeObjectInfo) -> None:
        """Emit bytecode to reconstruct a tuple or frozenset."""

        # For tuples, check if it's immutable and can be loaded as const
        if isinstance(x, tuple) and is_deeply_immutable(x):  # I'd prefer only one pass,
            self.emit_immutable(x)
            return

        # Check for self-references
        if obj_info.reflective_refs is None:
            # Simple case
            if isinstance(x, frozenset):
                self.bytecode.push_null()
                self.bytecode.load_const(frozenset)
                for item in x:
                    self.emit_expression(item)
                self.bytecode.build_tuple(len(x))
                self.bytecode.call(1)
            else:
                for item in x:
                    self.emit_expression(item)
                self.bytecode.build_tuple(len(x))
        else:
            if RAISE_ON_REFLEXIVE:
                raise NotImplementedError
            tuple_name = self.get_name(obj_info)

            # First pass: build tuple with None placeholders for self-refs
            ref_positions = []
            for i, item in enumerate(x):
                if obj_info.reflective_refs and any(
                    ref == tuple_name for ref in obj_info.reflective_refs
                ):
                    self.bytecode.load_const(None)
                    ref_positions.append(i)
                else:
                    self.emit_expression(item)

            self.bytecode.build_tuple(len(x))
            self.bytecode.store_fast(tuple_name)
            obj_info.var_name = tuple_name

            # Now inject the actual tuple into the positions
            for pos in ref_positions:
                # Load the object that referenced the tuple
                self.bytecode.load_fast(tuple_name)
                self.bytecode.load_const(pos)
                self.bytecode.load_fast(tuple_name)
                self.bytecode.store_subscr()

            # Load final result
            self.bytecode.load_fast(tuple_name)

    def emit_setstate_call(self, var: str, state: Any) -> None:
        """Emit bytecode for obj.__setstate__(state)."""
        self.bytecode.load_fast(var)
        self.bytecode.load_attr("__setstate__", is_method=True)
        self.emit_expression(state)
        self.bytecode.call_method(1)
        self.bytecode.pop_top()

    def emit_slot_setattrs(self, var: str, slot_state: dict[Any, Any]) -> None:
        """Emit bytecode for setattr calls on slots."""
        for k, v in slot_state.items():
            self.bytecode.push_null()
            self.bytecode.load_const(setattr)
            self.bytecode.load_fast(var)
            self.bytecode.load_const(k)
            self.emit_expression(v)
            self.bytecode.call(3)
            self.bytecode.pop_top()

    def emit_dict_update(self, var: str, dict_state: dict[str, Any]) -> None:
        """Emit bytecode for obj.__dict__.update(state)."""
        self.bytecode.load_fast(var)
        self.bytecode.load_attr("__dict__", is_method=False)  # Regular attribute access
        self.emit_expression(dict_state)
        self.bytecode.dict_update()
        self.bytecode.pop_top()

    def emit_list_appends(self, var: str, listiter: Iterable[Any]) -> None:
        """Emit bytecode for list comprehension that appends items."""
        for item in listiter:
            self.bytecode.load_fast(var)
            self.bytecode.load_attr("append", is_method=True)
            self.emit_expression(item)
            self.bytecode.call_method(1)
            self.bytecode.pop_top()

    def emit_dict_setitems(self, var: str, dictiter: Iterable[tuple[Any, Any]]) -> None:
        """Emit bytecode for dict comprehension that sets items."""

        # Convert dictiter to list first
        items = list(dictiter)

        # Build the list of tuples
        for key, value in items:
            self.emit_expression(value)
            self.emit_expression(key)
            self.bytecode.load_fast(var)
            self.bytecode.load_attr("__setitem__", is_method=True)
            self.bytecode.swap(3)  # -> ["value", "__setitem__", "NULL", "key"]
            self.bytecode.swap(2)  # -> ["value", "__setitem__", "key", "NULL"]
            self.bytecode.swap(4)  # -> ["NULL", "__setitem__", "key", "value"]
            self.bytecode.call_method(2)
            self.bytecode.pop_top()

    def emit_from_reduce(
        self,
        x: Any,
        obj_info: BytecodeObjectInfo,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        state: Any = None,
        listiter: Iterable[Any] | None = None,
        dictiter: Iterable[tuple[Any, Any]] | None = None,
    ) -> None:
        """Emit bytecode to reconstruct object using __reduce__ protocol."""

        if state is None and listiter is None and dictiter is None:
            # Simple case - just call the function
            if hasattr(func, "__qualname__") and func.__qualname__.endswith(".__new__"):
                # Special handling for __new__ methods - load via LOAD_ATTR
                if args and hasattr(args[0], "__name__"):
                    self.bytecode.load_const(args[0])  # Load the class
                    self.bytecode.load_attr("__new__", is_method=True)  # Load __new__ as method
                    # Load all arguments (including args[0] as first argument to method)
                    for arg in args:
                        self.emit_expression(arg)
                    # Handle keyword arguments
                    if kwargs:
                        for value in kwargs.values():
                            self.emit_expression(value)
                        self.bytecode.kw_names(tuple(kwargs.keys()))
                        self.bytecode.call(len(args) + len(kwargs))
                    else:
                        self.bytecode.call(len(args))
                else:
                    self.bytecode.push_null()
                    self.bytecode.load_const(func)
                    for arg in args:
                        self.emit_expression(arg)
                    self.bytecode.call(len(args))
            elif isinstance(func, type):
                # Class constructor - use regular function call
                self.bytecode.push_null()
                self.bytecode.load_const(func)
                for arg in args:
                    self.emit_expression(arg)
                # Handle keyword arguments for classes
                if kwargs:
                    for value in kwargs.values():
                        self.emit_expression(value)
                    self.bytecode.kw_names(tuple(kwargs.keys()))
                    self.bytecode.call(len(args) + len(kwargs))
                else:
                    self.bytecode.call(len(args))
            else:
                self.bytecode.push_null()
                self.bytecode.load_const(func)
                for arg in args:
                    self.emit_expression(arg)
                self.bytecode.call(len(args))

            return

        # Complex case - need to store intermediate result
        name = self.get_name(obj_info)

        # Call constructor
        if hasattr(func, "__qualname__") and func.__qualname__.endswith(".__new__"):
            # Special handling for __new__ methods - load via LOAD_ATTR
            if args and hasattr(args[0], "__name__"):
                self.bytecode.load_const(args[0])  # Load the class
                self.bytecode.load_attr("__new__", is_method=True)  # Load __new__ as method
                # Load all arguments (including args[0] as first argument to method)
                for arg in args:
                    self.emit_expression(arg)
                # Handle keyword arguments
                if kwargs:
                    for value in kwargs.values():
                        self.emit_expression(value)
                    self.bytecode.kw_names(tuple(kwargs))
                    self.bytecode.call_method(len(args) + len(kwargs))
                else:
                    self.bytecode.call_method(len(args))
            else:
                # Fallback to regular approach
                self.bytecode.push_null()
                self.bytecode.load_const(func)
                for arg in args:
                    self.emit_expression(arg)
                self.bytecode.call(len(args))
        elif isinstance(func, type):
            # Class constructor - use regular function call
            self.bytecode.push_null()
            self.bytecode.load_const(func)
            for arg in args:
                self.emit_expression(arg)
            # Handle keyword arguments for classes
            if kwargs:
                for value in kwargs.values():
                    self.emit_expression(value)
                self.bytecode.kw_names(tuple(kwargs.keys()))
                self.bytecode.call(len(args) + len(kwargs))
            else:
                self.bytecode.call(len(args))
        else:
            self.bytecode.push_null()
            self.bytecode.load_const(func)
            for arg in args:
                self.emit_expression(arg)
            self.bytecode.call(len(args))
        self.bytecode.store_fast(name)

        # Apply state
        if state is not None:
            if hasattr(x, "__setstate__"):
                self.emit_setstate_call(name, state)
            else:
                if isinstance(state, tuple) and len(state) == 2:
                    dict_state, slot_state = cast(
                        "tuple[dict[str, Any] | None, dict[str, Any] | None]", state
                    )
                    if slot_state is not None:
                        self.emit_slot_setattrs(name, slot_state)
                else:
                    dict_state = state

                if dict_state is not None:
                    self.emit_dict_update(name, dict_state)

        # Apply list items
        if listiter is not None:
            self.emit_list_appends(name, listiter)

        # Apply dict items
        if dictiter is not None:
            self.emit_dict_setitems(name, dictiter)

        # Load final result
        self.bytecode.load_fast(name)

    def emit_method_deep(self, x: types.MethodType) -> None:
        """Emit bytecode to reconstruct a bound method."""
        # Use getattr to create bound method from instance
        self.emit_expression(x.__self__)
        self.bytecode.load_attr(x.__func__.__name__, is_method=False)

    def emit_expression(self, x: Any) -> None:
        """Main dispatcher for object reconstruction."""
        cls = type(x)

        # Immutable types
        if cls in IMMUTABLE_NON_COLLECTIONS or issubclass(cls, type):
            self.emit_immutable(x)
            return

        # Empty object()
        if cls is object:
            self.bytecode.push_null()
            self.bytecode.load_const(object)
            self.bytecode.call(0)
            return

        # Single lookup/creation point
        obj_info = self.get_or_create_object_info(x)

        # Check if we can reference directly
        existing = self.check_object_state(obj_info)
        if existing is not None:
            return

        # Dispatch based on type - all functions now take both x and obj_info
        if cls is dict:
            self.emit_dict(x, obj_info)
        elif cls is list:
            self.emit_list(x, obj_info)
        elif cls is set:
            self.emit_set(x, obj_info)
        elif cls is tuple or cls is frozenset:
            self.emit_tuple(x, obj_info)
        elif cls is types.ModuleType:
            self.emit_immutable(x)
        elif cls is types.MethodType:
            self.emit_method_deep(x)
        elif (
            not self.ignore_deepcopy_method
            and (__deepcopy__ := getattr(x, "__deepcopy__", None)) is not None
        ):
            deepcopied = __deepcopy__(SentinelMemo(obj_info.vid, self.objects, BytecodeObjectInfo))
            self.bytecode.load_const(deepcopied)
            self.bytecode.load_attr("__deepcopy__", is_method=True)
            self.bytecode.build_map(0)  # Empty memo dict
            self.bytecode.call_method(1)
        else:
            # Standard reduce protocol
            rv = get_reduce(x, cls)
            if isinstance(rv, str):
                # Global reference
                self.emit_immutable(x)
            else:
                func, args, kwargs, state, listiter, dictiter = debunk_reduce(
                    rv, cls=cls, try_simplify_call=True
                )
                self.emit_from_reduce(x, obj_info, func, args, kwargs, state, listiter, dictiter)

        self.finalize_object(obj_info)


def is_deeply_immutable(obj: Any) -> bool:
    """Check if an object is deeply immutable (including nested tuples)."""
    if obj is None or type(obj) in IMMUTABLE_NON_COLLECTIONS:
        return True
    if isinstance(obj, tuple | frozenset):
        return all(is_deeply_immutable(item) for item in obj)
    return False


def build_reconstructor(
    x: T,
    keep_by_reference: dict[int, Any] | None = None,
    *,
    ignore_deepcopy_method: bool = False,
    runtime: Literal["cpython", "xpython"] = "cpython",
) -> Callable[[], T]:
    """
    Compiles bytecode that reconstructs `x` from atomic types.
    """
    bytecode = Bytecode(f"reconstruct_{type(x).__name__}")
    compiler = BytecodeCompiler(
        bytecode, memo=keep_by_reference, ignore_deepcopy_method=ignore_deepcopy_method
    )
    compiler.emit_expression(x)
    if runtime == "cpython":
        return bytecode.to_function()
    return partial(run_in_xpython, bytecode.to_function())
