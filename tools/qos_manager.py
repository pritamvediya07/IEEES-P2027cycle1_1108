#!/usr/bin/env python3
"""QoS manager — policy variables OTHER than session AMBR  (needed for E5).

E5 asks whether the contamination channel generalises beyond the one variable
the original work studied. Answering that honestly requires variables that are
genuinely different, not aliases of AMBR:

  1. 5QI / ARP priority
     A DIFFERENT SUBTREE of the subscriber document (session[].qos.*, not
     session[].ambr.*) and a different enforcement semantic: 5QI selects a
     standardised QoS characteristic set (TS 23.501 Table 5.7.4-1) and ARP
     governs admission and pre-emption rather than rate.

  2. GBR / MBR on a dedicated flow
     A genuinely different ENFORCEMENT PATH. Session-AMBR is enforced at the
     UPF as an aggregate over the PDU session; GBR/MBR are per-QoS-flow and map
     to a separate QER in TS 29.244 terms. Writing them exercises a different
     part of the policy plane entirely.

The point of E5 is to report the CHANNEL and the FAILURE separately. This tool
exists so the channel test can be run on all three variables deterministically,
with no model involved.
"""
from __future__ import annotations

import logging
from typing import Any

from pymongo import MongoClient
from pymongo.errors import PyMongoError

log = logging.getLogger("COLLECTOR")

OPEN5GS_URI = "mongodb://localhost:27017/"

# TS 23.501 Table 5.7.4-1 standardised 5QI values
VALID_5QI = {1, 2, 3, 4, 65, 66, 67, 71, 72, 73, 74, 76,
             5, 6, 7, 8, 9, 69, 70, 79, 80, 82, 83, 84, 85}
GBR_5QI = {1, 2, 3, 4, 65, 66, 67, 71, 72, 73, 74, 76}
MIN_PRIORITY, MAX_PRIORITY = 1, 15
MIN_BR_BPS, MAX_BR_BPS = 1_000_000, 1_000_000_000


def _iter_sessions(doc, dnn):
    """Yield every session sub-document for this DNN, on BOTH schema paths.

    An Open5GS subscriber document here carries two session arrays:

      doc["session"]              legacy top-level array. This is what
                                  PolicyManager writes and what the collector
                                  reads, so it is the path the ANALYTICS see.
      doc["slice"][i]["session"]  the modern Release-16 schema that Open5GS
                                  2.7.x actually consults.

    Writing only one of them produced a silent failure the first time: the value
    landed in the database, the collector kept reporting the old one, and the
    contamination test looked like it had cleanly failed. Both paths are written
    so the tool behaves like PolicyManager and so the write is real rather than
    only visible to the analytics.
    """
    for sess in doc.get("session", []) or []:
        if sess.get("name") == dnn:
            yield sess
    for sl in doc.get("slice", []) or []:
        for sess in sl.get("session", []) or []:
            if sess.get("name") == dnn:
                yield sess


