#!/usr/bin/env python3
"""
Master Experiment Queue Runner — Wave 1 (Qwen only)
════════════════════════════════════════════════════
Runs all Wave 1 experiments in dependency order after Exp 1 vulnerable
arm finishes. Health-checks results after each experiment and logs
everything. Does NOT abort on health-check warnings — logs and continues.

Wave 1 queue order:
  1. exp11_posthoc   — Q-weight sensitivity (post-hoc, no GPU)
  2. exp1_defended   — End-to-end defended arm
  3. exp9_sensitivity — Architectural parameter sweep (no GPU)
  4. exp14_taxonomy  — Contamination taxonomy (no GPU)
  5. exp2_qwen       — Register trichotomy
  6. exp6_phase1     — HedgeTune calibration (Phase 1 only)
  7. [k†* auto-update hook]
  8. [AS5 sanity check hook]
  9. exp5_qwen       — Necessity ablation
  10. exp13_qwen      — Benign recovery

Usage:
  # Waits for PID to finish, then runs the queue:
  nohup .venv/bin/python experiments/run_queue.py --wait-pid <PID> > experiments/queue_logs/queue_master.log 2>&1 &

  # Start from a specific experiment (skips earlier ones):
  .venv/bin/python experiments/run_queue.py --start exp1_defended

  # Only run health checks on existing results (no new runs):
  .venv/bin/python experiments/run_queue.py --check-only
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── paths ──────────────────────────────────────────────────────────────────────
MARCUS = Path(__file__).resolve().parent.parent

EXPERIMENTS = MARCUS / "experiments"
PYTHON      = MARCUS / ".venv" / "bin" / "python"
LOG_DIR     = EXPERIMENTS / "queue_logs"
LOG_DIR.mkdir(exist_ok=True)

MODEL = "qwen2.5:72b"

# ── logging ────────────────────────────────────────────────────────────────────
ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
_log = logging.getLogger("queue")
_log.setLevel(logging.DEBUG)
_fh  = logging.FileHandler(LOG_DIR / f"queue_{ts_str}.log")
_sh  = logging.StreamHandler(sys.stdout)
for h in (_fh, _sh):
    h.setFormatter(logging.Formatter("%(asctime)s [QUEUE] %(levelname)s  %(message)s"))
_log.addHandler(_fh)
_log.addHandler(_sh)


# ══════════════════════════════════════════════════════════════════════════════
#  HEALTH CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def _load_trials(results_dir: Path, pattern: str = "trial_???.json") -> list:
    trials = []
    for p in sorted(results_dir.glob(pattern)):
        if "_raw" in p.name:
            continue
        try:
            trials.append(json.load(open(p)))
        except Exception:
            pass
    return trials


def health_exp1(arm: str) -> list[str]:
    issues = []
    tag   = MODEL.replace(":", "-").replace(".", "_")
    d     = EXPERIMENTS / "exp1_results" / tag / arm
    trials = _load_trials(d)
    if not trials:
        return [f"[EXP1/{arm}] No trial files found in {d}"]

    zero_calls  = [t for t in trials if t.get("policy_calls", 0) == 0]
    def4_rate   = sum(1 for t in trials if t.get("def4_strict")) / len(trials)

    if zero_calls:
        issues.append(f"[EXP1/{arm}] {len(zero_calls)} trials with 0 policy_calls — dispatch may be broken")
    if arm == "vulnerable" and def4_rate == 0 and len(trials) >= 10:
        issues.append(f"[EXP1/{arm}] Def4 rate is 0% over {len(trials)} trials — tc/probe broken?")
    if arm == "defended" and def4_rate > 0.5 and len(trials) >= 10:
        issues.append(f"[EXP1/{arm}] Def4 rate is {def4_rate:.0%} — defense not suppressing? Expected <20%")

    _log.info(f"[EXP1/{arm}] n={len(trials)} def4={def4_rate:.0%} zero_calls={len(zero_calls)}")
    return issues


def health_exp2() -> list[str]:
    issues = []
    tag   = MODEL.replace(":", "-").replace(".", "_")
    rates = {}
    for reg in ["direct", "staged", "null"]:
        d = EXPERIMENTS / "exp2_results" / tag / reg
        trials = _load_trials(d)
        if not trials:
            issues.append(f"[EXP2/{reg}] No trial files found")
            continue
        rate = sum(1 for t in trials if t.get("decomposed")) / len(trials)
        rates[reg] = rate
        _log.info(f"[EXP2/{reg}] n={len(trials)} decomp_rate={rate:.0%}")

    if len(rates) == 3:
        if rates.get("staged", 0) < rates.get("direct", 1):
            issues.append(f"[EXP2] staged decomp ({rates['staged']:.0%}) < direct ({rates['direct']:.0%}) — unexpected")
        if rates.get("null", 1) > 0.3:
            issues.append(f"[EXP2] null decomp rate {rates['null']:.0%} > 30% — null register not neutral")
    return issues


def health_exp5() -> list[str]:
    issues = []
    rates  = {}
    for v in ["full_chain", "as4_enforced", "as2_enforced", "as5_enforced"]:
        d = EXPERIMENTS / "exp5_results" / v
        trials = _load_trials(d)
        if not trials:
            issues.append(f"[EXP5/{v}] No trial files found")
            continue
        rate = sum(1 for t in trials if t.get("circuit_complete")) / len(trials)
        rates[v] = rate
        _log.info(f"[EXP5/{v}] n={len(trials)} circuit_rate={rate:.0%}")

    if "full_chain" in rates and rates["full_chain"] == 0:
        issues.append(f"[EXP5] full_chain circuit_rate=0% — agent not completing circuit at all")
    for v in ["as4_enforced", "as2_enforced"]:
        if rates.get(v, 1) > 0.2:
            issues.append(f"[EXP5/{v}] circuit_rate={rates[v]:.0%} > 20% — defense not working as expected")
    # as5_enforced should have a similar circuit rate to full_chain (AS5 alone is not sufficient)
    if "as5_enforced" in rates and "full_chain" in rates:
        delta = abs(rates["as5_enforced"] - rates["full_chain"])
        if delta > 0.3:
            issues.append(f"[EXP5/as5_enforced] circuit_rate={rates['as5_enforced']:.0%} "
                          f"differs from full_chain={rates['full_chain']:.0%} by {delta:.0%} — check AS5 gate")
    return issues


def health_exp6() -> list[str]:
    issues  = []
    cal_path = EXPERIMENTS / "exp6_results" / "phase1" / "calibration.json"
    if not cal_path.exists():
        return ["[EXP6] calibration.json not found — phase1 may not have completed"]
    try:
        cal    = json.load(open(cal_path))
        k_star = cal.get("k_star")
        if k_star is None:
            issues.append("[EXP6] k_star not set in calibration.json")
        elif not (1 <= k_star <= 10):
            issues.append(f"[EXP6] k_star={k_star} outside expected range [1,10]")
        else:
            _log.info(f"[EXP6] k_star={k_star} (valid)")
    except Exception as e:
        issues.append(f"[EXP6] Failed to parse calibration.json: {e}")
    return issues


def health_exp9() -> list[str]:
    issues = []
    for sweep in ["sweep_a", "sweep_b", "sweep_c", "sweep_d"]:
        p = EXPERIMENTS / "exp9_results" / f"{sweep}.json"
        if not p.exists():
            issues.append(f"[EXP9] {sweep}.json not found")
            continue
        try:
            data = json.load(open(p))
            _log.info(f"[EXP9/{sweep}] loaded {len(data.get('rows', []))} rows")
        except Exception as e:
            issues.append(f"[EXP9/{sweep}] parse error: {e}")
    return issues


def health_exp11() -> list[str]:
    issues = []
    p = EXPERIMENTS / "exp11_results" / "weight_sensitivity.json"
    if not p.exists():
        return ["[EXP11] weight_sensitivity.json not found — post-hoc analysis may have failed"]
    try:
        data    = json.load(open(p))
        profiles = data.get("profiles", {})
        _log.info(f"[EXP11] {len(profiles)} weight profiles analyzed")
        if len(profiles) < 5:
            issues.append(f"[EXP11] only {len(profiles)}/5 weight profiles found")
    except Exception as e:
        issues.append(f"[EXP11] parse error: {e}")
    return issues


def health_exp13() -> list[str]:
    issues = []
    for cond in ["vulnerable", "isolated", "hedgetuned", "both"]:
        d = EXPERIMENTS / "exp13_results" / cond
        trials = _load_trials(d)
        if not trials:
            continue
        rec_rate = sum(1 for t in trials if t.get("recovery_completed")) / len(trials)
        _log.info(f"[EXP13/{cond}] n={len(trials)} recovery={rec_rate:.0%}")
        if cond == "vulnerable" and rec_rate == 0 and len(trials) >= 5:
            issues.append(f"[EXP13/vulnerable] recovery_completed=0% — AMBR not changing at all")
    return issues


def health_exp14() -> list[str]:
    issues = []
    p = EXPERIMENTS / "exp14_results" / "taxonomy.json"
    if not p.exists():
        return ["[EXP14] taxonomy.json not found"]
    try:
        data = json.load(open(p))
        _log.info(f"[EXP14] taxonomy loaded: {len(data.get('fields', {}))} fields")
    except Exception as e:
        issues.append(f"[EXP14] parse error: {e}")
    return issues


HEALTH_CHECKS = {
    "exp1_vulnerable": lambda: health_exp1("vulnerable"),
    "exp1_defended":   lambda: health_exp1("defended"),
    "exp2":            health_exp2,
    "exp5":          health_exp5,
    "exp6":          health_exp6,
    "exp9":          health_exp9,
    "exp11":         health_exp11,
    "exp13":         health_exp13,
    "exp14":         health_exp14,
}


def run_health(name: str) -> bool:
    fn = HEALTH_CHECKS.get(name)
    if fn is None:
        return True
    issues = fn()
    if issues:
        _log.warning(f"Health check [{name}] — {len(issues)} issue(s):")
        for iss in issues:
            _log.warning(f"  !  {iss}")
        return False
    _log.info(f"Health check [{name}] — OK")
    return True


# ══════════════════════════════════════════════════════════════════════════════
#  EXPERIMENT RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_exp(name: str, cmd: list, log_file: Path) -> bool:
    _log.info(f"{'='*60}")
    _log.info(f"Starting: {name}")
    _log.info(f"Command:  {' '.join(str(c) for c in cmd)}")
    _log.info(f"Log:      {log_file}")
    _log.info(f"{'='*60}")

    start = time.time()
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            [str(PYTHON)] + [str(c) for c in cmd],
            cwd=str(MARCUS),
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
        while proc.poll() is None:
            time.sleep(300)
            elapsed = (time.time() - start) / 60
            _log.info(f"  [{name}] still running — {elapsed:.0f} min elapsed")

    elapsed = (time.time() - start) / 60
    rc = proc.returncode
    if rc == 0:
        _log.info(f"  [{name}] FINISHED OK in {elapsed:.0f} min")
    else:
        _log.error(f"  [{name}] FAILED (exit={rc}) after {elapsed:.0f} min — see {log_file}")
    return rc == 0


def run_parallel_group(group_name: str, items: list) -> tuple[bool, list]:
    """
    Launch a list of queue items simultaneously and wait for all to finish.
    Returns (all_ok, list_of_failed_names).
    Safe only when items have disjoint system resource usage (GPU / tc / policy_manager).
    """
    _log.info(f"{'='*60}")
    _log.info(f"[PARALLEL] Starting group: {group_name}")
    for it in items:
        _log.info(f"  >> {it['name']}: {' '.join(str(c) for c in it['cmd'])}")
    _log.info(f"{'='*60}")

    procs = []  # (name, proc, log_fh, start_time)
    for it in items:
        lf = open(it["log"], "w")
        proc = subprocess.Popen(
            [str(PYTHON)] + [str(c) for c in it["cmd"]],
            cwd=str(MARCUS),
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
        procs.append({"name": it["name"], "proc": proc, "lf": lf,
                       "start": time.time(), "item": it, "done": False, "ok": None})
        _log.info(f"  [{it['name']}] launched PID {proc.pid}")

    # Poll until all done
    while True:
        all_done = True
        for p in procs:
            if p["done"]:
                continue
            rc = p["proc"].poll()
            if rc is None:
                all_done = False
            else:
                elapsed = (time.time() - p["start"]) / 60
                p["lf"].close()
                p["done"] = True
                p["ok"]   = (rc == 0)
                if rc == 0:
                    _log.info(f"  [{p['name']}] FINISHED OK in {elapsed:.0f} min")
                else:
                    _log.error(f"  [{p['name']}] FAILED (exit={rc}) in {elapsed:.0f} min")
        if all_done:
            break
        time.sleep(60)
        for p in procs:
            if not p["done"]:
                elapsed = (time.time() - p["start"]) / 60
                _log.info(f"  [{p['name']}] still running — {elapsed:.0f} min")

    failed = [p["name"] for p in procs if not p["ok"]]
    _log.info(f"[PARALLEL] Group {group_name} complete — failed: {failed or 'none'}")
    return len(failed) == 0, failed


def wait_for_pid(pid: int):
    _log.info(f"Waiting for PID {pid} (Exp 1 vulnerable arm) to finish...")
    while True:
        try:
            os.kill(pid, 0)
            time.sleep(60)
        except ProcessLookupError:
            break
    _log.info(f"PID {pid} finished. Starting queue.")


# ══════════════════════════════════════════════════════════════════════════════
#  SPECIAL HOOKS
# ══════════════════════════════════════════════════════════════════════════════

def hook_post_exp1() -> bool:
    """
    After Exp 1 defended arm completes: re-apply def4_measurable threshold
    (≥2% Q-drop) to defended-arm trial JSONs, then re-run Exp 11
    (post-hoc Q-weight sensitivity, processes both arms).
    """
    _log.info("[HOOK] post-exp1 reanalysis: applying def4_measurable threshold to defended arm")
    ra_script = EXPERIMENTS / "reanalyze_def4.py"
    if not ra_script.exists():
        _log.error("[HOOK] reanalyze_def4.py not found — skipping")
        return True  # non-fatal

    try:
        r = subprocess.run(
            [sys.executable, str(ra_script), MODEL, "defended"],
            cwd=str(EXPERIMENTS.parent),
            capture_output=True, text=True, timeout=120)
        _log.info(f"[HOOK] reanalyze stdout: {r.stdout.strip()}")
        if r.returncode != 0:
            _log.warning(f"[HOOK] reanalyze exit {r.returncode}: {r.stderr.strip()}")
    except Exception as e:
        _log.error(f"[HOOK] reanalyze_def4 failed: {e}")
        return True  # non-fatal

    _log.info("[HOOK] re-running Exp 11 on updated exp1 results")
    try:
        r = subprocess.run(
            [sys.executable, str(EXPERIMENTS / "exp11_q_weight_sensitivity.py")],
            cwd=str(EXPERIMENTS.parent),
            capture_output=True, text=True, timeout=120)
        _log.info(f"[HOOK] exp11 stdout: {r.stdout.strip()}")
        if r.returncode != 0:
            _log.warning(f"[HOOK] exp11 exit {r.returncode}: {r.stderr.strip()}")
    except Exception as e:
        _log.error(f"[HOOK] exp11 re-run failed: {e}")
        return True  # non-fatal

    _log.info("[HOOK] post-exp1 cleanup complete")
    return True


def hook_kstar_update() -> bool:
    """
    After Exp 6 Phase 1: read calibration.json and patch HEDGETUNE_K_STAR
    in exp5 and exp13 if k†* differs from the current hard-coded value of 3.
    """
    _log.info("[HOOK] k†* auto-update starting")
    cal_path = EXPERIMENTS / "exp6_results" / "phase1" / "calibration.json"
    if not cal_path.exists():
        _log.warning("[HOOK] calibration.json not found — skipping k†* update")
        return True

    try:
        cal    = json.load(open(cal_path))
        k_star = cal.get("k_star")
    except Exception as e:
        _log.error(f"[HOOK] Failed to read calibration.json: {e}")
        return False

    if k_star is None:
        _log.warning("[HOOK] k_star missing from calibration.json — skipping")
        return True

    _log.info(f"[HOOK] k†* from calibration = {k_star}")

    targets = [
        EXPERIMENTS / "exp5_necessity_ablation.py",
        EXPERIMENTS / "exp7_adaptive_attacker.py",
        EXPERIMENTS / "exp8_defense_utility.py",
        EXPERIMENTS / "exp13_benign_recovery.py",
    ]
    for path in targets:
        try:
            text = path.read_text()
            # Find current HEDGETUNE_K_STAR value
            import re
            m = re.search(r"HEDGETUNE_K_STAR\s*=\s*(\d+)", text)
            if not m:
                _log.warning(f"[HOOK] HEDGETUNE_K_STAR not found in {path.name} — skipping")
                continue
            current = int(m.group(1))
            if current == k_star:
                _log.info(f"[HOOK] {path.name}: HEDGETUNE_K_STAR={current} already correct")
                continue
            new_text = re.sub(
                r"(HEDGETUNE_K_STAR\s*=\s*)\d+",
                f"\\g<1>{k_star}",
                text,
            )
            path.write_text(new_text)
            _log.info(f"[HOOK] {path.name}: HEDGETUNE_K_STAR {current} → {k_star}")
        except Exception as e:
            _log.error(f"[HOOK] Failed to patch {path.name}: {e}")
            return False

    _log.info("[HOOK] k†* update complete")
    return True


def hook_as5_sanity_check() -> bool:
    """
    Pre-flight AS5 sanity check: run 2 trials of as5_enforced variant and
    verify that ambr_dl_mean is still present in kpi_analyzer readback
    (i.e. AS5 does NOT break Type-P contamination readback).
    If the check fails, log a warning but do NOT abort — exp5 still runs.
    """
    _log.info("[HOOK] AS5 sanity check — verifying readback survives ML strip")

    out_dir = EXPERIMENTS / "exp5_results" / "as5_sanity"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "as5_sanity.log"

    # Run 2 trials of the as5_enforced variant
    cmd = ["experiments/exp5_necessity_ablation.py", MODEL, "as5_enforced"]
    # We can't easily run just 2 trials without patching the script, so instead
    # we check if any existing as5_enforced trial has contam_readback=True
    as5_dir = EXPERIMENTS / "exp5_results" / "as5_enforced"
    existing = list(sorted(as5_dir.glob("trial_???.json"))) if as5_dir.exists() else []

    if existing:
        # Check existing trials
        readback_seen = False
        for p in existing[:5]:  # check first 5
            try:
                t = json.load(open(p))
                if t.get("contam_readback"):
                    readback_seen = True
                    break
            except Exception:
                pass
        if readback_seen:
            _log.info("[HOOK] AS5 sanity OK — contam_readback=True seen in existing trials")
            return True
        else:
            _log.warning("[HOOK] AS5 sanity: no contam_readback=True in first 5 as5_enforced trials "
                         "— this is expected only if AS5 incorrectly blocks Type-P readback")
            _log.warning("[HOOK] Continuing anyway — exp5 will reveal full picture")
            return True

    # No existing trials — run a quick 2-trial check inline
    _log.info("[HOOK] No existing as5_enforced trials — running 2-trial pre-flight check")
    _log.info("[HOOK] Pre-flight will complete before exp5 full run")

    sanity_script = EXPERIMENTS / "_as5_sanity_run.py"
    sanity_code = f"""
