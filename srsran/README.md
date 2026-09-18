# srsRAN Testbed — Radio-Side Validation and Supplementary Experiments (Track C)

This directory contains the second testbed used in the paper, for radio-side
validation and supplementary experiments, together with every experiment run on it.

**Its role in the paper is deliberately narrow.** The main end-to-end evaluation
(RQ1–RQ5, Tables 2–4) runs on Open5GS + UERANSIM (Tracks A and B in the top-level
[`README.md`](../README.md)). This testbed exists to:

1. **Validate the physical-harm mechanism with a real radio scheduler** (§6.3,
   App. E). UERANSIM does not enforce AMBR through a radio scheduler in the data plane,
   so on the main testbed over-subscription is realised at a host bottleneck. Here
   the srsRAN MAC scheduler is the bottleneck, and host shaping is held non-binding.
2. **Host the supplementary experiments**: model-capability sweep,
   deterministic controller baseline, target-free escalation, policy-field
   generality, time-dilation gate replay, and oversight overhead.

The Open5GS core, collector, MCP tools, and LLM agent are **the same code** as the
main testbed; only the RAN and UEs change.

---

## What is and is not included

| Included | Not included |
|---|---|
| srsRAN gNB/UE configurations over the **ZeroMQ RF front-end** (`configs/`) | USRP-2953R hardware-RF traces |
| Every experiment script and shell driver used for these experiments | srsRAN source or binaries (build from upstream, below) |
| All result files, per-trial LLM traces, and the invalidated-run record | |
| The experiment specification ([`SPEC.md`](SPEC.md)) and the full results report ([`RESULTS.md`](RESULTS.md)) | |

The paper (App. E) additionally reports a **hardware-RF confirmation** using a
USRP-2953R at both gNB and UE. That single-configuration check reproduced the
qualitative degradation trend; its traces were not retained, and it is not part of
this artifact. **The quantitative, reproducible radio-side validation is the ZeroMQ
configuration provided here.**

---

## Testbed versions

Recorded in [`results/testbed_manifest.json`](results/testbed_manifest.json):

| Component | Version |
|---|---|
| Core | Open5GS v2.7.6 (unchanged from the UERANSIM testbed) |
| gNB | srsRAN Project `release_24_10_1` (commit `ef4b074`) |
| UE | srsRAN 4G `srsue` 25.10.0 (commit `6bcbd9e`) |
| RF | ZeroMQ (`libsrsran_rf_zmq.so`) |
| Carrier | 20 MHz FDD, band 3, 106 PRB, 23.04 Msps |
| UE isolation | one Linux network namespace per UE (`ue1` … `ueN`) |
| Python | 3.12 |

---

## C1 — Offline verification (~1 minute, no radio, no root)

Every srsRAN number in the paper is registered in
[`../analysis/paper_numbers.json`](../analysis/paper_numbers.json) with its source
file and extraction rule. The registry holds 79 registered numbers; `analysis/verify_paper.py`
recomputes each from the stored raw results and additionally checks the 41 srsRAN
numbers printed in the paper, at their printed precision, against the registry. Two
verifiers:

```bash
pip install -r requirements.txt
python analysis/verify_paper.py               # every registered number reproduces from raw traces
python analysis/verify_prompt_provenance.py   # every experiment uses the paper's prompts, corpora and model
```

Expected final lines:

```
PASSED — every paper number is reproducible from the raw traces and matches the paper
PASSED — every experiment uses the paper's prompts, corpora and model
```

`verify_paper.py` also lists numbers flagged **not robust to analysis choices**
(for example, a latency delta at the measurement floor). Those flags are intentional:
the paper quotes such values only as bounds.

To regenerate the registry itself from the raw results:

```bash
python analysis/registry.py
```

---

## C2 — Live reproduction

**One command.**

```bash
sudo --preserve-env=SRSRAN_BUILD,ANTHROPIC_API_KEY ./run_artifact.sh live-srsran
```

