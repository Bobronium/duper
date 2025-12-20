# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

import ast
import fractions
import numbers
import re
import types
import weakref
from decimal import Decimal
from typing import TYPE_CHECKING
from typing import Any
from typing import Final
from typing import cast

if TYPE_CHECKING:
    from _ast import FunctionDef

# NON_COLLECTIONS should really be called "atomic"
IMMUTABLE_NON_COLLECTIONS_CONST_TYPES: Final = frozenset(
    {
        type(None),
        type(Ellipsis),
        type(NotImplemented),
        int,
        float,
        bool,
        complex,
        bytes,
        str,
    }
)
IMMUTABLE_NON_COLLECTIONS: Final = frozenset(
    {
        *IMMUTABLE_NON_COLLECTIONS_CONST_TYPES,
        types.BuiltinFunctionType,
        types.FunctionType,
        type,
        range,
        property,
        weakref.ref,
        types.CodeType,
        re.Pattern,
        Decimal,
        fractions.Fraction,
        numbers.Complex,
        numbers.Number,
        numbers.Rational,
        numbers.Real,
        numbers.Integral,
    }
)
IMMUTABLE_CONSTANTS_OR_IMPORTABLE: Final = frozenset(
    {
        *IMMUTABLE_NON_COLLECTIONS_CONST_TYPES,
        types.BuiltinFunctionType,
        types.FunctionType,
        type,
    }
)
CONST_COLLECTIONS: Final = frozenset({tuple, frozenset, slice})
IMMUTABLE_TYPES: Final = frozenset({*IMMUTABLE_NON_COLLECTIONS, *CONST_COLLECTIONS})
CONST_TYPES = frozenset({*IMMUTABLE_NON_COLLECTIONS_CONST_TYPES, *CONST_COLLECTIONS})
BUILTIN_COLLECTIONS: Final = frozenset({dict, list, set, tuple, frozenset, bytearray})
BUILTIN_MUTABLE: Final = frozenset({bytearray, dict, list, set})

BuiltinMutableType = bytearray | dict[Any, Any] | list[Any] | set[Any]
BuiltinCollectionType = (
    dict[Any, Any] | list[Any] | set[Any] | tuple[Any, ...] | frozenset[Any] | bytearray
)
ImmutableCollectionType = tuple[Any, ...] | frozenset[Any] | slice
ImmutableType = (
    type[None]
    | type[Any]
    | int
    | float
    | bool
    | complex
    | bytes
    | str
    | types.CodeType
    | type
    | range
    | types.BuiltinFunctionType
    | types.FunctionType
    | weakref.ref[Any]
    | property
)
IMMORTAL_OBJECTS = {
    None,
    True,
    False,
    (),
    frozenset(),
    *range(-5, 257),  # Small integers that CPython interns
    *[chr(i) for i in range(256)],  # ASCII characters
    "",
    " ",
    "\n",
    "\t",
    "\r",  # Common strings
}
_code_definition: Final = cast(
    "FunctionDef",
    ast.parse(f"def code{types.CodeType.__text_signature__}: pass").body[0],
)
CODE_ATTRIBUTES: Final = tuple(
    {"codestring": "co_code", "constants": "co_consts"}.get(arg.arg, f"co_{arg.arg}")
    for arg in _code_definition.args.posonlyargs
)
