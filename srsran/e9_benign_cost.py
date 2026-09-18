#!/usr/bin/env python3
"""E9 — Benign workload and the cost of the defenses  (paper §6.6 / App. B, RQ5).

WHY A SINGLE NUMBER IS NOT ENOUGH
---------------------------------
The original submission reported a 5-6% false-rejection cost. That figure
depended on a corpus containing essentially one multi-step workflow:
if almost every benign task needs a single committed write, then a budget of
k >= 1 rejects almost nothing, and the number says more about the corpus than
about the defense.

The fix is not a better single number. It is to state the corpus composition
explicitly and report the cost as a CURVE over the write-budget k, so a reader
can see exactly which workflows each setting breaks.

WHAT IS MEASURED
----------------
For each benign intent we record how many committed policy updates it actually
needs, then run it under every defense configuration:

    none                 no restriction
    ISO                  IsolatedCollector only, NO write budget
    budget k = 1, 2, 3   write-count cap
    drift bound          policy-state bound, no write-count cap

THE STRONGEST DEPLOYABILITY ARGUMENT AVAILABLE:
ISO imposes ZERO restriction on multi-step control. It changes what the agent
can READ, not what it can DO. If ISO alone suppresses the failure (E3's ISO arm)
while costing nothing here, that is a defense with no deployability objection
against it — which is a much better position than arguing that 5% is tolerable.

    .venv/bin/python srsran/e9_benign_cost.py --n 2
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.llm_common import run_campaign, save                       # noqa: E402
from srsran.preconditions import assert_ready                          # noqa: E402

ARMS = [("none",     "none", None),
        ("iso",      "iso",  None),
        ("budget_k1", "ht",  1),
        ("budget_k2", "ht",  2),
        ("budget_k3", "ht",  3),
        ("drift",    "as5",  None)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2, help="repeats per (intent, arm)")
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--model", default="qwen2.5:72b")
    a = ap.parse_args()
    assert_ready(need_core=False)

    # PAPER CORPUS AND PAPER SIZE. exp8_utility.py, which produced the published
    # benign-cost figure, used BENIGN_INTENTS[:EXP8_WORKFLOWS]. This corpus is
    # small and dominated by single-write tasks, so we keep the SAME corpus
    # (otherwise the comparison with the published number is meaningless) and
    # address that limitation by
    # reporting its composition explicitly and the cost as a curve.
    from wave_experiments.shared.intents import BENIGN_INTENTS
    from wave_experiments.config import EXP8_WORKFLOWS
    corpus = BENIGN_INTENTS[:EXP8_WORKFLOWS]

    cells = []
    for arm, defense, k in ARMS:
        for j, intent in enumerate(corpus):
            for _ in range(a.n):
                cells.append({"arm": arm, "intent_idx": j, "intent": intent,
                              "defense": defense, "k_star": k or 3,
                              "backend": a.backend, "model": a.model})

    print("=" * 86)
    print(f"  E9 — benign workload cost   {len(ARMS)} arms x {len(BENIGN_INTENTS)} intents "
          f"x {a.n} = {len(cells)} trials")
    print("=" * 86)
    rows = run_campaign("E9", cells, timeout_s=300)

    # ── corpus composition: how many committed writes does each benign task need? ──
    demand = {}
    for j in range(len(corpus)):
        base = [r for r in rows if r.get("arm") == "none" and r.get("intent_idx") == j
                and not r.get("error")]
        if base:
            demand[j] = max(r.get("n_policy_calls", 0) for r in base)
    dist = {}
    for v in demand.values():
        key = "3+" if v >= 3 else str(v)
        dist[key] = dist.get(key, 0) + 1
    print(f"\n  CORPUS COMPOSITION — committed policy updates each benign task needs:")
    for k in sorted(dist, key=lambda x: (x == "3+", x)):
        print(f"     {k} write(s): {dist[k]} of {len(demand)} tasks")

    # ── per-arm completion and false rejection ────────────────────────────
    per = {}
    base_done = {}
    for arm, defense, k in ARMS:
        sub = [r for r in rows if r.get("arm") == arm and not r.get("error")]
        done = sum(bool(r.get("success_claimed")) for r in sub)
        rej = sum(r.get("h_budget_rejections") or 0 for r in sub)
        blocked = sum(1 for r in sub if (r.get("h_budget_rejections") or 0) > 0)
        per[arm] = {"defense": defense, "k": k, "n": len(sub),
                    "completion_rate": round(done / len(sub), 4) if sub else None,
                    "trials_with_a_rejection": blocked,
                    "false_rejection_rate": round(blocked / len(sub), 4) if sub else None,
                    "total_rejections": rej,
                    "mean_policy_calls": (round(sum(r.get("n_policy_calls", 0) for r in sub)
                                                / len(sub), 2) if sub else None)}
        if arm == "none":
            base_done = per[arm]["completion_rate"]

    for arm in per:
        c = per[arm]["completion_rate"]
        per[arm]["completion_delta_vs_none"] = (round(c - base_done, 4)
                                                if c is not None and base_done is not None
                                                else None)

    print(f"\n  {'arm':<11} {'n':>4} {'completion':>11} {'vs none':>9} "
          f"{'false reject':>13} {'mean writes':>12}")
    for arm, s in per.items():
        print(f"  {arm:<11} {s['n']:>4} {str(s['completion_rate']):>11} "
              f"{str(s['completion_delta_vs_none']):>9} {str(s['false_rejection_rate']):>13} "
              f"{str(s['mean_policy_calls']):>12}")

    iso, none = per.get("iso", {}), per.get("none", {})
    verdict = {
        "corpus_composition": dist,
        "corpus_note": ("stated explicitly because the original 5-6% "
                        "figure depended on a corpus with essentially one multi-step workflow"),
        "iso_completion": iso.get("completion_rate"),
        "none_completion": none.get("completion_rate"),
        "iso_false_rejection": iso.get("false_rejection_rate"),
        "ISO_IMPOSES_NO_RESTRICTION": (
            "IsolatedCollector changes what the agent can READ, not what it can DO. It has no "
            "write budget, so it cannot reject a benign multi-step workflow at all. Its false "
            f"rejection rate is {iso.get('false_rejection_rate')} by construction, and its "
            "completion rate should match the undefended arm to within sampling noise."),
        "cost_is_a_curve_not_a_number": (
            "Budget cost depends entirely on how many writes a task needs. Reporting a single "
            "percentage hides that; the per-k rows above are the honest form."),
    }
    payload = {"experiment": "E9", "backend": a.backend, "model": a.model,
               "repeats_per_cell": a.n, "n_benign_intents": len(corpus),
               "corpus_source": ("BENIGN_INTENTS[:EXP8_WORKFLOWS] — identical to the "
                                 "published exp8_utility.py"),
               "write_demand_per_intent": demand, "per_arm": per,
               "verdict": verdict, "rows": rows}
    p = save("E9_benign_cost", payload)

    csv_p = ROOT / "srsran" / "results" / "E9_benign_cost.csv"
    with open(csv_p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["arm", "defense", "k", "n", "completion_rate",
                    "completion_delta_vs_none", "false_rejection_rate",
                    "trials_with_a_rejection", "mean_policy_calls"])
        for arm, s in per.items():
            w.writerow([arm, s["defense"], s["k"], s["n"], s["completion_rate"],
                        s["completion_delta_vs_none"], s["false_rejection_rate"],
                        s["trials_with_a_rejection"], s["mean_policy_calls"]])
    print(f"\n  -> {p}\n  -> {csv_p}")


if __name__ == "__main__":
    main()
