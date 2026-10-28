## Goal

Turn the recovered agent findings (3 council round-1 plans, NOTEBOOK-round4, live lab verification, Oct-27 postmortem) into one ordered, gated lab plan: open the embeddings lane, settle KV tuning with numbers, merge the research, stand up alerting, and unblock off-box trials — with no unplanned downtime.

## Success Criteria

- `nomic-embed-text:v1.5` pulled, probed, and unloaded (2026-10-28); embeddings lane open; `bge-m3` demoted to optional multilingual follow-up.
- KV q8_0 adopted or reverted on measured A/B numbers (RAM@4k, tok/s, quality probe).
- `research/assist` (5 files) merged to main; plan doc committed; tree clean.
- MacBook Tier-A cleanup done (~9 GB reclaimed); stateless `/status` alerting live.
- `eval-weekly.py` runs deterministic pytest-verifiers, zero judge calls.
- 14b/8b removed (14 GB) through the tag-verified gate; Mini stays above 15 GB free throughout.
- mem0 trial run or blocked-list recorded with reason; every Mini-touch owner-gated.

## Approach

Unanimous council votes seat directly (Q2=A pattern-only evals, no Harbor; Q3=B defer tagging until real traffic). Split votes merge below. The panel had no Mini access; the coordinator facts cited are live-verified Oct 28.

- Q1 → A (T2 pulls before KV work), 2-1. P3's KV-first dissent (widen RAM before spending) is absorbed as a conditional trigger: one-token T2 probes barely touch KV, so pulls need no q8_0; if any probe shows RAM pressure, fast-track Phase 5 before continuing pulls.
- Q5 → A (remove 14b/8b first), 2-1, with P2's verification gate (exact tags only, then `ollama list` + `df` + health.log). Decisive new fact: the Mini has 29 GB free, so T2's ~8 GB fits above the 15 GB floor either way — remove-first is safe and also ends the standing ban violation.
- Q4 → coordinator override: build alerting, sequenced strictly after Tier-A cleanup (panel voted B 2-1). Both B arguments are answered by new evidence: the Oct-27 postmortem proves the missed-incident gap is real (relay outage misdiagnosed for lack of a second vantage point), and P2's disk objection is honored by building only post-cleanup with a stateless poller (no local log growth).
- Round-2 cross-review never ran (council superseded); this merge handles each dissent explicitly instead, above.
- Run-tab agents (codex/muse/kiro-run) left zero recoverable findings: muse-run's log holds startup records only, kiro-run's session is stillborn (no messages), no codex threads exist from today. Anything from that episode is user-held and can fold in at `go`.

## Steps

Gate legend: [SSH] Mini session (human password, already open in w32:p2); [APPROVE] explicit human go/no-go; [JUDGE] human judgment on data. Unmarked steps run in-worktree with no Mini state.

