#!/bin/bash
# Standards-shaped KPI (E2.4) + dR/da at static Phi (E2.3) — needs root (netns) and a live radio.
#
#   E2.4  App. A Standards basis for AS2 — a TS 28.554 §6.4.2 shaped KPI under real traffic.
#         Sweeps ONLY the configured denominator with traffic running, showing a
#         standards-defined KPI moves on the configured half alone.
#   E2.3  §3.2 proxy vs. true quality — dR/da != 0 at PROVABLY STATIC Phi, with UEs attached and idle.
#         Refuses to record unless every Phi dimension is present and unchanged.
#
# Must NOT overlap the LLM chain: both write the same AMBR field. Each script
# aborts on its own if it detects llm_chain.sh running.
#
#   sudo bash srsran/run_standards_kpi_and_static_phi.sh
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
P=.venv/bin/python

if pgrep -f llm_chain.sh >/dev/null 2>&1; then
  echo "REFUSING: the LLM chain is running. Both write session[].ambr; wait for it."
  exit 1
fi
[ "$(id -u)" -eq 0 ] || { echo "REFUSING: run with sudo (netns access needed)"; exit 1; }

echo "=================== E2.4 — standards-shaped KPI under traffic ==================="
$P srsran/e2_4_standards_kpi.py --n-ue 4 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
echo
echo "=================== E2.3 — dR/da at provably static Phi ==================="
$P srsran/e2_3_dr_fixed_phi.py --n-ue 4 --repeats 5 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
echo
# Hand ownership back. Running under sudo makes every result root-owned, which
# stops the unprivileged refresh from overwriting it later — the sync then fails
# silently and analysis/ drifts out of step with srsran/results.
OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo "=================== refreshing SRSRAN_RESULTS.md ==================="
$P analysis/update_results.py
echo "E2.4 + E2.3 PHASE COMPLETE"
