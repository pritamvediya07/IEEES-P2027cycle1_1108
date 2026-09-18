#!/bin/bash
# Entrypoint for UERANSIM container
# MODE=gnb: run only the gNB
# MODE=ue:  run both gNB and UE (gNB in background, UE in foreground)
# MODE=both: alias for ue

set -e

MODE=${MODE:-gnb}
GNB_CFG=${GNB_CFG:-/config/gnb.yaml}
UE_CFG=${UE_CFG:-/config/ue.yaml}

# Enable IP forwarding (needed for UE TUN routing)
sysctl -w net.ipv4.ip_forward=1 2>/dev/null || true

case "$MODE" in
  gnb)
    echo "[UERANSIM] Starting gNB (connecting to AMF)..."
    exec nr-gnb -c "$GNB_CFG"
    ;;
  ue|both)
    echo "[UERANSIM] Starting gNB in background..."
    nr-gnb -c "$GNB_CFG" &
    GNB_PID=$!
    echo "[UERANSIM] gNB PID=$GNB_PID — waiting 5s for registration..."
    sleep 5
    echo "[UERANSIM] Starting UE..."
    nr-ue -c "$UE_CFG" &
    UE_PID=$!
    echo "[UERANSIM] UE PID=$UE_PID"
    # Wait for either process to exit
    wait -n "$GNB_PID" "$UE_PID"
    ;;
  *)
    echo "[UERANSIM] Unknown MODE=$MODE. Use: gnb | ue | both"
    exit 1
    ;;
esac
