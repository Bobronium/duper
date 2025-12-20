# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import collections
import copy
import re
import sys
import typing
from functools import partial
from typing import Any
from typing import NamedTuple

import pytest

from data import OBJECTS
from duper import deepcopy as duper_deepcopy
from duper.builders import build_reconstructor
from tests.comparer import assert_copies_equivalent

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from pytest_codspeed import BenchmarkFixture

SUPPORT_BYTECODE_FACTORY = sys.version_info[:2] == (3, 12)


# ── How to select what to run (pytest-native, no ifs) ─────────────────────────
# Examples:
#   pytest -k 'ast_factory'                   # only ast_factory params
#   pytest -k 'bytecode_factory and not reflexive'
#   pytest -k 'duper.deepcopy'
#   pytest -k 'namedtuple or stdlib'              # by case id fragments


# ── NamedTuple diff helper: show only differing fields ────────────────────────
class NTFieldDiff(NamedTuple):
    unequal: tuple[str, ...]
    left_only: tuple[str, ...]
    right_only: tuple[str, ...]


def assert_namedtuple_equal(a: Any, b: Any) -> None:
    if not (hasattr(a, "_asdict") and hasattr(b, "_asdict")):
        assert a == b
        return
    da = a._asdict()
    db = b._asdict()
    unequal = tuple(sorted([k for k in da.keys() & db.keys() if da[k] != db[k]], key=str))
    left_only = tuple(sorted(da.keys() - db.keys(), key=str))
    right_only = tuple(sorted(db.keys() - da.keys(), key=str))
    diff = NTFieldDiff(unequal=unequal, left_only=left_only, right_only=right_only)
    assert not (unequal or left_only or right_only), f"NamedTuple fields differ: {diff}"


# ── Param spaces (IDs are descriptive; use -k to select) ──────────────────────
FACTORY_PARAMS = [
    pytest.param(build_reconstructor, id="ast"),
]
if SUPPORT_BYTECODE_FACTORY:
    from duper.builders.bytecode import build_reconstructor

    FACTORY_PARAMS.append(
        pytest.param(
            partial(build_reconstructor, runtime="xpython"),
            marks=[pytest.mark.xfail(reason="bytecode_factory is not finishjed yet")],
            id="bytecode",
        ),
    )

COPIER_PARAMS = [
    pytest.param(duper_deepcopy, id="duper.deepcopy"),
]

CASES = [pytest.param(case.obj, id=case.name) for case in OBJECTS]


