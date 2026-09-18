# Installation Guide — PALA Artifact

**Paper:** Architecture-Induced Reward Hacking in NWDAF-Integrated LLM Control Loops  
**IEEE S&P 2027, Cycle 1**  
**Repository:** <https://github.com/pritamvediya07/IEEES-P2027cycle1_1108>

---

## Overview

> **Fastest path:** `./run_artifact.sh` installs the dependencies and runs every offline
> check in one command — see the README's *Quick Start*. This guide covers each step
> individually.

There are three evaluation tracks. Track C (srsRAN radio-side validation) is documented in [`srsran/README.md`](srsran/README.md) and summarised below.

| Track | Time | Hardware | Purpose |
|-------|------|---------|---------|
| **A: Offline** | < 1 min (+ install) | Any laptop | Verify the main paper claims (54 checks) from stored results |
| **B: Full Testbed** | ≈ 38 h (all UERANSIM experiments); one-day subset ≈ 16 h | GPU server with local Ollama | Re-run experiments from scratch |
| **C: srsRAN** | C1 ~1 min · C2 ≈ 5–6 h | C1 any laptop · C2 root + srsRAN build | Verify and re-run the radio-side validation and supplementary experiments |

Start with Track A. Track B is only needed if you want to generate new trial data; for a one-day live evaluation (≈ 21–22 h including the srsRAN track), use the subset in the README's *Artifact Evaluation Plan (fits in one day)*. The authors provide SSH access to the reference system for the live tracks; see the README's *Evaluator access (Reproduced badge)*.

---

## Track A: Offline Verification (Recommended)

### 1. System Requirements

- Ubuntu 20.04+ / macOS 12+ / Windows with WSL2
- Python 3.10–3.12 (3.12 recommended; the pinned numpy has no 3.13 wheel)
- ~500 MB disk space for dependencies + ~200 MB for stored results

### 2. Clone the Repository

```bash
git clone https://github.com/pritamvediya07/IEEES-P2027cycle1_1108.git pala-artifact
cd pala-artifact
```

### 3. Set Up Python Environment

```bash
python3 -m venv .venv               # Python 3.10–3.12 (tested with 3.12)
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate.bat       # Windows

pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Verify Stored Results

```bash
python reproduce_results.py
```

This reads the stored trial logs from `final_experiments/`, recomputes the main-evaluation statistics (54 checks; it should end with `All 54 checks PASS`), regenerates Figures 3–4 with `final_experiments/RQ1_realization/figures/gen_fig1_hq.py` and `final_experiments/RQ2_mechanism/figures/gen_fig2_hq.py` (byte-identical to the committed PDFs), and writes the supplementary figures and tables with `final_paper_results/generate_all_figures.py`. Add `--tables` to skip figure generation.

### 5. Explore the Analysis Notebook

```bash
pip install jupyter
jupyter notebook analysis/pala_analysis.ipynb
```

### 6. Run Unit Tests

```bash
python -m pytest tests/test_tools.py -v
# Expected: 26 passed in ~2.5 s (the tests use an in-memory MongoDB via mongomock;
# no database is contacted)
```

---

## Track B: Full Testbed Setup

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 8 cores | 16+ cores |
| RAM | 32 GB | 64 GB |
| GPU | 48 GB VRAM (Qwen 2.5:72b) | 80 GB+ VRAM (to host Mistral-Large, 73 GB) |
| Storage | 100 GB NVMe | 500 GB NVMe |
| OS | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| Kernel | 5.15+ | 5.15+ |
| Network | 1 GbE | 10 GbE |

> **GPU Note:** Every Track B experiment runs through a local Ollama, so a GPU is required
> (48 GB VRAM for Qwen 2.5:72b; 80 GB+ to also host Mistral-Large, 73 GB — Ollama loads one
> model at a time). There is no GPU-free route. Cloud APIs are supported only by
> `wave_experiments/exp1_vuln_multimodel.py` (Table 2 cross-family rows); see step 5 and
> [MODEL_SETUP.md](MODEL_SETUP.md).

The supported route is the Docker testbed started by `./quickstart.sh` (steps 1–4 below).

### 1. System Dependencies

```bash
# Docker Engine + Compose v2
curl -fsSL https://get.docker.com | sh
docker compose version            # must show v2.x
sudo usermod -aG docker $USER && newgrp docker

