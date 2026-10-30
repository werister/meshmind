# T11 — coder executables bench (BUILD; coordinator runs live)

## Problem
"SmolLM3 is the coder pick" / "Granite 4.2 obsoletes qwen-coder" are
unverified adjectives. Promotion needs passing executable tests, not
plausible explanations.

## Goal
`scripts/code_bench.py` + `tests/fixtures/codebench/tasks/*.md`:
10 Python tasks, each a prompt + HIDDEN pytest-style asserts the model
never sees. Runner prompts each model via the proxy
(X-Agent: code_bench), extracts the first code fence, executes asserts
in a subprocess (timeout 30s), records pass/fail + tokens. Output
`findings.json` (per model per task) + console table.

Task mix (fixed): 4 pure functions (median, dedup, anagrams, brackets),
2 stdlib use (json+pathlib, datetime), 2 bugfix (given buggy code, fix
it), 1 edge-case trap (empty/None/unicode), 1 tiny refactor (given
smelly code, clean + keep behavior).

## Non-goals
- No live runs by the builder (fixtures only; coordinator runs
  granite4.2 vs qwen2.5-coder:3b vs smollm3 on the Mini).
- No multi-file/repo tasks (single-function scope only).
- No network in task tests (stdlib + asserts only).

## Behavior
Per contracts-style conventions: JSON to stdout, reasons to stderr,
exit 0 = ran, exit 2 = infra error. `--models`, `--tasks DIR`,
`--ollama` (default localhost:11434; coordinator passes :8081),
`--timeout` per task. A model that emits no fence fails the task
(marked, not fatal). Timeouts fail the task.

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| No code fence in reply | task fail, run continues | test_no_fence |
| Assert subprocess timeout | task fail + note | test_task_timeout |
| Host down | exit 2, stderr reason | test_host_down |
| Task dir missing/malformed | exit 2 naming the file | test_bad_tasks |

## Tests (named, stdlib only)
`tests/test_code_bench.py` (+ fixtures incl. 2 sample tasks and canned
model replies: one passing, one failing, one fenceless). No live calls.

## Ticket fields
- Door: two-way (new files only). Blast radius: small.
- Acceptance: `python3 tests/test_code_bench.py` → exit 0 with PASS
  counts, AND all 10 task files validate (self-test: reference
  solutions pass their own asserts — builder ships one).
- May touch: `scripts/code_bench.py`, `tests/test_code_bench.py`,
  `tests/fixtures/codebench/*`.
- Must not: everything else, anything on the Mini.
- Author: kiro crew H (with T12, sequentially). Reviewer: coordinator.
- Cost: $0. Disk note: MacBook tight — targeted tests, no installs.
