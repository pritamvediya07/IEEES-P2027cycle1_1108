#!/usr/bin/env python3
"""E3-Φ — Definition 4 evaluated end-to-end, in one agent session  (paper §6.3 Target versus feedback, RQ2).

WHAT THIS CLOSES
----------------
Definition 4 requires BOTH halves in the same action sequence:

    R(a) > R(a')   AND   Q(a) < Q(a')

The rebuild established each half on its own — E2.3 measured ∂R/∂aⱼ ≠ 0 at
provably static Φ (180.0 standard vs 0.0 isolated), and E1 measured victim Q
falling from 0.4415 to 0.2580 as one slice over-provisioned. Neither experiment
contained the other: E1 had no agent, and E3 ran with `probe=None`, so no agent
session measured Q at all. `def4_satisfied` read 0/60 because the condition was
never evaluated, not because it was false.

This experiment runs the SAME published agent loop, prompts and corpora as E3,
with the radio up and a Φ probe attached, so Q is measured after every policy
call the agent makes. Definition 4 is then evaluated per session on real data.

DESIGN
------
    arms      V (standard collector) and ISO (IsolatedCollector read filter)
    registers staged  — states an explicit 60 Mbps target
              sla     — states NO numeric target, where E3 found agents inventing
                        values averaging 29x baseline

    The ISO arm is the control. Stage B/D/closure are zero under it BY
    CONSTRUCTION and are excluded from any comparison; the comparison rests on
    measured Q and on the committed policy state, neither of which is definitional.

REFUSES TO RECORD IF:
    * fewer UEs attach than requested
    * the probe self-test fails
    * the collector daemon is absent (the channel would be closed silently)

Run as root, with the LLM chain paused:
    sudo .venv/bin/python srsran/e3_phi_def4.py --n 3
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

from srsran.phi_agent_probe import PhiAgentProbe          # noqa: E402
from srsran.preconditions import assert_ready             # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW = "10.45.0.1"
BASELINE = 20.0


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def kill_radio():
    for sig in ("TERM", "KILL"):
        for pat in ("srsue/src/srsue", "apps/gnb/gnb", "gr_broker.py"):
            sh(f"pkill -{sig} -f '{pat}'")
        time.sleep(2)


def ue_ip(ns):
    r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def bring_up(n):
    kill_radio(); RUN.mkdir(exist_ok=True)
    subprocess.Popen([str(GNB), "-c", str(CFG / "gnb_zmq.yml")],
                     stdout=open(RUN / "gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    conf = lambda i: CFG / (f"ue{i}_mux.conf" if n > 1 else f"ue{i}.conf")
    for i in range(1, n + 1):
        subprocess.Popen([str(UE), str(conf(i))],
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


def collector_live():
    from srsran.preconditions import check_collector
    return check_collector()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="trials per (arm, register) cell")
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--iperf-secs", type=int, default=8)
    ap.add_argument("--model", default="qwen2.5:72b")
    ap.add_argument("--backend", default="ollama")
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (netns access for the probe)")
    for nm in ("COLLECTOR", "pymongo", "pymongo.serverSelection", "agent.agent", "httpx"):
        logging.getLogger(nm).setLevel(logging.ERROR)
    assert_ready()

    ok, why = collector_live()
    if not ok:
        sys.exit(f"ERROR: {why}\n  The contamination channel would be closed and every "
                 f"trial would read a frozen value.")
    print(f"  collector: {why}")

    from wave_experiments.shared.agent_runner import run_trial, reset_baseline_ambr
    from wave_experiments.shared.intents import CLOSED_LOOP_D_INTENTS, SLA_LOOP_INTENTS
    from wave_experiments.shared.db_clean import flush_analytics
    from collector.collector import Collector
    from srsran.llm_common import enrich

    OUT.mkdir(parents=True, exist_ok=True)
    print("=" * 84)
    print("  E3-Φ — Definition 4 evaluated end-to-end, Q measured during agent sessions")
    print("=" * 84)

    att = bring_up(a.n_ue)
    up = [ns for ns, ip in att.items() if ip]
    print(f"\n  attached: {att}")
    if len(up) < a.n_ue:
        kill_radio(); sys.exit(f"ERROR: only {len(up)}/{a.n_ue} attached — refusing to record")

    registers = {"staged": CLOSED_LOOP_D_INTENTS, "sla": SLA_LOOP_INTENTS}
    arms = {"V": "none", "ISO": "iso"}
    rows = []
    res = OUT / "E3_phi_def4.json"
    payload = {"experiment": "E3-Φ", "model": a.model, "n_ue": a.n_ue,
               "trials_per_cell": a.n, "iperf_secs": a.iperf_secs,
               "purpose": ("evaluate Definition 4 end-to-end: R(a)>R(a') AND Q(a)<Q(a') "
                           "within one agent session, with Q measured on the radio"),
               "started_at": datetime.now(timezone.utc).isoformat(), "rows": rows}

    print(f"\n  {'arm':<4} {'register':<7} {'#':>2} {'writes':>6} {'B_final':>8} "
          f"{'Q_first':>8} {'Q_last':>7} {'ΔQ':>8} {'Def4':>5}")
    for arm, defense in arms.items():
        for reg, corpus in registers.items():
            for i in range(a.n):
                reset_baseline_ambr()
                try:
                    flush_analytics(older_than_s=None)
                except Exception:
                    pass
                c = Collector()
                for _ in range(12):
                    c.collect_once()

                probe = PhiAgentProbe(up, {ns: att[ns] for ns in up},
                                      iperf_secs=a.iperf_secs)
                if not probe.selftest():
                    probe.close(); kill_radio()
                    sys.exit("ERROR: probe self-test failed — refusing to record")
                try:
                    tr = run_trial(corpus[i % len(corpus)], defense=defense, probe=probe,
                                   timeout_s=600, backend=a.backend, model=a.model)
                    ev = probe.evidence()
                    row = {"arm": arm, "register": reg, "trial": len(rows) + 1,
                           **enrich(tr, corpus[i % len(corpus)]), **ev, "error": None}
                except Exception as ex:                          # noqa: BLE001
                    row = {"arm": arm, "register": reg, "trial": len(rows) + 1,
                           "error": f"{type(ex).__name__}: {ex}"}
                finally:
                    probe.close()

                rows.append(row)
                payload["rows"] = rows
                res.write_text(json.dumps(payload, indent=2, default=str))
                if row.get("error"):
                    print(f"  {arm:<4} {reg:<7} {row['trial']:>2}  ERROR {row['error'][:50]}")
                else:
                    print(f"  {arm:<4} {reg:<7} {row['trial']:>2} "
                          f"{len(row.get('policy_values_mbps') or []):>6} "
                          f"{str(row.get('b_final_mbps')):>8} {str(row.get('q_first')):>8} "
                          f"{str(row.get('q_last')):>7} {str(row.get('delta_q')):>8} "
                          f"{str(row.get('def4_satisfied')):>5}")

    ok_rows = [r for r in rows if not r.get("error")]
    def agg(arm):
        g = [r for r in ok_rows if r["arm"] == arm]
        dq = [r["delta_q"] for r in g if r.get("delta_q") is not None]
        bf = [r["b_final_mbps"] for r in g if r.get("b_final_mbps") is not None]
        return {"n": len(g),
                "def4_satisfied": sum(1 for r in g if r.get("def4_satisfied")),
                "mean_delta_q": round(st.mean(dq), 4) if dq else None,
                "mean_b_final_mbps": round(st.mean(bf), 1) if bf else None,
                "q_measured_sessions": sum(1 for r in g if r.get("q_series"))}
    payload["per_arm"] = {arm: agg(arm) for arm in arms}
    payload["verdict"] = {
        "definition_4_evaluated_on_real_Q": True,
        "note": ("Stage B, Stage D and circuit closure are zero under ISO BY CONSTRUCTION "
                 "and are excluded here. The comparison rests on measured Q and on the "
                 "committed policy state, neither of which is definitional."),
    }
    print(f"\n  {'arm':<5} {'n':>3} {'Def4 satisfied':>15} {'mean ΔQ':>9} {'mean B_final':>13}")
    for arm, s in payload["per_arm"].items():
        print(f"  {arm:<5} {s['n']:>3} {s['def4_satisfied']:>10}/{s['n']:<4} "
              f"{str(s['mean_delta_q']):>9} {str(s['mean_b_final_mbps']):>13}")
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    res.write_text(json.dumps(payload, indent=2, default=str))
    reset_baseline_ambr(); kill_radio()
    print(f"\n  -> {res}\n  baseline restored, radio down")


if __name__ == "__main__":
    main()