- Phase 0 — Merge research + plan doc (docs only, revertible). [APPROVE] Commit split (preserve at publish): C1 = the 5 research files (currently untracked in `wt-lab-research`, add + commit on `research/assist`, merge to main); C2 = this plan file, direct to main.
- Phase 1 — MacBook Tier-A cleanup (unblocks alerting + trials). [APPROVE] then human runs: `uv cache clean`, codex-runtimes, Google caches (~9 GB). Verify `df` before proceeding. Tier-B (`vm_bundles`) stays gated on a Claude-idle check in Phase 7.
- Phase 2 — Alerting (Q4 override). Build stateless poller + launchd plist in-worktree (checks Mini `/status`, health freshness, disk floor, banned-model presence; notifies via `terminal-notifier`/`osascript`, writes nothing locally). [APPROVE] Owner installs the LaunchAgent on the MacBook; prove the notify path once with a forced FAIL.
- Phase 3 — Remove `qwen2.5:14b` + `deepseek-r1:8b` (Q5=A). [SSH] [APPROVE] Verify exact tags first; `ollama rm` both; confirm `ollama list`, `df`, health.log OK. Abort if anything beyond those two tags would be touched.
- Phase 4 — T2 Tier-1 pulls (Q1=A head). [SSH] Sequential, off-hours, one at a time in ticket order (`nomic-embed-text:v1.5` first — done 2026-10-28; `bge-m3` now optional): pull → one-token 4k probe → unload → `df` ≥ 15 GB + health OK → next. [JUDGE] Abort list on any disk/RAM/thermal alarm; partial success is logged, never forced. RAM-pressure trigger: fast-track Phase 5. Milestone: `/status` shows `nomic-embed-text:v1.5` (done 2026-10-28); embeddings lane open.
- Phase 5 — KV q8_0 corrected A/B + adopt/revert (Q1=A tail). Prep the A/B sheet in-worktree (f16 vs q8_0: RAM@4k, tok/s, quality probe via `llama-bench`/one-token probe). [APPROVE] Restart window (drops resident model). [SSH] Set env + `launchctl unload/load`, run A/B. [JUDGE] Adopt on numbers; one-command revert (drop var, reload) on any quality/stability regression.
- Phase 6 — pytest-verifier evals (Q2=A). Build in-worktree in parallel from Phase 4 on (no Mini state needed): Harbor-shaped fixed prompt + verifier + binary reward as plain asserts, zero judge calls, no Docker. [SSH] Coordinator installs; weekly cadence unchanged.
- Phase 7 — Disk Tier-B check → off-box trials (gated on Phase 1; embedder `nomic-embed-text:v1.5` already live). [JUDGE] Confirm no live Claude session before `vm_bundles`. [APPROVE] mem0 first (cheapest, one-command rollback), anything-llm second; LangGraph runtime off-box, Mini stays the stateless LLM+embedder endpoint; evaluator-optimizer loop for grounding checks.
- Phase 8 — Deferred triggers (no action now). Tagging (Q3=B) when sustained multi-agent proxy traffic exists. The two web-recon gaps (Tailscale transport specifics; `bge-m3` vs `nomic-embed-text` CPU t/s) may run anytime via web-recon, never nlmx. T5 distillation trial (ticket written; needs cloud teacher budget + Colab).

## Validation Plan

- Phase 0: `git log --oneline -n 3` shows C1 merge + C2; `git status -sb` clean; 5 research files readable on main.
- Phase 1: `df -h /System/Volumes/Data | tail -n 1` shows ≥ ~10 GB free.
- Phase 2: `launchctl list | grep ai-lab` shows the poller; forced-FAIL drill produces exactly one notification; no new local log files after 24 h.
- Phase 3: `ollama list` lacks both tags; `df -h /` delta ≈ +14 GB; `tail -n 2 health.log` all OK.
- Phase 4: per pull — 4k probe OK then unloaded; `/status` lists each new model; `df` ≥ 15 GB every step; abort list file exists iff cut short; final: embedder present (`nomic-embed-text:v1.5` done; `bge-m3` only if multilingual needed).
- Phase 5: A/B sheet filled (RAM@4k both arms, tok/s, probe verdict); `ps eww` on the Ollama PID shows (adopt) or lacks (revert) `OLLAMA_KV_CACHE_TYPE`; Serve 200 throughout except the approved window.
- Phase 6: `eval-weekly.py` full local run green with zero judge calls asserted (verifier count in JSONL); weekly plist loaded on the Mini.
- Phase 7: mem0 trial report (connected to Mini tailnet endpoint, rollback command run once to prove it); `vm_bundles` untouched unless Claude-idle was confirmed in writing.
- Highest-risk validation: Phase 5's restart + quality probe — the only step combining downtime with a judgment call. Run it off-hours with the Phase 2 poller watching.

## Risks / Open Questions

Non-goals (per council + prior verdicts): Harbor-the-tool, litellm, Tier-C user-data deletes, on-box RAG UIs, running 8B/14B, any agent-held Mini SSH (all Mini steps stay human-session).

- Risk: T2 pull flakes mid-sequence (network) → abort list + resume; never parallel.
- Risk: q8_0 quality regression → one-command revert; A/B numbers decide, not preference.
- Risk: builds on a full disk before Phase 1 lands → keep pre-cleanup writes tiny (worktrees exist; no venvs/caches).
- Open: (1) Any run-tab findings you want folded in — paste them and they join at `go`. (2) Round-2 cross-review was skipped — accept this merge or run the review round first? (3) Which off-hours window may Mini phases (3–5) use?
