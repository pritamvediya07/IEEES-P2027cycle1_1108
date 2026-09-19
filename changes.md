# Changes Log

---

## 2026-09-18 — Recomputed Track A, Fresh-Run Criteria, Live-Track Fixes, Documentation

**Context:** Artifact evaluation of the accepted paper. This entry makes every Track A
statistic a recomputation from the stored trial logs, adds claim-level criteria for
freshly generated results, fixes the live tracks so that they really re-run the
experiments, registers the srsRAN numbers the paper quotes, and corrects the
documentation against the final paper and the code.

### Verification

- **`reproduce_results.py`** — now **54 checks**, each recomputed from the trial logs at
  the printed precision (±0.5 pp); no check falls back to a paper value. Fisher exact and
  Wilcoxon tests are computed with SciPy (`scipy==1.13.1` added to `requirements.txt`); the
  Qwen Fisher p is computed from the counts (1.43e-8) instead of read from a stored 0.0.
  Coverage: Table 2 (all three families: full-loop, Strict Def. 4, "closes in some
  session"); Figure 4a (staged/direct/null decomposition, staged full-loop 30%, ordering
  staged > direct ≥ null with Fisher p < 0.05); Figure 4c / Table 10A; Table 10C (Type-P
  escape 100/80/40/26.7/16%); Table 11A (Strict Def. 4 range 53.6–75.0% across six
  Q-weight profiles); the §6.3 UERANSIM target share 71.4%, labelled **analytical**
  (computed from the probe's shaper model `wave_experiments/shared/probe.py`
  `update_tc_for_ambr`, on which 377/382 stored `exp1` τ samples lie; not re-measured by a
  fresh run); Table 3 for all three families (per-call, cumulative, one-sided Wilcoxon
  5.96e-6 / 8.63e-6 / 9.69e-6; AND-rule column printed as `NOTE`); Table 4 (full chain
  15/20; IsolatedCollector, HedgeTuned, Full PALA 0/20 operational closure; AS5 13/20 =
  Table 8 Panel B; BoN-PALA n\* = 4 and 14/20); k†\* = 1, CV 0.401, k† = 1 share 60.7%;
  Table 9 Panel A (46/50 vulnerable; 0/50 for IsolatedCollector, HedgeTuned, Full PALA);
  Table 6 (benign completion 84%, false rejections 6%, KPI latency 3,942 → 0.01 ms from
  `exp10/phaseB_summary.json`, recovery 17/20 undefended and Full PALA, Full PALA recovery
  false rejections 1/20).
- **`reproduce_results.py --fresh`** — judges freshly generated results by the paper's
  claims: a proportion passes if a two-sided Fisher exact test of the fresh count against
  the paper's count gives p > 0.05 (a ±10 pp window on n = 20–30 rejects a correct system
  most of the time); oversight tests must give p < 10⁻⁴; ordering claims are kept; Table
  10C must decrease from 100%. It lists the experiments that carry a `FRESH_RUN` marker and
  labels checks whose experiments the one-day plan does not rerun (Exp 6, 7, 15, RQ5).
  `run_artifact.sh live-ueransim` uses it for its re-check.
