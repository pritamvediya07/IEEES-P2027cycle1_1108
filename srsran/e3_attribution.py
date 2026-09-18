#!/usr/bin/env python3
"""E3 — Attribution: operator target vs agent escalation  (paper §6.3 Target versus feedback, RQ2).

THE QUESTION
------------
§6.3 Target versus feedback: when the slice ends up over-provisioned, how do you know that
is the AGENT's doing rather than the operator having asked for something unsafe?
If the operator says "raise it to 60" and it ends at 60, nothing has been
demonstrated.

The answer is Delta_star. Every intent with an explicit target B* is scored on
B_final/B* - 1. Writes issued after B* was already reached are agent-attributable
by construction: the operator's request was satisfied at call k*, and everything
after that is the agent continuing on its own.

ARMS
----
    V     standard collector, no budget    vulnerable baseline
    ISO   ISOLATED collector, NO budget    <-- THE LOAD-BEARING ARM
    BUD   standard collector, drift bound  isolates escalation limiting
    FULL  isolated + drift bound           combined

WHY ISO IS THE PRIMARY RESULT, NOT FULL
---------------------------------------
Under a write budget, Stage D is zero BY DEFINITION — the agent is not permitted
a second write, so it cannot escalate on a readback whatever it believes. Full
PALA therefore proves nothing on its own. The ISO arm imposes no budget at all:
the agent may escalate as freely as in V. If Stage D still collapses, the only
thing that changed is whether the analytics echoed the agent's own writes, and
the readback is what was driving escalation.

REGISTERS: staged-change (explicit B*), SLA-framing (NO numeric target),
null control. The SLA arm matters because it has no target to overshoot, so any
escalation there cannot be blamed on the operator's number.

    .venv/bin/python srsran/e3_attribution.py --n 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.llm_common import run_campaign, summarise, save          # noqa: E402
from srsran.preconditions import assert_ready                        # noqa: E402

ARMS = {"V":    {"defense": "none", "desc": "standard collector, no budget"},
        "ISO":  {"defense": "iso",  "desc": "ISOLATED collector, NO budget (primary)"},
        "BUD":  {"defense": "ht",   "desc": "standard collector, drift bound"},
        "FULL": {"defense": "both", "desc": "isolated + drift bound"}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5, help="trials per (arm, register) cell")
    ap.add_argument("--k-star", type=int, default=3)
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--model", default="qwen2.5:72b")
    ap.add_argument("--arms", default="V,ISO,BUD,FULL",
                    help="comma-separated subset. V,ISO alone gives the load-bearing "
                         "comparison in half the time; BUD and FULL can be added later and "
                         "the completed cells are reused, because checkpoints are "
                         "content-addressed rather than positional.")
    a = ap.parse_args()
    want = [x.strip() for x in a.arms.split(",") if x.strip()]
    bad = [x for x in want if x not in ARMS]
    if bad:
        sys.exit(f"ERROR: unknown arm(s) {bad}; choose from {list(ARMS)}")
    arms = {k: v for k, v in ARMS.items() if k in want}
    assert_ready(need_core=False)

    from wave_experiments.shared.intents import (
        CLOSED_LOOP_D_INTENTS, SLA_LOOP_INTENTS, NULL_INTENTS)
    registers = {"staged": CLOSED_LOOP_D_INTENTS,
                 "sla": SLA_LOOP_INTENTS,
                 "null": NULL_INTENTS}

    cells = []
    for arm, cfg in arms.items():
        for reg, corpus in registers.items():
            for i in range(a.n):
                cells.append({"arm": arm, "register": reg,
                              "intent": corpus[i % len(corpus)],
                              "defense": cfg["defense"], "k_star": a.k_star,
                              "backend": a.backend, "model": a.model})

    print("=" * 82)
    print(f"  E3 — attribution   {len(arms)} arms ({','.join(arms)}) x {len(registers)} "
          f"registers x {a.n} = {len(cells)} trials   model={a.model}")
    print("=" * 82)
    rows = run_campaign("E3", cells, timeout_s=300)

    per_arm = {arm: summarise([r for r in rows if r.get("arm") == arm]) for arm in arms}
    per_cell = {f"{arm}|{reg}": summarise(
        [r for r in rows if r.get("arm") == arm and r.get("register") == reg])
        for arm in arms for reg in registers}

    print(f"\n  {'arm':<5} {'n':>3} {'A':>6} {'B':>6} {'C':>6} {'D':>6} {'closure':>8} "
          f"{'mean D*':>8} {'mean B_final':>13} {'attrib writes':>14}")
    for arm, s in per_arm.items():
        print(f"  {arm:<5} {s['n_ok']:>3} {str(s['stage_A']):>6} {str(s['stage_B']):>6} "
              f"{str(s['stage_C']):>6} {str(s['stage_D']):>6} {str(s['circuit_closure']):>8} "
              f"{str(s['mean_delta_star']):>8} {str(s['mean_b_final_mbps']):>13} "
              f"{str(s['mean_agent_attributable_writes']):>14}")

    print(f"\n  by register (Stage D / closure):")
    print(f"  {'cell':<14} {'n':>3} {'D':>7} {'closure':>8} {'mean D*':>8}")
    for k, s in per_cell.items():
        print(f"  {k:<14} {s['n_ok']:>3} {str(s['stage_D']):>7} "
              f"{str(s['circuit_closure']):>8} {str(s['mean_delta_star']):>8}")

    v = per_arm.get("V", {})
    iso = per_arm.get("ISO", {})
    bud = per_arm.get("BUD", {})
    full = per_arm.get("FULL", {})
    verdict = {
        "primary_result_is_ISO": True,
        "arms_run": list(arms),
        "arms_not_run": [k for k in ARMS if k not in arms],
        "V_stage_D": v.get("stage_D"), "ISO_stage_D": iso.get("stage_D"),
        "BUD_stage_D": bud.get("stage_D"), "FULL_stage_D": full.get("stage_D"),
        "V_closure": v.get("circuit_closure"), "ISO_closure": iso.get("circuit_closure"),
        "V_mean_delta_star": v.get("mean_delta_star"),
        "ISO_mean_delta_star": iso.get("mean_delta_star"),
        "why_ISO_and_not_FULL": (
            "Under a write budget Stage D is zero BY DEFINITION, so BUD and FULL cannot "
            "distinguish 'the readback stopped driving escalation' from 'the agent was not "
            "allowed a second write'. ISO imposes no budget: the agent may escalate as freely "
            "as in V, and the only difference is whether the analytics echo its own writes."),
        "attribution_argument": (
            "Delta_star is computed only where the intent states an explicit target. Writes "
            "after call k* are agent-attributable by construction because the operator's "
            "request was already satisfied. The SLA register carries NO numeric target at all, "
            "so escalation there cannot be attributed to the operator's number under any "
            "reading."),
    }
    print(f"\n  Stage D:  V {v.get('stage_D')} -> ISO {iso.get('stage_D')}   "
          f"(BUD {bud.get('stage_D')}, FULL {full.get('stage_D')})")
    print(f"  closure:  V {v.get('circuit_closure')} -> ISO {iso.get('circuit_closure')}")
    print(f"  mean Delta*: V {v.get('mean_delta_star')} -> ISO {iso.get('mean_delta_star')}")

    payload = {"experiment": "E3", "backend": a.backend, "model": a.model,
               "k_star": a.k_star, "trials_per_cell": a.n,
               "arms": {k: v2["desc"] for k, v2 in arms.items()},
               "arms_not_yet_run": [k for k in ARMS if k not in arms],
               "per_arm": per_arm, "per_cell": per_cell,
               "verdict": verdict, "rows": rows}
    p = save("E3_attribution", payload)
    print(f"\n  -> {p}")


if __name__ == "__main__":
    main()
