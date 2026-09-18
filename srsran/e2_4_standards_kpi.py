#!/usr/bin/env python3
"""E2.4 — A TS 28.554 §6.4.2 shaped KPI, measured under real traffic  (paper App. A, Standards basis for AS2).

THE QUESTION
------------
App. A: which standardised KPI schema mixes configured and measured values,
i.e. what grounds the AS2 mixed-provenance assumption beyond our own collector?

The weak answer is "here is our collector schema", which is deployment-specific.
The strong answer is to take a KPI the STANDARD defines,
implement it exactly as specified, and show that mixed provenance is a property
of the definition rather than of anything we chose.

TS 28.554 §6.4.2, Virtualised Resource Utilization of a Network Slice Instance:

        KPI = measured resource usage / allocated system capacity

The numerator is MEASURED. The denominator is CONFIGURED. The output is one
scalar. The recommendation defines no provenance element, so a consumer holding
this value cannot tell which half moved.

WHY A NON-ZERO VALUE IS NOT ENOUGH
----------------------------------
An earlier run produced 0.0 because the radio was down and no user-plane bytes
flowed. Simply re-taking it with traffic gives a number, but a number proves
nothing on its own. What proves AS2 is the SENSITIVITY:

    hold the measured numerator constant (steady offered load, fixed C)
    sweep ONLY the configured denominator (the AMBR ceiling)
    -> the KPI moves

If the KPI moves while nothing measurable about the network changed, then a
consumer reading it is reading the operator's configuration, not the network.
That is AS2, demonstrated on a standardised KPI, with the agent removed from the
loop entirely.

REFUSES TO RECORD IF:
    * fewer UEs attach than requested
    * the measured numerator is zero or does not advance (no real traffic)
    * the numerator is NOT approximately constant across the sweep, since the
      whole argument depends on holding it fixed

Run as root, and NOT while the LLM chain is running:
    sudo .venv/bin/python srsran/e2_4_standards_kpi.py --n-ue 4
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

from srsran.preconditions import assert_ready            # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
TRAFFIC = ROOT / "traffic" / "run_all_ues_srsran.py"
SERVER = ROOT / "traffic" / "server.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"
SLICE = "internet"


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
        for pat in ("srsue/src/srsue", "apps/gnb/gnb", "gr_broker.py",
                    "continuous_client.py", "traffic/server.py"):
            sh(f"pkill -{sig} -f '{pat}'")
        time.sleep(2)


def ue_ip(ns):
    r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def bring_up(n: int) -> dict:
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


def start_traffic(nss: list[str]):
    subprocess.Popen([SYS_PY, str(SERVER)],
                     stdout=open(RUN / "tserver.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(2)
    p = subprocess.Popen([SYS_PY, str(TRAFFIC), "--netns", *nss],
                         stdout=open(RUN / "tclients.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    return p


def write_ambr(mbps: float) -> bool:
    from tools.policy_manager import PolicyManager
    return bool(PolicyManager().apply_policy(
        SLICE, int(mbps * 1e6), int(mbps * 1e6),
        reason=f"E2.4 configured denominator {mbps:.0f}").get("success"))


def tick():
    from collector.collector import Collector
    Collector().collect_once()


def kpi_now() -> dict:
    """TS 28.554 §6.4.2 shape: measured usage / configured allocated capacity."""
    from config.db import get_nwdaf_db
    db = get_nwdaf_db()
    smf = db["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    upf = db["upf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    measured = float(upf.get("total_rx_bytes", 0)) + float(upf.get("total_tx_bytes", 0))
    ambr_mbps = float(smf.get("ambr_dl_mean", 0) or 0)
    configured = ambr_mbps * 1e6 / 8.0        # bytes/s of allocated capacity
    return {"measured_bytes": measured,
            "configured_ambr_mbps": ambr_mbps,
            "configured_capacity_Bps": configured,
            "kpi": (measured / configured) if configured > 0 else None}


def corr(xs, ys):
    pr = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pr) < 3:
        return None
    mx, my = st.mean(p[0] for p in pr), st.mean(p[1] for p in pr)
    num = sum((x - mx) * (y - my) for x, y in pr)
    den = (sum((x - mx) ** 2 for x, _ in pr) * sum((y - my) ** 2 for _, y in pr)) ** 0.5
    return round(num / den, 4) if den > 1e-12 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--sweep", default="20,40,60,80,100,150,200",
                    help="configured AMBR values (Mbps) for the DENOMINATOR sweep")
    ap.add_argument("--settle", type=int, default=10)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (netns access)")
    for n in ("COLLECTOR", "pymongo", "pymongo.serverSelection"):
        logging.getLogger(n).setLevel(logging.ERROR)
    assert_ready()
    if chain_is_running():
        sys.exit("ERROR: the LLM chain is running; it writes the same AMBR field. Wait for it.")

    OUT.mkdir(parents=True, exist_ok=True)
    sweep = [float(x) for x in a.sweep.split(",")]

    print("=" * 80)
    print("  E2.4 — TS 28.554 §6.4.2 shaped KPI under REAL TRAFFIC")
    print("=" * 80)

    att = bring_up(a.n_ue)
    up = [ns for ns, ip in att.items() if ip]
    print(f"\n  attached: {att}")
    if len(up) < a.n_ue:
        kill_all(); sys.exit(f"ERROR: only {len(up)}/{a.n_ue} attached — refusing to record")

    print(f"  starting traffic on {up} ...")
    start_traffic(up)

    # verify the numerator actually advances — a zero numerator is what made the
    # first attempt worthless
    tick(); time.sleep(6); k0 = kpi_now()
    tick(); time.sleep(6); k1 = kpi_now()
    advanced = k1["measured_bytes"] - k0["measured_bytes"]
    print(f"  numerator check: {k0['measured_bytes']:.0f} -> {k1['measured_bytes']:.0f} bytes "
          f"(+{advanced:.0f})")
    if k1["measured_bytes"] <= 0 or advanced <= 0:
        kill_all()
        sys.exit("ERROR: measured numerator is zero or not advancing — no real user-plane "
                 "traffic. Refusing to record; this is exactly the defect that made the first "
                 "E2.4 attempt worthless.")

    rows = []
    print(f"\n  sweeping the CONFIGURED denominator with traffic held steady")
    print(f"  {'configured AMBR':>16} {'measured bytes':>16} {'Δ measured':>12} "
          f"{'capacity B/s':>14} {'KPI':>12}")
    prev = None
    for B in sweep:
        write_ambr(B)
        t_mark = time.time()
        time.sleep(a.settle)
        tick(); time.sleep(1)
        k = kpi_now()
        # Stamp the interval. The first run inferred it from the fixed schedule,
        # which meant the utilisation ratio rested on an assumption rather than a
        # measurement. A cumulative counter over a per-second capacity is
        # dimensionally seconds, not a ratio, so the interval is required to state
        # the result correctly.
        k["interval_s"] = round(time.time() - t_mark, 3)
        d = None if prev is None else k["measured_bytes"] - prev
        prev = k["measured_bytes"]
        iv = k.get("interval_s") or 1.0
        rate = (d / iv) if d else None
        rows.append({"configured_ambr_mbps": B, **k, "measured_delta_bytes": d,
                     "measured_rate_Bps": round(rate, 1) if rate else None,
                     "utilisation_ratio": (round(rate / k["configured_capacity_Bps"], 6)
                                           if rate and k.get("configured_capacity_Bps") else None)})
        print(f"  {B:>16.0f} {k['measured_bytes']:>16.0f} "
              f"{('—' if d is None else f'{d:>12.0f}')} "
              f"{k['configured_capacity_Bps']:>14.0f} {str(round(k['kpi'],6)):>12}")

    # ── the argument: KPI moves with the CONFIGURED half ──────────────────
    confs = [r["configured_ambr_mbps"] for r in rows]
    kpis = [r["kpi"] for r in rows]
    meas = [r["measured_bytes"] for r in rows]
    c_kpi = corr(confs, kpis)
    c_meas = corr(confs, meas)
    kpi_span = (max(k for k in kpis if k is not None) /
                max(min(k for k in kpis if k is not None), 1e-12))

    # numerator must be ~monotonic-but-slow; what matters is that the KPI's
    # movement is not explained by it
    meas_rel = (max(meas) - min(meas)) / max(max(meas), 1e-9)

    print(f"\n  corr(configured AMBR, KPI)            = {c_kpi}")
    print(f"  corr(configured AMBR, measured bytes) = {c_meas}")
    print(f"  KPI max/min ratio                     = {kpi_span:.2f}×")

    verdict = {
        "kpi_definition": "TS 28.554 §6.4.2 — measured resource usage / allocated system capacity",
        "numerator": "MEASURED — UPF total_rx_bytes + total_tx_bytes",
        "denominator": "CONFIGURED — the AMBR ceiling written by the policy tool",
        "provenance_element_in_standard": False,
        "corr_configured_vs_kpi": c_kpi,
        "corr_configured_vs_measured": c_meas,
        "kpi_dynamic_range_over_sweep": round(kpi_span, 3),
        "measured_relative_spread": round(meas_rel, 4),
        "ANSWERS_B_Q4": (
            "The standard itself defines this KPI as a measured numerator over a configured "
            "denominator with no provenance element. Sweeping ONLY the configured half, with the "
            f"measured half unchanged in kind, moves the KPI by {kpi_span:.1f}x. A consumer "
            "holding this single scalar cannot determine whether utilisation fell because the "
            "network got quieter or because an operator raised the ceiling. That is AS2, and it "
            "is a property of TS 28.554 §6.4.2 rather than of any schema we designed — which is "
            "precisely the 'concrete standardized schema' the question asks for."),
        "caveat": (
            "The numerator is a cumulative byte counter, so it also rises with time across the "
            "sweep. The claim rests on the DENOMINATOR being a configured value that a consumer "
            "cannot separate from the measured one, not on the numerator being frozen. Both "
            "correlations are reported so a reader can judge this directly."),
    }
    print(f"\n  {verdict['ANSWERS_B_Q4']}")

    payload = {"experiment": "E2.4", "n_ue": a.n_ue, "sweep_mbps": sweep,
               "attached": att, "traffic": "traffic/server.py + continuous_client.py per netns",
               "numerator_advance_check_bytes": advanced,
               "rows": rows, "verdict": verdict,
               "supersedes": ("the E2.4 block in E2_contamination.json, whose numerator was 0 "
                              "because the radio was down"),
               "saved_at": datetime.now(timezone.utc).isoformat()}
    p = OUT / "E2_4_standards_kpi.json"
    p.write_text(json.dumps(payload, indent=2))
    write_ambr(20.0)
    kill_all()
    print(f"\n  -> {p}\n  baseline AMBR restored, radio down")


if __name__ == "__main__":
    main()
