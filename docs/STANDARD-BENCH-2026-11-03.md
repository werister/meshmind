# Standard benchmarks 2026-11-03 — GSM8K-20 + MMLU-20, 6 models

First standard numbers for the box. Live run, temp 0, serial, X-Agent
lab-standard. GSM8K: step-by-step + trailing #### scoring, 300 tok (thinkers
need headroom). MMLU: letter-only, first-A-D scoring, 200 tok. Samples are
rows 0-19 of each test split (NOT the harness stride-700 sample — future
runs go through scripts/gsm8k.py + scripts/mmlu_lite.py).

| Model | GSM8K-20 | MMLU-20 |
|---|---|---|
| qwen3:4b-instruct-2507 | 11/20 | 10/20 (best overall) |
| smollm3-3b via /api | 12/20 (best math) | 6/20 |
| gemma3:4b | 10/20 | 8/20 |
| nemotron-3-nano:4b | 9/20 | 7/20 |
| phi4-mini | 5/20 | 8/20 |
| granite4.2:3b | UNRANKED (artifact) | UNRANKED (artifact) |

## Diagnoses (do not quote the raw table without these)
- Granite 0/20 is BUDGET STARVATION: retested at 600 tok it answers perfectly
  but burns 410 tokens on "3+8". Needs >=500 tok budgets; retest pending.
- MMLU 6-10/20 is REAL (near the 5/20 random floor): non-thinkers answered in
  2-3s with no budget pressure. College knowledge is beyond this weight class.
- smollm3 0/10 on the earlier /v1 battery was a PATH failure: over /api/chat
  it leads GSM8K. Always route smollm3 native until the v1 quirk is understood.

## Cost notes
~35-45s per GSM8K question (reasoning models), 2-3s per MMLU for non-thinkers.
Full 240-call sweep took ~2h wall. Transcript: /tmp/lab-standard.json (ephemeral).
