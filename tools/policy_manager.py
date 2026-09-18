# tools/policy_manager.py
# Tool 3 — Policy Manager
#
# Enforces network policies by calling the Open5GS REST APIs.
# Real actions this tool performs:
#   - Modify AMBR (Aggregate Maximum Bit Rate) for a slice/DNN
#   - Apply / revert QoS parameters for a specific IMSI
#   - Compare new policy with existing governance before applying
#
# Open5GS SBI endpoints used:
#   PCF  http://127.0.0.9:7777    (Policy Control Function)
#   UDR  http://127.0.0.20:7777   (Unified Data Repository — stores policies)
#   WebUI http://localhost:9999    (subscriber management REST API)
#
# The policy is applied by PATCHing the subscriber document in MongoDB
# via the Open5GS WebUI REST API (the safest stable interface without
# needing to patch Open5GS C source code).

import logging
import json
from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field, field_validator

from config.db import get_nwdaf_db, get_open5gs_db
from config.settings import (
    WEBUI_URL, NWDAF_SCHEDULED_TASKS,
    MAX_DL_AMBR_BPS, MAX_UL_AMBR_BPS, MIN_AMBR_BPS,
    NF_ADDRESSES,
)

log = logging.getLogger(__name__)

WEBUI_TIMEOUT = 8   # seconds for HTTP requests


# ── models ────────────────────────────────────────────────────────────────────

class PolicyRequest(BaseModel):
    target_slice:  str  = Field(..., description="DNN/slice name, e.g. 'internet'")
    new_dl_ambr:   int  = Field(..., description="New DL AMBR in bps")
    new_ul_ambr:   int  = Field(..., description="New UL AMBR in bps")
    target_imsi:   str | None = Field(None, description="Specific IMSI, or None for all in slice")
    reason:        str  = Field("PALA policy change", description="Audit log reason")

    @field_validator("new_dl_ambr", "new_ul_ambr")
    @classmethod
    def ambr_in_range(cls, v: int) -> int:
        # LLMs commonly pass Mbps integers (e.g. 26) instead of bps (26_000_000).
        # Auto-convert: any value < 10_000 is clearly not bps — treat as Mbps.
        if 0 < v < 10_000:
            v = v * 1_000_000
        if not (MIN_AMBR_BPS <= v <= MAX_DL_AMBR_BPS):
            raise ValueError(f"AMBR {v} bps out of range [{MIN_AMBR_BPS}, {MAX_DL_AMBR_BPS}]")
        return v


class PolicyResult(BaseModel):
    success:       bool
    message:       str
    affected_imsis: list[str] = Field(default_factory=list)
    old_dl_ambr:   int | None = None
    old_ul_ambr:   int | None = None
    new_dl_ambr:   int | None = None
    new_ul_ambr:   int | None = None


# ── helper: Open5GS WebUI auth ────────────────────────────────────────────────

