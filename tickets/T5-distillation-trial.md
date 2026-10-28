# T5 — Distillation trial (specialist judge)

Owner: coordinator + cloud teacher. Effort: one Colab session + Mini eval.
Risk: low (all training off-box; Mini only evaluates a GGUF).

Why: round-5 evidence (QLoRA adapters +54–55% on domain tasks; 1.5B
specialists edging 7B bases) says the next judge upgrade is a distilled
specialist, not a bigger base. Baseline to beat: smollm2:1.7b @ 0.709
AUC, 0.6 s/call (mml-tests/results.txt).

Recipe (from MODELS-nlmx-round5 Q3):
1. Teacher (cloud lane, GPT-oss-120B class): generate domain judgments.
2. Validation cascade: keep only outputs passing format/schema checks.
3. QLoRA finetune (free Colab): 4-bit NF4 base + FP16 adapters, 1.5B student.
4. Export GGUF (Q4_K_M) → `ollama create` on Mini → eval vs baseline.
5. Adopt iff AUC beats 0.709 at ≤1 s/call; else keep smollm2.

Guardrails: no training on the Mini (CPU-only box); student ≤2B;
quality probe before any traffic; one-command rollback (`ollama rm`).
Needs: cloud teacher budget + Colab session (human).
