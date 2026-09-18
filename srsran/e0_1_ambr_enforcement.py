#!/usr/bin/env python3
"""E0.1 — AMBR enforcement gate  (spec §3, Phase 0).

Two arms in one run:

  ARM A  native  — AMBR written to the subscriber DB only. Tests whether
                   Open5GS polices Session-AMBR on the data plane. Needs a
                   gNB+UE restart per point so the core re-reads the record.

  ARM B  htb     — the declared per-UE HTB stand-in for the TS 29.244 QER
                   (srsran/ambr_enforcer.py). No restart needed: changing an
                   HTB ceiling takes milliseconds.

Pass criterion (spec): achieved tracks B for B < C, |achieved - B| / B < 0.15.

Running both arms in one artifact documents the gate failure AND validates the
remedy, which is what the paper needs in order to state its enforcement point
honestly.

CRITICAL INVARIANT (spec §0): the enforcement point is per-UE and must never
scale the shared bottleneck C. assert_not_bottleneck() checks it.

Partial results are flushed after every point, so an interrupted run is not lost.

Run as root:
    sudo .venv/bin/python srsran/e0_1_ambr_enforcement.py
    sudo .venv/bin/python srsran/e0_1_ambr_enforcement.py --arm htb
"""
from __future__ import annotations

import argparse
import io
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

NS, GW, PORT, SLICE = "ue1", "10.45.0.1", 5299, "internet"
DURATION = 15
AMBR_SWEEP = [5, 10, 20, 50, 100, 200]
TOL = 0.15
UE_CONF = ROOT / "srsran" / "configs" / "ue1.conf"
GNB_CONF = ROOT / "srsran" / "configs" / "gnb_zmq.yml"
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
OUT = ROOT / "srsran" / "results"
RESULT = OUT / "E0_1_ambr_enforcement.json"


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def set_ambr_db(mbps: int) -> bool:
    from tools.policy_manager import PolicyManager
    return bool(PolicyManager().apply_policy(
        SLICE, int(mbps * 1e6), int(mbps * 1e6), reason=f"E0.1 -> {mbps} Mbps").get("success"))


