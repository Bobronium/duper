import ast
import copy
import json
import marshal
import pickle
from functools import partial

import dill
import orjson

import duper
from duper.fastast import Call, Name, Expression
from duper.factories.ast import Namespace
from timesup import timesup


def get_loader(lib, x):
    dumped = None
    dumper, loader = getattr(lib, "dumps"), getattr(lib, "loads")

    def f():
        nonlocal dumped
        if dumped is None:
            dumped = dumper(x)
        return loader(dumped)

    return f


@timesup(number=100000, repeats=3)
def reconstruction():
    """
    Current performance results.

    While compiling is extremely slow, decompiling is still faster than anything
    """
    x = (1, 2, 3, (1, 2, 3))  # i

    copy.deepcopy(x)  # t deepcopy
    dup = duper.Duper(x)  # t duper_init deepcopy
    # marshal_dumped = marshal.dumps(x)  # t marshal_dumps duper_init
    # pickle_dumped = pickle.dumps(x)  # t pickle_dumps duper_init
    # dill_dumped = dill.dumps(x)  # t dill_dumps duper_init
    # json_dumped = json.dumps(x)  # t json_dumps duper_init
    # orjson_dumped = orjson.dumps(x)  # t orjson_dumps duper_init
    dup.deep()  # t duper deepcopy

    # [marshal.loads(marshal_dumped) for i in range(num)]  # t marshal duper
    # [pickle.loads(pickle_dumped) for i in range(num)]  # t pickle duper
    # [dill.loads(dill_dumped) for i in range(num)]  # t dill duper
    # [json.loads(json_dumped) for i in range(num)]  # t json duper
    # [orjson.loads(orjson_dumped) for i in range(num)]  # t orjson_loads duper


# print(copy.deepcopy(copy))
# duper.compile({}, {})
x = {"a": {"x": 2}}  # i

ns = {}
# code = marshal.dumps(x)
# print(code)
# b'\xfb\xda\x01a{\xda\x01x\xe9\x02\x00\x00\x0000'.rstrip(b'\x00')
# eval(code.replace(b'\x00', b""), ns)
# print(ns)

"""
Before args:

@timesup
def reconstruction():
    dup = duper.deepdups(x)              # ~0.02314 ms (duper_init)
    marshal_dumped = marshal.dumps(x)    # ~0.00044 ms (marshal_dumps): 52.06 times faster than duper_init
    pickle_dumped = pickle.dumps(x)      # ~0.00056 ms (pickle_dumps): 41.01 times faster than duper_init
    dill_dumped = dill.dumps(x)          # ~0.02746 ms (dill_dumps): 1.19 times slower than duper_init
    json_dumped = json.dumps(x)          # ~0.00196 ms (json_dumps): 11.79 times faster than duper_init
    orjson_dumped = orjson.dumps(x)      # ~0.00017 ms (orjson_dumps): 137.37 times faster than duper_init
    dup()                                # ~0.00013 ms (duper)
    copy.deepcopy(x)                     # ~0.00581 ms (deepcopy): 44.93 times slower than duper
    marshal.loads(marshal_dumped)        # ~0.00032 ms (marshal): 2.47 times slower than duper
    pickle.loads(pickle_dumped)          # ~0.00040 ms (pickle): 3.06 times slower than duper
    dill.loads(dill_dumped)              # ~0.00153 ms (dill): 11.85 times slower than duper
    json.loads(json_dumped)              # ~0.00152 ms (json): 11.76 times slower than duper
    orjson.loads(orjson_dumped)          # ~0.00028 ms (orjson_loads): 2.18 times slower than duper

"""
reconstruction()
#
# N = ast.Name(id="int", ctx=ast.Load(), lineno=1, col_offset=0)
# NA = Name(id="int")
# @timesup
# def reconstruction():
#     my = Expression(Call(NA, args=[], keywords=[]))
#     st = ast.Expression(ast.Call(N, args=[], keywords=[], lineno=1, col_offset=0))
#     compile(my, "", "eval")
#     compile(st, "", "eval")
