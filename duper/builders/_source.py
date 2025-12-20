# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import ast
import linecache
import threading
import weakref
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import FunctionType


class LazySourceLines:
    """
    A list-like, lazily materialized sequence of newline-terminated source lines.
    Implements enough of the sequence protocol to satisfy inspect/linecache callers.
    """

    __slots__ = ("_filename", "_fn_ref", "_lines", "_lock")

    def __init__(self, fn: FunctionType, filename: str) -> None:
        self._fn_ref = weakref.ref(fn)
        self._filename = filename
        self._lock = threading.Lock()
        self._lines: list[str] | None = None

    def _materialize(self) -> list[str]:
        if self._lines is not None:
            return self._lines
        with self._lock:
            if self._lines is None:
                fn = self._fn_ref()
                if fn is None:
                    self._lines = []
                    linecache.cache.pop(self._filename)
                else:
                    text = ast.unparse(fn.__ast__)  # type: ignore[attr-defined]
                    self._lines = text.splitlines(keepends=True)
                    linecache.cache[self._filename] = (0, None, self._lines, self._filename)
        return self._lines

    # -- list-like API --
    def __len__(self) -> int:
        return len(self._materialize())

    def __getitem__(self, i: int | slice) -> str | list[str]:
        data = self._materialize()
        return data[i]  # slice returns list[str], int returns str

    def __iter__(self) -> Iterator[str]:
        return iter(self._materialize())

    def __repr__(self) -> str:
        state = "materialized" if self._lines is not None else "lazy"
        return (
            f"<LazySourceLines {state} {self._filename!r} len={len(self) if self._lines else '?'}>"
        )
