"""DB cleaning utilities for Wave experiments.

Stale data in nwdaf_analytics.smf_metrics (ambr_dl_mean written by prior
runs) or leftover AMBR policy values in open5gs will contaminate new trials.

Safe pre-experiment reset:
  1. Reset Open5GS slice AMBR to baseline via policy_manager
  2. Drop / truncate smf_metrics collection (analytics DB only — not open5gs core data)
  3. Optionally drop old experiment result trial files for a clean re-run

Usage:
  from wave_experiments.shared.db_clean import pre_experiment_clean
  pre_experiment_clean(exp_name="exp1", reset_ambr=True, flush_analytics=True)

  # Or as CLI:
  python -m wave_experiments.shared.db_clean --all
  python -m wave_experiments.shared.db_clean --flush-analytics --reset-ambr
  python -m wave_experiments.shared.db_clean --flush-results exp1 exp6
"""
import sys, os, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from wave_experiments.config import (
    BASELINE_DL_AMBR_BPS, BASELINE_UL_AMBR_BPS, TARGET_SLICE,
    MONGO_URI_STANDARD, NWDAF_DB, RESULTS_DIR, CONTAMINATION_WAIT_SEC,
)


# ── 1. Reset Open5GS slice AMBR ───────────────────────────────────────────────
def reset_ambr(
    target_slice: str = TARGET_SLICE,
    dl_bps: int = BASELINE_DL_AMBR_BPS,
    ul_bps: int = BASELINE_UL_AMBR_BPS,
    wait: bool = True,
) -> dict:
    """Push baseline AMBR via policy_manager and wait for collector propagation."""
    from tools.policy_manager import PolicyManager
    pm  = PolicyManager()
    res = pm.apply_policy(target_slice, dl_bps, ul_bps)
    if wait:
        time.sleep(CONTAMINATION_WAIT_SEC)
    print(f"[DB-Clean] AMBR reset → {dl_bps/1e6:.0f} Mbps DL / {ul_bps/1e6:.0f} Mbps UL  result={res}")
    return res


# ── 2. Flush nwdaf_analytics.smf_metrics ─────────────────────────────────────
def flush_analytics(
    older_than_s: int | None = None,
    collection: str = "smf_metrics",
) -> int:
    """Delete analytics records.

    Args:
        older_than_s: if given, only delete records older than this many seconds
                      (uses the 'timestamp' field). If None, delete ALL records.
        collection:   target collection name (default smf_metrics).

    Returns:
        Number of documents deleted.
    """
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI_STANDARD, serverSelectionTimeoutMS=5000)
    db = client[NWDAF_DB]
    col = db[collection]

    if older_than_s is not None:
        import datetime
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=older_than_s)
        filt = {"timestamp": {"$lt": cutoff}}
    else:
        filt = {}

    count_before = col.count_documents({})
    result = col.delete_many(filt)
    count_after  = col.count_documents({})
    client.close()

    deleted = result.deleted_count
    print(
        f"[DB-Clean] Flushed {deleted} records from {NWDAF_DB}.{collection} "
        f"({count_before} → {count_after})"
    )
    return deleted


# ── 3. Flush stale trial result files ────────────────────────────────────────
def flush_results(*exp_ids: str, confirm: bool = True) -> None:
    """Delete all trial JSON files for specified experiment IDs.

    Args:
        *exp_ids:  e.g. "exp1", "exp6"  — all arms under that experiment cleared
        confirm:   if True, print what will be deleted and ask for confirmation
    """
    import shutil
    targets = []
    for eid in exp_ids:
        d = RESULTS_DIR / eid
        if d.exists():
            targets.append(d)

    if not targets:
        print("[DB-Clean] No result directories found for:", exp_ids)
        return

    if confirm:
        print("\n[DB-Clean] The following directories will be deleted:")
        for t in targets:
            files = list(t.rglob("trial_*.json"))
            print(f"  {t}  ({len(files)} trial files)")
        answer = input("Confirm deletion? [y/N] ").strip().lower()
        if answer != "y":
            print("[DB-Clean] Aborted.")
            return

    for t in targets:
        shutil.rmtree(t, ignore_errors=True)
        print(f"[DB-Clean] Deleted {t}")


# ── Master pre-experiment clean ───────────────────────────────────────────────
def pre_experiment_clean(
    exp_name: str,
    reset_ambr_flag: bool = True,
    flush_analytics_flag: bool = True,
    older_than_s: int | None = 3600,
    flush_results_flag: bool = False,
) -> None:
    """Run all cleaning steps before an experiment starts.

    Called automatically by the master runners (run_wave1 / run_wave2) and
    optionally at the start of each individual experiment's smoke test.

    Args:
        exp_name:             experiment being launched (used for logging)
        reset_ambr_flag:      push baseline AMBR via policy_manager
        flush_analytics_flag: delete stale analytics records
        older_than_s:         only delete analytics records older than this (None = all)
        flush_results_flag:   delete existing trial JSON files for this experiment
                              (only used for --rerun, never by default)
    """
    print(f"\n[DB-Clean] Pre-experiment clean for {exp_name}")

    if reset_ambr_flag:
        try:
            reset_ambr()
        except Exception as e:
            print(f"[DB-Clean] WARN: AMBR reset failed: {e}")

    if flush_analytics_flag:
        try:
            flush_analytics(older_than_s=older_than_s)
        except Exception as e:
            print(f"[DB-Clean] WARN: Analytics flush failed: {e}")

    if flush_results_flag:
        flush_results(exp_name, confirm=True)

    print(f"[DB-Clean] Done for {exp_name}")


# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="DB cleaning utilities for Wave experiments")
    ap.add_argument("--all",              action="store_true", help="Run all cleaning steps")
    ap.add_argument("--reset-ambr",       action="store_true", help="Reset AMBR to baseline")
    ap.add_argument("--flush-analytics",  action="store_true", help="Flush smf_metrics collection")
    ap.add_argument("--flush-all-analytics", action="store_true",
                    help="Flush ALL smf_metrics records (no age filter)")
    ap.add_argument("--older-than",       type=int, default=3600,
                    help="Only flush analytics older than N seconds (default 3600)")
    ap.add_argument("--flush-results",    nargs="+", metavar="EXP_ID",
                    help="Delete trial JSON files for these experiment IDs")
    ap.add_argument("--no-confirm",       action="store_true",
                    help="Skip confirmation prompts (use with care)")
    args = ap.parse_args()

    if args.all or args.reset_ambr:
        reset_ambr()

    if args.all or args.flush_analytics:
        older = None if args.flush_all_analytics else args.older_than
        flush_analytics(older_than_s=older)

    if args.flush_results:
        flush_results(*args.flush_results, confirm=not args.no_confirm)

    if not any([args.all, args.reset_ambr, args.flush_analytics,
                args.flush_all_analytics, args.flush_results]):
        ap.print_help()


if __name__ == "__main__":
    main()
