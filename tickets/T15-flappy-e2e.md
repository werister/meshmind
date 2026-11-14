# T15 — Flappy end-to-end app bench (BUILD; results land follow-up)

## Problem
Micro-benches (26-case, 100-bank) rank code-writing, not app-building. No
published full-app-build comparison across local SLMs exists (see
docs/RESEARCH-specialist-stacks-2026-11-14.md Part G.5).

## Goal
`scripts/flappy/`: each model writes a complete single-file HTML5 Flappy Bird
from one fixed prompt; a headless grader (playwright, single-process flags
for sandboxed shells) scores L0 static 10 / L1 boot 20 / L2 hooks 15 /
L3 physics 25 / L4 game 30. Round 2 repairs with failure feedback for every
model under 100. Runner is serial, streaming (partials kept), resume-safe.

## Non-goals
- No pixel assertions (compositor frames freeze in headless-shell; motion is
  proven by rAF liveness + hook deltas instead).
- No multi-file apps (single-file scope only).
- No live runs by the builder (ref-good/ref-bad fixtures only; coordinator
  runs the 38-model sweep on the Mini).

## Behavior
`node grade.cjs <file>` prints one JSON line `{checks, score, ms, notes}`.
`python3 flappy_run.py [--models sub,...]` appends JSONL rows
`{model, round, total, grade}` to `flappy_transcript.jsonl`, games to
`games/`. Reference: ref-good scores 90, ref-bad scores 10.

## Follow-up (this ticket stays open)
Land `results/2026-11-14/flappy.jsonl` + `docs/FLAPPY-2026-11-14.md` when the
38-model run completes; analyze repair-round deltas (coachability axis).