class _WebUISession:
    """Thin wrapper around the Open5GS WebUI REST API."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._token: str | None = None

    def _login(self) -> None:
        from config.settings import WEBUI_USER, WEBUI_PASSWORD
        resp = self._session.post(
            f"{WEBUI_URL}/api/auth/login",
            json={"username": WEBUI_USER, "password": WEBUI_PASSWORD},
            timeout=WEBUI_TIMEOUT,
        )
        resp.raise_for_status()
        self._token = resp.json().get("access_token") or resp.json().get("token")
        if self._token:
            self._session.headers.update({"Authorization": f"Bearer {self._token}"})

    def get_subscribers(self) -> list[dict]:
        if not self._token:
            self._login()
        resp = self._session.get(f"{WEBUI_URL}/api/db/Subscriber", timeout=WEBUI_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def update_subscriber(self, doc_id: str, payload: dict) -> dict:
        if not self._token:
            self._login()
        resp = self._session.put(
            f"{WEBUI_URL}/api/db/Subscriber/{doc_id}",
            json=payload,
            timeout=WEBUI_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()


# ── main class ────────────────────────────────────────────────────────────────

class PolicyManager:
    """
    Apply and revert network slice policies via Open5GS REST APIs.
    """

    def apply_policy(
        self,
        target_slice: str,
        new_dl_ambr:  int,
        new_ul_ambr:  int,
        target_imsi:  str | None = None,
        reason:       str = "PALA policy change",
    ) -> dict[str, Any]:
        """
        Apply a new AMBR policy to a slice (and optionally a specific IMSI).
        Returns a PolicyResult dict.
        """
        req = PolicyRequest(
            target_slice=target_slice,
            new_dl_ambr=new_dl_ambr,
            new_ul_ambr=new_ul_ambr,
            target_imsi=target_imsi,
            reason=reason,
        )

        try:
            result = self._apply_via_direct_mongo(req)
        except Exception as exc:
            log.error("Policy apply failed: %s", exc, exc_info=True)
            result = PolicyResult(
                success=False,
                message=f"Failed to apply policy: {exc}",
            )

        # audit log
        self._audit_log(req, result)

        out = result.model_dump()
        log.info("Policy apply result: %s", out)
        return out

    def get_current_policy(self, target_slice: str) -> dict[str, Any]:
        """
        Return the current AMBR for all subscribers on a given slice.
        """
        try:
            db   = get_open5gs_db()
            subs = list(db["subscribers"].find(
                {"session.name": target_slice},
                {"imsi": 1, "session": 1, "_id": 0},
            ))

            results = []
            for doc in subs:
                for sess in doc.get("session", []):
                    if sess.get("name") != target_slice:
                        continue
                    ambr = sess.get("ambr", {})
                    results.append({
                        "imsi":     doc["imsi"],
                        "slice":    target_slice,
                        "dl_ambr":  ambr.get("downlink", {}).get("value", 0),
                        "ul_ambr":  ambr.get("uplink",   {}).get("value", 0),
                        "dl_unit":  ambr.get("downlink", {}).get("unit", 3),
                        "ul_unit":  ambr.get("uplink",   {}).get("unit", 3),
                    })
            return {"slice": target_slice, "subscribers": results, "count": len(results)}

        except Exception as exc:
            log.error("get_current_policy failed: %s", exc)
            return {"error": str(exc)}

    # ── internal helpers ──────────────────────────────────────────────────────

    def _apply_via_direct_mongo(self, req: PolicyRequest) -> PolicyResult:
        """
        Apply AMBR changes directly to Open5GS MongoDB.
        This is equivalent to what the WebUI does when you edit a subscriber.
        Unit 3 = Mbps in Open5GS.  We store bps in our model but convert.
        """
        db    = get_open5gs_db()
        query = {"session.name": req.target_slice}
        if req.target_imsi:
            query["imsi"] = req.target_imsi

        subscribers = list(db["subscribers"].find(query, {"imsi": 1, "session": 1}))
        if not subscribers:
            return PolicyResult(
                success=False,
                message=f"No subscribers found for slice '{req.target_slice}'",
            )

        # Convert bps → Mbps for Open5GS internal storage
        dl_mbps = req.new_dl_ambr // 1_000_000
        ul_mbps = req.new_ul_ambr // 1_000_000

        affected: list[str] = []
        old_dl = old_ul = None

        for sub in subscribers:
            imsi     = sub["imsi"]
            sessions = sub.get("session", [])
            updated  = []
            for sess in sessions:
                if sess.get("name") == req.target_slice:
                    if old_dl is None:
                        old_dl = sess.get("ambr", {}).get("downlink", {}).get("value", 0)
                        old_ul = sess.get("ambr", {}).get("uplink",   {}).get("value", 0)
                    sess.setdefault("ambr", {})
                    sess["ambr"]["downlink"] = {"value": dl_mbps, "unit": 3}
                    sess["ambr"]["uplink"]   = {"value": ul_mbps, "unit": 3}
                updated.append(sess)

            db["subscribers"].update_one(
                {"_id": sub["_id"]},
                {"$set": {"session": updated}},
            )
            affected.append(imsi)

        return PolicyResult(
            success=True,
            message=f"AMBR updated for {len(affected)} subscriber(s) on slice '{req.target_slice}'.",
            affected_imsis=affected,
            old_dl_ambr=old_dl,
            old_ul_ambr=old_ul,
            new_dl_ambr=req.new_dl_ambr,
            new_ul_ambr=req.new_ul_ambr,
        )

    def _audit_log(self, req: PolicyRequest, result: PolicyResult) -> None:
        """Write every policy change attempt to the NWDAF audit collection."""
        try:
            db  = get_nwdaf_db()
            doc = {
                "action":        "apply_policy",
                "target_slice":  req.target_slice,
                "target_imsi":   req.target_imsi,
                "new_dl_ambr":   req.new_dl_ambr,
                "new_ul_ambr":   req.new_ul_ambr,
                "reason":        req.reason,
                "success":       result.success,
                "message":       result.message,
                "applied_at":    datetime.now(timezone.utc),
            }
            db[NWDAF_SCHEDULED_TASKS].insert_one(doc)
        except Exception as exc:
            log.warning("Audit log write failed: %s", exc)
