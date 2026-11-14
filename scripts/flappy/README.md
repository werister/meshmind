# Flappy end-to-end app benchmark

Each lab model writes a complete single-file HTML5 Flappy Bird from
`prompt.txt`; `grade.cjs` (headless Chromium via playwright) scores it
0–100 across boot, hooks, physics, and game behavior. `flappy_run.py`
generates serially (streaming, partials kept, resume-safe) and runs a
repair round with failure feedback for every model under 100.

## Setup

    cd scripts/flappy
    npm install
    npx playwright install chromium   # or set PLAYWRIGHT_BROWSERS_PATH

## Self-check (no lab needed)

    node grade.cjs ref-good.html   # expect score 90, all checks true
    node grade.cjs ref-bad.html    # expect score 10

`python3 ../../tests/test_flappy_grader.py` runs the same pair as unittest.

## Run (needs the lab)

    python3 flappy_run.py [--models sub1,sub2]   # substring filter

Games land in `games/`, grades in `flappy_transcript.jsonl`. One model at a
time; ~4 min/model for two rounds on the Mini. Assumes the lab base URL in
`BASE` (tailnet, keyless).

## Notes

- Single-process Chromium flags are required under sandboxed shells (the
  Mach rendezvous is denied); see the comment at the launch call.
- Motion is proven by rAF liveness + hook deltas, never pixels: compositor
  frames freeze in headless-shell mode (verified).
- Keep context ≤ 4k tokens total (prompt + `num_predict: 3500`).

## v3 (input-causal, current; 2026-11-14)

v1/v2 crowned decorative games (static birds, luck scoring). `grade3.cjs`
replaces appearance scoring with causality: control-vs-treatment flap test,
hands-off-vs-autopilot scoring arms, flight filter (scores count only from
lives where the bird flew), floor-death check, hard caps (no input response
→ max 35, nothing flown+scored → max 50).

    node grade3.cjs ref-good.html   # expect score 90, all checks true
    node grade3.cjs ref-bad.html    # expect score 10

- `prompt-v2.txt`: hardened physics rules (frame-based numbers, one-variable
  bird, score-once flags) after the v3 failure taxonomy.
- `prompt-v3gen.txt`: research-built scaffold contract (pin-down + section
  scaffold); used for the Qwen3-Coder-30B run (90, human-crowned best).
- `flappy_coli30b.py`: 30B colibri driver (OpenAI schema, patch-first
  repairs, ≤3 rounds). `flappy_retry1.py`: single-model retry driver.
- `gallery3.py`: regenerates the v1+v2+v3 results gallery
  (`FLAPPY_SRC` = transcripts dir, `FLAPPY_GALLERY_OUT` = output path).
- `probe-armA.cjs`: autopilot telemetry harness; caught the over-press
  regression (chained presses pin vy — see `[DBG-flap1]` in grade3.cjs).
- Calibration wrinkle: `visible` samples the first 600ms, so legit
  tap-to-start screens fail it. Both v3 90s fail only that gate.
  See docs/FLAPPY-V3-2026-11-14.md.
