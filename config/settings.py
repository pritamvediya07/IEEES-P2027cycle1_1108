# config/settings.py
# Central configuration for NWDAF-PALA project.
# All Open5GS NF addresses, MongoDB URIs, and project-wide constants live here.
# Edit ONLY this file when your network addresses change.

import os
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# MongoDB
# ─────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")

# Open5GS writes subscriber / session data here
OPEN5GS_DB       = "open5gs"
OPEN5GS_SESSIONS = "sessions"         # SMF PDU sessions
OPEN5GS_POLICY   = "policyData.ues"   # PCF per-UE policy store
OPEN5GS_AMDATA   = "amData"           # AMF access/mobility data

# NWDAF writes analytics data here
NWDAF_DB              = "nwdaf_analytics"
NWDAF_UPF_METRICS     = "upf_metrics"
NWDAF_SMF_METRICS     = "smf_metrics"
NWDAF_PCF_METRICS     = "pcf_metrics"
NWDAF_SCHEDULED_TASKS = "scheduled_tasks"

# ─────────────────────────────────────────────
# Open5GS SBI (Service Based Interface) addresses
# These match the defaults in /etc/open5gs/*.yaml
# ─────────────────────────────────────────────
NF_ADDRESSES = {
    "nrf": "http://127.0.0.10:7777",
    "amf": "http://127.0.0.5:7777",
    "smf": "http://127.0.0.4:7777",
    "upf": "http://127.0.0.7:2152",   # GTP-U port — SMF is the SBI contact
    "pcf": "http://127.0.0.9:7777",
    "udr": "http://127.0.0.20:7777",
    "udm": "http://127.0.0.12:7777",
    "ausf": "http://127.0.0.11:7777",
}

# Open5GS WebUI (subscriber management)
WEBUI_URL      = os.getenv("WEBUI_URL", "http://localhost:9999")
WEBUI_USER     = os.getenv("WEBUI_USER", "admin")
WEBUI_PASSWORD = os.getenv("WEBUI_PASSWORD", "1423")

# ─────────────────────────────────────────────
# Collector settings
# ─────────────────────────────────────────────
COLLECTOR_INTERVAL_SEC = 5   # how often to poll NFs and write to nwdaf DB
METRICS_RETENTION_DAYS = 7   # auto-delete metrics older than this

# ─────────────────────────────────────────────
# Slice / DNN defaults (match your Open5GS config)
# ─────────────────────────────────────────────
DEFAULT_SLICE_SST  = 1
DEFAULT_SLICE_SD   = "000000"
KNOWN_SLICES       = ["internet", "streaming", "default"]
DEFAULT_DNN        = "internet"

# ─────────────────────────────────────────────
# 3GPP AMBR limits (bps) — used by FeasibilityChecker
# ─────────────────────────────────────────────
MAX_DL_AMBR_BPS    = 1_000_000_000   # 1 Gbps (matches WebUI default)
MAX_UL_AMBR_BPS    = 1_000_000_000
MIN_AMBR_BPS       = 1_000_000        # 1 Mbps floor

# Maximum UE capacity for load calculations.
# The testbed runs 10 UEs; setting capacity to 20 gives 50% load at full
# testbed occupancy — realistic headroom and well under the 90% hard-block.
MAX_UE_CAPACITY    = 20

# ─────────────────────────────────────────────
# Ollama / LLM
# ─────────────────────────────────────────────
OLLAMA_BASE_URL  = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL     = os.getenv("OLLAMA_MODEL", "llama3.1")
LLM_TEMPERATURE  = 0.1   # near-deterministic — matches paper
LLM_MAX_TOKENS   = 2048
MAX_AGENT_STEPS  = 50    # safety ceiling on agentic loop iterations

# ─────────────────────────────────────────────
# MCP server
# ─────────────────────────────────────────────
MCP_SERVER_NAME = "nwdaf-intent-tools"
