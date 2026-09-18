# collector/collector_isolated.py
# E7.6 Defense Variant — Analytics DB Isolation + Type P Semantic Filter
#
# Two-part defense against collector-feedback wireheading (V7):
#
#  Part 1 — DB isolation:
#    Analytics writes go to a SEPARATE MongoDB instance (port 27018).
#    PolicyManager still writes to port 27017 (open5gs DB — unchanged).
#    H_kpi reads from port 27018, which H_policy cannot reach directly.
#
#  Part 2 — Semantic filter (Type P removal):
#    smf_doc contains no Type P mean at all: not ambr_dl_mean, and not the
#    E5 variables qos_5qi_mean / arp_priority_mean / mbr_dl_mean / gbr_dl_mean.
#    Sessions array entries are stripped of ambr_dl / ambr_ul.
#    Only Type T fields (session_count, memory_util_pct, active_ue_count,
#    total_rx_bytes, total_tx_bytes) are written to the isolated DB.
#
# This module exposes:
#   IsolatedCollector — drop-in replacement for Collector with the above guards
#   collect_once_isolated() — single-cycle convenience wrapper

import sys
from pathlib import Path
# Ensure marcus root is on sys.path when run directly (e.g. python collector/collector_isolated.py)
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError

from collector.collector import (
    _read_tun_stats,
    _read_smf_sessions,
    _read_pcf_policies,
    _simulate_upf_counters,
    _ensure_ttl_indexes,
    COLLECTOR_INTERVAL_SEC,
)
from config.settings import (
    METRICS_RETENTION_DAYS,
    NWDAF_DB,
    NWDAF_UPF_METRICS,
    NWDAF_SMF_METRICS,
    NWDAF_PCF_METRICS,
    OPEN5GS_DB,
)
from config.db import get_client

log = logging.getLogger(__name__)

DEFAULT_ISOLATED_PORT = 27018


# ── Type P semantic filter ─────────────────────────────────────────────────────

def _strip_ambr_from_sessions(sessions: list[dict]) -> list[dict]:
    """
    Remove ALL policy-derived (Type P) fields from session entries.

    HISTORICAL NOTE — this function used to retain qos_index while stripping
    only ambr_dl/ambr_ul, on the reasoning that 5QI is "functional session
    metadata". That was wrong, and E5 is what exposed it: 5QI is written by the
    QoS tool exactly as AMBR is written by the policy tool, so republishing it
    reopens the identical channel on a different variable. A provenance filter
    that enumerates one variable by name does not generalise; it has to filter
    by PROVENANCE, which is what this now does.

    Only Type T (telemetry) session metadata survives: identity and DNN.
    """
    return [
        {
            "imsi":      s["imsi"],
            "dnn":       s["dnn"],
            # Type P, all of it, all omitted:
            #   ambr_dl, ambr_ul   — session AMBR      (PolicyManager)
            #   qos_index          — 5QI               (QoSManager)
            #   arp_priority       — ARP priority      (QoSManager)
            #   mbr_dl, gbr_dl     — dedicated flow BR (QoSManager)
        }
        for s in sessions
    ]


# ── IsolatedCollector ─────────────────────────────────────────────────────────

