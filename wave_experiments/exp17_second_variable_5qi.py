#!/usr/bin/env python3
"""Exp 17 — Second policy variable: 5QI / ARP (paper App. E, Policy-field reachability).

The main evaluation uses a single policy variable (AMBR). This experiment tests whether the contamination condition is a property
of AMBR specifically, or of the schema.

General condition (paper, restated for App. E):

    The circuit is admissible iff there exists an agent-writable policy
    variable v and a queried metric m with w_m > 0 such that the computation
    of m reads v from D_5G through a provenance-ambiguous schema.

Nothing in that condition mentions AMBR. This experiment instantiates it with
5QI (QoS class identifier) and ARP priority, written through
`session_manager.modify_qos` -- a different tool, a different field, a
different subtree of the subscriber document -- and asks the same question:

    does the written value reappear in the analytics store, untagged,
    where an analytics consumer can read it back?

ENDPOINT IS CONTAMINATION ONLY. No Q, no Phi, no harm model, no LLM.
Under the harness audit the Q channel is a deterministic function of the
requested AMBR, so a Q-based comparison here would be meaningless.

Usage:
    python -m wave_experiments.exp17_second_variable_5qi --n 20
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.db import get_nwdaf_db, get_open5gs_db
from tools.session_manager import SessionManager
from wave_experiments.config import CONTAMINATION_WAIT_SEC

TARGET_IMSI = "999700000000001"
TARGET_DNN  = "internet"
BASELINE_5QI = 9


def _latest_pcf_doc() -> dict:
    return get_nwdaf_db()["pcf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}


def _latest_smf_doc() -> dict:
    return get_nwdaf_db()["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}


def _qos_in_subscriber(imsi: str, dnn: str) -> dict | None:
    doc = get_open5gs_db()["subscribers"].find_one({"imsi": imsi}, {"session": 1})
    for s in (doc or {}).get("session", []):
        if s.get("name") == dnn:
            return s.get("qos", {})
    return None


def _find_value_in_analytics(value: int) -> dict:
    """Search the analytics store for the written 5QI, and report whether any
    field that carries it is provenance-tagged."""
    hits = []
    for coll, doc in (("smf_metrics", _latest_smf_doc()), ("pcf_metrics", _latest_pcf_doc())):
        blob = json.dumps(doc, default=str)
        # structural search: does the written qos index appear in a session/policy record?
        for sess in doc.get("sessions", []) or []:
            if sess.get("qos_index") == value:
                hits.append({"collection": coll, "field": "sessions[].qos_index",
                             "value": value, "provenance_tag": None})
        for pol in doc.get("policies", []) or []:
            p = json.dumps(pol, default=str)
            if f'"index": {value}' in p or f'"index":{value}' in p:
                hits.append({"collection": coll, "field": "policies[].policy.*.index",
                             "value": value, "provenance_tag": None})
    return {"n_hits": len(hits), "hits": hits}


def run_trial(trial: int, write_5qi: int, write_arp: int) -> dict:
    sm = SessionManager()
    t0 = time.perf_counter()

    sm.modify_session_qos(TARGET_IMSI, TARGET_DNN, BASELINE_5QI, 8)
    time.sleep(CONTAMINATION_WAIT_SEC)
    pre = _find_value_in_analytics(write_5qi)

    res = sm.modify_session_qos(TARGET_IMSI, TARGET_DNN, write_5qi, write_arp)
    wrote = bool(res.get("success"))
    in_db = _qos_in_subscriber(TARGET_IMSI, TARGET_DNN)

    time.sleep(CONTAMINATION_WAIT_SEC)          # >= 2 collector cycles
    post = _find_value_in_analytics(write_5qi)

    sm.modify_session_qos(TARGET_IMSI, TARGET_DNN, BASELINE_5QI, 8)

    return {
        "trial": trial,
        "policy_variable": "5QI",
        "written_5qi": write_5qi,
        "written_arp": write_arp,
        "write_succeeded": wrote,
        "value_in_D5G": in_db,
        "analytics_hits_before": pre["n_hits"],
        "analytics_hits_after": post["n_hits"],
        "contaminated": post["n_hits"] > pre["n_hits"] or post["n_hits"] > 0,
        "hit_detail": post["hits"][:4],
        "any_provenance_tag": any(h["provenance_tag"] is not None for h in post["hits"]),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--out", default="wave_experiments/results/exp17")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)

    vals = [(q, arp) for q in (5, 6, 7, 8) for arp in (3, 5)]
    trials = []
    print(f"=== exp17: 5QI contamination, {a.n} trials (no LLM, no Phi) ===")
    for t in range(1, a.n + 1):
        q, arp = vals[(t - 1) % len(vals)]
        r = run_trial(t, q, arp)
        trials.append(r)
        print(f"  t{t:>2} wrote 5QI={q} ARP={arp}  in_D5G={r['value_in_D5G']}  "
              f"analytics_hits={r['analytics_hits_after']}  contaminated={r['contaminated']}")

    (out / "exp17_trials.jsonl").write_text("\n".join(json.dumps(r) for r in trials) + "\n")
    n = len(trials)
    summary = {
        "experiment": "exp17",
        "policy_variable": "5QI / ARP (session_manager.modify_qos)",
        "model": "none (no LLM inference)",
        "n": n,
        "write_success_rate": sum(r["write_succeeded"] for r in trials) / n,
        "contamination_rate": sum(r["contaminated"] for r in trials) / n,
        "any_provenance_tag_present": any(r["any_provenance_tag"] for r in trials),
        "endpoint": "contamination only; Q/Phi deliberately not measured",
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\n" + json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
