# Code sweep — all chat models × 5 tasks / 26 exec cases (2026-11-13)

Box: Mac Mini i5-8500B, 8 GB, CPU-only Ollama (tailnet lab). Harness: `scripts/sweep_code_all.py` (resume-safe, raws kept,
10 s exec cap per task, trickle-proof call deadlines). Transcript:
`results/2026-11-13/code.jsonl`.

Contract (same as the Nov 12 code bench): native `/api/chat`, temp 0,
`think:false`, `num_predict: 300`. Tasks: fib (6), first_unique (5), merge
(4), bisect-fix (6), max_profit (5). Grading: extract `def`, reject on
import-poison regex, exec in a capped thread, exact-name + exact-output.
`timeout-loop` = model emitted an infinite loop (killed at 10 s, counts 0).

| model | cases/26 | eval tok |
|---|---|---|
| `gemma3:1b-it-q4_K_M` | 26 | 629 |
| `nemotron-3-nano:4b` | 26 | 351 |
| `qwen2.5-coder:3b` | 26 | 395 |
| `qwen2.5:1.5b` | 26 | 458 |
| `qwen2.5:3b` | 26 | 473 |
| `sam860/falcon-h1:1.5b` | 26 | 596 |
| `granite3.3:2b` | 25 | 514 |
| `nuextract:latest` | 25 | 449 |
| `yi-coder:1.5b` | 25 | 982 |
| `gemma3:4b` | 24 | 573 |
| `gemma3:4b-it-q4_K_M` | 24 | 573 |
| `granite4.2:3b-q4_K_M` | 23 | 465 |
| `qwen2.5-coder:1.5b` | 22 | 399 |
| `gemma4:e2b` | 20 | 548 |
| `granite4:micro-h` | 20 | 345 |
| `llama3.2:3b-instruct-q4_K_M` | 20 | 349 |
| `opencoder:1.5b` | 20 | 1011 |
| `phi4-mini:latest` | 20 | 405 |
| `qwen3:4b-instruct-2507-q4_K_M` | 20 | 420 |
| `rwkv7-g1g-proof:latest` | 19 | 383 |
| `qwen3:8b` | 18 | 329 |
| `huggingfacetb-smollm3-3b-q4-k-m:bakeoff` | 16 | 412 |
| `openbmb/minicpm5-2b:latest` | 16 | 427 |
| `qwen2.5:0.5b` | 16 | 604 |
| `granite-code:3b` | 15 | 391 |
| `granite3.1-moe:3b` | 15 | 476 |
| `qwen3:1.7b` | 14 | 311 |
| `qwen3:0.6b` | 13 | 375 |
| `athena-slm:latest` | 12 | 567 |
| `granite4:1b-h` | 11 | 301 |
| `granite3.1-moe:1b` | 8 | 331 |
| `hf.co/turintech/Qwen3.5-0.8B-Artemis-GGUF:Q5_K_M` | 8 | 705 |
| `llama3.2:1b-instruct-q4_K_M` | 8 | 678 |
| `phi3.5:3.8b` | 7 | 679 |
| `hf.co/LiquidAI/LFM3-1.7B-GGUF:Q4_K_M` | 6 | 277 |
| `qwen2.5:3b-instruct-q3_K_M` | 5 | 688 |
| `falcon3:3b` | 4 | 433 |
| `functiongemma:latest` | 0 | 222 |
| `qwen2.5:3b-instruct-q2_K` | 0 | 900 |
| `qwen3:4b-thinking-2507-q4_K_M` | 0 | 1500 |
| `voter-granite-moe:3b` | 0 | 61 |

Notes: six models tied at 26/26 (broken by T3, see `T3-bank100-2026-11-13.md`).
opencoder (voter 1/18) codes 20/26 — same format-vs-skill split as yi-coder.
qwen2.5:3b Q2_K 0/26 confirms sub-4-bit quants are dead on this box.
