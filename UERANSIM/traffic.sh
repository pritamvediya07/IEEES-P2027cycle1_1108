#!/bin/bash
# traffic.sh — Start ping traffic through all 10 UE tunnels
# Run AFTER all 10 UEs are registered and uesimtun0-9 are up.
# Target: 10.45.0.1 (Open5GS UPF ogstun gateway — always reachable within 5G core)
# Each ping runs in the background, logs to /tmp/pingN.log
# Stop all with:  sudo pkill -9 -f "ping -I uesimtun"

# Cache sudo credentials once in the foreground (avoids 10 password prompts
# from backgrounded processes that have no TTY to read from).
echo "Enter sudo password once to cache credentials:"
sudo -v

# Kill any leftover ping processes from previous runs
echo "Cleaning up any previous ping processes..."
sudo -n pkill -9 -f "ping -I uesimtun" 2>/dev/null
sleep 1

echo "Starting traffic on uesimtun0 through uesimtun9 -> 10.45.0.1 (UPF gateway)..."

sudo -n ping -I uesimtun0 -i 1 -c 100000 10.45.0.1 > /tmp/ping0.log 2>&1 &
sudo -n ping -I uesimtun1 -i 1 -c 100000 10.45.0.1 > /tmp/ping1.log 2>&1 &
sudo -n ping -I uesimtun2 -i 1 -c 100000 10.45.0.1 > /tmp/ping2.log 2>&1 &
sudo -n ping -I uesimtun3 -i 1 -c 100000 10.45.0.1 > /tmp/ping3.log 2>&1 &
sudo -n ping -I uesimtun4 -i 1 -c 100000 10.45.0.1 > /tmp/ping4.log 2>&1 &
sudo -n ping -I uesimtun5 -i 1 -c 100000 10.45.0.1 > /tmp/ping5.log 2>&1 &
sudo -n ping -I uesimtun6 -i 1 -c 100000 10.45.0.1 > /tmp/ping6.log 2>&1 &
sudo -n ping -I uesimtun7 -i 1 -c 100000 10.45.0.1 > /tmp/ping7.log 2>&1 &
sudo -n ping -I uesimtun8 -i 1 -c 100000 10.45.0.1 > /tmp/ping8.log 2>&1 &
sudo -n ping -I uesimtun9 -i 1 -c 100000 10.45.0.1 > /tmp/ping9.log 2>&1 &

sleep 2
echo ""
echo "Traffic started. Sample output from uesimtun0:"
tail -5 /tmp/ping0.log
echo ""
echo "Check live output: tail -f /tmp/ping0.log"
echo "Stop all traffic:  sudo pkill -9 -f 'ping -I uesimtun'"
