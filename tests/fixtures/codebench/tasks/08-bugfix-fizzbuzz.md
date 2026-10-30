# task: bugfix-fizzbuzz

type: bugfix

## prompt

The following function should return the FizzBuzz string for a positive integer
`n`: `"Fizz"` if divisible by 3, `"Buzz"` if divisible by 5, `"FizzBuzz"` if
divisible by both, otherwise the number as a string. It has a bug in its
ordering that makes it never return `"FizzBuzz"`. Fix it. Keep the function name
`fizzbuzz`. Return the corrected function as a single Python code fence.

```python
def fizzbuzz(n):
    if n % 3 == 0:
        return "Fizz"
    elif n % 5 == 0:
        return "Buzz"
    elif n % 15 == 0:
        return "FizzBuzz"
    else:
        return str(n)
```

## reference

```python
def fizzbuzz(n):
    if n % 15 == 0:
        return "FizzBuzz"
    elif n % 3 == 0:
        return "Fizz"
    elif n % 5 == 0:
        return "Buzz"
    else:
        return str(n)
```

## asserts

```python
assert fizzbuzz(1) == "1"
assert fizzbuzz(3) == "Fizz"
assert fizzbuzz(5) == "Buzz"
assert fizzbuzz(15) == "FizzBuzz"
assert fizzbuzz(30) == "FizzBuzz"
assert fizzbuzz(9) == "Fizz"
assert fizzbuzz(10) == "Buzz"
assert fizzbuzz(7) == "7"
```
