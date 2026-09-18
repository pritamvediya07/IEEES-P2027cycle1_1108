# tools/feasibility_checker.py
# Tool 2 — Feasibility Checker
#
# The agent ALWAYS calls this before any action tool (Policy Manager,
# Session Manager, Monitoring Manager).  It acts as the first safety gate.
#
# Checks performed:
#   1. AMBR bounds — requested value within 3GPP limits
#   2. Current load — does the network have headroom for this change?
#   3. Session existence — does the targeted UE / slice actually exist?
#   4. Cooldown — has a conflicting policy been applied in the last N seconds?

import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from pydantic import BaseModel, Field

from config.db import get_nwdaf_db, get_open5gs_db
from config.settings import (
    MAX_DL_AMBR_BPS, MAX_UL_AMBR_BPS, MIN_AMBR_BPS,
    NWDAF_SMF_METRICS, NWDAF_SCHEDULED_TASKS,
    KNOWN_SLICES, MAX_UE_CAPACITY,
)

log = logging.getLogger(__name__)

POLICY_COOLDOWN_SEC = 30   # block re-applying same policy within 30 s


# ── request / response models ─────────────────────────────────────────────────

class FeasibilityRequest(BaseModel):
    action:        str = Field(..., description="e.g. 'increase_ambr', 'terminate_session', 'apply_policy'")
    target_slice:  str | None = Field(None, description="DNN / slice name, e.g. 'internet'")
    target_imsi:   str | None = Field(None, description="Full IMSI, e.g. '999700000000001'")
    new_dl_ambr:   int | None = Field(None, description="Requested DL AMBR in bps")
    new_ul_ambr:   int | None = Field(None, description="Requested UL AMBR in bps")
    extra_params:  dict = Field(default_factory=dict)


class FeasibilityResult(BaseModel):
    allowed:   bool
    reason:    str
    warnings:  list[str] = Field(default_factory=list)
    current_load_pct: float | None = None


# ── main class ────────────────────────────────────────────────────────────────

