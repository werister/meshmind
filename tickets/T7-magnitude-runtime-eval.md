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
