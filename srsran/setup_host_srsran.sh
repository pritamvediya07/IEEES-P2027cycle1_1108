#!/usr/bin/env bash
# One-shot host preparation for the srsRAN testbed. Idempotent — safe to re-run.
#
# Run this AFTER run_srsran.sh has brought the UEs up (it needs tun_srsue to
# exist), and re-run it if the data plane ever goes quiet: k3s/kube-router
# periodically re-syncs its iptables chains and can displace our rules.
#
# WHY EACH PIECE EXISTS — all four were found empirically:
#
#  1. netns default route. srsUE creates tun_srsue and an on-link /24 but no
#     default route, so anything off-subnet returns "Network is unreachable".
#
#  2. Firewall. This host runs k3s (147 KUBE-* rules) with
#     `-P INPUT DROP` and `-P FORWARD DROP`, plus ufw. ICMP got through but
#     every TCP SYN from 10.45.0.0/16 was dropped: ping worked at 23-35 ms
#     while iperf3 died with "unable to send control message: Bad file
#     descriptor". Explicit ACCEPTs at position 1 fix it without touching
#     k3s's own chains.
#
#  3. NAT. network_run.md documents MASQUERADE but no script ever created it.
#
#  4. RRC. The gNB's inactivity_timer defaults to 120 s, which released the UE
#     to RRC_IDLE between measurements. Set to 7200 in gnb_zmq.yml.
#
#   sudo ./setup_host_srsran.sh

set -u
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; N='\033[0m'
ok(){ echo -e "  ${G}[OK]${N} $1"; }; warn(){ echo -e "  ${Y}[..]${N} $1"; }
bad(){ echo -e "  ${R}[!!]${N} $1"; }
[ "$(id -u)" -eq 0 ] || { bad "must run as root"; exit 1; }
SUBNET=10.45.0.0/16

echo "════ 1. forwarding ════"
sysctl -qw net.ipv4.ip_forward=1 && ok "ip_forward=1"

echo "════ 2. NAT ════"
iptables -t nat -C POSTROUTING -s $SUBNET ! -o ogstun -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -s $SUBNET ! -o ogstun -j MASQUERADE
ok "MASQUERADE for $SUBNET"

echo "════ 3. firewall — get ahead of k3s/ufw DROP policies ════"
for spec in "INPUT -s $SUBNET" "INPUT -d $SUBNET" \
            "FORWARD -s $SUBNET" "FORWARD -d $SUBNET" \
            "OUTPUT -d $SUBNET"; do
  chain=${spec%% *}; rest=${spec#* }
  iptables -C $chain $rest -j ACCEPT 2>/dev/null \
    || iptables -I $chain 1 $rest -j ACCEPT 2>/dev/null
done
ok "ACCEPT rules for $SUBNET in INPUT/FORWARD/OUTPUT"
echo "     INPUT  policy: $(iptables -L INPUT  -n | head -1 | grep -oP '\(policy \K\w+')"
echo "     FORWARD policy: $(iptables -L FORWARD -n | head -1 | grep -oP '\(policy \K\w+')"

echo "════ 4. per-UE namespace routing ════"
for NS in $(ip netns list 2>/dev/null | awk '{print $1}' | grep '^ue' | sort); do
  IP=$(ip netns exec "$NS" ip -4 -o addr show tun_srsue 2>/dev/null | grep -oP 'inet \K[\d.]+')
  if [ -z "$IP" ]; then warn "$NS: no tun_srsue (UE not attached) — skipped"; continue; fi
  ip netns exec "$NS" ip link set lo up 2>/dev/null
  ip netns exec "$NS" ip route show default | grep -q . || {
    ip netns exec "$NS" ip route add 10.45.0.1 dev tun_srsue 2>/dev/null
    ip netns exec "$NS" ip route add default via 10.45.0.1 dev tun_srsue 2>/dev/null; }
  mkdir -p "/etc/netns/$NS"; echo "nameserver 8.8.8.8" > "/etc/netns/$NS/resolv.conf"
  R=$(ip netns exec "$NS" ping -c 2 -W 3 -q 10.45.0.1 >/dev/null 2>&1 && echo yes || echo no)
  ok "$NS  ip=$IP  icmp=$R"
done

echo "════ 5. verification ════"
NS=""
for n in $(ip netns list | awk '{print $1}' | grep '^ue' | sort); do
  ip netns exec "$n" ip -4 -o addr show tun_srsue 2>/dev/null | grep -q inet && { NS=$n; break; }
done
if [ -n "$NS" ]; then
  P=5399; pkill -f "http.server $P" 2>/dev/null; sleep 1
  nohup python3 -m http.server $P --bind 0.0.0.0 >/dev/null 2>&1 & sleep 2
  if ip netns exec "$NS" timeout 8 bash -c "cat </dev/null >/dev/tcp/10.45.0.1/$P" 2>/dev/null; then
    ok "TCP from $NS to 10.45.0.1 works — data plane is usable"
  else
    bad "TCP still blocked from $NS — re-check firewall (k3s may have re-synced)"
  fi
  pkill -f "http.server $P" 2>/dev/null
fi
echo
echo "  Host ready. If the data plane goes quiet later, re-run this script:"
echo "  k3s/kube-router re-syncs iptables and can displace the ACCEPT rules."
