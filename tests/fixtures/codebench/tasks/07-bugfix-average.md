# task: bugfix-average

type: bugfix

## prompt

The following function is supposed to return the average of a list of numbers,
returning 0 for an empty list. It has a bug. Fix it so it returns the correct
average and does not crash on an empty list. Keep the function name `average`.
Return the corrected function as a single Python code fence.

```python
def average(nums):
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

## reference

```python
def average(nums):
    if not nums:
        return 0
    total = 0
    for n in nums:
        total += n
    return total / len(nums)
```

## asserts

```python
assert average([2, 4, 6]) == 4
assert average([]) == 0
assert average([5]) == 5
assert average([1, 2]) == 1.5
assert average([-2, 2]) == 0
```
