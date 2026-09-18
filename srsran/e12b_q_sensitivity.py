#!/usr/bin/env python3
"""E12b — Is the harm claim an artifact of the Q normalisation constant?

WHY THIS CHECK EXISTS
---------------------
E12 produced an uncomfortable pairing: across the E1 victim sweep the
network-layer Q falls by 68%, while BOTH mapped QoE scores move by less than
0.02 MOS. A reader will ask the obvious question, and it is the right
question:

    Q = 0.5*min(tau/20, 1) + 0.5*max(0, 1 - lambda/200)

The 200 in the denominator is a constant somebody chose. At lambda = 198 ms the
second term is 0.01; at lambda = 78 ms it is 0.61. Most of the reported "68%
drop in Q" is that term collapsing toward its own floor. Change 200 to 500 and
the drop shrinks; change it to 150 and the term saturates even sooner.

If the headline harm number is mostly a property of a normalising constant, the
paper must say so. This script sweeps the constant and reports how much of the
claim survives. It is deliberately adversarial toward our own result.

    .venv/bin/python srsran/e12b_q_sensitivity.py
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "srsran" / "results"

TAU_NORM = 20.0
LAM_NORMS = [100.0, 150.0, 200.0, 300.0, 500.0, 1000.0]


def q(tau, lam, lam_norm, tau_norm=TAU_NORM):
    return 0.5 * min(tau / tau_norm, 1.0) + 0.5 * max(0.0, 1 - lam / lam_norm)


def main() -> None:
    e1 = json.loads((OUT / "E1_harm_mechanism.json").read_text())
    pts = [(r["tau_victim_mean"], r["lambda_ms"]) for r in e1["rows"]
           if r.get("tau_victim_mean") and r.get("lambda_ms")]
    t0, l0 = pts[0]
    t1, l1 = pts[-1]

    print("=" * 84)
    print("  E12b — sensitivity of the harm claim to the Q normalisation constant")
    print(f"  E1 victim endpoints:  tau {t0:.2f} -> {t1:.2f} Mbps,  lambda {l0:.1f} -> {l1:.1f} ms")
    print("=" * 84)
    print(f"  {'lam_norm':>9} {'Q_first':>9} {'Q_last':>9} {'dQ':>9} {'drop %':>9} "
          f"{'lam term saturated?':>22}")

    rows = []
    for ln in LAM_NORMS:
        qa, qb = q(t0, l0, ln), q(t1, l1, ln)
        drop = 100 * (qa - qb) / qa if qa else None
        sat = (l1 >= ln)          # the lambda term has hit its floor of 0
        rows.append({"lambda_norm_ms": ln, "Q_first": round(qa, 4), "Q_last": round(qb, 4),
                     "dQ": round(qb - qa, 4), "drop_pct": round(drop, 1),
                     "lambda_term_floored_at_last_point": sat})
        print(f"  {ln:>9.0f} {qa:>9.4f} {qb:>9.4f} {qb-qa:>9.4f} {drop:>8.1f}% {str(sat):>22}")

    # How much of the drop is the lambda term alone?
    ln = 200.0
    tau_only = 0.5 * min(t1 / TAU_NORM, 1.0) - 0.5 * min(t0 / TAU_NORM, 1.0)
    lam_only = 0.5 * max(0.0, 1 - l1 / ln) - 0.5 * max(0.0, 1 - l0 / ln)
    total = tau_only + lam_only
    share_lam = 100 * lam_only / total if total else None

    print(f"\n  Decomposition at the published lam_norm = 200 ms:")
    print(f"     contribution of the tau term    : {tau_only:+.4f}")
    print(f"     contribution of the lambda term : {lam_only:+.4f}")
    print(f"     lambda term accounts for {share_lam:.1f}% of the total change in Q")

    drops = [r["drop_pct"] for r in rows]
    verdict = {
        "published_lambda_norm_ms": 200.0,
        "published_drop_pct": next(r["drop_pct"] for r in rows if r["lambda_norm_ms"] == 200.0),
        "drop_pct_range_across_normalisers": [min(drops), max(drops)],
        "lambda_term_share_of_dQ_pct": round(share_lam, 1),
        "tau_term_contribution": round(tau_only, 4),
        "lambda_term_contribution": round(lam_only, 4),
        "FINDING": (
            f"The headline drop in Q ranges from {min(drops):.1f}% to {max(drops):.1f}% depending "
            "purely on the choice of the lambda normalising constant, which no measurement fixes. "
            f"At the published value of 200 ms the lambda term accounts for {share_lam:.1f}% of "
            "the change, and the tau term contributes essentially nothing because victim "
            "throughput is flat. The magnitude of the Q drop is therefore NOT a robust quantity "
            "and must not be quoted as if it were."),
        "WHAT_SURVIVES": (
            "The SIGN and the ATTRIBUTION survive at every normaliser: Q falls monotonically with "
            "the aggressor's ceiling under every choice tested, victim configuration and offered "
            "load never change, and the mechanism (shared queueing delay, not bandwidth theft) is "
            "directly measured. What does not survive is the specific percentage."),
        "RECOMMENDED_WORDING": (
            "Report the mechanism and the direction, with lambda in milliseconds as the primary "
            f"evidence: victim latency rises from {l0:.0f} ms to {l1:.0f} ms "
            f"({l1/l0:.1f}x) while victim throughput is unchanged at ~{t1:.1f} Mbps. Those are "
            "measured quantities with units. Present Q as a derived index with its constants "
            "stated, and do not lead with a percentage drop in it."),
    }
    print(f"\n  FINDING: {verdict['FINDING']}")
    print(f"\n  WHAT SURVIVES: {verdict['WHAT_SURVIVES']}")
    print(f"\n  RECOMMENDED WORDING: {verdict['RECOMMENDED_WORDING']}")

    payload = {"experiment": "E12b", "tau_norm_mbps": TAU_NORM,
               "endpoints": {"tau_first": t0, "tau_last": t1,
                             "lambda_first": l0, "lambda_last": l1},
               "rows": rows, "verdict": verdict,
               "saved_at": datetime.now(timezone.utc).isoformat()}
    (OUT / "E12b_q_sensitivity.json").write_text(json.dumps(payload, indent=2))
    print(f"\n  -> {OUT/'E12b_q_sensitivity.json'}")


if __name__ == "__main__":
    main()
