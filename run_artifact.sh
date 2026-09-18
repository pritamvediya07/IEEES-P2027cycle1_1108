#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
#  run_artifact.sh — one command for the PALA artifact (IEEE S&P 2027)
# ══════════════════════════════════════════════════════════════════════════════
#
#   ./run_artifact.sh                  offline checks of the main results (~30 s after install, any machine)
#   ./run_artifact.sh env              hardware/software readiness report for the live tracks
#   ./run_artifact.sh live-ueransim    Track B: Docker testbed + all RQs + re-check (~38 h, local GPU >= 48 GB)
#   sudo ./run_artifact.sh live-srsran Track C2: paper-quoted srsRAN experiments (root, srsRAN build)
#   sudo ./run_artifact.sh all         verify, then both live tracks
#
#   Options:  --dry-run   show the plan and prerequisite checks without executing
#             --help
#
#  Every stage is logged to artifact_logs/<stage>.log and summarised in
#  artifact_logs/SUMMARY.txt. The exit status is 0 only if every executed stage passed.
#  Live tracks back up the stored results they will overwrite before running.
# ══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$ROOT"
LOG="$ROOT/artifact_logs"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
STAMP="$(date +%Y%m%d-%H%M%S)"

MODE="verify"; DRY=0
for a in "$@"; do
  case "$a" in
    verify|env|live-ueransim|live-srsran|all) MODE="$a" ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $a  (try --help)"; exit 2 ;;
  esac
done
mkdir -p "$LOG"

if [ -t 1 ]; then G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; C=$'\e[36m'; B=$'\e[1m'; N=$'\e[0m'
else G=""; R=""; Y=""; C=""; B=""; N=""; fi

declare -a S_NAME=() S_RES=() S_NOTE=() S_TIME=()
record() { S_NAME+=("$1"); S_RES+=("$2"); S_NOTE+=("$3"); S_TIME+=("$4"); }
hdr()    { printf "\n${B}%s${N}\n%s\n" "$1" "$(printf '─%.0s' $(seq 1 72))"; }
info()   { printf "  ${C}→${N} %s\n" "$*"; }
ok()     { printf "  ${G}✓${N} %s\n" "$*"; }
bad()    { printf "  ${R}✗${N} %s\n" "$*"; }
warn()   { printf "  ${Y}!${N} %s\n" "$*"; }
strip()  { sed 's/\x1b\[[0-9;]*m//g'; }

# run_stage NAME CHECK_FN -- command...
#   runs the command, logs it, and lets CHECK_FN decide PASS/FAIL from the log.
run_stage() {
  local name="$1" check="$2"; shift 3
  local log="$LOG/$name.log" t0 t1 rc note res
  printf "  ${C}▶${N} %-34s " "$name"
  if [ "$DRY" = 1 ]; then echo "(dry-run) $*"; record "$name" "PLAN" "$*" "-"; return 0; fi
  t0=$(date +%s)
  { echo "# $(date -Is)  $*"; "$@"; } > "$log" 2>&1; rc=$?
  t1=$(date +%s)
  note="$($check "$log" "$rc")"; res="${note%%|*}"; note="${note#*|}"
  if [ "$res" = PASS ]; then echo "${G}PASS${N}  $note"; else echo "${R}${res}${N}  $note  (see $log)"; fi
  record "$name" "$res" "$note" "$((t1-t0))s"
}

# ── checks: echo "PASS|note" or "FAIL|note" ───────────────────────────────────
chk_rc()      { [ "$2" = 0 ] && echo "PASS|exit 0" || echo "FAIL|exit $2"; }
chk_pytest()  { local s; s=$(strip < "$1" | grep -oE '([0-9]+ failed, )?[0-9]+ passed(, [0-9]+ (failed|errors?))*' | tail -1)
                [ "$2" = 0 ] && echo "PASS|$s" || echo "FAIL|${s:-exit $2}"; }
chk_trackA()  { local n f; n=$(strip < "$1" | grep -oE 'All [0-9]+ checks PASS' | grep -oE '[0-9]+' | tail -1)
                f=$(strip < "$1" | grep -c ' FAIL$')
                if [ "$2" = 0 ] && [ "$f" = 0 ] && [ "${n:-0}" -ge 39 ]; then echo "PASS|$n checks passed, 0 failed"
                else echo "FAIL|${n:-?} passed, $f failed (see log)"; fi; }
chk_passed()  { strip < "$1" | grep -q '^ *PASSED' && echo "PASS|$(strip < "$1" | grep '^ *PASSED' | tail -1 | sed 's/^ *//')" \
                                                    || echo "FAIL|no PASSED line"; }
