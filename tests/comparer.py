# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium)
# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import contextlib
import datetime as dt
import decimal
import enum
import types
import uuid
from dataclasses import dataclass
from typing import Any

# =============================== Public API ==================================


def assert_copies_equivalent(original: Any, deepcopied: Any, reconstructed: Any) -> None:
    """
    Compare (original, deepcopied) with (original, reconstructed) through a stable
    metadata projection that checks:
      - structural shape and types
      - atomic equality vs the original
      - identity preservation for atomics where it matters
      - shared-reference (alias) topology with consistent left→right mapping
      - object instance state (both __dict__ and __slots__)

    On mismatch, raises AssertionError showing ALL differences with clear paths.
    """
    expected = _build_metadata(original, deepcopied, alias_map=_AliasAssigner())
    actual = _build_metadata(original, reconstructed, alias_map=_AliasAssigner())
    differences = compare_metadata(expected, actual)
    if differences:
        raise AssertionError(_format_differences(differences))


# ============================== Data Structures ==============================


class TriState(str):
    """'T' | 'F' | 'EXC:<Type>' for atomic equality vs original."""


@dataclass(frozen=True)
class AtomInfo:
    type_name: str
    same_identity_as_original: bool
    equality_vs_original: TriState  # T/F/EXC:...
    alias_group: int  # shared-reference group id (per right-hand graph)


@dataclass(frozen=True)
class Difference:
    path: str
    kind: str
    details: str


class _AliasMap:
    """
    Maintains a left→right mapping of alias group ids to ensure shared-reference
    topology is preserved across the two compared graphs.
    """

    def __init__(self) -> None:
        self._map: dict[int, int] = {}

    def unify(self, left: int, right: int) -> list[Difference]:
        diffs: list[Difference] = []
        mapped = self._map.get(left)
        if mapped is None:
            self._map[left] = right
        elif mapped != right:
            diffs.append(
                Difference(
                    path="",
                    kind="alias_inconsistent",
                    details=f"left alias {left} previously mapped to {mapped}, now {right}",
                )
            )
        return diffs


# ============================== Safe Predicates ==============================


def _is_atomic(value: Any) -> bool:
    """Values we treat as atomic (we may call == on them, but never on containers)."""
    ATOMS = (
        type(None),
        bool,
        int,
        float,
        complex,
        str,
        bytes,
        bytearray,
        range,
        types.CodeType,
        types.BuiltinFunctionType,
        types.FunctionType,
        type,
        property,
        slice,
        staticmethod,
        classmethod,
        types.ModuleType,
        decimal.Decimal,
        uuid.UUID,
        dt.datetime,
        dt.date,
        dt.time,
        dt.timedelta,
        enum.Enum,
    )
    if isinstance(value, ATOMS):
        return True
    # typing objects (including parametrized PEP 585 aliases in 3.9+)
    mod = getattr(value, "__module__", "")
    return mod in {"typing", "types"}


def _tri_state_equality(a: Any, b: Any) -> TriState:
    try:
        return TriState("T" if a == b else "F")
    except Exception as exc:
        return TriState(f"EXC:{type(exc).__name__}")


# ============================== Metadata Builder =============================


class _AliasAssigner:
    """Assigns deterministic small integers per *right-hand* object identity."""

    def __init__(self) -> None:
        self._seen: dict[int, int] = {}
        self._next = 1

    def group_id(self, obj: Any) -> int:
        oid = id(obj)
        if oid in self._seen:
            return self._seen[oid]
        gid = self._next
        self._seen[oid] = gid
        self._next += 1
        return gid


