#!/bin/bash
# One-time host preparation for Docker testbed
# Run as: sudo bash docker/testbed/scripts/setup-host.sh
#
# This does NOT touch the native Open5GS testbed.

set -e
echo "[setup] Loading GTP kernel module..."
modprobe gtp || { echo "[WARN] modprobe gtp failed — kernel GTP may not be available. UPF may use userspace GTP."; }

echo "[setup] Enabling IP forwarding..."
sysctl -w net.ipv4.ip_forward=1
sysctl -w net.ipv6.conf.all.forwarding=1

echo "[setup] Creating log directory..."
mkdir -p /var/log/open5gs-docker
chmod 777 /var/log/open5gs-docker

echo "[setup] Host ready."
echo ""
echo "Next steps (from repo root):"
echo "  docker compose -f docker/testbed/docker-compose.testbed.yml build"
echo "  docker compose -f docker/testbed/docker-compose.testbed.yml up -d"
echo "  docker compose -f docker/testbed/docker-compose.testbed.yml run --rm init-db"
echo "  docker compose -f docker/testbed/docker-compose.testbed.yml logs -f"
