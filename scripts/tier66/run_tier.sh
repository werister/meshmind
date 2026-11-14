# Tier-66 tie-break runner (see docs/T2-tier66-2026-11-13.md).
#!/bin/bash
# Round-two T2: 66-item tie-break for the voter top tier (>=16/18 on the sweep).
# One run (seed 11) per model; harness.py resumes/refills on its own out files.
# Usage: t2_tier66.sh [dry]   (dry = budgets only, no lab calls)
EV="$(cd "$(dirname "$0")" && pwd)"
MODELS="granite4:micro-h gemma4:e2b gemma3:4b gemma3:4b-it-q4_K_M nuextract:latest huggingfacetb-smollm3-3b-q4-k-m:bakeoff qwen3:4b-instruct-2507-q4_K_M qwen3:8b falcon3:3b"
i=0
for m in $MODELS; do
  i=$((i + 1))
  out=./out/tier66_m$i.jsonl
  if [ "$1" = "dry" ]; then
    python3 $EV/harness.py --model "$m" --items $EV/items.jsonl --out $out --runs 1 --dry-run
  else
    echo "=== T2 [$i/9] $m ==="
    python3 $EV/harness.py --model "$m" --items $EV/items.jsonl --out $out --runs 1 --tag tier66-2026-11-13 >> ./out/t2_tier66.log 2>&1
    echo "T2 [$i/9] exit=$? $m"
  fi
done
echo T2-DONE