# ── Core equivalence tests for factories (vs copy.deepcopy baseline) ──────────
@pytest.mark.parametrize("factory", FACTORY_PARAMS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("original", CASES)
def test_factories_equivalence(
    factory: Callable[[Any], Callable[[], Any]], original: Any, benchmark: BenchmarkFixture
) -> None:
    deepcopy_failed = False
    try:
        deepcopied = copy.deepcopy(original)
    except Exception as e:
        deepcopied = e
        deepcopy_failed = True

    try:
        f = benchmark.pedantic(
            factory, (original,), {"ignore_deepcopy_method": False}, iterations=10
        )
        reconstructed = f()
    except Exception as e:
        reconstructed = e
        if not deepcopy_failed:
            raise
    assert_copies_equivalent(original, deepcopied, reconstructed)


# ── duper.deepcopy parity with copy.deepcopy across corpus ────────────────────
@pytest.mark.parametrize(
    "copier",
    COPIER_PARAMS,
    ids=lambda c: c.__name__ if hasattr(c, "__name__") else "duper.deepcopy",
)
@pytest.mark.parametrize("original", CASES)
def test_duper_deepcopy_parity(
    copier: Callable[[Any], Any], original: Any, request, benchmark
) -> None:
    deepcopy_failed = False
    try:
        baseline = copy.deepcopy(original)
    except Exception as e:
        baseline = e
        deepcopy_failed = True

    try:
        candidate = benchmark.pedantic(copier, (original,), iterations=10)
    except Exception as e:
        candidate = e
        if not deepcopy_failed:
            raise
    if (
        original is candidate
        and isinstance(original, frozenset)
        and all(o is c for o, c in zip(sorted(original), sorted(candidate), strict=False))
    ):
        request.node.add_marker(
            pytest.mark.xfail(
                reason="copy.deepcopy doesn't have special handling for frozenset", strict=True
            )
        )

    assert_copies_equivalent(original, baseline, candidate)


# ── NamedTuple equality helper sanity ─────────────────────────────────────────
def test_namedtuple_diff_helper() -> None:
    Point = collections.namedtuple("Point", ["x", "y", "meta"])
    a = Point(1, 2, {"k": [3, 4]})
    b = Point(1, 2, {"k": [3, 4]})
    assert_namedtuple_equal(a, b)
    b_bad = Point(1, 99, {"k": [3, 5]})
    with pytest.raises(AssertionError) as ei:
        assert_namedtuple_equal(a, b_bad)
    s = str(ei.value)
    assert "y" in s
    assert "meta" in s


# ── Not-supported-yet cases for factories (compile-time/construct-time error) ─
@pytest.mark.parametrize("factory", FACTORY_PARAMS, ids=lambda f: f.__name__)
def test_custom__deepcopy__referenced_after(factory) -> None:
    class C:
        def __init__(self, _mutable=None) -> None:
            self.deepcopied = False
            if _mutable is None:
                _mutable = [1, 2, 3]
            self.mutable = _mutable

        def __deepcopy__(self, memodict=None):
            c = C(self.mutable.copy())
            c.deepcopied = True
            memodict[id(self)] = c
            memodict[id(self.mutable)] = c.mutable
            memodict.setdefault(id(memodict), []).extend([c, c.mutable])
            return c

    original = C()
    a = [original, original.mutable]
    copied, mutable = copy.deepcopy(a)

    assert copied is not original
    assert original.mutable is not copied.mutable
    assert copied.mutable is mutable
    assert copied.deepcopied

    with pytest.raises(
        NotImplementedError,
        match=re.escape(
            "[1, 2, 3] was reconstructed by custom __deepcopy__"
            " and then referenced in other object. This is not supported yet.",
        ),
    ):
        factory(a)


@pytest.mark.parametrize("factory", FACTORY_PARAMS, ids=lambda f: f.__name__)
def test_custom__deepcopy__referenced_before(factory) -> None:
    class C:
        def __init__(self, _mutable=None) -> None:
            self.deepcopied = False
            if _mutable is None:
                _mutable = [1, 2, 3]
            self.mutable = _mutable

        def __deepcopy__(self, memodict=None):
            mutable = memodict.get(id(self.mutable), ["unexpected"])
            c = C(mutable)
            c.deepcopied = True
            memodict[id(self)] = c
            memodict[id(self.mutable)] = c.mutable
            memodict.setdefault(id(memodict), []).extend([c, c.mutable])
            return c

    original = C(mutable := {})
    a = [mutable, original, original.mutable]
    first_mutable, copied, mutable = copy.deepcopy(a)

    assert copied is not original
    assert first_mutable is mutable
    assert original.mutable is not copied.mutable
    assert copied.mutable is mutable
    assert copied.deepcopied

    with pytest.raises(
        NotImplementedError,
        match="Types with custom __deepcopy__ referencing previously reconstructed"
        " objects are not supported yet. See the comment above.",
    ):
        factory(a)


def test_memoryview_not_deepcopiable() -> None:
    mv = memoryview(b"abc")
    with pytest.raises(TypeError):
        copy.deepcopy(mv)
    with pytest.raises(TypeError):
        duper_deepcopy(mv)


@pytest.mark.parametrize("original", CASES)
def test_reprx_pickle_parity(original: Any, benchmark: BenchmarkFixture) -> None:
    import pickle

    import duper

    pickle_failed = False
    try:
        dumped = pickle.dumps(original)
        loaded = pickle.loads(dumped)
    except Exception as e:
        loaded = e
        pickle_failed = True

    reprx_failed = False
    try:
        source = benchmark.pedantic(duper.reprx, (original,), {"name": "get_obj"}, iterations=10)
        exec(source, globalns := {})
        reconstructed = globalns["__duper_reconstructor__"]()
    except Exception as e:
        reconstructed = e
        reprx_failed = True
        if not pickle_failed:
            raise

    if pickle_failed and not reprx_failed:
        if callable(original):
            assert original(1) == reconstructed(1)
        else:
            assert original == reconstructed
    else:
        assert_copies_equivalent(original, loaded, reconstructed)
