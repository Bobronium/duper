# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import copy
from collections import OrderedDict  # noqa
from collections.abc import Callable
from collections.abc import Iterable
from functools import partial
from typing import Any
from typing import NoReturn
from typing import TypeVar
from typing import cast

from duper import _msg
from duper.constants import BUILTIN_COLLECTIONS
from duper.constants import BUILTIN_MUTABLE
from duper.constants import IMMUTABLE_NON_COLLECTIONS
from duper.constants import IMMUTABLE_TYPES
from duper.constants import BuiltinCollectionType
from duper.constants import BuiltinMutableType
from duper.factories.ast import ast_factory
from duper.factories.runtime import debunk_reduce
from duper.factories.runtime import get_reduce
from duper.factories.runtime import reconstruct_copy
from duper.factories.runtime import returns


T = TypeVar("T")


Constructor = Callable[[], T]
Factory = Callable[[T], Constructor[T]]


class Error(copy.Error, TypeError):
    """
    Copy module can rise either copy.Error or any other exception that happens during copying
    Duper will do its best effort to always rise only duper.Error subclasses
    """


def warn(
    obj: T, memo: Any, factory: Callable[[T], Callable[[], T]], error: Exception
) -> Callable[[], T]:
    import warnings

    warnings.warn(
        f"Can't use `{_msg.repr(deepdups)}(..., factory={_msg.repr(factory)})` to copy this {_msg.repr(obj)}:"
        "\n" + " " * (len(_msg.repr(Error)) + 3) + f"{error!r}"
        f"\nFalling back to builtin copy.deepcopy()"
        f"\nNote: such fallbacks may be slow, if they happen too often, consider using copy.deepcopy() directly",
        RuntimeWarning,
        stacklevel=3,
    )
    return partial(copy.deepcopy, obj, memo)


def fail(obj: T, _: Any, factory: Callable[[T], Callable[[], T]], error: Exception) -> NoReturn:
    __tracebackhide__ = True

    raise Error(
        f"Can't use `{_msg.repr(deepdups)}(..., factory={_msg.repr(factory)})` to copy this {_msg.repr(obj)}:"
        "\n" + " " * (len(_msg.repr(Error)) + 3) + f"{error!r}"
        f"\n\nTip: `{_msg.repr(deepdups)}(..., fallback={_msg.repr(warn)})` will fallback to standard deepcopy on errors"
    ) from error


def deepdups(
    obj: T,
    /,
    *,
    factory: Callable[[T], Callable[[], T]] = ast_factory,
    fallback: Callable[..., Callable[[], T]] = fail,
    check: bool = True,
) -> Callable[[], T]:
    """
    Finds the fastest way of deep-copying an object.

    If object is immutable, it will be returned as is.
    If it's an empty builtin collection, it will return its class (list, dict, etc.)

    If obj is non-empty builtin collection, it will check if all values

    Then it will check for __deepcopy__ method and will use it, if it's defined.

    Constructs a factory that knows how to reconstruct an object _fast_.

    :param obj: object to reconstruct
    :param factory: an internal factory that will do the work if we
    :param fallback:
    :param check:
    """
    if (cls := cast(type[Any], type(obj))) in IMMUTABLE_NON_COLLECTIONS or issubclass(cls, type):
        return partial(returns, obj)
    # special case for empty collections. should also work for empty tuples since they are constant
    if (builtin := cls in BUILTIN_COLLECTIONS) and not obj:
        return cls

    if builtin:
        if cls is dict:
            container: Iterable[Any] = cast("dict[Any, Any] | OrderedDict[Any, Any]", obj).values()
        else:
            container = cast(BuiltinCollectionType, obj)

        if all(type(v) in IMMUTABLE_NON_COLLECTIONS for v in container):
            if cls in BUILTIN_MUTABLE:
                return cast(Callable[[], T], cast(BuiltinMutableType, obj).copy().copy)
            return partial(returns, obj)  # it's a shallow tuple or frozenset
    else:
        # seems like we can't speed things up here, unfortunately
        # being consistent with builtin deepcopy is better
        # than being just faster
        if (cp := getattr(obj, "__deepcopy__", None)) is not None:
            return partial(cp({}).__deepcopy__, {})

    try:
        compiled = factory(obj)
        if not check:
            return compiled
        try:
            compiled()
        except Exception as e:
            raise Error("Cannot reconstruct this object, see details above") from e
        return compiled
    except Exception as e:
        return fallback(obj, None, factory, e)


def deepdupe(
    obj: T,
    memo: Any = None,
    *,
    factory: Factory[T] = ast_factory,
    fallback: Callable[[T, Any, Factory[T], Exception], Constructor[T]] = fail,
) -> T:
    """
    Mirrors interface of copy.deepcopy. Mostly here for test and research purposes.
    Constructs a factory, calls it and throws it away, returning the result.

    It's generally going to be slower than deepcopy if used that way.

    If speed is important for your application, you should use `duper.depdupes` or `duper.Duper` instead.

    >>> o = {"a": {}}
    >>> c = deepdupe()
    >>> assert o == c
    >>> assert o["a"] is not c["a"]


    :return:
    """
    if memo is not None:  # error: Local variable "memo" has inferred type None; add an annotation
        return fallback(
            obj,
            memo,
            factory,
            NotImplementedError("Usage of memo is not supported."),
        )()
    return deepdups(obj, factory=factory, fallback=fallback)()


def dups(obj: T) -> Callable[[], T]:
    """
    Finds the fastest way to repeatedly copy an object and returns copy factory
    """
    # handle two special cases when we don't need to build any fancy reconstructor
    if (cls := cast(type[Any], type(obj))) in IMMUTABLE_TYPES or issubclass(cls, type):
        return partial(returns, obj)  # can just always return the same object

    if cls in BUILTIN_COLLECTIONS and not obj:
        return cls  # special case for empty collections

    if cls in BUILTIN_MUTABLE:
        return cast(Callable[[], T], cast(BuiltinMutableType, obj).copy().copy)
    if cp := getattr(obj, "__copy__", None):
        return cast(Callable[[], T], cp().__copy__)

    rv = get_reduce(obj, cls)
    if isinstance(rv, str):
        return partial(returns, obj)

    func, args, kwargs, *rest = debunk_reduce(*rv)

    if any(r is not None for r in rest):
        return partial(reconstruct_copy, func, args, kwargs, *rest)

    return partial(func, *args, **kwargs)


def dupe(obj: T) -> T:
    """
    Mirrors interface of copy.copy. Mostly useful for testing purposes.

    Constructs a factory, calls it and throws it away, returning the result.

    It's generally going to be slower than deepcopy if used that way.

    If speed is important for your application, you should use `duper.depdupes` or `duper.Duper` instead.

    >>> o = {"a": {}}
    >>> c = deepdupe()
    >>> assert o == c
    >>> assert o["a"] is not c["a"]


    :param obj:
    :param memo:
    :param factory:
    :param fallback:
    :return:
    """
    return dups(obj)()
