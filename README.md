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
- [ ] Find some quirky corner cases (there should be some)
- [ ] Make initial construction faster (could be 30-50 times faster than now)
- [ ] Support for memo in `__deepcopy__` and `__copy__` overrides

Project will be ready for release when `duper.deepdups(x)()` will behave the same as `copy.deepcopy()` and be as fast or faster than the latter. 

Currently `duper.deepdups(x)` part is on average 2-5 times slower than `copy.deepcopy()`, so it makes sense to use it only when you need to have a lot of copies of the same object.

If you have any feedback or ideas, you can [open an issue](https://github.com/Bobronium/duper/issues), or  reach out via [bobronium@gmail.com](mailto:bobronium@gmail.com) or [Telegram](https://t.me/Bobronium).

---

### Why?
It is challenging and fun, of course.

But if I'm being serious, deepcopy is [extremely slow](https://stackoverflow.com/questions/24756712/deepcopy-is-extremely-slow) and there's [no alternative](https://stackoverflow.com/questions/1410615/copy-deepcopy-vs-pickle) that is both faster **and** can replace deepcopy in all cases.


### How fast?
Generally 20-50 times faster than copy.deepcopy() on nested objects.
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
#### What's wrong with `copy.deepcopy()`
Well, it's slow. Extremely and unnecessarily slow, in fact. This has been noted by many, but no equally powerful alternatives were suggested.

#### Why not just rewrite it in C or Rust?
`deepcopy()` needs to examine an arbitrary Python object each time the copy is needed.
I figured: this must be quite wasteful regardless of whether the code that executes this algorithm is compiled or not, since interacting with Python objects inevitably invokes slow Python interpreter. 

When I already had a PoC, I discovered [gh-72793: C implementation of parts of copy.deepcopy](https://github.com/python/cpython/pull/91610), which further proved my assumptions. 

#### How duper is so fast without even being compiled?
Instead of interacting with slow Python objects, it compiles an instruction that reproduces that object to the simplest set of bytecode.
There's still an interpreter overhead when reconstructing the object, but now it already knows the exact actions that are needed and just executes them.
Funnily enough, I learned that this approach has a lot of in common with how `pickle` and `marshal` work. 

#### How is it different from `pickle` or `marshal`?
They both designed with `serialization` in mind, so they need to dump objects to `bytes` that can be stored on disk, and then used to reconstruct the object, even in different python process.
This creates a lot of constraints on the data that they can serialize as well as on the speed of reconstruction.

`duper`, however, isn't constrained by any of these problems. It only needs to guarantee that the object can be recreated within the same python process, and can use that to its advantage.


#### Are there any drawbacks of that approach?
Perhaps, the only drawback is that it non-trivial to implement.
When it comes to using it, I can't see any fundamental drawbacks, only advantages, really. 

However, there are drawbacks of current *implementation*. The approach itself boils down to getting a set of minimal instructions that will produce needed object. But there are different ways to obtain that set of instructions. The fastest way would be to compile instructions on the fly, while deconstructing the object. However, for sake of simplicity, I used a slower approach of building an AST that compiles to desirable bytecode. Removing this intermediate step should increase performance of initial construction by 20-50 times.

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