chk_info()    { echo "PASS|informational — compare against the paper in the log"; }

# ── python / venv ─────────────────────────────────────────────────────────────
find_python() {
  local c
  for c in python3.12 python3.11 python3.10 python3; do
    # numpy 1.26.4 (pinned) ships wheels for Python 3.10-3.12 only
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)'; then
      echo "$c"; return 0; fi
  done
  return 1
}

setup_venv() {
  hdr "Python environment"
  local sys_py; sys_py="$(find_python)" || { bad "Python 3.10–3.12 not found (3.12 recommended)"; record "python" "FAIL" "no python 3.10-3.12" "-"; return 1; }
  ok "using $($sys_py --version 2>&1) ($sys_py)"
  local reqs=(requirements.txt "$@") r pipargs=()
  for r in "${reqs[@]}"; do pipargs+=(-r "$r"); done
  if [ "$DRY" = 1 ]; then info "(dry-run) would create .venv and install ${reqs[*]} + pytest"; return 0; fi
  [ -x "$PY" ] || { info "creating .venv"; "$sys_py" -m venv "$VENV" || { bad "venv creation failed"; return 1; }; }
  local want; want="$(cat "${reqs[@]}" | sha256sum | cut -c1-16)"
  if [ "$(cat "$VENV/.artifact_reqs" 2>/dev/null)" != "$want" ]; then
    info "installing requirements (first run only; log: artifact_logs/pip_install.log)"
    { "$PY" -m pip install --upgrade pip && "$PY" -m pip install "${pipargs[@]}" pytest; } > "$LOG/pip_install.log" 2>&1 \
      || { bad "pip install failed — see artifact_logs/pip_install.log"; record "pip_install" "FAIL" "see log" "-"; return 1; }
    echo "$want" > "$VENV/.artifact_reqs"
  fi
  ok "requirements installed"
}

# ══════════════════════════════════════════════════════════════════════════════
do_verify() {
  hdr "VERIFY — everything checkable offline"
  info "stored results → paper claims; no GPU, network, Docker, or root needed"
  local f missing=0
  for f in final_experiments/exp1/summary.json final_experiments/exp1_multimodel/summary.json \
           final_experiments/exp5/summary.json final_experiments/exp6/kstar.json \
           final_experiments/exp7/data/exp7_trials.jsonl final_experiments/exp8/data/summary.json \
           srsran/results/E1_harm_mechanism.json srsran/results/E6_capability_sweep.json \
           srsran/results/E8_gate_replay.json analysis/paper_numbers.json; do
    [ -e "$f" ] || { bad "missing stored result: $f"; missing=1; }
  done
  [ "$missing" = 0 ] && { ok "stored results present"; record "stored_results" "PASS" "key result files present" "-"; } \
                     || record "stored_results" "FAIL" "stored results missing" "-"
  run_stage "unit_tests"              chk_pytest  -- "$PY" -m pytest tests/test_tools.py -q
  run_stage "trackA_main_evaluation"  chk_trackA  -- "$PY" reproduce_results.py
  run_stage "trackC1_srsran_numbers"  chk_passed  -- "$PY" analysis/verify_paper.py
  run_stage "trackC1_prompt_provenance" chk_passed -- "$PY" analysis/verify_prompt_provenance.py
}

