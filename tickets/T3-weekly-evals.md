# T3 — Weekly eval harness

**Assignee:** Sonnet (kiro CLI). **Needs:** SPEC.md, context-probe.py.
**No Mini SSH** — build against local Ollama only.

## Goal

A small weekly smoke eval (not the full sweep): 3 fast models × 3
fixed prompts, pass/fail + tok/s, results appended to JSONL, surfaced
in `/status`.

## Scope

- `eval-weekly.py`: fixed prompt set, per-model timeout, unload between
  models, memory guard (skip when pressured), JSONL output.
- LaunchAgent plist template (weekly cadence) + README runbook section.
- Sidecar `/status` reads the latest eval summary (read-only tail).

## Pass/fail

- Full run finishes locally in under 10 minutes on CPU-sized models.
- A deliberately failing prompt (nonsense model name) yields FAIL, not a crash.
- Memory guard path tested by forcing a low threshold.

## Guardrails

Own worktree only, merge nothing, stdlib-only, tiny writes.
Coordinator reviews and installs the LaunchAgent on the Mini.
