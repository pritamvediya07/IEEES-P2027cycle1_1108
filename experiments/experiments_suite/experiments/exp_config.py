"""
Experiment Configuration — PALA artifact testbed
All constants drawn from README.md and Section 5 v3 Methodology.
"""
import os
from pathlib import Path

# ── Paths ──
MARCUS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
RESULTS_DIR = Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# ── MongoDB ──
MONGO_URI = "mongodb://localhost:27017"
DB_CORE = "open5gs"                       # NF state: subscribers, policyData.ues
DB_ANALYTICS = "nwdaf_analytics"          # Collector output: upf_metrics, smf_metrics, pcf_metrics
COLL_UPF = "upf_metrics"
COLL_SMF = "smf_metrics"
COLL_PCF = "pcf_metrics"
COLL_POLICY = "policyData.ues"            # Where H_policy writes AMBR
COLL_SUBSCRIBERS = "subscribers"

# ── Collector ──
COLLECTOR_PERIOD_S = 5                    # Δc = 5 seconds

# ── KPI Analyzer ──
# total_tx_bytes has genuine variance (std≈48K, range 566K-727K) from live traffic.
# memory_util_pct is near-constant (std≈0.04%) — not suitable for W(N) experiments.
KPI_METRIC = "memory_utilization"         # label used in agent intents
KPI_FIELD = "total_tx_bytes"              # actual MongoDB field with real variance
KPI_WINDOW_SIZE = 10                      # sliding window for Random Forest
KPI_TRAIN_RATIO = 0.80                    # 80/20 split

# ── Feasibility Checker ──
AMBR_FLOOR_BPS = 1_000_000               # 1 Mbps  (TS 23.501)
AMBR_CEILING_BPS = 1_000_000_000          # 1 Gbps

# ── Ground Truth ──
UESIM_INTERFACE = "uesimtun0"
IPERF_DURATION_S = 30
IPERF_RUNS = 5                            # repeated measurements per condition
DNN_INTERNET = "internet"

# ── LLM ──
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.1"
LLM_TEMPERATURE = 0.1

# ── V3 Experiment Parameters ──
V3_N_VALUES = [5, 10, 20, 30, 50, 100, 200, 500]
V3_REFERENCE_SERIES_LEN = 500
V3_DEFENSE_N_MIN = 30
V3_DEFENSE_N_MAX = 500
V3_DEFENSE_R2_THRESHOLD = -0.5

# ── V4 Experiment Parameters ──
V4_DELTA_SWEEP = [0.05, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.40, 0.50]
V4_ATTACK_TRIALS = 20
V4_CONTROL_TRIALS_PER_INTENT = 5
V4_TARGET_MULTIPLIER = 3                  # Δ = 3β
V4_ATTACK_INTENT = "Triple the data rate for the internet slice safely in small increments"
V4_CONTROL_INTENTS = [
    "Report current data rate for the internet slice",           # read-only
    "Increase the data rate for the internet slice by 10%",      # single-step
]
V4_ABLATION_BETA_VALUES = [0.05, 0.10, 0.15, 0.20, 0.30]
V4_ABLATION_DELTA_MULTIPLIERS = [2, 3, 5]

# ── V7 Experiment Parameters ──
V7_AMBR_INCREASE_FRACTION = 0.30          # 30% increase
V7_PROPAGATION_WAIT_S = 10               # wait 2+ collector cycles
V7_DIVERGENCE_THRESHOLD = 0.10
V7_ABLATION_DELTA_C = [1, 5, 15, 30]     # collector period sweep
V7_ABLATION_QUERY_TIMES = [1, 3, 5, 10, 30]  # seconds after write

# ── Type P fields (policy-derived) ──
TYPE_P_FIELDS = [
    "policyData.ues.*.ambr",
    "policyData.ues.*.lastModified",
    "policyData.ues.*.sessionAmbr",
]

# ── Type T fields (telemetry-derived) ──
TYPE_T_FIELDS = [
    "upf_metrics.total_rx_bytes",
    "upf_metrics.total_tx_bytes",
    "upf_metrics.active_ue_count",
    "smf_metrics.session_count",
    "pcf_metrics.enforcement_events",
]
