#!/usr/bin/env bash
# srsRAN launcher — Paper 1108 rebuild
#
# Replaces UERANSIM. The Open5GS core, collector, MCP tools and LLM agent are
# unchanged; only the RAN and UEs change.
#
#   sudo ./run_srsran.sh start [n]   # gNB + n UEs (default 1)
#   sudo ./run_srsran.sh stop
#   sudo ./run_srsran.sh status
#
# Design notes:
#  * Each UE runs in its own netns (ue1..ueN). This is the fix for the
#    UERANSIM downlink failure: the UE address is no longer local to the host
#    namespace, so downlink genuinely traverses the RAN.
#  * PIDs are captured for the ACTUAL process, not a `su` wrapper — the bug
#    that made start_network.sh --stop orphan the collector.
#  * Exit status reflects reality: the banner is gated on real checks.

set -u

SRS_ROOT="${SRSRAN_BUILD:-$HOME/srsran_build}"
GNB_BIN="$SRS_ROOT/srsRAN_Project/build/apps/gnb/gnb"
UE_BIN="$SRS_ROOT/srsRAN_4G/build/srsue/src/srsue"
CFG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/configs"
RUN="/tmp/srsran"
mkdir -p "$RUN"

G='\033[0;32m'; R='\033[0;31m'; Y='\033[1;33m'; N='\033[0m'
ok(){ echo -e "  ${G}[OK]${N} $1"; }; bad(){ echo -e "  ${R}[FAIL]${N} $1"; }
warn(){ echo -e "  ${Y}[WARN]${N} $1"; }

need_root(){ [ "$(id -u)" -eq 0 ] || { bad "must run as root (netns + TUN)"; exit 1; }; }

stop_all(){
  echo "Stopping srsRAN…"
  [ -f "$RUN/gnb.pid" ] && kill "$(cat "$RUN/gnb.pid")" 2>/dev/null
  for f in "$RUN"/ue*.pid; do [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null; done
  sleep 2
  pkill -9 -f "apps/gnb/gnb"   2>/dev/null
  pkill -9 -f "srsue/src/srsue" 2>/dev/null
  rm -f "$RUN"/*.pid
  ok "stopped"
}

status(){
  echo "  gNB      : $(pgrep -cf 'apps/gnb/gnb') proc"
  echo "  srsUE    : $(pgrep -cf 'srsue/src/srsue') proc"
  for ns in $(ip netns list 2>/dev/null | awk '{print $1}' | grep '^ue'); do
    ip=$(ip netns exec "$ns" ip -4 -o addr show tun_srsue 2>/dev/null | awk '{print $4}')
    printf "  %-8s : %s\n" "$ns" "${ip:-no tun}"
  done
}

case "${1:-start}" in
  stop)   need_root; stop_all; exit 0 ;;
  status) status; exit 0 ;;
esac

need_root
NUE="${2:-1}"

echo "════════════════════════════════════════════════════"
echo "  srsRAN 5G SA (ZMQ)  —  gNB + ${NUE} UE(s)"
echo "════════════════════════════════════════════════════"

# ── preconditions ──────────────────────────────────────────────────────────
[ -x "$GNB_BIN" ] || { bad "gnb binary missing: $GNB_BIN"; exit 1; }
[ -x "$UE_BIN"  ] || { bad "srsue binary missing: $UE_BIN"; exit 1; }
ok "binaries present"

if pgrep -f "nr-gnb|nr-ue" >/dev/null 2>&1; then
  bad "UERANSIM is still running — it conflicts on AMF NGAP and the 10.45.0.0/16 pool"
  echo "        sudo pkill -9 -f nr-ue ; sudo pkill -9 -f nr-gnb"
  exit 1
fi
ok "no UERANSIM conflict"

for svc in open5gs-amfd open5gs-smfd open5gs-upfd open5gs-nrfd; do
  systemctl is-active --quiet "$svc" || { bad "$svc not active"; exit 1; }
done
ok "Open5GS core active"

for i in $(seq 1 "$NUE"); do
  ip netns list 2>/dev/null | grep -qw "ue$i" || ip netns add "ue$i"
done
ok "netns ue1..ue$NUE ready"

stop_all >/dev/null 2>&1

# ── gNB ────────────────────────────────────────────────────────────────────
echo
echo "Starting gNB…"
"$GNB_BIN" -c "$CFG/gnb_zmq.yml" > "$RUN/gnb.stdout" 2>&1 &
echo $! > "$RUN/gnb.pid"
for i in $(seq 1 20); do
  grep -qiE "NG setup (procedure )?(is )?success|Connected to AMF" "$RUN/gnb.stdout" "$RUN/gnb.log" 2>/dev/null && break
  sleep 1
done
if grep -qiE "NG setup (procedure )?(is )?success|Connected to AMF" "$RUN/gnb.stdout" "$RUN/gnb.log" 2>/dev/null; then
  ok "gNB up (PID $(cat "$RUN/gnb.pid")) — NG Setup successful"
else
  warn "gNB started but NG Setup not confirmed — see $RUN/gnb.stdout"
fi

# ── UEs ────────────────────────────────────────────────────────────────────
echo
echo "Starting ${NUE} UE(s)…"
for i in $(seq 1 "$NUE"); do
  "$UE_BIN" "$CFG/ue${i}.conf" > "$RUN/ue${i}.stdout" 2>&1 &
  echo $! > "$RUN/ue${i}.pid"
  sleep 4
done
sleep 8

# ── verification (real, not a banner) ──────────────────────────────────────
echo
echo "Verifying…"
UP=0
for i in $(seq 1 "$NUE"); do
  IP=$(ip netns exec "ue$i" ip -4 -o addr show tun_srsue 2>/dev/null | grep -oP 'inet \K[\d.]+')
  if [ -n "$IP" ]; then ok "ue$i  tun_srsue  $IP"; UP=$((UP+1))
  else bad "ue$i  no tun_srsue — see $RUN/ue${i}.stdout"; fi
done

echo
if [ "$UP" -eq "$NUE" ]; then
  echo -e "  ${G}srsRAN READY — ${UP}/${NUE} UE(s) attached${N}"
else
  echo -e "  ${R}INCOMPLETE — ${UP}/${NUE} UE(s) attached${N}"
fi
echo "  logs: $RUN/gnb.stdout  $RUN/ue*.stdout"
[ "$UP" -eq "$NUE" ] || exit 1
