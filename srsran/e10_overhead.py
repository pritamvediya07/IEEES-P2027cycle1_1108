#!/usr/bin/env python3
"""E10 — Oversight overhead at the policy-application boundary  (paper §6.6, RQ5).

§6.6 asks what the defenses cost at runtime. The honest framing matters as much as
the number: this overhead sits on the MANAGEMENT plane, not the user plane. The
standard already rate-limits successive policy updates on a slice, so the
comparison that means anything is against that inter-update interval, not
against a packet-forwarding budget. A defense that adds a millisecond to an
operation the standard expects you to perform every few seconds is free in any
sense an operator cares about.

Four arms, n >= 100 each:

    | arm         | drift bound | isolated collector |
    | none        | no          | no                 |
    | drift       | yes         | no                 |
    | iso         | no          | yes                |
    | both        | yes         | yes                |

Reports p50/p95/p99/mean per arm, plus KPI query latency separately, since a
consumer reading analytics pays that cost whether or not a gate is installed.

No model, no radio, no root.

    .venv/bin/python srsran/e10_overhead.py --n 120
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics as st
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.preconditions import assert_ready              # noqa: E402

OUT = ROOT / "srsran" / "results"
SLICE = "internet"
BASELINE = 20.0
THETA = 2.0
# TS 28.532 / operator practice: successive slice policy modifications are
# rate-limited on the order of seconds. This is the yardstick, not a packet budget.
MGMT_PLANE_INTERVAL_MS = 1000.0


def _quiet():
    for n in ("COLLECTOR", "pymongo", "pymongo.serverSelection"):
        logging.getLogger(n).setLevel(logging.ERROR)


def drift_gate(target: float) -> bool:
    """The whole defense: one comparison against the policy state."""
    return target <= BASELINE * THETA


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = min(len(xs) - 1, int(round((p / 100.0) * (len(xs) - 1))))
    return round(xs[k], 4)


def summarise(xs):
    return {"n": len(xs), "mean_ms": round(st.mean(xs), 4),
            "p50_ms": pct(xs, 50), "p95_ms": pct(xs, 95), "p99_ms": pct(xs, 99),
            "min_ms": round(min(xs), 4), "max_ms": round(max(xs), 4),
            "stdev_ms": round(st.stdev(xs), 4) if len(xs) > 1 else 0.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120)
    a = ap.parse_args()
    _quiet()
    assert_ready(need_core=False)
    OUT.mkdir(parents=True, exist_ok=True)

    from tools.policy_manager import PolicyManager
    from tools.kpi_analyzer import KPIAnalyzer
    from collector.collector import Collector
    from collector.collector_isolated import IsolatedCollector

    pm, ka = PolicyManager(), KPIAnalyzer()
    std_c, iso_c = Collector(), IsolatedCollector(write_port=27017)

    print("=" * 78)
    print(f"  E10 — oversight overhead, n = {a.n} per arm")
    print("=" * 78)

    arms = {"none": (False, False), "drift": (True, False),
            "iso": (False, True), "both": (True, True)}
    results = {}

    for arm, (use_drift, use_iso) in arms.items():
        lat, gate_only, rejected = [], [], 0
        for i in range(a.n):
            target = BASELINE * (1.0 + (i % 3) * 0.2)      # 20, 24, 28 Mbps — all pass the bound
            t0 = time.perf_counter()
            if use_drift:
                g0 = time.perf_counter()
                ok = drift_gate(target)
                gate_only.append((time.perf_counter() - g0) * 1e3)
                if not ok:
                    rejected += 1
                    lat.append((time.perf_counter() - t0) * 1e3)
                    continue
            pm.apply_policy(SLICE, int(target * 1e6), int(target * 1e6), reason="E10")
            (iso_c if use_iso else std_c).collect_once()
            lat.append((time.perf_counter() - t0) * 1e3)
        results[arm] = summarise(lat)
        results[arm].update({"drift_bound": use_drift, "isolated_collector": use_iso,
                             "rejected_by_gate": rejected})
        if gate_only:
            results[arm]["gate_check_only"] = summarise(gate_only)
        print(f"  {arm:<7} mean {results[arm]['mean_ms']:>8.2f}  p50 {results[arm]['p50_ms']:>8.2f}"
              f"  p95 {results[arm]['p95_ms']:>8.2f}  p99 {results[arm]['p99_ms']:>8.2f} ms")

    # ── KPI query latency, measured separately ────────────────────────────
    kq = []
    for _ in range(a.n):
        t0 = time.perf_counter()
        ka.analyze("ambr_dl_mean", n_samples=10, run_ml=False)
        kq.append((time.perf_counter() - t0) * 1e3)
    kpi = summarise(kq)
    print(f"\n  KPI query   mean {kpi['mean_ms']:>8.2f}  p50 {kpi['p50_ms']:>8.2f}"
          f"  p95 {kpi['p95_ms']:>8.2f}  p99 {kpi['p99_ms']:>8.2f} ms")

    base = results["none"]["mean_ms"]
    deltas = {arm: {"delta_ms": round(results[arm]["mean_ms"] - base, 4),
                    "delta_pct_vs_none": round(100 * (results[arm]["mean_ms"] - base) / base, 2),
                    "pct_of_mgmt_plane_interval": round(
                        100 * (results[arm]["mean_ms"] - base) / MGMT_PLANE_INTERVAL_MS, 4)}
              for arm in arms if arm != "none"}

    print(f"\n  {'arm':<7} {'delta vs none':>15} {'as % of none':>14} "
          f"{'as % of 1s mgmt interval':>26}")
    for arm, d in deltas.items():
        print(f"  {arm:<7} {d['delta_ms']:>13.3f} ms {d['delta_pct_vs_none']:>13.2f}% "
              f"{d['pct_of_mgmt_plane_interval']:>25.4f}%")

    worst = max(deltas.values(), key=lambda d: d["delta_ms"])
    verdict = {
        "framing": ("this is management-plane cost. The standard rate-limits successive slice "
                    "policy modifications on the order of seconds, so the meaningful denominator "
                    f"is that interval (~{MGMT_PLANE_INTERVAL_MS:.0f} ms), not a user-plane budget."),
        "worst_arm_delta_ms": worst["delta_ms"],
        "worst_arm_pct_of_mgmt_interval": worst["pct_of_mgmt_plane_interval"],
        "drift_bound_cost": ("a single float comparison against the policy state; its own cost is "
                             "in the microseconds and is dominated entirely by the database write "
                             "it precedes."),
        "conclusion": (
            f"The most expensive arm adds {worst['delta_ms']:.2f} ms per policy call, which is "
            f"{worst['pct_of_mgmt_plane_interval']:.4f}% of a one-second management-plane update "
            "interval. Neither defense is on the user-plane data path at all: the drift bound is "
            "one comparison at the policy-application boundary, and IsolatedCollector changes "
            "where the collector writes, not how often anything is forwarded."),
    }
    print(f"\n  {verdict['conclusion']}")

    payload = {"experiment": "E10", "model": "none", "n_per_arm": a.n,
               "mgmt_plane_interval_ms": MGMT_PLANE_INTERVAL_MS,
               "arms": results, "kpi_query_latency": kpi, "deltas_vs_none": deltas,
               "verdict": verdict, "saved_at": datetime.now(timezone.utc).isoformat()}
    (OUT / "E10_overhead.json").write_text(json.dumps(payload, indent=2))
    pm.apply_policy(SLICE, int(BASELINE * 1e6), int(BASELINE * 1e6), reason="E10 restore")
    print(f"\n  -> {OUT/'E10_overhead.json'}\n  baseline AMBR restored")


if __name__ == "__main__":
    main()