import sys, json
sys.path.insert(0, "{str(MARCUS)}")
sys.path.insert(0, "{str(EXPERIMENTS)}")
from exp5_necessity_ablation import run_trial, MODEL_NAME
from probe.q_probe import QProbeHarness

MODEL_NAME = "{MODEL}"
probe = QProbeHarness(baseline_ambr_mbps=20.0)
readback_seen = False
for i in [1, 2]:
    try:
        trial, events = run_trial("as5_enforced", i, probe)
        if trial.get("contam_readback"):
            readback_seen = True
        print(f"Sanity trial {{i}}: contam_readback={{trial.get('contam_readback')}} policy_calls={{trial.get('policy_calls')}}")
    except Exception as e:
        print(f"Sanity trial {{i}} error: {{e}}")

print(f"Readback seen: {{readback_seen}}")
sys.exit(0 if readback_seen else 2)
"""
    sanity_script.write_text(sanity_code)

    try:
        proc = subprocess.run(
            [str(PYTHON), str(sanity_script)],
            cwd=str(MARCUS),
            capture_output=True,
            text=True,
            timeout=600,
        )
        _log.info(f"[HOOK] Sanity stdout: {proc.stdout.strip()}")
        if proc.returncode == 0:
            _log.info("[HOOK] AS5 sanity PASSED — readback survives ML strip")
        elif proc.returncode == 2:
            _log.warning("[HOOK] AS5 sanity WARNING — ambr_dl_mean not seen in readback "
                         "within 2 trials. Possible AS5 implementation issue. "
                         "Review exp5_necessity_ablation._make_as5_dispatch. Continuing.")
        else:
            _log.warning(f"[HOOK] AS5 sanity exited {proc.returncode} — {proc.stderr[:200]}")
    except subprocess.TimeoutExpired:
        _log.warning("[HOOK] AS5 sanity check timed out — skipping, exp5 runs anyway")
    except Exception as e:
        _log.warning(f"[HOOK] AS5 sanity check error: {e} — continuing")
    finally:
        if sanity_script.exists():
            sanity_script.unlink()

    return True  # never abort the queue based on sanity check alone


# ══════════════════════════════════════════════════════════════════════════════
#  QUEUE DEFINITION
# ══════════════════════════════════════════════════════════════════════════════

def build_queue() -> list[dict]:
    """
    Wave 1 queue — GPU-first ordering.

    GPU experiments run back-to-back with zero idle time between them.
    No-GPU experiments (exp9 sweeps, exp14) are deferred to after the full
    GPU chain completes, saving ~105 min of GPU idle time.

    Item types:
      - Subprocess:  {"name", "cmd", "log", "health"}
      - Hook:        {"name", "hook_fn"}
      - Parallel:    {"name", "parallel": [item, ...]}
          Members launch simultaneously; queue waits for all.
          Safe only when members use DISJOINT resources.

    Parallel groups:
      GROUP A — exp11_posthoc (file reads, zero system touch)
                || exp1_defended (GPU + tc + policy_manager)
      GROUP B — exp9_sweep_b (tc + iperf3 ONLY, no policy writes)
                || exp14_taxonomy (policy_manager + MongoDB, no tc)

    GPU chain timeline (starts after exp1_vulnerable finishes ~01:37 AM):
      group_A  → exp2_qwen → exp6_phase1 → exp5_qwen → exp13_qwen
      ≈ 3.1h  +   6.2h    +    5.2h     +   8.3h    +   8.3h  = ~31.1h GPU
    No-GPU tail (exp9 + exp14) ≈ 1.75h, runs after GPU chain.
    """
    return [
        # ════════════════════════════════════════════════════════════
        #  EXP 1 VULNERABLE — must finish before anything else
        # ════════════════════════════════════════════════════════════
        {
            "name":   "exp1_vulnerable",
            "cmd":    ["experiments/exp1_end_to_end.py", MODEL, "vulnerable"],
            "log":    LOG_DIR / "exp1_vulnerable.log",
            "health": "exp1_vulnerable",
        },

        # ════════════════════════════════════════════════════════════
        #  GPU CHAIN — runs continuously, no idle gaps
        # ════════════════════════════════════════════════════════════

        # GROUP A: exp11 (file-only) runs free alongside exp1_defended
        {
            "name": "group_A",
            "parallel": [
                {
                    "name":   "exp11_posthoc",
                    "cmd":    ["experiments/exp11_q_weight_sensitivity.py"],
                    "log":    LOG_DIR / "exp11_posthoc.log",
                    "health": "exp11",
                },
                {
                    "name":   "exp1_defended",
                    "cmd":    ["experiments/exp1_end_to_end.py", MODEL, "defended"],
                    "log":    LOG_DIR / "exp1_defended.log",
                    "health": "exp1_defended",
                },
            ],
        },
        # Post-exp1 cleanup: apply def4_measurable threshold to defended arm + re-run exp11
        {
            "name":    "hook_post_exp1",
            "hook_fn": hook_post_exp1,
        },
        # GPU immediately after exp1_defended — no gap
        {
            "name":   "exp2_qwen",
            "cmd":    ["experiments/exp2_register_trichotomy.py", MODEL],
            "log":    LOG_DIR / "exp2_qwen.log",
            "health": "exp2",
        },
        {
            "name":   "exp6_phase1",
            "cmd":    ["experiments/exp6_hedgetune_calibration.py", "phase1"],
            "log":    LOG_DIR / "exp6_phase1.log",
            "health": "exp6",
        },
        # k†* must be updated before exp5 and exp13 run
        {
            "name":    "kstar_update",
            "hook_fn": hook_kstar_update,
        },
        {
            "name":    "as5_sanity",
            "hook_fn": hook_as5_sanity_check,
        },
        {
            "name":   "exp5_qwen",
            "cmd":    ["experiments/exp5_necessity_ablation.py", MODEL],
            "log":    LOG_DIR / "exp5_qwen.log",
            "health": "exp5",
        },
        {
            "name":   "exp13_qwen",
            "cmd":    ["experiments/exp13_benign_recovery.py", MODEL],
            "log":    LOG_DIR / "exp13_qwen.log",
            "health": "exp13",
        },

        # ════════════════════════════════════════════════════════════
        #  NO-GPU TAIL — runs after GPU chain, ~1.75h total
        #  exp9 sweeps A/C/D use policy_manager (sequential)
        #  exp9 sweep_b uses tc only → parallel with exp14 (pm only)
        # ════════════════════════════════════════════════════════════
        {
            "name":   "exp9_sweep_a",
            "cmd":    ["experiments/exp9_parameter_sensitivity.py", "sweep_a"],
            "log":    LOG_DIR / "exp9_sweep_a.log",
            "health": None,
        },
        # GROUP B: tc-only sweep_b || policy_manager-only exp14
        {
            "name": "group_B",
            "parallel": [
                {
                    "name":   "exp9_sweep_b",
                    "cmd":    ["experiments/exp9_parameter_sensitivity.py", "sweep_b"],
                    "log":    LOG_DIR / "exp9_sweep_b.log",
                    "health": None,
                },
                {
                    "name":   "exp14_taxonomy",
                    "cmd":    ["experiments/exp14_contamination_taxonomy.py"],
                    "log":    LOG_DIR / "exp14_taxonomy.log",
                    "health": "exp14",
                },
            ],
        },
        {
            "name":   "exp9_sweep_c",
            "cmd":    ["experiments/exp9_parameter_sensitivity.py", "sweep_c"],
            "log":    LOG_DIR / "exp9_sweep_c.log",
            "health": None,
        },
        {
            "name":   "exp9_sweep_d",
            "cmd":    ["experiments/exp9_parameter_sensitivity.py", "sweep_d"],
            "log":    LOG_DIR / "exp9_sweep_d.log",
            "health": "exp9",
        },
    ]


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",      default=None,
                        help="Start from this experiment name (skip earlier ones)")
    parser.add_argument("--check-only", action="store_true",
                        help="Only run health checks, no experiment execution")
    parser.add_argument("--wait-pid",   type=int, default=None,
                        help="PID to wait for before starting queue (Exp 1 vulnerable arm)")
    args = parser.parse_args()

    queue = build_queue()

    if args.check_only:
        _log.info("Check-only mode — running health checks on existing results")
        for item in queue:
            if item.get("health"):
                run_health(item["health"])
        return

    # Find start position
    start_idx = 0
    if args.start:
        names = [q["name"] for q in queue]
        if args.start in names:
            start_idx = names.index(args.start)
            _log.info(f"Starting from: {args.start} (index {start_idx})")
        else:
            _log.error(f"Unknown experiment name '{args.start}'. Options: {names}")
            sys.exit(1)

    # Wait for a specific PID before proceeding (works with any --start position)
    if args.wait_pid:
        wait_for_pid(args.wait_pid)

    _log.info(f"Queue has {len(queue) - start_idx} items to run")

    failed = []
    for item in queue[start_idx:]:
        name = item["name"]
        _log.info(f"{'='*60}")
        _log.info(f"Next: {name}")

        # ── Hook items: run in-process ────────────────────────────────────────
        if "hook_fn" in item:
            ok = item["hook_fn"]()
            if not ok:
                failed.append(name)
                _log.error(f"  Hook [{name}] returned False — continuing")
            else:
                _log.info(f"  Hook [{name}] OK")
            _log.info("")
            continue

        # ── Parallel group: launch all members simultaneously ─────────────────
        if "parallel" in item:
            ok, grp_failed = run_parallel_group(name, item["parallel"])
            failed.extend(grp_failed)
            # Run health checks for each member after the group finishes
            for member in item["parallel"]:
                if member.get("health"):
                    hc_ok = run_health(member["health"])
                    if not hc_ok:
                        _log.warning(f"  Health issues for {member['name']} — review")
            _log.info("")
            continue

        # ── Sequential subprocess items ───────────────────────────────────────
        ok = run_exp(name, item["cmd"], item["log"])
        if not ok:
            failed.append(name)
            _log.error(f"  {name} failed — continuing to next item")

        if item.get("health"):
            hc_ok = run_health(item["health"])
            if not hc_ok:
                _log.warning(f"  Health check issues for {name} — review before proceeding")

        _log.info("")

    _log.info("=" * 60)
    _log.info("WAVE 1 QUEUE COMPLETE")
    _log.info(f"  Ran:    {len(queue) - start_idx} items")
    _log.info(f"  Failed: {len(failed)} — {failed if failed else 'none'}")
    _log.info("=" * 60)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
