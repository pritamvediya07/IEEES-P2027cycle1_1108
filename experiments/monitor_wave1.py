#!/usr/bin/env python3
"""
Wave 1 live monitor — prints a status update every 60 seconds.
Run in background; stream with Monitor tool.
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).parent
EXP1_DIR = THIS_DIR / "exp1_results"
QUEUE_LOG = THIS_DIR / "queue_logs" / "queue_master_v3.log"


def tc_rate() -> str:
    try:
        r = subprocess.run(["sudo", "tc", "class", "show", "dev", "lo"],
                           capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if "1:10" in line and "rate" in line:
                for tok in line.split():
                    if tok.endswith("Mbit") or tok.endswith("Kbit"):
                        val = float(tok[:-4])
                        unit = tok[-4:]
                        mbps = val if unit == "Mbit" else val / 1000
                        return f"{mbps:.2f} Mbps"
    except Exception:
        pass
    return "N/A"


def current_ambr_from_tc(tc_str: str) -> str:
    try:
        mbps = float(tc_str.split()[0])
        if mbps <= 0:
            return "N/A"
        ambr = 20.0 * 20.0 / mbps
        return f"~{ambr:.0f} Mbps"
    except Exception:
        return "N/A"


def load_trials(arm_dir: Path) -> list:
    trials = []
    for p in sorted(arm_dir.glob("trial_[0-9][0-9][0-9].json")):
        try:
            trials.append(json.loads(p.read_text()))
        except Exception:
            pass
    return trials


def queue_position() -> str:
    if not QUEUE_LOG.exists():
        return "unknown"
    lines = QUEUE_LOG.read_text().splitlines()
    current = "unknown"
    for line in reversed(lines):
        if "Next:" in line or "Starting:" in line or "FINISHED" in line or "PARALLEL" in line:
            current = line.split(None, 3)[-1].strip()
            break
    return current


def arm_summary(model_tag: str, arm: str) -> str:
    arm_dir = EXP1_DIR / model_tag / arm
    if not arm_dir.exists():
        return f"  {arm:10s}: not started"
    trials = load_trials(arm_dir)
    n = len(trials)
    if n == 0:
        return f"  {arm:10s}: 0/30 trials"
    def4 = sum(1 for t in trials if t.get("def4_measurable"))
    kdagger_vals = [t["q_drop_at_kdagger"] for t in trials
                    if t.get("q_drop_at_kdagger") is not None]
    last = trials[-1]
    last_kd = f"{last['q_drop_at_kdagger']:.1f}%" if last.get("q_drop_at_kdagger") else "N/A"
    mean_kd = f"{sum(kdagger_vals)/len(kdagger_vals):.1f}%" if kdagger_vals else "N/A"
    return (f"  {arm:10s}: {n:2d}/30 trials | "
            f"def4_meas={def4/n:.0%} ({def4}/{n}) | "
            f"Q@k†: last={last_kd}  mean={mean_kd}")


def print_status():
    now = datetime.now().strftime("%H:%M:%S IST")
    tc  = tc_rate()
    ambr = current_ambr_from_tc(tc)
    qpos = queue_position()

    print(f"\n{'='*65}")
    print(f"  WAVE 1 STATUS  {now}")
    print(f"{'='*65}")
    print(f"  Queue position : {qpos}")
    print(f"  tc rate (lo)   : {tc}  →  agent AMBR ≈ {ambr}")
    print()

    model_tag = "qwen2_5-72b"
    for arm in ["vulnerable", "defended"]:
        print(arm_summary(model_tag, arm))

    # Latest trial quick look
    for arm in ["vulnerable", "defended"]:
        arm_dir = EXP1_DIR / model_tag / arm
        trials  = load_trials(arm_dir)
        if trials:
            t = trials[-1]
            kd = f"{t['q_drop_at_kdagger']:.1f}%" if t.get("q_drop_at_kdagger") else "N/A"
            print(f"\n  Latest {arm} trial {t['trial_idx']:03d}: "
                  f"def4_meas={t.get('def4_measurable')}  "
                  f"Q@k†={kd}  "
                  f"R:{t.get('r_baseline',0):.0f}→{t.get('r_final',0):.0f} Mbps  "
                  f"elapsed={t.get('elapsed_s',0):.0f}s")

    print(f"{'='*65}")
    sys.stdout.flush()


if __name__ == "__main__":
    print(f"[monitor] Wave 1 monitor started — updates every 60 s")
    sys.stdout.flush()
    while True:
        try:
            print_status()
        except Exception as e:
            print(f"[monitor] error: {e}")
            sys.stdout.flush()
        time.sleep(60)
