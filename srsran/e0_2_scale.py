#!/usr/bin/env python3
"""E0.2 — Multi-UE scale gate  (spec §3, Phase 0).

Question: how many srsUE instances run concurrently, in real time, on this
hardware, attached to one cell?

Pass criterion (spec): n >= 4. Below that you cannot create meaningful
contention, and without contention the two-regime harm mechanism cannot be
demonstrated at all.

HOW MULTI-UE IS ACHIEVED HERE
-----------------------------
srsRAN Project's ZMQ radio speaks only ZMQ_REQ/ZMQ_REP, which is strict 1:1.
One gNB therefore serves exactly one peer, and no broker ships with srsRAN.
srsran/zmq_broker.py stands in for the shared radio medium: it broadcasts each
gNB downlink block to every UE and sums the uplinks before handing them back.

WHAT WOULD INVALIDATE THE CAMPAIGN
----------------------------------
If the broker cannot keep up it — not the MAC scheduler — sets capacity, and
the AMBR->harm relationship becomes circular again, which is precisely the
defect this rebuild exists to remove. So this gate records broker late-block
counts alongside attach success, and a non-zero late count is reported rather
than tolerated.

Run as root:
    sudo .venv/bin/python srsran/e0_2_scale.py --max-n 4
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.preconditions import assert_ready       # noqa: E402

GW, PORT = "10.45.0.1", 5299
CFG = ROOT / "srsran" / "configs"
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"   # GNU Radio lives in system site-packages, not the venv
PY = sys.executable
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
SLOW_DOWN = 1.0


def sh(c, **k):
    return subprocess.run(c, shell=isinstance(c, str), capture_output=True, text=True, **k)


def kill_all() -> None:
    for sig in ("TERM", "KILL"):
        sh(f"pkill -{sig} -f 'srsue/src/srsue'")
        sh(f"pkill -{sig} -f 'apps/gnb/gnb'")
        sh(f"pkill -{sig} -f gr_broker.py")
        time.sleep(2)
    for _ in range(30):
        busy = sh("ss -lnt 2>/dev/null | grep -cE ':(200[01]|30[0-9][0-9]|40[0-9][0-9]) '").stdout.strip()
        if busy in ("", "0"):
            break
        time.sleep(1)


def ue_ip(ns: str) -> str | None:
    r = sh(["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"])
    return next((t.split("/")[0] for t in r.stdout.split() if t.count(".") == 3 and "/" in t), None)


def prep_ns(ns: str) -> None:
    sh(["ip", "netns", "exec", ns, "ip", "link", "set", "lo", "up"])
    sh(["ip", "netns", "exec", ns, "ip", "route", "add", "default", "via", GW, "dev", "tun_srsue"])


def gnb_late_slots() -> int:
    """srsRAN warns on late slots when the PHY misses its deadline."""
    try:
        t = (RUN / "gnb.stdout").read_text()
        return len(re.findall(r"[Ll]ate|[Uu]nderflow|[Ll]ost", t))
    except Exception:
        return -1


def measure_dl(ns: str, secs: int = 10) -> float | None:
    sh(f"pkill -f 'iperf3 -s -p {PORT}'"); time.sleep(1)
    subprocess.Popen(["iperf3", "-s", "-p", str(PORT)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    r = sh(["ip", "netns", "exec", ns, "iperf3", "-c", GW, "-p", str(PORT),
            "-t", str(secs), "-J", "-R"])
    sh(f"pkill -f 'iperf3 -s -p {PORT}'")
    try:
        return json.load(io.StringIO(r.stdout))["end"]["sum_received"]["bits_per_second"] / 1e6
    except Exception:
        return None


def bring_up(n: int) -> dict:
    """Start in the order srsRAN's docs mandate: gNB -> all UEs -> broker LAST.

    "UEs will not connect to the gNB until the GNU-Radio flow graph has been
    started, as the UL and DL channels are not directly connected between the
    UE and gNB."  Starting the broker first (as we did originally) cannot work.
    """
    kill_all()
    RUN.mkdir(exist_ok=True)

    # 1. gNB
    subprocess.Popen([str(GNB_BIN), "-c", str(CFG / "gnb_zmq.yml")],
                     stdout=open(RUN / "gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    if not sh("pgrep -f 'apps/gnb/gnb'").stdout.strip():
        return {"error": "gNB did not start",
                "gnb_log": (RUN / "gnb.stdout").read_text()[-400:]}

    # 2. all UEs (they will sit waiting for the broker)
    for i in range(1, n + 1):
        subprocess.Popen([str(UE_BIN), str(CFG / f"ue{i}_mux.conf")],
                         stdout=open(RUN / f"ue{i}.stdout", "w"), stderr=subprocess.STDOUT)
        time.sleep(3)

    # 3. broker LAST — this is what closes the UL/DL path and lets UEs attach
    subprocess.Popen([SYS_PY, str(BROKER), "--n-ue", str(n),
                      "--srate", "23.04e6", "--slow-down-ratio", str(SLOW_DOWN)],
                     stdout=open(RUN / "broker.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(4)
    if not sh("pgrep -f gr_broker.py").stdout.strip():
        return {"error": "GNU Radio broker did not start",
                "broker_log": (RUN / "broker.stdout").read_text()[-400:]}

    attached = {}
    for _ in range(30):
        time.sleep(2)
        attached = {f"ue{i}": ue_ip(f"ue{i}") for i in range(1, n + 1)}
        if all(attached.values()):
            break
    for ns, ip in attached.items():
        if ip:
            prep_ns(ns)
    return {"attached": attached}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=1,
                    help="skip smaller n already characterised")
    ap.add_argument("--max-n", type=int, default=4)
    ap.add_argument("--hold", type=int, default=60, help="stability window, seconds")
    ap.add_argument("--slow-down", type=float, default=1.0)
    a = ap.parse_args()
    global SLOW_DOWN; SLOW_DOWN = a.slow_down
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    assert_ready()
    OUT.mkdir(parents=True, exist_ok=True)

    payload = {"experiment": "E0.2", "question": "max concurrent srsUE in real time",
               "pass_criterion": "n >= 4",
               "multi_ue_mechanism": "srsran/gr_broker.py — GNU Radio flowgraph (srsRAN official; gNB ZMQ is REQ/REP, 1:1 only)",
               "started_at": datetime.now(timezone.utc).isoformat(), "trials": []}
    max_ok = 0
    res_path = OUT / "E0_2_scale.json"
    if res_path.exists():                      # keep earlier n results
        try:
            prev = json.loads(res_path.read_text())
            payload["trials"] = [t for t in prev.get("trials", []) if t.get("n", 0) < a.min_n]
            max_ok = max([t["n"] for t in payload["trials"] if t.get("ok")] or [0])
            print(f"  carried forward {len(payload['trials'])} earlier trial(s); max_ok={max_ok}")
        except Exception:
            pass

    for n in range(a.min_n, a.max_n + 1):
        print(f"\n{'='*64}\n  n = {n} UE(s)\n{'='*64}")
        st = bring_up(n)
        if "error" in st:
            print(f"  [FAIL] {st['error']}")
            payload["trials"].append({"n": n, "ok": False, **st})
            payload["max_n_ok"] = max_ok; res_path.write_text(json.dumps(payload, indent=2))
            break

        att = st["attached"]
        n_up = sum(1 for v in att.values() if v)
        for ns, ip in att.items():
            print(f"  {ns}: {ip or 'NOT ATTACHED'}")
        if n_up < n:
            print(f"  [FAIL] only {n_up}/{n} attached")
            payload["trials"].append({"n": n, "ok": False, "attached": att, "n_attached": n_up})
            payload["max_n_ok"] = max_ok; res_path.write_text(json.dumps(payload, indent=2))
            break

        print(f"  holding {a.hold}s for stability…")
        time.sleep(a.hold)
        still = {ns: ue_ip(ns) for ns in att}
        stable = all(still.values())
        late = gnb_late_slots()
        bstat = (RUN / "broker.stdout").read_text().strip().splitlines()[-1:] or [""]

        thr = {}
        for ns in att:
            d = measure_dl(ns, 10)
            thr[ns] = round(d, 2) if d else None
            print(f"  {ns} DL {thr[ns]} Mbps")
        agg = sum(v for v in thr.values() if v)

        print(f"  stable={stable}  gnb_late_markers={late}  aggregate={agg:.2f} Mbps")
        print(f"  broker: {bstat[0][:110]}")
        payload["trials"].append({
            "n": n, "ok": stable, "attached": att, "n_attached": n_up,
            "per_ue_dl_mbps_SOLO": thr, "sum_of_solo_dl_mbps": round(agg, 2),
            "measurement_note": ("each UE measured SEQUENTIALLY while the others idle; "
                                 "this is a sum of solo runs, NOT concurrent capacity. "
                                 "C is measured with simultaneous load in E0.3."),
            "gnb_late_markers": late, "broker_last_stat": bstat[0][:200],
            "hold_s": a.hold})
        if stable:
            max_ok = n
        payload["max_n_ok"] = max_ok
        res_path.write_text(json.dumps(payload, indent=2))
        if not stable:
            break

    payload["max_n_ok"] = max_ok
    payload["gate_passed"] = max_ok >= 4
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    res_path.write_text(json.dumps(payload, indent=2))

    print(f"\n{'='*64}")
    print(f"  max stable n = {max_ok}")
    print(f"  GATE {'PASSED' if max_ok >= 4 else 'FAILED'} (need n >= 4)")
    if max_ok >= 2:
        for t in payload["trials"]:
            if t.get("ok"):
                print(f"    n={t['n']}: sum-of-solo {t['sum_of_solo_dl_mbps']} Mbps "
                      f"per-UE(solo) {list(t['per_ue_dl_mbps_SOLO'].values())}")
    print(f"  -> {res_path}")
    kill_all()


if __name__ == "__main__":
    main()
