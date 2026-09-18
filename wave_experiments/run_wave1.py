"""Wave 1 master runner — executes all Wave 1 experiments in critical-path order.

Execution order (critical path enforced):
  0. Preflight gates G0–G4
  1. Exp 6 Phase 1 → produces kstar.json  [BLOCKS everything below]
  2. Exp 14 (taxonomy, no LLM, ~10 min)
  3. Exp 9  (sensitivity, no LLM, ~30 min)
  4. Exp 2  (register, 3×20=60 trials)
  5. Exp 3  (pilot, 30 trials)
  6. Exp 4  (full closed-loop, 30+20=50 trials)
  7. Exp 1  (end-to-end, 30+30=60 trials)  — uses k†*
  8. Exp 10 Phase A (re-extract Exp 1 latencies)
  9. Exp 10 Phases B+C (latency micro-bench)
 10. Exp 5  (ablation, 5×20=100 trials)    — uses k†*
 11. Exp 6 Phase 2 (enforcement, 30 trials)
 12. Exp 6 Phase 3 (benign, 30 trials)
 13. Exp 11 (Q-weight, post-hoc on Exp 1)
 14. Exp 13 (recovery, 4×20=80 trials)     — uses k†*

Each step runs a DB clean (reset AMBR + flush stale analytics) before starting.
A smoke test is run once at the start of the wave.

Usage:
  python run_wave1.py [--from STEP] [--skip STEP[,STEP...]] [--no-gates]
                      [--no-smoke] [--no-clean] [--rerun EXP_ID[,EXP_ID...]]
"""
import argparse, sys, os, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")

from wave_experiments.config import KSTAR_FILE, RESULTS_DIR
from wave_experiments.shared.results import print_banner, save_summary
from wave_experiments.shared.logging_setup import setup_logger, get_logger


STEP_ORDER = [
    "gates",
    "exp6p1",
    "exp14",
    "exp9",
    "exp2",
    "exp3",
    "exp4",
    "exp1",
    "exp10a",
    "exp10bc",
    "exp5",
    "exp6p2",
    "exp6p3",
    "exp11",
    "exp13",
]

STEP_LABELS = {
    "gates":   "Preflight gates G0–G4",
    "exp6p1":  "Exp 6 Phase 1 — HedgeTune calibration (k†*) [CRITICAL]",
    "exp14":   "Exp 14 — Contamination taxonomy (no LLM)",
    "exp9":    "Exp 9  — Architectural parameter sensitivity (no LLM)",
    "exp2":    "Exp 2  — Intent register (3×20=60 trials)",
    "exp3":    "Exp 3  — Simulated human-pilot ablation (30 trials)",
    "exp4":    "Exp 4  — Full closed-loop composition (30+20=50 trials)",
    "exp1":    "Exp 1  — End-to-end wireheading (30+30=60 trials)",
    "exp10a":  "Exp 10 Phase A — Latency re-extraction from Exp 1",
    "exp10bc": "Exp 10 Phases B+C — KPI + PM micro-benchmarks",
    "exp5":    "Exp 5  — Necessity & sufficiency ablation (5×20=100 trials)",
    "exp6p2":  "Exp 6 Phase 2 — Enforcement validation (30 trials)",
    "exp6p3":  "Exp 6 Phase 3 — Benign acceptance (30 trials)",
    "exp11":   "Exp 11 — Q-weight sensitivity (post-hoc, no LLM)",
    "exp13":   "Exp 13 — Benign recovery workload (4×20=80 trials)",
}

ESTIMATED_HOURS = {
    "gates":   0.5,
    "exp6p1":  8.0,
    "exp14":   0.2,
    "exp9":    0.5,
    "exp2":    6.0,
    "exp3":    4.0,
    "exp4":    7.0,
    "exp1":    8.0,
    "exp10a":  0.1,
    "exp10bc": 0.3,
    "exp5":   14.0,
    "exp6p2":  4.0,
    "exp6p3":  4.0,
    "exp11":   0.1,
    "exp13":  12.0,
}

# Steps that need k†* from exp6p1
NEEDS_KSTAR = {"exp1", "exp4", "exp5", "exp6p2", "exp6p3", "exp13"}

