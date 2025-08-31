# SPDX-FileCopyrightText: 2023-present Arseny Boykov (Bobronium) <mail@bobronium.me>
#
# SPDX-License-Identifier: MPL-2.0

import copy
from decimal import Decimal

import duper
import duper.builders.ast
from timesup import timesup


@timesup(number=1000, profile=not duper.COMPILED, repeats=1)
def reconstruction() -> None:
    x = {"a": 1, "b": [(1, 2, 3), (4, 5, 6)], "c": [object(), Decimal("3.14"), {()}]}  # i

    copy.deepcopy(x)  # t deepcopy
    duper.deepcopy(x)  # t duper_deepcopy deepcopy

    [copy.deepcopy(x) for _ in range(10)]  # t deepcopy_10
    [copy.deepcopy(x) for _ in range(100)]  # t deepcopy_100
    [copy.deepcopy(x) for _ in range(1000)]  # t deepcopy_1000

    duper.replicate(x, 10)  # t replicate_10 deepcopy_10
    duper.replicate(x, 100)  # t replicate_100 deepcopy_100
    duper.replicate(x, 1000)  # t replicate_1000 deepcopy_1000

    replicate_x = duper.reconstructs(x)  # # t build_reconstructor deepcopy
    replicate_x()  # t duper_deepcopies deepcopy
