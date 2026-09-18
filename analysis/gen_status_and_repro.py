#!/usr/bin/env python3
"""Generate the status table and reproduction section FROM ACTUAL STATE.

Both were hand-maintained and both went stale: the status table still listed E3,
E5 and E9 as NOT RUN long after all three had completed, which would tell a
reader the work had never been done. Anything that describes what exists should
be derived from what exists.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "srsran" / "results"
O = []; w = O.append


def has(f): return (RES / f).exists()
def nc(e):
    d = RES / "llm_trials" / e
    return len(list(d.glob("cell_*.json"))) if d.exists() else 0


# experiment, spec question, paper location, summary file, expected cells, needs
SPEC = [
 ("E0.1", "AMBR enforcement verification", "gate", "E0_1_ambr_enforcement.json", None, None),
 ("E0.2", "Multi-UE scale", "gate", "E0_2_scale.json", None,
  "n=1,2 re-record at slow_down 1 outstanding"),
 ("E0.3", "Bottleneck characterisation (C)", "§6.3 Physical-harm mechanism", "E0_3_capacity.json", None, None),
 ("E0.4", "Two-regime confirmation", "§6.3 Physical-harm mechanism", "E0_4_two_regime.json", None, None),
 ("E0.5", "ρ and σ resolution", "App. F weight sensitivity", "E0_5_analysis.json", None, None),
 ("E1", "Harm mechanism", "§6.3 Physical-harm mechanism", "E1_harm_mechanism.json", None, None),
 ("E2.1/2.2", "Contamination channel, no LLM", "App. A Standards basis for AS2", "E2_contamination.json", None, None),
 ("E2.3", "∂R/∂aⱼ at provably static Φ", "§3.2 Proxy reward vs. true quality", "E2_3_dr_fixed_phi.json", None,
  "root + live radio"),
 ("E2.4", "TS 28.554 §6.4.2 shaped KPI", "App. A Standards basis for AS2", "E2_4_standards_kpi.json", None, None),
 ("E3", "Attribution: target vs escalation", "§6.3 Target versus feedback", "E3_attribution.json", ("E3", 60), None),
 ("E4", "Deterministic controller baseline", "App. F Scripted-controller control", "E4_scripted_controller.json", None, None),
 ("E5", "Generality across policy variables", "App. E Policy-field reachability", "E5_multivariable.json", ("E5", 15), None),
 ("E6", "Model capability sweep", "§6.2 Model coverage; App. F Model scale", "E6_capability_sweep.json", ("E6", 100),
  "frontier + 4 local tiers"),
 ("E7", "Register study", "supplementary", None, ("E7", 60), "deprioritised"),
 ("E8", "Gate designs under time dilation", "§6.4 Time-dilation check; §6.5 Simpler alternatives", "E8_gate_replay.json", None, None),
 ("E9", "Benign workload and defense cost", "§6.6 / App. B benign cost", "E9_benign_cost.json", ("E9", 30), None),
 ("E10", "Oversight overhead", "§6.6 Runtime overhead", "E10_overhead.json", None, None),
 ("E11", "Number registry and reproduction", "Artifact: paper-number consistency", None, None, None),
 ("E12", "QoS→QoE mapping", "§3.2 QoS vs. QoE scope", "E12_qoe_mapping.json", None, None),
 ("E12b", "Q normaliser sensitivity", "App. F weight sensitivity", "E12b_q_sensitivity.json", None, None),
 ("E-FINAL", "Definition 4 end-to-end, targeted stratum", "§6.3 Physical-harm mechanism", "E_FINAL_def4.json", None,
  "4/4 sessions that acted satisfied both conjuncts"),
 ("E-FINAL+", "Definition 4, open-ended stratum with kpi accounting", "§6.3 Physical-harm mechanism",
  "E_FINAL_def4_openended.json", None,
  "channel closure 5/5 -> 0/5; escalation reduction NOT significant"),
]

w("# APPENDIX G — Status of every experiment, generated from actual state\n")
w("> This table is produced by `analysis/gen_status_and_repro.py` from the files that\n"
  "> exist, not maintained by hand. An earlier hand-written version still listed E3, E5\n"
  "> and E9 as NOT RUN long after all three had completed.\n")
w("\n| # | experiment | paper location | status | note |")
w("|---|---|---|---|---|")
done = running = todo = 0
for tag, name, rev, summary, cells, note in SPEC:
    if tag == "E11":
        st = "**done**" if (ROOT / "analysis" / "paper_numbers.json").exists() else "not run"
    elif cells:
        n, exp_n = nc(cells[0]), cells[1]
        if n >= exp_n: st = f"**done** ({n}/{exp_n})"
        # "partial" rather than "running": the generator cannot see whether a
        # campaign is in flight or stopped, and calling a paused campaign
        # "running" overstates it. The count is the fact; the verb is not.
        elif n > 0:    st = f"partial ({n}/{exp_n})"
        else:          st = "not run"
    else:
        st = "**done**" if (summary and has(summary)) else "not run"
    if st.startswith("**done"): done += 1
    elif st.startswith("partial"): running += 1
    else: todo += 1
    w(f"| {tag} | {name} | {rev} | {st} | {note or '—'} |")
w(f"\n**{done} complete · {running} partial · {todo} not started** of {len(SPEC)}.")
if running:
    w("\nA partial campaign has banked cells and is resumable — "
      "`srsran/chain.sh resume` skips every finished cell by content hash. "
      "Rates from a partial tier are not quotable.\n")
else:
    w("")

w("\n## By paper section\n")
BY = {"§6.3 mechanism and attribution (RQ2)": ["E0.3","E0.4","E1","E3","E-FINAL","E-FINAL+"],
      "App. A / App. E standards basis and policy fields": ["E2.1/2.2","E2.3","E2.4","E5"],
      "App. F controls and Q sensitivity": ["E0.5","E4","E12","E12b"],
      "§6.2 / App. F model coverage (RQ1)": ["E6"],
      "§6.4–§6.6 oversight, benign cost, overhead (RQ3–RQ5)": ["E8","E9","E10"],
      "Artifact: paper-number consistency": ["E11"]}
st_of = {}
for tag, name, rev, summary, cells, note in SPEC:
    if tag == "E11":
        st_of[tag] = (ROOT / "analysis" / "paper_numbers.json").exists()
    elif cells:
        st_of[tag] = nc(cells[0]) >= cells[1]
    else:
        st_of[tag] = bool(summary and has(summary))
w("\n| paper section | experiments | complete |")
w("|---|---|---|")
for r in ("§6.3 mechanism and attribution (RQ2)", "App. A / App. E standards basis and policy fields",
          "App. F controls and Q sensitivity", "§6.2 / App. F model coverage (RQ1)",
          "§6.4–§6.6 oversight, benign cost, overhead (RQ3–RQ5)", "Artifact: paper-number consistency"):
    exps = BY[r]
    ok = sum(1 for e in exps if st_of.get(e))
    mark = "**ALL DONE**" if ok == len(exps) else f"{ok}/{len(exps)}"
    w(f"| {r} | {', '.join(exps)} | {mark} |")

w("\n---\n")
w("# APPENDIX D — Reproduction\n")
w("Commands are grouped by what they need. Every script refuses to record rather than\n"
  "produce data it cannot stand behind.\n")
w("\n## No root, no radio, no LLM\n")
w("```bash")
for c in ("srsran/e2_contamination.py --n 30 --skip-phi",
          "srsran/e4_scripted_controller.py --n 20",
          "srsran/e8_gate_replay.py",
          "srsran/e10_overhead.py --n 120",
          "srsran/e12_qoe_mapping.py",
          "srsran/e12b_q_sensitivity.py"):
    w(f".venv/bin/python {c}")
w("```\n")
w("\n## Analysis and integrity checks\n")
w("```bash")
for c in ("analysis/registry.py",
          "analysis/verify_paper.py --emit-latex        # must exit 0",
          "analysis/verify_prompt_provenance.py         # prompts match the published corpus",
          "analysis/validate_collector_taint.py         # per-item taint audit",
          "analysis/gen_experiment_reports.py           # Appendix R",
          "analysis/gen_raw_appendix.py                 # Appendix Z",
          "analysis/gen_status_and_repro.py             # this appendix",
          "analysis/update_results.py                   # runs all of the above and syncs"):
    w(f".venv/bin/python {c}")
w("```\n")
w("\n## LLM experiments — pausable and resumable\n")
w("A collector daemon MUST be running or the analytics freeze and the contamination\n"
  "channel closes silently. `srsran/llm_common.py` aborts if the newest record is more\n"
  "than 30 s old.\n")
w("```bash")
w("setsid nohup .venv/bin/python -m collector.collector > /tmp/srsran/collector.log 2>&1 &")
w("")
w("srsran/chain.sh start      # run the configured stages")
w("srsran/chain.sh pause      # stop at the next cell boundary, nothing lost")
w("srsran/chain.sh resume     # skip every finished cell")
w("srsran/chain.sh status")
w("")
w("# or individually")
w(".venv/bin/python srsran/e9_benign_cost.py --n 1")
w(".venv/bin/python srsran/e5_multivariable.py --n-channel 12 --n-agent 5")
w(".venv/bin/python srsran/e3_attribution.py --n 5 --arms V,ISO,BUD,FULL")
w(".venv/bin/python srsran/e6_capability_sweep.py --n 20 --only-frontier \\")
w("      --frontier-backend anthropic --frontier-model claude-sonnet-4-5")
w(".venv/bin/python srsran/e6_capability_sweep.py --n 20    # local tiers")
w("```\n")
w("\n## Needs root and a live radio\n")
w("These bring up gNB + UEs + broker themselves and refuse to run while the LLM chain\n"
  "is active, since both write the same `session[].ambr` field.\n")
w("```bash")
w("sudo bash srsran/run_standards_kpi.sh   # E2.4  (App. A standards basis) — pauses and resumes the chain")
w("sudo bash srsran/run_short_remaining.sh # E2.3 + E0.2 n=1,2 re-record")
w("sudo bash srsran/run_standards_kpi_and_static_phi.sh   # E2.4 + E2.3 together")
w("```\n")
w("\n## Ownership note\n")
w("The sudo runs write results as root, which stops the unprivileged refresh from\n"
  "overwriting them. After any sudo run:\n")
w("```bash")
w('sudo chown -R "$USER:$USER" srsran/results analysis')
w("```\n")

sys.stdout.write("\n".join(O) + "\n")
