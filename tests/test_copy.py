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
from test import support

import pytest

import duper
from duper.factories import ast


ast.with_source = True


class Copy:
    error = Error = original_copy.Error
    copy = staticmethod(duper.dupe)
    deepcopy = staticmethod(duper.deepdupe)


copy = Copy()
# keeps copy module intact, but allows to keep test cases relatively unchanged
copy.__dict__.update(original_copy.__dict__)

del copy.__dict__["copy"], copy.__dict__["deepcopy"]


order_comparisons = le, lt, ge, gt
equality_comparisons = eq, ne
comparisons = order_comparisons + equality_comparisons


@pytest.fixture()
def self():
    return unittest.TestCase()


# Attempt full line coverage of copy.py from top to bottom


def test_exceptions(self):
    assert copy.Error is copy.error
    assert issubclass(copy.Error, Exception)

    assert issubclass(duper.Error, copy.Error)


# The copy() method


def test_copy_basic(self):
    x = 42
    y = copy.copy(x)
    assert x == y


def test_copy_copy(self):
    class C(object):
        def __init__(self, foo):
            self.foo = foo

        def __copy__(self):
            return C(self.foo)

    x = C(42)
    y = copy.copy(x)
    assert y.__class__ == x.__class__
    assert y.foo == x.foo


def test_copy_registry(self):
    class C(object):
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


def test_copy_reduce_ex(self):
    class C(object):
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


def test_copy_reduce(self):
    class C(object):
        def __reduce__(self):
            c.append(1)
            return ""

    c = []
    x = C()
    y = copy.copy(x)
    assert y is x
    assert c == [1]


def test_copy_cant(self):
    class C(object):
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

    class NewStyle(object):
        pass

    def f():
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
def test_copy_atomic(x):
    assert copy.copy(x) is x


def test_copy_list(self):
    x = [1, 2, 3]
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = []
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_tuple(self):
    x = (1, 2, 3)
    assert copy.copy(x) is x
    x = ()
    assert copy.copy(x) is x
    x = (1, 2, 3, [])
    assert copy.copy(x) is x


def test_copy_dict(self):
    x = {"foo": 1, "bar": 2}
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = {}
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_set(self):
    x = {1, 2, 3}
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = set()
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_frozenset(self):
    x = frozenset({1, 2, 3})
    assert copy.copy(x) is x
    x = frozenset()
    assert copy.copy(x) is x


def test_copy_bytearray(self):
    x = bytearray(b"abc")
    y = copy.copy(x)
    assert y == x
    assert y is not x
    x = bytearray()
    y = copy.copy(x)
    assert y == x
    assert y is not x


