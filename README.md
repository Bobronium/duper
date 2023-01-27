# duper

Library for building fast and reusable copying factories for python objects.

Aims to fill the gaps in performance and obscurity between copy, pickle, json and other serialization libraries, becoming the go-to library for copying objects within the same Python process.

![timesup_duper_demo](https://user-images.githubusercontent.com/36469655/215218569-1f833d77-d974-49ab-98cf-a03d9ab32899.gif)


### 🚧 Project is in development
There's no source code available yet.

If you have any feedback or ideas, you can [open the issue](https://github.com/Bobronium/duper/issues), or  contact me directly via [bobronium@gmail.com](mailto:bobronium@gmail.com) or [Telegram](https://t.me/Bobronium).

---

### Why?
It is challenging and fun, of course.

But if I'm being serious, deepcopy is [extremely slow](https://stackoverflow.com/questions/24756712/deepcopy-is-extremely-slow) and there's [no alternative](https://stackoverflow.com/questions/1410615/copy-deepcopy-vs-pickle) that is both faster **and** can replace deepcopy in all cases.



### Keypoints
- Generates a cook-book to reconstruct given object
- Upon subsequent calls, follows optimized instructions to produce new object
- Much faster handling of immutable types and flat collections.


### How fast?
Generally 20-50 times faster than copy.deepcopy() on nested objects.
```py
import duper
import copy
from timesup import timesup


@timesup(number=100000, repeats=3)
def reconstruction():
    x = {"a": 1, "b": [(1, 2, 3), (4, 5, 6)], "c": []}

    copy.deepcopy(x)      # ~0.00605 ms (deepcopy)
    dup = duper.Duper(x)  # ~0.00009 ms (duper_init):
    dup.deep()            # ~0.00014 ms (duper_dup): 42.22 times faster than deepcopy
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
    default_factory = duper.Duper(default, prepare=True).deep
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

### 🚧 Status
Though the library is in an early development stage, it already outperforms all other solutions I've found when copying objects. 

I am completing the implementation and exploring new and validating existing ideas to improve performance. 

My current priority is to speed up the initial build of the copying factory. It is currently slightly slower than deepcopy in most cases.
