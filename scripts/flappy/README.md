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
