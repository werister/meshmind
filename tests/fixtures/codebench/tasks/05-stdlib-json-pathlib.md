# task: stdlib-json-pathlib

type: stdlib

## prompt

Write a Python function `write_and_count(path, records)` that takes a filesystem
path (string or pathlib.Path) and a list of dictionaries. Serialize `records`
to that path as JSON using the standard library, then read the file back and
return the number of records it contains. Use `json` and `pathlib` from the
standard library. Return your answer as a single Python code fence.

## reference

```python
import json
from pathlib import Path


def write_and_count(path, records):
    p = Path(path)
    p.write_text(json.dumps(records), encoding="utf-8")
    loaded = json.loads(p.read_text(encoding="utf-8"))
    return len(loaded)
```

## asserts

```python
import tempfile
from pathlib import Path

_d = tempfile.mkdtemp()
_f = Path(_d) / "recs.json"
assert write_and_count(_f, [{"a": 1}, {"b": 2}, {"c": 3}]) == 3
assert write_and_count(str(_f), []) == 0
assert _f.exists()
import json as _json
assert _json.loads(_f.read_text(encoding="utf-8")) == []
assert write_and_count(_f, [{"x": [1, 2, 3]}]) == 1
```
