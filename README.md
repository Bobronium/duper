# duper

20-50x faster than `copy.deepcopy()` on mutable objects.

Aims to fill the gaps in performance and obscurity between copy, pickle, json and other serialization libraries, becoming the go-to library for copying objects within the same Python process.


[Skip to FAQ](#faq)... 

### 🚧 Project is in development
Current priorities
- [x] Support for immutable types
- [x] Support for builtin types
- [x] Support for arbitrary types
- [x] Partial support for `__deepcopy__` and `__copy__` overrides (memo is not respected)
- [ ] Support for recursive structures
- [ ] Find quirky corner cases
- [ ] Make initial construction faster (potentially 30-50 times faster than current implementation)
- [ ] Support memo in `__deepcopy__` and `__copy__` overrides

The project will be ready for release when `duper.deepdups(x)()` behaves the same as `copy.deepcopy()` and is at least as fast, if not faster. 

Currently, `duper.deepdups(x)` is on average 2-5 times slower than `copy.deepcopy()`, so it's recommended to use it only when you need many copies of the same object.

If you have any feedback or ideas, please [open an issue on GitHub](https://github.com/Bobronium/duper/issues) or reach out via [bobronium@gmail.com](mailto:bobronium@gmail.com) or [Telegram](https://t.me/Bobronium).

---

### Showcase
```py
import duper
import copy
from timesup import timesup


@timesup(number=100000, repeats=3)
def reconstruction():
    x = {"a": 1, "b": [(1, 2, 3), (4, 5, 6)], "c": [object(), object(), object()]}  # i

    copy.deepcopy(x)         # ~0.00576 ms (deepcopy)
    dup = duper.deepdups(x)  # ~0.03131 ms (duper_build)
    dup()                    # ~0.00013 ms (duper_dup): 45.18 times faster than deepcopy
```

### Real use case
#### Pydantic
<details>
<summary>Models definition</summary>

```py
from datetime import datetime
from functools import wraps

import duper
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo


class User(BaseModel):
    id: int
    name: str = "John Doe"
    signup_ts: datetime | None = None
    friends: list[int] = []
    skills: dict[str, int] = {
        "foo": {"count": 4, "size": None},
        "bars": [
            {"apple": "x1", "banana": "y"},
            {"apple": "x2", "banana": "y"},
        ],
    }



@wraps(Field)
def FastField(default, *args, **kwargs):
    """
    Overrides the fields that need to be copied to have default_factories
    """    
    default_factory = duper.deepdups(default)
    field_info: FieldInfo = Field(*args, default_factory=default_factory, **kwargs)
    return field_info


class FastUser(BaseModel):
    id: int
    name: str = FastField("John Doe")
    signup_ts: datetime | None = FastField(None)
    friends: list[int] = FastField([])
    skills: dict[str, int] = FastField(
        {
            "foo": {"count": 4, "size": None},
            "bars": [
                {"apple": "x1", "banana": "y"},
                {"apple": "x2", "banana": "y"},
            ],
        }
    )
```

</details>

```py
@timesup(number=100000, repeats=3)
def pydantic_defaults():
    User(id=42)        # ~0.00935 ms (with_deepcopy)
    FastUser(id=1337)  # ~0.00292 ms (with_duper): 3.20 times faster than with_deepcopy

```

### FAQ
#### What's wrong with `copy.deepcopy()`?
Well, it's slow. [Extremely slow](https://stackoverflow.com/questions/24756712/deepcopy-is-extremely-slow), in fact. This has been noted by many, but [no equally powerful alternatives](https://stackoverflow.com/questions/1410615/copy-deepcopy-vs-pickle) were suggested.

#### Why not just rewrite it in C or Rust?
`deepcopy()` needs to examine an arbitrary Python object each time the copy is needed. I figured that this must be quite wasteful, regardless of whether the code that executes this algorithm is compiled or not, since interacting with Python objects inevitably invokes the slow Python interpreter.

When I had a proof of concept, I discovered [gh-72793: C implementation of parts of copy.deepcopy](https://github.com/python/cpython/pull/91610), which further confirmed my assumptions.

#### How is `duper` so fast without even being compiled?
Instead of interacting with slow Python objects for each copy, it compiles concrete instructions to reproduces the object. There is still an interpreter overhead when reconstructing the object, but now it already knows the exact actions that are needed and just executes them.
Interestingly, I learned that this approach has a lot in common with how `pickle` and `marshal` work.

#### How is it different from `pickle` or `marshal`?
Both are designed for `serialization`, so they need to dump objects to `bytes` that can be stored on disk and then used to reconstruct the object, even in a different Python process.
This creates many constraints on the data they can serialize, as well as the speed of reconstruction.

`duper`, however, is not constrained by these problems. It only needs to guarantee that the object can be recreated within the same Python process, and it can use that to its advantage.

#### Are there any drawbacks to this approach?
Perhaps the only drawback is that it's non-trivial to implement.
When it comes to using it, I can't see any fundamental drawbacks, only advantages.

However, there are drawbacks to the current implementation. The approach itself boils down to getting a set of minimal instructions that will produce the needed object. But there are different ways to obtain this set of instructions. The fastest way would be to compile the instructions on the fly while deconstructing the object. However, for the sake of simplicity, I used a slower approach of building an AST that compiles to the desired bytecode. Removing this intermediate step should increase the performance of the initial construction by 20-50 times.

#### Is this a drop-in replacement for `deepcopy`?
Not quite yet, but it aims to be. 

#### How should I use it?
`duper` shines when you need to make multiple copies of the same object.

Here's an example where duper can help the most:
```python
import copy
data = {"a": 1, "b": [[1, 2, 3], [4, 5, 6]]}
copies = [copy.deepcopy(data) for _ in range(10000)]
```
By pre-compiling instructions in a separate one-time step, we eliminate all of the overhead from the copying phase: 
```python
import duper
data = {"a": 1, "b": [[1, 2, 3], [4, 5, 6]]}
reconstruct_data = duper.deepdups(data)
copies = [reconstruct_data() for _ in range(10000)]
```

#### Is it production ready?
[Hell no!](#-project-is-in-development)
