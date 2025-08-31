# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

"""Runtime instructions to reproduce an object"""

from __future__ import annotations

import copyreg
import types
from collections.abc import Callable
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import MutableMapping
from collections.abc import MutableSequence
from copy import Error
from copyreg import __newobj__  # type: ignore[attr-defined]
from copyreg import __newobj_ex__  # type: ignore[attr-defined]
from typing import Any
from typing import Final
from typing import TypeVar
from typing import cast

from duper.constants import BUILTIN_COLLECTIONS
from duper.constants import IMMUTABLE_NON_COLLECTIONS

T = TypeVar("T", bound=Any)


def returns(x: T) -> T:
    return x


_nil: Final = object

State = Any | tuple[dict[str, Any], dict[str, Any]] | None


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
                dict_state = cast("dict[str, Any]", state)

            if dict_state is not None:
                new_obj.__dict__.update(dict_state)

    if listiter is not None:
        supports_append = cast("MutableSequence[Any]", new_obj)
        for item in listiter:
            supports_append.append(item)
    if dictiter is not None:
        supports_setitem = cast("MutableMapping[Any, Any]", new_obj)
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
) -> T:
    reconstruct_state(new_obj := func(*args, **kwargs), state, listiter, dictiter)
    return new_obj


ReduceTuple = (
    tuple[Callable[..., Any], tuple[Any, ...]]
    | tuple[Callable[..., Any], tuple[Any, ...], Any | None]
    | tuple[Callable[..., Any], tuple[Any, ...], Any | None, Iterator[Any] | None]
    | tuple[
        Callable[..., Any],
        tuple[Any, ...],
        Any | None,
        Iterator[Any] | None,
        Iterator[tuple[Any, Any]] | None,
    ]
)


def get_reduce(x: Any, cls: type[Any]) -> str | ReduceTuple:
    if custom_reduce := copyreg.dispatch_table.get(cls):
        return custom_reduce(x)
    if (__reduce_ex__ := getattr(x, "__reduce_ex__", None)) is not None:
        return cast("tuple[Any, ...] | str", __reduce_ex__(4))
    if __reduce__ := getattr(x, "__reduce__", None):
        return cast("tuple[Any, ...] | str", __reduce__())
    raise Error(f"un(deep)copyable object of type {cls}")


def debunk_reduce(
    rv: ReduceTuple, cls: type[Any], *, try_simplify_call: bool = False
) -> tuple[
    Callable[..., Any],
    tuple[Any, ...],
    dict[str, Any],
    Any,
    Iterator[Any] | None,
    Iterator[tuple[Any, Any]] | None,
]:
    func, args = rv[0], rv[1]
    # mypy cannot understand length = len(rv) narrowing :(
    if len(rv) == 2:
        state = listiter = dictiter = None
    elif len(rv) == 3:
        state = rv[2]
        listiter = dictiter = None
    elif len(rv) == 4:
        state = rv[2]
        listiter = rv[3]
        dictiter = None
    else:
        state = rv[2]
        listiter = rv[3]
        dictiter = rv[4]

    # __newobj__ and __newobj_ex__ are special wrapper functions
    # getting rid of them saves us from one extra call on stack
    kwargs: dict[str, Any]
    if func is __newobj_ex__:
        cls, args, kwargs = args
        args = (cls, *args)
        func = cls.__new__
    elif func is __newobj__:
        func = (cls := args[0]).__new__
        kwargs = {}
    else:
        kwargs = {}

    if cls is object or (
        try_simplify_call
        # convert A.__new__(A) to just A()
        # doesn't make sense to do it when reconstructing object on the fly
        # but might be worth for repeated reconstruction
        and (
            func is cls.__new__
            # A() triggers: type(A).__call__() -> A.__init__(A.__new__(A))
            # so we want to make sure there's no custom logic in here
            # by verifying that these were not overwritten
            and (cls.__init__ is object.__init__ and type(cls).__call__ is type.__call__)
        )
    ):
        return cls, args[1:], kwargs, state, listiter, dictiter
    return func, args, kwargs, state, listiter, dictiter


Memo = dict[int, Any]


