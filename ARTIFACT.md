# PALA Artifact — Evaluation Guide

**Paper:** *Architecture-Induced Reward Hacking in NWDAF-Integrated LLM Control Loops*
**Venue:** IEEE S&P 2027, Cycle 1

**Fastest path:**

```bash
./run_artifact.sh
```

One command installs the dependencies and runs every offline check — unit tests, the main
evaluation (Track A), and the srsRAN radio-side validation (Track C1) — ending in `ALL 5 STAGES PASSED` with exit
status 0. Logs go to `artifact_logs/`. `./run_artifact.sh --help` lists the live modes.

This guide covers badges, setup, and expected output. For claim-by-claim file mappings
see [CLAIMS.md](CLAIMS.md), including its list of
[known differences between the paper and the stored data](CLAIMS.md#known-differences-between-the-paper-and-the-stored-data);
for the full walkthrough and the one-day evaluation plan see [README.md](README.md#artifact-evaluation-plan-fits-in-one-day).

---

## Claimed Badges

| Badge | Justification |
|---|---|
| **Artifacts Available** | Archived on Zenodo with a DOI after evaluation, before the camera-ready deadline (14 Oct 2026); the paper's anonymous.4open.science link is replaced by that DOI in the camera-ready. The GitHub repository (https://github.com/pritamvediya07/IEEES-P2027cycle1_1108) is the evaluation copy. Contents: complete PALA source, the Docker UERANSIM testbed, the srsRAN testbed configuration and experiment scripts, 1,418 stored UERANSIM result files (JSON/JSONL under `final_experiments/`), all srsRAN results with per-trial LLM traces, and the figure, table, and verification scripts |
| **Artifacts Functional** | `./run_artifact.sh` runs every offline check from a fresh clone; 26 unit tests pass on an in-memory database (no MongoDB, Open5GS or Ollama); the verifiers run on any machine with Python 3.10–3.12 |
| **Results Reproduced** | Tracks B and C2 re-run the experiments; `reproduce_results.py --fresh` and `analysis/verify_paper.py --fresh` judge the fresh results against the paper's claims (see the README's [one-day plan](README.md#artifact-evaluation-plan-fits-in-one-day) and [Evaluator access](#evaluator-access) below). Offline, `reproduce_results.py` recomputes the main-evaluation statistics from the stored trial logs (54 checks) and `analysis/verify_paper.py` recomputes all 79 registered srsRAN numbers from raw results and checks the 41 printed in the paper |

### Evaluator access

For the Reproduced badge the authors provide SSH (public-key) access to the reference
workstation on which the paper's experiments ran (2× Intel Xeon Gold 6538Y+, 503 GiB RAM,
1× NVIDIA RTX PRO 6000 Blackwell 96 GB, Ubuntu 22.04.5, Docker, Ollama with all paper
models pulled, native Open5GS 2.7.6, srsRAN built at
`/home/user/Desktop/pritam/srsran_build`).

- Send an SSH public key through HotCRP; the connection details are returned there.
- Work in a separate checkout of the repository and set
  `export SRSRAN_BUILD=/home/user/Desktop/pritam/srsran_build`.
- `./run_artifact.sh env` reports both live tracks ready on this machine.
- Only one evaluator should run live experiments at a time: the experiments share the GPU
  and the testbed database. Coordinate the schedule through HotCRP.

---

## Overview

The artifact supports the paper's claim that **architecture-induced reward hacking** arises
in NWDAF-integrated LLM control loops as a property of the deployment architecture, with no
adversarial input, compromised tools, or model retraining.

| Component | Location |
|---|---|
| PALA system (agent, tools, collector, MCP server) | `agent/`, `tools/`, `collector/`, `mcp_server/`, `config/` |
| Main testbed: Open5GS + UERANSIM (Docker) | `docker/testbed/` |
| Main experiment harness (Exp 1–15) | `wave_experiments/` |
| Main stored results | `final_experiments/` |
| Radio-side validation: Open5GS + srsRAN testbed, experiments, results | `srsran/` |
| Number registry and verifiers | `analysis/` |
| Unit tests | `tests/` |

---

## Repository Layout

```
.
├── run_artifact.sh          ← ONE COMMAND: all offline checks, or the live tracks
├── LICENSE                  ← MIT; third-party licenses listed inside
├── README.md                ← full walkthrough, Tracks A–C, reference system
├── ARTIFACT.md              ← this file
├── CLAIMS.md                ← paper claims → file mappings; known differences
├── STATUS.md                ← badge justification
├── INSTALL.md               ← installation reference
├── reproduce_results.py     ← Track A: verify stored UERANSIM results, regenerate figures
├── run_experiments.sh       ← Track B: live UERANSIM experiments by phase
├── quickstart.sh            ← Track B: guided testbed setup
├── requirements.txt         ← Tracks A and B
├── requirements-api.txt     ← optional cloud backends (Table 2 cross-family rows only)
├── requirements-srsran.txt  ← Track C2 (installed automatically by the live modes)
├── NOTICE                   ← third-party configurations (Open5GS, UERANSIM, srsRAN): AGPL-3.0
│
├── agent/  tools/  collector/  mcp_server/  config/   ← PALA system
├── tests/                   ← 26-test unit suite (in-memory database, no live network)
├── docker/testbed/          ← Open5GS + UERANSIM containers
├── wave_experiments/        ← Exp 1–15 and shared utilities
├── final_experiments/       ← stored results; RQ*_realization … RQ5_deployability hold paper figures/tables
├── final_paper_results/     ← supplementary figures, tables, and raw JSON
│
├── srsran/                  ← srsRAN radio-side validation — Track C
│   ├── README.md            ← build, run, and experiment index
│   ├── RESULTS.md           ← full results and claim boundaries
│   ├── SPEC.md              ← experiment specification
│   ├── configs/             ← gNB/UE configs (ZeroMQ RF front-end)
│   └── results/             ← results, LLM traces, INVALID_* record
└── analysis/                ← registry and verifiers
```

---

## Track A — Offline verification of the main evaluation (under a minute after setup)

No Docker, GPU, or network needed. Python 3.10–3.12 (numpy 1.26.4 has no 3.13 wheel;
tested with 3.12).

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python reproduce_results.py
```

Expected: `All 54 checks PASS`, then generation of the supplementary figures and tables in
`final_paper_results/` and of Figures 3–4 (`gen_fig1_hq.py`, `gen_fig2_hq.py`; the
regenerated PDFs are byte-identical to the committed ones, so the working tree stays
clean). `--tables` skips the figure step. Every statistic, including the Fisher exact and
Wilcoxon tests (SciPy), is recomputed from the stored trial logs and must match the
printed value to its printed precision (±0.5 pp for percentages). Two kinds of `NOTE`
lines are informational, not checks: the number of stored τ samples on the probe's shaper
model (377/382), and the Table 3 AND-rule column, which the stored decisions do not
reproduce exactly (see [CLAIMS.md](CLAIMS.md#known-differences-between-the-paper-and-the-stored-data)).
The §6.3 UERANSIM target share (71.4%) is analytical: it is computed from the testbed's
shaper model and is not re-measured by a fresh run. Excerpt of the actual output
(`python reproduce_results.py --tables`):

```
  RQ1 — Realization of Closed Contamination Circuit (Table 2)
  Qwen full-loop rate (vulnerable)               got=66.7%     expected≈66.7%  PASS
  Qwen Strict Def.4 rate                         got=60.0%     expected≈60.0%  PASS
  Qwen mean Q-drop                               got=11.0%     expected≈11.0%  PASS
  Qwen defended: 0 full-loop closures            got=0  expected=0  PASS
  Qwen Fisher p (Full PALA vs vulnerable)        p=1.43e-08  expected<1e-6  PASS
  ...
  Mistral-large full-loop rate                   got=26.7%     expected≈26.7%  PASS
  Mistral-large Strict Def.4 rate                got=36.7%     expected≈36.7%  PASS
  Mistral-large: circuit closes in some session  full-loop rate 26.7% > 0  PASS
  ...
  Staged-change: full-loop rate (Fig. 4a)        got=30.0%     expected≈30.0%  PASS
  Staged > direct >= null decomposition          65% > 15% >= 0%, Fisher p=0.003  PASS
  Table 10C: Type-P escape vs N                  [1.0, 0.8, 0.4, 0.2667, 0.16] vs printed [1.0, 0.8, 0.4, 0.267, 0.16]  PASS
  Table 11A: lowest Def. 4 rate across profiles  got=53.6%     expected≈53.6%  PASS
  Table 11A: highest Def. 4 rate across profiles  got=75.0%     expected≈75.0%  PASS
  tau samples on the shaper model (exp1)         377/382  NOTE
  [analytical: computed from the testbed's shaper model, not re-measured by a fresh run]
  §6.3 share of dQ at B* (analytical, >= 71%)    got=71.4%     expected≈71.4%  PASS
  ...
  Qwen: Wilcoxon p (per-call < cumulative)       p=5.96e-06  printed=5.96e-06  PASS
  Qwen: AND-rule approval                        got=44.3%   printed=44.0%  NOTE (see CLAIMS.md, known differences)
  ...
  AS2 ∧ AS4 (Full PALA): full-loop rate          got=0.0%      expected≈0.0%  PASS
  AS5 only: full-loop rate (Table 8 Panel B)     got=65.0%     expected≈65.0%  PASS
  k†* = 1 (conservative calibration)             got=1  expected=1  PASS
  ...
  Adaptive prompts — Full PALA: full-loop rate   got=0.0%      expected≈0.0%  PASS
  BoN-PALA calibrated n*                         got=4  expected=4  PASS
  BoN-PALA: full-loop rate                       got=70.0%     expected≈70.0%  PASS
  ...
  KPI latency: undefended -> IsolatedCollector   3,942 ms -> 0.01 ms  expected ~3,942 -> <0.1  PASS
  Recovery completion — Full PALA (of 20)        got=17  expected=17  PASS
  Recovery false rejections — Full PALA (of 20)  got=1  expected=1  PASS

  ✓ All 54 checks PASS
```

**Fresh results (`--fresh`).** After Track B, `python reproduce_results.py --fresh` judges
the freshly generated results by the paper's claims rather than the stored values. A
proportion passes if a two-sided Fisher exact test of the fresh count against the paper's
count gives p > 0.05 (a fixed ±10 pp window on n = 20–30 would reject a correct system most
of the time); the oversight tests must give p < 10⁻⁴; ordering claims are kept; the
Table 10C escape rate must decrease from 100%. The script lists which experiments carry a
`FRESH_RUN` marker (written by `run_experiments.sh`) and labels the checks whose
experiments the one-day plan does not rerun (Exp 6, 7, 15 and RQ5) with
`[stored results — … is not rerun by the one-day plan]`.

---

## Track C1 — Offline verification of the srsRAN radio-side validation (~1 minute)

```bash
python analysis/verify_paper.py
python analysis/verify_prompt_provenance.py
```

Expected final lines:

```
PASSED — every paper number is reproducible from the raw traces and matches the paper
PASSED — every experiment uses the paper's prompts, corpora and model
```

`verify_paper.py` recomputes all 79 registered numbers in `analysis/paper_numbers.json`
from the raw results and checks the 41 printed in the paper at their printed precision
(`PRINTED` in `verify_paper.py`). It also lists numbers flagged as not robust to analysis
choices; the paper quotes those only as bounds.

After Track C2, `python analysis/verify_paper.py --fresh` applies claim-level criteria to
the fresh srsRAN results (20 claims): the deterministic E4, E5 and E8 results must match
exactly; LLM session counts (E3, E6) are compared with the paper's counts by a two-sided
Fisher exact test (p > 0.05); E1 cell capacity 22.8 Mbps ± 10%, victim λ inflation > 1.5×
(paper 1.95×), victim τ flat (5.43 Mbps ± 10%); E0.4 target share > 86% (paper > 91%); E10
overhead < 1.3 ms.

---

## Track B — Live UERANSIM testbed (~2 hours setup, ≈ 38 hours of paper experiments)

```bash
cp .env.example .env        # OLLAMA_BASE_URL, OLLAMA_MODEL, MONGO_URI (see the file)
./quickstart.sh             # prerequisites, host setup, images, health checks, venv

source .venv/bin/activate
./run_experiments.sh --phase calibrate   # Exp 6 k†* calibration — run first
./run_experiments.sh --phase rq1         # Exp 1 + multimodel
./run_experiments.sh --phase rq2         # mechanism
./run_experiments.sh --phase rq3         # oversight rules
./run_experiments.sh --phase rq4         # defenses (--phase rq4-core: the Table 4 ablation only)
./run_experiments.sh --phase rq5         # deployability
./run_experiments.sh --phase figures     # figures and tables from fresh results
# or everything, in dependency order:
./run_experiments.sh --phase all
```

Measured active times with one GPU: exp1 3.1 h, exp1_multimodel 3.1 h, exp2 2.1 h, exp3
0.7 h, exp3_multimodel 2.4 h, exp5 3.9 h, exp6 5.5 h, exp7 7.7 h, exp8 4.6 h, exp9 0.9 h,
exp13 3.1 h, exp10/11/14 < 0.2 h each; exp15 is part of `--phase rq4` — ≈ 38 h in total.
By phase: rq1 6.2 h, rq2 ≈ 3 h, rq3 3.1 h, rq4-core 3.9 h, rq4 ≈ 17 h (includes rq4-core),
rq5 ≈ 7.8 h. For a one-day evaluation, use the subset in the README's
[Artifact Evaluation Plan](README.md#artifact-evaluation-plan-fits-in-one-day):
rq1 + rq2 + rq3 + rq4-core (≈ 16 h) plus the srsRAN live track (≈ 5–6 h), ≈ 21–22 h in
total.

Each experiment phase first moves the stored results of its experiments to
`artifact_logs/stored_<timestamp>/` (the scripts resume from checkpoints and would otherwise
re-read the stored trials), keeps the stored k†\* unless `--phase calibrate` runs, then
**replaces** `final_experiments/<exp>/` with the fresh results (the stored copy stays in
`artifact_logs/stored_<timestamp>/final_experiments/`), keeps the `EXP*_RESULTS.md`
write-ups, and writes a `FRESH_RUN` marker. `--phase preflight` runs
`wave_experiments/shared/smoke_test.py`; `--phase testbed` runs
`./quickstart.sh --testbed-only`; `--dry-run` prints the plan and `--resume` continues an
interrupted fresh run. `./run_artifact.sh live-ueransim` brings up the testbed, runs
`--phase all`, and re-checks with `reproduce_results.py --fresh`.

**LLM backends** (configured in `.env`):

| Option | Used by | GPU | API key |
|---|---|---|---|
| Ollama (paper): qwen2.5:72b; mistral-large:latest and llama3.1:70b for the cross-family rows | every UERANSIM experiment | ~48 GB VRAM for Qwen; 80 GB for Mistral-Large | none |
| OpenAI-compatible (`OPENAI_COMPAT_*`; Together AI, Groq, Mistral AI) or Gemini (`GEMINI_*`) | `wave_experiments/exp1_vuln_multimodel.py` only (Table 2 cross-family rows); needs `pip install -r requirements-api.txt` | none | yes |

Groq has retired `llama-3.1-70b-versatile`.

**Docker services** (Compose service names; the containers are `mongo_testbed` and
`testbed_<service>`, e.g. `testbed_amf`):

| Service | Role |
|---|---|
| `mongo-testbed` | MongoDB 7 (port 27020); `init-db` provisions 10 synthetic subscribers |
| `nrf`, `scp` | service discovery |
| `amf`, `smf`, `upf` | 5G control and user plane |
| `pcf`, `udm`, `udr`, `ausf`, `nssf`, `bsf` | policy, data, authentication |
| `webui` | Open5GS WebUI (port 10999) |
| `ueransim` | UERANSIM v3.2.7 (built from upstream) — gNB plus one UE |
| `nwdaf` | NWDAF collector (5 s interval → analytics DB) |

**Hardware:**

| Component | Minimum | System used for the paper |
|---|---|---|
| CPU | 8 cores | 2× Intel Xeon Gold 6538Y+ (64 cores) |
| RAM | 32 GB | 503 GiB |
| GPU (local LLM only) | 48 GB VRAM for Qwen 2.5:72B; 80 GB for Mistral-Large | 1× NVIDIA RTX PRO 6000 Blackwell, 96 GB |
| Storage | 150 GB free | 3.6 TB NVMe |
| OS | Ubuntu 22.04 | Ubuntu 22.04.5 LTS |

Full versions: the README's [Reference System](README.md#reference-system).

Track B needs a local GPU: every UERANSIM experiment except the Table 2 cross-family rows
(`exp1_vuln_multimodel.py`) runs only against Ollama, so there is no GPU-free route.
UERANSIM source is not in the repository (`UERANSIM/` holds build files, configurations and
the license); the Docker image builds v3.2.7 from upstream.
`./run_artifact.sh env` reports whether this machine is ready for each live track. See [INSTALL.md](INSTALL.md) and [MODEL_SETUP.md](MODEL_SETUP.md).

---

## Track C2 — Live srsRAN testbed

Requires an srsRAN build with ZeroMQ support, GNU Radio (`apt install gnuradio`, for the
ZeroMQ broker used by E0.x and E1), and root access. `requirements-srsran.txt` is installed
automatically by the live modes.

```bash
sudo --preserve-env=SRSRAN_BUILD,ANTHROPIC_API_KEY ./run_artifact.sh live-srsran
```

This moves the stored LLM checkpoints (`srsran/results/llm_trials/{E3,E5,E6}`) aside so
every trial re-runs, then runs the radio measurements (E0.1, E0.3/E0.4, E1), the E4
scripted controller, E5, E3, E6 with the paper's tiers (frontier tier only if
`ANTHROPIC_API_KEY` is set, then `e6_capability_sweep.py --tiers 7-8B,12-15B`), E8 and E10,
and finally gates on `analysis/verify_paper.py --fresh` (this stage can fail). E9, E2,
E2.3, E0.5 and E12/E12b are not re-run; their stored results are verified offline.
Measured time ≈ 5–6 h. `SRSRAN_BUILD` defaults to the invoking user's `~/srsran_build`,
also under `sudo`. Build steps, host preparation, per-experiment commands, and the
experiment index are in **[srsran/README.md](srsran/README.md)**.

The paper also reports a single-configuration **USRP-2953R hardware-RF confirmation**
(Appendix E). Its traces were not retained, and it is not part of this artifact; the
reproducible radio-side validation is the ZeroMQ configuration.

---

## Key Stored Result Files

| File | Size | Contents |
|---|---|---|
| `final_experiments/exp1/exp1_trials.jsonl` | 224 K | 60 sessions (30 vulnerable + 30 defended), Qwen |
| `final_experiments/exp1_multimodel/exp1_multimodel_trials.jsonl` | 224 K | 60 sessions (30 Mistral-large + 30 Llama 3.1:70b, vulnerable); Qwen's 30 are in `exp1` |
| `final_experiments/exp5/exp5_trials.jsonl` | 256 K | necessity/sufficiency ablation |
| `final_experiments/exp7/` | 1.7 M | adaptive-prompt stress test |
| `final_experiments/exp6/kstar.json` | 1 K | HedgeTune calibration (k†\*=1, CV=0.401) |
| `srsran/results/` | 3.4 M | every srsRAN result file |
| `srsran/results/llm_trials/` | 1.2 M | per-trial traces for E3, E5, E6, E7, E9 |
| `analysis/paper_numbers.json` | — | every srsRAN paper number, with source file and rule |

Each UERANSIM per-session record contains `q_trace` (Φ and Q at each policy step),
`policy_calls`, `kpi_calls`, the stage booleans `decomposed`, `contaminated`,
`success_claimed`, `escalated`, `full_loop`, `def4_satisfied`, plus
`h_budget_rejections` and `iso_filter_active`.

> **Older summary strings.** A few `summary.json` files carry free-text `headline` or
> `interpretation` fields written before the final analysis, and some are wrong (details in
> [CLAIMS.md](CLAIMS.md)). The numeric fields are authoritative and match the paper.

---

## Notes on Reproducibility

The main evaluation measures a live testbed with `tc` HTB traffic shaping. Exact numeric
reproduction depends on:

1. **Hardware, OS, and kernel** — shaping produces testbed-specific throughput, so the
   magnitude of the Q drop (~11% mean) will differ.
2. **Model weights and sampling** — temperature 0.1 is near-deterministic but not fully
   deterministic; proportions are stable, individual sessions may differ.
3. **Timing** — the collector interval (Δc = 5 s) and contamination latency depend on
   single-host timing.

**Should reproduce:** proportional outcomes consistent with the paper's counts (two-sided
Fisher exact test, p > 0.05, as applied by `--fresh`); the ordering Qwen > Mistral ≈
Llama; 0 circuit closures under Full PALA; 0 Type-P contamination under IsolatedCollector;
significance of all significant tests; k†\* = 1.

**May differ:** exact Q values, per-session step counts and elapsed times, and stage rates by
a few percentage points.

---

## Running Unit Tests

```bash
source .venv/bin/activate
python -m pytest tests/test_tools.py -q
```

Expected: `26 passed` in a few seconds. The tests run on an in-memory MongoDB (mongomock)
and contact no database; no Open5GS or Ollama is required.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `reproduce_results.py` raises `FileNotFoundError` | not run from the repository root | run it from the directory containing `reproduce_results.py` |
| `ModuleNotFoundError: matplotlib` | virtual environment not active | `source .venv/bin/activate` |
| Docker containers exit immediately | port conflict or missing GTP kernel module | see [INSTALL.md](INSTALL.md) |
| Ollama model not found | model not pulled | `ollama pull qwen2.5:72b` |
| `tc` enforcement has no effect | not root, or HTB module missing | `sudo modprobe sch_htb` |
| Experiment exits with `preflight FAIL` | MongoDB or Ollama unreachable | check with `mongosh --eval "db.runCommand({ping:1})"` |
| srsRAN script cannot find `gnb` / `srsue` | `SRSRAN_BUILD` not set or not passed through `sudo` | `export SRSRAN_BUILD=…` and use `sudo --preserve-env=SRSRAN_BUILD` |

---

## Contact

Reproducibility questions can be raised through HotCRP. Request SSH access to the
reference workstation through HotCRP as well (send an SSH public key; see
[Evaluator access](#evaluator-access)).

---

*All experiments ran on isolated testbeds with synthetic subscribers only; no live carrier
infrastructure, production traffic, or customer data was used.*
