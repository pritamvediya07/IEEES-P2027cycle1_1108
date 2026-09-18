#!/usr/bin/env python3
"""E2.3 — dR/da != 0 at PROVABLY FIXED Phi.  Standalone, radio required.

WHY THIS IS A SEPARATE SCRIPT
-----------------------------
E2.3 was run once inside e2_contamination.py and produced Delta_R = 90.0 Mbps
with every Phi dimension reported as None, because no UE was attached. That is
not a pass. It measured a real channel effect, but the load-bearing half of the
claim — that R moves WHILE Phi provably does not — was never tested: Phi was
absent, not static. With no traffic at all, one would correctly object
that of course a state-derived metric does not move.

So this script does the thing properly, and REFUSES to record anything if the
preconditions for a meaningful measurement are not met.

WHAT IT ESTABLISHES
-------------------
    badly designed KPI      R = g(Phi)        -> dR/da at fixed Phi = 0
    observability artifact  R = g(Pi Phi)     -> dR/da at fixed Phi = 0
    unstable control loop   state-only        -> dR/da at fixed Phi = 0
    PALA                    R = g(Phi, a_1:k) -> dR/da at fixed Phi != 0

Measuring a NON-ZERO dR at a Phi that is measured, real, and unchanged is what
separates this setting from all three alternatives. It is the formal core of
the paper's distinctness argument, so it has to be measured, not asserted.

DESIGN
------
UEs attached and IDLE. Idle matters: no offered load means Phi is genuinely
static across the write, and we verify that by measuring it on both sides
rather than assuming it. Then:

    treatment arm   standard collector   -> expect Delta_R != 0
    control arm     IsolatedCollector    -> expect Delta_R == 0 (Lemma 6)

The control arm is what makes this a measurement rather than an anecdote: the
same write, the same static Phi, and the only difference is provenance.

REFUSES TO RECORD IF:
    * any Phi dimension is None (the exact defect that made the first run void)
    * Phi moved more than the tolerance between before and after
    * fewer UEs attached than requested

Run as root, and NOT while the LLM experiment chain is running — that campaign
writes the same AMBR field and the two would corrupt each other:

    sudo .venv/bin/python srsran/e2_3_dr_fixed_phi.py --n-ue 4 --repeats 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import statistics as st
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.phi_probe import PhiProbe                    # noqa: E402
from srsran.preconditions import assert_ready            # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"
SLICE = "internet"

# Phi is "unchanged" if it moves less than this. Deliberately tight: the whole
# point is that Phi did NOT move, so a loose tolerance would beg the question.
TOL = {"tau_mbps": 0.15, "lambda_ms": 0.25, "rho_pct": 0.05}   # fractional


def chain_is_running() -> bool:
    """Is the LLM experiment chain running?

    Scans /proc directly instead of shelling out. `subprocess.run("pgrep -f
    llm_chain.sh", shell=True)` spawns `/bin/sh -c 'pgrep -f llm_chain.sh'`,
    whose OWN command line contains the pattern, so pgrep matched the shell that
    invoked it and the guard fired even with the chain correctly stopped.

    Processes in this process's own session are ignored for the same reason: a
    wrapper that paused the chain must not be mistaken for the chain.
    """
    import os as _os
    my_sid = _os.getsid(0)
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            if "llm_chain.sh" not in cmd:
                continue
            if _os.getsid(int(entry.name)) == my_sid:
                continue                      # us, or our own wrapper
            if "bash" not in cmd and "sh " not in cmd:
                continue                      # not the chain itself
            return True
        except (OSError, ProcessLookupError, ValueError):
            continue
    return False


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


def bring_up(n: int) -> dict:
    """gNB -> UEs -> broker LAST (srsRAN docs; validated at n=4 in E0.2)."""
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
            sh(["ip", "netns", "exec", ns, "ip", "route", "add", "default",
                "via", GW, "dev", "tun_srsue"])
    return att


def write_ambr(mbps: float) -> bool:
    from tools.policy_manager import PolicyManager
    return bool(PolicyManager().apply_policy(
        SLICE, int(mbps * 1e6), int(mbps * 1e6),
        reason=f"E2.3 write {mbps:.0f}").get("success"))


def read_R():
    from tools.kpi_analyzer import KPIAnalyzer
    r = KPIAnalyzer().analyze("ambr_dl_mean", n_samples=10, run_ml=False)
    if "error" in r:
        return None
    v = r.get("raw_values") or []
    return float(v[-1]) if v else None


def tick(isolated: bool):
    from collector.collector import Collector
    from collector.collector_isolated import IsolatedCollector
    (IsolatedCollector(write_port=27017) if isolated else Collector()).collect_once()


def phi_dict(rec):
    return {"tau_mbps": rec.tau_mbps, "lambda_ms": rec.lambda_ms, "rho_pct": rec.rho_pct}


def phi_complete(p: dict) -> bool:
    """The check whose absence voided the first run."""
    return all(p.get(k) is not None for k in ("tau_mbps", "lambda_ms", "rho_pct"))


def phi_static(a: dict, b: dict):
    """Returns (is_static, per-dimension detail)."""
    detail, ok = {}, True
    for k, tol in TOL.items():
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            detail[k] = {"before": x, "after": y, "within_tol": None}
            ok = False
            continue
        rel = abs(y - x) / max(abs(x), 1e-9)
        w = rel <= tol
        detail[k] = {"before": round(x, 4), "after": round(y, 4),
                     "rel_change": round(rel, 4), "tol": tol, "within_tol": w}
        ok = ok and w
    return ok, detail


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--phi-secs", type=int, default=10)
    ap.add_argument("--baseline-mbps", type=float, default=20.0)
    ap.add_argument("--write-mbps", type=float, default=200.0)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (netns access for the probe)")
    for n in ("COLLECTOR", "pymongo", "pymongo.serverSelection"):
        logging.getLogger(n).setLevel(logging.ERROR)
    assert_ready()

    # The ISO arm is only a control if NOTHING else is writing standard analytics.
    # A previous run left the collector daemon active: it writes ambr_dl_mean every
    # 5 s regardless of this experiment's own tick(isolated), so the "isolated" arm
    # read a live standard stream and returned dR = 180.0 — identical to the
    # treatment arm — making the control meaningless.
    from pathlib import Path as _P
    import os as _os
    for _e in _P("/proc").iterdir():
        if not _e.name.isdigit():
            continue
        try:
            _c = (_e / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except OSError:
            continue
        if "collector.collector" in _c and "python" in _c:
            sys.exit("ERROR: the collector daemon is running (pid " + _e.name + "). It writes "
                     "standard analytics every 5 s, which would defeat the IsolatedCollector "
                     "control arm. Stop it first:  kill " + _e.name)

    if chain_is_running():
        sys.exit("ERROR: the LLM chain is running. It writes the same AMBR field; "
                 "running both would corrupt each other's data. Wait for it to finish.")

    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 80)
    print("  E2.3 — dR/da != 0 at PROVABLY FIXED Phi")
    print("=" * 80)

    att = bring_up(a.n_ue)
    up = [ns for ns, ip in att.items() if ip]
    print(f"\n  attached: {att}")
    if len(up) < a.n_ue:
        sys.exit(f"ERROR: only {len(up)}/{a.n_ue} UEs attached — refusing to record")

    probe = PhiProbe(up, iperf_secs=a.phi_secs)
    if not probe.selftest():
        sys.exit("ERROR: probe self-test failed — refusing to record estimated data")

    # UEs attached and IDLE: kill any offered load so Phi is genuinely static.
    sh("pkill -f continuous_client.py")
    time.sleep(2)

    rows = []
    for arm, isolated in (("standard", False), ("isolated_control", True)):
        print(f"\n── arm: {arm} ({'IsolatedCollector' if isolated else 'standard collector'}) ──")
        for r in range(1, a.repeats + 1):
            write_ambr(a.baseline_mbps)
            tick(isolated)
            time.sleep(2)

            before = probe.measure(k=0)
            pb = phi_dict(before)
            r_before = read_R()

            write_ambr(a.write_mbps)
            tick(isolated)
            time.sleep(12)                      # >= 2 collector cycles

            r_after = read_R()
            after = probe.measure(k=1)
            pa = phi_dict(after)

            complete = phi_complete(pb) and phi_complete(pa)
            static, detail = phi_static(pb, pa)
            dR = (None if (r_before is None or r_after is None)
                  else round(r_after - r_before, 4))

            row = {"arm": arm, "repeat": r, "isolated": isolated,
                   "phi_before": pb, "phi_after": pa,
                   "phi_complete": complete, "phi_static": static,
                   "phi_detail": detail,
                   "R_before": r_before, "R_after": r_after, "delta_R": dR,
                   "valid": bool(complete and static)}
            rows.append(row)
            print(f"   [{r}/{a.repeats}] Phi tau {pb['tau_mbps']}->{pa['tau_mbps']}  "
                  f"lam {pb['lambda_ms']}->{pa['lambda_ms']}  "
                  f"complete={complete} static={static}   R {r_before}->{r_after}  dR={dR}"
                  f"{'' if row['valid'] else '   INVALID — not counted'}")
            write_ambr(a.baseline_mbps)
            tick(isolated)

    valid = [r for r in rows if r["valid"]]
    std = [r for r in valid if r["arm"] == "standard" and r["delta_R"] is not None]
    iso = [r for r in valid if r["arm"] == "isolated_control" and r["delta_R"] is not None]

    print(f"\n  valid measurements: {len(valid)}/{len(rows)}")
    if not std:
        print("\n  NO VALID TREATMENT MEASUREMENT. Phi was incomplete or moved. "
              "Nothing is claimed. Re-run with the radio settled and no offered load.")
        verdict = {"status": "NO VALID MEASUREMENT",
                   "reason": "Phi incomplete or not static in every treatment repeat",
                   "claim": "none — E2.3 remains unestablished"}
    else:
        m_std = round(st.mean(r["delta_R"] for r in std), 4)
        m_iso = round(st.mean(r["delta_R"] for r in iso), 4) if iso else None
        print(f"  standard          mean dR = {m_std}   (n={len(std)})")
        print(f"  isolated control  mean dR = {m_iso}   (n={len(iso)})")
        verdict = {
            "status": "VALID",
            "standard_mean_delta_R": m_std, "standard_n": len(std),
            "isolated_mean_delta_R": m_iso, "isolated_n": len(iso),
            "phi_was_measured_and_static": True,
            "tolerance_used": TOL,
            "conclusion": (
                f"With Phi measured on both sides of the write and unchanged within tolerance, "
                f"R moves by {m_std} under the standard collector and by {m_iso} under "
                "IsolatedCollector. A non-zero dR at fixed Phi is exactly dR/da != 0, which "
                "distinguishes this setting from a badly designed KPI (R = g(Phi)), an "
                "observability projection (R = g(Pi Phi)) and an unstable control loop — all "
                "three of which are state-only and would give zero here. The isolated arm is "
                "the control: same write, same static Phi, provenance severed."),
        }
        print(f"\n  {verdict['conclusion']}")

    payload = {"experiment": "E2.3", "n_ue": a.n_ue, "repeats": a.repeats,
               "baseline_mbps": a.baseline_mbps, "write_mbps": a.write_mbps,
               "phi_tolerance": TOL, "attached": att,
               "supersedes": ("the E2.3 block inside E2_contamination.json, whose Phi "
                              "verification was vacuous (all dimensions None, no UE attached)"),
               "rows": rows, "verdict": verdict,
               "probe_summary": probe.summary(),
               "saved_at": datetime.now(timezone.utc).isoformat()}
    p = OUT / "E2_3_dr_fixed_phi.json"
    p.write_text(json.dumps(payload, indent=2))
    probe.save(OUT / "E2_3_phi_trace.jsonl")
    write_ambr(a.baseline_mbps)
    kill_all()
    print(f"\n  -> {p}\n  baseline AMBR restored, radio down")


if __name__ == "__main__":
    main()
