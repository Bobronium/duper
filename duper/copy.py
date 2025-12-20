# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import copy as builtin_copy
from collections.abc import Callable
from functools import partial
from typing import Any
from typing import NoReturn
from typing import Protocol
from typing import TypeVar
from typing import cast

from duper import _msg
from duper import _replicate
from duper.builders.ast import build_reconstructor
from duper.builders.runtime import _deepcopy
from duper.builders.runtime import debunk_reduce
from duper.builders.runtime import get_reduce
from duper.builders.runtime import reconstruct_copy
from duper.builders.runtime import returns
from duper.constants import BUILTIN_COLLECTIONS
from duper.constants import BUILTIN_MUTABLE
from duper.constants import IMMUTABLE_NON_COLLECTIONS
from duper.constants import IMMUTABLE_TYPES
from duper.constants import BuiltinMutableType

T = TypeVar("T")

Constructor = Callable[[], T]
Memo = dict[int, Any]


class Builder(Protocol[T]):
    def __call__(
        self,
        x: T,
        *,
        keep_by_reference: dict[int, Any] | None = None,
        ignore_deepcopy_method: bool = False,
    ) -> Constructor[T]: ...


class Error(builtin_copy.Error):
    """
    Builtin copy module can rise either copy.Error or other exceptions that happens during copying.

    Duper will do its best to always rise duper.Error subclasses.
    """


def warn(
    obj: T, memo: Any, factory: Callable[[T], Callable[[], T]], error: Exception
) -> Callable[[], T]:
    import warnings

    warnings.warn(
        f"\nCan't use {factory.__name__[60:]} to copy this {type(obj).__name__}: {error}"
        f"\nFalling back to standard deepcopy()"
        f"\nNote: such fallbacks may be slow, if they happen too often, "
        f"consider using duper.deepcopy() directly",
        RuntimeWarning,
        stacklevel=3,
    )
    return partial(_deepcopy, obj, memo or {})


def fail(obj: T, _: Any, factory: Builder[T], error: Exception) -> NoReturn:
    __tracebackhide__ = True

    raise Error(
        f"Can't use `{_msg.repr(reconstructs)}(..., factory={_msg.repr(factory)})` "
        f"to copy this {_msg.repr(obj)[300:]}:"
        "\n" + " " * (len(_msg.repr(Error)) + 3) + f"{error!r}"
        f"\n\nTip: `{_msg.repr(reconstructs)}(..., fallback={_msg.repr(warn)})` "
        f"will fallback to standard deepcopy on errors"
    ) from error


def reraise(_: T, __: Any, ___: Builder[T], ____: Exception) -> NoReturn:
    raise  # noqa: PLE0704


def reconstructs(
    obj: T,
    /,
    *,
    builder: Builder[T] = build_reconstructor,
    ignore_deepcopy_method: bool = False,
    fallback: Callable[..., Callable[[], T]] = fail,
    check: bool = True,
    _keep_by_reference: Memo | None = None,
) -> Callable[[], T]:
    """
    Finds the fastest way of deep-copying an object.

    If object is immutable, it will be returned as is.
    If it's an empty builtin collection, it will return its class (list, dict, etc.)

    If obj is non-empty builtin collection, it will check if all values

    Then it will check for __deepcopy__ method and will use it, if it's defined.

    Constructs a factory that knows how to reconstruct an object _fast_.

    :param obj: object to reconstruct
    :param builder: an internal factory that will do the work if we
    :param fallback:
    :param check:
    :param _keep_by_reference: (experimental) can be used to avoid reconstruction
     of some values and instead reference them
    :param ignore_deepcopy_method: if True, custom __deepcopy__ will be ignored.
     Instead, objects will be reconstructed via __reduce__
    """

    if (
        _keep_by_reference is not None and id(obj) in _keep_by_reference
    ):  # quite an exotic case, but should be supported, I guess
        return partial(returns, _keep_by_reference[id(obj)])

    if (cls := cast("type[Any]", type(obj))) in IMMUTABLE_NON_COLLECTIONS or issubclass(cls, type):
        return partial(returns, obj)

    # special case for empty collections. should also work for empty tuples since they are constant
    if (cls in BUILTIN_COLLECTIONS) and not obj:
        return cls

    if not ignore_deepcopy_method and (cp := getattr(obj, "__deepcopy__", None)) is not None:
        # seems like we can't speed things up here
        # being consistent with builtin deepcopy is better
        # than being just faster
        return partial(cp({}).__deepcopy__, {})

    try:
        compiled = builder(
            obj,
            keep_by_reference=_keep_by_reference,
            ignore_deepcopy_method=ignore_deepcopy_method,
        )
        if not check:
            return compiled
        try:
            compiled()
        except Exception as e:
            raise Error(
                f"Cannot reconstruct this object (see details above): {e}, {repr(compiled)[:300]=}"
            ) from e
        else:
            return compiled
    except Exception as e:  # noqa: BLE001
        return fallback(obj, None, builder, e)


