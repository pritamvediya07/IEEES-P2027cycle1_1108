#!/usr/bin/env python3
"""
E4.4 Runner — LLM Autonomous Decomposition Trials
20 attack trials + 10 benign control trials + Fisher's exact test.

Run from marcus root:
    python experiments/experiments_suite_v2/run_e4_4.py

Takes 1–3 hours (30 trials × Llama 3.1 agentic loop per trial).
"""
import sys, time
from pathlib import Path

# ── 1. MARCUS root at sys.path[0] (config/ package must resolve before config.py) ──
MARCUS = Path(__file__).parent.parent.parent
if str(MARCUS) in sys.path:
    sys.path.remove(str(MARCUS))
sys.path.insert(0, str(MARCUS))

# ── 2. Experiments dir for exp_config and utils ──
EXPS_DIR = Path(__file__).parent / "experiments"
if str(EXPS_DIR) not in sys.path:
    sys.path.insert(1, str(EXPS_DIR))

# ── 3. Imports ───────────────────────────────────────────────────
from v4_decomposition.experiments import (
    run_e4_4,
    get_current_ambr,
    set_experiment_baseline,
    reset_ambr,
)
from exp_config import V4_COOLDOWN_WAIT_SEC, V4_EXPERIMENT_BASELINE_MBPS

# ── 4. Pre-flight checks ─────────────────────────────────────────
print("\n" + "#"*70)
print("#  V4-E4.4: LLM AUTONOMOUS DECOMPOSITION — 20 attack + 10 control")
print("#"*70)

# Verify Ollama is reachable
import requests
try:
    r = requests.get("http://localhost:11434/api/tags", timeout=5)
    models = [m["name"] for m in r.json().get("models", [])]
    print(f"  Ollama OK — models: {models}")
except Exception as e:
    print(f"  [ERROR] Ollama not reachable: {e}")
    print("  Start Ollama first: ollama serve")
    sys.exit(1)

# Verify MongoDB
from pymongo import MongoClient
try:
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    print("  MongoDB OK")
except Exception as e:
    print(f"  [ERROR] MongoDB not reachable: {e}")
    sys.exit(1)

# ── 5. Clear stale APScheduler jobs ──────────────────────────────
# Previous experiment sessions accumulate cron jobs in MongoDB.  When
# MonitoringManager starts its scheduler during a trial, it fires all
# "missed" jobs immediately — causing spurious AMBR changes that are
# invisible to extract_tool_calls() and corrupt the decomposition count.
try:
    from pymongo import MongoClient as _MC
    _c = _MC("mongodb://localhost:27017")
    n_deleted = _c["nwdaf_analytics"]["apscheduler_jobs"].delete_many({}).deleted_count
    print(f"  Cleared {n_deleted} stale APScheduler job(s) from MongoDB.")
except Exception as _e:
    print(f"  [WARN] Could not clear APScheduler jobs: {_e}")

# ── 6. Set experiment baseline (20 Mbps) ─────────────────────────
# E4.4 calls reset_ambr(original_dl, original_ul) before each trial.
# original_dl is read at the start of run_e4_4() — if it's 1 Mbps,
# all sub-100% increments floor to 1 Mbps and are invisible.
# We need ≥ 20 Mbps so decomposed steps (e.g. 33% each) register.

provisioned_dl, provisioned_ul = get_current_ambr()
print(f"\n  Provisioned AMBR: {provisioned_dl/1e6:.1f} Mbps")

print(f"  Setting experiment baseline to {V4_EXPERIMENT_BASELINE_MBPS} Mbps...")
baseline_dl, baseline_ul = set_experiment_baseline()

print(f"  Waiting {V4_COOLDOWN_WAIT_SEC}s for baseline cooldown to clear...")
time.sleep(V4_COOLDOWN_WAIT_SEC)

# ── 6. Run E4.4 ──────────────────────────────────────────────────
result = run_e4_4()

# ── 7. Restore provisioned AMBR ──────────────────────────────────
print(f"\n  Restoring provisioned AMBR ({provisioned_dl/1e6:.1f} Mbps)...")
time.sleep(V4_COOLDOWN_WAIT_SEC)
reset_ambr(provisioned_dl, provisioned_ul)
print("  Provisioned AMBR restored.")

# ── 8. Final summary ─────────────────────────────────────────────
print("\n" + "="*70)
print("E4.4 COMPLETE")
print("="*70)
if result:
    sr  = result.get("success_rate", 0)
    pv  = result.get("fisher_p_value")
    ci  = result.get("wilson_ci_95", [None, None])
    acc = result.get("accepted")
    print(f"  Attack success rate : {sr:.1%}  "
          f"(95% CI [{ci[0]:.1%}, {ci[1]:.1%}])" if ci[0] is not None else "")
    print(f"  Fisher p-value      : {pv:.6f}" if pv is not None else "  Fisher p-value: N/A")
    print(f"  ACCEPTED            : {acc}  (criterion: p < 0.05)")
