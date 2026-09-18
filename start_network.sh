#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════
#  PALA — One-Command 5G Testbed Startup
# ════════════════════════════════════════════════════════════════════
#
#  Starts the entire 5G network + NWDAF analytics stack:
#    1. Verifies prerequisites (MongoDB, Open5GS, Ollama)
#    2. Starts gNB (base station)
#    3. Starts 10 UEs (creates uesimtun0-9 tunnels)
#    4. Starts traffic server + 10 continuous UE traffic clients
#    5. Starts NWDAF collector (background, writes analytics every 5s)
#    6. Waits for collector to accumulate initial data
#
#  After this script completes, the network is ready for experiments:
#    cd <REPO_ROOT>/experiments
#    python3 reproduce_all.py all
#
#  Usage:
#    chmod +x start_network.sh
#    sudo ./start_network.sh          # Full startup (gNB + UEs + traffic + collector)
#    sudo ./start_network.sh --no-traffic   # Skip traffic generator
#    sudo ./start_network.sh --stop         # Stop everything
#
#  Note: Requires sudo for nr-gnb and nr-ue (TUN interface creation).
#
# ════════════════════════════════════════════════════════════════════

set -e

# Resolve the real user's home even under sudo
REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || whoami)}"
REAL_HOME=$(eval echo "~$REAL_USER")

MARCUS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UERANSIM="$MARCUS/UERANSIM"
VENV="$MARCUS/.venv"
LOG_DIR="/tmp/nwdaf_network"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'  # No Color

ok()   { echo -e "  ${GREEN}[OK]${NC}  $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC}  $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC}  $1"; }
info() { echo -e "  ${CYAN}[INFO]${NC}  $1"; }

