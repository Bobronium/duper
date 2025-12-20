# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

"""
Case naming scheme (pytest -k friendly):
- atom:*                – small atomic/builtin scalars & singletons
- container:*           – plain containers (lists/tuples/sets/dicts/fsets/range/slice)
- alias:*               – shared-identity graphs (no true cycles)
- reflexive:*           – true cycles / self or mutual refs
- proto:*               – protocol-driven objects (__deepcopy__, __getnewargs*__, __reduce*__, __get/setstate__)
- func:*                – functions, code objects, bound methods, closures, descriptors
- stdlib:*              – stdlib classes, enums, dataclasses, typing, regex, exceptions, types.*
- numeric:*             – fractions/decimal/array/memoryview/float edge cases
- path:*                – pathlib paths
- time:*                – datetime family (aware/naive), timedelta
- large:*               – larger graphs meant for perf/bench
- thirdparty:<lib>:*    – optional cases gated by import success
- xfail:pickle:*        – commonly non-picklable objects worth exercising

Export:
- Case
- OBJECTS (tuple[Case, ...])
"""

import array
import dataclasses as dc
import datetime as dt
import decimal
import enum
import fractions
import inspect
import math
import re
import traceback
import types
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple, TypedDict


@dataclass
class Case:
    name: str
    obj: Any


def _reflexive_self_list():
    x: list[Any] = []
    x.append(x)
    return x


def _reflexive_self_dict():
    d: dict[str, Any] = {}
    d["self"] = d
    return d


def _reflexive_mutual_lists():
    a: list[Any] = []
    b: list[Any] = []
    a.append(b)
    b.append(a)
    return a  # (b is reachable via a[0])


def _reflexive_tuple_list():
    t = ([],)
    t[0].append(t)
    return t


def _reflexive_dict_list_cross():
    lst: list[Any] = []
    d: dict[str, Any] = {"l": lst}
    lst.append(d)
    return d


def _alias_shared_list_pair():
    shared = ["A", "B"]
    return [shared, shared]


def _alias_mixed_combo():
    shared = ["X", {"k": [1, 2]}]
    return [shared, {"again": shared}, (shared,)]


def _alias_deep_shared_with_cycle():
    base: list[Any] = []
    pair = [base, base]
    d = {"a": base, "b": pair}
    base.append(d)  # cycle through base -> d -> base
    return d


def _large_deep_graph(depth: int = 6, leaf_len: int = 64):
    leaf = {"payload": list(range(leaf_len))}
    node = leaf
    for i in range(depth):
        node = {"d": i, "pair": [node, {"wrap": node}]}
    root = {"root": node}
    root["alias1"] = root["root"]
    root["alias2"] = root["root"]["pair"][0]
    return root


def _bound_method_holder():
    class BM:
        def m(self) -> int:
            return 1

    inst = BM()
    inst.bound = inst.m  # attribute holding a bound method
    return inst


def _closure_func():
    cap = [1]

    def inner(y: int) -> int:
        cap.append(y)
        return sum(cap)

    return inner


def _mappingproxy():
    return types.MappingProxyType({"a": [1, 2], "b": {"k": 3}})


# ----------------------------- Protocol classes -----------------------------


class ProtoDeepCopy:
    def __init__(self, xs) -> None:
        self.xs = xs

    def __deepcopy__(self, memo=None):
        import copy

        cls = type(self)
        obj = cls(copy.deepcopy(self.xs, memo))
        return obj

    def __eq__(self, other):  # pragma: no cover (equality helper)
        return isinstance(other, ProtoDeepCopy) and self.xs == other.xs


class ProtoGetNewArgs(int):
    def __new__(cls, payload):
        self = int.__new__(cls, 7)
        self.payload = payload
        return self

    def __getnewargs__(self):
        return (self.payload,)


class ProtoGetNewArgsEx(int):
    def __new__(cls, *, data):
        self = int.__new__(cls, 9)
        self.data = data
        return self

    def __getnewargs_ex__(self):
        return (), {"data": self.data}


class ProtoReduce:
    def __init__(self, a, b) -> None:
        self.a, self.b = a, b

    def __reduce__(self):
        def _rebuild(a, b):
            obj = ProtoReduce.__new__(ProtoReduce)
            obj.a, obj.b = a, b
            return obj

        return (_rebuild, (self.a, self.b))


class ProtoGetStateSetState:
    def __init__(self, foo) -> None:
        self.foo = foo

    def __getstate__(self):
        return {"foo": self.foo}

    def __setstate__(self, st):
        self.__dict__.update(st)


class SlotClass:
    __slots__ = ("a", "b")

    def __init__(self, a, b) -> None:
        self.a, self.b = a, b

    def __eq__(self, other: object) -> bool:  # pragma: no cover
        return isinstance(other, SlotClass) and (self.a, self.b) == (other.a, other.b)


# ----------------------------- Enums / typing-ish ---------------------------


