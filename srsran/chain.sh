#!/bin/bash
# Control the LLM experiment chain: start | pause | resume | status | stop
#
# Pausing is safe at any time. Trials are checkpointed one file per cell, keyed
# by a hash of the cell's identity (arm, register, intent, defense, model,
# repeat index) rather than by position. A resume therefore skips every finished
# cell and never returns one cell's result under another's labels — which is
# what a positional scheme would do the moment the cell list changed.
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
PAUSE=/tmp/srsran/PAUSE
mkdir -p /tmp/srsran
LOG=/tmp/srsran/llm_chain.log
CHAIN="$ROOT/srsran/llm_chain.sh"
P=.venv/bin/python

banked(){ local t=0; for d in E9 E5 E3 E7 E6; do
    n=$(ls srsran/results/llm_trials/$d 2>/dev/null | wc -l); t=$((t+n));
    [ "$n" -gt 0 ] && printf "    %-4s %3d cells\n" "$d" "$n"; done
  echo "    ---- $t cells banked"; }

ensure_collector(){
  pgrep -f "collector.collector" >/dev/null 2>&1 || {
    echo "  starting collector daemon (required: without it the channel is closed)"
    setsid nohup $P -m collector.collector > /tmp/srsran/collector.log 2>&1 < /dev/null &
    sleep 8; }
}

case "${1:-status}" in
  start|resume)
    if pgrep -f llm_chain.sh >/dev/null 2>&1; then echo "  already running"; exit 0; fi
    rm -f "$PAUSE"
    ensure_collector
    echo "  resuming — banked work is skipped:"; banked
    # APPEND, never truncate. A resume used to overwrite the log, so when a
    # chain exited unexpectedly the evidence of WHY vanished with it — one
    # restart could not be explained afterwards because its predecessor's final
    # output had already been erased.
    { echo; echo "########## chain (re)started $(date '+%F %T') by ${SUDO_USER:-$USER} ##########"; } >> "$LOG"
    setsid nohup bash "$CHAIN" >> "$LOG" 2>&1 < /dev/null &
    sleep 3
    pgrep -f llm_chain.sh >/dev/null && echo "  chain running" || echo "  FAILED to start"
    ;;
  pause)
    touch "$PAUSE"
    echo "  pause requested — the chain will stop at the next cell boundary"
    echo "  (the trial in flight finishes and is checkpointed first)"
    ;;
  stop)
    touch "$PAUSE"
    for pid in $(pgrep -f llm_chain.sh) $(pgrep -f "srsran/e[0-9].*\.py"); do
      kill -TERM "$pid" 2>/dev/null; done
    sleep 2
    pgrep -f llm_chain.sh >/dev/null 2>&1 && echo "  still running" || echo "  stopped"
    echo "  banked:"; banked
    ;;
  status)
    if pgrep -f llm_chain.sh >/dev/null 2>&1; then echo "  chain: RUNNING"; else echo "  chain: stopped"; fi
    [ -f "$PAUSE" ] && echo "  PAUSE flag is set — chain will not proceed past the next cell"
    pgrep -f "collector.collector" >/dev/null 2>&1 && echo "  collector: running" || echo "  collector: DOWN"
    echo "  stage: $(grep -E '^=+ (B\(|B-Q2|REVIEWER|A |A1|CHAIN)' "$LOG" 2>/dev/null | tail -1 | sed 's/=//g')"
    banked
    ;;
  *) echo "usage: $0 {start|resume|pause|stop|status}"; exit 1;;
esac
