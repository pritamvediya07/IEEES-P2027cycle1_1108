#!/bin/bash
# E2.3 re-run with a WORKING IsolatedCollector control.
#
# The previous attempt left the collector daemon active. It writes standard
# ambr_dl_mean records every 5 s regardless of the experiment's own
# tick(isolated), so the "isolated" arm read a live standard stream and returned
# dR = 180.0 — identical to the treatment arm. The control established nothing.
#
# This stops the daemon for the duration and restarts it afterwards, because the
# LLM experiments need it and would silently produce invalid data without it.
#
#   sudo bash srsran/rerun_e2_3.sh
set -u
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"
P=.venv/bin/python
[ "$(id -u)" -eq 0 ] || { echo "run with sudo — netns access required"; exit 1; }

echo "=== 1/4  stopping the collector daemon (required for a valid ISO control) ==="
for pid in $(pgrep -f "collector.collector"); do kill -TERM "$pid" 2>/dev/null; done
sleep 4
pgrep -f "collector.collector" >/dev/null && { echo "daemon would not stop; aborting"; exit 1; }
echo "    daemon stopped"

echo; echo "=== 2/4  E2.3 — dR/da at provably static Phi, ISO control now genuine ==="
$P srsran/e2_3_dr_fixed_phi.py --n-ue 4 --repeats 5 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
RC=${PIPESTATUS[0]}

echo; echo "=== 3/4  restarting the collector daemon ==="
setsid nohup $P -m collector.collector >> /tmp/srsran/collector.log 2>&1 < /dev/null &
sleep 8
pgrep -f "collector.collector" >/dev/null && echo "    daemon back up" || echo "    WARNING: daemon did not restart — start it before any LLM run"

# Hand ownership back. Running under sudo makes every result root-owned, which
# stops the unprivileged refresh from overwriting it later — the sync then fails
# silently and analysis/ drifts out of step with srsran/results.
OWNER=$(stat -c %U "$ROOT")
chown -R "$OWNER:$OWNER" "$ROOT/srsran/results" \
                          "$ROOT/analysis" 2>/dev/null
echo "    ownership returned to $OWNER"

echo; echo "=== 4/4  refreshing SRSRAN_RESULTS.md ==="
$P analysis/update_results.py 2>&1 | sed 's/^/    /'
echo
[ "$RC" -eq 0 ] && echo "E2.3 COMPLETE — check that the ISO arm now shows dR = 0" || echo "E2.3 exited $RC"
