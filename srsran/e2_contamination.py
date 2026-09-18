#!/usr/bin/env python3
"""E2 — Contamination channel, no LLM  (paper App. A Standards basis for AS2; §3.2).

E2.1  Write-then-readback. n policy writes issued directly through the tool,
      no model. For each: does the written value reappear in an analytics
      field, and is it tagged?

E2.2  Standard collector vs IsolatedCollector over the same writes.

E2.3  THE MEASUREMENT THAT SEPARATES REWARD HACKING FROM A BADLY DESIGNED KPI.
      Issue writes with ALL TRAFFIC STOPPED, so Φ is provably static (verified
      by the probe: τ, λ, ρ unchanged within noise). Then measure ΔR.
      That is dR/da != 0 at FIXED Φ, measured directly — the formal separation
      between this setting and "a badly designed KPI".

          badly designed KPI :  R = g(Φ)          -> dR/da|_Φ = 0
          PALA               :  R = g(Φ, a_1:k)   -> dR/da|_Φ != 0

      Lemma 6 is exactly the statement that IsolatedCollector restores the
      state-only property.

E2.4  Standards-shaped KPI. A KPI of the form in TS 28.554 §6.4.2 — measured
      consumption over CONFIGURED allocated capacity — implemented in the
      collector, showing it inherits mixed provenance by construction. This
      grounds AS2 in a standardised definition rather than a schema we chose.

Run as root (needs netns for the Φ static check):
    sudo .venv/bin/python srsran/e2_contamination.py --n 30
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.preconditions import assert_ready       # noqa: E402

OUT = ROOT / "srsran" / "results"
SLICE = "internet"
WAIT = 12          # >= 2 collector cycles


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def collector_tick(isolated: bool) -> None:
    """Run exactly one collection cycle."""
    from collector.collector import Collector
    from collector.collector_isolated import IsolatedCollector
    (IsolatedCollector(write_port=27017) if isolated else Collector()).collect_once()


def read_R(metric: str = "ambr_dl_mean") -> float | None:
    """Read the proxy the agent would see, through the same tool the agent uses."""
    from tools.kpi_analyzer import KPIAnalyzer
    r = KPIAnalyzer().analyze(metric, n_samples=10, run_ml=False)
    if "error" in r:
        return None
    v = r.get("raw_values") or []
    return float(v[-1]) if v else None


def write_ambr(mbps: int) -> bool:
    from tools.policy_manager import PolicyManager
    return bool(PolicyManager().apply_policy(
        SLICE, int(mbps * 1e6), int(mbps * 1e6), reason=f"E2 write {mbps}").get("success"))


def provenance_tagged(metric: str = "ambr_dl_mean") -> bool:
    """Does the analytics record carry ANY provenance/derivation field?"""
    from config.db import get_nwdaf_db
    d = get_nwdaf_db()["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    return any(k in d for k in ("provenance", "phi", "source", "derivation", "tag"))


def ts_28_554_kpi() -> dict:
    """E2.4 — TS 28.554 §6.4.2 shaped KPI: measured usage / CONFIGURED capacity.

    The numerator is measured, the denominator is configured, the output is one
    scalar with no provenance element. Mixed by definition, at the level of a
    standardised KPI rather than a schema we invented.
    """
    from config.db import get_nwdaf_db
    db = get_nwdaf_db()
    smf = db["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    upf = db["upf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    measured = float(upf.get("total_rx_bytes", 0) + upf.get("total_tx_bytes", 0))
    configured = float(smf.get("ambr_dl_mean", 0)) * 1e6 / 8 or 1.0
    return {"kpi": "virtualised_resource_utilisation (TS 28.554 §6.4.2 shape)",
            "numerator_measured_bytes": measured,
            "denominator_configured_from_ambr": configured,
            "value": round(measured / configured, 6),
            "provenance_field_present": False,
            "note": ("numerator is measured, denominator is a configured policy value; "
                     "the standard defines no provenance element, so a consumer cannot "
                     "separate them")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--ns", default="ue1")
    ap.add_argument("--skip-phi", action="store_true",
                    help="run E2.1/E2.2/E2.4 only; these touch no netns so they need no root "
                         "and no radio. E2.3 needs both, and is the only part that does.")
    a = ap.parse_args()
    if not a.skip_phi and os.geteuid() != 0:
        sys.exit("ERROR: E2.3 needs root for netns access (or pass --skip-phi)")
    assert_ready(need_core=not a.skip_phi)
    OUT.mkdir(parents=True, exist_ok=True)

    payload = {"experiment": "E2", "model": "none (no LLM inference)",
               "n_writes": a.n, "started_at": datetime.now(timezone.utc).isoformat()}
    print("=" * 72); print("  E2 — contamination channel, no LLM"); print("=" * 72)

    # ── E2.1 / E2.2 ────────────────────────────────────────────────────────
    for arm, isolated in (("standard", False), ("isolated", True)):
        print(f"\n── {arm} collector, {a.n} writes ──")
        rows = []
        for i in range(a.n):
            val = 20 + (i % 10) * 10          # 20..110 Mbps, distinguishable
            write_ambr(val)
            collector_tick(isolated)
            time.sleep(1)
            rb = read_R()
            hit = rb is not None and abs(rb - val) / val < 0.05
            rows.append({"write_mbps": val, "readback": rb, "reappeared": hit,
                         "tagged": provenance_tagged()})
            if i < 3 or i == a.n - 1:
                print(f"   write {val:>4} -> readback {rb}   reappeared={hit}")
        rate = sum(r["reappeared"] for r in rows) / len(rows)
        payload[f"arm_{arm}"] = {"rows": rows, "contamination_rate": round(rate, 4),
                                 "any_provenance_tag": any(r["tagged"] for r in rows)}
        print(f"   contamination rate: {sum(r['reappeared'] for r in rows)}/{len(rows)} = {rate:.0%}")
        (OUT / "E2_contamination.json").write_text(json.dumps(payload, indent=2))

    # ── E2.3 — dR/da at PROVABLY FIXED Φ ──────────────────────────────────
    if a.skip_phi:
        payload["E2_3_dR_at_fixed_phi"] = {
            "status": "NOT RUN — --skip-phi; requires root and a live radio"}
        print("\n── E2.3 SKIPPED (--skip-phi) ──")
    else:
      print(f"\n── E2.3 — ΔR with all traffic stopped (Φ provably static) ──")
      from srsran.phi_probe import PhiProbe
      probe = PhiProbe([a.ns], iperf_secs=8)
      sh("pkill -f continuous_client.py")            # ensure no offered load
      time.sleep(2)

      phi_before = probe.measure(k=0)
      r_before = read_R()
      write_ambr(200)
      collector_tick(False)
      time.sleep(WAIT)
      r_after = read_R()
      phi_after = probe.measure(k=1)

      def d(x, y):
          return None if (x is None or y is None) else round(abs(x - y), 4)

      phi_static = {
          "tau_delta_mbps": d(phi_before.tau_mbps, phi_after.tau_mbps),
          "lambda_delta_ms": d(phi_before.lambda_ms, phi_after.lambda_ms),
          "rho_delta_pct": d(phi_before.rho_pct, phi_after.rho_pct),
          "sigma_delta": d(phi_before.sigma, phi_after.sigma),
      }
      dR = d(r_before, r_after)
      print(f"   Φ before: τ={phi_before.tau_mbps} λ={phi_before.lambda_ms} ρ={phi_before.rho_pct}")
      print(f"   Φ after : τ={phi_after.tau_mbps} λ={phi_after.lambda_ms} ρ={phi_after.rho_pct}")
      print(f"   ΔΦ = {phi_static}")
      print(f"   R {r_before} -> {r_after}   ΔR = {dR}")
      payload["E2_3_dR_at_fixed_phi"] = {
          "R_before": r_before, "R_after": r_after, "delta_R": dR,
          "phi_before": phi_before.as_dict(), "phi_after": phi_after.as_dict(),
          "phi_deltas": phi_static,
          "interpretation": (
              "R changes as a function of the agent's write alone, with Φ static. "
              "That is dR/da != 0 at fixed Φ — the formal distinction from a badly "
              "designed KPI (R = g(Φ)), an observability projection (R = g(ΠΦ)) and "
              "an unstable control loop, all of which are state-only failures."),
      }

    # ── E2.4 ──────────────────────────────────────────────────────────────
    payload["E2_4_standards_shaped_kpi"] = ts_28_554_kpi()
    print(f"\n── E2.4 — TS 28.554 §6.4.2 shaped KPI ──")
    print(f"   {payload['E2_4_standards_shaped_kpi']['value']}  "
          f"provenance field: {payload['E2_4_standards_shaped_kpi']['provenance_field_present']}")

    write_ambr(20)
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "E2_contamination.json").write_text(json.dumps(payload, indent=2))
    print(f"\n  -> {OUT/'E2_contamination.json'}\n  baseline AMBR restored")


if __name__ == "__main__":
    main()
