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

## v3 follow-up (2026-11-14, Flappy lane)

v1/v2 crowned decorative games (owner play-test: "don't even take
keystrokes"). `grade3.cjs` is input-causal (control-treatment flap,
two-arm scoring, flight filter, floor check, hard caps); full 76-file
regrade in `results/2026-11-14/flappy_v3.jsonl`, findings in
`docs/FLAPPY-V3-2026-11-14.md`, gallery `games/gallery-v3.html`.
Machine best: gemma4 R1 + Qwen3-Coder-30B R1 (90 each); human crown:
coli30b R1. Both 90s fail only `visible` (start-screen wrinkle — see
issues). Repair rounds can HURT (90→35); T3 snippet scores don't predict
app builds. Prompts: `prompt-v2.txt`, `prompt-v3gen.txt`; 30B driver:
`flappy_coli30b.py` (transcript R1-only until repairs land).
