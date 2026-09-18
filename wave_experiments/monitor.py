#!/usr/bin/env python3
"""Wave 1+2 live monitor — refreshes every 30 s by default.

Usage:
  python wave_experiments/monitor.py          # default 30s refresh
  python wave_experiments/monitor.py -n 10   # 10s refresh
  python wave_experiments/monitor.py -1      # single snapshot, then exit
"""
import argparse, json, os, sys, time, subprocess, re
from pathlib import Path
from datetime import datetime, timezone

MARCUS = Path(__file__).parent.parent
sys.path.insert(0, str(MARCUS))

WAVE_ROOT   = MARCUS / "wave_experiments"
RESULTS_DIR = WAVE_ROOT / "results"
MASTER_LOG  = RESULTS_DIR / "wave1_run" / "wave1_master.log"
WAVE1_PID   = RESULTS_DIR / "wave1_run" / "wave1.pid"
KSTAR_FILE  = RESULTS_DIR / "exp6" / "kstar.json"

STEP_ORDER = [
    "gates", "exp6p1", "exp14", "exp9", "exp2", "exp3",
    "exp4", "exp1", "exp10a", "exp10bc", "exp5",
    "exp6p2", "exp6p3", "exp11", "exp13",
]
STEP_LABELS = {
    "gates":   "Preflight G0-G4",
    "exp6p1":  "Exp6 Ph1 k†* cal [CRIT]",
    "exp14":   "Exp14 Taxonomy",
    "exp9":    "Exp9  Sensitivity",
    "exp2":    "Exp2  Register",
    "exp3":    "Exp3  Pilot",
    "exp4":    "Exp4  Full-Loop",
    "exp1":    "Exp1  End-to-End",
    "exp10a":  "Exp10 Latency(A)",
    "exp10bc": "Exp10 Latency(BC)",
    "exp5":    "Exp5  Ablation",
    "exp6p2":  "Exp6 Ph2 Enforce",
    "exp6p3":  "Exp6 Ph3 Benign",
    "exp11":   "Exp11 Q-Weight",
    "exp13":   "Exp13 Recovery",
}
STEP_EST_H = {
    "gates":0.5,"exp6p1":8,"exp14":0.2,"exp9":0.5,"exp2":6,"exp3":4,
    "exp4":7,"exp1":8,"exp10a":0.1,"exp10bc":0.3,"exp5":14,
    "exp6p2":4,"exp6p3":4,"exp11":0.1,"exp13":12,
}


# ── helpers ───────────────────────────────────────────────────────────────────
def _gpu() -> dict:
    try:
        out = subprocess.check_output(
            ["nvidia-smi","--query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"], text=True, timeout=4
        ).strip().split(",")
        return {
            "used_mb":  int(out[0].strip()),
            "free_mb":  int(out[1].strip()),
            "util_pct": int(out[2].strip()),
            "temp_c":   int(out[3].strip()),
        }
    except Exception:
        return {}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _wave1_pid() -> int | None:
    if WAVE1_PID.exists():
        try:
            return int(WAVE1_PID.read_text().strip())
        except Exception:
            pass
    return None


def _progress_from_log() -> dict:
    """Parse master log to determine current step and recent activity."""
    if not MASTER_LOG.exists():
        return {}

    lines = MASTER_LOG.read_text(errors="replace").splitlines()
    done, current, start_ts = [], None, None

    for line in lines:
        # Detect step completion
        m = re.search(r"\[Wave1\] DONE (\w+) in ([\d.]+) h", line)
        if m:
            done.append({"step": m.group(1), "elapsed_h": float(m.group(2))})

        # Detect step start via banner
        for step in STEP_ORDER:
            label = STEP_LABELS.get(step, step)
            if label[:12] in line and "====" in line:
                current = step

        # Detect smoke ALL PASSED → gates started
        if "ALL PASSED" in line and current is None:
            current = "gates"

        # Detect failure
        m2 = re.search(r"\[Wave1\] FAILED (\w+)", line)
        if m2:
            done.append({"step": m2.group(1), "elapsed_h": 0, "failed": True})

    done_names = {d["step"] for d in done}
    if current and current in done_names:
        # Advance to next undone step
        idx = STEP_ORDER.index(current) + 1 if current in STEP_ORDER else 0
        for s in STEP_ORDER[idx:]:
            if s not in done_names:
                current = s
                break

    return {"done": done, "done_names": done_names, "current": current, "all_lines": lines}


def _trial_stats(exp_id: str) -> dict:
    """Count trials and compute live rates from the JSONL log."""
    jsonl = RESULTS_DIR / exp_id / f"{exp_id}_trials.jsonl"
    if not jsonl.exists():
        return {}
    lines = jsonl.read_text(errors="replace").splitlines()
    records = []
    for ln in lines:
        try:
            records.append(json.loads(ln))
        except Exception:
            pass
    if not records:
        return {}

    n = len(records)
    fl  = sum(1 for r in records if r.get("full_loop"))
    suc = sum(1 for r in records if r.get("success_claimed"))
    rej = sum(r.get("h_budget_rejections", 0) for r in records)
    dec = sum(1 for r in records if r.get("decomposed"))
    con = sum(1 for r in records if r.get("contaminated"))
    return {
        "n": n,
        "full_loop_rate":    round(fl  / n, 3) if n else 0,
        "success_rate":      round(suc / n, 3) if n else 0,
        "decomposed_rate":   round(dec / n, 3) if n else 0,
        "contaminated_rate": round(con / n, 3) if n else 0,
        "total_h_rejections": rej,
    }


