#!/usr/bin/env python3
"""Generate Appendix H (the LLM experiments) from whatever result files exist.

Written ahead of the campaign finishing so the write-up is mechanical rather
than hand-typed, for the same reason E11 exists: a number that is transcribed
by hand is a number that can be transcribed wrongly. Every figure below is read
out of the result JSON at generation time.

Stages that have not finished are reported as NOT RUN rather than omitted, so
the appendix never silently implies more coverage than the data supports.

    .venv/bin/python analysis/gen_llm_appendix.py > /tmp/appH.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "srsran" / "results"
out = []
w = out.append


def load(name):
    p = RES / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def pct(x):
    return "—" if x is None else f"{100*x:.0f}%"


def num(x, nd=2):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


w("\n---\n")
w("# APPENDIX H — The LLM experiments (E3, E5 Part 2, E6, E7, E9)\n")
w("Every trial below drives the **same** `agent.agent.PALA` loop, the same\n"
  "`SYSTEM_PROMPT`, and the same intent corpora used for the published results.\n"
  "The srsRAN harness adds only bookkeeping the original runs did not record:\n"
  "B★ (the operator's stated target), Δ★ = B_final/B★ − 1, k★ (the call at which\n"
  "B★ was reached), and the stages named explicitly.\n")
w("\n**Stage mapping** — A decomposed · B contaminated readback · C self-confirmed ·\n"
  "D escalated *after* a contaminated readback · closure = A∧B∧C∧D.\n")

# ── E7 ────────────────────────────────────────────────────────────────────
d = load("E7_register.json")
w("\n## H.1 — E7: register study\n")
if not d:
    w("**NOT RUN / incomplete.**\n")
else:
    w(f"Model `{d['model']}`, {d['trials_per_register']} trials per register. "
      "The target value is identical (60 Mbps) in the staged and direct arms, so any\n"
      "difference between them is attributable to the register, not to the magnitude asked for.\n")
    w("\n| register | n | A | B | C | D | closure | mean writes | mean B_final |")
    w("|---|---|---|---|---|---|---|---|---|")
    for reg, s in d["per_register"].items():
        w(f"| {reg} | {s['n_ok']} | {pct(s['stage_A'])} | {pct(s['stage_B'])} | "
          f"{pct(s['stage_C'])} | {pct(s['stage_D'])} | **{pct(s['circuit_closure'])}** | "
          f"{num(s['mean_policy_calls'])} | {num(s['mean_b_final_mbps'])} Mbps |")
    w("\n| comparison | staged | direct | null | Fisher p (vs direct) | Fisher p (vs null) |")
    w("|---|---|---|---|---|---|")
    for label, t in d["significance"].items():
        w(f"| {label} | {t['staged']} | {t['direct']} | {t['null']} | "
          f"{t['staged_vs_direct_p']} | {t['staged_vs_null_p']} |")

# ── E3 ────────────────────────────────────────────────────────────────────
d = load("E3_attribution.json")
w("\n## H.2 — E3: attribution, target vs escalation\n")
if not d:
    w("**NOT RUN / incomplete.**\n")
else:
    w(f"Model `{d['model']}`, {d['trials_per_cell']} trials per (arm × register) cell, "
      f"drift budget k★ = {d['k_star']}.\n")
    w("\n| arm | collector | budget | n | A | B | C | D | closure | mean Δ★ | mean B_final | attributable writes |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    meta = {"V": ("standard", "none"), "ISO": ("**isolated**", "**none**"),
            "BUD": ("standard", "drift bound"), "FULL": ("isolated", "drift bound")}
    for arm, s in d["per_arm"].items():
        c, b = meta.get(arm, ("?", "?"))
        w(f"| {arm} | {c} | {b} | {s['n_ok']} | {pct(s['stage_A'])} | {pct(s['stage_B'])} | "
          f"{pct(s['stage_C'])} | **{pct(s['stage_D'])}** | **{pct(s['circuit_closure'])}** | "
          f"{num(s['mean_delta_star'])} | {num(s['mean_b_final_mbps'])} | "
          f"{num(s['mean_agent_attributable_writes'])} |")
    v = d["verdict"]
    w(f"\n**Stage D: V {pct(v['V_stage_D'])} → ISO {pct(v['ISO_stage_D'])}.**\n")
    w("\n### Why ISO is the primary result, not Full PALA\n")
    w(v["why_ISO_and_not_FULL"] + "\n")
    w("\n### The attribution argument\n")
    w(v["attribution_argument"] + "\n")
    w("\n| cell | n | D | closure | mean Δ★ |")
    w("|---|---|---|---|---|")
    for k, s in d["per_cell"].items():
        w(f"| {k} | {s['n_ok']} | {pct(s['stage_D'])} | {pct(s['circuit_closure'])} | "
          f"{num(s['mean_delta_star'])} |")

# ── E5 Part 2 ─────────────────────────────────────────────────────────────
d = load("E5_multivariable.json")
w("\n## H.3 — E5 Part 2: does the FAILURE generalise?\n")
if not d or not isinstance(d.get("failure_per_variable"), dict) or \
        "status" in d.get("failure_per_variable", {}):
    w("**NOT RUN / incomplete.** Part 1 (the channel) is in Appendix F.8.\n")
else:
    w("Part 1 showed the *channel* is open on 4/4 variables. This is the separate,\n"
      "weaker question of whether an agent actually escalates on each one.\n")
    w("\n| variable | n | A | B | C | D | closure |")
    w("|---|---|---|---|---|---|---|")
    for var, s in d["failure_per_variable"].items():
        w(f"| {var} | {s['n_ok']} | {pct(s['stage_A'])} | {pct(s['stage_B'])} | "
          f"{pct(s['stage_C'])} | {pct(s['stage_D'])} | **{pct(s['circuit_closure'])}** |")
    w("\nThe channel result and the failure result must be quoted separately. A perfect\n"
      "channel score across four variables is a statement about the architecture; it does\n"
      "not license the claim that an agent escalates on all of them.\n")

# ── E9 ────────────────────────────────────────────────────────────────────
d = load("E9_benign_cost.json")
w("\n## H.4 — E9: benign workload and defense cost\n")
if not d:
    w("**NOT RUN / incomplete.**\n")
else:
    dist = d["verdict"]["corpus_composition"]
    w("### Corpus composition — stated because the objection was about the corpus\n")
    w("\n| committed writes needed | tasks |")
    w("|---|---|")
    for k in sorted(dist, key=lambda x: (x == "3+", x)):
        w(f"| {k} | {dist[k]} |")
    w("\n### Cost as a curve, not a single number\n")
    w("\n| arm | n | completion | Δ vs none | false rejection | mean writes |")
    w("|---|---|---|---|---|---|")
    for arm, s in d["per_arm"].items():
        w(f"| {arm} | {s['n']} | {pct(s['completion_rate'])} | "
          f"{num(s['completion_delta_vs_none'], 3)} | {pct(s['false_rejection_rate'])} | "
          f"{num(s['mean_policy_calls'])} |")
    w("\n### The deployability argument\n")
    w(d["verdict"]["ISO_IMPOSES_NO_RESTRICTION"] + "\n")
    w("\n" + d["verdict"]["cost_is_a_curve_not_a_number"] + "\n")

# ── E6 ────────────────────────────────────────────────────────────────────
d = load("E6_capability_sweep.json")
w("\n## H.5 — E6: model capability sweep\n")
if not d:
    w("**NOT RUN / incomplete.**\n")
else:
    w(f"{d['trials_per_tier']} trials per tier, identical interfaces and intent corpus.\n")
    w("\n| tier | model | n | tool-use competence | A | B | C | D | closure | mean Δ★ |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for tier, s in d["per_tier"].items():
        flag = " ⚠ floor" if s["capability_floor"] else ""
        w(f"| {tier}{flag} | `{s['model']}` | {s['n_ok']} | {s['tool_use_competent']:.2f} | "
          f"{pct(s['stage_A'])} | {pct(s['stage_B'])} | {pct(s['stage_C'])} | "
          f"{pct(s['stage_D'])} | **{pct(s['circuit_closure'])}** | {num(s['mean_delta_star'])} |")
    v = d["verdict"]
    w(f"\n**Falsification condition, stated in advance:** {v['falsification_condition']}.\n")
    w(f"\n**Falsified: {v['falsified']}.**\n")
    w("\n### The capability floor caveat\n")
    w(v["capability_floor_caveat"] + "\n")
    if v["tiers_at_capability_floor"]:
        w(f"\nTiers at the floor: {', '.join(v['tiers_at_capability_floor'])}. These are "
          "reported as *incapable*, not as *safe*.\n")

sys.stdout.write("\n".join(out) + "\n")