It installs `requirements-srsran.txt`, moves the stored LLM checkpoints
`results/llm_trials/{E3,E5,E6}` aside (to `artifact_logs/stored_llm_trials_<timestamp>/`)
so that every trial re-runs, and then runs: the radio measurements E0.1, E0.3/E0.4 and E1;
the E4 scripted controller; E5; E3; E6 with the paper's tiers (the frontier tier only if
`ANTHROPIC_API_KEY` is set, then the local tiers with `--tiers 7-8B,12-15B`); E8; E10. It
starts the collector daemon itself. Its last stage compares the fresh results with the
paper through `python analysis/verify_paper.py --fresh` and can fail. E9, E2, E2.3, E0.5 and
E12/E12b are not part of C2; their stored results are verified offline by C1.
`SRSRAN_BUILD` defaults to the invoking user's `~/srsran_build`, also under `sudo`.

`verify_paper.py --fresh` applies 20 claim-level criteria: the deterministic E4, E5 and E8
results must match exactly; E3 and E6 session counts are compared with the paper's counts
by a two-sided Fisher exact test (p > 0.05); E1 cell capacity 22.8 Mbps ± 10%, victim λ
inflation > 1.5× (paper 1.95×), victim τ flat (5.43 Mbps ± 10%); E0.4 target share > 86%
(paper > 91%); E10 overhead < 1.3 ms.

**Time.** About 5–6 h in total on one GPU, measured from per-cell `elapsed_s` and
result-file timestamps: E3 ≈ 2.0 h; E6 two local tiers ≈ 1.2 h (+ ≈ 0.6 h for the frontier
tier with an API key); the E0.x/E1 radio measurements < 0.5 h together; E4, E5, E8 and E10
a few minutes each.

### Requirements

- Ubuntu 22.04/24.04, x86-64, root access (network namespaces, `tc`, iptables)
- ≥ 8 cores recommended (the ZeroMQ sample stream is CPU-bound)
- `iperf3`, `iproute2`
- **GNU Radio (required)** for the system Python (`/usr/bin/python3`): `sudo apt install gnuradio`.
  It provides the ZeroMQ broker used by E0.x and E1; `./run_artifact.sh env` checks it
- For LLM experiments: local Ollama models (E3: `qwen2.5:72b`; E6: `llama3.1:latest`,
  `gemma3-12b-it-q8:latest`) and, for the E6 frontier tier only, `ANTHROPIC_API_KEY`; see
  [`../MODEL_SETUP.md`](../MODEL_SETUP.md)

`requirements-srsran.txt` is installed automatically by `./run_artifact.sh live-srsran`
and `all`. For manual runs:

```bash
pip install -r requirements.txt -r requirements-srsran.txt
```

### 1. Build srsRAN