def _recent_log_lines(n: int = 12) -> list[str]:
    if not MASTER_LOG.exists():
        return []
    lines = MASTER_LOG.read_text(errors="replace").splitlines()
    # Strip ANSI, keep last n non-empty lines
    clean = [re.sub(r"\x1b\[[0-9;]*m", "", l) for l in lines if l.strip()]
    return clean[-n:]


def _kstar() -> str:
    if KSTAR_FILE.exists():
        try:
            d = json.loads(KSTAR_FILE.read_text())
            return f"k†*={d.get('k_star','?')}  CV={d.get('cv','?')}"
        except Exception:
            pass
    return "not yet produced"


# ── rendering ─────────────────────────────────────────────────────────────────
BAR_W = 30

def _bar(rate: float, width: int = BAR_W) -> str:
    filled = int(rate * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {rate:.0%}"


def _render(refresh_s: int) -> None:
    os.system("clear")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    prog = _progress_from_log()
    gpu  = _gpu()
    pid  = _wave1_pid()
    alive = _pid_alive(pid) if pid else False

    print("╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║  WAVE 1 MONITOR   {now}   refresh={refresh_s}s  ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")

    # Process status
    status_str = f"PID {pid} {'🟢 RUNNING' if alive else '🔴 STOPPED'}" if pid else "not started"
    print(f"║  Process : {status_str:<59}║")

    # GPU
    if gpu:
        used_gb = gpu['used_mb'] / 1024
        free_gb = gpu['free_mb'] / 1024
        total_gb = (gpu['used_mb'] + gpu['free_mb']) / 1024
        gpu_bar = _bar(gpu['used_mb'] / (gpu['used_mb'] + gpu['free_mb']), 20)
        print(f"║  GPU     : {gpu['util_pct']:3d}% util  {gpu['temp_c']}°C  "
              f"VRAM {used_gb:.1f}/{total_gb:.0f}GB {gpu_bar:<30}  ║")
    else:
        print("║  GPU     : unavailable" + " " * 48 + "║")

    # k†*
    print(f"║  k†*     : {_kstar():<59}║")
    print("╠══════════════════════════════════════════════════════════════════════╣")

    # Step progress
    done_names = prog.get("done_names", set())
    current    = prog.get("current")
    done_list  = prog.get("done", [])

    n_done = len([s for s in STEP_ORDER if s in done_names])
    n_total = len(STEP_ORDER)
    pct = n_done / n_total
    overall_bar = _bar(pct, 30)
    print(f"║  Steps   : {n_done}/{n_total} {overall_bar:<40}      ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")

    for step in STEP_ORDER:
        label = STEP_LABELS.get(step, step)
        est_h = STEP_EST_H.get(step, 0)
        if step in done_names:
            elapsed = next((d.get("elapsed_h", 0) for d in done_list if d["step"] == step), 0)
            failed  = next((d.get("failed") for d in done_list if d["step"] == step), False)
            icon    = "✗ FAIL" if failed else f"✓ {elapsed:.1f}h"
            marker  = f" {icon}"
        elif step == current:
            # Count trials in progress
            st = _trial_stats(step)
            trial_str = f" trial {st.get('n','?')}" if st.get("n") else ""
            marker = f"► RUNNING{trial_str}"
        else:
            marker = f"  (est {est_h:.0f}h)"

        # Pad label to width
        row = f"  {label:<24} {marker}"
        print(f"║  {row:<68}║")

    print("╠══════════════════════════════════════════════════════════════════════╣")

    # Live trial stats for the current experiment
    if current:
        st = _trial_stats(current)
        if st and st.get("n", 0) > 0:
            print(f"║  [{current}] n={st['n']}  full_loop={_bar(st['full_loop_rate'],15)}", end="")
            print(f"  decomp={st['decomposed_rate']:.0%}" + " " * 10 + "║")
            print(f"║           success={st['success_rate']:.0%}  contam={st['contaminated_rate']:.0%}"
                  f"  h_rej={st['total_h_rejections']}" + " " * 25 + "║")
        else:
            print(f"║  [{current}] no trial data yet" + " " * 42 + "║")

    print("╠══════════════════════════════════════════════════════════════════════╣")
    print("║  RECENT LOG                                                          ║")

    recent = _recent_log_lines(10)
    for line in recent:
        # Clip to 68 chars
        clean = line.strip()
        # Strip log prefix timestamps if present
        clean = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[[\w]+\] ", "", clean)
        clean = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[MCP\] \w+\s+", "", clean)
        print(f"║  {clean[:68]:<68}║")

    print("╚══════════════════════════════════════════════════════════════════════╝")
    print(f"  Log: {MASTER_LOG}  (Ctrl+C to exit)")


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--refresh", type=int, default=30,
                    help="Refresh interval in seconds (default 30)")
    ap.add_argument("-1", "--once", action="store_true",
                    help="Single snapshot then exit")
    args = ap.parse_args()

    if args.once:
        _render(args.refresh)
        return

    try:
        while True:
            _render(args.refresh)
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\n[Monitor] Exited.")


if __name__ == "__main__":
    main()
