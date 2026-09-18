#!/usr/bin/env bash
# MTU / path diagnostic.
#
# Symptom: ping (64 B) succeeds but iperf3 fails with
#   "unable to send control message: Bad file descriptor"
# That pattern means small packets traverse and full-size TCP segments do not.
#
# Open5GS advertises mtu: 1400 in smf.yaml. If tun_srsue is left at 1500, TCP
# negotiates an MSS the path cannot carry, large segments are dropped, the
# control socket stalls and iperf3 reports a bad descriptor.
#
#   sudo ./diag_mtu.sh [ue1]

set -u
NS="${1:-ue1}"; GW=10.45.0.1
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "  ${G}[OK]${N} $1"; }; bad(){ echo -e "  ${R}[FAIL]${N} $1"; }
[ "$(id -u)" -eq 0 ] || { bad "must run as root"; exit 1; }
X(){ ip netns exec "$NS" "$@"; }

echo "════ interface MTUs ════"
X ip -o link show tun_srsue | sed 's/^/  UE  /'
ip -o link show ogstun | sed 's/^/  host /'
echo "  Open5GS smf.yaml mtu: $(grep -E '^\s*mtu:' /etc/open5gs/smf.yaml | tr -d ' ')"

echo
echo "════ largest payload that survives (DF set) ════"
LAST=0
for sz in 500 1000 1200 1300 1372 1400 1450 1472; do
  if X ping -c 1 -W 2 -M do -s $sz -q "$GW" >/dev/null 2>&1; then
    echo "  $sz bytes ... OK"; LAST=$sz
  else
    echo "  $sz bytes ... DROPPED"; break
  fi
done
echo "  => largest working payload: $LAST  (path MTU ≈ $((LAST+28)))"

echo
echo "════ lo up inside netns? (iperf3 needs it) ════"
X ip -o link show lo | grep -q "UP" && ok "lo is up" || { bad "lo is DOWN"; X ip link set lo up; ok "brought lo up"; }

echo
echo "════ applying MTU fix ════"
NEWMTU=1400
X ip link set dev tun_srsue mtu $NEWMTU && ok "tun_srsue MTU -> $NEWMTU"
# clamp TCP MSS so the negotiated segment fits the tunnel
iptables -t mangle -C FORWARD -p tcp --tcp-flags SYN,RST SYN -s 10.45.0.0/16 \
  -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || \
iptables -t mangle -A FORWARD -p tcp --tcp-flags SYN,RST SYN -s 10.45.0.0/16 \
  -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null && ok "TCP MSS clamped to PMTU"

echo
echo "════ retest: plain TCP first (same model as traffic/server.py) ════"
pkill -f "nc -l -p 5298" 2>/dev/null
( timeout 15 nc -l -p 5298 >/dev/null 2>&1 & ) 2>/dev/null; sleep 1
if X bash -c "head -c 2000000 /dev/zero | timeout 10 nc -w 5 $GW 5298" 2>/dev/null; then
  ok "plain TCP 2 MB transfer succeeded"
else
  bad "plain TCP transfer failed"
fi

echo
echo "════ retest: iperf3 ════"
pkill -f "iperf3 -s -p 5299" 2>/dev/null; sleep 1
nohup iperf3 -s -p 5299 >/tmp/srsran/iperf3_srv.log 2>&1 & sleep 1
RAW=$(X iperf3 -c "$GW" -p 5299 -t 5 -J 2>&1)
UL=$(echo "$RAW" | python3 -c "import json,sys;print('%.2f'%(json.load(sys.stdin)['end']['sum_received']['bits_per_second']/1e6))" 2>/dev/null)
if [ -n "$UL" ]; then ok "iperf3 UPLINK: ${UL} Mbps"
else bad "iperf3 still failing: $(echo "$RAW" | grep -i error | head -1)"; fi

pkill -f "iperf3 -s -p 5299" 2>/dev/null; sleep 1
nohup iperf3 -s -p 5299 >/tmp/srsran/iperf3_srv.log 2>&1 & sleep 1
RAW2=$(X iperf3 -c "$GW" -p 5299 -t 5 -J -R 2>&1)
DL=$(echo "$RAW2" | python3 -c "import json,sys;print('%.2f'%(json.load(sys.stdin)['end']['sum_received']['bits_per_second']/1e6))" 2>/dev/null)
if [ -n "$DL" ]; then ok "iperf3 DOWNLINK: ${DL} Mbps  <-- this is the first estimate of C"
else bad "downlink still failing: $(echo "$RAW2" | grep -i error | head -1)"; fi
pkill -f "iperf3 -s -p 5299" 2>/dev/null