# Steps that need tc + probe (heavier DB impact → full clean)
NEEDS_PROBE = {"exp1", "exp4", "exp6p1", "exp6p2", "exp13"}


def _pre_step_clean(step: str, no_clean: bool) -> None:
    """Reset AMBR and flush stale analytics before each LLM experiment step."""
    if no_clean or step in ("gates", "exp9", "exp10a", "exp10bc", "exp11", "exp14"):
        return
    try:
        from wave_experiments.shared.db_clean import pre_experiment_clean
        # Flush analytics records older than 2 collector cycles to avoid cross-trial contamination
        pre_experiment_clean(
            exp_name=step,
            reset_ambr_flag=True,
            flush_analytics_flag=True,
            older_than_s=120,    # 2 min — anything older than that is stale
        )
    except Exception as e:
        print(f"[Wave1] WARN: DB clean before {step} failed: {e}")


def run_step(step: str, completed: dict, no_clean: bool = False,
             gate_from: str | None = None,
             gate_skip: set | None = None,
             gate_rerun: set | None = None) -> bool:
    """Run a single step with pre-step DB clean. Returns True on success."""
    log = get_logger()
    print_banner(STEP_LABELS[step])
    _pre_step_clean(step, no_clean)
    t_start = time.time()

    try:
        if step == "gates":
            from wave_experiments.preflight.gates import run_all_gates
            run_all_gates(
                abort_on_fail=True,
                from_gate=gate_from,
                skip_gates=gate_skip,
                rerun_gates=gate_rerun,
            )

        elif step == "exp6p1":
            from wave_experiments.exp6_hedgetune import run_phase1
            run_phase1()
            if not KSTAR_FILE.exists():
                raise RuntimeError("kstar.json not produced by Exp 6 Phase 1")

        elif step == "exp14":
            from wave_experiments.exp14_taxonomy import main as exp14_main
            exp14_main()

        elif step == "exp9":
            from wave_experiments.exp9_sensitivity import main as exp9_main
            exp9_main()

        elif step == "exp2":
            from wave_experiments.exp2_register import run_register, summarise
            from wave_experiments.config import EXP2_TRIALS_PER_REG
            all_r = {}
            for reg in ["direct", "staged", "null"]:
                all_r[reg] = run_register(reg, EXP2_TRIALS_PER_REG)
            summarise(all_r)

        elif step == "exp3":
            from wave_experiments.exp3_pilot import run_pilot
            run_pilot()

        elif step == "exp4":
            from wave_experiments.exp4_full_loop import run_exp4
            run_exp4(skip_smoke=True)   # smoke already ran at wave start

        elif step == "exp1":
            from wave_experiments.exp1_end_to_end import run_arm, summarise as exp1_summarise
            from wave_experiments.shared.defense import load_kstar
            from wave_experiments.config import EXP1_TRIALS_PER_ARM
            k = load_kstar()
            v_trials = run_arm("vulnerable", EXP1_TRIALS_PER_ARM)
            d_trials = run_arm("defended",   EXP1_TRIALS_PER_ARM, k_star=k)
            exp1_summarise(v_trials, d_trials, k)

        elif step == "exp10a":
            from wave_experiments.exp10_latency import extract_exp1_latencies
            extract_exp1_latencies()

        elif step == "exp10bc":
            from wave_experiments.exp10_latency import bench_kpi_analyzer, bench_policy_manager
            bench_kpi_analyzer()
            bench_policy_manager()

        elif step == "exp5":
            from wave_experiments.exp5_ablation import (
                run_variant, summarise as exp5_summarise, VARIANTS,
            )
            from wave_experiments.shared.defense import load_kstar
            from wave_experiments.config import EXP5_TRIALS_PER_VAR
            k = load_kstar()
            all_r = {v: run_variant(v, EXP5_TRIALS_PER_VAR, k) for v in VARIANTS}
            exp5_summarise(all_r, k)

        elif step == "exp6p2":
            from wave_experiments.exp6_hedgetune import run_phase2
            run_phase2()

        elif step == "exp6p3":
            from wave_experiments.exp6_hedgetune import run_phase3
            run_phase3()

        elif step == "exp11":
            from wave_experiments.exp11_qweight import main as exp11_main
            exp11_main()

        elif step == "exp13":
            from wave_experiments.exp13_recovery import run_exp13
            run_exp13()

        elapsed = (time.time() - t_start) / 3600
        completed[step] = {"status": "ok", "elapsed_h": round(elapsed, 2)}
        log.info(f"\n[Wave1] DONE {step} in {elapsed:.2f} h")
        return True

    except Exception as e:
        import traceback
        elapsed = (time.time() - t_start) / 3600
        completed[step] = {"status": "FAILED", "error": str(e), "elapsed_h": round(elapsed, 2)}
        log.error(f"\n[Wave1] FAILED {step}: {e}")
        log.debug(traceback.format_exc())
        return False


