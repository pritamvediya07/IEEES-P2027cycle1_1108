#!/usr/bin/env python3
# traffic/server.py
# Multi-client TCP file receiver — handles all 10 UEs simultaneously.
# Each UE connects, sends a file, and disconnects.
# Files saved to traffic/received/<ue_ip>_<filename>
#
# Run first (Terminal A):
#   cd <artifact-root>
#   python3 traffic/server.py

import socket
import os
import threading
import struct
import time

HOST    = '0.0.0.0'
PORT    = 7654
SAVE_DIR = os.path.join(os.path.dirname(__file__), 'received')
os.makedirs(SAVE_DIR, exist_ok=True)

lock = threading.Lock()


def handle_client(conn: socket.socket, addr: tuple) -> None:
    ue_ip = addr[0]
    try:
        # Protocol: 4-byte little-endian filename length, filename, then raw file bytes until close
        raw_len = _recv_exact(conn, 4)
        if not raw_len:
            return
        name_len = struct.unpack('<I', raw_len)[0]
        filename = _recv_exact(conn, name_len).decode('utf-8')

        save_path = os.path.join(SAVE_DIR, f"{ue_ip}_{filename}")
        total = 0
        with open(save_path, 'wb') as f:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)

        with lock:
            print(f"  [OK]  {ue_ip:>15}  ->  {filename:<30}  {total:>10,} bytes  saved to received/{ue_ip}_{filename}")
    except Exception as exc:
        with lock:
            print(f"  [ERR] {ue_ip}: {exc}")
    finally:
        conn.close()


def _recv_exact(conn: socket.socket, n: int) -> bytes:
    buf = b''
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return b''
        buf += chunk
    return buf


def main() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(20)
    print(f"=== 5G Traffic Server listening on port {PORT} ===")
    print(f"    Saving received files to: {SAVE_DIR}")
    print(f"    Waiting for UE connections...\n")
    print(f"  {'UE IP':>15}    {'Filename':<30}  {'Bytes':>10}")
    print(f"  {'-'*15}    {'-'*30}  {'-'*10}")

    try:
        while True:
            conn, addr = srv.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        srv.close()


if __name__ == '__main__':
    main()