Build [srsRAN Project](https://github.com/srsran/srsRAN_Project) at `release_24_10_1`
and [srsRAN 4G](https://github.com/srsran/srsRAN_4G) at the commit above, both with
ZeroMQ support enabled. The scripts locate the binaries through one environment
variable:

```bash
export SRSRAN_BUILD=/path/to/srsran_build     # default: ~/srsran_build
# expected layout:
#   $SRSRAN_BUILD/srsRAN_Project/build/apps/gnb/gnb
#   $SRSRAN_BUILD/srsRAN_4G/build/srsue/src/srsue
```

Because experiments run under `sudo`, pass the variable through:
`sudo --preserve-env=SRSRAN_BUILD …`.

### 2. Bring up the RAN and prepare the host

```bash
sudo --preserve-env=SRSRAN_BUILD srsran/run_srsran.sh start 4   # gNB + 4 UEs, one netns each
sudo srsran/setup_host_srsran.sh                                # netns routes, firewall, CPU governor
sudo srsran/smoke_dataplane.sh ue1                              # confirm downlink traverses the RAN
```

`setup_host_srsran.sh` is idempotent; re-run it if the data plane goes quiet (some
hosts periodically re-sync their iptables chains). Stop with
`sudo srsran/run_srsran.sh stop`.

### 3. Run the experiments

The **measurement experiments** need root (they drive the radio and the probe):

```bash
sudo --preserve-env=SRSRAN_BUILD .venv/bin/python srsran/e0_3_e0_4_regimes.py --n-ue 4
sudo --preserve-env=SRSRAN_BUILD .venv/bin/python srsran/e1_harm_mechanism.py --n-ue 4
```

The **controller, LLM and replay experiments** do not. E3, E4, E5 and E6 read the
analytics the collector writes, so for manual runs start the collector daemon first
(without it the contamination channel is closed; see `INVALID_no_collector` below):

```bash
.venv/bin/python -m collector.collector &     # collector daemon (E3, E4, E5, E6)
.venv/bin/python srsran/e4_scripted_controller.py --n 20
.venv/bin/python srsran/e5_multivariable.py --n-channel 12 --n-agent 5
.venv/bin/python srsran/e3_attribution.py --n 5
.venv/bin/python srsran/e6_capability_sweep.py --n 20 --tiers 7-8B,12-15B
.venv/bin/python srsran/e6_capability_sweep.py --n 20 --only-frontier \
    --frontier-backend anthropic --frontier-model claude-sonnet-4-5   # needs ANTHROPIC_API_KEY
.venv/bin/python srsran/e8_gate_replay.py
.venv/bin/python srsran/e10_overhead.py --n 120
```

The long-running LLM experiments are checkpointed one file per cell under
`results/llm_trials/<exp>/` and can be managed as a chain. `chain.sh` starts the collector
daemon and runs the committed `srsran/llm_chain.sh`: E5, E3, the E6 frontier tier (if
`ANTHROPIC_API_KEY` is set), and the E6 local tiers 7-8B and 12-15B:

```bash
bash srsran/chain.sh start      # also: pause | resume | status | stop
```

A resume skips every finished cell. Cells are keyed by a hash of their identity, not
their position, so a changed cell list can never relabel an existing result. Because
finished cells are skipped, re-running from scratch requires moving the stored
`results/llm_trials/{E3,E5,E6}` directories aside first (`live-srsran` does this).

After any `sudo` run, restore ownership and refresh the report:

```bash
sudo chown -R "$USER:$USER" srsran/results analysis
python analysis/update_results.py
```

---

## Experiment index

**Paper** marks where a result appears in the paper. Experiments marked
*supporting* are retained as evidence but are not quoted.

| ID | Question | Command | Result file | Paper |
|---|---|---|---|---|
| E0.1 | Does the AMBR enforcement point track the requested ceiling? | `sudo … e0_1_ambr_enforcement.py` | `E0_1_ambr_enforcement.json` | supporting (setup gate) |
| E0.2 | Multi-UE scale gate | `sudo … e0_2_scale.py` | `E0_2_scale.json` | supporting (setup gate) |
| E0.3 | Cell capacity C | `sudo … e0_3_e0_4_regimes.py --n-ue 4` | `E0_3_capacity.json` | supporting (C = 23.38 Mbps on a separate run; the paper's 22.8 Mbps is E1's own measurement) |
| E0.4 | Two-regime knee; share of Φ degradation realised at B★ | same | `E0_4_two_regime.json` | §6.3 (>91%: registry `E0_4_target_share_of_dQ_pct` = 94.2%; escalation 5.8%) |
| E0.5 | Are ρ and σ measurable dimensions? | `sudo … e0_5_rho_sigma.py --n-ue 4` | `E0_5_rho_sigma.json` | supporting |
| E1 | Harm mechanism without binding host shaping | `sudo … e1_harm_mechanism.py --n-ue 4` | `E1_harm_mechanism.json` | §6.3, App. E (C = 22.8 Mbps, per-UE baseline 5.71 Mbps; τ 5.43→5.47 Mbps; λ 77.7→151.5 ms, 1.95×) |
| E2.1/2.2 | Write→readback channel, no LLM | `sudo … e2_contamination.py --n 30` | `E2_contamination.json` | supporting |
| E2.3 | ∂R/∂a at provably static Φ | `sudo bash srsran/rerun_e2_3.sh` | `E2_3_dr_fixed_phi.json` | supporting |
| E2.4 | Channel under a TS 28.554 §6.4.2-shaped KPI | `sudo bash srsran/run_standards_kpi.sh` | `E2_4_standards_kpi.json` | supporting |
| E3 | Target vs escalation; target-free escalation | `… e3_attribution.py --n 5` | `E3_attribution.json` | §6.2, App. F (17× undefended, 29× pooled; 9/10, 6/10) |
| E4 | Deterministic controller baseline | `… e4_scripted_controller.py --n 20` | `E4_scripted_controller.json` | §6.2 (Model coverage), App. F (20/20 to 50× vs 20/20 halted) |
| E5 | Generality across four policy fields | `… e5_multivariable.py --n-channel 12 --n-agent 5` | `E5_multivariable.json` | App. E (4/4 vs 0/4 channels open) |
| E6 | Model capability sweep | `… e6_capability_sweep.py --n 20 --tiers 7-8B,12-15B` (+ frontier tier) | `E6_capability_sweep.json` | §6.1, §6.2 (Model coverage), App. F (14/20, 15/20, 15/20) |
| E7 | Register study | — (not in the current chain) | `llm_trials/E7/` | not used (partial, 10/60) |
| E8 | Session gates under time dilation and re-instantiation | `… e8_gate_replay.py` | `E8_gate_replay.json` | §6.4 (129.8× vs 1.5×) |
| E9 | Benign workload and defense cost | `… e9_benign_cost.py --n 2` | `E9_benign_cost.json` | supporting |
| E10 | Oversight overhead per policy call | `… e10_overhead.py --n 120` | `E10_overhead.json` | §6.6, Table 6 in App. B (≤1.16 ms) |
| E11 | Number registry and reproduction | `python analysis/registry.py` | `../analysis/paper_numbers.json` | all srsRAN numbers |
| E12 | QoS→QoE mapping; Q-normaliser sensitivity | `… e12_qoe_mapping.py`, `… e12b_q_sensitivity.py` | `E12_qoe_mapping.json`, `E12b_q_sensitivity.json` | supporting |
| E-FINAL | Definition 4 end-to-end on srsRAN | `sudo bash srsran/run_final.sh` | `E_FINAL_def4*.json` | supporting |

`…` stands for `.venv/bin/python srsran/`; `sudo …` adds
`sudo --preserve-env=SRSRAN_BUILD`. Every result file above is in
[`results/`](results/). Per-trial LLM traces are in [`results/llm_trials/`](results/llm_trials/).

Two sources worth stating explicitly:

- **22.8 Mbps cell capacity (§6.3, App. E)** is E1's own capacity measurement
  (`E1_harm_mechanism.json`: `C_mbps` 22.83, per-UE baseline 5.71 Mbps), taken at the
  start of the E1 campaign. `E0_3_capacity.json` (23.38 Mbps) is a separate run.
- **">91%" target share (§6.3)** is registry key `E0_4_target_share_of_dQ_pct` = 94.2%:
  the share of the total paper-Q degradation in `E0_4_two_regime.json` already realised
  when the ceiling reaches B★ = 3× baseline, taking the minimum over the two measured
  baselines (5.71 and 5.84 Mbps). The escalation share is the remaining 5.8%
  (`E0_4_escalation_share_of_dQ_pct`).

Full per-experiment objectives, claim boundaries, and raw tables are in
[`RESULTS.md`](RESULTS.md).

---

## Invalidated runs

Runs that were found to be invalid are **kept, not deleted**, under
`results/INVALID_*/`, each with the defect that invalidated it:

| Directory | Defect (as recorded in `RESULTS.md`) |
|---|---|
| `INVALID_no_collector` | No collector daemon ran, so analytics froze and every trial read the same stale value; the contamination channel was closed throughout |
| `INVALID_short_flush` | The flush window let the previous trial's policy writes survive into the next trial |
| `INVALID_partial_settle` | Settling was verified on only the last 10 records, while the agent chooses its own sample size (up to 500) and could average stale records |
| `INVALID_rejected_counted` | Policy writes the tool had rejected were counted as committed, because calls were logged from the request rather than the result |
| `INVALID_iso_confounded` | The IsolatedCollector control arm of E2.3 was not isolated: the collector daemon kept writing standard AMBR records, so both arms showed the same ΔR |
| `INVALID_baseline_unenforced` | The baseline ceiling was written to the subscriber database but never applied at the HTB enforcement point, so baseline throughput ran at full cell capacity |
| `INVALID_e3_phi_no_readback` | R was taken from the agent's write rather than its readback, and no pre-action Q₀ was measured, so Definition 4's do-nothing alternative was never observed |
| `INVALID_api_credit` | API credit ran out mid-tier (E6 frontier); all-error trials had been recorded as completed |

No number in the paper is drawn from these directories. They document what was found
and corrected, so the reported results can be audited against the failures they replace.

---

## Relation to `wave_experiments/exp16–19`

`wave_experiments/exp16_scripted_controller.py`, `exp17_second_variable_5qi.py`,
`exp18_capability_sweep.py`, and `exp19_gate_replay.py` are **preliminary versions**
of E4, E5, E6, and E8 written against the UERANSIM testbed before this campaign.
They are superseded: the numbers in the paper come from the srsRAN versions in this
directory.
