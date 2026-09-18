#!/usr/bin/env python3
"""Pre-flight: does the enforcement point actually shape, and does crossing the
knee actually lower Q?

Three attempts at Definition 4 have now failed for measurement reasons rather
than because the phenomenon is absent, and each time the run started already
saturated. Rather than spend another two hours discovering a fourth, this checks
the two physical facts the experiment depends on, in about ten minutes:

  1. ENFORCEMENT   with a B Mbps/UE ceiling, aggregate tau must not exceed n*B.
                   If it does, the HTB class is not shaping and every Q0 is
                   measured in the saturated regime.

  2. HEADROOM      Q must be materially higher below the knee than above it.
                   If Q is flat across the sweep there is nothing for an agent
                   to degrade and Definition 4 cannot be exhibited here at all.

It records data either way. A negative answer is a real finding about the cell,
not a failure to be retried.

    sudo .venv/bin/python srsran/calibrate_regime.py
"""
from __future__ import annotations

import json, logging, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from srsran.phi_probe import PhiProbe                     # noqa: E402
from srsran.ambr_enforcer import AmbrEnforcer             # noqa: E402
from srsran.phi_agent_probe import q_of, LAM_NORM_MS      # noqa: E402
from srsran.preconditions import assert_ready             # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def kill_radio():
    for s in ("TERM", "KILL"):
        for p in ("srsue/src/srsue", "apps/gnb/gnb", "gr_broker.py"):
            sh(f"pkill -{s} -f '{p}'")
        time.sleep(2)


def ue_ip(ns):
    r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def bring_up(n=4):
    kill_radio(); RUN.mkdir(exist_ok=True)
    subprocess.Popen([str(GNB), "-c", str(CFG / "gnb_zmq.yml")],
                     stdout=open(RUN / "gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    for i in range(1, n + 1):
        subprocess.Popen([str(UE), str(CFG / f"ue{i}_mux.conf")],
                         stdout=open(RUN / f"ue{i}.stdout", "w"), stderr=subprocess.STDOUT)
        time.sleep(3)
    subprocess.Popen([SYS_PY, str(BROKER), "--n-ue", str(n), "--srate", "23.04e6",
                      "--slow-down-ratio", "1"],
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


def main():
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    for nm in ("COLLECTOR", "pymongo", "pymongo.serverSelection"):
        logging.getLogger(nm).setLevel(logging.ERROR)
    assert_ready()
    n = 4
    print("=" * 78)
    print("  CALIBRATION — does the ceiling shape, and does crossing the knee lower Q?")
    print("=" * 78)
    att = bring_up(n)
    up = [k for k, v in att.items() if v]
    print(f"\n  attached: {att}")
    if len(up) < n:
        kill_radio(); sys.exit(f"ERROR: only {len(up)}/{n} attached")

    probe = PhiProbe(up, iperf_secs=10)
    if not probe.selftest():
        kill_radio(); sys.exit("ERROR: probe self-test failed")
    enf = AmbrEnforcer(); enf.setup()

    rows = []
    print(f"\n  {'ceiling':>8} {'n*B':>6} {'τ agg':>7} {'τ≤n*B?':>8} {'λ ms':>8} {'Q':>7}")
    for B in (3.0, 5.0, 8.0, 15.0, 60.0):
        for ip in att.values():
            enf.set_ue_ambr(ip, B)
        time.sleep(5)
        rec = probe.measure(int(B))
        tau, lam = rec.tau_mbps, rec.lambda_ms
        q = q_of((tau / n) if tau else None, lam)
        holds = (tau is not None and tau <= n * B * 1.25)
        rows.append({"ceiling_mbps": B, "offered_total": n * B, "tau_agg": tau,
                     "ceiling_holds": holds, "lambda_ms": lam, "Q": q})
        print(f"  {B:>8.1f} {n*B:>6.0f} {str(tau):>7} {('yes' if holds else 'NO'):>8} "
              f"{str(lam):>8} {str(q):>7}")

    enf.teardown(); kill_radio()

    held = [r for r in rows if r["ceiling_holds"]]
    qs = [r["Q"] for r in rows if r["Q"] is not None]
    verdict = {
        "enforcement_works": len(held) >= 3,
        "ceilings_that_held": [r["ceiling_mbps"] for r in held],
        "q_range": [min(qs), max(qs)] if qs else None,
        "q_span": round(max(qs) - min(qs), 4) if qs else None,
        "headroom_exists": bool(qs and (max(qs) - min(qs)) > 0.05),
    }
    print(f"\n  enforcement holds at: {verdict['ceilings_that_held']}")
    print(f"  Q range across the sweep: {verdict['q_range']}  span {verdict['q_span']}")
    if verdict["enforcement_works"] and verdict["headroom_exists"]:
        lo = min(rows, key=lambda r: r["ceiling_mbps"])
        print(f"\n  GO — the ceiling shapes and Q has {verdict['q_span']} of headroom.")
        print(f"       Run E-FINAL with --baseline {lo['ceiling_mbps']}")
    else:
        print(f"\n  NO-GO — "
              f"{'the ceiling is not shaping' if not verdict['enforcement_works'] else ''}"
              f"{' and ' if not verdict['enforcement_works'] and not verdict['headroom_exists'] else ''}"
              f"{'Q is flat across the sweep' if not verdict['headroom_exists'] else ''}.")
        print("       Definition 4 cannot be exhibited on this cell as configured, and that")
        print("       is a finding about the testbed rather than something to retry.")
    payload = {"experiment": "calibration", "n_ue": n, "rows": rows, "verdict": verdict,
               "q_definition": f"0.5*min(tau_perUE/20,1)+0.5*max(0,1-lambda/{LAM_NORM_MS})",
               "saved_at": datetime.now(timezone.utc).isoformat()}
    (OUT / "calibration_regime.json").write_text(json.dumps(payload, indent=2))
    print(f"\n  -> {OUT/'calibration_regime.json'}")


if __name__ == "__main__":
    main()
