#!/usr/bin/env python3
"""
V4 Experiment Runner — E4.1 → E4.2 → E4.3 → E4.5 → E4.6
Run from marcus root:  python experiments/experiments_suite_v2/run_v4.py
"""
import sys, os
from pathlib import Path

# ── 1. Force marcus root at sys.path[0] BEFORE any imports ──────
# This ensures 'from config.db import ...' inside PALA tools resolves
# to the config/ package (directory), not any experiment-level file.
MARCUS = Path(__file__).parent.parent.parent  # /path/to/pala-artifact
if str(MARCUS) in sys.path:
    sys.path.remove(str(MARCUS))
sys.path.insert(0, str(MARCUS))

# ── 2. Insert experiments dir so 'from exp_config import *' resolves ──
EXPS_DIR = Path(__file__).parent / "experiments"
if str(EXPS_DIR) not in sys.path:
    sys.path.insert(1, str(EXPS_DIR))

# ── 3. Run suite ─────────────────────────────────────────────────
from v4_decomposition.experiments import (
    run_e4_1, run_e4_2, run_e4_3, run_e4_5, run_e4_6,
)

print("\n" + "#"*70)
print("#  V4: FEASIBILITY GATE DECOMPOSITION — E4.1 → E4.6 (no LLM)")
print("#"*70)

r1 = run_e4_1()
beta              = r1["beta"]            if r1 else None   # β_cooldown
beta_ambr         = r1.get("beta_ambr")  if r1 else None
provisioned_dl    = r1.get("_provisioned_dl") if r1 else None
provisioned_ul    = r1.get("_provisioned_ul") if r1 else None

r2 = run_e4_2(beta)
# E4.3 waits V4_COOLDOWN_WAIT_SEC internally to clear E4.2's cooldown
r3 = run_e4_3(beta, beta_ambr)
r5 = run_e4_5(beta)   # includes its own 31s cooldown wait before policy write
r6 = run_e4_6(beta)

print("\n" + "="*70)
print("V4 FINAL SUMMARY")
print("="*70)
if r1:
    print(f"  E4.1  β_cooldown = {r1.get('beta_cooldown')}  "
          f"β_ambr = {r1.get('beta_ambr')}  "
          f"(AMBR ceiling FAIL at δ={r1.get('phase_b_first_fail')})")
if r2: print(f"  E4.2  Manual decomp      : {'SUCCESS' if r2.get('decomposition_successful') else 'FAIL'}")
if r3:
    pa = r3.get("part_a_allowed")
    pb = r3.get("part_b_blocked")
    print(f"  E4.3  Part A (cooldown ablation): {'PASS ✓' if pa else 'FAIL ✗'}  "
          f"Part B (AMBR ceiling): {'BLOCKED ✓' if pb else 'NOT BLOCKED ✗'}")
if r5: print(f"  E4.5  iperf3 ratio       : {r5.get('ratio')}")
if r6: print(f"  E4.6  Defense            : blocked at step {r6.get('blocked_at_step')}")

# ── Teardown: restore provisioned AMBR ──────────────────────────
if provisioned_dl and provisioned_ul:
    from v4_decomposition.experiments import reset_ambr
    import time
    print("\n  Restoring provisioned AMBR after all V4 experiments...")
    time.sleep(35)   # clear final cooldown
    reset_ambr(provisioned_dl, provisioned_ul)
    print("  Provisioned AMBR restored.")

print("\nE4.4 (LLM autonomous, ~1-3 h) — run separately:")
print("  python -c \"import sys; sys.path.insert(0,'$(pwd)'); "
      "from experiments.experiments_suite_v2.experiments.v4_decomposition.experiments "
      "import run_e4_4; run_e4_4()\"")
