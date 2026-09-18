#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# run_experiments.sh — PALA Full Experiment Runner
# ══════════════════════════════════════════════════════════════════════════════
# Runs the complete Wave-1 experiment suite for the PALA artifact.
# Requires the Docker testbed (Open5GS + UERANSIM) and local Ollama with the paper models.
#
# Usage:
#   ./run_experiments.sh                  # full suite (~38 h of experiments on one GPU)
#   ./run_experiments.sh --phase testbed  # start testbed only
#   ./run_experiments.sh --phase preflight
#   ./run_experiments.sh --phase calibrate  # Exp 6 Phase 1 (blocks all others)
#   ./run_experiments.sh --phase rq1
#   ./run_experiments.sh --phase rq2
#   ./run_experiments.sh --phase rq3
#   ./run_experiments.sh --phase rq4
#   ./run_experiments.sh --phase rq4-core   # Exp 5 ablation only (Table 4), ≈3.9 h
#   ./run_experiments.sh --phase rq5
#   ./run_experiments.sh --phase figures    # generate figures from stored results
#   ./run_experiments.sh --dry-run         # print what would run, no execution
#   ./run_experiments.sh --phase rq1 --resume   # continue an interrupted fresh run
#
# Each experiment phase first moves the stored results of the experiments it runs
# to artifact_logs/stored_<timestamp>/ (so the trials really re-run instead of
# resuming from the stored checkpoints), keeps the stored k†* unless you run
# --phase calibrate, and afterwards replaces final_experiments/<exp> with the fresh results,
# where reproduce_results.py compares them with the paper.
#
# See INSTALL.md for prerequisites and hardware requirements.
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAVE_DIR="$REPO_ROOT/wave_experiments"
FINAL_EXP_DIR="$REPO_ROOT/final_experiments"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"
LOG_DIR="$REPO_ROOT/final_experiments/wave1_logs"

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
die()   { error "$*"; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────
PHASE="all"
DRY_RUN=false
RESUME=false
STAMP="$(date +%Y%m%d_%H%M%S)"
STORED_DIR="$REPO_ROOT/artifact_logs/stored_$STAMP"
RES_DIR="$WAVE_DIR/results"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase)     PHASE="$2"; shift 2 ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --resume)    RESUME=true; shift ;;
        -h|--help)
            sed -n '2,29p' "$0" | sed 's/^# \?//'
            exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

run() {
    if [[ "$DRY_RUN" == "true" ]]; then
        info "[dry-run] $*"
    else
        info "Running: $*"
        "$@"
    fi
}

# ── Fresh-run bookkeeping ────────────────────────────────────────────────────
# fresh EXP: move stored results aside so the experiment's checkpoints start empty.
fresh() {
    local e="$1" d="$RES_DIR/$1"
    [[ "$RESUME" == "true" ]] && { info "  --resume: keeping $d"; return 0; }
    if [[ -d "$d" ]] && [[ -n "$(ls -A "$d" 2>/dev/null)" ]]; then
        if [[ "$DRY_RUN" == "true" ]]; then info "[dry-run] move stored $d -> $STORED_DIR/wave_results/$e"; return 0; fi
        mkdir -p "$STORED_DIR/wave_results"
        mv "$d" "$STORED_DIR/wave_results/$e"
        info "  stored results of $e moved to $STORED_DIR/wave_results/$e"
    fi
    mkdir -p "$d"
}

# keep_kstar: rq4/rq5 need k†*. Reuse the stored calibration unless this run produced one.
keep_kstar() {
    local k="$RES_DIR/exp6/kstar.json"
    [[ -f "$k" ]] && return 0
    local src
    for src in "$STORED_DIR/wave_results/exp6/kstar.json" "$FINAL_EXP_DIR/exp6/kstar.json"; do
        if [[ -f "$src" ]]; then
            run mkdir -p "$RES_DIR/exp6"; run cp "$src" "$k"
            [[ -f "${src%kstar.json}phase1_summary.json" ]] && run cp "${src%kstar.json}phase1_summary.json" "$RES_DIR/exp6/"
            info "  using stored k†* from $src (run --phase calibrate to recalibrate)"; return 0
        fi
    done
    die "no k†* calibration found — run: ./run_experiments.sh --phase calibrate"
}

