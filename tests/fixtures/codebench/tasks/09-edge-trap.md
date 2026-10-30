# task: edge-trap

type: edge-case

## prompt

Write a Python function `clean_names(names)` that normalizes a list of raw name
strings. Edge cases matter:

- The input list may be empty or `None`; in both cases return an empty list.
- Skip any element that is `None` or that is empty / whitespace-only after
  stripping.
- For the rest, strip leading/trailing whitespace and collapse internal runs of
  whitespace to a single space.
- Preserve non-ASCII letters exactly (e.g. accented or CJK characters must not
  be dropped or mangled).
- Preserve input order.

Do not use any imports. Return your answer as a single Python code fence.

## reference

```python
def clean_names(names):
    if not names:
        return []
    out = []
    for name in names:
        if name is None:
            continue
        collapsed = " ".join(name.split())
        if collapsed:
            out.append(collapsed)
    return out
```

## asserts

```python
assert clean_names(None) == []
assert clean_names([]) == []
assert clean_names(["  Ada  Lovelace "]) == ["Ada Lovelace"]
assert clean_names(["", "   ", None, "x"]) == ["x"]
assert clean_names(["José  Núñez"]) == ["José Núñez"]
assert clean_names(["北京  市"]) == ["北京 市"]
assert clean_names(["a\tb\nc"]) == ["a b c"]
assert clean_names(["one", "two"]) == ["one", "two"]
```
