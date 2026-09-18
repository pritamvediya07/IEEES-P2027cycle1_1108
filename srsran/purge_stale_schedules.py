#!/usr/bin/env python3
"""Remove the scheduled AMBR changes left over from earlier agent campaigns.

WHY THIS IS NECESSARY
---------------------
MonitoringManager uses a MongoDBJobStore, so every job an agent ever scheduled
persists across processes. 130 were live, many raising the internet slice by
50-150% at times spread over the next two days.

`_get_scheduler()` starts a BackgroundScheduler the moment any monitoring_manager
call is made, and agents do call it. A job coming due mid-session would change
the slice AMBR underneath a measurement with no corresponding policy write. The
E-FINAL run of 2026-08-24 was checked and was NOT affected — every R1 there is
explained by the agent's own committed writes — but that was luck of timing, not
a property of the setup.

The jobs are written to a JSON snapshot before removal so this is reversible.

    sudo .venv/bin/python srsran/purge_stale_schedules.py --dry-run
    sudo .venv/bin/python srsran/purge_stale_schedules.py
"""
from __future__ import annotations
import argparse, json, logging, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for n in ("COLLECTOR", "pymongo", "apscheduler", "MONITOR"):
    logging.getLogger(n).setLevel(logging.CRITICAL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import tools.monitoring_manager as M
    sched = M._get_scheduler()
    jobs = sched.get_jobs()
    snap = [{"id": j.id, "next_run_time": str(j.next_run_time),
             "kwargs": {k: str(v) for k, v in (getattr(j, "kwargs", {}) or {}).items()}}
            for j in jobs]

    out = ROOT / "srsran" / "results" / "stale_schedules_snapshot.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"captured_at": datetime.now(timezone.utc).isoformat(),
         "reason": "jobs left by earlier agent campaigns; removed so they cannot "
                   "fire mid-experiment and move AMBR with no matching policy write",
         "n": len(snap), "jobs": snap}, indent=2))
    print(f"  snapshot of {len(snap)} job(s) -> {out}")

    if a.dry_run:
        print("  dry run — nothing removed")
        return
    ok = err = 0
    for j in jobs:
        try:
            sched.remove_job(j.id); ok += 1
        except Exception as ex:                                  # noqa: BLE001
            err += 1; print(f"    could not remove {j.id}: {ex}")
    print(f"  removed {ok}, failed {err}, remaining {len(sched.get_jobs())}")


if __name__ == "__main__":
    main()