# ══════════════════════════════════════════════════════════════════════════════
have() { command -v "$1" >/dev/null 2>&1; }
ollama_has() { have ollama && ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$1"; }

do_env() {
  hdr "ENVIRONMENT — readiness for the live tracks"
  printf "  %-12s %s\n" "CPU" "$(lscpu 2>/dev/null | awk -F: '/^Model name/{gsub(/^ +/,"",$2);print $2; exit}') — $(nproc) threads"
  printf "  %-12s %s\n" "RAM" "$(free -g 2>/dev/null | awk '/Mem:/{print $2" GiB"}')"
  if have nvidia-smi; then printf "  %-12s %s\n" "GPU" "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | paste -sd';')"
  else printf "  %-12s %s\n" "GPU" "none detected (the live tracks need a GPU with >= 48 GB)"; fi
  printf "  %-12s %s\n" "OS" "$( . /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}"), kernel $(uname -r)"
  printf "  %-12s %s\n" "Disk free" "$(df -h "$ROOT" | awk 'NR==2{print $4}')"

  local rb=1 rc=1
  hdr "Track B — live UERANSIM"
  have docker && ok "docker $(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,)" || { bad "docker not found"; rb=0; }
  docker compose version >/dev/null 2>&1 && ok "docker compose v2" || { bad "docker compose v2 not found"; rb=0; }
  if ollama_has qwen2.5:72b; then ok "ollama: qwen2.5:72b (primary model)"
  else bad "ollama: qwen2.5:72b missing (every UERANSIM experiment runs it locally)"; rb=0; fi
  for m in llama3.1:70b mistral-large:latest; do ollama_has "$m" && ok "ollama: $m (RQ1 multimodel)" || warn "ollama: $m missing (needed only for RQ1 multimodel)"; done

  hdr "Track C2 — live srsRAN"
  local uhome="$HOME"; [ -n "${SUDO_USER:-}" ] && uhome="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
  local sb="${SRSRAN_BUILD:-$uhome/srsran_build}"
  [ -x "$sb/srsRAN_Project/build/apps/gnb/gnb" ] && ok "gNB binary under \$SRSRAN_BUILD ($sb)" || { bad "gNB not found under \$SRSRAN_BUILD ($sb)"; rc=0; }
  [ -x "$sb/srsRAN_4G/build/srsue/src/srsue" ]   && ok "srsUE binary under \$SRSRAN_BUILD" || { bad "srsUE not found under \$SRSRAN_BUILD"; rc=0; }
  have iperf3 && ok "iperf3" || { bad "iperf3 not found"; rc=0; }
  /usr/bin/python3 -c 'import gnuradio' 2>/dev/null && ok "GNU Radio (ZeroMQ broker for E0.x/E1)" || { bad "GNU Radio not found for /usr/bin/python3 (apt install gnuradio) — needed by E0.3/E1"; rc=0; }
  have mongod || have mongosh || docker ps 2>/dev/null | grep -q mongo && ok "MongoDB available" || { bad "MongoDB not found"; rc=0; }
  have open5gs-amfd && ok "Open5GS $(dpkg -l 2>/dev/null | awk '$2 ~ /^open5gs(:|$)/{print $3; exit}')" || { bad "Open5GS not installed natively"; rc=0; }
  for m in llama3.1:latest gemma3-12b-it-q8:latest qwen2.5:72b; do ollama_has "$m" && ok "ollama: $m (E3/E5/E6)" || warn "ollama: $m missing (LLM experiments)"; done
  [ -n "${ANTHROPIC_API_KEY:-}" ] && ok "ANTHROPIC_API_KEY set (E6 frontier tier)" || warn "ANTHROPIC_API_KEY unset — E6 runs local tiers only"
  [ "$(id -u)" = 0 ] && ok "running as root" || warn "not root — live-srsran must be run with sudo"

  hdr "Readiness"
  printf "  %-24s %s\n" "verify (offline)" "${G}ready${N} (Python 3.10–3.12)"
  printf "  %-24s %s\n" "live-ueransim" "$([ $rb = 1 ] && echo "${G}ready${N}" || echo "${R}not ready${N}")"
  printf "  %-24s %s\n" "live-srsran" "$([ $rc = 1 ] && echo "${G}ready${N}" || echo "${R}not ready${N}")"
  record "env_report" "PASS" "B $([ $rb = 1 ] && echo ready || echo not-ready), C2 $([ $rc = 1 ] && echo ready || echo not-ready)" "-"
}

backup() {  # backup LABEL paths...
  local label="$1"; shift
  local dst="$LOG/backup_${label}_${STAMP}.tar.gz"
  if [ "$DRY" = 1 ]; then info "(dry-run) would back up $* → $dst"; return 0; fi
  tar -czf "$dst" "$@" && ok "stored results backed up → ${dst#$ROOT/}" || { bad "backup failed; refusing to overwrite results"; return 1; }
}

