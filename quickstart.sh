#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  PALA Testbed Quick-Start
#  IEEE S&P 2027 Artifact
# ══════════════════════════════════════════════════════════════════════════════
#
#  This script guides you through the complete setup in two paths:
#
#  Track A — Offline verification (< 1 min after install, no Docker, no GPU):
#    Reads stored trial logs → recomputes the main paper statistics → regenerates Figs 3–4
#    Run:  python reproduce_results.py
#
#  Track B — Full live testbed (≈ 38 h for every experiment; one-day plan in README):
#    Starts Open5GS 5G SA core + UERANSIM + NWDAF collector via Docker,
#    then runs experiments that generate new trial data.
#    Run:  ./quickstart.sh
#
#  See INSTALL.md for full documentation.
#
#  Usage:
#    ./quickstart.sh                 # interactive setup + testbed start
#    ./quickstart.sh --offline-only  # only run reproduce_results.py (Track A)
#    ./quickstart.sh --testbed-only  # only start Docker testbed
#    ./quickstart.sh --status        # print current testbed status
#    ./quickstart.sh --stop          # stop all testbed containers
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$REPO_ROOT/docker/testbed/docker-compose.testbed.yml"
ENV_FILE="$REPO_ROOT/.env"
ENV_EXAMPLE="$REPO_ROOT/.env.example"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
ok()    { echo -e "  ${GREEN}✓${NC}  $*"; }
warn()  { echo -e "  ${YELLOW}⚠${NC}  $*"; }
info()  { echo -e "  ${CYAN}→${NC}  $*"; }
err()   { echo -e "  ${RED}✗${NC}  $*"; }
header(){ echo -e "\n${BOLD}$*${NC}"; echo "$(printf '─%.0s' {1..60})"; }

# ── Argument parsing ──────────────────────────────────────────────────────────
MODE="full"
case "${1:-}" in
  --offline-only) MODE="offline" ;;
  --testbed-only) MODE="testbed" ;;
  --status)       MODE="status"  ;;
  --stop)         MODE="stop"    ;;
  --help|-h)
    sed -n '3,30p' "$0" | sed 's/^# \?//'
    exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1 (see ./quickstart.sh --help)" >&2; exit 2 ;;
esac

# ══════════════════════════════════════════════════════════════════════════════
banner() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║   PALA Testbed Quick-Start — IEEE S&P 2027 Artifact      ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

# ── Status ────────────────────────────────────────────────────────────────────
do_status() {
  banner
  header "Testbed Status"
  if docker compose -f "$COMPOSE_FILE" ps 2>/dev/null | grep -q "running\|Up"; then
    docker compose -f "$COMPOSE_FILE" ps
  else
    warn "Testbed is not running. Start with: ./quickstart.sh"
  fi
  echo ""
  header "Python Environment"
  if [[ -f "$PYTHON" ]]; then
    ok "venv found: $VENV"
    "$PYTHON" -c "import pymongo, sklearn, scipy; print('  Core deps OK')" 2>/dev/null || warn "Some deps missing — run: pip install -r requirements.txt"
  else
    warn "No venv — run ./quickstart.sh to set up"
  fi
  echo ""
  header "Stored Results"
  N=$(find "$REPO_ROOT/final_experiments" -name "*.jsonl" 2>/dev/null | wc -l)
  echo "  JSONL trial files: $N"
  echo ""
}

# ── Stop ─────────────────────────────────────────────────────────────────────
do_stop() {
  banner
  header "Stopping Testbed"
  docker compose -f "$COMPOSE_FILE" down
  ok "All containers stopped."
  echo ""
}

# ── Offline verification (Track A) ───────────────────────────────────────────
do_offline() {
  banner
  header "Track A — Offline Verification (~10 min)"
  info "This reads stored trial logs and recomputes all paper statistics."
  info "No Docker, GPU, or network connection required."
  echo ""

  if [[ ! -f "$PYTHON" ]]; then
    header "Setting up Python environment"
    info "Creating virtual environment with Python 3.12..."
    python3.12 -m venv "$VENV" || python3 -m venv "$VENV"
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt"
    ok "Virtual environment ready"
  fi

  echo ""
  header "Running reproduce_results.py"
  cd "$REPO_ROOT"
  "$PYTHON" reproduce_results.py
}

