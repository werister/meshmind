# T1 — think-enabled reasoning, 7 thinking-capable models × 4 (2026-11-13)

Box: Mac Mini i5-8500B, 8 GB, CPU-only Ollama (tailnet lab). Harness: `scripts/t1_reason.py`. Transcript:
`results/2026-11-13/t1.jsonl`. Items (same graded set as Nov 11 bench5):
apples (20), train (4), syllogism (C), bat-ball (5). Grader: last number /
first letter, empty counts wrong. Instruct-only models excluded (server
hard-errors on think:true); granite4.2 excluded (already 4/4 on these items).

| model | think setting | score/4 |
|---|---|---|
| `nemotron-3-nano:4b` | default | 4 |
| `qwen3:4b-instruct-2507-q4_K_M` | think=false/300 | 4 |
| `qwen3:0.6b` | think=true/900 | 3 |
| `rwkv7-g1g-proof:latest` | default | 3 |
| `qwen3:4b-thinking-2507-q4_K_M` | think=true/900 | 2 |
| `qwen3:8b` | think=true/900 | 2 |
| `qwen3:1.7b` | think=true/900 | 1 |

Notes: think-on HURT short items (empties): qwen3:4b-thinking and qwen3:8b
2/4 with think=true+900, and a 2048-budget retest (T1b) gave the identical
2/4 (same items) — budget starvation falsified, model-side quirk confirmed.
Controls swept: nemotron 4/4, qwen3:4b-instruct 4/4.