# ══════════════════════════════════════════════════════════════════════════════
do_live_ueransim() {
  hdr "LIVE — Track B, Open5GS + UERANSIM"
  local miss=0
  have docker && docker compose version >/dev/null 2>&1 || { bad "Docker with compose v2 is required"; miss=1; }
  # Every UERANSIM experiment runs the agent on local Ollama; cloud backends are supported only
  # by exp1_vuln_multimodel.py (see MODEL_SETUP.md), so a cloud key cannot replace the GPU here.
  ollama_has qwen2.5:72b || { bad "Ollama with qwen2.5:72b is required (GPU with >= 48 GB)"; miss=1; }
  for m in mistral-large:latest llama3.1:70b; do
    ollama_has "$m" || warn "$m not pulled — needed for the Table 2 / Table 3 cross-family rows"
  done
  if [ "$miss" = 1 ]; then
    if [ "$DRY" = 1 ]; then warn "(dry-run) prerequisites missing — showing the plan anyway"
    else record "live_ueransim" "FAIL" "prerequisites missing — run: ./run_artifact.sh env" "-"; return 1; fi
  fi
  if [ ! -f .env ]; then
    if [ "$DRY" = 1 ]; then info "(dry-run) would create .env from .env.example (Ollama, as in the paper)"
    else cp .env.example .env; info "created .env from .env.example (Ollama, as in the paper)"; fi
  fi
  backup ueransim final_experiments wave_experiments/results || { record "live_ueransim" "FAIL" "backup failed" "-"; return 1; }
  warn "fresh results overwrite final_experiments/; the backup above restores the stored ones"
  run_stage "trackB_testbed_up"      chk_rc     -- ./quickstart.sh --testbed-only
  run_stage "trackB_all_experiments" chk_rc     -- ./run_experiments.sh --phase all
  run_stage "trackB_recheck_fresh"   chk_trackA -- "$PY" reproduce_results.py --fresh
  info "the re-check applies the paper's ±10 pp tolerance to the freshly generated results"
}

# ══════════════════════════════════════════════════════════════════════════════
do_live_srsran() {
  hdr "LIVE — Track C2, Open5GS + srsRAN (ZeroMQ RF)"
  if [ "$(id -u)" != 0 ] && [ "$DRY" = 0 ]; then
    bad "root is required (network namespaces, tc, iptables): sudo --preserve-env=SRSRAN_BUILD,ANTHROPIC_API_KEY ./run_artifact.sh live-srsran"
    record "live_srsran" "FAIL" "not root" "-"; return 1
  fi
  # under sudo, $HOME is root's; default to the invoking user's home
  local uhome="$HOME"; [ -n "${SUDO_USER:-}" ] && uhome="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
  export SRSRAN_BUILD="${SRSRAN_BUILD:-$uhome/srsran_build}"
  local ok_pre=1
  [ -x "$SRSRAN_BUILD/srsRAN_Project/build/apps/gnb/gnb" ] || { bad "gNB not found under \$SRSRAN_BUILD=$SRSRAN_BUILD"; ok_pre=0; }
  [ -x "$SRSRAN_BUILD/srsRAN_4G/build/srsue/src/srsue" ]   || { bad "srsUE not found under \$SRSRAN_BUILD"; ok_pre=0; }
  have iperf3 || { bad "iperf3 is required"; ok_pre=0; }
  if [ "$ok_pre" = 0 ] && [ "$DRY" = 0 ]; then record "live_srsran" "FAIL" "prerequisites missing — run: ./run_artifact.sh env" "-"; return 1; fi
  [ "$ok_pre" = 1 ] && ok "srsRAN binaries and iperf3 found"

  backup srsran srsran/results analysis/paper_numbers.json || { record "live_srsran" "FAIL" "backup failed" "-"; return 1; }
  warn "fresh results overwrite srsran/results/; the backup above restores the stored ones"
  # The LLM experiments checkpoint every trial under srsran/results/llm_trials/<exp>/ and skip
  # any trial already there, so the stored checkpoints are moved aside: every trial re-runs.
  local held="$LOG/stored_llm_trials_$(date +%Y%m%d-%H%M%S)" x
  for x in E3 E5 E6; do
    [ -d "srsran/results/llm_trials/$x" ] || continue
    if [ "$DRY" = 1 ]; then info "(dry-run) would move stored srsran/results/llm_trials/$x to $held/"
    else mkdir -p "$held"; mv "srsran/results/llm_trials/$x" "$held/"; fi
  done
  [ "$DRY" = 1 ] || info "stored LLM checkpoints moved to $held — every LLM trial re-runs"

  info "1/4  host preparation and data-plane smoke test"
  run_stage "C2_ran_up"          chk_rc -- bash srsran/run_srsran.sh start 4
  run_stage "C2_host_setup"      chk_rc -- bash srsran/setup_host_srsran.sh
  run_stage "C2_dataplane_smoke" chk_rc -- bash srsran/smoke_dataplane.sh ue1

  info "2/4  radio measurements (each experiment manages the RAN itself)"
  run_stage "C2_E0.1_ambr_enforcement" chk_rc -- "$PY" srsran/e0_1_ambr_enforcement.py
  run_stage "C2_E0.3_E0.4_regimes"     chk_rc -- "$PY" srsran/e0_3_e0_4_regimes.py --n-ue 4
  run_stage "C2_E1_harm_mechanism"     chk_rc -- "$PY" srsran/e1_harm_mechanism.py --n-ue 4
  run_stage "C2_ran_down"              chk_rc -- bash srsran/run_srsran.sh stop

  info "3/4  controller, LLM, replay, and overhead experiments"
  if [ "$DRY" = 0 ] && ! pgrep -f "collector.collector" >/dev/null 2>&1; then
    mkdir -p /tmp/srsran
    setsid nohup "$PY" -m collector.collector > "$LOG/C2_collector_daemon.log" 2>&1 < /dev/null &
    sleep 8; ok "collector daemon started"
  fi
  run_stage "C2_E4_scripted_controller" chk_rc -- "$PY" srsran/e4_scripted_controller.py --n 20
  run_stage "C2_E5_multivariable"       chk_rc -- "$PY" srsran/e5_multivariable.py --n-channel 12 --n-agent 5
  run_stage "C2_E3_attribution"         chk_rc -- "$PY" srsran/e3_attribution.py --n 5
  if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
    run_stage "C2_E6_frontier_tier" chk_rc -- "$PY" srsran/e6_capability_sweep.py --n 20 --only-frontier --frontier-backend anthropic --frontier-model claude-sonnet-4-5
  else
    warn "ANTHROPIC_API_KEY unset — skipping the E6 frontier tier"
  fi
  run_stage "C2_E6_local_tiers"         chk_rc -- "$PY" srsran/e6_capability_sweep.py --n 20 --tiers 7-8B,12-15B
  run_stage "C2_E8_gate_replay"         chk_rc -- "$PY" srsran/e8_gate_replay.py
  run_stage "C2_E10_overhead"           chk_rc -- "$PY" srsran/e10_overhead.py --n 120

  info "4/4  compare fresh results with the paper's registered numbers"
  if [ "$DRY" = 0 ] && [ -n "${SUDO_USER:-}" ]; then chown -R "$SUDO_USER:$SUDO_USER" srsran/results analysis "$LOG" 2>/dev/null; fi
  run_stage "C2_compare_with_paper" chk_passed -- "$PY" analysis/verify_paper.py --fresh
}

