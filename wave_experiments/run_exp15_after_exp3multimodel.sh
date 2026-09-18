#!/usr/bin/env bash
# Auto-launches exp15_inference_vs_session.py after exp3_multimodel.py (PID 358264) finishes.
# Usage: bash run_exp15_after_exp3multimodel.sh

set -euo pipefail

WAIT_PID=358264
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/results/exp15_run.log"

mkdir -p "$SCRIPT_DIR/results"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for exp3_multimodel (PID $WAIT_PID) to finish..."

while kill -0 "$WAIT_PID" 2>/dev/null; do
    sleep 30
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] PID $WAIT_PID finished. Launching exp15..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log → $LOG"

cd "$SCRIPT_DIR/.."
nohup .venv/bin/python wave_experiments/exp15_inference_vs_session.py \
    >> "$LOG" 2>&1 &

NEW_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exp15 started with PID $NEW_PID"
echo "$NEW_PID" > "$SCRIPT_DIR/results/exp15.pid"
echo "PID file: $SCRIPT_DIR/results/exp15.pid"
