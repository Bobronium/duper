# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

import copy
from collections.abc import Callable
from math import ceil
from typing import Any
from typing import NoReturn
from typing import TypeVar

T = TypeVar("T")


def reraise() -> NoReturn:
    raise  # noqa: PLE0704


def run_in_xpython(func: Callable[[], T]) -> T:
    try:
        from xpython.byteop.byteop24 import (  # type: ignore[import-untyped, import-not-found, unused-ignore]
            ByteOp24,
        )
        from xpython.vm import PyVM  # type: ignore[import-untyped, import-not-found, unused-ignore]
    except ImportError:
        raise ImportError(f"To use {run_in_xpython.__name__}, install 'duper[debug]'")

    ByteOp24.traceback_from_frame = staticmethod(reraise)
    return PyVM().run_code(func.__code__, func.__globals__.copy(), {}, toplevel=False)  # type: ignore[no-any-return]


def find_minimal_example(
    data: T,
    check: Callable[[T], Any],
    raises: type[BaseException] | tuple[type[BaseException]],
) -> T:
    """
    Reduce `data` to a minimal example that still triggers `check` to raise.
    - Delta-debug chunk removals for speed.
    - Smartly detect container-length-only bugs via exponential + linear search,
      for both lists (number of items) and dicts (number of keys).
    - Print both successful (✔) and unsuccessful (✘) removal attempts.
    """
    current = copy.deepcopy(data)

    def try_check(d: T) -> bool:
        try:
            check(d)
        except raises:
            return True
        else:
            return False

    if not try_check(current):
        raise RuntimeError("Original data must raise.")

    def format_path(path: list[Any]) -> str:
        return "root" if not path else "".join(f"[{p!r}]" for p in path)

    def get_at(path: list[Any]) -> Any:
        ref = current
        for p in path:
            ref = ref[p]  # type: ignore[index]
        return ref

    def set_at(path: list[Any], subtree: Any) -> None:
        nonlocal current
        if not path:
            current = subtree
        else:
            ref = current
            for p in path[:-1]:
                ref = ref[p]  # type: ignore[index]
            ref[path[-1]] = subtree  # type: ignore[index]

    def try_replace(path: list[Any], subtree: Any) -> bool:
        trial = copy.deepcopy(current)
        if not path:
            trial = subtree
        else:
            ref = trial
            for p in path[:-1]:
                ref = ref[p]  # type: ignore[index]
            ref[path[-1]] = subtree  # type: ignore[index]
        return try_check(trial)

    def ddmin_list(path: list[Any]) -> None:
        lst = get_at(path)
        pth = format_path(path)
        length = len(lst)

        # 1) Try removing everything
        if length:
            if try_replace(path, []):
                print(f"✔ Removed ALL items at {pth}")
                set_at(path, [])
                return
            print(f"✘ Cannot remove ALL items at {pth} (error goes away)")

        # 2) Detect length-only bug via exponential search
        if length:
            placeholder = [None] * length
            if try_replace(path, placeholder):
                print(f"ℹ Detected length-only condition at {pth}, original length={length}")
                # exponential find upper bound
                step = 1
                while step < length and not try_replace(path, [None] * step):
                    step *= 2
                step = min(step, length)
                lo = step // 2
                hi = step
                threshold = None
                for n in range(lo + 1, hi + 1):
                    if try_replace(path, [None] * n):
                        threshold = n
                        break
                if threshold is not None:
                    print(f"✔ Minimal failing length at {pth} is {threshold}")
                    set_at(path, [None] * threshold)
                    return
            else:
                print(f"✘ Content matters at {pth}, not just length={length}")

        # 3) Bulk chunk removals
        n = 2
        length = len(get_at(path))
        while n <= length:
            size = ceil(length / n)
            removed_any = False
            for start in range(0, length, size):
                end = min(start + size, length)
                chunk = list(range(start, end))
                trial = [v for i, v in enumerate(lst) if i < start or i >= end]
                if try_replace(path, trial):
                    print(f"✔ Removed chunk indices {chunk} at {pth}")
                    set_at(path, trial)
                    lst = get_at(path)
                    length = len(lst)
                    n = 2
                    removed_any = True
                    break
                print(f"✘ Cannot remove chunk {chunk} at {pth}")
            if not removed_any:
                n *= 2

        # 4) Single-item removals
        lst = get_at(path)
        i = 0
        while i < len(lst):
            trial = lst[:i] + lst[i + 1 :]
            if try_replace(path, trial):
                print(f"✔ Removed index {i} at {pth}, element={repr(lst[i])[:50]}")
                set_at(path, trial)
                lst = get_at(path)
            else:
                print(f"✘ Keeping index {i} at {pth}, element={repr(lst[i])[:50]}")
                i += 1

        # 5) Recurse into elements
        for j in range(len(get_at(path))):
            recurse([*path, j])

    def ddmin_dict(path: list[Any]) -> None:
        d = get_at(path)
        pth = format_path(path)

        # 1) Remove all keys
        if d:
            if try_replace(path, {}):
                print(f"✔ Removed ALL keys at {pth}")
                set_at(path, {})
                return
            print(f"✘ Cannot remove ALL keys at {pth} (error goes away)")

        # 2) Detect length-only bug for dict keys
        length = len(d)
        if length:
            placeholder = {f"__dummy{i}": None for i in range(length)}
            if try_replace(path, placeholder):
                print(f"ℹ Detected key-count–only condition at {pth}, original keys={length}")
                # exponential find upper bound
                step = 1
                while step < length and not try_replace(
                    path, {f"__dummy{i}": None for i in range(step)}
                ):
                    step *= 2
                step = min(step, length)
                lo = step // 2
                hi = step
                threshold = None
                for n in range(lo + 1, hi + 1):
                    trial = {f"__dummy{i}": None for i in range(n)}
                    if try_replace(path, trial):
                        threshold = n
                        break
                if threshold is not None:
                    print(f"✔ Minimal failing key-count at {pth} is {threshold}")
                    set_at(path, {f"__dummy{i}": None for i in range(threshold)})
                    return
            else:
                print(f"✘ Content matters at {pth}, not just key-count={length}")

        # 3) Bulk key-chunk removals
        keys = list(d.keys())
        n = 2
        while n <= len(keys):
            size = ceil(len(keys) / n)
            removed_any = False
            for start in range(0, len(keys), size):
                chunk = keys[start : start + size]
                trial = {k: v for k, v in d.items() if k not in chunk}
                if try_replace(path, trial):
                    print(f"✔ Removed chunk keys {chunk} at {pth}")
                    set_at(path, trial)
                    d = get_at(path)
                    keys = list(d.keys())
                    n = 2
                    removed_any = True
                    break
                print(f"✘ Cannot remove chunk keys {chunk} at {pth}")
            if not removed_any:
                n *= 2

        # 4) Single-key removals
        for key in list(get_at(path).keys()):
            trial = copy.deepcopy(get_at(path))
            removed: Any = trial.pop(key)
            if try_replace(path, trial):
                print(f"✔ Removed key {key!r} at {pth}, value={repr(removed)[:50]}")
                set_at(path, trial)
            else:
                print(f"✘ Keeping key {key!r} at {pth}")

        # 5) Recurse into values
        for key in list(get_at(path).keys()):
            recurse([*path, key])

    def recurse(path: list[Any] | None = None) -> None:
        if path is None:
            path = []
        subtree = get_at(path)
        if isinstance(subtree, dict):
            ddmin_dict(path)
        elif isinstance(subtree, list):
            ddmin_list(path)
        # primitives: nothing to do

    recurse([])
    return current
