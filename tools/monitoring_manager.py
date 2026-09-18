# tools/monitoring_manager.py
# Tool 5 — Monitoring Manager
#
# Time-based policy scheduling — exactly what Use Case 2 in the paper demonstrates.
# "Increase the data rate for the 'streaming' slice by 20% from 4:27 PM to 4:30 PM on weekdays."
#
# Uses APScheduler (Advanced Python Scheduler) to:
#   1. Schedule a policy apply job at the start time
#   2. Schedule a policy revert job at the end time
#   3. Persist schedules to MongoDB so they survive restarts
#   4. Expose a list/cancel API for the agent to manage existing schedules
#
# How it connects to Use Case 2 (paper Figure 5):
#   - Agent calls schedule_policy_change() with the slice, AMBR delta, time window
#   - At 4:27 PM: PolicyManager.apply_policy() fires → AMBR increases
#   - At 4:30 PM: revert job fires → AMBR returns to original
#   - Figure 5 shows the data rate spike exactly in that window

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from pydantic import BaseModel, Field

from config.db import get_client, get_nwdaf_db
from config.settings import MONGO_URI, NWDAF_DB, NWDAF_SCHEDULED_TASKS

log = logging.getLogger(__name__)

# Day-of-week mapping (APScheduler cron uses 0=mon,1=tue,...,6=sun)
DAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
    "WEEKDAYS": "0-4", "WEEKEND": "5-6", "ALL": "*",
}


# ── models ────────────────────────────────────────────────────────────────────

class ScheduleRequest(BaseModel):
    slice_name:     str   = Field(..., description="DNN / slice name, e.g. 'streaming'")
    action:         str   = Field("increase_ambr",
                                  description="'increase_ambr' | 'decrease_ambr' | 'custom'")
    delta_pct:      float = Field(..., description="Percentage change, e.g. 20.0 for +20%")
    start_time:     str   = Field(..., description="HH:MM in 24h or 12h, e.g. '16:27' or '4:27 PM'")
    end_time:       str   = Field(..., description="HH:MM, e.g. '16:30'")
    days:           list[str] = Field(
        default=["MON", "TUE", "WED", "THU", "FRI"],
        description="Days to apply. Use 'WEEKDAYS', 'WEEKEND', 'ALL', or explicit days.",
    )
    target_imsi:    str | None = Field(None)


class ScheduleResult(BaseModel):
    success:      bool
    message:      str
    job_id_apply: str | None = None
    job_id_revert: str | None = None
    schedule_doc_id: str | None = None


# ── scheduler singleton ────────────────────────────────────────────────────────

_scheduler_lock    = threading.Lock()
_scheduler_instance: BackgroundScheduler | None = None


def _get_scheduler() -> BackgroundScheduler:
    global _scheduler_instance
    with _scheduler_lock:
        if _scheduler_instance is None or not _scheduler_instance.running:
            jobstore = MongoDBJobStore(
                database=NWDAF_DB,
                collection="apscheduler_jobs",
                client=get_client(),
            )
            _scheduler_instance = BackgroundScheduler(
                jobstores={"default": jobstore},
                timezone="UTC",
            )
            _scheduler_instance.start()
            log.info("APScheduler started with MongoDB job store")
    return _scheduler_instance


# ── main class ────────────────────────────────────────────────────────────────

