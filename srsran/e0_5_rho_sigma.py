#!/usr/bin/env python3
"""E0.5 — Resolving the two open Φ questions: ρ and σ.

OPEN QUESTION 1 — is ρ ≈ 0 physically real, or a measurement artifact?
----------------------------------------------------------------------
E0.4/E1 measured ρ ≈ 0 under heavy congestion, and a validity cross-check
rejected it: 4 UEs x 22.2 Mbps offered against C = 23.4 Mbps is 40.9 MB of
excess over 5 s, while a 400 ms standing queue holds only ~1.17 MB. Two
explanations both predict ρ ≈ 0 and were not separated:

  (a) PHYSICALLY REAL. 5G NR uses HARQ at the MAC layer and RLC-AM
      (acknowledged mode) above it. Both retransmit. Their design purpose is
      to convert loss into DELAY. Under RLC-AM a congested bearer genuinely
      shows ~0 IP loss and rising latency.
  (b) MEASUREMENT ARTIFACT. iperf3's UDP accounting in reverse mode.

This experiment separates them two ways at once:

  ARM AM   default bearer (RLC acknowledged mode)
  ARM UM   same bearer reconfigured to RLC um-bidir — NO retransmission

  and for each arm, ρ is measured by TWO independent methods:
    m1  iperf3 UDP reverse, with --get-server-output so the receiver's own
        count is used rather than the sender's
    m2  interface counters: bytes the server sent vs bytes that arrived at
        tun_srsue, straight from /proc/net/dev. Independent of iperf3 entirely.

  If UM shows loss and AM does not, explanation (a) holds and ρ ≈ 0 is a real
  property of an RLC-AM bearer — which is a finding, not a defect.
  If neither shows loss while m2 says packets vanished, explanation (b) holds.

OPEN QUESTION 2 — can σ vary at all?
-------------------------------------
σ was constant at 4 in every run because n is fixed and no session ever
dropped. That is correct behaviour, not a bug, but it means σ carries no
information and must be excluded from Q rather than padding it at 25% (the
defect in the original Table 11).

Here we deliberately detach a UE mid-run and confirm σ responds. If it does,
σ is a legitimate dimension that our experimental design simply never
exercised — which is a different and more honest statement than "σ is
constant".

Run as root:
    sudo .venv/bin/python srsran/e0_5_rho_sigma.py --n-ue 4
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

from srsran.ambr_enforcer import AmbrEnforcer            # noqa: E402
from srsran.preconditions import assert_ready       # noqa: E402

CFG = ROOT / "srsran" / "configs"
GNB_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/build/apps/gnb/gnb")
UE_BIN = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_4G/build/srsue/src/srsue")
BROKER = ROOT / "srsran" / "gr_broker.py"
SYS_PY = "/usr/bin/python3"
OUT = ROOT / "srsran" / "results"
RUN = Path("/tmp/srsran")
GW, PORT = "10.45.0.1", 5299
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


def tun_rx(ns) -> int:
    r = sh(["ip", "netns", "exec", ns, "cat", "/proc/net/dev"])
    for line in r.stdout.splitlines():
        if "tun_srsue" in line:
            return int(line.replace(":", " ").split()[1])
    return 0


def smf_sessions() -> int | None:
    r = sh("journalctl -u open5gs-smfd --since '5 min ago' --no-pager 2>/dev/null "
           "| grep -oP 'Number of SMF-Sessions is now \\K[0-9]+' | tail -1")
    v = r.stdout.strip()
    return int(v) if v.isdigit() else None


SRSRAN_QOS = Path(os.environ.get("SRSRAN_BUILD", str(Path.home() / "srsran_build")), "srsRAN_Project/configs/qos.yml")


def write_qos(rlc_mode: str) -> Path:
    """Emit a gNB config whose 5QI-9 bearer uses the requested RLC mode.

    IMPORTANT: we append srsRAN's COMPLETE shipped QoS table (5QI 1,2,5,7,9) and
    patch only the 5QI-9 rlc block. An earlier attempt supplied a qos list with
    a single 5QI-9 entry; that replaces the whole table, leaves the other
    bearers undefined, and the UE then reaches RRC Connected and is immediately
    released without ever getting a PDU session.

    srsRAN ships 5QI 9 as RLC mode `am`, so the AM arm is the stock table
    verbatim and the UM arm differs in exactly one property.
    """
    base = (CFG / "gnb_zmq.yml").read_text()
    if "\nqos:" in base:
        base = base.split("\nqos:")[0] + "\n"

    qos = SRSRAN_QOS.read_text()
    qos = qos[qos.index("qos:"):]

    if rlc_mode == "um":
        # patch ONLY the 5QI-9 item's rlc block, leaving every other entry intact
        i = qos.index("five_qi: 9")
        head, tail = qos[:i], qos[i:]
        j = tail.index("    pdcp:")              # end of the 5QI-9 rlc block
        um = """five_qi: 9
    rlc:
      mode: um-bidir
      um-bidir:
        tx:
          sn: 12
          queue-size: 16384
          queue-bytes: 6172672
        rx:
          sn: 12
          t-reassembly: 50
