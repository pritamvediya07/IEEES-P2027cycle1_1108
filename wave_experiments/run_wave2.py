"""Wave 2 master runner — executes Exp 7 and Exp 8 with smoke test + DB clean.

Requires k†* from Wave 1 Exp 6 Phase 1. Run AFTER Wave 1 is complete.

Experiments:
  Exp 7 — Adaptive attacker robustness   (5×4×10 = 200 trials, ~28 h)
  Exp 8 — Defense utility on benign work (5×4×10 = 200 trials, ~28 h)

Each experiment gets:
  - Opening smoke test
  - Pre-experiment DB clean (AMBR reset + analytics flush)
  - Per-trial JSONL + individual trial JSON logging
  - Experiment-level .log file

Usage:
  python run_wave2.py [--exp {7,8,all}] [--reps N] [--no-smoke] [--no-clean]
"""
import argparse, sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")

from wave_experiments.config import KSTAR_FILE, RESULTS_DIR
from wave_experiments.shared.results import print_banner, save_summary
from wave_experiments.shared.logging_setup import setup_logger, get_logger


def main():
    ap = argparse.ArgumentParser(description="Wave 2 master runner")
    ap.add_argument("--exp",      choices=["7", "8", "all"], default="all")
    ap.add_argument("--reps",     type=int, default=None)
    ap.add_argument("--no-smoke", action="store_true")
    ap.add_argument("--no-clean", action="store_true")
    args = ap.parse_args()

    setup_logger("wave2_run", RESULTS_DIR)
    log = get_logger()

    if not KSTAR_FILE.exists():
        log.warning("[Wave2] kstar.json not found — run Wave 1 exp6p1 first. Using DEFAULT_KSTAR=3.")
    else:
        import json
        k_star = json.loads(KSTAR_FILE.read_text()).get("k_star")
        log.info(f"[Wave2] k†* = {k_star}  (from {KSTAR_FILE})")

    print_banner(f"Wave 2 Master Runner  (~56 h estimated)  model={os.environ['OLLAMA_MODEL']}")

    # ── Opening smoke test ────────────────────────────────────────────────────
    if not args.no_smoke:
        from wave_experiments.shared.smoke_test import run_smoke_test
        smoke = run_smoke_test("wave2_start", probe=False)
        if not smoke["passed"]:
            log.error("[Wave2] Opening smoke test FAILED — fix issues before running.")
            sys.exit(1)

    # ── Initial DB clean ──────────────────────────────────────────────────────
    if not args.no_clean:
        from wave_experiments.shared.db_clean import pre_experiment_clean
        pre_experiment_clean("wave2_start", reset_ambr_flag=True,
                             flush_analytics_flag=True, older_than_s=None)

    wave_t0   = time.time()
    completed = {}

    if args.exp in ("7", "all"):
        print_banner("Exp 7 — Adaptive attacker robustness")
        if not args.no_clean:
            from wave_experiments.shared.db_clean import pre_experiment_clean
            pre_experiment_clean("exp7", reset_ambr_flag=True,
                                 flush_analytics_flag=True, older_than_s=120)
        from wave_experiments.exp7_adaptive import run_exp7
        from wave_experiments.config import EXP7_REPS
        reps = args.reps if args.reps else EXP7_REPS
        try:
            t0 = time.time()
            run_exp7(n_reps=reps)
            elapsed_h = round((time.time() - t0) / 3600, 2)
            completed["exp7"] = {"status": "ok", "elapsed_h": elapsed_h}
            log.info(f"[Wave2] Exp 7 DONE in {elapsed_h} h")
        except Exception as e:
            import traceback
            completed["exp7"] = {"status": "FAILED", "error": str(e)}
            log.error(f"[Wave2] Exp 7 FAILED: {e}")
            log.debug(traceback.format_exc())

    if args.exp in ("8", "all"):
        print_banner("Exp 8 — Defense utility on benign workloads")
        if not args.no_clean:
            from wave_experiments.shared.db_clean import pre_experiment_clean
            pre_experiment_clean("exp8", reset_ambr_flag=True,
                                 flush_analytics_flag=True, older_than_s=120)
        from wave_experiments.exp8_utility import run_exp8
        from wave_experiments.config import EXP8_REPS
        reps = args.reps if args.reps else EXP8_REPS
        try:
            t0 = time.time()
            run_exp8(n_reps=reps)
            elapsed_h = round((time.time() - t0) / 3600, 2)
            completed["exp8"] = {"status": "ok", "elapsed_h": elapsed_h}
            log.info(f"[Wave2] Exp 8 DONE in {elapsed_h} h")
        except Exception as e:
            import traceback
            completed["exp8"] = {"status": "FAILED", "error": str(e)}
            log.error(f"[Wave2] Exp 8 FAILED: {e}")
            log.debug(traceback.format_exc())

    total_h = (time.time() - wave_t0) / 3600
    summary = {
        "wave": 2,
        "model": os.environ.get("OLLAMA_MODEL"),
        "total_elapsed_h": round(total_h, 2),
        "steps": completed,
    }
    save_summary(summary, "wave2_run")

    log.info(f"\n{'='*60}")
    log.info(f"[Wave2] Complete in {total_h:.2f} h")
    for s, r in completed.items():
        marker = "OK" if r.get("status") == "ok" else r.get("status", "?").upper()
        log.info(f"  {s:<8} {marker:<8} {r.get('elapsed_h', '?')} h")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
