#!/usr/bin/env bash
# TCP-path diagnostic.
#
# Established so far: ICMP from the UE netns to 10.45.0.1 works (23-35 ms RTT,
# rx moves), path MTU is 1500, lo is up. TCP does not connect.
#
# ICMP-yes / TCP-no points at packet filtering, not at the RAN. This host runs
# k3s, which installs KUBE-* chains with catch-all rules that commonly drop
# traffic from unknown subnets.
#
#   sudo ./diag_tcp.sh [ue1]

set -u
NS="${1:-ue1}"; GW=10.45.0.1; P=5399
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "  ${G}[OK]${N} $1"; }; bad(){ echo -e "  ${R}[FAIL]${N} $1"; }
warn(){ echo -e "  ${Y}[WARN]${N} $1"; }
[ "$(id -u)" -eq 0 ] || { bad "must run as root"; exit 1; }
X(){ ip netns exec "$NS" "$@"; }

echo "════ 1. python TCP server on the host, correct syntax ════"
pkill -f "http.server $P" 2>/dev/null; sleep 1
nohup python3 -m http.server $P --bind 0.0.0.0 >/tmp/srsran/httpd.log 2>&1 &
sleep 2
ss -lnt | grep -q ":$P" && ok "listening on 0.0.0.0:$P" || bad "server did not bind"

echo
echo "════ 2. TCP connect from the UE netns ════"
if X timeout 8 bash -c "cat < /dev/null > /dev/tcp/$GW/$P" 2>/dev/null; then
  ok "TCP handshake to $GW:$P SUCCEEDED"
  BYTES=$(X timeout 15 curl -s -o /dev/null -w '%{size_download}' "http://$GW:$P/" 2>/dev/null)
  ok "HTTP GET returned ${BYTES:-0} bytes"
else
  bad "TCP handshake to $GW:$P FAILED (ICMP works, so this is filtering)"
fi

echo
echo "════ 3. does the SYN even reach the host? ════"
BEF=$(grep -c . /proc/net/nf_conntrack 2>/dev/null || echo 0)
X timeout 5 bash -c "cat < /dev/null > /dev/tcp/$GW/$P" 2>/dev/null
grep "10.45.0" /proc/net/nf_conntrack 2>/dev/null | grep tcp | head -3 | sed 's/^/  ct: /' \
  || warn "no TCP conntrack entries for 10.45.0.0/16 (SYN may be dropped before conntrack)"

echo
echo "════ 4. filter tables — INPUT / FORWARD policies ════"
iptables -S INPUT   2>/dev/null | head -8  | sed 's/^/  IN   /'
iptables -S FORWARD 2>/dev/null | head -8  | sed 's/^/  FWD  /'
echo "  --- chain policies ---"
iptables -L INPUT   -n 2>/dev/null | head -1 | sed 's/^/  /'
iptables -L FORWARD -n 2>/dev/null | head -1 | sed 's/^/  /'

echo
echo "════ 5. k3s / kube chains present? ════"
KN=$(iptables -S 2>/dev/null | grep -c "KUBE-")
echo "  KUBE-* rules: $KN"
iptables -S FORWARD 2>/dev/null | grep -iE "KUBE|CNI|DROP|REJECT" | head -6 | sed 's/^/  /'

echo
echo "════ 6. drop counters on ogstun path ════"
iptables -L INPUT -v -n 2>/dev/null | grep -iE "drop|reject|ogstun|10.45" | head -6 | sed 's/^/  /'

echo
echo "════ 7. TARGETED FIX — allow the UE subnet explicitly ════"
iptables -C INPUT -s 10.45.0.0/16 -j ACCEPT 2>/dev/null || {
  iptables -I INPUT 1 -s 10.45.0.0/16 -j ACCEPT && ok "INPUT: accept from 10.45.0.0/16"; }
iptables -C FORWARD -s 10.45.0.0/16 -j ACCEPT 2>/dev/null || {
  iptables -I FORWARD 1 -s 10.45.0.0/16 -j ACCEPT && ok "FORWARD: accept from 10.45.0.0/16"; }
iptables -C FORWARD -d 10.45.0.0/16 -j ACCEPT 2>/dev/null || {
  iptables -I FORWARD 1 -d 10.45.0.0/16 -j ACCEPT && ok "FORWARD: accept to 10.45.0.0/16"; }

echo
echo "════ 8. RETEST after fix ════"
if X timeout 8 bash -c "cat < /dev/null > /dev/tcp/$GW/$P" 2>/dev/null; then
  ok "TCP now CONNECTS"
  pkill -f "iperf3 -s -p 5299" 2>/dev/null; sleep 1
  nohup iperf3 -s -p 5299 >/tmp/srsran/iperf3_srv.log 2>&1 & sleep 1
  RAW=$(X iperf3 -c "$GW" -p 5299 -t 5 -J -R 2>&1)
  DL=$(echo "$RAW" | python3 -c "import json,sys;print('%.2f'%(json.load(sys.stdin)['end']['sum_received']['bits_per_second']/1e6))" 2>/dev/null)
  [ -n "$DL" ] && ok "iperf3 DOWNLINK: ${DL} Mbps   <-- first real measurement of C" \
                || bad "iperf3: $(echo "$RAW" | grep -i error | head -1)"
  pkill -f "iperf3 -s -p 5299" 2>/dev/null
else
  bad "TCP still blocked — filtering is deeper (k3s KUBE chains or nftables)"
  echo "     next: nft list ruleset | grep -A5 -i 'drop\\|reject' | head -30"
fi
pkill -f "http.server $P" 2>/dev/null