class MonitoringManager:
    """
    Schedule time-based policy actions.
    This is the engine behind Use Case 2 in the PALA paper.
    """

    def schedule_policy_change(
        self,
        slice_name:   str,
        action:       str,
        delta_pct:    float,
        start_time:   str,
        end_time:     str,
        days:         list[str] | None = None,
        target_imsi:  str | None = None,
    ) -> dict[str, Any]:
        """
        Schedule a time-windowed policy change.

        Example call from agent (Use Case 2):
          schedule_policy_change(
              slice_name="streaming",
              action="increase_ambr",
              delta_pct=20.0,
              start_time="16:27",
              end_time="16:30",
              days=["MON","TUE","WED","THU","FRI"],
          )
        """
        if days is None:
            days = ["MON", "TUE", "WED", "THU", "FRI"]

        req = ScheduleRequest(
            slice_name=slice_name,
            action=action,
            delta_pct=delta_pct,
            start_time=start_time,
            end_time=end_time,
            days=days,
            target_imsi=target_imsi,
        )

        try:
            start_h, start_m = _parse_time(req.start_time)
            end_h,   end_m   = _parse_time(req.end_time)
            day_expr         = _days_to_cron(req.days)

            # Store the schedule document first so jobs can reference it
            schedule_doc = {
                "slice_name":   req.slice_name,
                "action":       req.action,
                "delta_pct":    req.delta_pct,
                "start_time":   req.start_time,
                "end_time":     req.end_time,
                "days":         req.days,
                "target_imsi":  req.target_imsi,
                "created_at":   datetime.now(timezone.utc),
                "active":       True,
            }
            db        = get_nwdaf_db()
            insert_id = str(db[NWDAF_SCHEDULED_TASKS].insert_one(schedule_doc).inserted_id)

            sched = _get_scheduler()

            # ── apply job ──────────────────────────────────────────────────
            apply_id = f"apply_{insert_id}"
            sched.add_job(
                func=_run_policy_change,
                trigger=CronTrigger(
                    day_of_week=day_expr,
                    hour=start_h,
                    minute=start_m,
                ),
                id=apply_id,
                replace_existing=True,
                kwargs={
                    "slice_name":  req.slice_name,
                    "delta_pct":   req.delta_pct,
                    "is_revert":   False,
                    "target_imsi": req.target_imsi,
                    "doc_id":      insert_id,
                },
            )

            # ── revert job ─────────────────────────────────────────────────
            revert_id = f"revert_{insert_id}"
            sched.add_job(
                func=_run_policy_change,
                trigger=CronTrigger(
                    day_of_week=day_expr,
                    hour=end_h,
                    minute=end_m,
                ),
                id=revert_id,
                replace_existing=True,
                kwargs={
                    "slice_name":  req.slice_name,
                    "delta_pct":   -req.delta_pct,   # negative = revert
                    "is_revert":   True,
                    "target_imsi": req.target_imsi,
                    "doc_id":      insert_id,
                },
            )

            log.info(
                "Scheduled policy change: slice=%s delta=%+.0f%% %s-%s days=%s",
                req.slice_name, req.delta_pct, req.start_time, req.end_time, req.days,
            )

            return ScheduleResult(
                success=True,
                message=(
                    f"Policy change scheduled for slice '{req.slice_name}': "
                    # Use the validated request, not the raw parameters. Pydantic
                    # coerces delta_pct="20" to 20.0 inside `req`, but the local
                    # name still holds the string, and formatting a str with
                    # `.0f` raises. The agent supplies tool arguments as free
                    # JSON and does pass numbers as strings, so this fired on
                    # every such call and lost the whole scheduling result.
                    f"{req.action} by {req.delta_pct:.0f}% from {req.start_time} "
                    f"to {req.end_time} on {', '.join(req.days)}."
                ),
                job_id_apply=apply_id,
                job_id_revert=revert_id,
                schedule_doc_id=insert_id,
            ).model_dump()

        except Exception as exc:
            log.error("schedule_policy_change failed: %s", exc, exc_info=True)
            return ScheduleResult(success=False, message=str(exc)).model_dump()

    def list_schedules(self) -> dict[str, Any]:
        """Return all active scheduled tasks."""
        try:
            db   = get_nwdaf_db()
            docs = list(db[NWDAF_SCHEDULED_TASKS].find(
                {"active": True},
                {"_id": 0, "slice_name": 1, "action": 1, "delta_pct": 1,
                 "start_time": 1, "end_time": 1, "days": 1, "created_at": 1},
            ))
            return {"schedules": docs, "count": len(docs)}
        except Exception as exc:
            return {"error": str(exc)}

    def cancel_schedule(self, schedule_doc_id: str) -> dict[str, Any]:
        """Cancel an existing scheduled job pair."""
        try:
            sched = _get_scheduler()
            for prefix in ("apply_", "revert_"):
                job_id = f"{prefix}{schedule_doc_id}"
                try:
                    sched.remove_job(job_id)
                    log.info("Removed job %s", job_id)
                except Exception:
                    pass  # job may have already run

            db = get_nwdaf_db()
            db[NWDAF_SCHEDULED_TASKS].update_one(
                {"_id": schedule_doc_id},
                {"$set": {"active": False, "cancelled_at": datetime.now(timezone.utc)}},
            )
            return {"success": True, "message": f"Schedule {schedule_doc_id} cancelled."}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def monitor_metric(
        self,
        metric:     str,
        threshold:  float,
        interval_s: int = 30,
        action:     str = "alert",
    ) -> dict[str, Any]:
        """
        Set up a recurring monitor that fires when a metric crosses a threshold.
        Useful for reactive policies: "alert me if UE count exceeds 8".
        """
        try:
            sched  = _get_scheduler()
            job_id = f"monitor_{metric}_{int(datetime.now().timestamp())}"

            sched.add_job(
                func=_check_metric_threshold,
                trigger="interval",
                seconds=interval_s,
                id=job_id,
                replace_existing=False,
                kwargs={"metric": metric, "threshold": threshold, "action": action},
            )
            return {
                "success":  True,
                "message":  f"Monitoring '{metric}' every {interval_s}s. "
                            f"Alert when > {threshold}.",
                "job_id":   job_id,
            }
        except Exception as exc:
            return {"success": False, "message": str(exc)}


