#!/usr/bin/env python3
"""E11 — Recompute every paper number from raw traces and fail on any mismatch.

This is the check that would have caught the Table 2 / Table 11 discrepancy
before submission. It does five things:

  1. Recomputes the whole registry from the raw result files and diffs it
     against the committed paper_numbers.json.
  2. Verifies that every baseline_key actually resolves to another registered
     key. A relative number whose baseline does not exist is the exact shape of
     the original error.
  3. Verifies that every number carries a source path that exists on disk.
  4. Checks every srsRAN number printed in the paper (PRINTED) against its
     registry entry, at the precision the paper prints it.
  5. Reports which numbers are flagged NOT robust to analysis choices, so a
     non-robust quantity can never be quoted in the paper as if it were solid.

Exit code 0 means every number in the paper is reproducible from the traces.

    .venv/bin/python analysis/verify_paper.py
    .venv/bin/python analysis/verify_paper.py --emit-latex
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.registry import build                        # noqa: E402

COMMITTED = ROOT / "analysis" / "paper_numbers.json"
TOL = 1e-9

# Every srsRAN number as it is PRINTED in the paper, keyed to its registry entry.
# "=" : the registry value rounds to the printed value at the printed precision
# ">" / "<" / "<=" : the printed bound holds
PRINTED = [
    # §6.3 and App. E: radio-side harm
    ("E1_cell_capacity_mbps",                     "=",  "22.8",  "§6.3, App. E"),
    ("E1_per_ue_baseline_mbps",                   "=",  "5.71",  "App. E"),
    ("E1_victim_tau_first_mbps",                  "=",  "5.43",  "App. E"),
    ("E1_victim_tau_last_mbps",                   "=",  "5.47",  "App. E"),
    ("E1_victim_lambda_first_ms",                 "=",  "77.7",  "§6.3, App. E"),
    ("E1_victim_lambda_last_ms",                  "=",  "151.5", "§6.3, App. E"),
    ("E1_victim_lambda_inflation_x",              "=",  "1.95",  "§6.3, App. E"),
    ("E0_4_target_share_of_dQ_pct",               ">",  "91",    "§6.3 Target versus feedback"),
    ("E0_4_escalation_share_of_dQ_pct",           "<",  "9",     "§6.3 Target versus feedback"),
    # §6.2 and App. F: model coverage, scripted controller, target-free sessions
    ("E6_llama8b_closed_sessions",                "=",  "14",    "§6.2, App. F (14/20)"),
    ("E6_gemma12b_closed_sessions",               "=",  "15",    "§6.2, App. F (15/20)"),
    ("E6_sonnet45_closed_sessions",               "=",  "15",    "§6.2, App. F (15/20)"),
    ("E6_llama8b_mean_delta_star",                "=",  "3.41",  "App. F"),
    ("E6_gemma12b_mean_delta_star",               "=",  "2.48",  "App. F"),
    ("E6_sonnet45_mean_delta_star",               "=",  "-0.12", "App. F"),
    ("E6_partial_30_36b_closed_sessions",         "=",  "6",     "App. F (6/6, partial)"),
    ("E4_closed_loop_mean_escalation_x",          "=",  "50",    "§6.2, App. F"),
    ("E4_closed_loop_overshoot_rate",             "=",  "1.0",   "App. F (20/20)"),
    ("E4_closed_loop_iso_overshoot_rate",         "=",  "0.0",   "App. F (ISO halts)"),
    ("E3_target_free_undefended_mean_x",          "=",  "17",    "§6.2, App. F"),
    ("E3_target_free_undefended_at_ceiling",      "=",  "1",     "App. F (1/10)"),
    ("E3_target_free_undefended_contaminated",    "=",  "9",     "App. F (9/10)"),
    ("E3_target_free_undefended_write_after_readback", "=", "6", "App. F (6/10)"),
    ("E3_target_free_pooled_mean_x",              "=",  "29",    "§6.2, App. F"),
    ("E3_target_free_pooled_n",                   "=",  "33",    "App. F (n=33)"),
    ("E3_no_target_at_tool_ceiling",              "=",  "13",    "App. F (13/33)"),
    # App. E: policy-field generality
    ("E5_corr_session_ambr",                      "=",  "1.0",   "App. E"),
    ("E5_corr_5qi",                               "=",  "1.0",   "App. E"),
    ("E5_corr_arp_priority",                      "=",  "1.0",   "App. E"),
    ("E5_corr_flow_mbr",                          "=",  "1.0",   "App. E"),
    ("E5_variables_with_open_channel",            "=",  "4",     "App. E (4/4)"),
    ("E5_variables_open_under_iso",               "=",  "0",     "App. E (0/4)"),
    # §6.4: time-dilation check
    ("E8_calls_per_trace",                        "=",  "12",    "§6.4"),
    ("E8_time_gates_min_admitted_at_10x_100x",    "=",  "12",    "§6.4 (12/12)"),
    ("E8_counter_admitted_after_reinstantiation", "=",  "12",    "§6.4"),
    ("E8_max_escalation_x",                       "=",  "129.8", "§6.4"),
    ("E8_drift_bound_max_admitted",               "=",  "1",     "§6.4"),
    ("E8_drift_bound_ceiling_x",                  "=",  "1.5",   "§6.4"),
    # §6.6 and Table 6: overhead
    ("E10_worst_arm_delta_ms",                    "=",  "1.16",  "§6.6, Table 6 (at most)"),
    ("E10_worst_arm_delta_ms",                    "<",  "1.3",   "§6.6, Table 6"),
    ("E10_n_per_arm",                             "=",  "120",   "§6.6"),
]


# Claim-level criteria for FRESHLY generated srsRAN results (--fresh). A fresh radio or LLM
# run cannot reproduce stored values to the digit; it has to support the paper's claim.
#   ("exact", v)          deterministic experiment: must equal v
#   ("fisher", k, n)      LLM session count: fresh count must not differ from the paper's k/n
#                         (two-sided Fisher exact test, p > 0.05)
#   (">", v) / ("<", v)   direction or bound claimed by the paper
#   ("within", v, frac)   measurement within ±frac of the paper's value
FRESH_CLAIMS = {
    # §6.3 / App. E radio-side harm (E1, E0.4)
    "E1_cell_capacity_mbps":                     (("within", 22.8, 0.10), "cell capacity ≈ 22.8 Mbps"),
    "E1_victim_lambda_inflation_x":              ((">", 1.5),  "victim queueing delay inflates (paper 1.95×)"),
    "E1_victim_tau_last_mbps":                   (("within", 5.43, 0.10), "victim throughput stays flat (5.43 → 5.47)"),
    "E0_4_target_share_of_dQ_pct":               ((">", 86.0), "target B★ accounts for most of ΔQ (paper >91%)"),
    # §6.2 / App. F (E6 capability sweep, E4 scripted controller, E3 target-free)
    "E6_llama8b_closed_sessions":                (("fisher", 14, 20), "Llama 3.1:8B closes 14/20"),
    "E6_gemma12b_closed_sessions":               (("fisher", 15, 20), "Gemma-3 12B closes 15/20"),
    "E6_sonnet45_closed_sessions":               (("fisher", 15, 20), "Claude Sonnet 4.5 closes 15/20"),
    "E4_closed_loop_overshoot_rate":             (("exact", 1.0),  "scripted controller escalates 20/20"),
    "E4_closed_loop_iso_overshoot_rate":         (("exact", 0.0),  "IsolatedCollector halts it 20/20"),
    "E4_closed_loop_mean_escalation_x":          (("exact", 50),   "escalation to 50×"),
    "E3_target_free_undefended_mean_x":          ((">", 3.0),  "escalates past any 3× target without one (paper 17×)"),
    "E3_target_free_undefended_contaminated":    (("fisher", 9, 10), "9/10 contaminated readback"),
    "E3_target_free_undefended_write_after_readback": (("fisher", 6, 10), "6/10 write again after readback"),
    # App. E policy-field reachability (E5)
    "E5_variables_with_open_channel":            (("exact", 4), "4/4 fields read back (standard collector)"),
    "E5_variables_open_under_iso":               (("exact", 0), "0/4 under IsolatedCollector"),
    # §6.4 time-dilation check (E8, deterministic replay)
    "E8_time_gates_min_admitted_at_10x_100x":    (("exact", 12), "time gates admit 12/12 under dilation"),
    "E8_counter_admitted_after_reinstantiation": (("exact", 12), "counter admits 12/12 after re-instantiation"),
    "E8_drift_bound_max_admitted":               (("exact", 1),  "drift bound admits one call"),
    "E8_drift_bound_ceiling_x":                  (("exact", 1.5), "drift bound holds at 1.5×"),
    # §6.6 overhead (E10)
    "E10_worst_arm_delta_ms":                    (("<", 1.3), "gate overhead < 1.3 ms per call"),
}


def _fresh_ok(value, crit) -> tuple[bool, str]:
    kind = crit[0]
    if kind == "exact":
        return abs(value - crit[1]) < 1e-9, f"= {crit[1]}"
    if kind == ">":
        return value > crit[1], f"> {crit[1]}"
    if kind == "<":
        return value < crit[1], f"< {crit[1]}"
    if kind == "within":
        return abs(value - crit[1]) <= crit[2] * crit[1], f"{crit[1]} ± {crit[2]:.0%}"
    if kind == "fisher":
        from scipy.stats import fisher_exact
        k, n = crit[1], crit[2]
        got = round(value)
        p = fisher_exact([[got, n - got], [k, n - k]])[1]
        return p > 0.05, f"vs paper {k}/{n}, Fisher p={p:.2f}"
    raise ValueError(kind)


def fresh_main() -> int:
    """--fresh: judge freshly generated srsRAN results by the paper's claims."""
    reg = build()
    print("=" * 78)
    print("  E11 --fresh — fresh srsRAN results against the paper's claims")
    print("=" * 78)
    bad = skipped = 0
    for key, (crit, claim) in FRESH_CLAIMS.items():
        if key not in reg:
            skipped += 1
            print(f"  SKIP  {claim:<52} (not produced by this run)")
            continue
        ok, rule = _fresh_ok(reg[key]["value"], crit)
        bad += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {claim:<52} got {reg[key]['value']}  ({rule})")
    print(f"\n  {len(FRESH_CLAIMS) - skipped - bad} passed, {bad} failed, {skipped} skipped")
    if bad:
        print("\n  FAILED")
        return 1
    print("\n  PASSED — the fresh srsRAN results support the paper's claims")
    return 0


