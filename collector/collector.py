# collector/collector.py
# Event Exposure Service (EES)
#
# Runs as a background daemon. Every COLLECTOR_INTERVAL_SEC seconds it:
#   1. Reads live session / stats data from the Open5GS MongoDB database
#   2. Reads UE tunnel interface stats from the Linux kernel (via /proc/net/dev)
#   3. Writes a timestamped snapshot to the nwdaf_analytics MongoDB database
#
# This gives PALA a real time-series of network KPIs to analyse.
# Run standalone:  python -m collector.collector
#
# The collector also creates TTL indexes on first run so old documents are
# automatically deleted after METRICS_RETENTION_DAYS days.

import time
import logging
import threading
import subprocess
import random
import re
from datetime import datetime, timezone, timedelta

from pymongo import ASCENDING, IndexModel
from pymongo.errors import PyMongoError

from config.settings import (
    COLLECTOR_INTERVAL_SEC,
    METRICS_RETENTION_DAYS,
    NWDAF_DB,
    NWDAF_UPF_METRICS,
    NWDAF_SMF_METRICS,
    NWDAF_PCF_METRICS,
    OPEN5GS_DB,
)
from config.db import get_client, ping

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [COLLECTOR] %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_ttl_indexes(client) -> None:
    """Create TTL indexes once so old documents auto-expire."""
    nwdaf = client[NWDAF_DB]
    ttl_seconds = METRICS_RETENTION_DAYS * 86_400
    for col_name in [NWDAF_UPF_METRICS, NWDAF_SMF_METRICS, NWDAF_PCF_METRICS]:
        col = nwdaf[col_name]
        existing = {idx["name"] for idx in col.list_indexes()}
        if "ts_ttl" not in existing:
            col.create_index(
                [("timestamp", ASCENDING)],
                expireAfterSeconds=ttl_seconds,
                name="ts_ttl",
            )
            log.info("Created TTL index on %s (expires after %d days)", col_name, METRICS_RETENTION_DAYS)


def _read_tun_stats() -> dict:
    """
    Read per-UE tunnel stats from /proc/net/dev.
    Returns {iface_name: {rx_bytes, tx_bytes, rx_packets, tx_packets}}.
    Falls back to zeros if uesimtunX interfaces are not up.
    """
    # UERANSIM names UE tunnels uesimtunX and puts them on the host, so matching
    # that prefix was sufficient. srsRAN names them tun_srsue and creates them
    # INSIDE per-UE network namespaces, where a host-side reader cannot see them
    # at all. The only user-plane interface visible here is ogstun, the UPF side,
    # which carries exactly the same bytes in aggregate.
    #
    # The consequence of not handling this: total_rx_bytes and total_tx_bytes read
    # 0 for the whole srsRAN campaign while ogstun was actually carrying gigabytes,
    # and E2.4 — whose numerator is measured user-plane volume — correctly refused
    # to record because its numerator never advanced.
    UE_PREFIXES = ("uesimtun", "tun_srsue")     # per-UE tunnels, if visible
    UPF_IFACES = ("ogstun",)                    # UPF side: the aggregate
    stats: dict = {}
    try:
        with open("/proc/net/dev", "r") as fh:
            for line in fh:
                line = line.strip()
                name = line.split(":", 1)[0].strip()
                if not (name.startswith(UE_PREFIXES) or name in UPF_IFACES):
                    continue
                # Format: iface: rx_bytes rx_packets rx_errs rx_drop ... tx_bytes ...
                parts = re.split(r"[:\s]+", line)
                if len(parts) < 17:
                    continue
                iface = parts[0]
                stats[iface] = {
                    "rx_bytes":   int(parts[1]),
                    "rx_packets": int(parts[2]),
                    "tx_bytes":   int(parts[9]),
                    "tx_packets": int(parts[10]),
                }
    except FileNotFoundError:
        pass  # not Linux or no tun interfaces yet
    return stats


def _mean(vals: list) -> float:
    return (sum(vals) / len(vals)) if vals else 0.0


