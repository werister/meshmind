# task: dedup

type: pure-function

## prompt

Write a Python function `dedup(items)` that returns a new list with duplicates
removed while preserving the order of first appearance. The input may contain
any hashable values. Do not use any imports. Return your answer as a single
Python code fence.

## reference

```python
def dedup(items):
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
```

## asserts

```python
assert dedup([1, 1, 2, 3, 3, 3, 1]) == [1, 2, 3]
assert dedup([]) == []
assert dedup(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]
assert dedup([1, 2, 3]) == [1, 2, 3]
assert dedup([True, 1, False, 0]) == [True, False]
assert dedup([3, 2, 1, 2, 3]) == [3, 2, 1]
```
