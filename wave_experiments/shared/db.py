"""MongoDB utility helpers for wave experiments."""
import sys, time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
import pymongo
from wave_experiments.config import MONGO_URI_STANDARD, NWDAF_DB, OPEN5GS_DB

# ── Connection pool ────────────────────────────────────────────────────────────
_clients: dict[str, pymongo.MongoClient] = {}

def _client(uri: str = MONGO_URI_STANDARD) -> pymongo.MongoClient:
    if uri not in _clients:
        _clients[uri] = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _clients[uri]

def nwdaf_db(uri: str = MONGO_URI_STANDARD):
    return _client(uri)[NWDAF_DB]

def open5gs_db(uri: str = MONGO_URI_STANDARD):
    return _client(uri)[OPEN5GS_DB]

# ── Metric readers ─────────────────────────────────────────────────────────────
def read_latest(collection: str, field: str, uri: str = MONGO_URI_STANDARD):
    """Return most recent value of a field from an analytics collection."""
    doc = nwdaf_db(uri)[collection].find_one(
        {field: {"$exists": True}}, sort=[("timestamp", -1)]
    )
    return doc.get(field) if doc else None

def read_series(collection: str, field: str, n: int,
                uri: str = MONGO_URI_STANDARD) -> list:
    """Return last n values of a field (most-recent first)."""
    docs = list(
        nwdaf_db(uri)[collection]
        .find({field: {"$exists": True}}, {"_id": 0, field: 1, "timestamp": 1})
        .sort("timestamp", -1)
        .limit(n)
    )
    return [d[field] for d in docs]

def get_ambr_dl_mean(uri: str = MONGO_URI_STANDARD) -> float | None:
    """Return latest ambr_dl_mean from smf_metrics (Type-P metric)."""
    return read_latest("smf_metrics", "ambr_dl_mean", uri)

def get_session_count(uri: str = MONGO_URI_STANDARD) -> int | None:
    return read_latest("smf_metrics", "session_count", uri)

def get_active_ue_count(uri: str = MONGO_URI_STANDARD) -> int | None:
    return read_latest("upf_metrics", "active_ue_count", uri)

# ── Provenance record inspector (Exp 14) ──────────────────────────────────────
def classify_smf_record(doc: dict) -> str:
    """Classify a smf_metrics document as Type-T, Type-P, or Mixed."""
    has_type_t = "session_count" in doc   # derived from subscriber count
    has_type_p = "ambr_dl_mean" in doc    # derived from policy constants
    if has_type_t and has_type_p:
        return "Mixed"
    if has_type_p:
        return "Type-P"
    return "Type-T"

def get_smf_record_sample(n: int = 20, uri: str = MONGO_URI_STANDARD) -> list[dict]:
    """Return n recent smf_metrics records for taxonomy analysis."""
    return list(
        nwdaf_db(uri)["smf_metrics"]
        .find({}, {"_id": 0})
        .sort("timestamp", -1)
        .limit(n)
    )

# ── Subscriber / policy helpers ────────────────────────────────────────────────
def get_all_imsis(uri: str = MONGO_URI_STANDARD) -> list[str]:
    """Return list of registered IMSIs from open5gs.subscribers."""
    docs = list(open5gs_db(uri)["subscribers"].find({}, {"imsi": 1, "_id": 0}))
    return [d["imsi"] for d in docs if "imsi" in d]

def get_subscriber_ambr(imsi: str, uri: str = MONGO_URI_STANDARD) -> dict | None:
    """Return current AMBR for a subscriber."""
    doc = open5gs_db(uri)["subscribers"].find_one({"imsi": imsi})
    if not doc:
        return None
    try:
        sess = doc.get("slice", [{}])[0].get("session", [{}])[0]
        return {
            "ambr_dl": sess.get("ambr", {}).get("downlink", {}).get("value"),
            "ambr_ul": sess.get("ambr", {}).get("uplink", {}).get("value"),
        }
    except (IndexError, KeyError):
        return None

# ── Latency microbenchmark helper (Exp 10) ────────────────────────────────────
def time_mongo_write(collection: str = "smf_metrics",
                     uri: str = MONGO_URI_STANDARD) -> float:
    """Return wall-clock ms for a MongoDB insert + find_one roundtrip."""
    t0 = time.perf_counter()
    db = nwdaf_db(uri)
    doc = {"_bench": True, "timestamp": datetime.now(timezone.utc)}
    oid = db[collection].insert_one(doc).inserted_id
    db[collection].find_one({"_id": oid})
    db[collection].delete_one({"_id": oid})
    return (time.perf_counter() - t0) * 1000  # ms

def wait_for_fresh_metric(field: str, collection: str, older_than_ts,
                          timeout_s: float = 30, uri: str = MONGO_URI_STANDARD) -> bool:
    """Block until a metric newer than older_than_ts appears."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        doc = nwdaf_db(uri)[collection].find_one(
            {field: {"$exists": True}, "timestamp": {"$gt": older_than_ts}},
            sort=[("timestamp", -1)]
        )
        if doc:
            return True
        time.sleep(1)
    return False
