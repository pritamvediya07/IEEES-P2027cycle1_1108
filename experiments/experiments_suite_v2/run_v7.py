#!/usr/bin/env python3
"""
V7 Experiment Runner — E7.1 → E7.6 + Ablations
Wireheading: policy write → collector propagation → Type P in D_ana → H_kpi consumption.

Run from marcus root:
    python experiments/experiments_suite_v2/run_v7.py

Independent of V4 results; can run concurrently with E4.4.
"""
import sys, time
from pathlib import Path

# ── 1. MARCUS root at sys.path[0] ────────────────────────────────────────────
MARCUS = Path(__file__).parent.parent.parent
if str(MARCUS) in sys.path:
    sys.path.remove(str(MARCUS))
sys.path.insert(0, str(MARCUS))

# ── 2. Experiments dir ───────────────────────────────────────────────────────
EXPS_DIR = Path(__file__).parent / "experiments"
if str(EXPS_DIR) not in sys.path:
    sys.path.insert(1, str(EXPS_DIR))

# ── 3. Pre-flight checks ─────────────────────────────────────────────────────
print("\n" + "#"*70)
print("#  V7: COLLECTOR FEEDBACK WIREHEADING — E7.1 → E7.6 + Ablations")
print("#"*70)

from pymongo import MongoClient
try:
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    db_ana = client["nwdaf_analytics"]
    n_upf = db_ana["upf_metrics"].count_documents({})
    n_pcf = db_ana["pcf_metrics"].count_documents({})
    print(f"  MongoDB OK — upf_metrics={n_upf} docs, pcf_metrics={n_pcf} docs")
except Exception as e:
    print(f"  [ERROR] MongoDB not reachable: {e}")
    sys.exit(1)

# ── 4. Run suite ─────────────────────────────────────────────────────────────
from v7_wireheading.experiments import (
    run_e7_1, run_e7_2, run_e7_3,
    run_e7_4a, run_e7_4b, run_e7_4c,
    run_e7_5, run_e7_6, run_ablations,
    _read_ambr_bps,
)
from exp_config import DNN_INTERNET, V4_COOLDOWN_WAIT_SEC

# Read baseline AMBR before any writes (for teardown)
provisioned_dl, provisioned_ul = _read_ambr_bps(DNN_INTERNET)
print(f"\n  Current AMBR (flat path): DL={provisioned_dl/1e6:.1f} Mbps" if provisioned_dl else
      "\n  WARNING: Could not read current AMBR — teardown may not restore correctly")

# E7.1: Baseline field inventory (no writes)
r1 = run_e7_1()

# E7.2: Policy +30% write (triggers cooldown — wait before E7.3)
r2 = run_e7_2()
# E7.3 only needs collector propagation (3 × 5s = 16s), well within cooldown window.
# No extra wait needed here — E7.3 itself calls wait_for_collector(cycles=3).

# E7.3: Propagation + provenance trace
r3 = run_e7_3()

# Wait for cooldown to clear before further policy writes
print(f"\n  Waiting {V4_COOLDOWN_WAIT_SEC}s for E7.2 cooldown to clear...")
time.sleep(V4_COOLDOWN_WAIT_SEC)

# E7.4a: Instrumentation — what fields does H_kpi read?
r4a = run_e7_4a()

# E7.4b: Type P removal — does masking change H_kpi output?
# (Temporarily deletes + restores pcf_metrics docs — no cooldown triggered)
r4b = run_e7_4b()

# E7.4c: Discriminating case (writes +30%, waits, reads same offered load)
print(f"\n  Waiting {V4_COOLDOWN_WAIT_SEC}s before E7.4c policy write...")
time.sleep(V4_COOLDOWN_WAIT_SEC)
r4c = run_e7_4c()

# E7.5: Escalation (illustrative — no LLM calls, just instructions)
r5 = run_e7_5()

# E7.6: Defense — isolated DB (runs regardless, gracefully skips if port 27018 absent)
print(f"\n  Waiting {V4_COOLDOWN_WAIT_SEC}s before E7.6 policy write...")
time.sleep(V4_COOLDOWN_WAIT_SEC)
r6 = run_e7_6()

# Ablations: A7.5 query timing sweep
print(f"\n  Waiting {V4_COOLDOWN_WAIT_SEC}s before ablation policy write...")
time.sleep(V4_COOLDOWN_WAIT_SEC)
abl = run_ablations()

# ── 5. Restore AMBR ──────────────────────────────────────────────────────────
if provisioned_dl and provisioned_ul:
    from v7_wireheading.experiments import _read_ambr_bps
    from utils import call_policy_manager
    current_dl, _ = _read_ambr_bps(DNN_INTERNET)
    if current_dl != provisioned_dl:
        print(f"\n  Restoring AMBR to {provisioned_dl/1e6:.1f} Mbps...")
        time.sleep(V4_COOLDOWN_WAIT_SEC)
        call_policy_manager("apply_policy", {
            "dnn": DNN_INTERNET, "ambr_dl": provisioned_dl, "ambr_ul": provisioned_ul
        })
        print("  AMBR restored.")
    else:
        print(f"\n  AMBR already at {provisioned_dl/1e6:.1f} Mbps — no restore needed.")

# ── 6. Summary ───────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("V7 COMPLETE")
print("="*70)
if r3:
    print(f"  E7.3  Type P propagated to D_ana : {'CONFIRMED ✓' if r3.get('accepted') else 'NOT FOUND ✗'}")
if r4a:
    print(f"  E7.4a AMBR in pcf_metrics        : {r4a.get('pcf_metrics_contains_ambr')}")
if r4b:
    delta = r4b.get('delta')
    print(f"  E7.4b Type P causal effect       : {'YES ✓' if r4b.get('type_p_causal') else 'NO ✗'}  "
          f"(Δ={delta:.4f})" if delta is not None else "")
if r4c:
    div = r4c.get('delta_diverge')
    print(f"  E7.4c Discriminating evidence    : {'YES ✓' if r4c.get('discriminating_evidence') else 'NO ✗'}  "
          f"(Δ_diverge={div:.4f})" if div is not None else "")
if r6:
    print(f"  E7.6  Defense isolation          : {'ACCEPTED ✓' if r6.get('accepted') else 'SETUP NEEDED'}")
if abl:
    lat = abl.get('circuit_latency_s')
    print(f"  A7.5  Circuit latency            : {lat}s" if lat else "  A7.5  No propagation detected in timing sweep")