# ── job callbacks (run by APScheduler in background threads) ──────────────────

def _run_policy_change(
    slice_name:  str,
    delta_pct:   float,
    is_revert:   bool,
    target_imsi: str | None,
    doc_id:      str,
) -> None:
    """
    Callback executed by APScheduler at the scheduled time.
    Reads the current AMBR, computes the new value, and applies it.
    """
    from tools.policy_manager import PolicyManager

    try:
        pm      = PolicyManager()
        current = pm.get_current_policy(slice_name)

        subs = current.get("subscribers", [])
        if not subs:
            log.warning("No subscribers found for slice %s at schedule time", slice_name)
            return

        for sub in subs:
            if target_imsi and sub["imsi"] != target_imsi:
                continue

            # current AMBR in Mbps (Open5GS unit 3 = Mbps)
            cur_dl_mbps = sub.get("dl_ambr", 0) or 0
            cur_ul_mbps = sub.get("ul_ambr", 0) or 0

            # If reverting and we stored the original, restore it
            # Otherwise apply the delta
            factor  = 1 + (delta_pct / 100.0)
            new_dl  = int(cur_dl_mbps * factor) * 1_000_000  # back to bps
            new_ul  = int(cur_ul_mbps * factor) * 1_000_000

            # Clamp to safe defaults if stored value was 0
            if new_dl < 1_000_000:
                new_dl = int(200 * factor) * 1_000_000
            if new_ul < 1_000_000:
                new_ul = int(100 * factor) * 1_000_000

            result = pm.apply_policy(
                target_slice=slice_name,
                new_dl_ambr=new_dl,
                new_ul_ambr=new_ul,
                target_imsi=sub["imsi"] if target_imsi else None,
                reason=f"Scheduled {'revert' if is_revert else 'apply'} "
                       f"{delta_pct:+.0f}% on slice {slice_name}",
            )
            log.info("Scheduled job result: %s", result.get("message"))
            break  # applied per-slice; all subs updated inside policy_manager

    except Exception as exc:
        log.error("Scheduled policy job failed: %s", exc, exc_info=True)