# Ground-truth probe (tc + iperf3)
sudo apt-get install -y iperf3 iproute2

# Python 3.10–3.12 (Ubuntu 22.04 ships 3.10; 3.12 recommended)
python3 --version
```

MongoDB, Open5GS and UERANSIM run inside the Docker testbed; they are not installed on the
host.

### 2. Install Ollama (Local LLM)

```bash
curl -fsSL https://ollama.com/install.sh | sh

# Pull required model families
ollama pull qwen2.5:72b          # Headline model (47 GB)
ollama pull llama3.1:70b         # Cross-family rows, Tables 2 and 3 (~42 GB)
ollama pull mistral-large:latest # Cross-family rows, Tables 2 and 3 (73 GB)
```

Verify Ollama is running:
```bash
curl http://localhost:11434/api/tags
```

### 3. Start the Docker Testbed

```bash
./quickstart.sh                  # interactive: .env, venv, host setup, build, start, tc
# or, once .env and .venv exist:
./quickstart.sh --testbed-only   # same as ./run_experiments.sh --phase testbed
./quickstart.sh --status         # service status
./quickstart.sh --stop           # stop the testbed
```

`quickstart.sh` checks Docker, Compose, Python and sudo, writes `.env` from `.env.example`,
creates `.venv`, runs the one-time host setup (`docker/testbed/scripts/setup-host.sh`),
builds the images (first run ~15 min; UERANSIM v3.2.7 is compiled from upstream source
inside `Dockerfile.ueransim`), starts the 16 services, and applies the loopback shaper
(`docker/testbed/scripts/tc-setup.sh`). You do not need to configure `tc` by hand: the
ground-truth probe (`wave_experiments/shared/probe.py`) also installs its own HTB/netem
shaper at the start of every trial.

Check the stack:

```bash
docker compose -f docker/testbed/docker-compose.testbed.yml ps
docker logs testbed_amf 2>&1 | tail -20
docker logs testbed_ueransim 2>&1 | tail -20
```

Services: MongoDB (`mongo-testbed`, container `mongo_testbed`, host port 27020), the one-shot
subscriber init (`init-db`), Open5GS NRF, SCP, UDR, UDM, AUSF, PCF, NSSF, BSF, AMF, SMF, UPF
and WebUI (containers `testbed_<nf>`, WebUI on host port 10999), UERANSIM (`ueransim`,
container `testbed_ueransim`, which runs the gNB and one UE), and the NWDAF collector
(`nwdaf`, container `testbed_nwdaf`, 5 s interval).

### 4. Register Subscriber Profiles

The testbed requires 10 test subscriber IMSIs on the `internet` slice. They are written by
the one-shot `init-db` service (`docker/testbed/scripts/init_subscribers.js`, IMSIs
`999700000000001`–`999700000000010`); `./quickstart.sh` runs it automatically. To run it by
hand (idempotent):

```bash
# from docker/testbed/
docker compose -f docker-compose.testbed.yml run --rm init-db
```

`wave_experiments/shared/db_clean.py` does not add subscribers; it resets AMBR and flushes
analytics between runs (`--reset-ambr`, `--flush-analytics`, `--all`).

> **Native (non-Docker) testbed — not supported for artifact evaluation.** The repository's
> `UERANSIM/` directory holds only build files, configs and the license, not the UERANSIM
> source. A native setup needs UERANSIM cloned from upstream at v3.2.7 and built, a native
> Open5GS 2.7.6 with MongoDB, and `MONGO_URI=mongodb://localhost:27017` in `.env`. The
> evaluation instructions assume the Docker testbed above.

### 5. Configure the LLM Backend (`.env`)

`quickstart.sh` creates `.env`; for the paper setup keep the Ollama defaults:

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:72b
MONGO_URI=mongodb://localhost:27020   # Docker testbed; the tools and the harness both read it
```

Cloud backends are optional and apply only to `exp1_vuln_multimodel.py`: install the clients
(`pip install -r requirements-api.txt`) and set `OPENAI_COMPAT_KEY` /
`OPENAI_COMPAT_BASE_URL` (a Groq key also goes in `OPENAI_COMPAT_KEY`). Groq has retired
`llama-3.1-70b-versatile`. See [MODEL_SETUP.md](MODEL_SETUP.md).

### 6. Run Preflight Checks

```bash
./run_experiments.sh --phase preflight
```

This runs `wave_experiments/shared/smoke_test.py`: S1 Ollama reachable and `OLLAMA_MODEL`
present, S2 MongoDB reachable with `nwdaf_analytics.smf_metrics`, S3 the KPI tool returns
samples, S4 an AMBR write reads back through the collector, S5 the agent completes one step
on a simple intent. Each check prints `[PASS] …` or `[FAIL] …`, followed by
`[Smoke] ALL PASSED` or `[Smoke] SOME CHECKS FAILED`.

### 7. Run the Experiments

```bash
# Full suite (all UERANSIM experiments, ≈ 38 h measured)
./run_experiments.sh

