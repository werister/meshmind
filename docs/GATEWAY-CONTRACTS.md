# Gateway protocol contracts v1.2 (FROZEN)

Frozen by the owner at plan-gate; amended at second-model review
(mem unit fix, --questions data flag, mixed-truth filter rule).
T8 implements the first two, T9 consumes all three. Changes need a
new version + owner sign-off — builders do not renegotiate
interfaces mid-build.

Conventions for all three: JSON object to stdout, human reasons to
stderr, exit 0 = ran (pass/fail lives inside the JSON), exit 2 =
infrastructure error (host down, missing file, guard trip).

## run_8q.py — yes/no filter

`python3 scripts/run_8q.py --model TAG [--ollama URL] [--fixture PATH] [--timeout S] [--questions PATH]`

- Default `--ollama http://127.0.0.1:11434`, default `--timeout 120`.
- `--fixture`: read canned answers from PATH, touch no network (tests).
- `--questions`: JSON list of 8 `{q, expect_yes}` objects. Ships with a
  PLACEHOLDER set clearly marked as such; the coordinator swaps in the
  reviewed set without rebuilding. bakeoff.py passes it through.
- stdout: `{"tool":"run_8q","model":TAG,"answers":[{"q":N,"answer":"yes|no|null","latency_s":F}×8],"pass":B,"notes":S}`
- `pass=false` when any answer is null, non-yes/no, or all 8 agree
  (always-yes / always-no filter). Valid ONLY with mixed ground truth:
  the question set MUST contain both yes- and no-answers (4/4 split),
  else "all agree" is ambiguous.

## run_ladder.py — headroom ladder

`python3 scripts/run_ladder.py --model TAG [--contexts 4096] [--parallel 1,2] [--ollama URL] [--status URL] [--fixture PATH] [--step-timeout S]`

- Defaults: contexts `4096`, parallel `1,2`, num_ctx 4096 on every step,
  `--status http://127.0.0.1:8081/status`, `--step-timeout 600`.
- stdout: `{"tool":"run_ladder","model":TAG,"num_ctx":4096,"steps":[{"ctx":I,"parallel":I,"prompt_tokens":I,"gen_tokens":I,"tok_s":F,"mem_kb":I|null,"ok":B,"notes":S}],"verdict":B}`
- `mem_kb` = `mem_free_mb` × 1024, read from `/status` (the T6 field)
  when reachable, else `null` + note. Never fabricated, never zero-filled.
- A failed step sets `ok:false`, `verdict:false`, the run continues.
- `--parallel 2` measures two concurrent clients against the DEPLOYED
  server config (queues if the server serializes — record the observed
  behavior, do not change server env).

## bakeoff.py — composition

`python3 scripts/bakeoff.py --models T1,T2 [--out DIR] [--ollama URL] [--status URL] [--screen-cmd TPL] [--questions PATH]`

- Runs run_8q → run_ladder → screen (optional) per model, in order.
  A failed model is marked and skipped forward, never fatal.
- `--screen-cmd`: shell template with `{model}` placeholder pointing at
  the mml-stack screen script. Absent/unrunnable → screen null + note.
- Writes `DIR/findings.json` (machine) + `DIR/findings.md` (human table).
- 8Q failures skip the ladder for that model (filter first, measure survivors).
- Zero survivors: exit 0, `findings.json` carries `"models":[]`, `findings.md`
  says "no survivors" (v1.1 micro-amendment, pre-build).

## mini_pull.py — guarded pull (coordinator runs on Mini)

`python3 scripts/mini_pull.py pull --spec SPEC --expect-gb F [--ollama URL]`

- Guards IN ORDER: free disk ≥15GB → `ollama pull/create` → size within
  ±20% of expect → 1-token probe → report JSON to stdout.
- Any guard trip: stderr reason, exit 2, no partial state hidden
  (a pulled-but-wrong-size model is reported, coordinator decides rm).
- `--spec` is one PULLPACK line spec: `tag:NAME` or `gguf:URL|FILE` (+ Modelfile notes in PULLPACK).