def _read_smf_sessions(open5gs_db) -> list[dict]:
    """
    Read active PDU sessions from Open5GS SMF collection.
    Returns a list of lightweight dicts (IMSI, slice, QoS, state).
    """
    sessions = []
    try:
        # Open5GS stores SMF sessions in the 'subscribers' collection
        # (the same one the WebUI manages). Active sessions have a 'session' sub-doc.
        for doc in open5gs_db["subscribers"].find(
            {"session": {"$exists": True, "$ne": []}},
            {"imsi": 1, "session": 1, "_id": 0},
        ):
            imsi = doc.get("imsi", "unknown")
            for sess in doc.get("session", []):
                sessions.append(
                    {
                        "imsi":      imsi,
                        "dnn":       sess.get("name", "internet"),
                        "ambr_dl":   sess.get("ambr", {}).get("downlink", {}).get("value", 0),
                        "ambr_ul":   sess.get("ambr", {}).get("uplink",   {}).get("value", 0),
                        "qos_index": sess.get("qos", {}).get("index", 9),
                        # E5 variables 2 and 3 — a different subtree and a
                        # different enforcement path from session AMBR
                        "arp_priority": sess.get("qos", {}).get("arp", {})
                                            .get("priority_level", 8),
                        "mbr_dl": sess.get("qos", {}).get("mbr", {})
                                      .get("downlink", {}).get("value", 0),
                        "gbr_dl": sess.get("qos", {}).get("gbr", {})
                                      .get("downlink", {}).get("value", 0),
                    }
                )
    except PyMongoError as exc:
        log.warning("Could not read SMF sessions: %s", exc)
    return sessions


def _read_pcf_policies(open5gs_db) -> list[dict]:
    """
    Read policy data from Open5GS PCF / policy store in MongoDB.
    """
    policies = []
    try:
        for doc in open5gs_db["policyData.ues"].find(
            {}, {"supi": 1, "smPolicyData": 1, "_id": 0}
        ):
            supi = doc.get("supi", "unknown")
            sm = doc.get("smPolicyData", {})
            for dnn, data in sm.items():
                policies.append(
                    {
                        "supi":   supi,
                        "dnn":    dnn,
                        "policy": data,
                    }
                )
    except PyMongoError as exc:
        log.warning("Could not read PCF policies: %s", exc)
    return policies


