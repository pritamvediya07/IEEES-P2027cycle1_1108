#!/usr/bin/env python3
# traffic/continuous_client.py
# Runs inside nr-binder — continuously sends files through a specific UE tunnel.
# Called by run_all_ues.py; do not invoke directly.
#
# Usage (via nr-binder):
#   ./nr-binder <UE_IP> python3 continuous_client.py <UE_IP> <tunnel_id>

import socket
import struct
import sys
import os
import time
import random

SERVER_IP   = '10.45.0.1'
SERVER_PORT = 7654
RETRY_DELAY = 2    # seconds between retries on connection failure
FILES_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'files')

# All files to cycle through
ALL_FILES = [
    'test_image.jpg',
    'ue_metrics.csv',
    'kpi_report.json',
    'policy_update.txt',
    'model_gradients.bin',
]


def send_file(ue_ip: str, tun_id: str, file_path: str) -> bool:
    filename       = os.path.basename(file_path)
    file_size      = os.path.getsize(file_path)
    filename_bytes = filename.encode('utf-8')

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((SERVER_IP, SERVER_PORT))

        # Protocol: 4-byte filename length + filename + raw bytes
        sock.sendall(struct.pack('<I', len(filename_bytes)))
        sock.sendall(filename_bytes)

        sent = 0
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                sock.sendall(chunk)
                sent += len(chunk)

        sock.close()
        print(f"[UE{tun_id}|{ue_ip}] sent {filename} ({sent:,} bytes)", flush=True)
        return True

    except Exception as exc:
        print(f"[UE{tun_id}|{ue_ip}] ERROR sending {filename}: {exc}", flush=True)
        return False


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: continuous_client.py <ue_ip> <tunnel_id>")
        sys.exit(1)

    ue_ip  = sys.argv[1]
    tun_id = sys.argv[2]

    # Each UE starts at a different file so transfers don't all collide at once
    file_list = ALL_FILES[:]
    offset    = int(tun_id) % len(file_list)
    file_list = file_list[offset:] + file_list[:offset]

    print(f"[UE{tun_id}|{ue_ip}] Starting continuous traffic -> {SERVER_IP}:{SERVER_PORT}", flush=True)

    idx = 0
    while True:
        fname     = file_list[idx % len(file_list)]
        file_path = os.path.join(FILES_DIR, fname)

        if not os.path.isfile(file_path):
            print(f"[UE{tun_id}|{ue_ip}] WARNING: {fname} not found, skipping", flush=True)
            idx += 1
            continue

        ok = send_file(ue_ip, tun_id, file_path)
        if not ok:
            time.sleep(RETRY_DELAY)

        idx += 1
        # Small pause between transfers so server isn't overwhelmed
        time.sleep(0.5)


if __name__ == '__main__':
    main()