def ue_ip() -> str | None:
    r = sh(["ip", "netns", "exec", NS, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def _port_free(p: int) -> bool:
    return (sh(f"ss -lnt 2>/dev/null | grep -c ':{p} '").stdout.strip() or "0") == "0"


def prep_ns() -> None:
    sh(["ip", "netns", "exec", NS, "ip", "link", "set", "lo", "up"])
    sh(["ip", "netns", "exec", NS, "ip", "route", "add", "default", "via", GW, "dev", "tun_srsue"])


def restart_stack() -> str | None:
    """Cycle gNB AND UE together.

    srsRAN's ZMQ radio is sample-synchronised between the two processes.
    Restarting only the UE leaves the gNB bound to the dead stream: the UE
    initialises its PHY, prints "Attaching UE..." and hangs, with no RACH and
    no error message. Both ends must cycle.
    """
    for sig in ("TERM", "KILL"):
        sh(f"pkill -{sig} -f 'srsue/src/srsue'")
        sh(f"pkill -{sig} -f 'apps/gnb/gnb'")
        for _ in range(12):
            time.sleep(1)
            if not sh("pgrep -f 'srsue/src/srsue|apps/gnb/gnb'").stdout.strip():
                break
    for _ in range(40):
        if _port_free(2000) and _port_free(2001):
            break
        time.sleep(1)
    time.sleep(2)

    subprocess.Popen([str(GNB_BIN), "-c", str(GNB_CONF)],
                     stdout=open("/tmp/srsran/gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(6)
    if not sh("pgrep -f 'apps/gnb/gnb'").stdout.strip():
        print("   [FAIL] gNB did not start")
        return None

    subprocess.Popen([str(UE_BIN), str(UE_CONF)],
                     stdout=open("/tmp/srsran/ue1.stdout", "w"), stderr=subprocess.STDOUT)
    for _ in range(60):
        time.sleep(1)
        if "Address already in use" in Path("/tmp/srsran/ue1.stdout").read_text():
            print("   [FAIL] ZMQ port collision")
            return None
        ip = ue_ip()
        if ip:
            time.sleep(3)
            prep_ns()
            return ip
    print("   [FAIL] no PDU session after 60s")
    return None


def measure_dl() -> float | None:
    sh(f"pkill -f 'iperf3 -s -p {PORT}'")
    time.sleep(1)
    subprocess.Popen(["iperf3", "-s", "-p", str(PORT)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    r = sh(["ip", "netns", "exec", NS, "iperf3", "-c", GW, "-p", str(PORT),
            "-t", str(DURATION), "-J", "-R"])
    sh(f"pkill -f 'iperf3 -s -p {PORT}'")
    try:
        return json.load(io.StringIO(r.stdout))["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        return None


def flush(payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2))


def run_arm(arm: str, payload: dict) -> list[dict]:
    rows: list[dict] = []
    enf = None

    if arm == "htb":
        from srsran.ambr_enforcer import AmbrEnforcer
        enf = AmbrEnforcer()
        enf.setup()
        set_ambr_db(1000)                    # remove the DB value as a variable
        ip = restart_stack()
        if not ip:
            print("   [FAIL] stack did not come up for arm B")
            return rows
        print(f"   stack up at {ip}; HTB installed (root {enf.root_rate} Mbit)")

    for B in AMBR_SWEEP:
        print(f"\n── [{arm}] AMBR = {B} Mbps ──")
        if arm == "native":
            if not set_ambr_db(B):
                print("   [FAIL] policy write")
                continue
            ip = restart_stack()
            if not ip:
                continue
        else:
            ip = ue_ip()
            if not ip:
                print("   [FAIL] UE gone")
                break
            if not enf.set_ue_ambr(ip, B):
                print("   [FAIL] htb set")
                continue
            time.sleep(2)

        dl = measure_dl()
        if dl is None:
            print("   [FAIL] iperf3")
            rows.append({"ambr_mbps": B, "achieved_mbps": None})
        else:
            err = abs(dl - B) / B
            print(f"   UE {ip}   achieved {dl:.2f} Mbps   |err|={err*100:.0f}%   tracks={err < TOL}")
            rows.append({"ambr_mbps": B, "achieved_mbps": round(dl, 2),
                         "rel_err": round(err, 4), "tracks": err < TOL, "ue_ip": ip})
        payload[f"arm_{arm}"] = rows
        flush(payload)

    if enf:
        C = max((r["achieved_mbps"] for r in rows if r.get("achieved_mbps")), default=0)
        if C:
            enf.assert_not_bottleneck(C)
            print(f"\n   invariant OK: HTB root {enf.root_rate} Mbit >= 10x C({C:.1f} Mbps)")
        enf.teardown()
    return rows


def verdict(rows: list[dict]) -> tuple[bool, float]:
    got = [r for r in rows if r.get("achieved_mbps")]
    C = max((r["achieved_mbps"] for r in got), default=0)
    below = [r for r in got if r["ambr_mbps"] < C * 0.9]
    return (bool(below) and all(r["tracks"] for r in below)), C


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["native", "htb", "both"], default="both")
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    assert_ready()
    Path("/tmp/srsran").mkdir(exist_ok=True)

    payload = {"experiment": "E0.1",
               "question": "does a change to Session-AMBR change achieved throughput?",
               "n_ue": 1, "duration_s": DURATION, "tolerance": TOL,
               "sweep_mbps": AMBR_SWEEP,
               "started_at": datetime.now(timezone.utc).isoformat()}

    print("=" * 72)
    print("  E0.1 — AMBR enforcement gate   (single UE, no contention)")
    print(f"  sweep {AMBR_SWEEP} Mbps   {DURATION}s saturating DL per point")
    print("=" * 72)

    if a.arm in ("native", "both"):
        print("\n########## ARM A — native Open5GS (no HTB) ##########")
        ok_a, C_a = verdict(run_arm("native", payload))
        payload["arm_native_enforced"] = ok_a
        payload["C_estimate_mbps"] = C_a
        flush(payload)

    if a.arm in ("htb", "both"):
        print("\n########## ARM B — declared per-UE HTB stand-in ##########")
        ok_b, _ = verdict(run_arm("htb", payload))
        payload["arm_htb_enforced"] = ok_b
        flush(payload)

    print("\n" + "=" * 72)
    for arm in ("native", "htb"):
        rs = payload.get(f"arm_{arm}") or []
        if not rs:
            continue
        print(f"  ARM {arm.upper()}")
        print(f"  {'AMBR':>8} | {'achieved':>9} | {'err':>6} | tracks")
        for r in rs:
            if r.get("achieved_mbps") is None:
                print(f"  {r['ambr_mbps']:>8} |         - |      - | -")
            else:
                print(f"  {r['ambr_mbps']:>8} | {r['achieved_mbps']:>9.2f} | "
                      f"{r['rel_err']*100:>5.0f}% | {r['tracks']}")
        print()

    nat, htb = payload.get("arm_native_enforced"), payload.get("arm_htb_enforced")
    if nat is False:
        print("  GATE: Open5GS does NOT enforce Session-AMBR on the data plane.")
        print("  The paper must declare its enforcement point (spec §3, E0.1).")
    if htb:
        print("  STAND-IN VALIDATED: per-UE HTB tracks the configured AMBR.")
        print("  Enforcement is per-UE; the bottleneck stays at the air interface.")

    payload["verdict"] = {
        "open5gs_enforces_session_ambr": nat,
        "htb_standin_tracks": htb,
        "paper_statement": (
            "AMBR is enforced at the UPF by a per-UE HTB class on the tunnel "
            "interface, configured from the subscriber's Session-AMBR. Open5GS does "
            "not implement QER-based rate enforcement, so this stands in for the QER "
            "an operator UPF applies under TS 29.244. The enforcement point is per-UE "
            "and is the only place the agent's policy value acts; the shared "
            "bottleneck is at the air interface and is independent of it."
        ) if nat is False else "Open5GS enforces Session-AMBR natively (TS 29.244 QER path).",
    }
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    flush(payload)
    set_ambr_db(20)
    print(f"\n  -> {RESULT}\n  baseline AMBR restored to 20 Mbps")


if __name__ == "__main__":
    main()
