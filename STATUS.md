# Artifact Status

**Paper:** Architecture-Induced Reward Hacking in NWDAF-Integrated LLM Control Loops
**Venue:** IEEE S&P 2027, Cycle 1

---

## Badges Claimed

### Artifacts Available ✅

The artifact is archived on Zenodo, DOI 10.5281/zenodo.22843385 (release `v1.0-ae`); the
version after evaluation is deposited as a new Zenodo version before the camera-ready
deadline (14 Oct 2026), as the Available badge requires; the paper
(IEEE_S_P.pdf) links this GitHub repository, and the camera-ready will also cite the DOI. The GitHub
repository (https://github.com/pritamvediya07/IEEES-P2027cycle1_1108) is the evaluation
copy.

- Complete PALA source (`agent/`, `tools/`, `collector/`, `mcp_server/`, `config/`)
- Docker Open5GS + UERANSIM testbed (`docker/testbed/`)
- Experiment harness for Exp 1–15 (`wave_experiments/`)
- 1,418 stored UERANSIM result files (JSON/JSONL trial logs and summary statistics, `final_experiments/`)
- srsRAN radio-side validation: testbed configuration, experiment scripts, drivers, every
  result file, per-trial LLM traces, and the invalidated-run record (`srsran/`)
- Number registry and verifiers (`analysis/`)
- Figure and table generators, analysis notebook (`analysis/pala_analysis.ipynb`)

### Artifacts Functional ✅

- **Unit tests** (`tests/test_tools.py`): 26 tests pass on an in-memory MongoDB (mongomock); they contact no database or live infrastructure
- **One command** (`run_artifact.sh`): installs dependencies and runs every offline check —
  unit tests, Track A, and Track C1 — with a PASS/FAIL summary and exit status
- **Offline reproduction** (`reproduce_results.py`): 54 checks, every statistic recomputed
  from the stored trial logs (Fisher exact and Wilcoxon tests via SciPy), in under a minute
  with Python 3.10–3.12
- **Offline srsRAN check** (`analysis/verify_paper.py`): recomputes all 79 registered srsRAN
  numbers from raw results and checks the 41 printed in the paper, in ~1 minute
- **Docker testbed**: brings up Open5GS Release-18 with UERANSIM; tested on Ubuntu 22.04 LTS
- **srsRAN testbed**: `srsran/run_srsran.sh` brings up an srsRAN Project gNB and srsUE over
  ZeroMQ, one network namespace per UE

### Results Reproduced ✅

**Main evaluation** — `python reproduce_results.py` (54 checks). Fresh results from Tracks B and C2
are judged by `reproduce_results.py --fresh` and `analysis/verify_paper.py --fresh`.
Stored mode requires each recomputed value to match the paper at its printed precision
(±0.5 pp for percentages). Fresh mode judges a proportion by a two-sided Fisher exact test
of the fresh count against the paper's count (pass if p > 0.05), requires p < 10⁻⁴ for the
oversight tests, and keeps the ordering claims.

| Claim (paper) | Stored result | Criterion on a fresh run (`--fresh`) |
|---|---|---|
| Qwen full-loop 20/30 (66.7%); Strict Def. 4 18/30 (60.0%) — Table 2 | `exp1/summary.json` | Fisher vs paper count, p > 0.05 |
| Mistral full-loop 8/30 (26.7%) — Table 2 | `exp1_multimodel/summary_mistral_large_latest.json` | Fisher vs paper count, p > 0.05 |
| Llama full-loop 9/30 (30.0%) — Table 2 | `exp1_multimodel/summary_llama3_1_70b.json` | Fisher vs paper count, p > 0.05 |
| Full PALA 0/20 operational closures — Table 4 | `exp5/summary.json` | Fisher vs 0/20, p > 0.05 |
| IsolatedCollector 0/20 full-loop closures — Table 4 | `exp5/summary.json` | Fisher vs 0/20, p > 0.05 |
| k†\* = 1, CV = 0.401 — §6.1, App. G | `exp6/kstar.json` | k†\* exactly 1, CV 0.401 ± 0.05 (Exp 6 is not in the one-day plan; the check then reads the stored calibration) |
| Per-call vs cumulative approval, all three families (Qwen 45.3% vs 74.6%), Wilcoxon p₂ — Table 3 | `exp3/exp3_trials.jsonl`, `exp3_multimodel/exp3_multimodel_trials.jsonl` | approval rates ±10 pp; Wilcoxon per-call < cumulative, p < 10⁻⁴ |
| KPI latency 3,942 ms → < 0.1 ms — Table 6 | `exp10/phaseB_summary.json` | undefended 3,000–5,000 ms and IsolatedCollector < 0.1 ms (RQ5 is not in the one-day plan) |
| UERANSIM share of ΔQ at B★ ≥ 71% — §6.3 | probe shaper model (`wave_experiments/shared/probe.py`), checked against `exp1` τ samples | analytical: computed from the shaper model, not re-measured |
| Adaptive prompts: 0/50 closures under Full PALA — Table 9 | `exp7/data/exp7_trials.jsonl` | Fisher vs 0/50, p > 0.05 (Exp 7 is not in the one-day plan) |

**srsRAN radio-side validation** — `python analysis/verify_paper.py` (stored: 41 printed
numbers at printed precision); after Track C2, `analysis/verify_paper.py --fresh` applies
20 claim-level criteria (deterministic E4/E5/E8 exact; E3/E6 session counts by Fisher vs
the paper's counts; E1 capacity 22.8 Mbps ± 10%, λ inflation > 1.5×, τ 5.43 Mbps ± 10%;
E0.4 target share > 86%; E10 overhead < 1.3 ms):

| Claim (paper) | Stored result |
|---|---|
| Capability tiers 14/20, 15/20, 15/20 — §6.2 | `srsran/results/E6_capability_sweep.json` |
| Scripted controller 20/20 vs 20/20 — §6.2 | `srsran/results/E4_scripted_controller.json` |
| Radio-side harm: λ 77.7→151.5 ms (1.95×), τ flat; capacity 22.8 Mbps — §6.3 | `srsran/results/E1_harm_mechanism.json` |
| Share of ΔQ at B★ > 91% (stored 94.2%) — §6.3 | `srsran/results/E0_4_two_regime.json` |
| Time-dilation gate replay 129.8× vs 1.5× — §6.4 | `srsran/results/E8_gate_replay.json` |
| Gate overhead ≤ 1.16 ms — §6.6 | `srsran/results/E10_overhead.json` |

Full mapping: [CLAIMS.md](CLAIMS.md). Printed numbers that the stored data do not reproduce
exactly (for example the Table 3 AND-rule column) are listed there under
[Known differences between the paper and the stored data](CLAIMS.md#known-differences-between-the-paper-and-the-stored-data).

---

## Artifact Scope and Limitations

**Traceable to stored result files:** the tables, figures and quantitative claims mapped in
[CLAIMS.md](CLAIMS.md), with the exceptions listed there under Known differences.

**Mechanically checked:** the 54 Track A checks (`reproduce_results.py`) and the 41 srsRAN
numbers printed in the paper (`analysis/verify_paper.py`, which also recomputes all 79
registered numbers).

**Requires a live testbed to re-run:**
- generating new trial logs
- validating with a different LLM backend or model version
- the srsRAN measurements (root access, an srsRAN build with ZeroMQ, and GNU Radio)

**Hardware for live runs:** the evaluator's own machine with one GPU ≥ 48 GB, Docker and
Ollama; root, native Open5GS, srsRAN (ZeroMQ) and GNU Radio for the srsRAN track. Details:
[README](README.md#hardware-for-the-reproduced-badge).

**Not included:**
- USRP-2953R hardware-RF traces for the single-configuration confirmation in Appendix E;
  they were not retained, and the reproducible radio-side validation is the ZeroMQ
  configuration in `srsran/`
- srsRAN and UERANSIM compiled binaries (build from upstream; Docker image for UERANSIM)
- API keys for cloud LLM providers (set via `.env`)
- any production network configuration or real subscriber data

---

## Estimated Evaluation Time

Live times are measured active run times from the stored trial timestamps, on the reference
system with one GPU. The one-day evaluation plan is in the README's
[Artifact Evaluation Plan](README.md#artifact-evaluation-plan-fits-in-one-day).

| Evaluation path | Time | Hardware |
|---|---|---|
| `./run_artifact.sh` — all offline checks | a few minutes first run (install), ~30 s after | any machine with Python 3.10–3.12 |
| Track A — offline main evaluation | < 1 min | any machine with Python 3.10–3.12 |
| Track C1 — offline srsRAN check | ~1 min | any machine with Python 3.10–3.12 |
| Unit tests | ~15 s | any machine (in-memory database) |
| Analysis notebook | ~30 min | any machine |
| Track B — RQ1 only (exp1 Qwen 3.1 h + exp1_multimodel 3.1 h) | ≈ 6.2 h | GPU server + Docker testbed |
| Track B — all paper experiments (exp1 3.1, exp1_multimodel 3.1, exp2 2.1, exp3 0.7, exp3_multimodel 2.4, exp5 3.9, exp6 5.5, exp7 7.7, exp8 4.6, exp9 0.9, exp13 3.1 h; exp10/11/14 < 0.2 h each; exp15) | ≈ 38 h | GPU server + Docker testbed |
| Track C2 — srsRAN live track (`live-srsran`) | ≈ 5–6 h | root, srsRAN build, GNU Radio, local GPU for the LLM tiers (`ANTHROPIC_API_KEY` only for the E6 frontier tier) |
| One-day plan — rq1 + rq2 + rq3 + rq4-core (≈ 16 h) + Track C2 | ≈ 21–22 h | GPU ≥ 48 GB, Docker, root, srsRAN build |