class FeasibilityChecker:
    """
    Pre-flight check for every intent action.
    Returns allowed=True only when all checks pass.
    """

    def check(
        self,
        action:       str,
        target_slice: str | None = None,
        target_imsi:  str | None = None,
        new_dl_ambr:  int | None = None,
        new_ul_ambr:  int | None = None,
        extra_params: dict | None = None,
    ) -> dict[str, Any]:
        req = FeasibilityRequest(
            action=action,
            target_slice=target_slice,
            target_imsi=target_imsi,
            new_dl_ambr=new_dl_ambr,
            new_ul_ambr=new_ul_ambr,
            extra_params=extra_params or {},
        )

        warnings: list[str] = []

        # 1. Validate AMBR bounds
        ambr_check = self._check_ambr_bounds(req)
        if not ambr_check["ok"]:
            return FeasibilityResult(
                allowed=False, reason=ambr_check["reason"], warnings=warnings
            ).model_dump()
        warnings.extend(ambr_check.get("warnings", []))

        # 2. Check slice exists
        if req.target_slice:
            slice_check = self._check_slice_exists(req.target_slice)
            if not slice_check["ok"]:
                return FeasibilityResult(
                    allowed=False, reason=slice_check["reason"], warnings=warnings
                ).model_dump()

        # 3. Check IMSI exists (if targeted)
        if req.target_imsi:
            imsi_check = self._check_imsi_exists(req.target_imsi)
            if not imsi_check["ok"]:
                return FeasibilityResult(
                    allowed=False, reason=imsi_check["reason"], warnings=warnings
                ).model_dump()

        # 4. Network load check
        load_check = self._check_network_load()
        load_pct   = load_check["load_pct"]
        if load_pct > 90.0:
            return FeasibilityResult(
                allowed=False,
                reason=f"Network load is critically high ({load_pct:.1f}%). "
                       "Increasing AMBR is not safe right now.",
                current_load_pct=load_pct,
                warnings=warnings,
            ).model_dump()
        if load_pct > 70.0:
            warnings.append(f"Network load is elevated ({load_pct:.1f}%). Proceed with caution.")

        # 5. Cooldown check (prevent rapid repeated policy changes)
        cooldown_check = self._check_cooldown(req.action, req.target_slice)
        if not cooldown_check["ok"]:
            return FeasibilityResult(
                allowed=False, reason=cooldown_check["reason"], warnings=warnings,
                current_load_pct=load_pct,
            ).model_dump()

        return FeasibilityResult(
            allowed=True,
            reason="All feasibility checks passed.",
            warnings=warnings,
            current_load_pct=load_pct,
        ).model_dump()

    # ── individual checks ─────────────────────────────────────────────────────

    def _check_ambr_bounds(self, req: FeasibilityRequest) -> dict:
        """Validate requested AMBR values against 3GPP ceilings."""
        warnings = []

        if req.new_dl_ambr is not None:
            if req.new_dl_ambr > MAX_DL_AMBR_BPS:
                return {
                    "ok": False,
                    "reason": f"Requested DL AMBR {req.new_dl_ambr} bps exceeds "
                              f"maximum allowed {MAX_DL_AMBR_BPS} bps (1 Gbps).",
                }
            if req.new_dl_ambr < MIN_AMBR_BPS:
                return {
                    "ok": False,
                    "reason": f"Requested DL AMBR {req.new_dl_ambr} bps is below "
                              f"minimum floor {MIN_AMBR_BPS} bps (1 Mbps).",
                }
            if req.new_dl_ambr > MAX_DL_AMBR_BPS * 0.8:
                warnings.append("DL AMBR is above 80% of the network ceiling.")

        if req.new_ul_ambr is not None:
            if req.new_ul_ambr > MAX_UL_AMBR_BPS:
                return {
                    "ok": False,
                    "reason": f"Requested UL AMBR {req.new_ul_ambr} bps exceeds "
                              f"maximum allowed {MAX_UL_AMBR_BPS} bps.",
                }
            if req.new_ul_ambr < MIN_AMBR_BPS:
                return {
                    "ok": False,
                    "reason": f"Requested UL AMBR {req.new_ul_ambr} bps is below "
                              f"minimum floor {MIN_AMBR_BPS} bps.",
                }

        return {"ok": True, "warnings": warnings}

    def _check_slice_exists(self, slice_name: str) -> dict:
        """Check the slice/DNN name is known in the subscriber database."""
        # First check our known config list
        if slice_name in KNOWN_SLICES:
            return {"ok": True}

        # Then check if any subscriber has this DNN configured
        try:
            db    = get_open5gs_db()
            count = db["subscribers"].count_documents(
                {"session.name": slice_name}
            )
            if count > 0:
                return {"ok": True}
        except Exception as exc:
            log.warning("Could not query subscribers for slice check: %s", exc)
            # Allow action even if DB check fails — don't block on DB errors
            return {"ok": True}

        return {
            "ok": False,
            "reason": f"Slice/DNN '{slice_name}' not found in subscriber database. "
                      f"Known slices: {KNOWN_SLICES}",
        }

    def _check_imsi_exists(self, imsi: str) -> dict:
        """Verify the IMSI exists in Open5GS subscriber store."""
        try:
            db  = get_open5gs_db()
            doc = db["subscribers"].find_one({"imsi": imsi}, {"_id": 1})
            if doc:
                return {"ok": True}
            return {
                "ok": False,
                "reason": f"IMSI '{imsi}' not found in the subscriber database.",
            }
        except Exception as exc:
            log.warning("IMSI check DB error: %s", exc)
            return {"ok": True}  # fail open on DB error

    def _check_network_load(self) -> dict:
        """
        Estimate current network load as a percentage of max capacity.
        Uses active_ue_count from nwdaf_analytics — which the collector sets
        from live uesimtunX tunnel interfaces, not the DB subscriber count.
        This gives a true picture of how many UEs are actually connected.
        """
        try:
            db  = get_nwdaf_db()
            doc = db["upf_metrics"].find_one(
                {}, {"active_ue_count": 1}, sort=[("timestamp", -1)]
            )
            if doc:
                count    = doc.get("active_ue_count", 0)
                load_pct = round((count / MAX_UE_CAPACITY) * 100, 1)
                return {"load_pct": load_pct}
        except Exception as exc:
            log.warning("Load check DB error: %s", exc)
        return {"load_pct": 0.0}

    def _check_cooldown(self, action: str, target_slice: str | None) -> dict:
        """
        Block the same action on the same slice if it ran within
        POLICY_COOLDOWN_SEC seconds (prevents rapid hammering).
        """
        try:
            db      = get_nwdaf_db()
            cutoff  = datetime.now(timezone.utc) - timedelta(seconds=POLICY_COOLDOWN_SEC)
            query   = {"action": action, "applied_at": {"$gte": cutoff}}
            if target_slice:
                query["target_slice"] = target_slice
            recent = db[NWDAF_SCHEDULED_TASKS].find_one(query)
            if recent:
                return {
                    "ok": False,
                    "reason": (
                        f"Action '{action}' on slice '{target_slice}' was applied "
                        f"less than {POLICY_COOLDOWN_SEC}s ago. Wait before re-applying."
                    ),
                }
        except Exception as exc:
            log.warning("Cooldown check DB error: %s", exc)
        return {"ok": True}