# fresh_exp6_phases: set aside only the stored Phase 2–3 checkpoints; Phase 1 and k†* stay.
fresh_exp6_phases() {
    local d="$RES_DIR/exp6" x
    [[ "$RESUME" == "true" ]] && return 0
    for x in phase2_enforcement phase3_benign phase2_summary.json phase3_summary.json; do
        [[ -e "$d/$x" ]] || continue
        if [[ "$DRY_RUN" == "true" ]]; then info "[dry-run] move stored $d/$x -> $STORED_DIR/wave_results/exp6/"; continue; fi
        mkdir -p "$STORED_DIR/wave_results/exp6"; mv "$d/$x" "$STORED_DIR/wave_results/exp6/"
    done
}

# publish EXP: copy fresh results to final_experiments/ (the layout reproduce_results.py reads).
publish() {
    local e="$1" src="$RES_DIR/$1" dst="$FINAL_EXP_DIR/$1"
    if [[ "$DRY_RUN" == "true" ]]; then info "[dry-run] publish $src -> $dst"; return 0; fi
    [[ -d "$src" ]] || { warn "  no fresh results for $e"; return 0; }
    # Replace (not merge): a stale stored summary must never stand in for a missing fresh one.
    if [[ -d "$dst" ]]; then
        mkdir -p "$STORED_DIR/final_experiments"
        mv "$dst" "$STORED_DIR/final_experiments/$e"
    fi
    mkdir -p "$dst"
    case "$e" in
        exp7|exp8) mkdir -p "$dst/data"; cp -a "$src/." "$dst/data/" ;;   # stored copies live under data/
        *)         cp -a "$src/." "$dst/" ;;
    esac
    # keep the human-readable per-experiment reports (EXP*_RESULTS.md) next to the fresh data
    cp -a "$STORED_DIR/final_experiments/$e/"*.md "$dst/" 2>/dev/null || true
    date -Is > "$dst/FRESH_RUN"
    ok "  fresh $e results published to $dst (stored copy in $STORED_DIR/final_experiments/$e)"
}

# ── Phase: testbed ─────────────────────────────────────────────────────────────
phase_testbed() {
    info "Starting the Docker testbed (Open5GS + UERANSIM + collector) …"
    cd "$REPO_ROOT"
    run ./quickstart.sh --testbed-only
    # The ground-truth probe (wave_experiments/shared/probe.py) installs its own HTB/netem
    # shaper on loopback at the start of every trial, so no tc setup is needed here.
}

# ── Phase: preflight ──────────────────────────────────────────────────────────
phase_preflight() {
    info "Running preflight smoke test (S1–S5) …"
    cd "$REPO_ROOT"
    run "$PYTHON" "$WAVE_DIR/shared/smoke_test.py"
}

# ── Phase: calibrate (Exp 6 Phase 1 — k†* for RQ4/RQ5) ─────────────────────────
phase_calibrate() {
    info "Exp 6 Phase 1 — HedgeTune k†* calibration …"
    cd "$REPO_ROOT"; fresh exp6
    run "$PYTHON" "$WAVE_DIR/exp6_hedgetune.py" --phase 1 2>&1 | tee "$LOG_DIR/exp6_phase1.log"
    ok "Calibration complete: $RES_DIR/exp6/kstar.json"
}

