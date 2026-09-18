#!/usr/bin/env bash
# Data-plane smoke test — srsRAN, self-contained (no internet required).
#
# Under UERANSIM every uesimtunX had rx=0 in EVERY run ever recorded (0 non-zero
# total_rx_bytes across 3,846 result files), because the UE address lived in the
# HOST's `local` routing table and downlink was short-circuited to lo.
#
# srsRAN puts the UE in its own netns, so downlink genuinely traverses the RAN.
# All traffic here is between the UE netns and OUR OWN server on the UPF-side
# gateway (10.45.0.1). Nothing leaves the machine, so host/site firewall policy
# is irrelevant — same model the UERANSIM traffic/ harness used.
#
#   sudo ./smoke_dataplane.sh [ue1]

set -u
NS="${1:-ue1}"
GW=10.45.0.1
PORT=5299
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "  ${G}[PASS]${N} $1"; }; bad(){ echo -e "  ${R}[FAIL]${N} $1"; }
warn(){ echo -e "  ${Y}[WARN]${N} $1"; }
[ "$(id -u)" -eq 0 ] || { bad "must run as root"; exit 1; }

ctr(){ ip netns exec "$NS" cat /proc/net/dev 2>/dev/null | awk '/tun_srsue/{gsub(":","",$1); print $2" "$10}'; }
UEIP=$(ip netns exec "$NS" ip -4 -o addr show tun_srsue 2>/dev/null | grep -oP 'inet \K[\d.]+')

echo "════════════════════════════════════════════════════════"
echo "  srsRAN data-plane smoke — netns=$NS  UE=${UEIP:-NONE}  server=$GW:$PORT"
echo "════════════════════════════════════════════════════════"
[ -n "$UEIP" ] || { bad "no tun_srsue in $NS — is srsUE running?"; exit 1; }

# ── T0: RRC state. Everything below is meaningless if the UE is idle. ───────
echo
echo "── T0: RRC connection state ──"
if grep -q "Received RRC Release" /tmp/srsran/ue1.stdout 2>/dev/null && \
   ! tail -3 /tmp/srsran/ue1.stdout 2>/dev/null | grep -q "RRC Connected"; then
  warn "UE saw an RRC Release — it may be idle (inactivity_timer)"
else
  ok "no trailing RRC Release"
fi
echo "    gNB-UEs at AMF: $(journalctl -u open5gs-amfd --since '2 min ago' --no-pager 2>/dev/null | grep -oP 'Number of gNB-UEs is now \K\d+' | tail -1 || echo '?')"

# ── T1: the UERANSIM killer ────────────────────────────────────────────────
echo
echo "── T1: is the UE IP LOCAL to the host? (the UERANSIM killer) ──"
if ip route get "$UEIP" 2>/dev/null | grep -q "^local"; then
  bad "UE IP is in the host's local table — downlink would be short-circuited"
else
  ok "UE IP is NOT local to the host namespace"
fi

# ── T2: downlink through the RAN ───────────────────────────────────────────
echo
echo "── T2: ping our own gateway $GW through the RAN ──"
B=$(ctr); ip netns exec "$NS" ping -c 4 -W 3 -q "$GW" 2>&1 | tail -2 | sed 's/^/    /'; A=$(ctr)
RX=$(( $(echo "$A"|cut -d' ' -f1) - $(echo "$B"|cut -d' ' -f1) ))
TX=$(( $(echo "$A"|cut -d' ' -f2) - $(echo "$B"|cut -d' ' -f2) ))
echo "    tun_srsue delta: rx=+$RX  tx=+$TX"
if [ "$RX" -gt 0 ]; then ok "DOWNLINK ALIVE — rx moved (never happened under UERANSIM)"
else bad "rx still 0 — downlink not reaching the UE"; fi

# ── T3: TCP throughput against our own iperf3 server ───────────────────────
echo
echo "── T3: downlink throughput, our own iperf3 server (10 s) ──"
pkill -f "iperf3 -s -p $PORT" 2>/dev/null; sleep 1
nohup iperf3 -s -p "$PORT" >/tmp/srsran/iperf3_srv.log 2>&1 &
sleep 1
ss -lnt | grep -q ":$PORT" && ok "server listening on 0.0.0.0:$PORT" || bad "server did not bind"
B=$(ctr)
RAW=$(ip netns exec "$NS" iperf3 -c "$GW" -p "$PORT" -t 10 -J -R 2>&1)
DL=$(echo "$RAW" | python3 -c "import json,sys;print('%.2f'%(json.load(sys.stdin)['end']['sum_received']['bits_per_second']/1e6))" 2>/dev/null)
A=$(ctr)
RX3=$(( $(echo "$A"|cut -d' ' -f1) - $(echo "$B"|cut -d' ' -f1) ))
if [ -n "$DL" ]; then
  echo "    measured DOWNLINK: ${DL} Mbps    tun_srsue rx=+${RX3} bytes"
  ok "REAL THROUGHPUT MEASURED through the 5G data plane"
else
  bad "iperf3 failed: $(echo "$RAW" | grep -iE 'error|refused|unreach' | head -1)"
fi

# ── T4: uplink ─────────────────────────────────────────────────────────────
echo
echo "── T4: uplink throughput (10 s) ──"
pkill -f "iperf3 -s -p $PORT" 2>/dev/null; sleep 1
nohup iperf3 -s -p "$PORT" >/tmp/srsran/iperf3_srv.log 2>&1 &
sleep 1
RAW2=$(ip netns exec "$NS" iperf3 -c "$GW" -p "$PORT" -t 10 -J 2>&1)
UL=$(echo "$RAW2" | python3 -c "import json,sys;print('%.2f'%(json.load(sys.stdin)['end']['sum_received']['bits_per_second']/1e6))" 2>/dev/null)
[ -n "$UL" ] && { echo "    measured UPLINK: ${UL} Mbps"; ok "uplink measured"; } || bad "uplink iperf3 failed"
pkill -f "iperf3 -s -p $PORT" 2>/dev/null

# ── T5: external (informational only — site firewall may block) ────────────
echo
echo "── T5: external 8.8.8.8 (INFORMATIONAL — not required) ──"
ip netns exec "$NS" ping -c 2 -W 2 -q 8.8.8.8 >/dev/null 2>&1 \
  && ok "external reachable" \
  || warn "external blocked — irrelevant: all experiments use the local server"

echo
echo "════════════════════════════════════════════════════════"
if [ "$RX" -gt 0 ] && [ -n "$DL" ]; then
  echo -e "  ${G}DATA PLANE IS ALIVE${N}  DL=${DL} Mbps  UL=${UL:-?} Mbps"
  echo "  This is capability UERANSIM never had. DL is the first estimate of C."
else
  echo -e "  ${R}DATA PLANE NOT WORKING${N} — see failures above."
  exit 1
fi
