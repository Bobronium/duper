# SPDX-FileCopyrightText: 2023 Bobronium <appkiller16@gmail.com>
#
# SPDX-License-Identifier: MPL-2.0

"""Runtime instructions to reproduce an object"""
from __future__ import annotations

import copyreg
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from copy import Error
from copyreg import __newobj__  # type: ignore[attr-defined]
from copyreg import __newobj_ex__  # type: ignore[attr-defined]
from typing import Any
from typing import TypeVar
from typing import Union
from typing import cast


T = TypeVar("T")


def returns(x: T) -> T:
    return x


State = Union[Any, tuple[dict[str, Any], dict[str, Any]], None]


def reconstruct_state(
    new_obj: T,
    state: State = None,
    listiter: Iterable[Any] | None = None,
    dictiter: Iterable[tuple[Any, Any]] | None = None,
) -> T:
    if state is not None:
        if (setstate := getattr(new_obj, "__setstate__", None)) is not None:
            setstate(state)
        else:
            if isinstance(state, tuple) and len(state) == 2:
                dict_state, slot_state = state
                if slot_state is not None:
                    for key, value in slot_state.items():
                        setattr(new_obj, key, value)
            else:
                dict_state = cast(dict[str, Any], state)

            if dict_state is not None:
                new_obj.__dict__.update(dict_state)

    if listiter is not None:
        supports_append = cast(MutableSequence[Any], new_obj)
        for item in listiter:
            supports_append.append(item)
    if dictiter is not None:
        supports_setitem = cast(MutableMapping[Any, Any], new_obj)
        for key, value in dictiter:
            supports_setitem[key] = value

    return new_obj


def reconstruct_copy(
    func: Callable[..., T],
    args: Any,
    kwargs: Any,
    state: Any = None,
    listiter: Iterable[Any] | None = None,
    dictiter: Iterable[tuple[Any, Any]] | None = None,
    *unsupported: Any,
) -> T:
    if unsupported:
        raise NotImplementedError(f"Unsupported reduce value length {5 + len(unsupported)}")
    reconstruct_state(new_obj := func(*args, **kwargs), state, listiter, dictiter)
    return new_obj


def get_reduce(
    x: Any, cls: type[Any]
) -> (
    str
    | tuple[Callable[..., Any], tuple[Any, ...]]
    | tuple[Callable[..., Any], tuple[Any, ...], Any]
    | tuple[Callable[..., Any], tuple[Any, ...], Any, Any, Any]
    | tuple[Callable[..., Any], tuple[Any, ...], Any, Any, Any, Any]
    | tuple[Any, ...]  # FIXME: enforce proper types and make sure we never fail
):
    if custom_reduce := copyreg.dispatch_table.get(cls):
        return custom_reduce(x)
    elif (__reduce_ex__ := getattr(x, "__reduce_ex__", None)) is not None:
        return cast("tuple[Any, ...] | str", __reduce_ex__(4))
    elif __reduce__ := getattr(x, "__reduce__", None):
        return cast("tuple[Any, ...] | str", __reduce__())
    else:
        raise Error(f"un(deep)copyable object of type {cls}")


def debunk_reduce(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    state: Any = None,
    listiter: Iterable[Any] | None = None,
    dictiter: Iterable[tuple[Any, Any]] | None = None,
    *unsupported: Any,
) -> tuple[Any, ...]:
    if unsupported:
        raise NotImplementedError(f"Unexpected values in reduce value: {unsupported}")
    # __newobj__ and __newobj_ex__ are special wrapper functions
    # getting rid of them saves us from one extra call on stack
    if func is __newobj_ex__:
        cls, args, kwargs = args
        args = (cls, *args)
        func = cls.__new__
    elif func is __newobj__:
        func = args[0].__new__
        kwargs = {}
    else:
        kwargs = {}
    return func, args, kwargs, state, listiter, dictiter