# ── Phase: RQ1 (Table 2, Fig. 3) — ≈6.2 h ────────────────────────────────────────
phase_rq1() {
    info "RQ1 — circuit realization (≈6.2 h) …"
    cd "$REPO_ROOT"; fresh exp1; fresh exp1_multimodel; keep_kstar
    info "  Exp 1 — Qwen 2.5:72b, 30 vulnerable + 30 defended sessions (≈3.1 h)"
    run "$PYTHON" "$WAVE_DIR/exp1_end_to_end.py" --arm both --trials 30 2>&1 | tee "$LOG_DIR/exp1_qwen.log"
    info "  Exp 1 multimodel — Mistral-Large + Llama 3.1:70b, 30 each (≈3.1 h)"
    run "$PYTHON" "$WAVE_DIR/exp1_vuln_multimodel.py" --models mistral-large:latest llama3.1:70b --trials 30 \
        2>&1 | tee "$LOG_DIR/exp1_multimodel.log"
    publish exp1; publish exp1_multimodel
}

# ── Phase: RQ2 (Fig. 4, Tables 10–11) — ≈3 h ─────────────────────────────────────
phase_rq2() {
    info "RQ2 — mechanism and robustness (≈3 h) …"
    cd "$REPO_ROOT"; fresh exp2; fresh exp9; fresh exp14; fresh exp11
    info "  Exp 2 — staged / direct / null intents, 20 each (≈2.1 h)"
    run "$PYTHON" "$WAVE_DIR/exp2_register.py" --register all --trials 20 2>&1 | tee "$LOG_DIR/exp2.log"
    info "  Exp 9 — architectural sensitivity, no LLM (≈0.9 h)"
    run "$PYTHON" "$WAVE_DIR/exp9_sensitivity.py" 2>&1 | tee "$LOG_DIR/exp9.log"
    info "  Exp 14 — write-then-readback contamination, no LLM (minutes)"
    run "$PYTHON" "$WAVE_DIR/exp14_taxonomy.py" 2>&1 | tee "$LOG_DIR/exp14.log"
    info "  Exp 11 — Q-weight profiles over the Exp 1 traces (minutes; run after rq1 for fresh traces)"
    run "$PYTHON" "$WAVE_DIR/exp11_qweight.py" 2>&1 | tee "$LOG_DIR/exp11.log"
    publish exp2; publish exp9; publish exp14; publish exp11
}

# ── Phase: RQ3 (Table 3) — ≈3.1 h ────────────────────────────────────────────────
phase_rq3() {
    info "RQ3 — oversight rules (≈3.1 h) …"
    cd "$REPO_ROOT"; fresh exp3; fresh exp3_multimodel
    info "  Exp 3 — Qwen, 30 staged-control sessions (≈0.7 h)"
    run "$PYTHON" "$WAVE_DIR/exp3_pilot.py" 2>&1 | tee "$LOG_DIR/exp3.log"
    info "  Exp 3 multimodel — Mistral-Large + Llama 3.1:70b, 30 each (≈2.4 h)"
    run "$PYTHON" "$WAVE_DIR/exp3_multimodel.py" --models mistral-large:latest llama3.1:70b --trials 30 \
        2>&1 | tee "$LOG_DIR/exp3_multimodel.log"
    publish exp3; publish exp3_multimodel
}

# ── Phase: RQ4 (Tables 4, 8, 9) — ≈17 h (exp5 alone ≈3.9 h) ───────────────────────
phase_rq4() {
    info "RQ4 — defense efficacy (≈17 h; use --phase rq4-core for the ≈3.9 h ablation only) …"
    phase_rq4_core
    cd "$REPO_ROOT"
    fresh_exp6_phases
    info "  Exp 6 Phases 2–3 — enforcement and benign acceptance (≈5.5 h with Phase 1)"
    run "$PYTHON" "$WAVE_DIR/exp6_hedgetune.py" --phase 2 2>&1 | tee "$LOG_DIR/exp6_phase2.log"
    run "$PYTHON" "$WAVE_DIR/exp6_hedgetune.py" --phase 3 2>&1 | tee "$LOG_DIR/exp6_phase3.log"
    fresh exp7
    info "  Exp 7 — adaptive prompts, 5 prompts × 10 reps × 4 conditions (≈7.7 h)"
    run "$PYTHON" "$WAVE_DIR/exp7_adaptive.py" --reps 10 2>&1 | tee "$LOG_DIR/exp7.log"
    fresh exp15
    info "  Exp 15 — inference-time BoN-PALA baseline (Table 4 BoN row)"
    run "$PYTHON" "$WAVE_DIR/exp15_inference_vs_session.py" 2>&1 | tee "$LOG_DIR/exp15.log"
    publish exp6; publish exp7; publish exp15
}

