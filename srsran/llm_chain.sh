#!/bin/bash
# The srsRAN LLM experiment chain, started and controlled by srsran/chain.sh.
#
#   E5  policy-field reachability, agent side      (App. E)
#   E3  target attribution and target-free control  (§6.2, App. F)
#   E6  capability sweep: frontier tier first (if ANTHROPIC_API_KEY is set), then the
#       paper's local tiers 7-8B and 12-15B          (§6.2 Model coverage, App. F)
#
# Every tier uses the same agent loop, system prompt and intent corpus, so a tier
# difference cannot be a prompt difference. Trials are checkpointed per cell under
# srsran/results/llm_trials/<exp>/; a paused or interrupted chain resumes where it stopped.
# To re-run trials from scratch, move those directories aside first (run_artifact.sh
# live-srsran does this automatically).
cd "$(dirname "$(readlink -f "$0")")/.." || exit 1
P=.venv/bin/python
PAUSE=/tmp/srsran/PAUSE
mkdir -p /tmp/srsran
log(){ echo; echo "=================== $* @ $(date +%H:%M:%S) ==================="; }

ensure_collector(){
  pgrep -f "collector.collector" >/dev/null 2>&1 || {
    echo "[chain] collector not running — starting it"
    setsid nohup $P -m collector.collector >> /tmp/srsran/collector.log 2>&1 < /dev/null &
    sleep 8
  }
}

run_stage(){
  ensure_collector
  set -o pipefail
  "$@" 2>&1 | grep -vE "COLLECTOR|pymongo|Waiting for suitable"
  local rc=${PIPESTATUS[0]}
  set +o pipefail
  if [ "$rc" -eq 17 ]; then log "CHAIN PAUSED — resume with: srsran/chain.sh resume"; exit 17
  elif [ "$rc" -ne 0 ]; then log "CHAIN HALTED — stage exited $rc"; exit "$rc"; fi
}

[ -f "$PAUSE" ] && { echo "PAUSE flag set — remove it first (srsran/chain.sh resume)"; exit 17; }

log "E5 — policy-field reachability"
run_stage $P srsran/e5_multivariable.py --n-channel 12 --n-agent 5

log "E3 — target attribution and target-free control"
run_stage $P srsran/e3_attribution.py --n 5

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  log "E6 — frontier tier (Anthropic claude-sonnet-4-5)"
  run_stage $P srsran/e6_capability_sweep.py --n 20 --only-frontier \
      --frontier-backend anthropic --frontier-model claude-sonnet-4-5
else
  log "E6 — ANTHROPIC_API_KEY unset: skipping the frontier tier"
fi

log "E6 — local tiers (7-8B, 12-15B)"
run_stage $P srsran/e6_capability_sweep.py --n 20 --tiers 7-8B,12-15B

log "CHAIN COMPLETE — compare with the paper: $P analysis/verify_paper.py --fresh"
