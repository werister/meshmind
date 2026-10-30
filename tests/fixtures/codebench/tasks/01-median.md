# task: median

type: pure-function

## prompt

Write a Python function `median(nums)` that returns the median of a non-empty
list of numbers. For an odd-length list return the middle value; for an
even-length list return the arithmetic mean of the two middle values (as a
float). Do not use any imports. Return your answer as a single Python code
fence.

## reference

```python
def median(nums):
    ordered = sorted(nums)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
```

## asserts

```python
assert median([1]) == 1
assert median([3, 1, 2]) == 2
assert median([1, 2, 3, 4]) == 2.5
assert median([7, 7, 7]) == 7
assert median([-5, -1, -3]) == -3
assert median([2, 4]) == 3.0
assert isinstance(median([2, 4]), float)
# skewed set: median (2) differs from the mean (~34.3), so a mean-returning
# impostor cannot pass by coincidence.
assert median([1, 2, 100]) == 2
assert median([0, 0, 0, 1000]) == 0.0
```