# ══════════════════════════════════════════════════════════════════════════════
summary() {
  local t=0 p=0 f=0 i res
  hdr "SUMMARY"
  {
    echo "PALA artifact — $MODE$([ $DRY = 1 ] && echo ' (dry-run)') — $(date -Is)"
    printf "%-34s %-6s %-8s %s\n" "stage" "result" "time" "note"
  } > "$LOG/SUMMARY.txt"
  for i in "${!S_NAME[@]}"; do
    res="${S_RES[$i]}"; t=$((t+1))
    case "$res" in PASS) p=$((p+1)); col="$G" ;; PLAN) col="$C" ;; *) f=$((f+1)); col="$R" ;; esac
    printf "  %-34s ${col}%-6s${N} %-8s %s\n" "${S_NAME[$i]}" "$res" "${S_TIME[$i]}" "${S_NOTE[$i]}"
    printf "%-34s %-6s %-8s %s\n" "${S_NAME[$i]}" "$res" "${S_TIME[$i]}" "${S_NOTE[$i]}" >> "$LOG/SUMMARY.txt"
  done
  echo
  if [ "$DRY" = 1 ]; then info "dry-run: nothing executed. Plan saved to artifact_logs/SUMMARY.txt"; return 0; fi
  if [ "$f" = 0 ]; then printf "  ${G}${B}ALL %d STAGES PASSED${N}\n" "$p"
  else printf "  ${R}${B}%d of %d STAGES FAILED${N} — logs in artifact_logs/\n" "$f" "$t"; fi
  info "summary saved to artifact_logs/SUMMARY.txt"
  [ "$f" = 0 ]
}

# ══════════════════════════════════════════════════════════════════════════════
printf "${B}PALA artifact — %s${N}%s\n" "$MODE" "$([ $DRY = 1 ] && echo '  (dry-run)')"
case "$MODE" in
  verify)        setup_venv && do_verify ;;
  env)           do_env ;;
  live-ueransim) setup_venv && do_live_ueransim ;;
  live-srsran)   setup_venv requirements-srsran.txt && do_live_srsran ;;
  all)           setup_venv requirements-srsran.txt && { do_verify; do_live_ueransim; do_live_srsran; } ;;
esac
summary
