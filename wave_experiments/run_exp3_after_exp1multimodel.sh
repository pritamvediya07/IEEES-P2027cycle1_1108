#!/usr/bin/env bash
# Auto-launches exp3_multimodel.py after exp1_vuln_multimodel.py (PID 244320) finishes.
# Usage: bash run_exp3_after_exp1multimodel.sh [--trials N]

set -euo pipefail

WAIT_PID=244320
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/results/exp3_multimodel_run.log"
TRIALS="${2:-30}"

mkdir -p "$SCRIPT_DIR/results"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for exp1_vuln_multimodel (PID $WAIT_PID) to finish..."

# Poll until the PID is gone
while kill -0 "$WAIT_PID" 2>/dev/null; do
    sleep 30
done

echo "[$(date '+%Y-%m-%d %H:%M:%S')] PID $WAIT_PID finished. Launching exp3_multimodel..."
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Log → $LOG"

cd "$SCRIPT_DIR/.."
nohup .venv/bin/python wave_experiments/exp3_multimodel.py --trials "$TRIALS" \
    >> "$LOG" 2>&1 &

NEW_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] exp3_multimodel started with PID $NEW_PID"
echo "$NEW_PID" > "$SCRIPT_DIR/results/exp3_multimodel.pid"
echo "PID file: $SCRIPT_DIR/results/exp3_multimodel.pid"
