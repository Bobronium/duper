# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import warnings
from typing import Any, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import FunctionType, ModuleType

from duper._compile_support import COMPILED  # this import must stay above any other duper imports


def _replicate(factory: Callable[[], _T], n: int) -> list[_T]:
    return [factory() for _ in range(n)]


from duper.copy import copy, copies, deepcopy, reconstructs, Error, warn, fail, replicate  # noqa: E402
from duper.builders.runtime import returns  # noqa: E402
from duper.builders.ast import reprx  # noqa: E402
from duper import builders  # noqa: E402

_T = TypeVar("_T")
__all__ = [
    "COMPILED",
    "Error",
    "builders",
    "copies",
    "copy",
    "deepcopy",
    "fail",
    "reconstructs",
    "replicate",
    "reprx",
    "returns",
    "warn",
]

for _attr in __all__:
    if hasattr(public_object := globals()[_attr], "__module__"):
        public_object.__module__ = __name__


_DEPRECATED_NAMES = {
    "dups": copies,
    "dupe": copy,
    "deepdups": reconstructs,
    "deepdupe": deepcopy,
    "factories": builders,
}


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED_NAMES:
        new_obj = _DEPRECATED_NAMES[name]
        warnings.warn(
            f"{__name__}.{name} is deprecated, use {__name__}.{new_obj.__name__} instead.",  # type: ignore[attr-defined]
            stacklevel=1,
        )
        return new_obj
    raise AttributeError(f"Module {__name__!r} doesn't have attributee {name}.")