- **`analysis/paper_numbers.json`, `analysis/verify_paper.py`** — the registry grows
  from 54 to 79 numbers with the srsRAN numbers the paper quotes; `verify_paper.py` checks
  the 41 numbers printed in the paper at their printed precision against the registry and
  ends with "PASSED — every paper number is reproducible from the raw traces and matches
  the paper". New entries
  include the E1 capacity 22.8 Mbps and per-UE baseline 5.71 Mbps (from
  `srsran/results/E1_harm_mechanism.json`; E0.3's separate run measured 23.38 Mbps), the
  original derivation of the 71%/29% split from the E1 ceiling sweep (71.1% / 28.9%,
  `E1_share_of_victim_dQ_at_3x_pct`), the §6.3 srsRAN target share 94.2% and escalation
  share 5.8%, E6, E3 target-free, E8, and E10 n = 120.
- **`analysis/verify_paper.py --fresh`** — 20 claim-level criteria for fresh srsRAN results:
  deterministic E4/E5/E8 exact; E3/E6 session counts by Fisher exact test against the
  paper's counts; E1 capacity 22.8 Mbps ± 10%, victim λ inflation > 1.5× (paper 1.95×),
  victim τ flat (5.43 Mbps ± 10%); E0.4 target share > 86% (paper > 91%); E10 overhead
  < 1.3 ms. `run_artifact.sh live-srsran` gates its final stage on it.
- **Unit tests** (`tests/test_tools.py`) — previously connected to the MongoDB at
  `MONGO_URI` and cleared and re-seeded its collections. They now run on an in-memory
  MongoDB (`mongomock==4.3.0` added to `requirements.txt`) and contact no database.
- **Figures 3–4** — the figure step regenerates them (`gen_fig1_hq.py`, `gen_fig2_hq.py`;
  `statsmodels==0.14.2` added for Figure 4). PDFs are written with a fixed
  `SOURCE_DATE_EPOCH`, so regenerated figures are byte-identical to the committed ones and
  the working tree stays clean.

### Live tracks

- **`run_experiments.sh`** — the experiment phases called the scripts with options they do
  not accept (`--model`, `--n`, `--output`, `--k-star`, …), so every live phase failed at
  its first call; they now use each script's real options. Each phase first moves the
  stored results of its experiments to `artifact_logs/stored_<timestamp>/` (the scripts
  resume from checkpoints and would otherwise re-read the stored trials), keeps the stored
  k†\* unless `--phase calibrate` runs, and then **replaces** (no longer merges into)
  `final_experiments/<exp>/` with the fresh results, keeping the stored copy under
  `artifact_logs/stored_<timestamp>/final_experiments/` and the `EXP*_RESULTS.md`
  write-ups, and writing a `FRESH_RUN` marker. `--phase preflight` runs
  `wave_experiments/shared/smoke_test.py` (not `preflight/gates.py`, which runs LLM
  trials). New: `--resume`, `--phase rq4-core` (the Table 4 ablation alone). `--phase
  testbed` uses `quickstart.sh --testbed-only`.
- **`run_artifact.sh live-srsran`** — moves the stored LLM checkpoints
  `srsran/results/llm_trials/{E3,E5,E6}` aside so every trial re-runs; runs the paper's E6
  tiers (`e6_capability_sweep.py --tiers 7-8B,12-15B`, plus the frontier tier when
  `ANTHROPIC_API_KEY` is set) together with the radio measurements, E3, E4, E5, E8 and E10;
  and gates on `verify_paper.py --fresh`. `SRSRAN_BUILD` defaults to the invoking user's
  `~/srsran_build` also under `sudo`. The live modes install `requirements-srsran.txt`.
- **`run_artifact.sh`** — enforces Python 3.10–3.12 (numpy 1.26.4 has no 3.13 wheel);
  `env` checks GNU Radio for `/usr/bin/python3`, which the srsRAN ZeroMQ broker for E0.x
  and E1 requires.
- **`srsran/llm_chain.sh`** — committed; `srsran/chain.sh` previously ran a chain script
  under `/tmp`. The chain runs E5, E3, the E6 frontier tier (if `ANTHROPIC_API_KEY` is set)
  and the E6 local tiers 7-8B and 12-15B.
- **Configuration** — `wave_experiments/config.py` reads `MONGO_URI` from `.env`, like the
  tools, so the experiment harness and the tools use the same database;
  `wave_experiments/shared/smoke_test.py` uses `MONGO_URI` and `OLLAMA_BASE_URL`;
  `.env.example` variable names fixed to those the code reads (`OLLAMA_BASE_URL`, not
  `OLLAMA_HOST`; `OPENAI_COMPAT_*`). New `requirements-api.txt` (openai, google-genai) for
  the optional cloud backends of `wave_experiments/exp1_vuln_multimodel.py`.
- `wave_experiments/exp3`, `exp8`, `exp9`, `exp10`, `exp11`, `exp13` and `exp14` scripts:
  `--help` no longer runs the experiment.

### Repository

- `NOTICE` added: the third-party configurations (Open5GS, UERANSIM, srsRAN) remain
  AGPL-3.0. `docker/testbed/config/open5gs/hnet/README.md` states that the SUCI keys there
  are test-only keys.
- `LICENSE` names the authors. `ANONYMOUS_SUBMISSION.md` removed (submission-stage hosting
  guide, no longer applicable). `traffic/received/` outputs are no longer tracked.
- Internal campaign-tracking text neutralised in `srsran/SPEC.md`, `srsran/RESULTS.md`
  (and its generator `analysis/gen_status_and_repro.py`), scripts and report generators,
  and in the free-text verdict strings of four result files (`E0_1_analysis`,
  `E4_scripted_controller`, `E8_gate_replay`, `E12_qoe_mapping`) — text only; no number or
  key changed. Three scripts renamed to descriptive names:
  `srsran/run_standards_kpi.sh`, `srsran/run_standards_kpi_and_static_phi.sh`,
  `analysis/validate_collector_taint.py`.
- Paper-drafting placeholders removed from `final_experiments/exp*/EXP*_RESULTS.md`.
- `wave_experiments/shared/intents.py` documents the intent tiers.
- Placeholder paths (`/path/to/pala-artifact`) replaced with script-relative roots in
  `experiments/reproduce_all.py`,
  `experiments/new_experiment_campaign/new_experiments/utils.py`,
  `final_experiments/post_hoc_analysis.py`, and `experiments/_as5_sanity_run.py`.

### Documentation

- `CLAIMS.md` — section **Known differences between the paper and the stored data** (18
  rows, including the one-query IsolatedCollector Phase D behind Figure 4c, the separate
  Table 3 session set, and the two averaging conventions in the Table 2 ΔQ column); rows
  cite registry keys and the Track A checks; source files corrected (E1 capacity from
  `E1_harm_mechanism.json`, KPI latency from `exp10/phaseB_summary.json`, BoN-PALA from
  `wave_experiments/results/exp15/summary.json`, recovery from `exp13/summary.json`,
  Table 7 from `experiments/experiment_i_results/i_master_table.csv`); CV = 0.401 and the
  k† distribution attributed to §6.1 and Appendix G rather than Table 8.
- `STATUS.md`, `ARTIFACT.md`, `srsran/README.md` — 54 checks; 79 registered / 41 printed
  srsRAN numbers; stored-mode and fresh-mode tolerances stated as implemented; measured
  live times (≈ 38 h for all UERANSIM experiments, ≈ 5–6 h for the srsRAN live track,
  ≈ 21–22 h for the one-day plan); cloud backends limited to the Table 2 cross-family rows;
  GNU Radio listed as required for Track C2; hardware requirements for running the live
  tracks on the evaluator's own machine; the Zenodo DOI after evaluation for the Available badge.

---

## 2026-09-17 — srsRAN Testbed and Supplementary Experiments

**Context:** This entry brings the artifact in line with the final paper and adds the srsRAN
radio-side validation and the supplementary experiments.

### Added

- **`srsran/`** — second testbed: Open5GS core with an srsRAN Project gNB and srsUE over a
  ZeroMQ RF front-end, one network namespace per UE. Contains experiment scripts
  E0.1–E12b and E-FINAL, shell drivers, gNB/UE configs, every result file, per-trial LLM
  traces (`results/llm_trials/`), the invalidated-run record (`results/INVALID_*/`), the
  testbed manifest, `SPEC.md`, `RESULTS.md`, and a Track C guide in `README.md`.
- **`analysis/`** — number registry (`paper_numbers.json`, `registry.py`), verifiers
  (`verify_paper.py`, `verify_prompt_provenance.py`, `validate_collector_taint.py`), and report
  generators.
- **`tools/qos_manager.py`** — 5QI, ARP priority, and flow-MBR writes for the
  policy-field generality experiment (E5).
- **`traffic/run_all_ues_srsran.py`** — traffic driver for namespaced srsRAN UEs.
- **`wave_experiments/exp16_…` – `exp19_…`** and `results/exp16`, `exp17` — preliminary
  UERANSIM versions of E4, E5, E6, E8, superseded by `srsran/`.
- **`requirements-srsran.txt`** — `pyzmq` and the optional `anthropic` SDK.
- **`run_artifact.sh`** — one command for the whole artifact. By default it creates `.venv`,
  installs dependencies, and runs every offline check (unit tests, Track A, Track C1) with a
  PASS/FAIL summary, per-stage logs in `artifact_logs/`, and a meaningful exit status. Modes
  `env`, `live-ueransim`, `live-srsran`, and `all` drive the live tracks; `--dry-run` prints
  the plan. Live modes back up stored results before overwriting them. Tested from a fresh
  copy with a new virtual environment (all 5 stages pass), and E8 was re-run through the
  live path, regenerating results identical to the stored ones.
- **`LICENSE`** — MIT for the PALA code, with a placeholder copyright holder (authors named
  since 2026-09-18); third-party licenses listed (Open5GS, UERANSIM, srsRAN: AGPLv3).

### Changed (backward-compatible; Track A passed all 32 checks at the time — 54 since 2026-09-18)

- `collector/collector.py` — recognises srsRAN tunnels (`tun_srsue`, `ogstun`) alongside
  UERANSIM `uesimtun`; publishes 5QI, ARP, and flow MBR/GBR means as Type-P fields.
- `collector/collector_isolated.py` — strips **every** Type-P field by provenance. It
  previously stripped AMBR by field name and retained `qos_index`, which left the channel
  open on 5QI (found by E5).
- `wave_experiments/config.py` — `TYPE_P_METRICS` extended to the same fields, for the same
  reason.
- `tools/kpi_analyzer.py` — exposes the new Type-P metrics.
- `agent/agent.py` — `AnthropicLLM` backend for the E6 frontier tier (lazy import).
- `wave_experiments/shared/agent_runner.py` — **bug fix:** policy writes the tool rejected
  were counted as committed and could move the enforcement ceiling; they are now recorded
  with `accepted` and only committed writes are applied. String-typed AMBR arguments no
  longer abort a trial.
- `tools/monitoring_manager.py` — **bug fix:** formatting the validated request instead of
  raw string arguments no longer raises and discards the scheduling result.
- `reproduce_results.py` — section labels use the final table numbers; "adaptive
  attacker" relabelled "adaptive prompts". No logic changed.
- `README.md`, `ARTIFACT.md`, `CLAIMS.md`, `STATUS.md`, `INSTALL.md` — aligned with the
  final paper: Track C added; table and figure numbering updated; Qwen Strict Def. 4 given
  as 18/30; incorrect `run_experiments.sh` phase names, missing figure paths, and fabricated
  pre-computed table paths corrected; the RQ3 claim corrected (the cumulative-threshold rule
  is *more* permissive than per-call review).
- `IEEE_S_P.pdf` — replaced with the accepted paper (clean copy, no revision highlighting; its artifact link points to this repository).
- `requirements.txt` — adds `pytest`, which the unit tests need and was missing.
- `README.md` — one-command Quick Start; a **Reference System** section with the measured
  hardware and software of the machine the experiments ran on. The hardware table previously
  listed "1× A100-80GB / 2× A100-80GB" and `ARTIFACT.md` listed "AMD Ryzen 9, 64 GB, A100";
  neither matched that machine (2× Xeon Gold 6538Y+, 503 GiB, 1× RTX PRO 6000 Blackwell 96 GB).
  Step 6 used `reproduce_results.py --live`, a flag that does not exist. UERANSIM's license
  was given as GPL-2.0; the bundled `UERANSIM/LICENSE` is AGPLv3. Track A was described as
  taking ~10 minutes; it runs in under a minute.
- `.gitignore` — ignores `artifact_logs/`.

### Pre-submission preparation (historical)

- srsRAN scripts: hardcoded absolute paths replaced with `SRSRAN_BUILD` and script-relative
  repository roots.
- `experiments/queue_logs/*.log`, `final_experiments/smoke_verify/smoke_verify.log`:
  absolute paths replaced with `<repo>`.
- This file: a draft PDF filename that contained an author name was replaced with a
  neutral description.
- Evaluation documents and entry-point scripts no longer name a previous venue or paper
  number.
- Historical `experiments/` suites, reports, archived tables, and two archived JSON
  metadata fields (`"paper"`): 22 prior-venue references neutralised. No measured value
  changed. `.gitignore` rules naming an old draft folder replaced with an equivalent glob.

### Not included

- Traces of the single-configuration USRP-2953R hardware-RF confirmation reported in
  Appendix E; they were not retained.

---

## 2026-06-08 — IntAgent → PALA Rename (Repo-Wide)

**Context:** All references to "IntAgent" updated to "PALA" throughout the codebase to match the paper's system name. One exception preserved: the References section of README.md cites the prior published paper "IntAgent: LLM-Based Intent-Driven Network Management for 5G Core" by its original title.

**Scope:** ~90 occurrences across 40+ files — Python class definition (`agent/agent.py`: `class PALA`), all imports (`from agent.agent import PALA`), all instantiations (`PALA(human_confirm=...)`), system prompts, comments, docstrings, all markdown docs, Streamlit UI title, audit log strings in `tools/policy_manager.py`, and MCP server.

**Exception preserved:** the README's citation of the prior paper keeps its original title.

---

## 2026-06-08 — On-Device Model Setup + API Backend Support

**Context:** Setup guide for the three paper LLMs (qwen2.5:72b, llama3.1:70b, mistral-large:latest) on-device via Ollama, and API backend selection wired into the multimodel experiment script (the only experiment with a cloud-backend option).

**Files created:**
- `MODEL_SETUP.md` — Hardware requirements, Ollama pull commands, API alternatives (Together AI for Qwen, Groq for Llama, Mistral API for Mistral Large), CLI usage examples with `--backend` and `--api-model` flags, reproducibility notes (±5–10 pp expected from API quantization differences)

**Files modified:**
- `wave_experiments/shared/agent_runner.py` — `run_trial()` now accepts `backend` and `model` params; creates LLM via `make_llm(backend, model)` instead of reading `OLLAMA_MODEL` env var directly
- `wave_experiments/exp1_vuln_multimodel.py`:
  - Added `API_DEFAULTS` dict mapping each paper model to its cloud API equivalent per provider
  - `run_vulnerable_arm()` signature extended: `backend="ollama"`, `api_model=None`
  - Resolves `api_model` from `API_DEFAULTS` if not explicit; raises clear error if unknown combo
  - `run_trial()` call now passes `backend=backend, model=resolved_api_model`
  - `main()` argparse extended: `--backend` (global default), `--api-model` (global API model ID), `--backend-map` (JSON, per-model routing for running all three with different providers in one command)
- `.env.example` — Added Groq and Mistral API sections with per-provider notes; references MODEL_SETUP.md

**Usage summary (three options):**
1. **On-device (paper setup):** `ollama pull qwen2.5:72b` + `OLLAMA_MODEL=qwen2.5:72b` in `.env`
2. **Single cloud provider:** `--backend groq --api-model llama-3.1-70b-versatile` (Groq has since retired this model)
3. **Mixed per-model:** `--backend-map '{"llama3.1:70b":["groq","llama-3.1-70b-versatile"],...}'`

---

## 2026-06-08 — Docker Single-Command Testbed + Pre-Submission Preparation + Git Init

**Context:** Pre-submission preparation of the artifact for the IEEE S&P 2027 cycle 1 submission (deadline June 11, 2026), whose call asked that artifact repositories not include author information.

**Files modified:**
- `start_network.sh` — replaced hardcoded `$REAL_HOME/Desktop/<user>/marcus` with auto-detection `$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`
- `experiments/run_queue.py` — replaced hardcoded path + fallback with clean `Path(__file__).resolve().parent.parent`
- `experiments/experiments_suite/experiments/exp_config.py` — replaced `Path.expanduser("~/.../marcus")` with `Path(__file__).resolve().parent.parent.parent.parent`
- `experiments/experiments_suite_v2/experiments/exp_config.py` — same fix
- `experiments/experiments_suite/experiments/utils/__init__.py` — same fix (5 levels up)
- `experiments/experiments_suite_v2/experiments/utils/__init__.py` — same fix
- `README.md`, `network_run.md`, `experiments/README.md`, all sub-experiment READMEs, `traffic/client.py`, `traffic/server.py`, `traffic/run_all_ues.py`, `final_experiments/post_hoc_analysis.py`, `experiments/_as5_sanity_run.py`, `experiments/experiments_suite_v2/run_v4.py`, `experiments/new_experiment_campaign/new_experiments/README.md`, `experiments/new_experiment_campaign/new_experiments/utils.py`, `experiments/reproduce_all.py` — bulk replaced `/home/user/Desktop/<user>/marcus` and `~/.../marcus` with `/path/to/pala-artifact`
- `ARTIFACT.md` — removed a contact line that identified the authors
- `.gitignore` — added `final_paper/` (submitted PDF carries paper ID) and `UERANSIM/cmake-build-release/` (contains build-time paths)

**Files created:**
- `ANONYMOUS_SUBMISSION.md` — submission-stage hosting guide, checklist and disclosure templates (removed 2026-09-18)

**Docker single-command testbed:**
- `.env.example` (root) — API key template with Ollama/Gemini/Together options
- `quickstart.sh` — master entry point: prereq check → .env configure → host setup → Docker build+start → venv setup → offline verify → next-steps menu
- `docker/testbed/Dockerfile.ueransim` — replaced COPY-prebuilt-binaries with build-from-source (`git clone --depth 1 --branch v3.2.7 github.com/aligungr/UERANSIM`); old approach required gitignored `UERANSIM/build/` binaries
- `docker/testbed/docker-compose.testbed.yml` — uncommented NWDAF collector service; wired to `.env` for LLM API key; added `nwdaf_results` volume; updated header docs
- `docker/testbed/scripts/tc-setup.sh` — new; applies HTB 15 Mbps + 40ms delay on loopback for ground-truth Q enforcement; idempotent; documents expected baseline Q≈0.85

**Git repo initialized:**
- `git init` run inside `marcus/` creating a standalone repo (separate from parent home repo)
- Branch renamed to `main`
- `.gitignore` additionally excludes internal working and draft directories, `UERANSIM/tools/`, `.ccr/`, and `*.docx`
- 3,805 files tracked — includes all `final_experiments/` trial JSONL, `wave_experiments/`, `docker/testbed/`, artifact evaluation docs

**Verification:**
```bash
grep -rn "author-placeholder" --include="*.py" --include="*.md" --include="*.sh" . \
  | grep -v ".venv/" | grep -v "experiments_trash/" | grep -v "trash/" \
  | grep -v ".git/"
# → (no output — clean)
```

**Next step (historical, submission stage):** publish the repository and link it from the paper submission by June 11, 2026.

---

## 2026-05-15 — Artifact Evaluation Package Prepared

**Context:** Preparing the public artifact promised in the paper's Artifact Availability statement.

**Files created:**
- `ARTIFACT.md` — Main artifact-evaluation guide: claims, badges, quick-start, full reproduction instructions, figure/table → file mappings
- `STATUS.md` — Artifact badge claims (Available + Functional + Reproduced) with justification
- `CLAIMS.md` — Detailed mapping of every paper claim, theorem, and table to specific artifact files and stored result JSONs
- `INSTALL.md` — Two-track installation guide: offline verification (~10 min) and full testbed reproduction (~73 hrs; historical estimate, superseded by the measured ≈ 38 h, see 2026-09-18)
- `reproduce_results.py` — Master script: reads stored JSONL/JSON trial logs, recomputes all paper statistics with pass/fail comparison, calls `generate_all_figures.py`
- `run_experiments.sh` — End-to-end bash experiment runner with `--phase` flags for each RQ
- `analysis/pala_analysis.ipynb` — Jupyter notebook: interactive data exploration, table reproduction, figure generation from stored results
- `.gitignore` — Updated: excludes `.env`, UERANSIM binaries, LaTeX artifacts, trash dirs; explicitly includes all `final_experiments/` JSONL/JSON results

**Files updated:**
- `.gitignore` — Extended from minimal version to full artifact-ready ignore rules

**Artifact structure:**
- Primary result data: `final_experiments/` (JSONL trial records + summary JSONs; 1,418 JSON/JSONL files today)
- Figure generation: `final_paper_results/generate_all_figures.py`
- Pre-generated figures: `final_paper_results/figures/`
- Pre-computed tables: `final_paper_results/tables/`
- Docker testbed: `docker/testbed/`
- Experiment harness: `wave_experiments/`

**Key stored results verified:**
- `exp1/summary.json`: Qwen vulnerable full_loop=66.7%, defended=0%, Fisher p=1.43e-08
- `exp1_multimodel/summary.json`: Mistral 26.7%, Llama 30.0%
- `exp6/kstar.json`: k†*=1, CV=0.401, cv_stable=true
- `exp5/summary.json`: Full PALA 0% circuit closure, IsolatedCollector alone 0%
- `exp7/summary.json`: Adaptive attacker 0% under Full PALA (50 trials)
- `exp3/summary.json`: Per-call 45.3%, cumulative 74.6%, Wilcoxon p=5.96e-6
