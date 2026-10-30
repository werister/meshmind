# task: brackets

type: pure-function

## prompt

Write a Python function `balanced(s)` that returns True if every opening
bracket in `s` has a matching closing bracket of the same kind in the correct
order, and False otherwise. Handle three bracket kinds: `()`, `[]`, and `{}`.
Non-bracket characters are ignored. Do not use any imports. Return your answer
as a single Python code fence.

## reference

```python
def balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = set(pairs.values())
    stack = []
    for ch in s:
        if ch in opens:
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
```

## asserts

```python
assert balanced("()") is True
assert balanced("([{}])") is True
assert balanced("(]") is False
assert balanced("(()") is False
assert balanced("") is True
assert balanced("a(b)c[d]{e}") is True
assert balanced("{[}]") is False
assert balanced(")(") is False
```