class Animal(enum.Enum):
    CAT = 1
    DOG = 2


class Point(NamedTuple):
    x: int
    y: int
    meta: Any = None


class UserTD(TypedDict):
    id: int
    name: str


# ----------------------------- Standard library objects ---------------------


@dc.dataclass
class UserDC:
    name: str
    tags: list[str]
    props: dict[str, Any]


@dc.dataclass(frozen=True)
class FrozenPair:
    x: int
    y: tuple[int, ...]


# pattern, traceback, signature, etc.
def _make_traceback_exception():
    try:
        1 / 0
    except Exception as e:
        return traceback.TracebackException.from_exception(e)


# ----------------------------- Third-party (optional) -----------------------


def _thirdparty_cases():
    out: list[Case] = []
    # numpy
    try:
        import numpy as np

        def _np_object_alias_array():
            shared = {"k": [1, 2]}
            arr = np.empty(3, dtype=object)
            arr[:] = [shared, shared, shared]
            return arr

        out += [
            Case("thirdparty:numpy:array_i32_2x3", np.arange(6, dtype=np.int32).reshape(2, 3)),
            Case(
                "thirdparty:numpy:array_f64_nan_inf", np.array([0.0, -0.0, np.nan, np.inf, -np.inf])
            ),
            Case(
                "thirdparty:numpy:array_structured",
                np.array([(1, 2.0), (3, 4.5)], dtype=[("a", "i4"), ("b", "f8")]),
            ),
            Case("thirdparty:numpy:array_object_alias", _np_object_alias_array()),
        ]
    except Exception:
        pass
    # pandas
    try:
        import pandas as pd

        out += [
            Case("thirdparty:pandas:series_Int64_na", pd.Series([1, None, 3], dtype="Int64")),
            Case(
                "thirdparty:pandas:dataframe_categorical",
                pd.DataFrame({"a": [1, 2, 1], "b": pd.Categorical(["x", "y", "x"])}),
            ),
            Case(
                "thirdparty:pandas:dataframe_dt_tz",
                pd.DataFrame(
                    {"ts": pd.to_datetime(["2025-08-30T12:00:00Z", "2025-08-31T00:00:00Z"])}
                ),
            ),
        ]
    except Exception:
        pass
    # pydantic (v1/v2 compatible imports)
    try:
        from pydantic import BaseModel, Field

        class UserModel(BaseModel):
            id: int
            name: str = "Alice"
            tags: list[str] = Field(default_factory=lambda: ["x"])

        shared = ["tag", {"k": [1, 2]}]
        model = UserModel(id=1, name="Bob", tags=shared)
        out += [Case("thirdparty:pydantic:basemodel_with_alias", {"model": model, "alias": shared})]
    except Exception:
        pass
    # attrs
    try:
        import attrs

        @attrs.define
        class A:
            x: int
            y: list[int]

        out += [Case("thirdparty:attrs:define_instance", A(1, [2, 3]))]
    except Exception:
        pass
    # msgspec
    try:
        import msgspec

        @msgspec.struct
        class S:
            x: int
            y: list[int]

        out += [Case("thirdparty:msgspec:struct_instance", S(1, [2, 3]))]
    except Exception:
        pass
    # Pillow
    try:
        from PIL import Image

        out += [
            Case("thirdparty:pillow:image_rgba_2x2", Image.new("RGBA", (2, 2), (255, 0, 0, 128)))
        ]
    except Exception:
        pass
    # torch
    try:
        import torch

        out += [Case("thirdparty:torch:tensor_long_2x3", torch.arange(6).reshape(2, 3))]
    except Exception:
        pass
    # sympy
    try:
        import sympy as sp

        x = sp.Symbol("x")
        out += [Case("thirdparty:sympy:expr_sin2_plus_cos2", sp.sin(x) ** 2 + sp.cos(x) ** 2)]
    except Exception:
        pass
    # networkx
    try:
        import networkx as nx

        g = nx.DiGraph()
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        out += [Case("thirdparty:networkx:digraph_2cycle", g)]
    except Exception:
        pass
    return tuple(out)


# ----------------------------- OBJECTS --------------------------------------