# ── Prerequisite checks ───────────────────────────────────────────────────────
check_prerequisites() {
  header "Checking Prerequisites"

  local ok_flag=true

  # Docker
  if command -v docker &>/dev/null; then
    local dv; dv=$(docker --version | grep -oP '[\d.]+' | head -1)
    ok "Docker $dv"
  else
    err "Docker not found. Install: https://docs.docker.com/get-docker/"
    ok_flag=false
  fi

  # Docker Compose v2
  if docker compose version &>/dev/null 2>&1; then
    ok "Docker Compose v2"
  elif command -v docker-compose &>/dev/null; then
    warn "docker-compose v1 found. Upgrade to Docker Compose v2 for best results."
    warn "Install: https://docs.docker.com/compose/install/"
  else
    err "Docker Compose not found."
    ok_flag=false
  fi

  # Python 3.12
  if command -v python3.12 &>/dev/null; then
    ok "Python 3.12 ($(python3.12 --version))"
  elif command -v python3 &>/dev/null; then
    local pv; pv=$(python3 -c "import sys; print(sys.version)" | cut -d' ' -f1)
    if python3 -c "import sys; assert sys.version_info >= (3,10)" 2>/dev/null; then
      ok "Python $pv (3.10+ required)"
    else
      warn "Python $pv found — 3.12 recommended. Some features may break."
    fi
  else
    err "Python 3.10+ not found."
    ok_flag=false
  fi

  # sudo (for host setup)
  if [[ $EUID -eq 0 ]] || sudo -n true 2>/dev/null; then
    ok "sudo available (needed for one-time host setup)"
  else
    warn "sudo not pre-authorized. You may be prompted for your password."
  fi

  if [[ "$ok_flag" == "false" ]]; then
    echo ""
    err "Missing prerequisites. Install the items above and re-run."
    exit 1
  fi
}

# ── .env configuration ────────────────────────────────────────────────────────
configure_env() {
  header "LLM API Configuration"

  if [[ -f "$ENV_FILE" ]]; then
    ok ".env already exists"
    if grep -q "your_.*key_here\|YOUR_KEY" "$ENV_FILE" 2>/dev/null; then
      warn "Placeholder key detected in .env — update it before running experiments."
    fi
    return
  fi

  info "No .env file found. Creating one from .env.example..."
  cp "$ENV_EXAMPLE" "$ENV_FILE"

  echo ""
  echo -e "${BOLD}Which LLM backend will you use?${NC}"
  echo ""
  echo "  1) Ollama (local GPU — qwen2.5:72b, ~48 GB VRAM, NO API key needed)"
  echo "  2) Google AI Studio / Gemini (cloud, free API key, no GPU)"
  echo "  3) Skip — I'll configure .env manually later"
  echo ""
  read -rp "  Enter choice [1/2/3]: " llm_choice

  case "$llm_choice" in
    1)
      ok "Configured for Ollama (localhost:11434)"
      info "Make sure ollama is running and qwen2.5:72b is pulled:"
      info "  curl -fsSL https://ollama.ai/install.sh | sh"
      info "  ollama pull qwen2.5:72b"
      ;;
    2)
      echo ""
      echo -e "  Get a free key at: ${CYAN}https://aistudio.google.com/apikey${NC}"
      read -rp "  Paste your Gemini API key: " gemini_key
      if [[ -n "$gemini_key" ]]; then
        # Uncomment Gemini lines, comment Ollama lines
        sed -i \
          -e 's/^OLLAMA_BASE_URL=/#OLLAMA_BASE_URL=/' \
          -e 's/^OLLAMA_MODEL=/#OLLAMA_MODEL=/' \
          -e "s|^# GEMINI_API_KEY=.*|GEMINI_API_KEY=$gemini_key|" \
          -e 's/^# GEMINI_MODEL=/GEMINI_MODEL=/' \
          "$ENV_FILE"
        ok "Gemini API key saved to .env"
      else
        warn "No key entered — using placeholder. Edit .env before running experiments."
      fi
      ;;
    3)
      warn "Skipping API configuration. Edit .env before running experiments."
      ;;
    *)
      warn "Invalid choice — skipping. Edit .env manually."
      ;;
  esac
}

