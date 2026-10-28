#!/bin/sh
# ai-lab monitor (every 5 min via local.ai-lab.health): availability +
# capability snapshot + live token probe + cumulative tokens + feedback -> health.log
LAB="$HOME/local-ai-lab"
LOG="$LAB/health.log"
FB="$LAB/feedback.log"
STATE="$LAB/monitor-state"
TS=$(date "+%Y-%m-%dT%H:%M:%S%z")
SERVE="https://mac-mini-von-hugo-1.taild73e38.ts.net"
if curl -s --max-time 15 http://127.0.0.1:11434/api/version 2>/dev/null | grep -q version; then L="OK"; else L="FAIL"; fi
if curl -s --max-time 20 "$SERVE/api/version" 2>/dev/null | grep -q version; then R="OK"; else R="FAIL"; fi
TAGS=$(curl -s --max-time 15 http://127.0.0.1:11434/api/tags 2>/dev/null)
NMODELS=$(printf "%s" "$TAGS" | grep -o "\"name\":" | wc -l | tr -d " ")
PS=$(curl -s --max-time 15 http://127.0.0.1:11434/api/ps 2>/dev/null)
LOADED=$(printf "%s" "$PS" | grep -o "\"name\":\"[^\"]*\"" | cut -d "\"" -f4 | tr "\n" "," | sed "s/,\$//")
[ -z "$LOADED" ] && LOADED="none"
PROBE=$(curl -s --max-time 60 http://127.0.0.1:11434/api/chat -d "{\"model\":\"qwen2.5:0.5b\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: OK\"}],\"stream\":false}" 2>/dev/null)
EC=$(printf "%s" "$PROBE" | grep -o "\"eval_count\":[0-9]*" | grep -o "[0-9][0-9]*" | head -1)
ED=$(printf "%s" "$PROBE" | grep -o "\"eval_duration\":[0-9]*" | grep -o "[0-9][0-9]*" | head -1)
TPS=$(awk -v c="${EC:-0}" -v d="${ED:-0}" "BEGIN{if(d>0) printf \"%.1f\", c/d*1000000000; else print 0}")
PTOT=0
if [ -f "$STATE" ]; then PTOT=$(grep -o "[0-9][0-9]*" "$STATE" 2>/dev/null | head -1); fi
[ -z "$PTOT" ] && PTOT=0
PTOT=$((PTOT + ${EC:-0}))
echo "$PTOT" > "$STATE"
FTOT=$(grep -o "\"tokens\": [0-9][0-9]*" "$FB" 2>/dev/null | grep -o "[0-9][0-9]*" | awk "BEGIN{s=0}{s+=\$1}END{print s}")
if [ -f "$FB" ]; then FBN=$(wc -l < "$FB" | tr -d " "); FBLAST=$(tail -1 "$FB" 2>/dev/null | head -c 120); else FBN=0; FBLAST="none"; fi
# ---- T6: memory + swap telemetry (additive) ------------------------------
# Sample vm_stat + sysctl vm.swapusage at this (5-min) cadence. Report MB.
# Parse drift or a missing tool -> the field stays "null"; the monitor keeps
# running and still logs everything else. State file carries the previous
# swap_used and loaded-model set so we can log a delta and raise an alert when
# swap grows across a model load.
MEMSTATE="$LAB/mem-state"
MEM_FREE_MB="null"; MEM_COMPRESSED_MB="null"; SWAP_USED_MB="null"
VMSTAT=$(vm_stat 2>/dev/null)
if [ -n "$VMSTAT" ]; then
  PGSZ=$(printf "%s" "$VMSTAT" | head -1 | grep -o "page size of [0-9]* bytes" | grep -o "[0-9][0-9]*" | head -1)
  if [ -n "$PGSZ" ]; then
    FREE_PG=$(printf "%s" "$VMSTAT" | grep "Pages free" | grep -o "[0-9][0-9]*" | head -1)
    COMP_PG=$(printf "%s" "$VMSTAT" | grep "Pages occupied by compressor" | grep -o "[0-9][0-9]*" | head -1)
    [ -n "$FREE_PG" ] && MEM_FREE_MB=$(awk -v p="$FREE_PG" -v s="$PGSZ" "BEGIN{printf \"%d\", p*s/1048576}")
    [ -n "$COMP_PG" ] && MEM_COMPRESSED_MB=$(awk -v p="$COMP_PG" -v s="$PGSZ" "BEGIN{printf \"%d\", p*s/1048576}")
  fi
fi
SWAPRAW=$(sysctl -n vm.swapusage 2>/dev/null)
if [ -n "$SWAPRAW" ]; then
  # e.g. "total = 2048.00M  used = 512.50M  free = 1535.50M"
  SU=$(printf "%s" "$SWAPRAW" | sed -n "s/.*used = \([0-9.]*\)\([KMG]*\).*/\1 \2/p")
  if [ -n "$SU" ]; then
    SWAP_USED_MB=$(printf "%s" "$SU" | awk "{u=\$1; unit=\$2; if(unit==\"K\")u=u/1024; else if(unit==\"G\")u=u*1024; else if(unit==\"\")u=u/1048576; printf \"%d\", u}")
  fi
fi
# Previous sample (swap_used_mb and loaded set) for delta + load detection.
PREV_SWAP="null"; PREV_LOADED=""
if [ -f "$MEMSTATE" ]; then
  PREV_SWAP=$(sed -n "1p" "$MEMSTATE" 2>/dev/null)
  PREV_LOADED=$(sed -n "2p" "$MEMSTATE" 2>/dev/null)
  [ -z "$PREV_SWAP" ] && PREV_SWAP="null"
fi
SWAP_DELTA_MB="null"
if [ "$SWAP_USED_MB" != "null" ] && [ "$PREV_SWAP" != "null" ]; then
  SWAP_DELTA_MB=$((SWAP_USED_MB - PREV_SWAP))
fi
# A "load" = a model present now that was not present last tick.
LOAD_EVENT="no"
if [ "$LOADED" != "none" ]; then
  OLDIFS=$IFS; IFS=","
  for m in $LOADED; do
    case ",$PREV_LOADED," in
      *",$m,"*) : ;;
      *) [ -n "$m" ] && LOAD_EVENT="yes" ;;
    esac
  done
  IFS=$OLDIFS
fi
# Alert: swap grew while a new model loaded this tick.
if [ "$LOAD_EVENT" = "yes" ] && [ "$SWAP_DELTA_MB" != "null" ] && [ "$SWAP_DELTA_MB" -gt 0 ]; then
  echo "$TS ALERT swap_grew_during_load swap_delta_mb=$SWAP_DELTA_MB swap_used_mb=$SWAP_USED_MB loaded=[$LOADED] prev_loaded=[$PREV_LOADED]" >> "$LOG"
fi
# Persist this tick's swap + loaded set for the next comparison.
printf "%s\n%s\n" "$SWAP_USED_MB" "$LOADED" > "$MEMSTATE"
echo "$TS local=$L serve=$R installed=$NMODELS loaded=[$LOADED] probe_tok_s=$TPS probe_tokens=${EC:-0} total_probe_tokens=$PTOT total_feedback_tokens=${FTOT:-0} feedback_n=$FBN feedback_last=[$FBLAST] mem_free_mb=$MEM_FREE_MB mem_compressed_mb=$MEM_COMPRESSED_MB swap_used_mb=$SWAP_USED_MB swap_delta_mb=$SWAP_DELTA_MB load_event=$LOAD_EVENT" >> "$LOG"
