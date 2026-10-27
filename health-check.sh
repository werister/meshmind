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
echo "$TS local=$L serve=$R installed=$NMODELS loaded=[$LOADED] probe_tok_s=$TPS probe_tokens=${EC:-0} total_probe_tokens=$PTOT total_feedback_tokens=${FTOT:-0} feedback_n=$FBN feedback_last=[$FBLAST]" >> "$LOG"