def test_copy_inst_vanilla(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_copy(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __copy__(self):
            return C(self.foo)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getinitargs(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __getinitargs__(self):
            return (self.foo,)

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getnewargs(self):
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


def test_copy_inst_getnewargs_ex(self):
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


def test_copy_inst_getstate(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __getstate__(self):
            return {"foo": self.foo}

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_setstate(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __setstate__(self, state):
            self.foo = state["foo"]

        def __eq__(self, other):
            return self.foo == other.foo

    x = C(42)
    assert copy.copy(x) == x


def test_copy_inst_getstate_setstate(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_basic(self):
    x = 42
    y = copy.deepcopy(x)
    assert y == x


def test_deepcopy_same_object(self):
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


def test_deepcopy_issubclass(self):
    # XXX Note: there's no way to test the TypeError coming out of
    # issubclass() -- this can only happen when an extension
    # module defines a "type" that doesn't formally inherit from
    # type.
    class Meta(type):
        pass

    class C(metaclass=Meta):
        pass

    assert copy.deepcopy(C) == C


def test_deepcopy_deepcopy(self):
    class C(object):
        def __init__(self, foo):
            self.foo = foo

        def __deepcopy__(self, memo=None):
            return C(self.foo)

    x = C(42)
    y = copy.deepcopy(x)
    assert y.__class__ == x.__class__
    assert y.foo == x.foo


def test_deepcopy_registry(self):
    class C(object):
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


def test_deepcopy_reduce_ex(self):
    class C(object):
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


def test_deepcopy_reduce(self):
    class C(object):
        def __reduce__(self):
            c.append(1)
            return ""

    c = []
    x = C()
    y = copy.deepcopy(x)
    assert y is x
    assert c == [1]


def test_deepcopy_cant(self):
    class C(object):
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

    class NewStyle(object):
        pass

    def f():
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
def test_deepcopy_atomic(x):
    assert copy.deepcopy(x) is x


def test_deepcopy_list(self):
    x = [[1, 2], 3]
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x[0] is not y[0]


@pytest.mark.xfail(strict=True, raises=duper.Error)
@pytest.mark.parametrize("op", comparisons)
def test_deepcopy_reflexive_list(op):
    x = []
    x.append(x)
    y = copy.deepcopy(x)
    with pytest.raises(RecursionError):
        op(y, x)
    assert y is not x
    assert y[0] is y
    assert len(y) == 1


def test_deepcopy_empty_tuple(self):
    x = ()
    y = copy.deepcopy(x)
    assert x is y


def test_deepcopy_tuple(self):
    x = ([1, 2], 3)
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x[0] is not y[0]


def test_deepcopy_tuple_of_immutables(self):
    x = ((1, 2), 3)
    y = copy.deepcopy(x)
    assert x is y


@pytest.mark.xfail(strict=True, raises=duper.Error)
@pytest.mark.parametrize("op", comparisons)
def test_deepcopy_reflexive_tuple(op):
    x = ([], 4, 3)
    x[0].append(x)
    y = copy.deepcopy(x)
    assert y is not x
    assert y[0] is not x[0]
    assert y[0][0] is y

    with pytest.raises(RecursionError):
        op(y, x)


def test_deepcopy_dict(self):
    x = {"foo": [1, 2], "bar": 3}
    y = copy.deepcopy(x)
    assert y == x
    assert x is not y
    assert x["foo"] is not y["foo"]


@pytest.mark.xfail(strict=True, raises=duper.Error)
@pytest.mark.parametrize("order_op,eq_op", zip(order_comparisons, equality_comparisons))
def test_deepcopy_reflexive_dict_order(order_op, eq_op):
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


@pytest.mark.xfail(strict=True, raises=duper.Error)
def test_deepcopy_keepalive(self):
    memo = {}
    x = []
    copy.deepcopy(x, memo)
    assert memo[id(memo)][0] is x


@pytest.mark.xfail(strict=True, raises=duper.Error)
def test_deepcopy_dont_memo_immutable(self):
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


def test_deepcopy_inst_vanilla(self):
    class C:
        def __init__(self, foo):
            self.foo = foo

        def __eq__(self, other):
            return self.foo == other.foo

    x = C([42])
    y = copy.deepcopy(x)
    assert y == x
    assert y.foo is not x.foo


def test_deepcopy_inst_deepcopy(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_inst_getinitargs(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_inst_getnewargs(self):
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


def test_deepcopy_inst_getnewargs_ex(self):
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


def test_deepcopy_inst_getstate(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_inst_setstate(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_inst_getstate_setstate(self):
    class C:
        def __init__(self, foo):
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


def test_deepcopy_reflexive_inst(self):
    class C:
        pass

    x = C()
    x.foo = x
    y = copy.deepcopy(x)
    assert y is not x
    assert y.foo is y


# _reconstruct()


def test_reconstruct_string(self):
    class C(object):
        def __reduce__(self):
            return ""

    x = C()
    y = copy.copy(x)
    assert y is x
    y = copy.deepcopy(x)
    assert y is x


def test_reconstruct_nostate(self):
    class C(object):
        def __reduce__(self):
            return (C, ())

    x = C()
    x.foo = 42
    y = copy.copy(x)
    assert y.__class__ is x.__class__
    y = copy.deepcopy(x)
    assert y.__class__ is x.__class__


def test_reconstruct_state(self):
    class C(object):
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


def test_reconstruct_state_setstate(self):
    class C(object):
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


def test_reconstruct_reflexive(self):
    class C(object):
        pass

    x = C()
    x.foo = x
    y = copy.deepcopy(x)
    assert y is not x
    assert y.foo is y


# Additions for Python 2.3 and pickle protocol 2


def test_reduce_4tuple(self):
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


def test_reduce_5tuple(self):
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


def test_copy_slots(self):
    class C(object):
        __slots__ = ["foo"]

    x = C()
    x.foo = [42]
    y = copy.copy(x)
    assert x.foo is y.foo


def test_deepcopy_slots(self):
    class C(object):
        __slots__ = ["foo"]

    x = C()
    x.foo = [42]
    y = copy.deepcopy(x)
    assert x.foo == y.foo
    assert x.foo is not y.foo


def test_deepcopy_dict_subclass(self):
    class C(dict):
        def __init__(self, d=None):
            if not d:
                d = {}
            self._keys = list(d.keys())
            super().__init__(d)

        def __setitem__(self, key, item):
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


def test_copy_list_subclass(self):
    class C(list):
        pass

    x = C([[1, 2], 3])
    x.foo = [4, 5]
    y = copy.copy(x)
    assert list(x) == list(y)
    assert x.foo == y.foo
    assert x[0] is y[0]
    assert x.foo is y.foo


def test_deepcopy_list_subclass(self):
    class C(list):
        pass

    x = C([[1, 2], 3])
    x.foo = [4, 5]
    y = copy.deepcopy(x)
    assert list(x) == list(y)
    assert x.foo == y.foo
    assert x[0] is not y[0]
    assert x.foo is not y.foo


def test_copy_tuple_subclass(self):
    class C(tuple):
        pass

    x = C([1, 2, 3])
    assert tuple(x) == (1, 2, 3)
    y = copy.copy(x)
    assert tuple(y) == (1, 2, 3)


def test_deepcopy_tuple_subclass(self):
    class C(tuple):
        pass

    x = C([[1, 2], 3])
    assert tuple(x) == ([1, 2], 3)
    y = copy.deepcopy(x)
    assert tuple(y) == ([1, 2], 3)
    assert x is not y
    assert x[0] is not y[0]


def test_getstate_exc(self):
    class EvilState(object):
        def __getstate__(self):
            raise ValueError("ain't got no stickin' state")

    with pytest.raises(ValueError):
        copy.copy(EvilState())


def test_copy_function(self):
    assert copy.copy(global_foo) == global_foo

    def foo(x, y):
        return x + y

    assert copy.copy(foo) == foo

    def bar():
        return None

    assert copy.copy(bar) == bar


def test_deepcopy_function(self):
    assert copy.deepcopy(global_foo) == global_foo

    def foo(x, y):
        return x + y

    assert copy.deepcopy(foo) == foo

    def bar():
        return None

    assert copy.deepcopy(bar) == bar


def check_weakref(_copy):
    class C(object):
        pass

    obj = C()
    x = weakref.ref(obj)
    y = _copy(x)
    assert y is x
    del obj
    y = _copy(x)
    assert y is x


def test_copy_weakref(self):
    check_weakref(copy.copy)


def test_deepcopy_weakref(self):
    check_weakref(copy.deepcopy)


def check_copy_weakdict(_dicttype):
    class C(object):
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
    support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1
    x, y = C(), C()
    # The underlying containers are decoupled
    v[x] = y
    assert x not in u


def test_copy_weakkeydict(self):
    check_copy_weakdict(weakref.WeakKeyDictionary)


def test_copy_weakvaluedict(self):
    check_copy_weakdict(weakref.WeakValueDictionary)


def test_deepcopy_weakkeydict(self):
    class C(object):
        def __init__(self, i):
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
    support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1


def test_deepcopy_weakvaluedict(self):
    class C(object):
        def __init__(self, i):
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
    support.gc_collect()  # For PyPy or other GCs.
    assert len(v) == 1


def test_deepcopy_bound_method(self):
    class Foo(object):
        def m(self):
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
