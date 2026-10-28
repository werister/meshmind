# T9 — pull-pack + bake-off runner + guarded pull script (BUILD)

## Problem
The 5 gateway pulls are verified except SmolLM3 (exact GGUF unresolved);
there is no composed bake-off runner and no guarded pull procedure —
a tired human pulling 5 models by hand is the failure mode. The installed
roster is also 3 months stale, so each slot needs a freshness re-check.

## Goal
0. Freshness re-check (NEW): for each of the 5 slots, check the Ollama
   registry + huggingface.co for a strictly-newer same-class release
   (same size class, Ollama tag or verified GGUF). Prefer the newer
   drop-in; record a per-slot kept/superseded decision + why. Blog and
   benchmark claims are leads — registry tags are evidence.
1. `docs/GATEWAY-PULLPACK.md`: per model — exact tag or GGUF file ID,
   size, source, and the coordinator's verify command. SmolLM3 is either
   resolved (exact filename + bytes from huggingface.co) or explicitly
   DROPPED with the reason recorded. No pull without a verified line.
2. `scripts/bakeoff.py` implementing [docs/GATEWAY-CONTRACTS.md](../docs/GATEWAY-CONTRACTS.md)
   v1.2: composes run_8q + run_ladder (+ optional `--screen-cmd`) per model,
   writes findings table (md + json).
3. `scripts/mini_pull.py` implementing contracts v1.2: guarded single-model
   pull for the coordinator to run on the Mini (disk/size/probe checks).

Builder runs in a MacBook pane with FULL network (only the coordinator
is sandboxed): the HF API and ollama.com registry are reachable —
verify against them, never guess.

## Non-goals
- Builder executes zero pulls and touches nothing on the Mini.
- No 8Q/ladder implementation (consume the T8 contract, do not reimplement).
- No embedding bake-off build (coordinator hand-runs nomic vs bge-m3
  per the runbook checklist — cut from build, kept as evidence).
- No keeper refresh: re-pulling the installed roster is deferred until
  after the bake-off (do not move the baseline mid-experiment).
- No logprob screen fork (shell out to the mml-stack script or skip
  with null + note).

## Behavior
Per contracts v1.2. Pull-pack lines carry: model, exact spec, expected
GB (±20% assert band), source URL, verify command. bakeoff continues
past a failed model (marked, not fatal). mini_pull aborts before
pulling when free disk <15GB or post-pull size is out of band.

## Failure modes
| Trigger | Visible result | Test |
|---|---|---|
| SmolLM3 unresolvable | PULLPACK marks DROPPED + reason, bake-off runs 4 models | coordinator re-checks HF (not unit-testable — verify-close) |
| Newer drop-in found | PULLPACK takes it, decision recorded | coordinator re-checks registry (verify-close) |
| Disk <15GB at pull time | abort before pull, stderr reason, exit 2 | test_disk_guard (fixture df) |
| Post-pull size out of band | exit 2 + keep/revert note | test_size_band |
| One model fails mid-bakeoff | marked failed, rest continue | test_continue_past_failure |
| screen-cmd missing | screen null + note, no crash | test_screen_skip |

## Tests (named, stdlib only)
`tests/test_bakeoff.py`, `tests/test_mini_pull.py` (+ fixtures).
Contract-conformance against stub 8Q/ladder scripts in fixtures.

## Ticket fields
- Door: two-way. Blast radius: small (build) / medium at coordinator
  execution (Mini pulls — runbook guards).
- Acceptance: `python3 tests/test_bakeoff.py && python3 tests/test_mini_pull.py` → exit 0 with PASS counts, AND coordinator re-verifies
  every PULLPACK line + freshness decision against the registry/HF
  before first pull.
- May touch: `scripts/bakeoff.py`, `scripts/mini_pull.py`, `docs/GATEWAY-PULLPACK.md`, `tests/test_bakeoff.py`, `tests/test_mini_pull.py`, `tests/fixtures/gateway/*` (coordinate fixture names with T8: prefix `b9-*`).
- Must not: `scripts/run_8q.py`, `scripts/run_ladder.py`, `feedback-server.py`, `Caddyfile`, `health-check.sh`, `.env`, `mockups/`, `tickets/`, anything on the Mini.
- Author: kiro crew B. Reviewer: coordinator (verify-close) + security lens at diff.
- Cost: $0. Disk note: MacBook <5GB free — targeted tests only, no installs.