def _iter_all_slots(cls: type[Any]) -> list[str]:
    names: list[str] = []
    for base in cls.__mro__:
        slots = getattr(base, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for s in slots or ():
            if isinstance(s, str):
                names.append(s)
    return names


def _public_instance_state(obj: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (__dict__ snapshot, __slots__ snapshot) without invoking custom logic."""
    out_dict: dict[str, Any] = {}
    out_slots: dict[str, Any] = {}
    if hasattr(obj, "__dict__") and isinstance(obj.__dict__, dict):
        for k in sorted(obj.__dict__.keys(), key=str):
            out_dict[k] = obj.__dict__[k]
    for name in _iter_all_slots(type(obj)):
        if hasattr(obj, name):
            with contextlib.suppress(Exception):
                out_slots[name] = getattr(obj, name)
    return out_dict, out_slots


def _pair_dict_value(copy_dict: dict[Any, Any], original_key: Any) -> tuple[Any, Any] | None:
    """Find a key in copy_dict that equals original_key, even if hashing differs."""
    try:
        if original_key in copy_dict:
            return original_key, copy_dict[original_key]
    except Exception:
        pass
    for candidate_key in copy_dict:
        try:
            if candidate_key == original_key:
                return candidate_key, copy_dict[candidate_key]
        except Exception:
            continue
    return None


def _pair_set_element(
    copy_set: set[Any] | frozenset[Any], original_element: Any, used_right_ids: set[int]
) -> Any | None:
    """Greedy matching by equality, avoiding reusing the same right-hand element."""
    for candidate in copy_set:
        cid = id(candidate)
        if cid in used_right_ids:
            continue
        try:
            if candidate == original_element:
                used_right_ids.add(cid)
                return candidate
        except Exception:
            continue
    return None


def _build_metadata(
    original: Any,
    right: Any,
    *,
    alias_map: _AliasAssigner,
    seen_pairs: set[tuple[int, int]] | None = None,
) -> Any:
    """
    Build a pure-builtin metadata tree for (original, right) without calling __eq__
    on containers or instances. Only atomic leaves use equality.
    Shapes/types/aliasing are preserved to support robust diffs.
    """
    if seen_pairs is None:
        seen_pairs = set()

    oid, rid = id(original), id(right)
    if (oid, rid) in seen_pairs:
        return ("BACKREF", alias_map.group_id(right))
    seen_pairs.add((oid, rid))

    if _is_atomic(original):
        return (
            "ATOM",
            AtomInfo(
                type_name=type(original).__name__,
                same_identity_as_original=(right is original),
                equality_vs_original=_tri_state_equality(right, original),
                alias_group=alias_map.group_id(right),
            ),
        )

    def hdr(type_name: str) -> AtomInfo:
        return AtomInfo(
            type_name=type_name,
            same_identity_as_original=(right is original),
            equality_vs_original=TriState("-"),  # not computed for non-atomics
            alias_group=alias_map.group_id(right),
        )

    # Sequence-like
    if isinstance(original, list):
        if not isinstance(right, list):
            return ("TYPE_MISMATCH", "list", type(right).__name__)
        return (
            "LIST",
            hdr("list"),
            [
                _build_metadata(ov, right[i], alias_map=alias_map, seen_pairs=seen_pairs)
                for i, ov in enumerate(original)
            ],
        )

    if isinstance(original, tuple):
        if not isinstance(right, tuple):
            return ("TYPE_MISMATCH", "tuple", type(right).__name__)
        return (
            "TUPLE",
            hdr("tuple"),
            [
                _build_metadata(ov, right[i], alias_map=alias_map, seen_pairs=seen_pairs)
                for i, ov in enumerate(original)
            ],
        )

    # Mapping
    if isinstance(original, dict):
        if not isinstance(right, dict):
            return ("TYPE_MISMATCH", "dict", type(right).__name__)
        items = []
        for ok in original:
            match = _pair_dict_value(right, ok)
            if match is None:
                items.append(("MISSING_KEY", repr(ok)))
            else:
                rk, rv = match
                km = _build_metadata(ok, rk, alias_map=alias_map, seen_pairs=seen_pairs)
                vm = _build_metadata(original[ok], rv, alias_map=alias_map, seen_pairs=seen_pairs)
                items.append(("ITEM", km, vm))
        return ("DICT", hdr("dict"), tuple(items))

    # Set-like
    if isinstance(original, (set, frozenset)):
        if not isinstance(right, type(original)):
            return ("TYPE_MISMATCH", type(original).__name__, type(right).__name__)
        used: set[int] = set()
        elems = []
        for oe in original:
            match = _pair_set_element(right, oe, used)
            if match is None:
                elems.append(("MISSING_ELEMENT", repr(oe)))
            else:
                elems.append(_build_metadata(oe, match, alias_map=alias_map, seen_pairs=seen_pairs))
        tag = type(original).__name__.upper()  # SET or FROZENSET
        return (tag, hdr(type(original).__name__), tuple(sorted(elems, key=str)))

    # Method boundness matters only as a tag; deeper comparison is not helpful here
    if isinstance(original, types.MethodType):
        return ("METHOD", hdr("method"))

    # Fallback: treat as a plain instance by introspecting __dict__ and __slots__
    o_dict, o_slots = _public_instance_state(original)
    r_dict, r_slots = _public_instance_state(right)
    dict_items = tuple(
        (k, _build_metadata(o_dict[k], r_dict[k], alias_map=alias_map, seen_pairs=seen_pairs))
        if k in r_dict
        else (k, ("MISSING_ATTR",))
        for k in sorted(o_dict.keys(), key=str)
    )
    slot_items = tuple(
        (s, _build_metadata(o_slots[s], r_slots[s], alias_map=alias_map, seen_pairs=seen_pairs))
        if s in r_slots
        else (s, ("MISSING_SLOT",))
        for s in sorted(o_slots.keys(), key=str)
    )
    return ("INSTANCE", hdr(type(original).__name__), dict_items, slot_items)


# ============================== Metadata Compare =============================


def compare_metadata(expected: Any, actual: Any) -> list[Difference]:
    """
    Deep comparison of two metadata trees.
    Returns ALL differences as a list of Difference objects.
    """
    differences: list[Difference] = []
    _compare_impl(expected, actual, differences, alias_unifier=_AliasMap(), path=".")
    return differences


def _compare_atoms(
    left: AtomInfo, right: AtomInfo, alias_unifier: _AliasMap, path: str, out: list[Difference]
) -> None:
    if left.type_name != right.type_name:
        out.append(
            Difference(
                path, "type_mismatch", f"Expected type {left.type_name}, actual {right.type_name}"
            )
        )
    # For ints/strs identity can differ without being a bug; everything else we check
    if left.same_identity_as_original != right.same_identity_as_original and left.type_name not in {
        "int",
        "str",
    }:
        out.append(
            Difference(
                path,
                "identity_mismatch",
                f"Expected same-identity={left.same_identity_as_original}, "
                f"actual {right.same_identity_as_original}",
            )
        )
    if left.equality_vs_original != right.equality_vs_original:
        out.append(
            Difference(
                path,
                "equality_mismatch",
                f"Expected equality flag {left.equality_vs_original}, "
                f"actual {right.equality_vs_original}",
            )
        )
    out.extend(alias_unifier.unify(left.alias_group, right.alias_group))


def _compare_impl(
    left: Any, right: Any, out: list[Difference], alias_unifier: _AliasMap, path: str
) -> None:
    # BACKREF
    if isinstance(left, tuple) and left and left[0] == "BACKREF":
        if not (isinstance(right, tuple) and right and right[0] == "BACKREF"):
            out.append(Difference(path, "tag_mismatch", f"Expected BACKREF, actual {right[0]}"))
            return
        la, rb = left[1], right[1]
        out.extend(alias_unifier.unify(la, rb))
        return

    # ATOM
    if isinstance(left, tuple) and left and left[0] == "ATOM":
        if not (isinstance(right, tuple) and right and right[0] == "ATOM"):
            out.append(Difference(path, "tag_mismatch", f"Expected ATOM, actual {right[0]}"))
            return
        _compare_atoms(left[1], right[1], alias_unifier, path, out)
        return

    # TYPE_MISMATCH (leaf produced by builder)
    if isinstance(left, tuple) and left and left[0] == "TYPE_MISMATCH":
        if left != right:
            out.append(
                Difference(
                    path,
                    "type_mismatch",
                    f"Expected {left[1]}, actual {left[2]} (builder leaf differs)",
                )
            )
        return

    # Container / instance tags
    if isinstance(left, tuple) and left:
        if not (isinstance(right, tuple) and right):
            out.append(
                Difference(
                    path, "tag_mismatch", f"Expected tuple tag, actual {type(right).__name__}"
                )
            )
            return

        left_tag, right_tag = left[0], right[0]
        if left_tag != right_tag:
            out.append(
                Difference(path, "tag_mismatch", f"Expected tag {left_tag}, actual {right_tag}")
            )
            return

        # Header meta (AtomInfo) for alias/identity checks on container/instance nodes
        if left_tag in {"LIST", "TUPLE", "DICT", "SET", "FROZENSET", "METHOD", "INSTANCE"}:
            _compare_atoms(left[1], right[1], alias_unifier, path + f".{left_tag}", out)

        # Recurse into payloads
        if left_tag in {"LIST", "TUPLE"}:
            l_items, r_items = left[2], right[2]
            if len(l_items) != len(r_items):
                out.append(
                    Difference(
                        path,
                        "length_mismatch",
                        f"{left_tag} length expected {len(l_items)}, actual {len(r_items)}",
                    )
                )
            for idx in range(min(len(l_items), len(r_items))):
                _compare_impl(
                    l_items[idx], r_items[idx], out, alias_unifier, f"{path}.{left_tag}[{idx}]"
                )
            return

        if left_tag == "DICT":
            l_pairs, r_pairs = left[2], right[2]
            if len(l_pairs) != len(r_pairs):
                out.append(
                    Difference(
                        path + ".DICT",
                        "length_mismatch",
                        f"pairs expected {len(l_pairs)}, actual {len(r_pairs)}",
                    )
                )
            for i in range(min(len(l_pairs), len(r_pairs))):
                la, ra = l_pairs[i], r_pairs[i]
                if la[0] != ra[0]:
                    out.append(
                        Difference(
                            f"{path}.DICT[{i}]",
                            "entry_tag_mismatch",
                            f"expected {la[0]}, actual {ra[0]}",
                        )
                    )
                    continue
                if la[0] == "MISSING_KEY":
                    if la[1] != ra[1]:
                        out.append(
                            Difference(
                                f"{path}.DICT[{i}]",
                                "missing_key_mismatch",
                                f"expected {la[1]}, actual {ra[1]}",
                            )
                        )
                else:
                    _compare_impl(la[1], ra[1], out, alias_unifier, f"{path}.DICT[{i}].key")
                    _compare_impl(la[2], ra[2], out, alias_unifier, f"{path}.DICT[{i}].value")
            return

        if left_tag in {"SET", "FROZENSET"}:
            l_elems, r_elems = left[2], right[2]
            if len(l_elems) != len(r_elems):
                out.append(
                    Difference(
                        path + f".{left_tag}",
                        "length_mismatch",
                        f"elements expected {len(l_elems)}, actual {len(r_elems)}",
                    )
                )
            for i in range(min(len(l_elems), len(r_elems))):
                le, re = l_elems[i], r_elems[i]
                if le[0] != re[0]:
                    out.append(
                        Difference(
                            f"{path}.{left_tag}[{i}]",
                            "entry_tag_mismatch",
                            f"expected {le[0]}, actual {re[0]}",
                        )
                    )
                    continue
                if le[0] == "MISSING_ELEMENT":
                    if le[1] != re[1]:
                        out.append(
                            Difference(
                                f"{path}.{left_tag}[{i}]",
                                "missing_element_mismatch",
                                f"expected {le[1]}, actual {re[1]}",
                            )
                        )
                else:
                    _compare_impl(le, re, out, alias_unifier, f"{path}.{left_tag}[{i}]")
            return

        if left_tag == "METHOD":
            return

        if left_tag == "INSTANCE":
            l_dict, l_slots = left[2], left[3]
            r_dict, r_slots = right[2], right[3]
            if len(l_dict) != len(r_dict):
                out.append(
                    Difference(
                        path + ".INSTANCE.__dict__",
                        "length_mismatch",
                        f"items expected {len(l_dict)}, actual {len(r_dict)}",
                    )
                )
            for i in range(min(len(l_dict), len(r_dict))):
                (lk, lv), (rk, rv) = l_dict[i], r_dict[i]
                if lk != rk:
                    out.append(
                        Difference(
                            f"{path}.INSTANCE.__dict__[{i}]",
                            "key_mismatch",
                            f"expected key {lk!r}, actual {rk!r}",
                        )
                    )
                _compare_impl(lv, rv, out, alias_unifier, f"{path}.INSTANCE.__dict__[{lk}]")
            if len(l_slots) != len(r_slots):
                out.append(
                    Difference(
                        path + ".INSTANCE.__slots__",
                        "length_mismatch",
                        f"slots expected {len(l_slots)}, actual {len(r_slots)}",
                    )
                )
            for i in range(min(len(l_slots), len(r_slots))):
                (ls, lv), (rs, rv) = l_slots[i], r_slots[i]
                if ls != rs:
                    out.append(
                        Difference(
                            f"{path}.INSTANCE.__slots__[{i}]",
                            "slot_name_mismatch",
                            f"expected slot {ls!r}, actual {rs!r}",
                        )
                    )
                _compare_impl(lv, rv, out, alias_unifier, f"{path}.INSTANCE.__slots__[{ls}]")
            return

    # Fallback raw inequality if builder produced plain values (should be rare)
    if left != right:
        out.append(Difference(path, "raw_value_mismatch", f"expected {left!r}, actual {right!r}"))


# ============================== Pretty Printer ===============================


def _format_differences(differences: list[Difference]) -> str:
    # Group by path to make large outputs navigable
    by_path: dict[str, list[Difference]] = {}
    for d in differences:
        by_path.setdefault(d.path, []).append(d)

    lines = ["Metadata mismatch(s):"]
    for path in sorted(by_path.keys(), key=str):
        lines.append(f"\n• At {path}:")
        for diff in by_path[path]:
            lines.append(f"  - {diff.kind}: {diff.details}")
    return "\n".join(lines)
