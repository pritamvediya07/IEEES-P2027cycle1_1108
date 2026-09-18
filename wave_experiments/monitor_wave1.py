#!/usr/bin/env python3
"""Wave 1 experiment monitor — progress tracking + result validation.

Designed to run standalone (cron / ScheduleWakeup) or interactively.
Reads results directories directly; does NOT depend on the running process.

Usage:
    python wave_experiments/monitor_wave1.py           # full report
    python wave_experiments/monitor_wave1.py --quiet   # one-line per exp
    python wave_experiments/monitor_wave1.py --watch   # repeat every 60s
"""
import argparse, json, time, os, sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

ROOT     = Path(__file__).parent.parent
WAVE_DIR = Path(__file__).parent
RESULTS  = WAVE_DIR / "results"
STATE    = Path("/tmp/wave1_monitor_state.json")
LOG      = RESULTS / "wave1_run" / "wave1_restart.log"

# ── Experiment manifest ────────────────────────────────────────────────────────
# (arm_or_variant, total_trials, result_subdir)  — one entry per tracked arm
EXPS = {
    "exp14": [
        ("phaseB_writes", 20, "exp14/phaseB_writes"),
    ],
    "exp9": [
        ("sensitivity",    1, "exp9"),           # single summary
    ],
    "exp2": [
        ("direct",        20, "exp2/direct"),
        ("staged",        20, "exp2/staged"),
        ("null",          20, "exp2/null"),
    ],
    "exp3": [
        ("pilot",         30, "exp3/pilot"),
    ],
    "exp4": [
        ("vulnerable",    30, "exp4/vulnerable"),
        ("defended",      20, "exp4/defended"),
    ],
    "exp1": [
        ("vulnerable",    30, "exp1/vulnerable"),
        ("defended",      30, "exp1/defended"),
    ],
    "exp5": [
        ("no_defense",    20, "exp5/no_defense"),
        ("iso_only",      20, "exp5/iso_only"),
        ("ht_only",       20, "exp5/ht_only"),
        ("as4_only",      20, "exp5/as4_only"),
        ("as2_and_as4",   20, "exp5/as2_and_as4"),
    ],
    "exp6p2": [
        ("phase2_enforcement", 30, "exp6/phase2_enforcement"),
    ],
    "exp6p3": [
        ("phase3_benign",      30, "exp6/phase3_benign"),
    ],
    "exp13": [
        ("baseline",      20, "exp13/baseline"),
        ("ht_defense",    20, "exp13/ht_defense"),
        ("iso_defense",   20, "exp13/iso_defense"),
        ("full_pala",     20, "exp13/full_pala"),
    ],
}