# ── One-time host setup ───────────────────────────────────────────────────────
host_setup() {
  header "One-Time Host Setup"

  # Only run if not already done
  if lsmod 2>/dev/null | grep -q "^gtp "; then
    ok "GTP kernel module already loaded"
  else
    info "Loading GTP kernel module and enabling IP forwarding..."
    if [[ $EUID -eq 0 ]]; then
      bash "$REPO_ROOT/docker/testbed/scripts/setup-host.sh"
    else
      sudo bash "$REPO_ROOT/docker/testbed/scripts/setup-host.sh"
    fi
  fi
}

# ── Python venv setup ─────────────────────────────────────────────────────────
setup_venv() {
  header "Python Environment"

  if [[ -f "$PYTHON" ]]; then
    ok "Virtual environment exists at .venv/"
    # Quick dep check
    if "$PYTHON" -c "import pymongo, sklearn, scipy, numpy, matplotlib" 2>/dev/null; then
      ok "Core dependencies installed"
    else
      info "Installing/updating dependencies..."
      "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt"
      ok "Dependencies installed"
    fi
  else
    info "Creating Python 3.12 virtual environment..."
    if command -v python3.12 &>/dev/null; then
      python3.12 -m venv "$VENV"
    else
      python3 -m venv "$VENV"
    fi
    info "Installing dependencies (~2 min)..."
    "$VENV/bin/pip" install --quiet --upgrade pip
    "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/requirements.txt"
    ok "Virtual environment ready at .venv/"
  fi
}

# ── Build + start Docker testbed ─────────────────────────────────────────────
start_testbed() {
  header "Building Docker Testbed"
  info "This builds Open5GS + UERANSIM images (first run ~10–15 min, cached after)."
  echo ""

  cd "$REPO_ROOT"

  # Pass env file to compose
  local compose_cmd="docker compose -f $COMPOSE_FILE"
  if [[ -f "$ENV_FILE" ]]; then
    compose_cmd="$compose_cmd --env-file $ENV_FILE"
  fi

  # Build (uses cache on repeat runs)
  $compose_cmd build

  echo ""
  header "Starting 5G Testbed"
  info "Starting MongoDB, Open5GS NFs (AMF/SMF/UPF/PCF/UDM/UDR/AUSF/NRF/BSF/SCP/NSSF), UERANSIM, WebUI..."

  $compose_cmd up -d

  echo ""
  header "Waiting for Testbed to Be Ready"
  info "Polling MongoDB health (timeout: 120s)..."

  local attempts=0
  until docker compose -f "$COMPOSE_FILE" exec -T mongo-testbed \
        mongosh --eval "db.runCommand('ping').ok" --quiet 2>/dev/null | grep -q "1"; do
    attempts=$((attempts + 1))
    if [[ $attempts -ge 24 ]]; then
      err "MongoDB did not become healthy within 120s."
      err "Check logs: docker compose -f $COMPOSE_FILE logs mongo-testbed"
      exit 1
    fi
    echo -n "  ."
    sleep 5
  done
  echo ""
  ok "MongoDB healthy"

  # Initialize subscribers (idempotent)
  info "Initializing subscriber database (synthetic test UEs)..."
  $compose_cmd run --rm init-db 2>/dev/null || warn "init-db may have already run (normal on repeat starts)"

  # Wait for Open5GS NFs
  info "Waiting 20s for Open5GS NFs to register with NRF..."
  sleep 20

  # Wait for UERANSIM UE registration
  info "Checking UERANSIM UE registration..."
  sleep 10

  echo ""
  ok "5G testbed is running."
  echo ""
  echo -e "  WebUI:      ${CYAN}http://localhost:10999${NC}  (admin / 1423)"
  echo -e "  MongoDB:    ${CYAN}localhost:27020${NC}"
  echo -e "  Logs:       docker compose -f docker/testbed/docker-compose.testbed.yml logs -f"
  echo ""
}

