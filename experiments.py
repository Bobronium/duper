import ast
import json
import timeit
from pathlib import Path
import copy
from typing import (
    Any,
)

# import astpretty

from duper import deepdups, dups

import pyinstrument

from duper.factories.ast import reconstruct_expression, Namespace


# from duper.compiled import get_factory
# from duper.factory import duper


# python_partial = partial(passthrough, 1)
# assert python_partial() == native_partial()


def t(expr, bake="pass", number=10):
    print(expr)
    r = timeit.timeit(expr, bake, number=number)
    return r


# t(get_factory(1))


def bench():
    k = []
    print(timeit.timeit(lambda: k))
    # print(timeit.timeit(duper(k)))
    runs = 10000

    def tm(name, c, v):
        print(
            name,
            timeit.timeit(
                c,
                number=runs,
                globals={
                    **globals(),
                    "copy": copy.deepcopy,
                    "deepcopy": copy.deepcopy,
                    "v": v,
                },
            ),
            c,
        )

    immutable = ["", "Not empty", 0, 1, 0.0, 0.1, True, False, object, object(), ...]
    empty = [[], (), {}, set(), (), frozenset()]
    flat = [[1, 2, 3], (1, 2, 3), {"key": "value"}, {1, 2, 3}, frozenset((1, 2, 3))]
    nested = [[[]], {"key": {}}]

    for v in flat:
        print("vz")
        tm(f"copy.deepcopy({v!r}))()", "deepcopy(v)", v)
        tm(f"copy.copy({v!r})", "copy(v)", v)
        tm(f"(lambda: {v!r})()", lambda: v, v)
        tm(f"copier({v!r})", dups(v), v)
        tm(f"deepcopier({v!r})", deepdups(v), v)
        tm(f"copier_factory()", "copier(v)", v)
        tm("deepcopier_factory", "deepcopier(v)", v)
        print("")
        # try:
        #     print(dis.dis(duper(v)))
        #     print(dis.dis(lambda: lambda: v))
        # except TypeError:
        #     pass

        # with pyinstrument.Profiler() as p:
        #     duper(v)
        # p.print(color=True, show_all=True)
        # tm("deepcopy_factory_dynamic", "deepcopy_factory(v)", v)

        # if orig is not None:
        #     tm(
        #         f"{orig.__name__}()" if isinstance(orig, type) else f"{repr(v)}.copy()",
        #         orig,
        #     )


def bench(item: dict[str, Any]):
    r = repr(item)
    if len(r) > 100:
        r = r[0:50] + "<...>" + r[-50:]
    print(f"Benchmarking for {r}")

    for name, dup in (
        (f"{deepdups}({r})", deepdups),
        # (f"{factory.duper}({r})", factory.duper),
    ):
        print(f"-" * 100)
        print(f"RUNNING {name}")
        print(dup)
        ...
        with pyinstrument.Profiler(interval=0.0001) as deepcopy_:
            t(lambda: json.loads(json.dumps(item)))

        with pyinstrument.Profiler(interval=0.0001) as deepcopy_:
            copy.deepcopy(item)

        with pyinstrument.Profiler(interval=0.0001) as creation:
            f = dup(item)

        creation.print(color=True, show_all=True)

        with pyinstrument.Profiler(interval=0.0001) as first_run:
            f()

        # assert deepcopied == r
        # assert r is not item
        first_run.print(color=True)

        with pyinstrument.Profiler(interval=0.0001) as subsequent_runs:
            f()
        # subsequent_runs.print()
        print(f"DUPER: {dup.__module__}, FACTORY: {f}")

        # assert deepcopied == r
        creation = creation.last_session.duration
        first_run = first_run.last_session.duration
        subsequent_runs = subsequent_runs.last_session.duration
        deepcopy_ = deepcopy_.last_session.duration
        # second_run = second_run.last_session.duration

        overhead = (creation + first_run) / deepcopy_
        increase = deepcopy_ / subsequent_runs

        makes_sens_after = (creation + first_run) / (deepcopy_ - subsequent_runs)

        # makes_sens_after = int(increase // overhead) - 1
        and_moar = 1000
        after_moar = (creation + first_run) + subsequent_runs * (and_moar - 1)
        print(
            f"copy_obj = duper.deepcopier(obj)  #  takes {creation:.5F}s to compile\n"
            f"copied = factory()                #  takes {subsequent_runs=:.5F} to make a copy)",
            f"copier = copy.deepcopy(obj)       #  takes {deepcopy_:.5F}s to make a copy",
            f"{overhead:.2F} time slower than deepcopy on the first run: {creation=:.5F}, {first_run=:.5F}",
            f"{increase:.2F} times faster than deepcopy on subsequent runs: {subsequent_runs=:.5F}",
            f"Will become faster than deepcopy after {makes_sens_after} copies made",
            f"Deepcopy after {and_moar} runs: {deepcopy_* and_moar}",
            f"deepcopy_factory after {and_moar} runs: {after_moar}",
            sep="\n",
        )
        print("$$$$$$$$$")
        print()


d = json.loads(Path("/Users/bobronium/dev/py/pythings/requests/history-human.json").read_text())
# print(ast.unparse(reconstruct_expression(d, Namespace())))

a = []
a.append(a)
a.append(a)
a.append(a)
if __name__ == "__main__":
    bench(d)


def function(a, b):
    return [(KEY := "VALUE"), KEY]


a = []
# print(ast_factory([a, a]))


class C:
    ...


c = C()
c.foo = c

# t("d[1] = 2", "d={}")
# t("d.__setitem__(1, 2)", "d={}")

# function(1, 2)
# astpretty.pprint(ast.parse(inspect.getsource(produce_C)).body[0].body[0].value)
# print(dis.dis(function))
#