def main():
    ap = argparse.ArgumentParser(
        description="Wave 1 master runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Resume examples:
  --auto-resume                        # read progress.json, continue from last incomplete step
  --from exp2                          # start from exp2 regardless of progress.json
  --only exp6p1                        # run exactly one step then exit
  --skip exp9,exp14                    # skip these steps entirely
  --gates-from G1                      # start gates from G1 (G0 already passed)
  --rerun-gate G1                      # force re-run G1 even if it passed
  --rerun exp2,exp5                    # delete result dirs and re-run (asks confirmation)
""")
    ap.add_argument("--from",         dest="from_step", default=None,
                    help="Start from this step (overrides --auto-resume)")
    ap.add_argument("--auto-resume",  action="store_true",
                    help="Read progress.json and continue from first incomplete step")
    ap.add_argument("--only",         dest="only_step", default=None,
                    help="Run exactly this one step then exit")
    ap.add_argument("--skip",         default="",
                    help="Comma-separated steps to skip")
    ap.add_argument("--no-gates",     action="store_true",
                    help="Skip the gates step entirely")
    ap.add_argument("--no-smoke",     action="store_true",
                    help="Skip opening smoke test")
    ap.add_argument("--no-clean",     action="store_true",
                    help="Skip pre-step DB clean (NOT recommended)")
    ap.add_argument("--rerun",        default="",
                    help="Delete and re-run these exp result dirs (comma-separated)")
    # Gate-level resume controls
    ap.add_argument("--gates-from",   default=None, metavar="GN",
                    help="Start gates from this gate ID, e.g. G1")
    ap.add_argument("--rerun-gate",   default="",
                    help="Force re-run these gates even if passed, e.g. G1,G2")
    ap.add_argument("--skip-gate",    default="",
                    help="Skip these specific gates, e.g. G3,G4")
    args = ap.parse_args()

    setup_logger("wave1_run", RESULTS_DIR)
    log = get_logger()

    from wave_experiments.shared.checkpoint import (
        next_wave_step, summarise_resume, wave_progress,
    )

    skip_set = set(s.strip() for s in args.skip.split(",") if s.strip())
    if args.no_gates:
        skip_set.add("gates")

    # ── Determine start step ──────────────────────────────────────────────────
    from_idx = 0

    if args.only_step:
        # Single-step mode: run exactly one step
        if args.only_step not in STEP_ORDER:
            log.error(f"Unknown step '{args.only_step}'. Valid: {STEP_ORDER}")
            sys.exit(1)
        from_idx = STEP_ORDER.index(args.only_step)
        # Limit step_order to just this one step
        _only = args.only_step
    else:
        _only = None

    if args.auto_resume and not args.from_step and not args.only_step:
        nxt = next_wave_step(STEP_ORDER, wave=1)
        if nxt is None:
            log.info("[Wave1] All steps complete per progress.json. Nothing to do.")
            summarise_resume(STEP_ORDER, wave=1)
            sys.exit(0)
        log.info(f"[Wave1] --auto-resume: continuing from '{nxt}'")
        summarise_resume(STEP_ORDER, wave=1)
        from_idx = STEP_ORDER.index(nxt)
    elif args.from_step:
        if args.from_step not in STEP_ORDER:
            log.error(f"Unknown step '{args.from_step}'. Valid: {STEP_ORDER}")
            sys.exit(1)
        from_idx = STEP_ORDER.index(args.from_step)

    # Gate resume params
    gate_from  = args.gates_from or None
    gate_skip  = set(s.strip() for s in args.skip_gate.split(",")  if s.strip())
    gate_rerun = set(s.strip() for s in args.rerun_gate.split(",") if s.strip())

    # Optional: delete result dirs for specified experiments before re-running
    if args.rerun:
        rerun_ids = [s.strip() for s in args.rerun.split(",") if s.strip()]
        from wave_experiments.shared.db_clean import flush_results
        flush_results(*rerun_ids, confirm=True)

    total_est = sum(ESTIMATED_HOURS[s] for s in STEP_ORDER[from_idx:] if s not in skip_set)
    print_banner(f"Wave 1 Master Runner  (~{total_est:.0f} h estimated)")
    log.info(f"  Model: {os.environ['OLLAMA_MODEL']}")
    log.info(f"  Steps: {STEP_ORDER[from_idx:]}")
    log.info(f"  Skip:  {skip_set or 'none'}")
    log.info(f"\n  Step schedule:")
    for s in STEP_ORDER[from_idx:]:
        skip_marker = " [SKIP]" if s in skip_set else ""
        log.info(f"    {STEP_LABELS[s]}{skip_marker}  (~{ESTIMATED_HOURS[s]:.1f} h)")

    # ── Opening smoke test ────────────────────────────────────────────────────
    if not args.no_smoke:
        from wave_experiments.shared.smoke_test import run_smoke_test
        smoke = run_smoke_test("wave1_start", probe=False)
        if not smoke["passed"]:
            log.error("[Wave1] Opening smoke test FAILED — fix the issues above before running.")
            log.error("        Re-run with --no-smoke to skip (not recommended).")
            sys.exit(1)

    # ── Initial DB clean ──────────────────────────────────────────────────────
    if not args.no_clean:
        from wave_experiments.shared.db_clean import pre_experiment_clean
        pre_experiment_clean("wave1_start", reset_ambr_flag=True,
                             flush_analytics_flag=True, older_than_s=None)

    wave_t0   = time.time()
    # Seed completed from existing progress so --auto-resume context is correct
    completed = {k: v for k, v in wave_progress(wave=1).items()}

    active_steps = [_only] if _only else STEP_ORDER[from_idx:]

    for step in active_steps:
        if step in skip_set:
            log.info(f"\n[Wave1] Skipping {step}")
            completed[step] = {"status": "skipped"}
            continue

        if step in NEEDS_KSTAR and "exp6p1" not in completed:
            log.warning(f"[Wave1] {step} needs k†* — exp6p1 not run. Using DEFAULT_KSTAR.")

        ok = run_step(
            step, completed,
            no_clean=args.no_clean,
            gate_from=gate_from,
            gate_skip=gate_skip,
            gate_rerun=gate_rerun,
        )

        if not ok and step == "exp6p1":
            log.error("[Wave1] FATAL: Exp 6 Phase 1 failed — k†* unavailable. Aborting.")
            break

        # Save running status after each step so we can resume on crash
        save_summary({
            "wave": 1, "model": os.environ.get("OLLAMA_MODEL"),
            "steps_so_far": completed,
            "elapsed_h": round((time.time() - wave_t0) / 3600, 2),
        }, "wave1_run", "progress.json")

    total_h = (time.time() - wave_t0) / 3600
    summary = {
        "wave": 1,
        "model": os.environ.get("OLLAMA_MODEL"),
        "total_elapsed_h": round(total_h, 2),
        "steps": completed,
    }
    save_summary(summary, "wave1_run")

    log.info(f"\n{'='*60}")
    log.info(f"[Wave1] Complete in {total_h:.2f} h")
    for s, r in completed.items():
        marker = "OK" if r["status"] == "ok" else r["status"].upper()
        elapsed = r.get("elapsed_h", "?")
        log.info(f"  {s:<12} {marker:<8} {elapsed} h")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