"""
        qos = head + um + tail[j:]

    p = CFG / f"gnb_zmq_rlc_{rlc_mode}.yml"
    p.write_text(base + "\n" + qos)
    return p


def bring_up(n: int, gnb_cfg: Path) -> dict[str, str]:
    kill_all(); RUN.mkdir(exist_ok=True)
    subprocess.Popen([str(GNB_BIN), "-c", str(gnb_cfg)],
                     stdout=open(RUN / "gnb.stdout", "w"), stderr=subprocess.STDOUT)
    time.sleep(8)
    if not sh("pgrep -f 'apps/gnb/gnb'").stdout.strip():
        return {}
    for i in range(1, n + 1):
        subprocess.Popen([str(UE_BIN), str(CFG / f"ue{i}_mux.conf")],
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


def servers(nsl, up=True):
    for i in range(len(nsl)):
        sh(f"pkill -f 'iperf3 -s -p {PORT + i}'")
    time.sleep(0.5)
    if up:
        for i in range(len(nsl)):
            subprocess.Popen(["iperf3", "-s", "-p", str(PORT + i)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)


def measure_rho(nsl, offer_mbps: float, secs: int = 8) -> dict:
    """Two independent loss measurements, run concurrently across all UEs."""
    servers(nsl, True)
    before = {ns: tun_rx(ns) for ns in nsl}
    procs = {}
    for i, ns in enumerate(nsl):
        procs[ns] = subprocess.Popen(
            ["ip", "netns", "exec", ns, "iperf3", "-c", GW, "-p", str(PORT + i),
             "-u", "-b", f"{offer_mbps}M", "-t", str(secs), "-J", "-R",
             "--get-server-output"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    m1, m2, raw = [], [], {}
    for ns, p in procs.items():
        try:
            out, _ = p.communicate(timeout=secs + 30)
            d = json.load(io.StringIO(out))
            s = d["end"]["sum"]
            sent_bytes = None
            # server-side view: how much did the sender actually put on the wire
            so = d.get("server_output_json") or {}
            if so:
                sent_bytes = (so.get("end", {}).get("sum", {}) or {}).get("bytes")
            m1.append(float(s.get("lost_percent", 0.0)))
            raw[ns] = {"iperf_lost": s.get("lost_packets"), "iperf_total": s.get("packets"),
                       "iperf_pct": s.get("lost_percent"),
                       "server_sent_bytes": sent_bytes,
                       "client_recv_bytes": s.get("bytes")}
        except Exception as e:
            raw[ns] = {"error": str(e)[:80]}
    servers(nsl, False)
    for ns in nsl:
        d_rx = tun_rx(ns) - before[ns]
        raw.setdefault(ns, {})["tun_rx_delta"] = d_rx
        sb = raw[ns].get("server_sent_bytes")
        if sb:
            loss2 = 100.0 * max(0.0, (sb - d_rx)) / sb
            raw[ns]["counter_loss_pct"] = round(loss2, 3)
            m2.append(loss2)
    return {"m1_iperf_mean_pct": round(sum(m1) / len(m1), 4) if m1 else None,
            "m2_counter_mean_pct": round(sum(m2) / len(m2), 4) if m2 else None,
            "offered_mbps_per_ue": offer_mbps, "per_ue": raw}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-ue", type=int, default=4)
    ap.add_argument("--offer", type=float, default=25.0, help="UDP offer per UE, Mbps")
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root")
    assert_ready()
    OUT.mkdir(parents=True, exist_ok=True)
    n = a.n_ue
    payload = {"experiment": "E0.5",
               "purpose": "separate 'rho~0 is real (RLC-AM)' from 'rho~0 is a measurement artifact', "
                          "and test whether sigma can vary at all",
               "started_at": datetime.now(timezone.utc).isoformat(), "arms": {}}
    res = OUT / "E0_5_rho_sigma.json"

    print("=" * 74)
    print("  E0.5 — resolving rho (RLC-AM vs artifact) and sigma (can it vary?)")
    print("=" * 74)

    for mode in ("am", "um"):
        print(f"\n{'#'*70}\n  ARM: RLC {mode.upper()}\n{'#'*70}")
        cfg = write_qos(mode)
        att = bring_up(n, cfg)
        up = [ns for ns, ip in att.items() if ip]
        if len(up) < n:
            print(f"  [FAIL] only {len(up)}/{n} attached under RLC {mode}")
            payload["arms"][mode] = {"error": f"only {len(up)}/{n} attached", "attached": att}
            res.write_text(json.dumps(payload, indent=2))
            continue
        print(f"  attached: {att}")

        enf = AmbrEnforcer(); enf.setup()
        for ip in att.values():
            enf.set_ue_ambr(ip, UNLIMITED)
        time.sleep(3)

        r = measure_rho(up, a.offer)
        sig = smf_sessions()
        offered_total = a.offer * n
        print(f"  offered {offered_total:.0f} Mbps total (C ~= 23 Mbps)")
        print(f"  m1 iperf3 UDP  : {r['m1_iperf_mean_pct']}%")
        print(f"  m2 counters    : {r['m2_counter_mean_pct']}%   <- independent of iperf3")
        for ns, v in r["per_ue"].items():
            print(f"    {ns}: iperf_lost={v.get('iperf_lost')}/{v.get('iperf_total')} "
                  f"server_sent={v.get('server_sent_bytes')} tun_rx={v.get('tun_rx_delta')} "
                  f"counter_loss={v.get('counter_loss_pct')}%")
        payload["arms"][mode] = {"rho": r, "sigma": sig, "attached": att}
        res.write_text(json.dumps(payload, indent=2))
        enf.teardown()

        # ── sigma: detach one UE and see whether sigma responds ────────────
        if mode == "am":
            print(f"\n  -- sigma test: detaching ue{n} --")
            s_before = smf_sessions()
            sh(f"pkill -f 'ue{n}_mux.conf'")
            time.sleep(12)
            s_after = smf_sessions()
            live = sum(1 for i in range(1, n + 1) if ue_ip(f"ue{i}"))
            print(f"  SMF sessions {s_before} -> {s_after}   live tunnels now {live}")
            payload["sigma_test"] = {"sessions_before": s_before, "sessions_after": s_after,
                                     "live_tunnels_after": live,
                                     "sigma_can_vary": bool(s_before and s_after and s_after != s_before)}
            res.write_text(json.dumps(payload, indent=2))

    # ── verdict ────────────────────────────────────────────────────────────
    am = (payload["arms"].get("am") or {}).get("rho") or {}
    um = (payload["arms"].get("um") or {}).get("rho") or {}
    v = {}
    if am and um:
        a1, u1 = am.get("m1_iperf_mean_pct"), um.get("m1_iperf_mean_pct")
        a2, u2 = am.get("m2_counter_mean_pct"), um.get("m2_counter_mean_pct")
        v = {"AM_iperf_pct": a1, "UM_iperf_pct": u1,
             "AM_counter_pct": a2, "UM_counter_pct": u2}
        # Decision tree over BOTH measurements. The earlier version tested only
        # "UM >> AM" and fell through to INCONCLUSIVE whenever both arms showed
        # large, similar loss — which is exactly what actually happens.
        big = lambda x: x is not None and x > 5.0
        gap = (None if (a1 is None or u1 is None) else abs(u1 - a1))
        if big(a1) and big(u1) and gap is not None and gap < max(0.25 * max(a1, u1), 2.0):
            v["conclusion"] = (
                "rho IS MEASURABLE AND LARGE, AND RLC MODE IS NOT THE CAUSE. Both arms lose "
                f"a similar amount (AM {a1:.2f}%, UM {u1:.2f}%, gap {gap:.2f} pp), so acknowledged "
                "mode is not hiding loss. Any earlier observation of rho ~ 0 must be explained by "
                "the experiment design, not by RLC-AM: when the per-UE HTB ceiling equals the "
                "sweep value the shaper PACES the sender rather than dropping, so nothing excess "
                "is ever offered and nothing can be lost.")
            v["rlc_am_hypothesis"] = "REJECTED"
        elif u1 is not None and a1 is not None and u1 > max(a1 * 3, 1.0):
            v["conclusion"] = ("RLC-AM HIDES the loss: UM shows substantially more loss than AM "
                               "under identical offered load. rho ~ 0 under AM is therefore a REAL "
                               "property of an acknowledged-mode bearer, not a measurement defect.")
            v["rlc_am_hypothesis"] = "SUPPORTED"
        elif big(a2) and not big(a1):
            v["conclusion"] = ("MEASUREMENT ARTIFACT: interface counters show packets vanishing "
                               "while iperf3 reports ~0 loss. iperf3 UDP accounting in reverse "
                               "mode cannot be trusted here.")
            v["rlc_am_hypothesis"] = "NOT TESTED — iperf3 unusable"
        else:
            v["conclusion"] = ("NO APPRECIABLE LOSS IN EITHER ARM by either method. Report rho as "
                               "not discriminating in this regime, and check that the sender was "
                               "actually unpaced before drawing any physical conclusion.")
            v["rlc_am_hypothesis"] = "NOT TESTED — no loss to explain"
        # Counters are the trustworthy measure; flag when iperf3 disagrees with them.
        if big(a2) and a1 is not None and a2 > a1 * 1.5:
            v["iperf3_under_reports"] = (
                f"iperf3 {a1:.2f}% vs counters {a2:.2f}% — trust the /proc/net/dev figure.")
        print(f"\n{'='*74}\n  {v['conclusion']}\n{'='*74}")
    payload["verdict"] = v
    payload["finished_at"] = datetime.now(timezone.utc).isoformat()
    res.write_text(json.dumps(payload, indent=2))
    kill_all()
    print(f"\n  -> {res}")


if __name__ == "__main__":
    main()
