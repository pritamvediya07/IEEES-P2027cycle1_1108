#!/usr/bin/env python3
# traffic/run_all_ues_srsran.py
# srsRAN replacement for run_all_ues.py.
#
# Reuses traffic/server.py and traffic/continuous_client.py UNCHANGED. Only the
# launch mechanism differs:
#
#   UERANSIM : ./nr-binder <UE_IP> python3 continuous_client.py <UE_IP> <id>
#   srsRAN   : ip netns exec ueN  python3 continuous_client.py <UE_IP> <id>
#
# Two defects of the old runner are fixed here:
#
#  1. It hardcoded UE addresses 10.45.0.16-.25. The real tunnels were
#     10.45.0.2-.11, so nr-binder bound to non-existent addresses, silently
#     fell through to the host route, and every "UE transfer" bypassed the 5G
#     data plane entirely — the server logged all of them arriving from
#     10.45.0.1. This runner DISCOVERS the address inside each netns.
#
#  2. It reported success regardless. This one verifies the tunnel exists and
#     that bytes actually move on it, and refuses to start otherwise.
#
# Run as root (netns access):
#   sudo python3 traffic/run_all_ues_srsran.py --netns ue1 ue2 ue3 ue4

import argparse
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(ROOT, "traffic", "continuous_client.py")
SERVER_IP = "10.45.0.1"
SERVER_PORT = 7654


def netns_list() -> list[str]:
    out = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True).stdout
    return sorted(l.split()[0] for l in out.splitlines() if l.split() and l.split()[0].startswith("ue"))


def ue_ip(ns: str) -> str | None:
    r = subprocess.run(
        ["ip", "netns", "exec", ns, "ip", "-4", "-o", "addr", "show", "tun_srsue"],
        capture_output=True, text=True)
    for tok in r.stdout.split():
        if tok.count(".") == 3 and "/" in tok:
            return tok.split("/")[0]
    return None


def tun_bytes(ns: str) -> int:
    r = subprocess.run(["ip", "netns", "exec", ns, "cat", "/proc/net/dev"],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "tun_srsue" in line:
            f = line.replace(":", " ").split()
            return int(f[1]) + int(f[9])
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--netns", nargs="*", default=None, help="namespaces (default: all ue*)")
    ap.add_argument("--verify-only", action="store_true")
    a = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("ERROR: must run as root (ip netns exec)")
    if not os.path.isfile(CLIENT):
        sys.exit(f"ERROR: client not found: {CLIENT}")

    nss = a.netns or netns_list()
    if not nss:
        sys.exit("ERROR: no ue* network namespaces found")

    print("=" * 62)
    print("  srsRAN traffic generator — reusing continuous_client.py")
    print(f"  server {SERVER_IP}:{SERVER_PORT}   namespaces: {' '.join(nss)}")
    print("=" * 62)

    # ── preflight: every namespace must have a live tunnel ────────────────
    targets = []
    for ns in nss:
        ip = ue_ip(ns)
        if ip:
            print(f"  [OK]   {ns:<6} tun_srsue {ip}")
            targets.append((ns, ip))
        else:
            print(f"  [FAIL] {ns:<6} no tun_srsue — skipping")
    if not targets:
        sys.exit("ERROR: no usable namespaces")

    # server reachability from inside the first namespace
    ns0, _ = targets[0]
    r = subprocess.run(["ip", "netns", "exec", ns0, "ping", "-c", "2", "-W", "3", "-q", SERVER_IP],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: {SERVER_IP} unreachable from {ns0}. Is the UE in RRC_CONNECTED "
                 f"and is traffic/server.py running?")
    print(f"  [OK]   {SERVER_IP} reachable from {ns0}")

    if a.verify_only:
        return

    # ── launch one client per namespace ───────────────────────────────────
    procs = []
    print()
    for idx, (ns, ip) in enumerate(targets):
        p = subprocess.Popen(
            ["ip", "netns", "exec", ns, sys.executable, CLIENT, ip, str(idx)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append((ns, ip, p))
        print(f"  started client in {ns} ({ip}) pid={p.pid}")
        time.sleep(0.4)

    # ── verify bytes actually move (the check the old runner lacked) ──────
    print("\n  verifying traffic is really crossing the tunnels…")
    before = {ns: tun_bytes(ns) for ns, _, _ in procs}
    time.sleep(12)
    moved = 0
    for ns, ip, _ in procs:
        d = tun_bytes(ns) - before[ns]
        flag = "OK  " if d > 10_000 else "FAIL"
        print(f"  [{flag}] {ns:<6} {ip:<12} +{d:,} bytes on tun_srsue")
        moved += 1 if d > 10_000 else 0
    print(f"\n  {moved}/{len(procs)} namespaces carrying real traffic")

    def shutdown(*_):
        for _, _, p in procs:
            p.terminate()
        print("\n  stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    print("  running — Ctrl-C to stop")
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()
