# task: stdlib-datetime

type: stdlib

## prompt

Write a Python function `business_days(start_iso, end_iso)` that takes two dates
as ISO strings (`"YYYY-MM-DD"`) and returns the number of weekdays
(Monday–Friday) in the inclusive range from `start_iso` to `end_iso`. If the end
date is before the start date, return 0. Use the `datetime` module from the
standard library. Return your answer as a single Python code fence.

## reference

```python
from datetime import date, timedelta


def business_days(start_iso, end_iso):
    start = date.fromisoformat(start_iso)
    end = date.fromisoformat(end_iso)
    if end < start:
        return 0
    count = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count
```

## asserts

```python
# 2026-10-26 is a Monday; 2026-10-30 is the Friday of that week.
assert business_days("2026-10-26", "2026-10-30") == 5
# full week incl. weekend -> still 5 weekdays
assert business_days("2026-10-26", "2026-11-01") == 5
# single weekday
assert business_days("2026-10-28", "2026-10-28") == 1
# single weekend day -> 0
assert business_days("2026-10-31", "2026-10-31") == 0
# reversed range -> 0
assert business_days("2026-10-30", "2026-10-26") == 0
```
