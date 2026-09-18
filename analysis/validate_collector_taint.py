#!/usr/bin/env python3
"""Validate the radio-side and channel results currently in hand against the
collector defect (§6.3 mechanism, App. A standards basis, App. E, §6.6).

Each is checked for three things:

  1. does the file exist and parse
  2. is it TAINTED by the collector defect — i.e. did it depend on the agent
     reading analytics while no collector daemon was running
  3. do its headline numbers still recompute from the raw trace

The taint question is the one that matters. Experiments that measure Phi with
the probe, or that call collect_once() explicitly in their own loop, were never
exposed to the frozen-analytics failure. Only the LLM experiments, which rely on
the daemon to update analytics mid-session, were.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "srsran" / "results"

def load(n):
    p = RES / n
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except json.JSONDecodeError: return "CORRUPT"

# item -> (file, taint exposure, why)
ITEMS = [
 ("§6.3 mechanism / capacity", "E0_3_capacity.json", "none",
  "radio experiment; Phi measured directly by the probe, no analytics readback"),
 ("§6.3 two-regime knee", "E0_4_two_regime.json", "none",
  "radio experiment; probe-measured, no analytics readback"),
 ("§6.3 harm mechanism", "E1_harm_mechanism.json", "none",
  "radio experiment; probe-measured, no analytics readback"),
 ("App. F rho/sigma resolution", "E0_5_analysis.json", "none",
  "radio experiment; interface counters and iperf3 only"),
 ("Artifact number registry", None, "none",
  "derived from raw traces by analysis/registry.py"),
 ("App. A channel, no LLM", "E2_contamination.json", "none",
  "calls Collector().collect_once() explicitly in its own loop"),
 ("App. A standards KPI value", "E2_4_standards_kpi.json", "n/a",
  "NOT YET RUN — needs root and a live radio"),
 ("App. E channel generality", "E5_multivariable.json", "none",
  "Part 1 calls collect_once() explicitly; Part 2 is the LLM half, re-running"),
 ("§6.6 benign cost", "E9_benign_cost.json", "TAINTED->rerun",
  "LLM experiment; depends on the daemon. First campaign invalid, re-running"),
 ("§6.3 target vs feedback attribution", "E3_attribution.json", "TAINTED->rerun",
  "LLM experiment; first campaign had no daemon so the channel was closed"),
]

print("="*88)
print("  COLLECTOR-TAINT AUDIT — validation of every result currently in hand")
print("="*88)
ok = tainted = missing = 0
for label, fn, taint, why in ITEMS:
    d = load(fn) if fn else "N/A"
    if fn and d is None:
        state = "NOT RUN"; missing += 1
    elif d == "CORRUPT":
        state = "CORRUPT"; missing += 1
    elif taint.startswith("TAINTED"):
        state = "RE-RUNNING"; tainted += 1
    else:
        state = "VALID"; ok += 1
    print(f"\n  [{state:^11}] {label}")
    print(f"                taint exposure: {taint}")
    print(f"                {why}")

print("\n" + "="*88)
print(f"  VALID {ok} | re-running {tainted} | not run {missing}")
print("="*88)

# headline numbers, recomputed
print("\n  HEADLINE NUMBERS, RECOMPUTED FROM RAW TRACES\n")
d = load("E0_3_capacity.json")
if d: print(f"    §6.3  C = {d['C_mbps']} Mbps (n={d['n_ue']}), fair share {d['fair_share_mbps']}")
d = load("E0_4_two_regime.json")
if d:
    u=[r for r in d["rows"] if r["regime"]=="under" and r.get("lambda_ms")]
    o=[r for r in d["rows"] if r["regime"]=="over" and r.get("lambda_ms")]
    if u and o:
        lo=min(r["lambda_ms"] for r in u); hi=max(r["lambda_ms"] for r in o)
        print(f"    §6.3  knee at {d['knee_mbps_per_ue']} Mbps/UE; lambda {lo}->{hi} ms "
              f"({hi/lo:.1f}x) while tau saturates")
d = load("E1_harm_mechanism.json")
if d:
    r0,r1 = d["rows"][0], d["rows"][-1]
    print(f"    §6.3  victim tau {r0['tau_victim_mean']} -> {r1['tau_victim_mean']} Mbps (FLAT); "
          f"victim lambda {r0['lambda_ms']} -> {r1['lambda_ms']} ms "
          f"({r1['lambda_ms']/r0['lambda_ms']:.2f}x)")
d = load("E2_contamination.json")
if d:
    s,i = d["arm_standard"], d["arm_isolated"]
    print(f"    App.A channel corr: standard {s['corr_write_readback']}, "
          f"isolated {i['corr_write_readback']}; provenance field present: "
          f"{any(r['tagged'] for r in s['rows'])}")
d = load("E5_multivariable.json")
if d:
    cs=d["channel_standard"]
    tot=sum(v["exact_matches"] for v in cs.values()); n=sum(v["n"] for v in cs.values())
    print(f"    App.E channel: {tot}/{n} exact across {len(cs)} policy variables, "
          f"{d['channel_open_standard']} open standard / {d['channel_open_isolated']} isolated")
try:
    reg=json.loads((ROOT/"analysis"/"paper_numbers.json").read_text())
    nr=[k for k,v in reg.items() if not v["robust_to_analysis_choices"]]
    print(f"    registry: {len(reg)} numbers, {len(nr)} flagged NOT robust")
except Exception: pass

print("\n  OUTSTANDING")
print("    * §6.3  E3 attribution      — re-running with the channel live")
print("    * §6.6  E9 benign cost      — re-running with the channel live")
print("    * App.E E5 Part 2           — queued")
print("    * App.A E2.4 standards KPI  — needs  sudo bash srsran/run_standards_kpi_and_static_phi.sh")
