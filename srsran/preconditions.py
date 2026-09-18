#!/usr/bin/env python3
"""Preconditions every srsRAN experiment must satisfy before recording data.

WHY THIS EXISTS
---------------
mongod died twice during this campaign when the disk filled. Both times the
visible symptom pointed somewhere else entirely — the second time UEs reached
RRC Connected and were then released, which reads as a RAN or QoS fault. It is
an AMF registration reject (5GMM cause 7, "5GS services not allowed") caused by
an empty subscriber database.

A silent core-dependency failure that lets a run complete partially is exactly
how confidently wrong data gets recorded. Check loudly, up front, and refuse.
"""
from __future__ import annotations

import shutil
import subprocess


def _sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=30)


def check_mongod() -> tuple[bool, str]:
    """mongod alive AND the subscriber collection non-empty."""
    ping = _sh("mongosh --quiet --eval 'db.adminCommand({ping:1}).ok' 2>/dev/null")
    if "1" not in ping.stdout:
        return False, "mongod not responding to ping — Open5GS will reject every registration"
    n = _sh("mongosh open5gs --quiet --eval 'db.subscribers.countDocuments({})' 2>/dev/null")
    try:
        count = int(n.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, f"could not count subscribers (got {n.stdout.strip()!r})"
    if count == 0:
        return False, "subscriber database is EMPTY — every UE will get Registration reject [7]"
    return True, f"mongod OK, {count} subscribers provisioned"


def check_disk(min_gb: float = 5.0) -> tuple[bool, str]:
    """Free space. This is what killed mongod, so check the cause not just the effect."""
    free_gb = shutil.disk_usage("/").free / 2**30
    if free_gb < min_gb:
        return False, f"only {free_gb:.1f} GB free — mongod will crash mid-run (need {min_gb})"
    return True, f"disk OK, {free_gb:.1f} GB free"


def check_core() -> tuple[bool, str]:
    """The Open5GS NFs an experiment cannot proceed without."""
    missing = [nf for nf in ("amf", "smf", "upf", "nrf")
               if _sh(f"pgrep -f 'open5gs-{nf}d' >/dev/null").returncode != 0]
    if missing:
        return False, f"Open5GS NFs not running: {', '.join(missing)}"
    return True, "Open5GS AMF/SMF/UPF/NRF running"


def check_collector(max_age_s: float = 30.0) -> tuple[bool, str]:
    """The analytics must be FRESH, i.e. a collector daemon is actually running.

    WHY THIS EXISTS
    ---------------
    E3, E7 and an initial slice of E9 were run with no collector daemon. Nothing
    in the agent's tool path calls collect_once, so the analytics store was
    frozen at its last manual tick and kpi_analyzer returned the same stale value
    to every trial. The contamination channel — the entire subject of the paper —
    was closed for the whole campaign, and nothing in the harness noticed,
    because a stale read looks exactly like a fresh one.

    A reachable mongod is NOT sufficient. The check has to be recency.
    """
    from datetime import datetime, timezone
    try:
        import sys as _s
        from pathlib import Path as _P
        _s.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from config.db import get_nwdaf_db
        d = get_nwdaf_db()["smf_metrics"].find_one({}, sort=[("timestamp", -1)])
    except Exception as ex:                                   # noqa: BLE001
        return False, f"could not read analytics: {ex}"
    if not d or not d.get("timestamp"):
        return False, "no analytics records at all — start the collector daemon"
    ts = d["timestamp"]
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    if age > max_age_s:
        return False, (f"newest analytics record is {age:.0f}s old (limit {max_age_s:.0f}s). "
                       "The collector daemon is not running, so the agent would read a frozen "
                       "value and the contamination channel would be closed. Start it with:  "
                       "setsid nohup .venv/bin/python -m collector.collector "
                       "> /tmp/srsran/collector.log 2>&1 &")
    return True, f"collector live, newest record {age:.0f}s old"


def assert_ready(*, need_core: bool = True, need_collector: bool = False) -> None:
    """Run every check and abort the experiment if any fails."""
    checks = [("disk", check_disk), ("mongod", check_mongod)]
    if need_collector:
        checks.append(("collector", check_collector))
    if need_core:
        checks.append(("open5gs", check_core))
    failures = []
    print("  preconditions:")
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as ex:                       # noqa: BLE001
            ok, msg = False, f"check raised {ex!r}"
        print(f"    [{'OK ' if ok else 'FAIL'}] {name}: {msg}")
        if not ok:
            failures.append(f"{name}: {msg}")
    if failures:
        raise SystemExit(
            "\n  ABORTING before any data is recorded. Failed preconditions:\n    - "
            + "\n    - ".join(failures)
            + "\n\n  Fix these first; a partial run here produces plausible-looking wrong data.\n")
    print()


if __name__ == "__main__":
    assert_ready()
    print("  all preconditions satisfied")