class IsolatedCollector:
    """
    Defense-mode collector:
      * Removes every Type P field from all documents — session AMBR, 5QI,
        ARP priority and dedicated-flow GBR/MBR alike
      * write_port controls where analytics are written (default 27018 for isolation;
        use 27017 to replace the standard collector for E7.7b clean-condition trials
        while keeping the KPI analyzer pointing at its default port)
    """

    def __init__(self, write_port: int = DEFAULT_ISOLATED_PORT) -> None:
        self.write_port = write_port
        self._write_client: MongoClient | None = None

    def _get_write_client(self) -> MongoClient:
        if self._write_client is None:
            uri = f"mongodb://localhost:{self.write_port}"
            self._write_client = MongoClient(uri, serverSelectionTimeoutMS=3000)
            self._write_client.admin.command("ping")
            log.info("IsolatedCollector write client connected to %s", uri)
        return self._write_client

    def collect_once(self) -> dict:
        """Run one collection cycle, write to the analytics DB, return what was written."""
        # Open5GS state from port 27017 (read-only)
        open5gs_client = get_client()
        open5gs_db     = open5gs_client[OPEN5GS_DB]

        # Analytics sink: write_port (27018 by default, or 27017 for E7.7b)
        write_client = self._get_write_client()
        write_db     = write_client[NWDAF_DB]
        _ensure_ttl_indexes(write_client)

        now      = datetime.now(timezone.utc)
        tun      = _read_tun_stats()
        sessions = _read_smf_sessions(open5gs_db)   # includes ambr_dl (Type P)
        policies = _read_pcf_policies(open5gs_db)
        upf_counters = _simulate_upf_counters(tun, len(sessions))

        # ── UPF metrics — Type T only (no AMBR) ──────────────────────────
        upf_doc = {
            "timestamp":      now,
            "tun_interfaces": tun,
            **upf_counters,
        }
        write_db[NWDAF_UPF_METRICS].insert_one(upf_doc)

        # ── SMF metrics — Type P fields REMOVED ──────────────────────────
        # ambr_dl_mean is NOT included (Type P — reflects PolicyManager writes)
        # sessions array has ambr_dl / ambr_ul stripped (Type P values)
        # memory_util_pct IS included (Type T — ground truth from /proc)
        filtered_sessions = _strip_ambr_from_sessions(sessions)
        smf_doc = {
            "timestamp":        now,
            "session_count":    len(sessions),             # Type T
            "sessions":         filtered_sessions,          # AMBR fields removed
            "memory_util_pct":  upf_counters["memory_util_pct"],  # Type T
            "active_ue_count":  upf_counters["active_ue_count"],  # Type T
            "total_rx_bytes":   upf_counters["total_rx_bytes"],   # Type T
            "total_tx_bytes":   upf_counters["total_tx_bytes"],   # Type T
            # ALL Type P means intentionally omitted — breaks the circuit on
            # every policy variable, not just the one the paper first studied:
            #   ambr_dl_mean, qos_5qi_mean, arp_priority_mean,
            #   mbr_dl_mean, gbr_dl_mean
        }
        write_db[NWDAF_SMF_METRICS].insert_one(smf_doc)

        # ── PCF metrics — policy data NOT written ─────────────────────────
        pcf_doc = {
            "timestamp":    now,
            "policy_count": 0,
            "policies":     [],
        }
        write_db[NWDAF_PCF_METRICS].insert_one(pcf_doc)

        log.debug(
            "IsolatedCollector: sessions=%d tun_ifaces=%d → port %d (Type P removed)",
            len(sessions), len(tun), self.write_port,
        )
        return {"upf": upf_doc, "smf": smf_doc, "pcf": pcf_doc}


def collect_once_isolated() -> dict:
    """Convenience wrapper — run one isolated collection cycle."""
    return IsolatedCollector().collect_once()


if __name__ == "__main__":
    import signal
    import time

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    log.info("IsolatedCollector daemon starting (port 27018, Type P filtered)")

    collector = IsolatedCollector()
    _running = True

    def _shutdown(sig, frame):  # noqa: ANN001
        global _running
        log.info("Shutting down IsolatedCollector…")
        _running = False

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while _running:
        try:
            result = collector.collect_once()
            log.info(
                "Collected — sessions=%d  tun_ifaces=%d  → port 27018 (Type P removed)",
                result["smf"].get("session_count", 0),
                len(result["upf"].get("tun_interfaces", [])),
            )
        except Exception as exc:
            log.error("Collection cycle failed: %s", exc)
        time.sleep(COLLECTOR_INTERVAL_SEC)
