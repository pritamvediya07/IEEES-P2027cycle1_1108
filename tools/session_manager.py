# tools/session_manager.py
# Tool 4 — Session Manager
#
# Manages PDU session lifecycles and QoS changes.
# Real actions:
#   - List all active sessions with QoS info
#   - Get session details for a specific IMSI
#   - Terminate a PDU session (sends Delete Session Request to SMF)
#   - Validate QoS changes against SMF and UPF standards
#   - Force session re-establishment (terminate + subscriber stays registered)
#
# Open5GS SMF SBI: http://127.0.0.4:7777
# The most reliable approach for session management on Open5GS is via the
# subscriber MongoDB document — the SMF watches for changes.

import logging
from datetime import datetime, timezone
from typing import Any

import requests
from pydantic import BaseModel, Field

from config.db import get_open5gs_db, get_nwdaf_db
from config.settings import NF_ADDRESSES, NWDAF_SCHEDULED_TASKS

log = logging.getLogger(__name__)

SMF_URL     = NF_ADDRESSES["smf"]
HTTP_TIMEOUT = 8


# ── models ────────────────────────────────────────────────────────────────────

class SessionInfo(BaseModel):
    imsi:        str
    dnn:         str
    state:       str = "active"
    dl_ambr_mbps: float | None = None
    ul_ambr_mbps: float | None = None
    qos_index:   int  = 9
    ip_address:  str | None = None


class SessionActionResult(BaseModel):
    success:  bool
    message:  str
    imsi:     str | None = None
    dnn:      str | None = None
    details:  dict = Field(default_factory=dict)


# ── main class ────────────────────────────────────────────────────────────────