# Or individual RQ phases (measured active times, reference system):
./run_experiments.sh --phase rq1       # exp1 3.1 h + exp1_multimodel 3.1 h ≈ 6.2 h
./run_experiments.sh --phase rq2       # exp2 2.1 h, exp9 0.9 h, exp14 + exp11 minutes ≈ 3 h
./run_experiments.sh --phase rq3       # exp3 0.7 h + exp3_multimodel 2.4 h ≈ 3.1 h
./run_experiments.sh --phase rq4-core  # exp5 ablation (Table 4) 3.9 h
./run_experiments.sh --phase rq4       # rq4-core + exp6 phases 2–3, exp7 7.7 h, exp15 ≈ 17 h
./run_experiments.sh --phase rq5       # exp8 4.6 h, exp10 minutes, exp13 3.1 h ≈ 7.8 h
./run_experiments.sh --phase calibrate # exp6 phase 1: k†* recalibration (optional)
```

All UERANSIM experiments take ≈ 38 h (measured from the stored trial timestamps). This
exceeds a one-day evaluation budget; the README's *Artifact Evaluation Plan (fits in one
day)* lists a ≈ 21–22 h subset (rq1, rq2, rq3, rq4-core and the srsRAN live track).
Add `--dry-run` to print what a phase would do, and `--resume` to continue an interrupted
phase.

Each phase publishes its results automatically: it first moves the stored results of its
experiments to `artifact_logs/stored_<timestamp>/` (the scripts resume from checkpoints and
would otherwise re-read the stored trials), keeps the stored k†\* unless you run
`--phase calibrate`, then replaces `final_experiments/<exp>` with the fresh results (the
stored copy stays in `artifact_logs/stored_<timestamp>/final_experiments/`) and writes a
`FRESH_RUN` marker. No manual copying is needed.

### 8. Compare with the Paper and Generate Figures

```bash
python reproduce_results.py --fresh    # claim-level comparison of the fresh results
python reproduce_results.py            # stored mode (printed precision) + figures
# or
python final_paper_results/generate_all_figures.py
```

`--fresh` judges each proportion by a two-sided Fisher exact test against the paper's count
(pass if p > 0.05), requires p < 10⁻⁴ for the oversight tests, lists which experiments carry
a `FRESH_RUN` marker, and labels the checks that still come from stored results.

---

## Troubleshooting

### Docker testbed won't start

```bash
# Check for port conflicts on the host ports the testbed maps
sudo lsof -i :27020  # MongoDB (mongo_testbed)
sudo lsof -i :38413  # AMF N2 (SCTP, mapped from 38412)
sudo lsof -i :10999  # Open5GS WebUI

# Re-run the one-time host setup (GTP module, IP forwarding)
sudo bash docker/testbed/scripts/setup-host.sh
```

### UERANSIM UEs not registering

```bash
docker logs testbed_ueransim 2>&1 | tail -30   # gNB and UE output
docker logs testbed_amf 2>&1 | tail -30
# Restart the UPF and the UERANSIM container (gNB + UE)
docker compose -f docker/testbed/docker-compose.testbed.yml restart upf ueransim
# Check SCTP is supported
cat /proc/net/sctp/snmp | head -5
```

### Ollama model OOM

```bash
# Check available VRAM
nvidia-smi
# Use smaller model if needed (not the paper's model; results will differ)
ollama pull llama3.1:8b   # 8B model, runs on 16GB GPU
# Then set OLLAMA_MODEL=llama3.1:8b in .env (read by wave_experiments/config.py)
```

### MongoDB not accepting connections

```bash
docker compose -f docker/testbed/docker-compose.testbed.yml ps mongo-testbed   # expect "healthy"
docker start mongo_testbed
# .env must point at the Docker testbed: MONGO_URI=mongodb://localhost:27020
```

### `tc` enforcement not capping throughput

```bash
# Verify HTB class is active
sudo tc -s class show dev lo
# Reload if needed
sudo tc qdisc del dev lo root
sudo bash docker/testbed/scripts/tc-setup.sh
```

### `reproduce_results.py` exits with `FileNotFoundError`

```bash
# Ensure you're in the repo root
cd /path/to/pala-artifact
python reproduce_results.py