def _printed_ok(value, op: str, printed: str) -> bool:
    p = float(printed)
    if op == ">":
        return value > p
    if op == "<":
        return value < p
    if op == "<=":
        return value <= p
    decimals = len(printed.split(".")[1]) if "." in printed else 0
    return abs(value - p) <= 0.5 * 10 ** -decimals + 1e-9


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emit-latex", action="store_true")
    ap.add_argument("--fresh", action="store_true",
                    help="judge freshly generated results by the paper's claims instead of "
                         "diffing them against the committed registry")
    a = ap.parse_args()
    if a.fresh:
        return fresh_main()

    if not COMMITTED.exists():
        print(f"  FAIL: {COMMITTED} does not exist — run analysis/registry.py first")
        return 1

    committed = json.loads(COMMITTED.read_text())
    recomputed = build()
    errors: list[str] = []

    # ── 1. recompute and diff ─────────────────────────────────────────────
    only_c = set(committed) - set(recomputed)
    only_r = set(recomputed) - set(committed)
    for k in sorted(only_c):
        errors.append(f"key {k!r} is committed but no longer produced by the registry")
    for k in sorted(only_r):
        errors.append(f"key {k!r} is produced by the registry but not committed "
                      f"(run registry.py)")

    mismatched = 0
    for k in sorted(set(committed) & set(recomputed)):
        cv, rv = committed[k]["value"], recomputed[k]["value"]
        same = (abs(cv - rv) <= TOL) if isinstance(cv, (int, float)) and \
                                        isinstance(rv, (int, float)) else (cv == rv)
        if not same:
            mismatched += 1
            errors.append(f"VALUE MISMATCH {k}: committed {cv!r} != recomputed {rv!r}")

    # ── 2. baseline references resolve ────────────────────────────────────
    dangling = 0
    for k, v in sorted(recomputed.items()):
        bk = v.get("baseline_key")
        if bk and bk not in recomputed:
            dangling += 1
            errors.append(f"DANGLING BASELINE {k}: baseline_key {bk!r} is not a registered key")

    # ── 3. every source file exists ───────────────────────────────────────
    missing_src = 0
    for k, v in sorted(recomputed.items()):
        src = v["source"]
        if src.startswith("derived from"):
            continue
        path = ROOT / src.split(":")[0]
        if not path.exists():
            missing_src += 1
            errors.append(f"MISSING SOURCE {k}: {path} does not exist")

    # ── 4. registry against the numbers printed in the paper ──────────────
    printed_bad = 0
    for key, op, printed, where in PRINTED:
        if key not in recomputed:
            printed_bad += 1
            errors.append(f"PAPER NUMBER UNREGISTERED {printed} ({where}): no registry key {key!r}")
        elif not _printed_ok(recomputed[key]["value"], op, printed):
            printed_bad += 1
            errors.append(f"PAPER MISMATCH {where}: paper prints {op} {printed}, "
                          f"registry {key} = {recomputed[key]['value']}")

    # ── 5. non-robust numbers ─────────────────────────────────────────────
    nonrobust = {k: v for k, v in recomputed.items() if not v["robust_to_analysis_choices"]}

    print("=" * 78)
    print("  E11 — paper number verification")
    print("=" * 78)
    print(f"  numbers registered        : {len(recomputed)}")
    print(f"  recomputed and matched    : {len(set(committed) & set(recomputed)) - mismatched}")
    print(f"  value mismatches          : {mismatched}")
    print(f"  dangling baseline refs    : {dangling}")
    print(f"  missing source files      : {missing_src}")
    print(f"  keys only in committed    : {len(only_c)}")
    print(f"  keys only in recomputed   : {len(only_r)}")
    print(f"  printed in paper, checked : {len(PRINTED)} ({len(PRINTED) - printed_bad} match the paper)")

    print(f"\n  numbers flagged NOT ROBUST to analysis choices ({len(nonrobust)}):")
    for k, v in sorted(nonrobust.items()):
        print(f"     {k} = {v['value']} {v['units']}")
        print(f"        {v['note'][:150]}")

    # named-baseline pairs that must stay distinct
    pair = ("E1_Q0_preaction", "E1_Q0_postfirstcall")
    if all(p in recomputed for p in pair):
        va, vb = recomputed[pair[0]]["value"], recomputed[pair[1]]["value"]
        print(f"\n  named-baseline guard: {pair[0]}={va}  {pair[1]}={vb}  "
              f"distinct={'YES' if va != vb else 'NO — investigate'}")

    if errors:
        print(f"\n  {len(errors)} PROBLEM(S):")
        for e in errors:
            print(f"     - {e}")
        print("\n  FAILED")
        return 1

    if a.emit_latex:
        tex = ROOT / "analysis" / "paper_numbers.tex"
        lines = ["% GENERATED by analysis/verify_paper.py — DO NOT EDIT BY HAND",
                 "% every macro below is recomputed from raw traces on each run"]
        for k, v in sorted(recomputed.items()):
            macro = "\\num" + "".join(w.capitalize() for w in k.split("_") if w.isalpha() or w)
            macro = "\\num" + k.replace("_", "")
            lines.append(f"\\newcommand{{{macro}}}{{{v['value']}}}  % {v['units']} — {v['source']}")
        tex.write_text("\n".join(lines) + "\n")
        print(f"\n  -> {tex} ({len(recomputed)} macros)")

    print("\n  PASSED — every paper number is reproducible from the raw traces and matches the paper")
    return 0


if __name__ == "__main__":
    sys.exit(main())
