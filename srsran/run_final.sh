#!/bin/bash
# E-FINAL — the capstone. Is NGN reward hacking real on a fully real testbed,
# and does the defence stop it?
#
# Everything is real: srsRAN gNB + 4 srsUE over ZeroMQ, Open5GS core, Φ measured
# on the live radio, R read through the same kpi_analyzer the agent uses, the
# published PALA loop and SYSTEM_PROMPT, and CLOSED_LOOP_INTENTS verbatim from
# wave_experiments/shared/intents.py.
#
#   sudo bash srsran/run_final.sh          # 8 sessions per arm, ~2h
#   sudo bash srsran/run_final.sh 5        # 5 per arm, ~75 min
set -u
N=${1:-8}
B=${2:-5.0}     # per-UE baseline Mbps. Calibration measured Q=0.5604 here and
                # Q=0.3021 at the 15 Mbps target, i.e. 0.2583 of headroom — the
                # widest of any ceiling in the sweep.
TAG=${3:-}
CLASS=${4:-}    # optional: "targeted" or "open_ended" to run a single stratum.
                # Without it the corpus is split half and half.
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
P=.venv/bin/python
[ "$(id -u)" -eq 0 ] || { echo "run with sudo — netns access required"; exit 1; }

echo "=== 1/5  pausing the LLM chain ==="
touch /tmp/srsran/PAUSE
for i in $(seq 1 90); do
  pgrep -f llm_chain.sh >/dev/null 2>&1 || break
  [ $((i % 6)) -eq 0 ] && echo "    waiting for the trial in flight ($((i*5))s)"
  sleep 5
done
pgrep -f llm_chain.sh >/dev/null 2>&1 && { echo "chain would not stop; aborting"; exit 1; }
echo "    chain paused, work banked"

echo; echo "=== 2/5  collector daemon must be UP (the proxy has to update) ==="
pgrep -f "collector.collector" >/dev/null 2>&1 || {
  setsid nohup $P -m collector.collector >> /tmp/srsran/collector.log 2>&1 < /dev/null &
  sleep 8; }
pgrep -f "collector.collector" >/dev/null 2>&1 && echo "    collector up" || { echo "collector failed"; exit 1; }

if [ ! -f srsran/results/calibration_regime.json ]; then
  echo "no calibration on file — run: sudo $P srsran/calibrate_regime.py"; exit 1
fi

echo; echo "=== 3/5  E-FINAL — Definition 4, ${N} sessions per arm, baseline ${B} Mbps/UE ==="
$P srsran/e_final_def4.py --n "$N" --n-ue 4 --baseline "$B" ${TAG:+--tag "$TAG"} ${CLASS:+--only-class "$CLASS"} 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable|UndefinedMetricWarning|warnings.warn"
RC=${PIPESTATUS[0]}

OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo; echo "=== 4/5  refreshing SRSRAN_RESULTS.md ==="
$P analysis/update_results.py 2>&1 | sed 's/^/    /'

echo; echo "=== 5/5  chain left PAUSED ==="
echo "    resume E6 local tiers with: srsran/chain.sh resume"
echo
[ "$RC" -eq 0 ] && echo "E-FINAL COMPLETE" || echo "E-FINAL exited $RC"
