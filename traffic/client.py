#!/usr/bin/env python3
# traffic/client.py
# Sends a file through the 5G tunnel to the server.
# Must be invoked via nr-binder to force traffic through the UE tunnel.
#
# Usage (bind to a specific UE IP with nr-binder):
#   cd <artifact-root>/UERANSIM/build
#   ./nr-binder <UE_IP> python3 <artifact-root>/traffic/client.py <file_path>
#
# Example:
#   ./nr-binder 10.45.0.16 python3 <artifact-root>/traffic/client.py \
#       <artifact-root>/traffic/files/report.json

import socket
import struct
import sys
import os

SERVER_IP   = '10.45.0.1'   # Open5GS UPF ogstun gateway — reachable from all UE tunnels
SERVER_PORT = 7654

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: client.py <file_path>")
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.isfile(file_path):
        print(f"ERROR: File not found: {file_path}")
        sys.exit(1)

    filename      = os.path.basename(file_path)
    file_size     = os.path.getsize(file_path)
    filename_bytes = filename.encode('utf-8')

    print(f"Connecting to {SERVER_IP}:{SERVER_PORT} ...")
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((SERVER_IP, SERVER_PORT))
    print(f"Connected. Sending '{filename}' ({file_size:,} bytes) through 5G tunnel...")

    # Send filename length (4 bytes) + filename
    client.sendall(struct.pack('<I', len(filename_bytes)))
    client.sendall(filename_bytes)

    # Stream file contents
    sent = 0
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            client.sendall(chunk)
            sent += len(chunk)

    client.close()
    print(f"Done. {sent:,} bytes sent successfully through the 5G tunnel.")

if __name__ == '__main__':
    main()