def _check_metric_threshold(metric: str, threshold: float, action: str) -> None:
    """Periodic metric monitor callback."""
    from tools.kpi_analyzer import KPIAnalyzer
    try:
        result = KPIAnalyzer().analyze(metric, n_samples=5, run_ml=False)
        stats  = result.get("stats", {})
        latest = stats.get("mean", 0)
        if latest > threshold:
            log.warning(
                "[MONITOR] %s = %.4f exceeds threshold %.4f — action=%s",
                metric, latest, threshold, action,
            )
            # Future: trigger alert or auto-policy here
    except Exception as exc:
        log.warning("Monitor check failed: %s", exc)


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_time(time_str: str) -> tuple[int, int]:
    """
    Parse a time string into (hour_24, minute). Handles:
      - 'HH:MM'            → (H, M)
      - '4:27 PM'          → (16, 27)
      - 'NOW'              → current local HH:MM
      - ISO datetime       → '2023-02-20T14:30' or '2023-02-20T14' → (14, 30)
      - Unix timestamp     → integer seconds since epoch → local HH:MM
    """
    from datetime import datetime as _dt
    import re as _re

    s = str(time_str).strip()

    # "NOW" → current time
    if s.upper() == "NOW":
        now = _dt.now()
        return now.hour, now.minute

    # Unix epoch (all-digit string, or large integer)
    if _re.fullmatch(r"\d{9,10}", s):
        t = _dt.fromtimestamp(int(s))
        return t.hour, t.minute

    # ISO datetime: '2023-02-20T14:30', '2023-02-20T14:30:00', '2023-02-20T14'
    iso = _re.match(r"\d{4}-\d{2}-\d{2}[T ]\s*(\d{1,2})(?::(\d{2}))?", s)
    if iso:
        h = int(iso.group(1))
        m = int(iso.group(2)) if iso.group(2) else 0
        return h % 24, m

    # Relative offsets like '+1H', '1H', '+30M' — treat as current time + offset
    offset_match = _re.fullmatch(r"[+]?(\d+)\s*([HhMm])", s)
    if offset_match:
        val = int(offset_match.group(1))
        unit = offset_match.group(2).upper()
        from datetime import datetime as _dt2, timedelta as _td
        if unit == "H":
            target = _dt2.now() + _td(hours=val)
        else:
            target = _dt2.now() + _td(minutes=val)
        return target.hour, target.minute

    # 'NEVER' / 'INDEFINITE' / 'ALWAYS' / 'END_OF_DAY' etc. — use end-of-business day
    keywords = {"NEVER", "INDEFINITE", "ALWAYS", "END", "ONGOING", "PERMANENT"}
    if s.upper() in keywords or s.upper().startswith("END_"):
        return 23, 59

    # Standard 'HH:MM' / '4:27 PM' / '4 PM'
    try:
        su = s.upper()
        pm = "PM" in su
        am = "AM" in su
        su = su.replace("PM", "").replace("AM", "").strip()
        parts = su.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        if pm and h != 12:
            h += 12
        if am and h == 12:
            h = 0
        return h % 24, m
    except (ValueError, IndexError):
        # Unrecognised format — use current time as safe fallback
        from datetime import datetime as _dt3
        now = _dt3.now()
        log.warning("_parse_time: unrecognised format %r — using current time", time_str)
        return now.hour, now.minute


def _days_to_cron(days: list[str]) -> str:
    """
    Convert day list to APScheduler cron day_of_week expression.
    ['MON','WED','FRI'] → '0,2,4'
    ['WEEKDAYS']        → '0-4'
    """
    if not days:
        return "*"
    nums = []
    for d in days:
        d = d.upper()
        val = DAY_MAP.get(d)
        if val is None:
            continue
        if isinstance(val, str):
            return val    # 'WEEKDAYS' etc already a cron expression
        nums.append(str(val))
    return ",".join(nums) if nums else "*"