# Check stored results exist
ls final_experiments/exp1/summary.json
ls final_experiments/exp6/kstar.json
```

---

## Track C: srsRAN Testbed

Track C1 needs nothing beyond Track A:

```bash
python analysis/verify_paper.py
python analysis/verify_prompt_provenance.py
```

Track C2 (live srsRAN) additionally needs:

```bash
sudo apt install iperf3 iproute2 gnuradio # GNU Radio is REQUIRED (ZeroMQ broker for E0.x and E1)
export SRSRAN_BUILD=/path/to/srsran_build # holds srsRAN_Project/ and srsRAN_4G/ builds
./run_artifact.sh env                     # checks the builds, GNU Radio (/usr/bin/python3) and the key
```

`SRSRAN_BUILD` defaults to `~/srsran_build` of the invoking user, also under `sudo`.
`requirements-srsran.txt` (pyzmq; anthropic for the E6 frontier tier) is installed
automatically by `./run_artifact.sh live-srsran` (and `all`); for manual runs install it with
`pip install -r requirements-srsran.txt`.

Build srsRAN Project `release_24_10_1` and srsRAN 4G `srsue` 25.10.0 with ZeroMQ support
under `$SRSRAN_BUILD`, then either run the live track (≈ 5–6 h measured) with

```bash
sudo --preserve-env=SRSRAN_BUILD,ANTHROPIC_API_KEY ./run_artifact.sh live-srsran
```

or follow [`srsran/README.md`](srsran/README.md) for host preparation and the
per-experiment commands. `live-srsran` runs the radio measurements (E0.1, E0.3/E0.4, E1),
E4, E5, E3, E6 (local tiers 7-8B and 12-15B; the frontier tier only with a paid
`ANTHROPIC_API_KEY`), E8 and E10 — E3 ≈ 2.0 h, E6 local tiers ≈ 1.2 h (+ ≈ 0.6 h frontier),
radio < 0.5 h, the rest minutes — after moving the stored LLM checkpoints
(`srsran/results/llm_trials/{E3,E5,E6}`) aside, and finishes with
`analysis/verify_paper.py --fresh`, which fails if the fresh results do not support the
paper's claims. It does not run E9, E2, E2.3, E0.5 or E12/E12b (verified offline by C1).

For manual runs of E3, E4, E5 or E6, start the collector daemon first
(`python -m collector.collector &`); without it the contamination channel is closed.
`bash srsran/chain.sh start|pause|resume|status|stop` runs the LLM chain
(`srsran/llm_chain.sh`: E5, E3, E6 frontier if the key is set, E6 local tiers) and starts the
collector itself.

---

## Environment Summary

Read from the system the experiments ran on; full hardware in the README's
[Reference System](README.md#reference-system) section.

| Software | Version | Notes |
|---------|-------------|-------|
| Ubuntu | 22.04.5 LTS | Linux 6.8.0 |
| Python | 3.12.12 | 3.10–3.12 required |
| MongoDB | 7.0.31 | Community Edition |
| Docker / Compose | 29.3.0 / v5.1.0 | |
| Ollama server | 0.33.3 | local LLM runtime |
| Qwen 2.5:72b | Q4_K_M | 47 GB on disk |
| Open5GS | 2.7.6 | Release-18 compatible |
| UERANSIM | v3.2.7 | built from source |
| iperf3 | 3.9 | ground-truth τ measurement |
| NVIDIA driver / CUDA | 580.126.09 / 13.0 | 1× RTX PRO 6000 Blackwell, 96 GB |
| srsRAN Project gNB | release_24_10_1 (ef4b074) | Track C, ZeroMQ RF |
| srsRAN 4G srsUE | 25.10.0 (6bcbd9e) | Track C, ZeroMQ RF |
| pyzmq | 27.2.0 | Track C |
| anthropic | 1.0.0 | Track C, E6 frontier tier only |
