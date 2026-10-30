# T7 — Evaluate magnitude as alt CPU runtime (benchmark-gated)

Owner: coordinator. Effort: install + A/B bench. Risk: medium (new binary on
the Mini; Ollama stays default until numbers win).

Why: magnitudedev/magnitude (Rust inference engine, 7,380 stars, Intel-aware
kernel autotuning) claims >2x over Ollama on CPU. Unverified on AVX2-only
Intel. If true, it shifts every headroom number on this box.

Scope (strictly OUT of the model bake-off — a runtime swap is a confounder):
- Install magnitude on the Mini on a separate port; never serve the same
  model from Ollama and magnitude concurrently (double weights = OOM).
- A/B: same GGUF, same 4k ctx — magnitude vs Ollama (tok/s + RAM + quality).
- Adopt for a lane only on measured i5-8500B wins.

Acceptance: bench numbers recorded; adopt/reject decision with data.

## Outcome (2026-10-30, coordinator) — REJECT

Tested magnitude 0.2.15 on the Mini (macOS 15.8.1, i5-8500B) over SSH.
Install was clean (pinned GitHub release, sha256 + codesign + spctl verified);
`serve` ran headless on :10100 (no port conflict with Ollama/Caddy/sidecar).
No benchmark was possible — capability reject, not a speed loss:

- `catalog list`: zero compatible models for this computer.
- All 13 Ollama models found but unrunnable ("No kernels for the <arch>
  architecture" across qwen2/qwen3/gemma3/phi3/granite/smollm3/bert, plus
  unsupported tokenizers).
- Spot-check bartowski Llama-3.2-3B Q4_K_M: every quant Unsupported
  (rope_freqs.weight, tied output layer, quant types).
- Verdict: the engine cannot serve any model on this Intel CPU target in
  v0.2.15, so the "2x" claim is untestable here. Reject; revisit on a future
  version with CPU kernel coverage. Full evidence:
  `docs/RESEARCH-runtime-scout-2026-10-30.md`.
- Box restored to Ollama-only (app + data removed, Ollama 0.32.1 verified
  healthy, no models left loaded by this test).