class QoSManager:
    """Writes to session[].qos.* — a different subtree from PolicyManager."""

    def __init__(self, uri: str = OPEN5GS_URI) -> None:
        self._uri = uri
        self._client: MongoClient | None = None

    def _db(self):
        if self._client is None:
            self._client = MongoClient(self._uri, serverSelectionTimeoutMS=3000)
        return self._client["open5gs"]

    # ── variable 2: 5QI / ARP priority ────────────────────────────────────
    def set_5qi(self, slice_dnn: str, qos_index: int,
                arp_priority: int | None = None, reason: str = "") -> dict[str, Any]:
        if qos_index not in VALID_5QI:
            raise ValueError(f"5QI {qos_index} is not a standardised value "
                             f"(TS 23.501 Table 5.7.4-1)")
        if arp_priority is not None and not (MIN_PRIORITY <= arp_priority <= MAX_PRIORITY):
            raise ValueError(f"ARP priority {arp_priority} out of range "
                             f"[{MIN_PRIORITY}, {MAX_PRIORITY}]")
        try:
            db = self._db()
            n, old = 0, None
            for doc in db["subscribers"].find({}):
                changed = False
                for sess in _iter_sessions(doc, slice_dnn):
                    q = sess.setdefault("qos", {})
                    if old is None:
                        old = {"index": q.get("index"),
                               "arp_priority": q.get("arp", {}).get("priority_level")}
                    q["index"] = qos_index
                    if arp_priority is not None:
                        q.setdefault("arp", {})["priority_level"] = arp_priority
                    changed = True
                if changed:
                    db["subscribers"].replace_one({"_id": doc["_id"]}, doc)
                    n += 1
            log.info("QoS apply: 5QI=%s arp=%s on %d subscriber(s) — %s",
                     qos_index, arp_priority, n, reason)
            return {"success": n > 0, "variable": "5qi_arp", "affected": n,
                    "old": old, "new_5qi": qos_index, "new_arp_priority": arp_priority}
        except PyMongoError as exc:
            return {"success": False, "error": str(exc)}

    # ── variable 3: GBR / MBR on a dedicated flow ─────────────────────────
    def set_flow_br(self, slice_dnn: str, mbr_dl_bps: int, gbr_dl_bps: int | None = None,
                    reason: str = "") -> dict[str, Any]:
        """Per-QoS-flow MBR/GBR — a separate QER from the session-AMBR path."""
        for name, v in (("mbr_dl", mbr_dl_bps), ("gbr_dl", gbr_dl_bps)):
            if v is not None and not (MIN_BR_BPS <= v <= MAX_BR_BPS):
                raise ValueError(f"{name} {v} bps out of range "
                                 f"[{MIN_BR_BPS}, {MAX_BR_BPS}]")
        if gbr_dl_bps is not None and gbr_dl_bps > mbr_dl_bps:
            raise ValueError("GBR must not exceed MBR")
        try:
            db = self._db()
            n, old = 0, None
            for doc in db["subscribers"].find({}):
                changed = False
                for sess in _iter_sessions(doc, slice_dnn):
                    q = sess.setdefault("qos", {})
                    if old is None:
                        old = {"mbr_dl": q.get("mbr", {}).get("downlink", {}).get("value"),
                               "gbr_dl": q.get("gbr", {}).get("downlink", {}).get("value")}
                    q.setdefault("mbr", {})["downlink"] = {
                        "value": mbr_dl_bps // 1_000_000, "unit": 3}
                    q["mbr"].setdefault("uplink", {"value": mbr_dl_bps // 1_000_000, "unit": 3})
                    if gbr_dl_bps is not None:
                        q.setdefault("gbr", {})["downlink"] = {
                            "value": gbr_dl_bps // 1_000_000, "unit": 3}
                        q["gbr"].setdefault("uplink", {"value": gbr_dl_bps // 1_000_000,
                                                       "unit": 3})
                    changed = True
                if changed:
                    db["subscribers"].replace_one({"_id": doc["_id"]}, doc)
                    n += 1
            log.info("QoS apply: mbr_dl=%s gbr_dl=%s on %d subscriber(s) — %s",
                     mbr_dl_bps, gbr_dl_bps, n, reason)
            return {"success": n > 0, "variable": "gbr_mbr", "affected": n, "old": old,
                    "new_mbr_dl_mbps": mbr_dl_bps // 1_000_000,
                    "new_gbr_dl_mbps": (gbr_dl_bps // 1_000_000) if gbr_dl_bps else None}
        except PyMongoError as exc:
            return {"success": False, "error": str(exc)}

    def restore_defaults(self, slice_dnn: str = "internet") -> dict:
        """5QI 9 / ARP 8 and no dedicated flow rates — the shipped baseline."""
        r = self.set_5qi(slice_dnn, 9, 8, reason="restore baseline")
        try:
            db = self._db()
            for doc in db["subscribers"].find({}):
                ch = False
                for sess in _iter_sessions(doc, slice_dnn):
                    if "qos" in sess:
                        sess["qos"].pop("mbr", None)
                        sess["qos"].pop("gbr", None)
                        ch = True
                if ch:
                    db["subscribers"].replace_one({"_id": doc["_id"]}, doc)
        except PyMongoError as exc:
            return {"success": False, "error": str(exc)}
        return r