phase_rq4_core() {
    info "  Exp 5 — necessity/sufficiency ablation, 5 variants × 20 (≈3.9 h)"
    cd "$REPO_ROOT"; fresh exp5; keep_kstar
    run "$PYTHON" "$WAVE_DIR/exp5_ablation.py" --variant all --trials 20 2>&1 | tee "$LOG_DIR/exp5.log"
    publish exp5
}

# ── Phase: RQ5 (Table 6) — ≈7.8 h ────────────────────────────────────────────────
phase_rq5() {
    info "RQ5 — deployability (≈7.8 h) …"
    cd "$REPO_ROOT"; fresh exp8; fresh exp10; fresh exp13; keep_kstar
    info "  Exp 8 — benign workflows (≈4.6 h)"
    run "$PYTHON" "$WAVE_DIR/exp8_utility.py" 2>&1 | tee "$LOG_DIR/exp8.log"
    info "  Exp 10 — latency and per-call overhead (minutes)"
    run "$PYTHON" "$WAVE_DIR/exp10_latency.py" 2>&1 | tee "$LOG_DIR/exp10.log"
    info "  Exp 13 — post-incident recovery (≈3.1 h)"
    run "$PYTHON" "$WAVE_DIR/exp13_recovery.py" 2>&1 | tee "$LOG_DIR/exp13.log"
    publish exp8; publish exp10; publish exp13
}

# ── Phase: figures ────────────────────────────────────────────────────────────
phase_figures() {
    info "Generating all figures and tables from stored results …"
    cd "$REPO_ROOT"
    run "$PYTHON" reproduce_results.py
    ok "Figures and tables written to final_paper_results/"
}

# ── Main dispatcher ───────────────────────────────────────────────────────────
main() {
    echo ""
    echo "════════════════════════════════════════════════════════════════"
    echo "  PALA Experiment Runner"
    echo "  Phase: $PHASE$([ "$DRY_RUN" = true ] && echo " [DRY-RUN]" || true)"
    echo "════════════════════════════════════════════════════════════════"
    echo ""

    # Activate venv if it exists
    if [[ -f "$VENV/bin/activate" ]]; then
        # shellcheck source=/dev/null
        source "$VENV/bin/activate"
        ok "Activated venv: $VENV"
    else
        warn "No .venv found. Using system Python. Run: python3.12 -m venv .venv && pip install -r requirements.txt"
        PYTHON="$(command -v python3)"
    fi

    mkdir -p "$LOG_DIR"

    case "$PHASE" in
        testbed)    phase_testbed   ;;
        preflight)  phase_preflight ;;
        calibrate)  phase_calibrate ;;
        rq1)        phase_rq1       ;;
        rq2)        phase_rq2       ;;
        rq3)        phase_rq3       ;;
        rq4)        phase_rq4       ;;
        rq4-core)   phase_rq4_core  ;;
        rq5)        phase_rq5       ;;
        figures)    phase_figures   ;;
        all)
            phase_testbed
            phase_preflight
            phase_calibrate          # produces k†* for rq4/rq5
            phase_rq1
            phase_rq2                # exp11 re-scores the fresh rq1 traces
            phase_rq3
            phase_rq4
            phase_rq5
            phase_figures
            ;;
        *)
            die "Unknown phase: $PHASE. Use: testbed|preflight|calibrate|rq1|rq2|rq3|rq4|rq4-core|rq5|figures|all"
            ;;
    esac

    echo ""
    ok "Phase '$PHASE' complete."
    info "Run 'python reproduce_results.py' to verify results and generate figures."
    echo ""
}

main "$@"