OBJECTS: tuple[Case, ...] = (
    # --- atom ---
    Case("atom:none", None),
    Case("atom:NoneType", type(None)),
    Case("atom:bool_true", True),
    Case("atom:bool_true", bool),
    Case("atom:int_big", 2**120),
    Case("atom:float_pi", 3.1415926535),
    Case("atom:complex_unit_imag", 1j),
    Case("atom:str_unicode", "hello\u1234"),
    Case("atom:bytes_small", b"bytes"),
    Case("atom:bytearray_small", bytearray(b"ba")),
    Case("atom:uuid4", uuid.uuid4()),
    Case("atom:ellipsis", ...),
    Case("atom:not_implemented", NotImplemented),
    # --- numeric ---
    Case("numeric:fraction_355_113", fractions.Fraction(355, 113)),
    Case("numeric:decimal_pi", decimal.Decimal("3.1415926535")),
    Case("numeric:array_i", array.array("i", [1, 2, 3, 4])),
    Case("numeric:float_edges", [0.0, -0.0, math.inf, -math.inf, math.nan]),
    Case("numeric:memoryview_bytes", memoryview(b"\x00\x01\xfe\xff")),
    # --- time ---
    Case("time:date_2025_08_30", dt.date(2025, 8, 30)),
    Case("time:time_12_34_56_789", dt.time(12, 34, 56, 789)),
    Case("time:datetime_naive", dt.datetime(2025, 8, 30, 12, 34, 56, 789)),
    Case("time:timedelta_3d7s", dt.timedelta(days=3, seconds=7)),
    # zoneinfo if available
    *(
        lambda: (
            Case(
                "time:datetime_tz_zoneinfo_utc",
                dt.datetime(2025, 8, 30, 12, 0, tzinfo=__import__("zoneinfo").ZoneInfo("UTC")),
            ),
        )
        if __import__("importlib").util.find_spec("zoneinfo")
        else ()
    )(),
    # --- path ---
    Case("path:relative", Path("some/relative/path.txt")),
    Case("path:absolute", Path("/tmp/example.bin")),
    # --- container (plain, immutable or no alias) ---
    Case("container:list_simple", [1, 2, 3, 43]),
    Case("container:tuple_simple", (1, 2, 3)),
    Case("container:dict_mixed_keys", {"a": True, 42: "answer", (1, 2): "tuple-key"}),
    Case("container:set_small", {3, 2, 1}),
    Case("container:frozenset_small", frozenset({1, 2, 3})),
    Case("container:slice_1_10_2", slice(1, 10, 2)),
    Case("container:range_5_50_5", range(5, 50, 5)),
    # --- alias (shared identity, no cycles) ---
    Case("alias:list_shared_pair", _alias_shared_list_pair()),
    Case("alias:mixed_shared_combo", _alias_mixed_combo()),
    Case(
        "alias:repeated_dataclass",
        (lambda inst: [inst, inst, {"again": inst}])(
            (lambda: dc.make_dataclass("D", [("x", int)])(7))()
        ),
    ),
    # --- reflexive (true cycles) ---
    Case("reflexive:self_list", _reflexive_self_list()),
    Case("reflexive:self_dict", _reflexive_self_dict()),
    Case("reflexive:mutual_lists", _reflexive_mutual_lists()),
    Case("reflexive:tuple_list", _reflexive_tuple_list()),
    Case("reflexive:dict_list_cross", _reflexive_dict_list_cross()),
    Case("reflexive:deep_shared_subgraph", _alias_deep_shared_with_cycle()),
    # --- func / code / descriptors ---
    Case("func:builtin_max", max),
    Case("func:code_object", (lambda: None).__code__),
    Case("func:plain_function", (lambda x, y=3: x + y)),  # top-level lambda literal
    Case("func:bound_method_attr", _bound_method_holder()),
    Case("func:property_descriptor", property()),
    # likely non-picklable but interesting to deepcopy
    Case("xfail:pickle:closure_function", _closure_func()),
    Case("xfail:pickle:mappingproxy", _mappingproxy()),
    # --- proto (copy/pickle protocols) ---
    Case("proto:__deepcopy__", ProtoDeepCopy([1, [2, 3]])),
    Case("proto:__getnewargs__", ProtoGetNewArgs([1, 2, 3])),
    Case("proto:__getnewargs_ex__", ProtoGetNewArgsEx(data={"k": [1, 2]})),
    Case("proto:__reduce__", ProtoReduce(a=[1, 2], b={"k": [3]})),
    Case("proto:getstate_setstate", ProtoGetStateSetState([42])),
    Case("proto:slots_class", SlotClass([1, 2], {"k": [3]})),
    # --- stdlib miscellany ---
    Case("stdlib:enum_animal_cat", Animal.CAT),
    Case("stdlib:namedtuple_point", Point(1, 2, {"k": [3, 4]})),
    Case("stdlib:typeddict_user", (lambda: {"id": 7, "name": "Alice"})()),
    Case("stdlib:dataclass_user", UserDC("alice", ["x", "y"], {"score": [1, 2, 3]})),
    Case("stdlib:dataclass_frozen_pair", FrozenPair(1, (2, 3, 4))),
    Case(
        "stdlib:regex_word_icase_multiline", re.compile(r"\w+", flags=re.IGNORECASE | re.MULTILINE)
    ),
    Case("stdlib:inspect_signature", inspect.signature(lambda a, b: (a, b))),
    Case("stdlib:traceback_exception", _make_traceback_exception()),
    Case("stdlib:types_simple_namespace", types.SimpleNamespace(a=[1, 2], b={"k": 3})),
    # --- large / perf ---
    Case("large:deep_graph_d6_leaf64", _large_deep_graph(35, 64)),
) + _thirdparty_cases()
