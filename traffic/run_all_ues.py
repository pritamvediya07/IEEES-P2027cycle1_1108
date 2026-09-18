#!/usr/bin/env python3
# traffic/run_all_ues.py
# Launches all 10 UE clients simultaneously through their 5G tunnels.
# Each client runs via nr-binder, binding to the correct UE tunnel IP.
# Traffic runs continuously until you press Ctrl+C.
#
# Run from the project root:
#   cd <artifact-root>
#   python3 traffic/run_all_ues.py
#
# Prerequisites:
#   1. gNB running (nr-gnb)
#   2. All 10 UEs connected (uesimtun0-9 UP)
#   3. Server running: python3 traffic/server.py  (in another terminal)

import subprocess
import signal
import sys
import os
import time

# Absolute paths — run_all_ues.py works from any cwd
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NR_BINDER    = os.path.join(PROJECT_ROOT, 'UERANSIM', 'build', 'nr-binder')
BINDER_CWD   = os.path.join(PROJECT_ROOT, 'UERANSIM', 'build')   # nr-binder needs libdevbnd.so here
CLIENT_SCRIPT = os.path.join(PROJECT_ROOT, 'traffic', 'continuous_client.py')

# UE tunnel IP -> tunnel index mapping (matches uesimtun0-9)
UE_TUNNELS = [
    ('10.45.0.16', '0'),
    ('10.45.0.17', '1'),
    ('10.45.0.18', '2'),
    ('10.45.0.19', '3'),
    ('10.45.0.20', '4'),
    ('10.45.0.21', '5'),
    ('10.45.0.22', '6'),
    ('10.45.0.23', '7'),
    ('10.45.0.24', '8'),
    ('10.45.0.25', '9'),
]


def check_prerequisites() -> bool:
    ok = True
    if not os.path.isfile(NR_BINDER):
        print(f"ERROR: nr-binder not found at {NR_BINDER}")
        ok = False
    if not os.path.isfile(CLIENT_SCRIPT):
        print(f"ERROR: continuous_client.py not found at {CLIENT_SCRIPT}")
        ok = False

    # Check at least some tunnels are up
    try:
        with open('/proc/net/dev') as f:
            content = f.read()
        tuns_up = [t for t in content.split('\n') if 'uesimtun' in t]
        if not tuns_up:
            print("WARNING: No uesimtun interfaces found in /proc/net/dev — are UEs connected?")
    except Exception:
        pass

    return ok


def launch_ue(ue_ip: str, tun_id: str) -> subprocess.Popen:
    cmd = [
        NR_BINDER, ue_ip,
        sys.executable, CLIENT_SCRIPT,
        ue_ip, tun_id
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=BINDER_CWD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    return proc


def monitor_output(procs: list) -> None:
    """Stream output from all child processes to stdout."""
    import select
    fds = {p.stdout.fileno(): p for p in procs if p.stdout}

    while fds:
        readable, _, _ = select.select(list(fds.keys()), [], [], 1.0)
        for fd in readable:
            proc = fds[fd]
            line = proc.stdout.readline()
            if line:
                print(line, end='', flush=True)
            elif proc.poll() is not None:
                del fds[fd]


def main() -> None:
    print("=" * 60)
    print("NWDAF 5G Continuous Traffic — All 10 UEs")
    print("=" * 60)

    if not check_prerequisites():
        sys.exit(1)

    procs = []

    def shutdown(sig, frame):
        print("\n[*] Ctrl+C received — stopping all UE traffic...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass
        print("[*] All UE clients stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print(f"\nLaunching {len(UE_TUNNELS)} UE clients via nr-binder...")
    print(f"  nr-binder: {NR_BINDER}")
    print(f"  client:    {CLIENT_SCRIPT}")
    print(f"  server:    10.45.0.1:7654")
    print()

    for ue_ip, tun_id in UE_TUNNELS:
        proc = launch_ue(ue_ip, tun_id)
        procs.append(proc)
        print(f"  [started] UE{tun_id} ({ue_ip})  PID={proc.pid}")
        time.sleep(0.3)   # stagger launches slightly

    print(f"\nAll {len(procs)} UEs running. Press Ctrl+C to stop.\n")
    print("-" * 60)

    monitor_output(procs)

    # If all processes exit on their own (shouldn't happen in normal use)
    print("\nAll UE processes have exited.")


if __name__ == '__main__':
    main()
