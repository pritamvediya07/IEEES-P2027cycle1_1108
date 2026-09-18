#!/usr/bin/env python3
"""E7 — Register study, re-run on srsRAN  (retained from the current work).

Staged-change vs direct-change vs null-control, everything else fixed. This
experiment was sound in the original submission and needs no Phi at all: every
endpoint is behavioural. It is re-run here only so that all reported results
come from one testbed.

The claim under test is narrow and worth stating precisely: an operator-normative
register (ITIL/SRE staged-change vocabulary) activates multi-step decomposition,
while an equally explicit direct instruction to the same target does not, and a
null instruction does not either. The target value is IDENTICAL across staged
and direct arms, so the difference cannot be the number being asked for.

    .venv/bin/python srsran/e7_register.py --n 20
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.llm_common import run_campaign, summarise, save          # noqa: E402
from srsran.preconditions import assert_ready                        # noqa: E402


def fisher(a, b, c, d):
    """Two-sided Fisher exact test on a 2x2 table, exact and dependency-free."""
    from math import comb
    n = a + b + c + d
    if n == 0:
        return None
    r1, c1 = a + b, a + c

    def p_of(x):
        return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)

    p_obs = p_of(a)
    lo = max(0, c1 - (n - r1))
    hi = min(r1, c1)
    return round(sum(p_of(x) for x in range(lo, hi + 1)
                     if p_of(x) <= p_obs + 1e-12), 8)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20, help="trials per register")
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--model", default="qwen2.5:72b")
    a = ap.parse_args()
    assert_ready(need_core=False)

    from wave_experiments.shared.intents import (
        CLOSED_LOOP_D_INTENTS, DIRECT_INTENTS, NULL_INTENTS)

    registers = {"staged": CLOSED_LOOP_D_INTENTS,
                 "direct": DIRECT_INTENTS,
                 "null": NULL_INTENTS}

    cells = []
    for reg, corpus in registers.items():
        for i in range(a.n):
            cells.append({"register": reg, "intent": corpus[i % len(corpus)],
                          "defense": "none", "backend": a.backend, "model": a.model})

    print("=" * 78)
    print(f"  E7 — register study   {a.n} trials x {len(registers)} registers "
          f"= {len(cells)}   model={a.model}")
    print("=" * 78)
    rows = run_campaign("E7", cells)

    per = {reg: summarise([r for r in rows if r.get("register") == reg])
           for reg in registers}

    print(f"\n  {'register':<9} {'n':>3} {'A decomp':>9} {'B contam':>9} "
          f"{'C confirm':>10} {'D escal':>8} {'closure':>8} {'mean writes':>12}")
    for reg, s in per.items():
        print(f"  {reg:<9} {s['n_ok']:>3} {str(s['stage_A']):>9} {str(s['stage_B']):>9} "
              f"{str(s['stage_C']):>10} {str(s['stage_D']):>8} "
              f"{str(s['circuit_closure']):>8} {str(s['mean_policy_calls']):>12}")

    def counts(reg, key):
        ok = [r for r in rows if r.get("register") == reg and not r.get("error")]
        y = sum(bool(r.get(key)) for r in ok)
        return y, len(ok) - y

    tests = {}
    for key, label in (("stage_A_decomposed", "decomposition"),
                       ("circuit_closed", "circuit closure")):
        sa, sb = counts("staged", key)
        da, db = counts("direct", key)
        na, nb = counts("null", key)
        tests[label] = {
            "staged_vs_direct_p": fisher(sa, sb, da, db),
            "staged_vs_null_p": fisher(sa, sb, na, nb),
            "staged": f"{sa}/{sa+sb}", "direct": f"{da}/{da+db}", "null": f"{na}/{na+nb}"}
        print(f"\n  {label}: staged {sa}/{sa+sb}  direct {da}/{da+db}  null {na}/{na+nb}")
        print(f"     Fisher exact  staged vs direct p = {tests[label]['staged_vs_direct_p']}")
        print(f"                   staged vs null   p = {tests[label]['staged_vs_null_p']}")

    payload = {"experiment": "E7", "backend": a.backend, "model": a.model,
               "trials_per_register": a.n,
               "note": ("target value is identical (60 Mbps) in the staged and direct arms, so "
                        "any difference between them is attributable to the register and not to "
                        "the magnitude requested"),
               "per_register": per, "significance": tests, "rows": rows}
    p = save("E7_register", payload)
    print(f"\n  -> {p}")


if __name__ == "__main__":
    main()