# ── Post-start traffic enforcement ────────────────────────────────────────────
setup_tc() {
  header "Traffic Control (tc HTB)"
  info "Applying 15 Mbps loopback cap for ground-truth Q measurement..."

  # Apply tc on host loopback (experiments probe via localhost)
  if [[ $EUID -eq 0 ]]; then
    bash "$REPO_ROOT/docker/testbed/scripts/tc-setup.sh"
  else
    sudo bash "$REPO_ROOT/docker/testbed/scripts/tc-setup.sh"
  fi
}

# ── Offline verification ──────────────────────────────────────────────────────
run_offline_verify() {
  header "Offline Verification (Track A)"
  info "Recomputing paper statistics from stored trial logs..."
  echo ""
  cd "$REPO_ROOT"
  "$PYTHON" reproduce_results.py
}

# ── Print next steps ──────────────────────────────────────────────────────────
print_next_steps() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}║   Testbed is ready. Next steps:                          ║${NC}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "  ${BOLD}Verify stored results (Track A — no live network):${NC}"
  echo "    python reproduce_results.py"
  echo ""
  echo -e "  ${BOLD}Run individual experiment phases (Track B — live testbed):${NC}"
  echo "    source .venv/bin/activate"
  echo "    ./run_experiments.sh --phase rq1       # RQ1: circuit realization  (~6.2 h)"
  echo "    ./run_experiments.sh --phase rq2       # RQ2: mechanism            (~3 h)"
  echo "    ./run_experiments.sh --phase rq3       # RQ3: oversight            (~3.1 h)"
  echo "    ./run_experiments.sh --phase rq4-core  # RQ4: Table 4 ablation     (~3.9 h)"
  echo "    ./run_experiments.sh --phase rq4       # RQ4: all defense runs     (~17 h)"
  echo "    ./run_experiments.sh --phase rq5       # RQ5: deployability        (~7.8 h)"
  echo "    (one-day evaluation plan: README, 'Artifact Evaluation Plan')"
  echo "    ./run_experiments.sh --phase figures # Regenerate all figures"
  echo ""
  echo -e "  ${BOLD}Interactive analysis:${NC}"
  echo "    source .venv/bin/activate && jupyter notebook analysis/pala_analysis.ipynb"
  echo ""
  echo -e "  ${BOLD}Stop the testbed:${NC}"
  echo "    ./quickstart.sh --stop"
  echo ""
  echo -e "  ${BOLD}Documentation:${NC}"
  echo "    ARTIFACT.md              — full artifact guide"
  echo "    INSTALL.md               — detailed installation"
  echo "    CLAIMS.md                — paper claims → data file mappings"
  echo "    run_artifact.sh          — one command: verify every result offline"
  echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

case "$MODE" in
  status)
    do_status
    exit 0 ;;
  stop)
    do_stop
    exit 0 ;;
  offline)
    banner
    setup_venv
    do_offline
    exit 0 ;;
esac

# Full or testbed-only
banner
check_prerequisites
configure_env

if [[ "$MODE" == "full" ]]; then
  setup_venv
fi

host_setup
start_testbed
setup_tc

if [[ "$MODE" == "full" ]]; then
  echo ""
  read -rp "  Run offline verification now (reproduce_results.py)? [Y/n]: " do_verify
  if [[ "${do_verify:-Y}" =~ ^[Yy]$ ]]; then
    run_offline_verify
  fi
fi

print_next_steps
