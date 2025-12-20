# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""
Unified object tracking system for both AST and bytecode factories.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from duper.fastast import AST


class ObjectInfo:
    """Base class for tracking object reconstruction state.

    Contains common fields that both factories need, keyed by object ID.
    Replaces multiple vid-keyed dictionaries with a single lookup.
    """

    def __init__(
        self,
        vid: int,
        value: Any,
        cls: type[Any],
        external_value: Any = None,
        exclusive_for: int = 0,
    ) -> None:
        self.vid = vid
        self.value = value
        self.cls = cls
        self.name: str | None = None
        self.is_reconstructing = False
        self.exclusive_for = exclusive_for
        self.external_value = external_value  # from memo/keep_by_reference


class ASTObjectInfo(ObjectInfo):
    """AST factory-specific object tracking."""

    def __init__(
        self,
        vid: int,
        value: Any,
        cls: type[Any],
        external_value: Any = None,
        exclusive_for: int = 0,
    ) -> None:
        super().__init__(vid, value, cls, external_value, exclusive_for)
        self.expression: AST | None = None
        self.reflective_refs: list[AST] | None = None


class BytecodeObjectInfo(ObjectInfo):
    """Bytecode factory-specific object tracking."""

    def __init__(
        self,
        vid: int,
        value: Any,
        cls: type[Any],
        external_value: Any = None,
        exclusive_for: int = 0,
    ) -> None:
        super().__init__(vid, value, cls, external_value, exclusive_for)
        self.var_name: str | None = None  # stored_in_vars
        self.first_construction_position: int | None = None
        self.reflective_refs: list[str] | None = None
