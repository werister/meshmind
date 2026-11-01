# Learning from our own behavior — eval tooling the lab could build (2026-11-01)

agent-reach pass on two questions: (1) more tools worth using, and (2) **evals that learn from
the system's own past behavior.** The key realization: the lab **already records the dataset** —
every call lands in `calls.log` (rotated JSONL) + the `CALLS_RING` (256-deep) + aggregates, with
per-call `{ts, path, status, agent, model, prompt_tokens, eval_tokens, ok, stream, partial,
truncated, duration_ms}`. We log behavior and never mine it. That's the gap. Proposals only.

## What's out there (prior art, agent-reach + web)

### Cluster A — eval FROM past traces / replay / regression (the "learn from behavior" idea)
- **clay-good/agent-replay** — "time-travel debugging for agents": **record every step → replay →
  `diff` two runs side-by-side** showing exactly where a prompt/model swap diverged. Three
  primitives: record, replay, diff. ([repo](https://github.com/clay-good/agent-replay))
  → Maps 1:1 onto the lab's recurring question *"it worked before — what changed after the model
  swap?"* (gemma2→gemma3, qwen3:4b→2507, artemis adoption). The lab already has the "record" half.
- **tracegym**, **flight-recorder**, **tracecase**, **agentpytest**, **trace-vault** — variations
  on capturing agent traces and turning them into regression fixtures / pytest cases.
  → The transferable idea: **promote real past calls into test cases** (a failing prod call
  becomes a fixture that must pass after a fix) — exactly what T12 did by hand for the fence bug.
- **Anthropic "Demystifying evals for AI agents"** — concept source: eval on *trajectories*, grade
  each interaction, escalate only anomalies (echoes the OpenAI-misalignment pattern already in
  SCOUT-ecosystem). ([anthropic](https://www.anthropic.com/research/demystifying-evals-for-ai-agents))

### Cluster B — lightweight local eval frameworks (if we ever want more than stdlib)
- **boscoh/microeval** — **Ollama-native**, `uvx microeval`, compare models & prompts, CLI + web
  UI, tracks results. The closest fit: local-first, tiny, no cloud key needed.
  ([repo](https://github.com/boscoh/microeval)) → Reference design for the lab's own eval surface;
  but it's a `uv`/web-UI tool — the lab's stdlib ethos favors *borrowing the shape*, not adopting.
- **DeepEval** (has an Ollama integration), **pytest-llm-evals / pytest-eval / gatecheck /
  llm-eval-harness** — pytest-plugin-style assertions over LLM output.
  → The transferable idea: **eval-as-pytest** (assertions the weekly run must pass), which the
  lab already partly does with its stdlib harnesses. gatecheck/pytest-eval are worth a glance for
  the *gating* pattern (fail CI if quality drops).

## What the lab should build from its OWN data (the real opportunity)

The lab doesn't need any of these installed — it needs their *ideas* applied to `calls.log`,
which is a growing behavioral record nobody mines. Ranked by value:

### 1. `calls.log` → regression corpus ("behavior replay") — highest value, pure stdlib
Harvest real past calls into a replayable fixture set:
- Each `calls.log` line already has the model, path, agent, status, tokens, duration — add (behind
  a flag, privacy-gated) the prompt+response for a sampled subset, or key off the existing
  metered calls.
- A `replay.py` (stdlib): take N past calls, re-issue the same prompt to the *same or a new*
  model, and **diff** the result (did the answer change? did tok/s regress? did it start
  stalling?). This is agent-replay's record→replay→diff, built on data we already have.
- **Directly answers the lab's recurring question** — "what changed after the model swap?" —
  without re-authoring fixtures each time. The T12 fence bug and the weekly-eval all-FAIL would
  both have been caught earlier by a diff against last week's run.

### 2. Behavioral drift signals on the existing dashboard (stdlib, ties to earlier scouts)
Mine the ring/aggregates for *self-learned* baselines rather than fixed thresholds:
- **Per-model rolling tok/s baseline + alert on regression** — e.g. gemma3:4b historically ~9.7
  tok/s; flag when a run drifts >25% (catches swap/thrash/KV-config regressions).
- **Per-model prompt/eval-length drift** — a shift in mean token lengths after a prompt/model
  change is the cheap "context rot / behavior changed" signal (from the observability scout).
- **Failure-rate-by-model trend** — `ok:false` ratio per model over time; a model silently
  degrading shows here before a human notices.
All computable from `CALLS_RING`/aggregates with stdlib `statistics` — no new deps.

### 3. Promote failures into fixtures automatically ("flight recorder")
When a call fails (`ok:false`, `truncated`, or a bad weekly-eval item), auto-capture it as a
candidate regression fixture (prompt + expected shape) the next run must handle. This is how the
tool-bench *should* grow — real failures become permanent tests. Gate it so the fixture set stays
curated (human-approved), not auto-bloated.

### 4. Weekly-eval upgrade (fixes a live finding + applies the above)
The DASHBOARD-CHECK found the weekly eval stale + all-FAIL (3/3 rubric, old model set). Rebuild it
to (a) report a **score/ratio** not binary PASS, (b) run the **current 18-model set**, (c) **diff
against the previous week** (behavior replay), and (d) draw its cases partly from promoted real
failures (#3). This turns the weekly eval from a static smoke test into a **self-learning
regression gate** — the whole point of your request.

## Honest scope notes
- All of this is **stdlib-buildable on-box** — the value is in mining `calls.log`, not installing
  microeval/DeepEval (those are references for *shape*). A judge step (the `/v1/systemone` shim
  from SCOUT-ecosystem, `gut`/`Kev` over Ollama) would make the "did the answer change meaningfully"
  diff smarter than string-compare — the two ideas compose.
- **Privacy:** replaying real prompts means storing them; today `calls.log` stores metadata +
  token counts, not bodies. Any behavior-replay must be opt-in per agent and body-gated (consistent
  with the fetch-endpoint "never log the body" rule).
- Every external tool's claims are hypotheses; here we're borrowing *designs*, not numbers.

## Ranked recommendation
1. **`replay.py` — record→replay→diff over `calls.log`** (agent-replay shape, stdlib). Answers
   "what changed after the swap?" using data we already keep. *Highest value.*
2. **Self-learned drift alerts on the dashboard** (rolling tok/s, length drift, failure-rate
   trend) — cheap stdlib additions, catch silent regressions.
3. **Auto-promote failures → curated fixtures** (flight-recorder pattern) — makes the test set
   grow from real behavior.
4. **Rebuild the weekly eval as a self-learning gate** (score not binary, current models,
   week-over-week diff, promoted failures) — fixes the live all-FAIL *and* delivers the ask.
5. Optional later: a `gut`/`Kev` judge to grade the diffs semantically; microeval/DeepEval only if
   a richer UI is ever wanted (off-box).

### Evidence / cross-ref
agent-reach reads: clay-good/agent-replay (record/replay/diff), boscoh/microeval (Ollama-native
eval), + tracegym/flight-recorder/tracecase/agentpytest (trace→fixture), DeepEval/pytest-eval/
gatecheck (eval-as-pytest/gating), Anthropic demystifying-evals (trajectory grading). Lab:
`feedback-server.py` (`_record_call`, `CALLS`/`CALLS_RING`/aggregates schema), `eval-weekly.py`,
`DASHBOARD-CHECK-2026-11-01.md` (stale all-FAIL finding), `SCOUT-ecosystem-2026-11-01.md`
(judge shim, observability ideas), `GAPS-whats-left-2026-11-01.md`. All stdlib-buildable on-box;
external tools are shape references, not adoptions. *External content rephrased for licensing.*
