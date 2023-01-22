# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

import types
import weakref
from typing import Any
from typing import Final
from typing import Union


IMMUTABLE_NON_COLLECTIONS: Final = frozenset(
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
        types.CodeType,
        type,
        range,
        types.BuiltinFunctionType,
        types.FunctionType,
        weakref.ref,
        property,
    }
)
IMMUTABLE_TYPES: Final = frozenset({*IMMUTABLE_NON_COLLECTIONS, tuple, frozenset, slice})
BUILTIN_COLLECTIONS: Final = frozenset({dict, list, set, tuple, frozenset})
BUILTIN_MUTABLE: Final = frozenset({bytearray, dict, list, set})

BuiltinMutableType = Union[bytearray, dict[Any, Any], list[Any], set[Any]]
BuiltinCollectionType = Union[dict[Any, Any], list[Any], set[Any], tuple[Any, ...], frozenset[Any]]
ImmutableCollectionType = Union[tuple[Any, ...], frozenset, slice]
ImmutableType = Union[
    type[None],
    type[Any],
    int,
    float,
    bool,
    complex,
    bytes,
    str,
    types.CodeType,
    type,
    range,
    types.BuiltinFunctionType,
    types.FunctionType,
    weakref.ref,
    property,
]
