# Voter sweep — all chat models × 18 yes/no (2026-11-13)

Box: Mac Mini i5-8500B, 8 GB, CPU-only Ollama (tailnet lab). Ollama 0.32.1. Serial, one model at a time, `keep_alive:0`
unload between models. Harness: `scripts/sweep_voter_all.py` (resume-safe,
per-item error rows, raws kept). Transcript: `results/2026-11-13/voter.jsonl`.

Contract (same as the Nov 11 pilot): native `/api/chat`, temp 0, `think:false`,
`num_predict: 8`, system `Answer with exactly one word: YES or NO.`, strict
first-token parse (`?` counts wrong). Items: 8 standard truths + hard-10
near-miss set (thermal Eiffel, O(n) binary search, octopus hearts, 100k genes,
lightning, flamboyance, Venus spin, Titanic 1912, goldfish memory, sound in
water). Embed-only models excluded (3); LFM3 errored on all 18 (server 500s —
see T-but-fixed note below).

| model | correct/18 | med s | eval tok |
|---|---|---|---|
| `granite4:micro-h` | 18 | 2.0 | 36 |
| `gemma4:e2b` | 18 | 1.8 | 36 |
| `gemma3:4b` | 18 | 2.3 | 54 |
| `gemma3:4b-it-q4_K_M` | 18 | 2.3 | 54 |
| `nuextract:latest` | 18 | 1.7 | 144 |
| `huggingfacetb-smollm3-3b-q4-k-m:bakeoff` | 17 | 1.0 | 42 |
| `qwen3:4b-instruct-2507-q4_K_M` | 17 | 1.1 | 36 |
| `qwen3:8b` | 17 | 2.8 | 36 |
| `falcon3:3b` | 16 | 0.8 | 36 |
| `granite3.3:2b` | 15 | 1.0 | 37 |
| `nemotron-3-nano:4b` | 14 | 4.1 | 36 |
| `phi4-mini:latest` | 14 | 1.1 | 36 |
| `sam860/falcon-h1:1.5b` | 13 | 4.1 | 47 |
| `granite3.1-moe:3b` | 13 | 0.5 | 44 |
| `voter-granite-moe:3b` | 13 | 0.5 | 44 |
| `phi3.5:3.8b` | 13 | 1.6 | 114 |
| `gemma3:1b-it-q4_K_M` | 13 | 1.1 | 53 |
| `qwen3:1.7b` | 12 | 1.3 | 36 |
| `llama3.2:3b-instruct-q4_K_M` | 12 | 0.8 | 36 |
| `qwen2.5:1.5b` | 11 | 0.8 | 36 |
| `qwen2.5-coder:1.5b` | 11 | 0.7 | 36 |
| `qwen2.5:3b` | 11 | 1.0 | 36 |
| `qwen3:0.6b` | 10 | 0.5 | 36 |
| `llama3.2:1b-instruct-q4_K_M` | 10 | 0.9 | 54 |
| `qwen2.5-coder:3b` | 10 | 0.9 | 36 |
| `granite4.2:3b-q4_K_M` | 10 | 0.9 | 36 |
| `qwen2.5:0.5b` | 9 | 0.4 | 36 |
| `openbmb/minicpm5-2b:latest` | 9 | 1.2 | 66 |
| `qwen2.5:3b-instruct-q3_K_M` | 9 | 1.0 | 36 |
| `hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M` | 8 | 1.2 | 36 |
| `granite3.1-moe:1b` | 8 | 0.4 | 54 |
| `granite4:1b-h` | 8 | 2.3 | 36 |
| `granite-code:3b` | 8 | 1.1 | 69 |
| `athena-slm:latest` | 8 | 0.6 | 37 |
| `rwkv7-g1g-proof:latest` | 8 | 1.8 | 36 |
| `hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M` | 8 | 0.6 | 44 |
| `functiongemma:latest` | 3 | 0.8 | 87 |
| `opencoder:1.5b` | 1 | 1.1 | 135 |
| `yi-coder:1.5b` | 0 | 0.9 | 142 |
| `qwen2.5:3b-instruct-q2_K` | 0 | 1.4 | 144 |
| `qwen3:4b-thinking-2507-q4_K_M` | 0 | 1.9 | 144 |

Notes: five models tied at 18/18 (ceiling — broken by T2, see
`T2-tier66-2026-11-13.md`). Voter-0 is a format verdict, not a quality
verdict: yi-coder (0/18) codes 25/26. LFM3's 500s were fixed the next day
by the Ollama 0.32.1 → 0.40.16 update (`unknown model architecture: lfm3`);
re-test scored 8/18 + 6/26 (weak, kept installed).