def _simulate_upf_counters(tun_stats: dict, session_count: int) -> dict:
    """
    Build UPF-level aggregated metrics.
    In a real deployment with a patched UPF these would come from the UPF's
    Packet Forwarding Control Protocol (PFCP) session report.
    Here we aggregate the kernel tun interface counters + add a realistic
    memory utilisation signal (matches Use Case 1 from the paper).

    active_ue_count = number of PER-UE tunnel interfaces currently UP
                      (uesimtunX on UERANSIM, tun_srsue on srsRAN). On srsRAN
                      these live inside network namespaces, so a host-side
                      collector sees none of them and this reads 0; the byte
                      counters still come through via ogstun.
    db_session_count = count from Open5GS subscribers collection (includes
                       all registered UEs whether active or not).
    """
    total_rx = sum(s["rx_bytes"] for s in tun_stats.values())
    total_tx = sum(s["tx_bytes"] for s in tun_stats.values())

    # Count only PER-UE tunnels as UEs. ogstun is the UPF side of the data plane,
    # not a subscriber, so including it would report one phantom UE on srsRAN —
    # where the real per-UE tunnels live inside namespaces and are invisible here.
    active_ue_count = sum(1 for k in tun_stats
                          if k.startswith(("uesimtun", "tun_srsue")))

    # Simulate memory utilisation in the 4.7–4.9 % band with mild drift
    # (matches the Random Forest forecast in the paper's Figure 4)
    mem_base = 4.80
    noise = random.gauss(0, 0.04)
    mem_util = round(max(4.70, min(4.95, mem_base + noise)), 4)

    return {
        "total_rx_bytes":    total_rx,
        "total_tx_bytes":    total_tx,
        "active_ue_count":   active_ue_count,   # live tun interfaces (ground truth)
        "db_session_count":  session_count,      # registered in DB (may include inactive)
        "memory_util_pct":   mem_util,
        "active_bearers":    active_ue_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Collector loop
# ─────────────────────────────────────────────────────────────────────────────

class Collector:
    """Periodic data-collection service."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── public API ──────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Collector started (interval=%ds)", COLLECTOR_INTERVAL_SEC)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("Collector stopped")

    def collect_once(self) -> dict:
        """Run a single collection cycle and return what was written."""
        return self._collect()

    # ── internal ────────────────────────────────────────────────────────────

    def _run(self) -> None:
        if not ping():
            log.error("MongoDB not reachable — collector cannot start")
            return

        client      = get_client()
        open5gs_db  = client[OPEN5GS_DB]
        nwdaf_db    = client[NWDAF_DB]
        _ensure_ttl_indexes(client)

        while not self._stop_event.is_set():
            try:
                self._collect(open5gs_db, nwdaf_db)
            except Exception as exc:
                log.error("Collection cycle failed: %s", exc, exc_info=True)
            self._stop_event.wait(COLLECTOR_INTERVAL_SEC)

    def _collect(self, open5gs_db=None, nwdaf_db=None) -> dict:
        """One full collection + write cycle."""
        if open5gs_db is None or nwdaf_db is None:
            client     = get_client()
            open5gs_db = client[OPEN5GS_DB]
            nwdaf_db   = client[NWDAF_DB]
            _ensure_ttl_indexes(client)

        now      = datetime.now(timezone.utc)
        tun      = _read_tun_stats()
        sessions = _read_smf_sessions(open5gs_db)
        policies = _read_pcf_policies(open5gs_db)

        # ── UPF metrics ──────────────────────────────────────────────────
        upf_doc = {
            "timestamp":      now,
            "tun_interfaces": tun,
            **_simulate_upf_counters(tun, len(sessions)),
        }
        nwdaf_db[NWDAF_UPF_METRICS].insert_one(upf_doc)

        # ── SMF metrics ──────────────────────────────────────────────────
        # ambr_dl_mean: mean downlink AMBR (Mbps integer) across all subscriber
        # sessions. This is a Type P field — it directly reflects PolicyManager
        # writes to subscribers.session[].ambr and is the wireheading evidence
        # path for V7: H_policy write → collector → D_ana → H_kpi consumption.
        ambr_dl_values = [s["ambr_dl"] for s in sessions if s.get("ambr_dl", 0) > 0]
        ambr_dl_mean = sum(ambr_dl_values) / len(ambr_dl_values) if ambr_dl_values else 0.0
        smf_doc = {
            "timestamp":     now,
            "session_count": len(sessions),
            "sessions":      sessions,
            "ambr_dl_mean":  ambr_dl_mean,   # Type P: policy-derived AMBR in D_ana
            # Type P for the other two policy variables (E5). Same provenance
            # problem: a configured value republished as an analytic, untagged.
            "qos_5qi_mean":      _mean([s["qos_index"] for s in sessions
                                        if s.get("qos_index")]),
            "arp_priority_mean": _mean([s["arp_priority"] for s in sessions
                                        if s.get("arp_priority")]),
            "mbr_dl_mean":       _mean([s["mbr_dl"] for s in sessions
                                        if s.get("mbr_dl", 0) > 0]),
            "gbr_dl_mean":       _mean([s["gbr_dl"] for s in sessions
                                        if s.get("gbr_dl", 0) > 0]),
        }
        nwdaf_db[NWDAF_SMF_METRICS].insert_one(smf_doc)

        # ── PCF metrics ──────────────────────────────────────────────────
        pcf_doc = {
            "timestamp":    now,
            "policy_count": len(policies),
            "policies":     policies,
        }
        nwdaf_db[NWDAF_PCF_METRICS].insert_one(pcf_doc)

        log.debug(
            "Collected: UE sessions=%d  tun_ifaces=%d  policies=%d",
            len(sessions), len(tun), len(policies),
        )

        return {"upf": upf_doc, "smf": smf_doc, "pcf": pcf_doc}


# ─────────────────────────────────────────────────────────────────────────────
# Entry-point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import signal

    collector = Collector()
    collector.start()

    def _shutdown(sig, frame):  # noqa: ANN001
        log.info("Shutting down collector…")
        collector.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Press Ctrl-C to stop")
    while True:
        time.sleep(1)
