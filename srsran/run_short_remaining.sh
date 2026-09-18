#!/bin/bash
# The two short outstanding experiments, in one radio session.
#
#   E2.3      C2 — dR/da != 0 at PROVABLY STATIC Phi. UEs attached and IDLE,
#             Phi measured on both sides of the write, refuses to record unless
#             every dimension is present and unchanged. Includes an ISO control.
#   E0.2      re-record n=1 and n=2 at slow_down_ratio 1. The published E0.2
#             covered n=3,4 at that ratio; n=1 and n=2 were taken earlier under
#             a different ratio, so the scale curve mixes two configurations.
#
# Both need root. Pauses the chain first, resumes after.
#
#   sudo bash srsran/run_short_remaining.sh
set -u
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

echo; echo "=== 2/5  E2.3 — dR/da at provably static Phi  (C2) ==="
$P srsran/e2_3_dr_fixed_phi.py --n-ue 4 --repeats 5 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
RC1=${PIPESTATUS[0]}

echo; echo "=== 3/5  E0.2 — re-record n=1 and n=2 at slow_down 1 ==="
$P srsran/e0_2_scale.py --min-n 1 --max-n 2 --slow-down 1 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
RC2=${PIPESTATUS[0]}

# Hand ownership back. Running under sudo makes every result root-owned, which
# stops the unprivileged refresh from overwriting it later — the sync then fails
# silently and analysis/ drifts out of step with srsran/results.
OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo; echo "=== 4/5  refreshing SRSRAN_RESULTS.md ==="
$P analysis/update_results.py 2>&1 | sed 's/^/    /'

echo; echo "=== 5/5  leaving the chain PAUSED ==="
echo "    E6 local tiers are the last stage and should be started deliberately:"
echo "      srsran/chain.sh resume"

echo
echo "E2.3 exit $RC1 | E0.2 exit $RC2"
[ "$RC1" -eq 0 ] && [ "$RC2" -eq 0 ] && echo "SHORT REMAINING WORK COMPLETE"