def copies(obj: T) -> Callable[[], T]:
    """
    Finds the fastest way to repeatedly copy an `obj` and returns copy factory
    """
    # handle two special cases when we don't need to build any fancy reconstructor
    if (cls := cast("type[Any]", type(obj))) in IMMUTABLE_TYPES or issubclass(cls, type):
        return partial(returns, obj)  # can just always return the same object

    if cls in BUILTIN_COLLECTIONS and not obj:
        return cls  # special case for empty collections

    if cls in BUILTIN_MUTABLE:
        return cast("Callable[[], T]", cast("BuiltinMutableType", obj).copy().copy)
    if cp := getattr(obj, "__copy__", None):
        return cast("Callable[[], T]", cp().__copy__)

    rv = get_reduce(obj, cls)
    if isinstance(rv, str):
        return partial(returns, obj)

    func, args, kwargs, state, listiter, dictiter = debunk_reduce(rv, cls=cls)
    if state is not None or listiter is not None or dictiter is not None:
        return partial(reconstruct_copy, func, args, kwargs, state, listiter, dictiter)

    return partial(func, *args, **kwargs)


def copy(obj: T) -> T:
    """
    Faster drop-in replacement for copy.copy().
    """
    if (cls := cast("type[Any]", type(obj))) in IMMUTABLE_TYPES or issubclass(cls, type):
        return obj

    if cls in BUILTIN_COLLECTIONS and not obj:
        return cast("T", cls())  # special case for empty collections

    if cls in BUILTIN_MUTABLE:
        return cast("T", cast("BuiltinMutableType", obj).copy())

    if cp := getattr(obj, "__copy__", None):
        return cast("T", cast("Callable[[], T]", cp()))

    rv = get_reduce(obj, cls)
    if isinstance(rv, str):
        return obj

    func, args, kwargs, state, listiter, dictiter = debunk_reduce(rv, cls=cls)

    if state is not None or listiter is not None or dictiter is not None:
        return cast("T", reconstruct_copy(func, args, kwargs, state, listiter, dictiter))

    return cast("T", func(*args, **kwargs))


def deepcopy(x: T, memo: Memo | None = None) -> T:
    """
    Faster drop-in replacement for copy.deepcopy.
    """
    if memo is None:
        memo = {}

    memo.setdefault(id(memo), [])

    return _deepcopy(x, memo)


def replicate(obj: T, /, n: int, compile_after: int = 20) -> list[T]:
    """
    Returns list of `n` deep copies of the `obj`.

    if `n` > `compile_after`, it compiles a minimal set of instructions to reproduce the object.
    Compilation takes time, but pays off by much faster copying.
    """
    if n <= compile_after:  # likely still going to be faster than building a factory
        return [deepcopy(obj) for _ in range(n)]
    factory = build_reconstructor(obj)
    # calling non-compiled function in a loop here turns out to be slower than
    # calling it in python
    return _replicate(factory, n)
