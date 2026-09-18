#!/bin/bash
# E3-Φ — Definition 4 evaluated end-to-end, Q measured during agent sessions.
#
# The rebuild proved each half of Definition 4 separately and never together:
#   E2.3  dR/da != 0 at provably static Phi  (180.0 standard vs 0.0 isolated)
#   E1    victim Q falls 0.4415 -> 0.2580 as one slice over-provisions
# E3 ran with probe=None, so no agent session measured Q and def4_satisfied read
# 0/60 because the condition was never evaluated. This closes that gap.
#
# Needs root (netns) and a live radio. The collector daemon MUST stay up — unlike
# E2.3, whose ISO control required it stopped, here the agent must be able to read
# its own writes back or the experiment measures nothing.
#
#   sudo bash srsran/run_e3_phi.sh
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
P=.venv/bin/python
[ "$(id -u)" -eq 0 ] || { echo "run with sudo — netns access required"; exit 1; }

echo "=== 1/4  pausing the LLM chain ==="
touch /tmp/srsran/PAUSE
for i in $(seq 1 90); do
  pgrep -f llm_chain.sh >/dev/null 2>&1 || break
  [ $((i % 6)) -eq 0 ] && echo "    waiting for the trial in flight ($((i*5))s)"
  sleep 5
done
pgrep -f llm_chain.sh >/dev/null 2>&1 && { echo "chain would not stop; aborting"; exit 1; }
echo "    chain paused, work banked"

echo; echo "=== 2/4  ensuring the collector daemon is UP (required here) ==="
pgrep -f "collector.collector" >/dev/null 2>&1 || {
  setsid nohup $P -m collector.collector >> /tmp/srsran/collector.log 2>&1 < /dev/null &
  sleep 8; }
pgrep -f "collector.collector" >/dev/null 2>&1 && echo "    collector up" || { echo "collector failed"; exit 1; }

echo; echo "=== 3/4  E3-Φ — Definition 4 on measured Q ==="
$P srsran/e3_phi_def4.py --n 3 --n-ue 4 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
RC=${PIPESTATUS[0]}

OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo; echo "=== 4/4  refreshing SRSRAN_RESULTS.md ==="
$P analysis/update_results.py 2>&1 | sed 's/^/    /'
echo
echo "    chain left PAUSED — resume E6 local tiers with: srsran/chain.sh resume"
[ "$RC" -eq 0 ] && echo "E3-Φ COMPLETE — check def4_satisfied and mean ΔQ per arm" || echo "E3-Φ exited $RC"