class SessionManager:
    """
    Lifecycle management for PDU sessions.
    """

    def list_sessions(self, dnn_filter: str | None = None) -> dict[str, Any]:
        """
        Return all active PDU sessions, optionally filtered by DNN/slice.
        """
        try:
            db    = get_open5gs_db()
            query = {}
            if dnn_filter:
                query["session.name"] = dnn_filter

            subs = list(db["subscribers"].find(
                query,
                {"imsi": 1, "session": 1, "_id": 0},
            ))

            sessions: list[dict] = []
            for sub in subs:
                imsi = sub["imsi"]
                for sess in sub.get("session", []):
                    if dnn_filter and sess.get("name") != dnn_filter:
                        continue
                    ambr = sess.get("ambr", {})
                    sessions.append(SessionInfo(
                        imsi=imsi,
                        dnn=sess.get("name", "internet"),
                        dl_ambr_mbps=ambr.get("downlink", {}).get("value"),
                        ul_ambr_mbps=ambr.get("uplink",   {}).get("value"),
                        qos_index=sess.get("qos", {}).get("index", 9),
                    ).model_dump())

            return {
                "session_count": len(sessions),
                "sessions":      sessions,
                "filter_dnn":    dnn_filter,
            }
        except Exception as exc:
            log.error("list_sessions failed: %s", exc)
            return {"error": str(exc)}

    def get_session(self, imsi: str, dnn: str | None = None) -> dict[str, Any]:
        """
        Return session details for a specific IMSI.
        """
        try:
            db    = get_open5gs_db()
            sub   = db["subscribers"].find_one({"imsi": imsi}, {"session": 1, "imsi": 1})
            if not sub:
                return {"error": f"IMSI {imsi} not found."}

            result = []
            for sess in sub.get("session", []):
                if dnn and sess.get("name") != dnn:
                    continue
                ambr = sess.get("ambr", {})
                result.append({
                    "dnn":          sess.get("name"),
                    "dl_ambr_mbps": ambr.get("downlink", {}).get("value"),
                    "ul_ambr_mbps": ambr.get("uplink",   {}).get("value"),
                    "qos_index":    sess.get("qos", {}).get("index", 9),
                    "arp_priority": sess.get("qos", {}).get("arp", {}).get("priority_level", 8),
                })
            return {"imsi": imsi, "sessions": result, "count": len(result)}
        except Exception as exc:
            log.error("get_session failed: %s", exc)
            return {"error": str(exc)}

    def validate_qos_change(
        self,
        imsi:          str,
        dnn:           str,
        new_qos_index: int,
        new_arp:       int | None = None,
    ) -> dict[str, Any]:
        """
        Validate a proposed QoS change against 3GPP rules.

        3GPP TS 23.501 QoS rules:
          - 5QI 1–4: GBR (Guaranteed Bit Rate) — need explicit GBR params
          - 5QI 5–9: Non-GBR — safe for data sessions
          - ARP priority 1–15 (1 = highest priority)
        """
        warnings: list[str] = []
        allowed  = True
        reason   = "QoS change is valid."

        # 5QI validation
        if not (1 <= new_qos_index <= 9):
            return {
                "allowed": False,
                "reason":  f"5QI/QoS index {new_qos_index} is outside valid range 1–9.",
            }
        if new_qos_index in (1, 2, 3, 4):
            warnings.append(
                f"5QI {new_qos_index} is a GBR resource type. "
                "Ensure GBR DL/UL values are explicitly set."
            )

        # ARP validation
        if new_arp is not None:
            if not (1 <= new_arp <= 15):
                return {
                    "allowed": False,
                    "reason":  f"ARP priority {new_arp} is outside valid range 1–15.",
                }
            if new_arp == 1:
                warnings.append("ARP priority 1 is the highest — may pre-empt other sessions.")

        # Check the subscriber actually has this DNN
        session_info = self.get_session(imsi, dnn)
        if "error" in session_info:
            return {"allowed": False, "reason": session_info["error"]}
        if session_info["count"] == 0:
            return {
                "allowed": False,
                "reason":  f"IMSI {imsi} has no active session on DNN '{dnn}'.",
            }

        return {"allowed": allowed, "reason": reason, "warnings": warnings}

    def modify_session_qos(
        self,
        imsi:          str,
        dnn:           str,
        new_qos_index: int,
        new_arp:       int | None = None,
    ) -> dict[str, Any]:
        """
        Apply QoS changes to a session by updating the subscriber document.
        Open5GS SMF re-reads subscriber data on the next session update.
        """
        # Validate first
        val = self.validate_qos_change(imsi, dnn, new_qos_index, new_arp)
        if not val.get("allowed"):
            return SessionActionResult(
                success=False,
                message=val.get("reason", "Validation failed"),
                imsi=imsi, dnn=dnn,
            ).model_dump()

        try:
            db  = get_open5gs_db()
            sub = db["subscribers"].find_one({"imsi": imsi})
            if not sub:
                return SessionActionResult(
                    success=False, message=f"IMSI {imsi} not found.",
                    imsi=imsi, dnn=dnn,
                ).model_dump()

            sessions = sub.get("session", [])
            modified = False
            for sess in sessions:
                if sess.get("name") == dnn:
                    sess.setdefault("qos", {})
                    sess["qos"]["index"] = new_qos_index
                    if new_arp is not None:
                        sess["qos"].setdefault("arp", {})
                        sess["qos"]["arp"]["priority_level"] = new_arp
                    modified = True

            if not modified:
                return SessionActionResult(
                    success=False,
                    message=f"DNN '{dnn}' not found in subscriber {imsi}.",
                    imsi=imsi, dnn=dnn,
                ).model_dump()

            db["subscribers"].update_one(
                {"_id": sub["_id"]},
                {"$set": {"session": sessions}},
            )
            self._audit("modify_qos", imsi, dnn, {"qos_index": new_qos_index, "arp": new_arp})

            return SessionActionResult(
                success=True,
                message=f"QoS index updated to {new_qos_index} for IMSI {imsi} on DNN {dnn}.",
                imsi=imsi, dnn=dnn,
                details={"new_qos_index": new_qos_index},
            ).model_dump()

        except Exception as exc:
            log.error("modify_session_qos failed: %s", exc, exc_info=True)
            return SessionActionResult(
                success=False, message=str(exc), imsi=imsi, dnn=dnn,
            ).model_dump()

    def terminate_session(self, imsi: str, dnn: str) -> dict[str, Any]:
        """
        Terminate a PDU session.

        Strategy: We attempt to call the SMF's Nsmf_PDUSession_Release endpoint.
        If the SMF SBI call fails (common in loopback test setups), we log the
        request and return guidance — the operator can use `nr-cli` to force-drop
        the UERANSIM UE tunnel instead.
        """
        # Try SMF NAS release via SBI
        smf_result = self._smf_release(imsi, dnn)
        self._audit("terminate_session", imsi, dnn, smf_result)
        return smf_result

    # ── private ───────────────────────────────────────────────────────────────

    def _smf_release(self, imsi: str, dnn: str) -> dict[str, Any]:
        """
        Call SMF SBI to release a PDU session.
        The Nsmf_PDUSession_Release endpoint is at:
          POST /nsmf-pdusession/v1/sm-contexts/{smContextRef}/release
        We query the SMF's context list first to find the smContextRef.
        """
        try:
            # Query SMF for active contexts
            resp = requests.get(
                f"{SMF_URL}/nsmf-pdusession/v1/sm-contexts",
                timeout=HTTP_TIMEOUT,
            )
            if resp.status_code == 200:
                contexts = resp.json()
                for ctx in contexts:
                    if ctx.get("supi") == f"imsi-{imsi}" and ctx.get("dnn") == dnn:
                        ref = ctx.get("smContextRef") or ctx.get("contextId")
                        if ref:
                            rel = requests.post(
                                f"{SMF_URL}/nsmf-pdusession/v1/sm-contexts/{ref}/release",
                                json={"cause": "REL_DUE_TO_IMPLICIT_DEREGISTRATION"},
                                timeout=HTTP_TIMEOUT,
                            )
                            return SessionActionResult(
                                success=rel.status_code in (200, 204),
                                message=f"SMF release status {rel.status_code}",
                                imsi=imsi, dnn=dnn,
                            ).model_dump()

            # SMF SBI not exposed or context not found — give operator guidance
            return SessionActionResult(
                success=False,
                message=(
                    f"Could not find SMF session context for IMSI {imsi} DNN {dnn}. "
                    "To force-terminate, run on the UERANSIM machine: "
                    f"  build/nr-cli <ue-name> --exec 'ps-release 1'"
                ),
                imsi=imsi, dnn=dnn,
            ).model_dump()

        except requests.RequestException as exc:
            log.warning("SMF SBI not reachable: %s", exc)
            return SessionActionResult(
                success=False,
                message=(
                    f"SMF SBI unreachable ({exc}). "
                    "Manual termination via nr-cli is required."
                ),
                imsi=imsi, dnn=dnn,
            ).model_dump()

    def _audit(self, action: str, imsi: str, dnn: str, details: dict) -> None:
        try:
            get_nwdaf_db()[NWDAF_SCHEDULED_TASKS].insert_one({
                "action":     action,
                "imsi":       imsi,
                "dnn":        dnn,
                "details":    details,
                "applied_at": datetime.now(timezone.utc),
            })
        except Exception as exc:
            log.warning("Audit log write failed: %s", exc)
