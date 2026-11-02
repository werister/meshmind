# T14 — Paired-run gate for routing changes (no ship without a decisive win)

## Problem
Sequential A/Bs on the Mini are confounded three ways: run order (second
model inherits a hot, swap-pressured box), co-resident contention (both
models loaded at once), and sampling variance (unseeded draws, n=10).
Tonight this bit us live: the challenger swept a sequential run, then a
paired rerun (interleave AB/BA, 2 reps, shared seeds, unload-between)
produced 20 cells, 3 decisive split 1-2 after artifact exclusion (2 more
challenger losses were systematic no_fence), task favor 1-2-7,
task-level sign p=1.0 — no evidence of difference. The sequential verdict
did not survive controls. AGENTS.md routing must never ship on that basis
again.

## Goal
A working agreement + harness: every model-lane routing change ships iff a
paired comparison against the incumbent wins decisively. Borrowed from the
repos100 scan's ponytail pattern (paired ±change runs before shipping;
note the scan's pattern also used bootstrap intervals — this ticket uses
an exact sign test instead, see rule 1, because n is small and binary),
adapted to the lab's CPU box and stdlib-only rule.

## Design (harness — built, `scripts/code_bench.py`)
- `--order interleave`: counterbalancing on (task_index + rep), so every
  task sees both orders across reps; each row records rep, turn, and which
  model went first. (Order fixed per task would let a task x order
  interaction hide.)
- `--reps N`, `--seed S` (required), `--temp T` (required, explicit —
  invisible per-model Modelfile defaults are an uncontrolled confound).
  temp 0 with reps > 1 is refused (greedy reps duplicate draws).
- `--unload`: unload idle models before each turn and VERIFY via /api/ps
  (poll until absent; persistent presence = infra abort, never silent).
- `--journal PATH`: every scored row appended as JSONL (aborts keep evidence).
- Provenance in every findings object: argv, ollama URL, timestamp, fixture
  path-or-null, tasks dir + sha16 of names/prompts/asserts, per-model
  Ollama digests (best-effort), seed/temp. Fixture+reps runs flag
  `fixture_duplicates` unless entries are per-rep lists.
- The pairing is the shared task/time/order, NOT the seed: identical seeds
  map to unrelated draws across architectures; seeds buy reproducibility.

## Decision rule (normative)
A challenger replaces an incumbent iff ALL hold on ONE pre-registered run:
1. **Challenger wins significantly**: task-level two-sided sign p < 0.05
   (unit = task favoring; reps of one task are correlated and must not be
   the denominator), AND the challenger has strictly more favoring tasks.
   Two-sided 0.05 for a one-sided ship decision ≈ one-sided 0.025:
   deliberately conservative for a gate. p uses the unrounded value.
2. **Enough evidence**: >= 6 favoring tasks total. (Note the conjunction's
   bite: at 6 favoring tasks only 6-0 ships; 5-1 gives p=0.2188.)
3. **Magnitude**: net favoring tasks (challenger minus incumbent) >= 2 AND
   >= 20% of complete tasks. Significance on a sliver does not ship.
4. **Breadth**: the challenger's net spans >= 2 tasks (no single task may
   carry the decision). If tie rate > 90%, the task set is saturated —
   add harder tasks, not more reps.
5. **No parity reversal**: the overall loser must not lead either
   order-parity subset by >= 2 net cell wins (implemented; computed, not
   eyeballed). A win that reverses under one order is an order effect.
