# task: refactor

type: refactor

## prompt

The function below works but is repetitive and hard to read. Refactor it into
cleaner code while keeping its exact behavior. It classifies an integer score
into a letter grade. Keep the function name `grade` and its input/output
behavior identical. Return the refactored function as a single Python code
fence.

```python
def grade(score):
    if score >= 90:
        result = "A"
        return result
    else:
        if score >= 80:
            result = "B"
            return result
        else:
            if score >= 70:
                result = "C"
                return result
            else:
                if score >= 60:
                    result = "D"
                    return result
                else:
                    result = "F"
                    return result
```

## reference

```python
def grade(score):
    thresholds = ((90, "A"), (80, "B"), (70, "C"), (60, "D"))
    for cutoff, letter in thresholds:
        if score >= cutoff:
            return letter
    return "F"
```

## asserts

```python
assert grade(95) == "A"
assert grade(90) == "A"
assert grade(89) == "B"
assert grade(80) == "B"
assert grade(75) == "C"
assert grade(60) == "D"
assert grade(59) == "F"
assert grade(0) == "F"
assert grade(100) == "A"
```
