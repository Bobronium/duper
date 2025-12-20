# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""
Slightly modified builtin test.test_copy module
"""

import abc
import copy as original_copy
import copyreg
import unittest
import weakref
from operator import eq
from operator import ge
from operator import gt
from operator import le
from operator import lt
from operator import ne
from typing import NoReturn

import pytest

import duper


def panic(*_, **__) -> NoReturn:
    raise


def _deepcopy(obj, memo=None):
    factory = duper.reconstructs(obj, check=False, fallback=panic, _keep_by_reference=memo)
    return factory()


def _copy(obj):
    factory = duper.copies(obj)
    return factory()


order_comparisons = le, lt, ge, gt
equality_comparisons = eq, ne
comparisons = order_comparisons + equality_comparisons


class CopyModule:
    error = Error = original_copy.Error
    copy = staticmethod(duper.copy)
    deepcopy = staticmethod(duper.deepcopy)


@pytest.fixture(
    params=[
        pytest.param((duper.copy, duper.deepcopy), id="runtime"),
        pytest.param((_copy, _deepcopy), id="factory"),
        # pytest.param((_copy, orcopy.deepcopy), id="orcopy"),
    ]
)
def copy(request) -> CopyModule:
    copy_substitute, deepcopy_substitute = request.param

    class CopyModule:
        error = Error = original_copy.Error
        copy = staticmethod(copy_substitute)
        deepcopy = staticmethod(deepcopy_substitute)

    copy_module = CopyModule()
    # keeps copy module intact, but allows to keep test cases relatively unchanged
    copy_module.__dict__.update(original_copy.__dict__)
    del copy_module.__dict__["copy"], copy_module.__dict__["deepcopy"]
    return copy_module


# Attempt full line coverage of copy.py from top to bottom


def test_exceptions(copy) -> None:
    assert copy.Error is copy.error
    assert issubclass(copy.Error, Exception)

    assert issubclass(duper.Error, copy.Error)


# The copy() method


def test_copy_basic(copy) -> None:
    x = 42
    y = copy.copy(x)
    assert x == y


def test_copy_copy(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __copy__(self):
            return C(self.foo)

    x = C(42)
    y = copy.copy(x)
    assert y.__class__ == x.__class__
    assert y.foo == x.foo


def test_copy_registry(copy) -> None:
    class C:
        def __new__(cls, foo):
            obj = object.__new__(cls)
            obj.foo = foo
            return obj

    def pickle_C(obj):
        return (C, (obj.foo,))

    x = C(42)
    with pytest.raises(TypeError):
        copy.copy(x)
    copyreg.pickle(C, pickle_C, C)
    copy.copy(x)


def test_copy_reduce_ex(copy) -> None:
    class C:
        def __reduce_ex__(self, proto):
            c.append(1)
            return ""

        def __reduce__(self):
            self.fail("shouldn't call this")

    c = []
    x = C()
    y = copy.copy(x)
    assert y is x
    assert c == [1]


def test_copy_reduce(copy) -> None:
    class C:
        def __reduce__(self):
            c.append(1)
            return ""

    c = []
    x = C()
    y = copy.copy(x)
    assert y is x
    assert c == [1]


def test_copy_cant(copy) -> None:
    class C:
        def __getattribute__(self, name):
            if name.startswith("__reduce"):
                raise AttributeError(name)
            return object.__getattribute__(self, name)

    x = C()
    with pytest.raises(copy.Error):
        copy.copy(x)


def get_copy_atomic():
    class Classic:
        pass

    class NewStyle:
        pass

    def f() -> None:
        pass

    class WithMetaclass(metaclass=abc.ABCMeta):
        pass

    return [
        None,
        ...,
        NotImplemented,
        42,
        2**100,
        3.14,
        True,
        False,
        1j,
        "hello",
        "hello\u1234",
        f.__code__,
        b"world",
        bytes(range(256)),
        range(10),
        slice(1, 10, 2),
        NewStyle,
        Classic,
        max,
        WithMetaclass,
        property(),
    ]


@pytest.mark.parametrize("x", get_copy_atomic())
def test_copy_atomic(copy, x) -> None:
    assert copy.copy(x) is x


def test_copy_list(copy) -> None:
    x = [1, 2, 3]
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = []
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_tuple(copy) -> None:
    x = (1, 2, 3)
    assert copy.copy(x) is x
    x = ()
    assert copy.copy(x) is x
    x = (1, 2, 3, [])
    assert copy.copy(x) is x


def test_copy_dict(copy) -> None:
    x = {"foo": 1, "bar": 2}
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = {}
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_set(copy) -> None:
    x = {1, 2, 3}
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = set()
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_frozenset(copy) -> None:
    x = frozenset({1, 2, 3})
    assert copy.copy(x) is x
    x = frozenset()
    assert copy.copy(x) is x


def test_copy_bytearray(copy) -> None:
    x = bytearray(b"abc")
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = bytearray()
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_inst_vanilla(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_copy(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __copy__(self):
            return C(self.foo)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getinitargs(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getinitargs__(self):
            return (self.foo,)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getnewargs(copy) -> None:
    class C(int):
        def __new__(cls, foo):
            self = int.__new__(cls)
            self.foo = foo
            return self

        def __getnewargs__(self):
            return (self.foo,)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    y = copy.copy(x)
    assert isinstance(y, C)
    assert y == x
    assert y is not x
    assert y.foo == x.foo


def test_copy_inst_getnewargs_ex(copy) -> None:
    class C(int):
        def __new__(cls, *, foo):
            self = int.__new__(cls)
            self.foo = foo
            return self

        def __getnewargs_ex__(self):
            return (), {"foo": self.foo}

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(foo=42)
    y = copy.copy(x)
    assert isinstance(y, C)
    assert y == x
    assert y is not x
    assert y.foo == x.foo


def test_copy_inst_getstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getstate__(self):
            return {"foo": self.foo}

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_setstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __setstate__(self, state):
            self.foo = state["foo"]

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getstate_setstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getstate__(self):
            return self.foo

        def __setstate__(self, state):
            self.foo = state

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x
    # State with boolean value is false (issue #25718)
    x = C(0.0)

    assert copy.copy(x) == x


# The deepcopy() method


def test_deepcopy_basic(copy) -> None:
    x = 42
    y = copy.deepcopy(x)
    assert y == x


def test_deepcopy_same_object(copy) -> None:
    # previously was called test_deepcopy_memo, but I find new name to be clearer
    # Tests of reflexive objects are under type-specific sections below.
    # This tests only repetitions of objects.
    x = []
    x = [x, x]
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y[0] is not x[0]
    assert y[0] is y[1]


def test_deepcopy_same_object_different_parents(copy) -> None:
    # previously was called test_deepcopy_memo, but I find new name to be clearer
    # Tests of reflexive objects are under type-specific sections below.
    # This tests only repetitions of objects.
    x = []
    x = [[x], x]
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y[0] is not x[0]
    assert y[0][0] is y[1]


def test_deepcopy_issubclass(copy) -> None:
    # XXX Note: there's no way to test the TypeError coming out of
    # issubclass() -- this can only happen when an extension
    # module defines a "type" that doesn't formally inherit from
    # type.
    class Meta(type):
        pass

    class C(metaclass=Meta):
        pass

    assert copy.deepcopy(C) == C


def test_deepcopy_deepcopy(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __deepcopy__(self, memo=None):
            return C(self.foo)

    x = C(42)
    y = copy.deepcopy(x)
    assert y.__class__ == x.__class__
    assert y.foo == x.foo


def test_deepcopy_registry(copy) -> None:
    class C:
        def __new__(cls, foo):
            obj = object.__new__(cls)
            obj.foo = foo
            return obj

    def pickle_C(obj):
        return (C, (obj.foo,))

    x = C(42)
    with pytest.raises(TypeError):
        copy.deepcopy(x)
    copyreg.pickle(C, pickle_C, C)
    copy.deepcopy(x)


def test_deepcopy_reduce_ex(copy) -> None:
    class C:
        def __reduce_ex__(self, proto):
            c.append(1)
            return ""

        def __reduce__(self):
            self.fail("shouldn't call this")

    c = []
    x = C()
    y = copy.deepcopy(x)
    assert y is x
    assert c == [1]


def test_deepcopy_reduce(copy) -> None:
    class C:
        def __reduce__(self):
            c.append(1)
            return ""

    c = []
    x = C()
    y = copy.deepcopy(x)
    assert y is x
    assert c == [1]


def test_deepcopy_cant(copy) -> None:
    class C:
        def __getattribute__(self, name):
            if name.startswith("__reduce"):
                raise AttributeError(name)
            return object.__getattribute__(self, name)

    x = C()
    with pytest.raises(copy.Error):
        copy.deepcopy(x)


# Type-specific _deepcopy_xxx() methods


def get_deepcopy_atomic():
    class Classic:
        pass

    class NewStyle:
        pass

    def f() -> None:
        pass

    return [
        None,
        42,
        2**100,
        3.14,
        True,
        False,
        1j,
        "hello",
        "hello\u1234",
        f.__code__,
        NewStyle,
        range(10),
        Classic,
        max,
        property(),
    ]


@pytest.mark.parametrize("x", get_deepcopy_atomic())
def test_deepcopy_atomic(copy, x) -> None:
    assert copy.deepcopy(x) is x


def test_deepcopy_list(copy) -> None:
    x = [[1, 2], 3]
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x[0] is not y[0]


@pytest.mark.parametrize("op", comparisons)
def test_deepcopy_reflexive_list(copy, op) -> None:
    x = []
    x.append(x)
    y = copy.deepcopy(x)
    with pytest.raises(RecursionError):
        op(y, x)
    assert y is not x
    assert y[0] is y
    assert len(y) == 1


def test_deepcopy_empty_tuple(copy) -> None:
    x = ()
    y = copy.deepcopy(x)
    assert x is y


def test_deepcopy_tuple(copy) -> None:
    x = ([1, 2], 3)
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x[0] is not y[0]


def test_deepcopy_tuple_of_immutables(copy) -> None:
    x = ((1, 2), 3)
    y = copy.deepcopy(x)
    assert x is y


@pytest.mark.parametrize("op", comparisons)
def test_deepcopy_reflexive_tuple(copy, op) -> None:
    x = ([], 4, 3)
    x[0].append(x)
    y = copy.deepcopy(x)
    assert y is not x
    assert y[0] is not x[0]
    assert y[0][0] is y

    with pytest.raises(RecursionError):
        op(y, x)


def test_deepcopy_dict(copy) -> None:
    x = {"foo": [1, 2], "bar": 3}
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x["foo"] is not y["foo"]


@pytest.mark.parametrize(
    ("order_op", "eq_op"), zip(order_comparisons, equality_comparisons, strict=False)
)
def test_deepcopy_reflexive_dict_order(copy, order_op, eq_op) -> None:
    x = {}
    x["foo"] = x
    y = copy.deepcopy(x)
    with pytest.raises(TypeError):
        order_op(y, x)
    with pytest.raises(RecursionError):
        eq_op(y, x)
    assert y is not x
    assert y["foo"] is y
    assert len(y) == 1


def test_deepcopy_keepalive(copy) -> None:
    if copy.deepcopy is _deepcopy:
        pytest.xfail("Factories don't respect memo")
    memo = {}
    x = []
    # original_copy.deepcopy(x, memo)
    copy.deepcopy(x, memo)
    assert memo[id(memo)][0] is x


def test_deepcopy_by_reference(copy) -> None:
    x = []
    memo = {id(x): 123}
    assert copy.deepcopy(x, memo) == 123


def test_deepcopy_dont_memo_immutable(copy) -> None:
    if copy.deepcopy is _deepcopy:
        pytest.xfail("Factories don't respect memo")
    memo = {}
    x = [1, 2, 3, 4]
    y = copy.deepcopy(x, memo)
    assert y == x
    # There's the entry for the new list, and the keep alive.
    assert len(memo) == 2

    memo = {}
    x = [(1, 2)]
    y = copy.deepcopy(x, memo)
    assert y == x
    # Tuples with immutable contents are immutable for deepcopy.
    assert len(memo) == 2


def test_deepcopy_inst_vanilla(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y.foo is not x.foo


def test_deepcopy_inst_deepcopy(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __deepcopy__(self, memo):
            return C(original_copy.deepcopy(self.foo, memo))

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo


def test_deepcopy_inst_getinitargs(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getinitargs__(self):
            return (self.foo,)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo


def test_deepcopy_inst_getnewargs(copy) -> None:
    class C(int):
        def __new__(cls, foo):
            self = int.__new__(cls)
            self.foo = foo
            return self

        def __getnewargs__(self):
            return (self.foo,)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert isinstance(y, C)
    assert y == x
    assert y is not x
    assert y.foo == x.foo
    assert y.foo is not x.foo


def test_deepcopy_inst_getnewargs_ex(copy) -> None:
    class C(int):
        def __new__(cls, *, foo):
            self = int.__new__(cls)
            self.foo = foo
            return self

        def __getnewargs_ex__(self):
            return (), {"foo": self.foo}

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(foo=[42])
    y = copy.deepcopy(x)
    assert isinstance(y, C)
    assert y == x
    assert y is not x
    assert y.foo == x.foo
    assert y.foo is not x.foo


def test_deepcopy_inst_getstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getstate__(self):
            return {"foo": self.foo}

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo


def test_deepcopy_inst_setstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __setstate__(self, state):
            self.foo = state["foo"]

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo


def test_deepcopy_inst_getstate_setstate(copy) -> None:
    class C:
        def __init__(self, foo) -> None:
            self.foo = foo

        def __getstate__(self):
            return self.foo

        def __setstate__(self, state):
            self.foo = state

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo
    # State with boolean value is false (issue #25718)
    x = C([])
    y = copy.deepcopy(x)
    assert y == x
    assert y is not x
    assert y.foo is not x.foo


def test_deepcopy_reflexive_inst(copy) -> None:
    class C:
        pass

    x = C()
    x.foo = x
    y = copy.deepcopy(x)
    assert y is not x
    assert y.foo is y


# _reconstruct()


def test_reconstruct_string(copy) -> None:
    class C:
        def __reduce__(self):
            return ""

    x = C()
    y = copy.copy(x)
    assert y is x
    y = copy.deepcopy(x)
    assert y is x


def test_reconstruct_nostate(copy) -> None:
    class C:
        def __reduce__(self):
            return (C, ())

    x = C()
    x.foo = 42
    y = copy.copy(x)
    assert y.__class__ is x.__class__
    y = copy.deepcopy(x)
    assert y.__class__ is x.__class__


def test_reconstruct_state(copy) -> None:
    class C:
        def __reduce__(self):
            return (C, (), self.__dict__)

        def __eq__(self, other):
            return self.__dict__ == other.__dict__

    x = C()
    x.foo = [42]
    y = copy.copy(x)
    assert y == x
    y = copy.deepcopy(x)
    assert y == x
    assert y.foo is not x.foo


def test_reconstruct_state_setstate(copy) -> None:
    class C:
        def __reduce__(self):
            return (C, (), self.__dict__)

        def __setstate__(self, state):
            self.__dict__.update(state)

        def __eq__(self, other):
            return self.__dict__ == other.__dict__

    x = C()
    x.foo = [42]
    y = copy.copy(x)
    assert y == x
    y = copy.deepcopy(x)
    assert y == x
    assert y.foo is not x.foo


def test_reconstruct_reflexive(copy) -> None:
    class C:
        pass

    x = C()
    x.foo = x
    y = copy.deepcopy(x)
    assert y is not x
    assert y.foo is y


# Additions for Python 2.3 and pickle protocol 2


def test_reduce_4tuple(copy) -> None:
    class C(list):
        def __reduce__(self):
            return (C, (), self.__dict__, iter(self))

        def __eq__(self, other):
            return list(self) == list(other) and self.__dict__ == other.__dict__

    x = C([[1, 2], 3])
    y = copy.copy(x)
    assert x == y
    assert x is not y
    assert x[0] is y[0]
    y = copy.deepcopy(x)
    assert x == y
    assert x is not y
    assert x[0] is not y[0]


def test_reduce_5tuple(copy) -> None:
    class C(dict):
        def __reduce__(self):
            return (C, (), self.__dict__, None, self.items())

        def __eq__(self, other):
            return dict(self) == dict(other) and self.__dict__ == other.__dict__

    x = C([("foo", [1, 2]), ("bar", 3)])
    y = copy.copy(x)
    assert x == y
    assert x is not y
    assert x["foo"] is y["foo"]
    y = copy.deepcopy(x)
    assert x == y
    assert x is not y
    assert x["foo"] is not y["foo"]


def test_copy_slots(copy) -> None:
    class C:
        __slots__ = ["foo"]

    x = C()
    x.foo = [42]
    y = copy.copy(x)
    assert x.foo is y.foo


def test_deepcopy_slots(copy) -> None:
    class C:
        __slots__ = ["foo"]

    x = C()
    x.foo = [42]
    y = copy.deepcopy(x)
    assert x.foo == y.foo
    assert x.foo is not y.foo


def test_deepcopy_dict_subclass(copy) -> None:
    class C(dict):
        def __init__(self, d=None) -> None:
            if not d:
                d = {}
            self._keys = list(d.keys())
            super().__init__(d)

        def __setitem__(self, key, item) -> None:
            super().__setitem__(key, item)
            if key not in self._keys:
                self._keys.append(key)

    x = C(d={"foo": 0})
    y = copy.deepcopy(x)
    assert x == y
    assert x._keys == y._keys
    assert x is not y
    x["bar"] = 1
    assert x != y
    assert x._keys != y._keys


def test_copy_list_subclass(copy) -> None:
    class C(list):
        pass

    x = C([[1, 2], 3])
    x.foo = [4, 5]
    y = copy.copy(x)
    assert list(x) == list(y)
    assert x.foo == y.foo
    assert x[0] is y[0]
    assert x.foo is y.foo


def test_deepcopy_list_subclass(copy) -> None:
    class C(list):
        pass

    x = C([[1, 2], 3])
    x.foo = [4, 5]
    y = copy.deepcopy(x)
    assert list(x) == list(y)
    assert x.foo == y.foo
    assert x[0] is not y[0]
    assert x.foo is not y.foo


def test_copy_tuple_subclass(copy) -> None:
    class C(tuple):
        pass

    x = C([1, 2, 3])
    assert tuple(x) == (1, 2, 3)
    y = copy.copy(x)
    assert tuple(y) == (1, 2, 3)


def test_deepcopy_tuple_subclass(copy) -> None:
    class C(tuple):
        pass

    x = C([[1, 2], 3])
    assert tuple(x) == ([1, 2], 3)
    y = copy.deepcopy(x)
    assert tuple(y) == ([1, 2], 3)
    assert x is not y
    assert x[0] is not y[0]


def test_getstate_exc(copy) -> None:
    class EvilState:
        def __getstate__(self):
            raise ValueError("ain't got no stickin' state")

    with pytest.raises(ValueError):
        copy.copy(EvilState())


def test_copy_function(copy) -> None:
    assert copy.copy(global_foo) == global_foo

    def foo(x, y):
        return x + y

    assert copy.copy(foo) == foo

    def bar() -> None:
        return None

    assert copy.copy(bar) == bar


def test_deepcopy_function(copy) -> None:
    assert copy.deepcopy(global_foo) == global_foo

    def foo(x, y):
        return x + y

    assert copy.deepcopy(foo) == foo

    def bar() -> None:
        return None

    assert copy.deepcopy(bar) == bar


def check_weakref(_copy) -> None:
    class C:
        pass

    obj = C()
    x = weakref.ref(obj)
    y = _copy(x)
    assert y is x
    del obj
    y = _copy(x)
    assert y is x


def test_copy_weakref(copy) -> None:
    check_weakref(copy.copy)


def test_deepcopy_weakref(copy) -> None:
    check_weakref(copy.deepcopy)


def check_copy_weakdict(copy, _dicttype) -> None:
    class C:
        pass

    a, b, c, d = [C() for i in range(4)]
    u = _dicttype()
    u[a] = b
    u[c] = d
    v = copy.copy(u)
    assert v is not u
    assert v == u
    assert v[a] == b
    assert v[c] == d
    assert len(v) == 2
    del c, d
    # #  support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1
    x, y = C(), C()
    # The underlying containers are decoupled
    v[x] = y
    assert x not in u


def test_copy_weakkeydict(copy) -> None:
    check_copy_weakdict(copy, weakref.WeakKeyDictionary)


def test_copy_weakvaluedict(copy) -> None:
    check_copy_weakdict(copy, weakref.WeakValueDictionary)


def test_deepcopy_weakkeydict(copy) -> None:
    class C:
        def __init__(self, i) -> None:
            self.i = i

    a, b, c, d = [C(i) for i in range(4)]
    u = weakref.WeakKeyDictionary()
    u[a] = b
    u[c] = d
    # Keys aren't copied, values are
    v = copy.deepcopy(u)
    assert v != u
    assert len(v) == 2
    assert v[a] is not b
    assert v[c] is not d
    assert v[a].i == b.i
    assert v[c].i == d.i
    del c
    #  support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1


def test_deepcopy_weakvaluedict(copy) -> None:
    class C:
        def __init__(self, i) -> None:
            self.i = i

    a, b, c, d = [C(i) for i in range(4)]
    u = weakref.WeakValueDictionary()
    u[a] = b
    u[c] = d
    # Keys are copied, values aren't
    v = copy.deepcopy(u)
    assert v != u
    assert len(v) == 2
    (x, y), (z, t) = sorted(v.items(), key=lambda pair: pair[0].i)
    assert x is not a
    assert x.i == a.i
    assert y is b
    assert z is not c
    assert z.i == c.i
    assert t is d
    del x, y, z, t
    del d
    #  support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1


def test_deepcopy_bound_method(copy) -> None:
    class Foo:
        def m(self) -> None:
            pass

    f = Foo()
    f.b = f.m
    g = copy.deepcopy(f)
    assert g.m == g.b
    assert g.b.__self__ is g
    g.b()


def global_foo(x, y):
    return x + y


if __name__ == "__main__":
    unittest.main()
