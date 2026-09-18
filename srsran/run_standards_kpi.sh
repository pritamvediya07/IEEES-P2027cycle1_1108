#!/bin/bash
# E2.4 — standards basis for AS2 (paper App. A); needs root.
#
#   E2.4: a TS 28.554 §6.4.2 shaped KPI measured under REAL TRAFFIC.
#   Sweeps ONLY the configured denominator while traffic runs, showing that a
#   KPI the STANDARD defines moves on the configured half alone — so a consumer
#   cannot tell whether utilisation fell because the network got quieter or
#   because an operator raised the ceiling. That is AS2 grounded in TS 28.554
#   rather than in a schema we chose.
#
# Handles the whole sequence itself:
#   1. pauses the LLM chain and waits for it to stop cleanly
#      (both write session[].ambr; concurrent runs corrupt each other)
#   2. runs E2.4 — brings up gNB + 4 UEs + broker, starts traffic, sweeps
#   3. refreshes SRSRAN_RESULTS.md
#   4. resumes the chain exactly where it left off
#
#   sudo bash srsran/run_standards_kpi.sh
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
P=.venv/bin/python
[ "$(id -u)" -eq 0 ] || { echo "run with sudo — netns access is required"; exit 1; }

echo "=== 1/4  pausing the LLM chain ==="
touch /tmp/srsran/PAUSE
for i in $(seq 1 60); do
  pgrep -f llm_chain.sh >/dev/null 2>&1 || break
  [ $((i % 6)) -eq 0 ] && echo "    waiting for the trial in flight to finish and checkpoint ($((i*5))s)"
  sleep 5
done
pgrep -f llm_chain.sh >/dev/null 2>&1 && { echo "chain did not stop; aborting"; rm -f /tmp/srsran/PAUSE; exit 1; }
echo "    chain paused, work banked"

echo
echo "=== 2/4  E2.4 — standards-shaped KPI under traffic ==="
$P srsran/e2_4_standards_kpi.py --n-ue 4 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
RC=${PIPESTATUS[0]}

echo
# Hand ownership back. Running under sudo makes every result root-owned, which
# stops the unprivileged refresh from overwriting it later — the sync then fails
# silently and analysis/ drifts out of step with srsran/results.
OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo "=== 3/4  refreshing SRSRAN_RESULTS.md ==="
$P analysis/update_results.py 2>&1 | sed 's/^/    /'

echo
echo "=== 4/4  resuming the LLM chain ==="
rm -f /tmp/srsran/PAUSE
sudo -u "$(stat -c %U "$ROOT")" bash srsran/chain.sh resume 2>&1 | sed 's/^/    /'

echo
[ "$RC" -eq 0 ] && echo "E2.4 COMPLETE — recorded" || echo "E2.4 exited $RC — see the output above"
