#!/usr/bin/env python3
"""E1 — Harm mechanism: ASYMMETRIC over-provisioning  (paper §6.3 Physical-harm mechanism; §6.3 Target versus feedback).

WHY THIS EXPERIMENT AND NOT E0.4
---------------------------------
E0.4 swept every UE's AMBR together. All four then saturate at the same fair
share C/n, so nobody is worse off than anybody else and there is no victim.
Q fell only because latency rose for everyone equally.

The reward-hacking scenario in the paper is asymmetric: the agent raises ONE
slice's ceiling, that slice takes a larger share of a FIXED C, and the other
slices degrade. That is where Definition 4 actually bites, and it is what
§6.3 (Target versus feedback) separates from "the operator's target was unsafe".

DESIGN
------
  aggressor  ue1        AMBR swept from baseline up to >> C
  victims    ue2..ue4   AMBR pinned at baseline for the whole run

  Fixed for the entire campaign, and never touched by the sweep:
    * cell capacity C          (srsRAN MAC scheduler over a fixed PRB pool)
    * victim AMBR              (baseline)
    * offered load per UE      (saturating)

  Only the aggressor's ceiling moves. So any change in victim throughput is
  caused by contention for C, not by anything the harness did to the victims.
  That is the spec §0 separation, applied to the harm measurement itself.

WHAT IT ANSWERS
---------------
  §6.3 mechanism: over-provisioning does not reduce YOUR rate, it takes
        capacity from OTHERS and inflates queueing delay.
  §6.3 attribution: victim degradation is agent-attributable by construction —
        the victims' own configuration never changes.
  §6.3 regimes: below the knee the aggressor gains with no victim cost;
        above it the gain is purely redistributive.

Run as root:
    sudo .venv/bin/python srsran/e1_harm_mechanism.py --n-ue 4
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

from srsran.phi_probe import PhiProbe                     # noqa: E402
from srsran.ambr_enforcer import AmbrEnforcer             # noqa: E402
from srsran.preconditions import assert_ready       # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"
UNLIMITED = 10_000


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def kill_all():
    for sig in ("TERM", "KILL"):
        for pat in ("srsue/src/srsue", "apps/gnb/gnb", "gr_broker.py"):
            sh(f"pkill -{sig} -f '{pat}'")
        time.sleep(2)


def ue_ip(ns):
    r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def bring_up(n: int) -> dict[str, str]:
    """gNB -> all UEs -> broker LAST (srsRAN docs; validated at n=4 in E0.2)."""
    kill_all(); RUN.mkdir(exist_ok=True)
    subprocess.Popen([str(GNB_BIN), "-c", str(CFG / "gnb_zmq.yml")],
                     stdout=open(RUN / "gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    conf = (lambda i: CFG / (f"ue{i}_mux.conf" if n > 1 else f"ue{i}.conf"))
    for i in range(1, n + 1):
        subprocess.Popen([str(UE_BIN), str(conf(i))],
                         stdout=open(RUN / f"ue{i}.stdout", "w"), stderr=subprocess.STDOUT)
        time.sleep(3)
    if n > 1:
        subprocess.Popen([SYS_PY, str(BROKER), "--n-ue", str(n),
                          "--srate", "23.04e6", "--slow-down-ratio", "1"],
                         stdout=open(RUN / "broker.stdout", "w"), stderr=subprocess.STDOUT)
        time.sleep(4)
    att = {}
    for _ in range(30):
        time.sleep(2)
        att = {f"ue{i}": ue_ip(f"ue{i}") for i in range(1, n + 1)}
        if all(att.values()):
            break
    for ns, ip in att.items():
        if ip:
            sh(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])
            sh(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", GW,
                "dev", "tun_srsue"])
    return att


def q_of(tau_ue, lam):
    """Two-dimensional Q. rho and sigma are DELIBERATELY excluded:
    E0.4 showed sigma is constant by construction (n fixed) and the rho
    accounting failed its own validity cross-check. Padding Q with constants is
    the defect in the original Table 11."""
    if tau_ue is None or lam is None:
        return None
    return round(0.5 * min(tau_ue / 20.0, 1.0) + 0.5 * max(0.0, 1 - lam / 200.0), 4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--points", type=int, default=8)
    ap.add_argument("--iperf-secs", type=int, default=12)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    assert_ready()
    OUT.mkdir(parents=True, exist_ok=True)
    n = a.n_ue

    print("=" * 74)
    print(f"  E1 — asymmetric harm:  ue1 escalates, ue2..ue{n} pinned at baseline")
    print("=" * 74)

    att = bring_up(n)
    up = [ns for ns, ip in att.items() if ip]
    print(f"\n  attached: {att}")
    if len(up) < n:
        sys.exit(f"ERROR: only {len(up)}/{n} attached")

    probe = PhiProbe(up, iperf_secs=a.iperf_secs)
    if not probe.selftest():
        sys.exit("ERROR: probe self-test failed — refusing to record estimated data")

    enf = AmbrEnforcer(); enf.setup()
    ips = {ns: att[ns] for ns in up}
    aggressor, victims = up[0], up[1:]

    # ── measure C with everyone unlimited ──────────────────────────────────
    for ip in ips.values():
        enf.set_ue_ambr(ip, UNLIMITED)
    time.sleep(3)
    cap = PhiProbe(up, iperf_secs=30).measure(k=0)
    C = cap.tau_mbps
    if C is None:
        sys.exit("ERROR: could not measure C — refusing to guess")
    baseline = round(C / n, 2)
    probe.capacity_hint = C
    enf.assert_not_bottleneck(C)
    print(f"\n  C = {C:.2f} Mbps   baseline (fair share) = {baseline} Mbps/UE")
    print(f"  aggressor = {aggressor}   victims = {victims}")

    sweep = [round(baseline * m, 2) for m in (1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)][:a.points]
    print(f"  ue1 AMBR sweep: {sweep}   (victims pinned at {baseline})\n")

    rows = []
    payload = {"experiment": "E1", "design": "asymmetric over-provisioning",
               "n_ue": n, "C_mbps": round(C, 2), "baseline_mbps": baseline,
               "aggressor": aggressor, "victims": victims, "sweep_mbps": sweep,
               "fixed_during_campaign": ["cell capacity C", "victim AMBR", "offered load"],
               "Q_definition": "0.5*min(tau/20,1) + 0.5*max(0,1-lambda/200); rho and sigma excluded",
               "started_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    res = OUT / "E1_harm_mechanism.json"

    print(f"  {'ue1 AMBR':>9} {'tau_ue1':>8} {'tau_vict':>9} {'lam':>7} {'Q_vict':>7} {'dQ_vict':>8}")
    q_v0 = None
    for j, B in enumerate(sweep, 1):
        enf.set_ue_ambr(ips[aggressor], B)
        for v in victims:
            enf.set_ue_ambr(ips[v], baseline)
        time.sleep(3)
        rec = probe.measure(k=j)
        per = rec.per_ue_tau or {}
        t_a = per.get(aggressor)
        vt = [per.get(v) for v in victims if per.get(v) is not None]
        t_v = (sum(vt) / len(vt)) if vt else None
        q_v = q_of(t_v, rec.lambda_ms)
        q_a = q_of(t_a, rec.lambda_ms)
        if q_v0 is None:
            q_v0 = q_v
        dq = None if (q_v is None or q_v0 is None) else round(q_v - q_v0, 4)
        rows.append({"ue1_ambr_mbps": B, "ratio_to_baseline": round(B / baseline, 2),
                     "tau_aggressor": t_a, "tau_victim_mean": round(t_v, 3) if t_v else None,
                     "tau_total": rec.tau_mbps, "lambda_ms": rec.lambda_ms,
                     "rho_pct": rec.rho_pct, "rho_source": rec.rho_source,
                     "Q_victim": q_v, "Q_aggressor": q_a, "dQ_victim": dq,
                     "per_ue_tau": per, "complete": rec.complete})
        payload["rows"] = rows
        res.write_text(json.dumps(payload, indent=2))
        print(f"  {B:>9.2f} {str(t_a):>8} {str(round(t_v,2) if t_v else None):>9} "
              f"{str(rec.lambda_ms):>7} {str(q_v):>7} {str(dq):>8}"
              f"{'' if rec.complete else '  INCOMPLETE'}")

    # ── verdict ────────────────────────────────────────────────────────────
    ok = [r for r in rows if r["tau_victim_mean"] and r["tau_aggressor"]]
    verdict = {}
    if len(ok) >= 2:
        first, last = ok[0], ok[-1]
        v_drop = 100 * (first["tau_victim_mean"] - last["tau_victim_mean"]) / first["tau_victim_mean"]
        a_gain = 100 * (last["tau_aggressor"] - first["tau_aggressor"]) / max(first["tau_aggressor"], 1e-9)
        dq = last["dQ_victim"]
        verdict = {"victim_tau_drop_pct": round(v_drop, 1),
                   "aggressor_tau_gain_pct": round(a_gain, 1),
                   "victim_dQ": dq,
                   "harm_is_agent_attributable": True,
                   "why": ("victim AMBR, offered load and C were all fixed; only the "
                           "aggressor's ceiling changed, so any victim degradation is "
                           "caused by contention the agent created"),
                   "def4_victim": bool(dq is not None and dq < 0)}
        print(f"\n  victim τ: {first['tau_victim_mean']:.2f} -> {last['tau_victim_mean']:.2f} Mbps "
              f"({v_drop:+.1f}%)")
        print(f"  aggressor τ: {first['tau_aggressor']:.2f} -> {last['tau_aggressor']:.2f} Mbps "
              f"({a_gain:+.1f}%)")
        print(f"  victim ΔQ: {dq}")
        print(f"  Def.4 satisfied for the VICTIM: {verdict['def4_victim']}")
    payload["verdict"] = verdict
    try:
        probe.assert_dimensions_vary()
        payload["degeneracy_check"] = "PASS"
    except AssertionError as ex:
        payload["degeneracy_check"] = f"FLAGGED — {ex}"
        print(f"\n  degeneracy: {ex}")
    payload["probe_summary"] = probe.summary()
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    res.write_text(json.dumps(payload, indent=2))
    probe.save(OUT / "E1_phi_trace.jsonl")
    enf.teardown(); kill_all()
    print(f"\n  -> {res}\n  -> {OUT/'E1_phi_trace.jsonl'}")


if __name__ == "__main__":
    main()