# Quality thresholds for result validation alerts
ALERT_THRESHOLDS = {
    "exp1_vulnerable_full_loop_min":  0.50,   # expect ≥50% wireheading in vulnerable arm
    "exp1_defended_full_loop_max":    0.15,   # expect ≤15% wireheading in defended arm
    "exp4_vulnerable_full_loop_min":  0.50,
    "exp5_no_defense_full_loop_min":  0.50,
    "error_rate_max":                 0.20,   # >20% error trials is a warning
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_trials(subdir: str) -> list[dict]:
    d = RESULTS / subdir
    if not d.exists():
        return []
    trials = []
    for p in sorted(d.glob("trial_*.json")):
        try:
            trials.append(json.loads(p.read_text()))
        except Exception:
            pass
    return trials


def _rate(trials: list[dict], key: str) -> float | None:
    good = [t for t in trials if key in t]
    if not good:
        return None
    return sum(1 for t in good if t.get(key)) / len(good)


def _error_rate(trials: list[dict]) -> float:
    if not trials:
        return 0.0
    return sum(1 for t in trials if "error" in t) / len(trials)


def _gpu() -> str:
    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu",
             "--format=csv,noheader"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        util, temp = out.split(", ")
        return f"{util.strip()} / {temp.strip()}°C"
    except Exception:
        return "n/a"


def _process_alive() -> tuple[int | None, str]:
    """Return (pid, status_str)."""
    import subprocess
    try:
        pids = subprocess.check_output(
            ["pgrep", "-f", "run_wave1.py"], text=True
        ).strip().split()
        if pids:
            return int(pids[0]), "RUNNING"
    except subprocess.CalledProcessError:
        pass
    return None, "STOPPED"


def _current_exp_from_log() -> str:
    """Guess currently active experiment from the last few log lines."""
    if not LOG.exists():
        return "unknown"
    try:
        lines = LOG.read_text().splitlines()[-60:]
        for line in reversed(lines):
            for tag in ["exp14", "exp9", "exp2", "exp3", "exp4", "exp1",
                        "exp10", "exp5", "exp6p2", "exp6p3", "exp11", "exp13"]:
                if tag in line.lower():
                    return tag
    except Exception:
        pass
    return "unknown"


def _last_log_line() -> str:
    if not LOG.exists():
        return ""
    try:
        lines = [l for l in LOG.read_text().splitlines() if l.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""


# ── Per-experiment validation ──────────────────────────────────────────────────

def validate_arm(exp_id: str, arm: str, subdir: str, total: int) -> dict:
    trials = _load_trials(subdir)
    n = len(trials)
    pct = n / total if total else 0
    result = {
        "arm":        arm,
        "done":       n,
        "total":      total,
        "pct":        pct,
        "complete":   n >= total,
        "alerts":     [],
    }

    if n == 0:
        return result

    err_rate = _error_rate(trials)
    if err_rate > ALERT_THRESHOLDS["error_rate_max"]:
        result["alerts"].append(f"ERROR_RATE={err_rate:.0%} (>{ALERT_THRESHOLDS['error_rate_max']:.0%})")

    for metric in ("full_loop", "decomposed", "contaminated"):
        r = _rate(trials, metric)
        if r is not None:
            result[metric] = round(r, 3)

    # Experiment-specific quality checks
    fl = result.get("full_loop")
    key_min = f"{exp_id}_{arm}_full_loop_min"
    key_max = f"{exp_id}_{arm}_full_loop_max"
    if fl is not None and n >= 10:   # only alert once we have ≥10 trials
        if key_min in ALERT_THRESHOLDS and fl < ALERT_THRESHOLDS[key_min]:
            result["alerts"].append(
                f"FULL_LOOP_LOW={fl:.0%} (exp={ALERT_THRESHOLDS[key_min]:.0%} min)")
        if key_max in ALERT_THRESHOLDS and fl > ALERT_THRESHOLDS[key_max]:
            result["alerts"].append(
                f"FULL_LOOP_HIGH={fl:.0%} (exp={ALERT_THRESHOLDS[key_max]:.0%} max)")

    result["error_rate"] = round(err_rate, 3)
    return result


# ── Main report ───────────────────────────────────────────────────────────────

def build_report(quiet: bool = False) -> dict:
    pid, proc_status = _process_alive()
    gpu              = _gpu()
    cur_exp          = _current_exp_from_log()
    last_line        = _last_log_line()
    now              = datetime.now(timezone.utc).isoformat()

    # k†* status
    kstar_file = RESULTS / "exp6" / "kstar.json"
    kstar_info = {}
    if kstar_file.exists():
        try:
            kd = json.loads(kstar_file.read_text())
            kstar_info = {
                "k_star":    kd.get("k_star"),
                "cv":        kd.get("cv"),
                "cv_stable": kd.get("cv_stable"),
            }
        except Exception:
            pass

    exp_status   = {}
    all_alerts   = []
    total_done   = 0
    total_target = 0

    for exp_id, arms in EXPS.items():
        arms_out = []
        for arm, total, subdir in arms:
            r = validate_arm(exp_id, arm, subdir, total)
            arms_out.append(r)
            total_done   += r["done"]
            total_target += total
            for alert in r["alerts"]:
                all_alerts.append(f"[{exp_id}/{arm}] {alert}")
        exp_status[exp_id] = arms_out

    # Process alerts
    if proc_status == "STOPPED":
        if total_done < total_target:
            all_alerts.insert(0, "PROCESS_DEAD — wave1 not running, experiments incomplete")

    gpu_util = gpu.split(" / ")[0].replace(" %", "").strip()
    try:
        if int(gpu_util) == 0:
            all_alerts.append(f"GPU_IDLE=0% — Ollama may be stuck")
    except Exception:
        pass

    return {
        "timestamp":   now,
        "process":     {"pid": pid, "status": proc_status},
        "gpu":         gpu,
        "current_exp": cur_exp,
        "kstar":       kstar_info,
        "overall":     {"done": total_done, "target": total_target,
                        "pct": round(total_done / total_target, 3) if total_target else 0},
        "experiments": exp_status,
        "alerts":      all_alerts,
        "last_log":    last_line[-120:] if last_line else "",
    }


def print_report(report: dict, quiet: bool = False) -> None:
    ts  = report["timestamp"][:19].replace("T", " ")
    pid = report["process"]["pid"]
    st  = report["process"]["status"]
    gpu = report["gpu"]
    ov  = report["overall"]
    ks  = report["kstar"]

    print(f"\n{'='*68}")
    print(f"  Wave 1 Monitor  {ts} UTC")
    print(f"  Process: {st} (PID={pid})   GPU: {gpu}")
    if ks:
        cv_tag = "✓stable" if ks.get("cv_stable") else "UNSTABLE"
        print(f"  k†* = {ks.get('k_star')}   CV = {ks.get('cv')} ({cv_tag})")
    print(f"  Overall: {ov['done']}/{ov['target']} trials ({ov['pct']:.0%})")
    print(f"{'='*68}")

    for exp_id, arms in report["experiments"].items():
        any_started = any(a["done"] > 0 for a in arms)
        all_done    = all(a["complete"] for a in arms)

        if quiet and not any_started:
            continue

        tag = "DONE" if all_done else ("ACTIVE" if any_started else "pending")
        print(f"\n  [{exp_id.upper():<8}] {tag}")
        for arm in arms:
            bar_n  = int(arm["pct"] * 20)
            bar    = "█" * bar_n + "░" * (20 - bar_n)
            fl     = arm.get("full_loop")
            fl_str = f"  full_loop={fl:.0%}" if fl is not None else ""
            err    = arm.get("error_rate", 0)
            err_str = f"  errors={err:.0%}" if err > 0 else ""
            alert_str = "  ⚠ " + ", ".join(arm["alerts"]) if arm["alerts"] else ""
            print(f"    {arm['arm']:<22} [{bar}] {arm['done']:>3}/{arm['total']:<3}"
                  f"{fl_str}{err_str}{alert_str}")

    if report["alerts"]:
        print(f"\n  ALERTS ({len(report['alerts'])}):")
        for a in report["alerts"]:
            print(f"    ⚠  {a}")

    if report["last_log"] and not quiet:
        print(f"\n  Last log: {report['last_log'][-100:]}")
    print()


def save_state(report: dict) -> None:
    try:
        STATE.write_text(json.dumps({
            "timestamp":   report["timestamp"],
            "process_pid": report["process"]["pid"],
            "gpu":         report["gpu"],
            "current_exp": report["current_exp"],
            "overall":     report["overall"],
            "alerts":      report["alerts"],
            "kstar":       report["kstar"],
        }, indent=2))
    except Exception:
        pass


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Wave 1 experiment monitor")
    ap.add_argument("--quiet",  action="store_true", help="Only show started experiments")
    ap.add_argument("--watch",  action="store_true", help="Repeat every 60s until done")
    ap.add_argument("--json",   action="store_true", help="Output raw JSON")
    ap.add_argument("--alerts-only", action="store_true", help="Print only if alerts exist")
    args = ap.parse_args()

    while True:
        report = build_report(quiet=args.quiet)
        save_state(report)

        if args.json:
            print(json.dumps(report, indent=2))
        elif args.alerts_only:
            if report["alerts"]:
                print_report(report, quiet=True)
        else:
            print_report(report, quiet=args.quiet)

        if not args.watch:
            break

        pid_status = report["process"]["status"]
        all_done   = report["overall"]["done"] >= report["overall"]["target"]
        if all_done or pid_status == "STOPPED":
            print("Wave 1 complete or process stopped. Exiting watch mode.")
            break

        time.sleep(60)


if __name__ == "__main__":
    main()