6. **Protocol health (loser-side)**: cells where EITHER side suffered a
   harness artifact (no_fence/timeout) are excluded from decisive counts —
   superiority inference runs on comparable cells only — and a win where
   the loser's decisive losses are majority-artifact does not ship.
   (Transport errors abort the run as infra; they can never appear in a
   completed run's artifact rate.)
Otherwise: NO DECISION (keep incumbent). A NO DECISION is a result, not a
failure — recorded with the run parameters.

## Pre-registration (normative)
Before a gate run, record: seed(s), temp, max cells (tasks x reps),
task-dir hash, unload on, stopping rule (fixed-N: run to completion, no
peek-and-extend; a temp-0 run is a SEPARATE pre-registered run, not a
follow-up to a p >= 0.05). Aborts are recorded too (journal path +
reason): completion correlates with box state, so unreported aborts are
survivorship bias. Re-running seeds until p < 0.05 is p-hacking and voids
the gate.

## Power guidance (non-normative, honest)
With the observed ~75% tie rate, the task-level test is strict — this gate
ships only clear wins ("only huge wins ship" is the conservative choice):

| favoring tasks (of 10) | shippable splits (p<0.05) |
|---|---|
| 6 | 6-0 only (p=0.0313) |
| 7 | 7-0 (0.0156) |
| 8 | 8-0 (0.0078), 7-1 (0.0703 NO) |
| 10 | 10-0, 9-1 (0.0215) |

Realistic path to power is MORE DISCRIMINATING TASKS (rule: scale tasks
first, cap reps at ~3 — reps add correlated pseudo-replicates, not
independent evidence). 20 discriminating tasks at a true 70% task-win rate
gives ~80% power; at 60%, ~800 cells-worth of tasks is honest but
impractical — in that regime the models are tied for routing purposes.

## Open gaps (acknowledged)
- Tasks are near-independent, not perfectly (shared box drift within a
  run); alternation spreads drift evenly but does not remove it.
- A routing win is a win *on this task set*; task-set expansion is the
  scaling path, not this ticket.
- Slow-model HTTP timeouts abort the whole run (fail-closed); the journal
  preserves partial evidence for the abort record.

## Red-team changelog (v1 -> v2)
Two independent red-teams (spec + implementation), both fix-first. v1
errors corrected: cell-level sign test over correlated reps (false-ship
11-34% at nominal 5%) -> task-level units; "scale reps" -> scale tasks,
cap reps; missing challenger-must-win; unimplemented parity/health ->
implemented + tested; fixed-per-task order -> (task+rep) counterbalance;
winner-side health -> loser-side artifacts excluded from decisive;
peek-and-extend -> pre-registration + abort ledger; temp-0+reps refused;
seed/temp required; unload verified via /api/ps; provenance block;
--journal; per-rep fixture lists; exit-contract holes closed
(ValueError/HTTPException -> infra); full-precision p; order/turn/first
recorded per row. Pre-existing out-of-scope notes kept: run_code tempfile
handling, _split_sections duplicate headings.

## Tests (named, stdlib only, offline)
`tests/test_code_bench.py` (29 tests): paired CLI block
(`test_paired_interleave`, `test_paired_all_ties`,
`test_paired_order_alternates_per_rep`, `test_paired_per_rep_fixture_lists`,
`test_paired_requires_two_models`, `test_paired_models_must_differ`,
`test_paired_requires_seed_and_temp`, `test_temp0_reps_refused`,
`test_reps_sequential_refused`, `test_unload_fixture_skips_with_note`,
`test_journal_survives_rows`, `test_provenance_recorded`,
`test_seed_threading_stubbed`, `test_bad_server_json_is_infra_not_traceback`)
plus direct `paired_summary` units (`test_summary_task_level_sign`,
`test_summary_artifacts_excluded`, `test_summary_parity_veto`,
`test_summary_incomplete_and_validation`). Suite 29/29.

## Pre-registered run P1 (recorded before launch)
- Question: does opencoder:1.5b replace qwen2.5-coder:3b in the Code lane?
- Parameters: --order interleave --reps 1 --seed 100 --temp 0 --unload,
  canonical tasks dir, --journal /tmp/paired-p1.jsonl, timeout 240.
- Rationale: temp-0 single rep = deterministic capability snapshot;
  cheapest run that can possibly ship (needs 6+ favoring tasks all
  challenger). If NO DECISION, the question stays open pending harder
  tasks (rule: scale tasks, not reps).
- Decision: SHIP iff all six rule clauses hold, else NO DECISION.
- Outcome: _(filled after the run)_

## Ticket fields
- Door: two-way (harness additive; AGENTS.md edits gated, never direct).
- Blast radius: small (bench + docs).
- Acceptance: this ticket merged AND the opencoder-vs-incumbent question
  re-run as a pre-registered gate run with a recorded SHIP / NO DECISION.
- May touch: `scripts/code_bench.py`, `tests/test_code_bench.py`,
  `AGENTS.md` (only through the gate), `docs/MODEL-FIT.md`, `docs/CANDIDATES*`.
- Must not: Mini serving core (Ollama/Caddy/launchd), bench task fixtures,
  origin pushes, anything outside the lab repo.
- Author: coordinator. Cost: $0.
