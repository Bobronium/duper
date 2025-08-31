# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from typing import Any
from typing import NoReturn
from typing import TypeVar

from duper.builders._tracking import ObjectInfo

T = TypeVar("T")

OT = TypeVar("OT", bound=ObjectInfo)
_sentinel = object()


class SentinelMemo(dict[int, Any]):
    def __init__(
        self,
        vid: int,
        seen: dict[int, OT],
        info_cls: type[OT],
    ) -> None:
        super().__init__()
        self._vid = vid
        self._seen = seen
        self._info_cls = info_cls

    def _validate(self, key: int, value: Any = _sentinel) -> None:
        existing = self._seen.get(key, None)
        if existing is None:
            if value is not _sentinel:
                self._seen[key] = self._info_cls(
                    key, value, type(value), None, exclusive_for=self._vid
                )
            return

        if self._vid not in (key, existing.exclusive_for):
            # reusing these is not impossible, but tricky to implement
            # it would require maintaining memo name that would collect
            # all objects reconstructed via
            # custom __deepcopy__ methods, as well as references to objects reconstructed outside of
            # custom __deepcopy__, but later referenced there
            raise NotImplementedError(
                "Types with custom __deepcopy__ referencing previously "
                "reconstructed objects are not supported yet. See the comment above."
            )

    def get(self, key: int, default: Any = None) -> Any:
        self._validate(key)
        return super().get(key, default)

    def __setitem__(self, key: int, value: Any) -> None:
        self._validate(key, value)
        return super().__setitem__(key, value)

    def __getitem__(self, key: int) -> Any:
        self._validate(key)
        return super().__getitem__(key)

    def __contains__(self, key: int) -> bool:  # type: ignore[override]
        self._validate(key)
        return super().__contains__(key)


def forbid_references(value: Any) -> NoReturn:
    raise NotImplementedError(
        f"{value} was reconstructed by custom __deepcopy__ and then referenced in other object."
        " This is not supported yet."
    )