# ────────────────────────────────────────────────────────────────────
#  STOP MODE
# ────────────────────────────────────────────────────────────────────
stop_all() {
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  Stopping all 5G network components..."
    echo "════════════════════════════════════════════════════════════"

    # Traffic clients
    if [ -f "$LOG_DIR/traffic_clients.pid" ]; then
        PID=$(cat "$LOG_DIR/traffic_clients.pid")
        kill "$PID" 2>/dev/null && info "Stopped traffic clients (PID $PID)" || true
        # Kill any child nr-binder processes
        pkill -f "continuous_client.py" 2>/dev/null || true
    fi

    # Traffic server
    if [ -f "$LOG_DIR/traffic_server.pid" ]; then
        PID=$(cat "$LOG_DIR/traffic_server.pid")
        kill "$PID" 2>/dev/null && info "Stopped traffic server (PID $PID)" || true
    fi

    # NWDAF collector
    if [ -f "$LOG_DIR/collector.pid" ]; then
        PID=$(cat "$LOG_DIR/collector.pid")
        kill "$PID" 2>/dev/null && info "Stopped collector (PID $PID)" || true
    fi

    # UEs
    pkill -9 -f "nr-ue" 2>/dev/null && info "Stopped all UEs" || info "No UEs running"

    # gNB
    if [ -f "$LOG_DIR/gnb.pid" ]; then
        PID=$(cat "$LOG_DIR/gnb.pid")
        kill "$PID" 2>/dev/null && info "Stopped gNB (PID $PID)" || true
    else
        pkill -f "nr-gnb" 2>/dev/null && info "Stopped gNB" || info "No gNB running"
    fi

    # Cleanup PID files
    rm -f "$LOG_DIR"/*.pid 2>/dev/null

    echo ""
    ok "All components stopped."
    exit 0
}

# Check for --stop flag
if [ "${1:-}" = "--stop" ]; then
    stop_all
fi

NO_TRAFFIC=false
if [ "${1:-}" = "--no-traffic" ]; then
    NO_TRAFFIC=true
fi

# ────────────────────────────────────────────────────────────────────
#  BANNER
# ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  PALA — 5G Testbed Startup"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════════════════"
echo ""

mkdir -p "$LOG_DIR"

# ────────────────────────────────────────────────────────────────────
#  STEP 0: Prerequisites check
# ────────────────────────────────────────────────────────────────────
echo "Step 0: Checking prerequisites..."

PREREQ_OK=true

# Check we're running as root (needed for TUN interfaces)
if [ "$(id -u)" -ne 0 ]; then
    fail "Must run as root (sudo). TUN interfaces require elevated privileges."
    echo "       Usage: sudo ./start_network.sh"
    exit 1
fi
ok "Running as root"

# MongoDB
if systemctl is-active --quiet mongod; then
    ok "MongoDB is active"
else
    warn "MongoDB not active — starting..."
    systemctl start mongod
    sleep 2
    if systemctl is-active --quiet mongod; then
        ok "MongoDB started"
    else
        fail "Could not start MongoDB"
        PREREQ_OK=false
    fi
fi

# Open5GS core NFs
OPEN5GS_SERVICES="open5gs-nrfd open5gs-amfd open5gs-smfd open5gs-upfd \
open5gs-ausfd open5gs-udmd open5gs-udrd open5gs-pcfd open5gs-scpd open5gs-nssfd"

ALL_NFS_OK=true
for svc in $OPEN5GS_SERVICES; do
    if ! systemctl is-active --quiet "$svc"; then
        warn "$svc not active — starting..."
        systemctl start "$svc" 2>/dev/null || true
        sleep 1
        if ! systemctl is-active --quiet "$svc"; then
            fail "$svc failed to start"
            ALL_NFS_OK=false
        fi
    fi
done
if $ALL_NFS_OK; then
    ok "All Open5GS 5G SA NFs active"
else
    fail "Some Open5GS services failed to start"
    PREREQ_OK=false
fi

# Ollama
if pgrep -f "ollama" > /dev/null 2>&1; then
    ok "Ollama is running"
else
    warn "Ollama not running — attempting to start..."
    su - "$(logname)" -c "ollama serve &" 2>/dev/null || ollama serve &
    sleep 3
    if pgrep -f "ollama" > /dev/null 2>&1; then
        ok "Ollama started"
    else
        fail "Could not start Ollama"
        PREREQ_OK=false
    fi
fi

# Check llama3.1 model
OLLAMA_USER="$REAL_USER"
if su - "$OLLAMA_USER" -c "ollama list 2>/dev/null" | grep -q "llama3.1"; then
    ok "Ollama model llama3.1 available"
else
    warn "llama3.1 model not found — pulling (this may take a while)..."
    su - "$OLLAMA_USER" -c "ollama pull llama3.1" 2>/dev/null || true
fi

# UERANSIM binaries
if [ -f "$UERANSIM/build/nr-gnb" ] && [ -f "$UERANSIM/build/nr-ue" ]; then
    ok "UERANSIM binaries found"
else
    fail "UERANSIM binaries not found at $UERANSIM/build/"
    PREREQ_OK=false
fi

# Python venv
if [ -f "$VENV/bin/python3" ]; then
    ok "Python venv found at $VENV"
else
    fail "Python venv not found at $VENV"
    PREREQ_OK=false
fi

if ! $PREREQ_OK; then
    echo ""
    fail "Prerequisites not met. Fix the issues above and re-run."
    exit 1
fi

echo ""
ok "All prerequisites satisfied."
echo ""

# ────────────────────────────────────────────────────────────────────
#  STEP 1: Kill any existing instances
# ────────────────────────────────────────────────────────────────────
echo "Step 1: Cleaning up any existing instances..."

pkill -9 -f "nr-ue" 2>/dev/null || true
pkill -f "nr-gnb" 2>/dev/null || true
pkill -f "traffic/server.py" 2>/dev/null || true
pkill -f "continuous_client.py" 2>/dev/null || true
sleep 2
ok "Cleaned up previous instances"
echo ""

# ────────────────────────────────────────────────────────────────────
#  STEP 2: Start gNB
# ────────────────────────────────────────────────────────────────────
echo "Step 2: Starting gNB (base station)..."

"$UERANSIM/build/nr-gnb" -c "$UERANSIM/config/open5gs-gnb.yaml" \
    > "$LOG_DIR/gnb.log" 2>&1 &
GNB_PID=$!
echo "$GNB_PID" > "$LOG_DIR/gnb.pid"

# Wait for NG Setup success
for i in $(seq 1 15); do
    if grep -q "NG Setup procedure is successful" "$LOG_DIR/gnb.log" 2>/dev/null; then
        ok "gNB started (PID $GNB_PID) — NG Setup successful"
        break
    fi
    if [ $i -eq 15 ]; then
        warn "gNB started but NG Setup not confirmed yet (check $LOG_DIR/gnb.log)"
    fi
    sleep 1
done
echo ""

# ────────────────────────────────────────────────────────────────────
#  STEP 3: Start 10 UEs
# ────────────────────────────────────────────────────────────────────
echo "Step 3: Starting 10 UEs..."

for i in $(seq 1 10); do
    "$UERANSIM/build/nr-ue" -c "$UERANSIM/config/ue${i}.yaml" \
        > "/tmp/ue${i}.log" 2>&1 &
    echo "  UE$i started (PID $!)"
    sleep 0.5
done

# Wait for tunnels to come up
echo "  Waiting for UE tunnels to establish..."
sleep 10

TUN_COUNT=$(ip link show 2>/dev/null | grep -c "uesimtun" || echo 0)
if [ "$TUN_COUNT" -ge 1 ]; then
    ok "$TUN_COUNT UE tunnel(s) established"
else
    warn "No uesimtun interfaces detected — UEs may still be registering"
    echo "       Check logs: tail /tmp/ue1.log"
fi

# Show tunnel IPs
echo "  Tunnel IPs:"
for iface in $(ip -4 addr show 2>/dev/null | grep -oP "uesimtun\d+" | sort -u); do
    IP=$(ip -4 addr show "$iface" 2>/dev/null | grep -oP "inet \K[\d.]+")
    echo "    $iface: $IP"
done
echo ""

# ────────────────────────────────────────────────────────────────────
#  STEP 4: Start traffic (unless --no-traffic)
# ────────────────────────────────────────────────────────────────────
if $NO_TRAFFIC; then
    info "Skipping traffic generator (--no-traffic flag)"
else
    echo "Step 4: Starting traffic generator..."

    # Traffic server
    su - "$OLLAMA_USER" -c "cd $MARCUS && $VENV/bin/python3 traffic/server.py" \
        > "$LOG_DIR/traffic_server.log" 2>&1 &
    TSVR_PID=$!
    echo "$TSVR_PID" > "$LOG_DIR/traffic_server.pid"
    sleep 2

    if kill -0 "$TSVR_PID" 2>/dev/null; then
        ok "Traffic server started (PID $TSVR_PID, port 7654)"
    else
        warn "Traffic server may have failed (check $LOG_DIR/traffic_server.log)"
    fi

    # Traffic clients (10 UEs)
    su - "$OLLAMA_USER" -c "cd $MARCUS && $VENV/bin/python3 traffic/run_all_ues.py" \
        > "$LOG_DIR/traffic_clients.log" 2>&1 &
    TCLI_PID=$!
    echo "$TCLI_PID" > "$LOG_DIR/traffic_clients.pid"
    sleep 3

    if kill -0 "$TCLI_PID" 2>/dev/null; then
        ok "Traffic clients started (PID $TCLI_PID, 10 UEs)"
    else
        warn "Traffic clients may have failed (check $LOG_DIR/traffic_clients.log)"
    fi
    echo ""
fi

# ────────────────────────────────────────────────────────────────────
#  STEP 5: Start NWDAF Collector
# ────────────────────────────────────────────────────────────────────
echo "Step 5: Starting NWDAF collector..."

su - "$OLLAMA_USER" -c "cd $MARCUS && $VENV/bin/python3 -c '
import sys
sys.path.insert(0, \"$MARCUS\")
from collector.collector import Collector
import time, signal

c = Collector()
c.start()
print(\"[COLLECTOR] Running (5s interval). PID:\", __import__(\"os\").getpid(), flush=True)

def handle_term(sig, frame):
    c.stop()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_term)
signal.signal(signal.SIGINT, handle_term)

while True:
    time.sleep(60)
'" > "$LOG_DIR/collector.log" 2>&1 &
COLLECTOR_PID=$!
echo "$COLLECTOR_PID" > "$LOG_DIR/collector.pid"
sleep 3

if kill -0 "$COLLECTOR_PID" 2>/dev/null; then
    ok "NWDAF collector started (PID $COLLECTOR_PID)"
else
    warn "Collector may have failed (check $LOG_DIR/collector.log)"
fi

# ────────────────────────────────────────────────────────────────────
#  STEP 6: Wait for initial data accumulation
# ────────────────────────────────────────────────────────────────────
echo ""
echo "Step 6: Waiting 30s for initial data collection..."
echo "  (Collector writes analytics to MongoDB every 5s)"

for i in $(seq 1 6); do
    sleep 5
    echo "  ... $(( i * 5 ))s elapsed"
done

# Verify data in MongoDB
DATA_CHECK=$("$VENV/bin/python3" -c "
from pymongo import MongoClient
c = MongoClient('mongodb://localhost:27017', serverSelectionTimeoutMS=3000)
db = c['nwdaf_analytics']
upf = db['upf_metrics'].count_documents({})
smf = db['smf_metrics'].count_documents({})
print(f'upf_metrics={upf} smf_metrics={smf}')
" 2>/dev/null || echo "check_failed")

ok "Data verification: $DATA_CHECK"

# ────────────────────────────────────────────────────────────────────
#  DONE
# ────────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}5G TESTBED IS READY${NC}"
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  Components running:"
echo "    gNB:              PID $(cat $LOG_DIR/gnb.pid 2>/dev/null || echo '?')"
echo "    UEs:              $(pgrep -c -f 'nr-ue' 2>/dev/null || echo '0') processes"
echo "    Tunnels:          $(ip link show 2>/dev/null | grep -c uesimtun || echo '0') interfaces"
if ! $NO_TRAFFIC; then
echo "    Traffic server:   PID $(cat $LOG_DIR/traffic_server.pid 2>/dev/null || echo '?')"
echo "    Traffic clients:  PID $(cat $LOG_DIR/traffic_clients.pid 2>/dev/null || echo '?')"
fi
echo "    NWDAF collector:  PID $(cat $LOG_DIR/collector.pid 2>/dev/null || echo '?')"
echo ""
echo "  Logs:"
echo "    gNB:      $LOG_DIR/gnb.log"
echo "    UEs:      /tmp/ue{1..10}.log"
echo "    Traffic:  $LOG_DIR/traffic_server.log"
echo "    Collector:$LOG_DIR/collector.log"
echo ""
echo "  Next steps:"
echo "    1. Run experiments:"
echo "       cd $MARCUS/experiments"
echo "       source $VENV/bin/activate"
echo "       python3 reproduce_all.py all"
echo ""
echo "    2. Or run specific experiment groups:"
echo "       python3 reproduce_all.py v3"
echo "       python3 reproduce_all.py v7_behavioral"
echo "       python3 reproduce_all.py figures"
echo ""
echo "    3. To stop everything:"
echo "       sudo ./start_network.sh --stop"
echo ""
echo "════════════════════════════════════════════════════════════════"
