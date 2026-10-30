# task: anagrams

type: pure-function

## prompt

Write a Python function `is_anagram(a, b)` that returns True if strings `a` and
`b` are anagrams of each other, ignoring spaces and letter case, and False
otherwise. Only alphabetic characters and spaces appear in the input. Do not
use any imports. Return your answer as a single Python code fence.

## reference

```python
def is_anagram(a, b):
    def norm(s):
        return sorted(c.lower() for c in s if c != " ")
    return norm(a) == norm(b)
```

## asserts

```python
assert is_anagram("listen", "silent") is True
assert is_anagram("Dormitory", "Dirty Room") is True
assert is_anagram("hello", "world") is False
assert is_anagram("", "") is True
assert is_anagram("a", "A") is True
assert is_anagram("abc", "abcd") is False
assert is_anagram("The Eyes", "They See") is True
```
