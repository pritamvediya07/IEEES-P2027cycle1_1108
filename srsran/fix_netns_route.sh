#!/usr/bin/env bash
# Add the default route inside each UE netns and diagnose reachability.
#
# srsUE creates tun_srsue and an on-link /24 route, but no DEFAULT route, so
# anything outside 10.45.0.0/24 returns "Network is unreachable" from the netns.
# The UPF gateway (10.45.0.1) is the correct next hop for all UE traffic.
#
#   sudo ./fix_netns_route.sh [ue1 ue2 ...]

set -u
G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "  ${G}[OK]${N} $1"; }; bad(){ echo -e "  ${R}[FAIL]${N} $1"; }
warn(){ echo -e "  ${Y}[WARN]${N} $1"; }
[ "$(id -u)" -eq 0 ] || { bad "must run as root"; exit 1; }

NSLIST=("$@"); [ ${#NSLIST[@]} -eq 0 ] && NSLIST=($(ip netns list | awk '{print $1}' | grep '^ue' | sort))

for NS in "${NSLIST[@]}"; do
  echo "════ $NS ════"
  IP=$(ip netns exec "$NS" ip -4 -o addr show tun_srsue 2>/dev/null | grep -oP 'inet \K[\d.]+')
  [ -n "$IP" ] || { warn "no tun_srsue — skipping"; continue; }
  echo "  UE IP: $IP"

  echo "  routes before:"; ip netns exec "$NS" ip route show | sed 's/^/    /'

  # loopback up (iperf3 and some tools need it)
  ip netns exec "$NS" ip link set lo up 2>/dev/null

  # default route via the UPF gateway, on-link through the tunnel
  if ! ip netns exec "$NS" ip route show default | grep -q .; then
    ip netns exec "$NS" ip route add 10.45.0.1 dev tun_srsue 2>/dev/null
    ip netns exec "$NS" ip route add default via 10.45.0.1 dev tun_srsue 2>/dev/null \
      || ip netns exec "$NS" ip route add default dev tun_srsue 2>/dev/null
    ok "default route added"
  else
    ok "default route already present"
  fi

  # DNS inside the netns (Open5GS advertises 8.8.8.8)
  mkdir -p "/etc/netns/$NS"
  echo "nameserver 8.8.8.8" > "/etc/netns/$NS/resolv.conf"

  echo "  routes after:"; ip netns exec "$NS" ip route show | sed 's/^/    /'

  echo "  reachability:"
  ip netns exec "$NS" ping -c 2 -W 3 -q 10.45.0.1 >/dev/null 2>&1 \
    && ok "gateway 10.45.0.1 reachable" || bad "gateway unreachable"
  ip netns exec "$NS" ping -c 2 -W 3 -q 8.8.8.8 >/dev/null 2>&1 \
    && ok "external 8.8.8.8 reachable (NAT working)" \
    || warn "external unreachable — MASQUERADE or upstream"
  echo
done

echo "════ host-side NAT check ════"
iptables -t nat -S POSTROUTING 2>/dev/null | grep -E "10\.45\.0\.0/16" | sed 's/^/  /' \
  || warn "no MASQUERADE rule found for 10.45.0.0/16"
echo "  ip_forward = $(cat /proc/sys/net/ipv4/ip_forward)"
