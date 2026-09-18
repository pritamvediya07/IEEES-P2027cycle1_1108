#!/usr/bin/env bash
# Auto-launches exp5_multimodel.py after exp3_multimodel.py (PID 358264) finishes.
# Usage: bash run_exp5_after_exp3multimodel.sh [--trials N]

set -euo pipefail

WAIT_PID=358264
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/results/exp5_multimodel_run.log"
TRIALS="${2:-20}"

mkdir -p "$SCRIPT_DIR/results"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for exp3_multimodel (PID $WAIT_PID) to finish..."

while kill -0 "$WAIT_PID" 2>/dev/null; do
    sleep 30
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] PID $WAIT_PID finished. Launching exp5_multimodel..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log → $LOG"

cd "$SCRIPT_DIR/.."
nohup .venv/bin/python wave_experiments/exp5_multimodel.py --trials "$TRIALS" \
    >> "$LOG" 2>&1 &

NEW_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exp5_multimodel started with PID $NEW_PID"
echo "$NEW_PID" > "$SCRIPT_DIR/results/exp5_multimodel.pid"
echo "PID file: $SCRIPT_DIR/results/exp5_multimodel.pid"
