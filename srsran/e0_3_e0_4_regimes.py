#!/usr/bin/env python3
"""E0.3 + E0.4 — capacity characterisation and the two-regime curve.

E0.3  What is C?
      n UEs, all AMBRs unlimited, saturating load, aggregate downlink over a
      long window. That aggregate IS C.

E0.4  Does the knee exist, and where?
      Fix n. Sweep the UNIFORM per-UE AMBR B across [0.2*C/n, 4*C/n].
      At each point measure per-UE τ, aggregate τ, λ, ρ, σ.

      Pass: τ per UE rises with B while n*B < C, then flattens near C/n;
            λ and ρ rise once n*B > C.

WHY THIS IS THE MOST IMPORTANT FIGURE IN THE REBUILD
----------------------------------------------------
It establishes the physical-harm mechanism and the two regimes (paper §6.3) simultaneously:

  * Below the knee, raising the AMBR ceiling RAISES real throughput. That is
    legitimate scaling, with no victim cost.
  * Above the knee, per-UE throughput saturates at ~C/n while latency and loss
    climb. That is the regime the paper assumed but never stated.

Crucially neither regime is imposed by the harness. Enforcement is a per-UE
HTB ceiling; the bottleneck is the srsRAN MAC scheduler over a fixed PRB pool.
They are different objects, which is the separation spec §0 demands and the
thing whose absence made the original harm claims circular.

Run as root:
    sudo .venv/bin/python srsran/e0_3_e0_4_regimes.py --n-ue 4
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
SYS_PY = "/usr/bin/python3"   # GNU Radio is in system site-packages, not the venv
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"
UNLIMITED = 10_000        # Mbps — far above any achievable C


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
    """gNB -> all UEs -> broker LAST (srsRAN docs; validated by E0.2 at n=4).

    "UEs will not connect to the gNB until the GNU-Radio flow graph has been
    started, as the UL and DL channels are not directly connected between the
    UE and gNB."
    """
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--points", type=int, default=10)
    ap.add_argument("--iperf-secs", type=int, default=12)
    ap.add_argument("--capacity-secs", type=int, default=60)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    assert_ready()
    OUT.mkdir(parents=True, exist_ok=True)
    n = a.n_ue

    print("=" * 72)
    print(f"  E0.3 + E0.4 — capacity and two-regime curve   (n = {n} UEs)")
    print("=" * 72)

    att = bring_up(n)
    up = [ns for ns, ip in att.items() if ip]
    print(f"\n  attached: {att}")
    if len(up) < n:
        sys.exit(f"ERROR: only {len(up)}/{n} UEs attached — run E0.2 first")

    probe = PhiProbe(up, iperf_secs=a.iperf_secs)   # capacity_hint set after E0.3
    if not probe.selftest():
        sys.exit("ERROR: probe self-test failed — refusing to record estimated data")

    enf = AmbrEnforcer(); enf.setup()
    ips = {ns: att[ns] for ns in up}

    # ── E0.3 : measure C ───────────────────────────────────────────────────
    print(f"\n{'='*72}\n  E0.3 — capacity C  ({a.capacity_secs}s, all AMBRs unlimited)\n{'='*72}")
    for ns, ip in ips.items():
        enf.set_ue_ambr(ip, UNLIMITED)
    time.sleep(3)
    cap_probe = PhiProbe(up, iperf_secs=a.capacity_secs)
    cap = cap_probe.measure(k=0)
    C = cap.tau_mbps
    if C is None:
        sys.exit("ERROR: could not measure C (τ unavailable) — refusing to guess")
    print(f"  C = {C:.2f} Mbps aggregate   per-UE fair share C/n = {C/n:.2f} Mbps")
    print(f"  per-UE: {cap.per_ue_tau}")
    print(f"  λ={cap.lambda_ms} ms  ρ={cap.rho_pct}%  σ={cap.sigma}")

    e03 = {"experiment": "E0.3", "n_ue": n, "C_mbps": round(C, 2),
           "fair_share_mbps": round(C / n, 2), "window_s": a.capacity_secs,
           "record": cap.as_dict(),
           "saved_at": datetime.now(timezone.utc).isoformat()}
    (OUT / "E0_3_capacity.json").write_text(json.dumps(e03, indent=2))
    enf.assert_not_bottleneck(C)
    print(f"  invariant OK: HTB root {enf.root_rate} Mbit >= 10x C")

    # ── E0.4 : sweep B across the knee ─────────────────────────────────────
    probe.capacity_hint = C          # enables the rho plausibility check
    lo, hi = 0.2 * C / n, 4.0 * C / n
    sweep = [round(lo + (hi - lo) * i / (a.points - 1), 2) for i in range(a.points)]
    print(f"\n{'='*72}\n  E0.4 — two-regime sweep")
    print(f"  B from {lo:.2f} to {hi:.2f} Mbps/UE   knee expected at B = C/n = {C/n:.2f}")
    print(f"  {sweep}\n{'='*72}")

    rows = []
    e04 = {"experiment": "E0.4", "n_ue": n, "C_mbps": round(C, 2),
           "knee_mbps_per_ue": round(C / n, 2), "sweep_mbps": sweep,
           "started_at": datetime.now(timezone.utc).isoformat(), "rows": rows}

    for j, B in enumerate(sweep, 1):
        for ip in ips.values():
            enf.set_ue_ambr(ip, B)
        time.sleep(3)
        rec = probe.measure(k=j)
        offered = n * B
        regime = "under" if offered < C else "over"
        row = {"B_mbps_per_ue": B, "offered_total_mbps": round(offered, 2),
               "regime": regime, **rec.as_dict()}
        rows.append(row)
        e04["rows"] = rows
        (OUT / "E0_4_two_regime.json").write_text(json.dumps(e04, indent=2))
        tau_ue = (rec.tau_mbps / n) if rec.tau_mbps else None
        print(f"  B={B:>7.2f}  offered={offered:>7.2f}  [{regime:>5}]  "
              f"τ_agg={rec.tau_mbps}  τ/UE={round(tau_ue,2) if tau_ue else None}  "
              f"λ={rec.lambda_ms}  ρ={rec.rho_pct}  σ={rec.sigma}"
              f"{'' if rec.complete else '   INCOMPLETE'}")

    # ── integrity + verdict ────────────────────────────────────────────────
    try:
        probe.assert_dimensions_vary()
        e04["degeneracy_check"] = "PASS — every Φ dimension varies"
        print("\n  degeneracy check PASS — all four Φ dimensions vary")
    except AssertionError as ex:
        e04["degeneracy_check"] = f"FAIL — {ex}"
        print(f"\n  DEGENERACY: {ex}")

    ok = [r for r in rows if r["complete"]]
    under = [r for r in ok if r["regime"] == "under"]
    over = [r for r in ok if r["regime"] == "over"]
    verdict = {}
    if under and over:
        rises = under[-1]["tau_mbps"] > under[0]["tau_mbps"] * 1.2
        flat = abs(over[-1]["tau_mbps"] - over[0]["tau_mbps"]) / max(over[0]["tau_mbps"], 1) < 0.15
        lam_up = (over[-1]["lambda_ms"] or 0) > (under[0]["lambda_ms"] or 0) * 1.2
        verdict = {"tau_rises_below_knee": rises, "tau_flat_above_knee": flat,
                   "lambda_rises_above_knee": lam_up,
                   "gate_passed": bool(rises and flat)}
        print(f"\n  τ rises below knee : {rises}")
        print(f"  τ flat above knee  : {flat}")
        print(f"  λ rises above knee : {lam_up}")
        print(f"  E0.4 GATE {'PASSED' if verdict['gate_passed'] else 'FAILED'}")
    e04["verdict"] = verdict
    e04["probe_summary"] = probe.summary()
    e04["finished_at"] = datetime.now(timezone.utc).isoformat()
    (OUT / "E0_4_two_regime.json").write_text(json.dumps(e04, indent=2))
    probe.save(OUT / "E0_4_phi_trace.jsonl")

    enf.teardown(); kill_all()
    print(f"\n  -> {OUT/'E0_3_capacity.json'}\n  -> {OUT/'E0_4_two_regime.json'}"
          f"\n  -> {OUT/'E0_4_phi_trace.jsonl'}")


if __name__ == "__main__":
    main()
