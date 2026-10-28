# Gateway execution runbook (COORDINATOR ONLY)

Mini-side execution for the 5-model gateway bake-off. Builders never
run this. Window approved: now (daytime, sequential, guarded).

## Order (two gates — pulls anytime, ladders need T6 live)

```
Gate 1 (now, needs nobody): pulls, ONE model at a time (mini_pull.py
  guards, or the guard checklist below for hand-pulls before it lands)
Gate 2 (needs builders): run_8q per model (filter, needs T8)
  → T6 deploy (telemetry live → mem floor works, needs T6)
  → run_ladder per SURVIVOR (measure, needs T8 + T6 live)
  → logprob screen per survivor (mml-stack script, --screen-cmd)
  → gate agreement vs labelled findings (hand step, kappa bar 0.7)
  → findings note back to the gateway user
```

Between models: `ollama stop <prev>` + `ollama ps` shows unloaded.
Never two weight servers / never parallel pulls.

## Abort guards (any trip stops the run)

- Free disk <15GB before a pull → stop, report.
- Free mem <1GB (via T6 /status) before a ladder step → stop, report.
- Any step timeout (120s probe / 600s ladder) → mark, continue to NEXT
  model, never retry more than once.
- Mid-pull network flake → `ollama rm` the partial tag, re-run once,
  then park the model with a note.

## Given/When/Then (acceptance scenarios)

1. Given the Mini idle, when mini_pull runs a PULLPACK line, then
   `ollama list` shows the tag at ±20% size and the 1-token probe passes.
2. Given a size mismatch, when the guard trips, then nothing else is
   pulled and the stderr reason names the expected vs actual GB.
3. Given an 8Q pass=false, when bakeoff continues, then that model
   skips the ladder and appears as filtered in findings.md.

## Rollback

- Pulls: `ollama rm <tag>` per model (instant, two-way).
- T6 deploy: git-revert + redeploy previous sidecar (pattern from the
  2026-10-28 deploy, backup kept on the Mini during the window).

## Embedding mini-probe (hand-run, not built)

nomic-embed-text:v1.5 (installed) vs bge-m3 (5th pull): latency +
dim table + one sanity pair (known-similar scores higher than
known-dissimilar). Record in the findings note.

## Findings note (deliverable back to gateway user)

Per model: 8Q pass/fail, ladder tok_s + mem, screen AUC/kappa where
run, keep/drop verdict. Plus: what was cut (SmolLM3? embeddings
scope?) and the measured numbers that replace yesterday's inferences.