def _deepcopy(obj: T, memo: Memo) -> T:
    if (cls := type(obj)) in IMMUTABLE_NON_COLLECTIONS or issubclass(cls, type):
        return obj

    vid = id(obj)
    if (existing_copy := memo.get(vid, _nil)) is not _nil:
        return cast("T", existing_copy)

    if cls in BUILTIN_COLLECTIONS and not obj:  # type: ignore[comparison-overlap]
        empty_instance = cls()
        memo[vid] = empty_instance
        memo[id(memo)].append(obj)
        return cast("T", empty_instance)

    if cls is dict:
        result_dict: dict[Any, Any] = {}
        memo[vid] = result_dict  # memoize before recursion
        for original_key, original_value in obj.items():
            copied_key = _deepcopy(original_key, memo)
            copied_value = _deepcopy(original_value, memo)
            result_dict[copied_key] = copied_value

        memo[id(memo)].append(obj)
        return result_dict  # type: ignore[return-value]

    if cls is list:
        result_list: list[Any] = []
        memo[vid] = result_list  # memoize before recursion
        for original_item in obj:
            result_list.append(_deepcopy(original_item, memo))  # noqa: PERF401
        memo[id(memo)].append(obj)
        return result_list  # type: ignore[return-value]

    if cls is set:
        result_set: set[Any] = set()
        memo[vid] = result_set  # memoize before recursion
        for original_item in obj:
            result_set.add(_deepcopy(original_item, memo))
        memo[id(memo)].append(obj)
        return result_set  # type: ignore[return-value]

    if cls is tuple:
        changed = False
        items: list[Any] = []
        for original_item in obj:
            copied_item = _deepcopy(original_item, memo)
            if copied_item is not original_item:
                changed = True
            items.append(copied_item)

        if not changed:
            return obj

        if (already_copied := memo.get(vid, _nil)) is not _nil:
            return cast("T", already_copied)

        result_tuple = tuple(items)
        memo[vid] = result_tuple
        memo[id(memo)].append(obj)
        return result_tuple  # type: ignore[return-value]

    if cls is frozenset:
        changed = False
        items_list: list[Any] = []
        for original_item in obj:
            copied_item = _deepcopy(original_item, memo)
            if copied_item is not original_item:
                changed = True
            items_list.append(copied_item)

        if not changed:
            return obj

        if (already_copied := memo.get(vid, _nil)) is not _nil:
            return cast("T", already_copied)

        copied = frozenset(items_list)
        memo[vid] = copied
        memo[id(memo)].append(obj)
        return copied  # type: ignore[return-value]

    if cls is types.ModuleType:
        return obj

    if cls is types.MethodType:
        bound_self_copied = _deepcopy(obj.__self__, memo)
        result_method = types.MethodType(
            cast("Callable[..., object]", obj.__func__),
            bound_self_copied,
        )
        memo[vid] = result_method
        memo[id(memo)].append(obj)
        return result_method  # type: ignore[return-value]

    if cls is object:  # doesn't hurt at this point
        memo[vid] = new_object = object()
        memo[id(memo)].append(obj)
        return new_object  # type: ignore[return-value]

    deep_copy_hook = getattr(obj, "__deepcopy__", None)
    if deep_copy_hook is not None:
        result: T = deep_copy_hook(memo)
        memo[vid] = result
        memo[id(memo)].append(obj)
        return result

    rv = get_reduce(obj, cls)
    if isinstance(rv, str):
        return obj

    args: tuple[Any, ...]
    func, args = rv[0], rv[1]
    # mypy cannot understand length = len(rv) narrowing :(
    if len(rv) == 2:
        state = listiter = dictiter = None
    elif len(rv) == 3:
        state = rv[2]
        listiter = dictiter = None
    elif len(rv) == 4:
        state = rv[2]
        listiter = rv[3]
        dictiter = None
    else:
        state = rv[2]
        listiter = rv[3]
        dictiter = rv[4]

    if args == ():
        new_object = cast("T", func())
    else:
        new_object = cast("T", func(*[_deepcopy(arg, memo) for arg in args]))

    memo[vid] = new_object  # memoize before state reconstruction

    if state is not None:
        setstate = getattr(new_object, "__setstate__", None)
        if setstate is not None:
            setstate(_deepcopy(state, memo))
        else:
            if isinstance(state, tuple) and len(state) == 2:
                dict_state, slot_state = state
                if slot_state is not None:
                    for attribute_name, attribute_value in slot_state.items():
                        setattr(
                            new_object,
                            attribute_name,
                            _deepcopy(attribute_value, memo),
                        )
            else:
                dict_state = cast("dict[str, Any]", state)

            if dict_state is not None:
                new_object.__dict__.update(_deepcopy(dict_state, memo))

    if listiter is not None:
        sequence_interface = cast("MutableSequence[Any]", new_object)
        for sequence_item in listiter:
            sequence_interface.append(_deepcopy(sequence_item, memo))

    if dictiter is not None:
        mapping_interface = cast("MutableMapping[Any, Any]", new_object)
        for mapping_key, mapping_value in dictiter:
            mapping_interface[mapping_key] = _deepcopy(mapping_value, memo)

    return new_object
