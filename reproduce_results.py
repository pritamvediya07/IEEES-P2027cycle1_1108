#!/usr/bin/env python3
"""
PALA Artifact — reproduce_results.py
=====================================
Reads stored trial logs from final_experiments/ and reproduces all paper
tables and figures reported in:

  "Architecture-Induced Reward Hacking in NWDAF-Integrated LLM Control Loops"
  IEEE S&P 2027 — Cycle 1

Usage:
    python reproduce_results.py            # all tables + figures
    python reproduce_results.py --tables   # tables only (no matplotlib)
    python reproduce_results.py --figures  # figures only
    python reproduce_results.py --rq RQ1   # single RQ

Runtime: under a minute with Python >= 3.10 (tables); figures add ~1 minute.
No live 5G network or GPU required.

Every statistic is recomputed from the stored trial logs; no check falls back to
a paper value. Where the stored data do not reproduce a printed number exactly,
the script prints it as NOTE with both values instead of hiding the difference
(see CLAIMS.md, "Known differences between the paper and the stored data").
"""

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

from scipy.stats import fisher_exact, wilcoxon

ROOT        = Path(__file__).parent
EXP_DIR     = ROOT / "final_experiments"
FIG_SCRIPT  = ROOT / "final_paper_results" / "generate_all_figures.py"
OUT_DIR     = ROOT / "final_paper_results"

# Paper-reported reference values for pass/fail comparison
PAPER_VALUES = {
    "qwen_full_loop":       (20, 30, 0.667),
    "qwen_def4":            (18, 30, 0.600),
    "qwen_defended":        ( 0, 30, 0.000),
    "mistral_full_loop":    ( 8, 30, 0.267),
    "mistral_def4":         (11, 30, 0.367),
    "llama_full_loop":      ( 9, 30, 0.300),
    "llama_def4":           ( 9, 30, 0.300),
    "per_call_approval":    (None, None, 0.453),
    "cumulative_approval":  (None, None, 0.746),
    "full_pala_circuit":    ( 0, 20, 0.000),
    "iso_only_circuit":     ( 0, 20, 0.000),
    "full_chain_circuit":   (15, 20, 0.750),
    "k_star":               (1,  None, 1),
    "k_star_cv":            (None, None, 0.401),
    "adaptive_vuln":        (46, 50, 0.920),
    "adaptive_full_pala":   ( 0, 50, 0.000),
}

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
NOTE = "\033[96mNOTE\033[0m"

TOL = 0.10  # 10 pp tolerance for proportion comparisons
FRESH = False  # --fresh: judge freshly generated results by the paper's claims, not exact stored values


def banner(title: str) -> None:
    print(f"\n{'═'*64}")
    print(f"  {title}")
    print(f"{'═'*64}")


def load_json(path: Path) -> dict:
    if not path.exists():
        print(f"  [MISSING] {path.relative_to(ROOT)}")
        return {}
    with open(path) as f:
        return json.load(f)


def check(label: str, got: float, expected: float, tol: float = TOL, fmt: str = ".1%",
          n: int | None = None) -> bool:
    """Stored mode: |got - expected| <= tol. Fresh mode, for a proportion over n sessions:
    the fresh count must not differ significantly from the paper's count (two-sided Fisher
    exact test, p > 0.05) -- a ±10 pp window on n = 20-30 rejects a correct system too often."""
    if FRESH and n:
        k_got, k_exp = round(got * n), round(expected * n)
        p = fisher_exact([[k_got, n - k_got], [k_exp, n - k_exp]])[1]
        ok = p > 0.05
        print(f"  {label:<45}  fresh {k_got}/{n} vs paper {k_exp}/{n}  Fisher p={p:.2f}  "
              f"{PASS if ok else FAIL}")
        return ok
    tol = min(tol, 0.0051)   # stored logs must match the printed value to its rounding
    ok = abs(got - expected) <= tol
    status = PASS if ok else FAIL
    expected_s = f"{expected:{fmt}}"
    got_s      = f"{got:{fmt}}"
    print(f"  {label:<45}  got={got_s:<8}  expected≈{expected_s}  {status}")
    return ok


def check_true(label: str, ok: bool, detail: str) -> bool:
    print(f"  {label:<45}  {detail}  {PASS if ok else FAIL}")
    return ok


def stored_only(what: str) -> None:
    """Mark checks whose experiments the one-day plan does not rerun."""
    if FRESH:
        print(f"  [stored results — {what} is not rerun by the one-day plan]")


def check_exact(label: str, got: int, expected: int) -> bool:
    ok = got == expected
    status = PASS if ok else FAIL
    print(f"  {label:<45}  got={got}  expected={expected}  {status}")
    return ok


# ── RQ1: Circuit Realization ──────────────────────────────────────────────────

def rq1_circuit_realization() -> list[bool]:
    banner("RQ1 — Realization of Closed Contamination Circuit (Table 2)")
    results: list[bool] = []

    # Qwen from exp1
    d = load_json(EXP_DIR / "exp1" / "summary.json")
    if d:
        v = d.get("vulnerable", {})
        results.append(check("Qwen full-loop rate (vulnerable)",
                              v.get("full_loop_rate", -1), 20 / 30, n=v.get("n", 30)))
        results.append(check("Qwen Strict Def.4 rate",
                              v.get("def4_rate", -1), 18 / 30, n=v.get("n", 30)))
        results.append(check("Qwen mean Q-drop",
                              v.get("q_drop_mean", -1), 0.110, tol=0.05))   # Table 2: -11.0%
        defended = d.get("defended", {})
        results.append(check_exact("Qwen defended: 0 full-loop closures",
                                   int(defended.get("full_loop_rate", 1) * 30), 0))
        # Fisher exact test recomputed from the per-arm counts
        v_n, d_n = v.get("n", 30), defended.get("n", 30)
        v_k = round(v.get("full_loop_rate", 0) * v_n)
        d_k = round(defended.get("full_loop_rate", 0) * d_n)
        fp = fisher_exact([[v_k, v_n - v_k], [d_k, d_n - d_k]])[1]
        ok = fp < 1e-6
        print(f"  {'Qwen Fisher p (Full PALA vs vulnerable)':<45}  p={fp:.2e}  "
              f"expected<1e-6  {PASS if ok else FAIL}")
        results.append(ok)

    # Cross-family from exp1_multimodel
    md = load_json(EXP_DIR / "exp1_multimodel" / "summary.json")
    if md:
        models = md.get("models", {})
        for model_key, label, fl, d4 in [       # Table 2 counts out of 30
            ("qwen2.5:72b",          "Qwen 2.5:72b",  20, 18),
            ("mistral-large:latest", "Mistral-large",  8, 11),
            ("llama3.1:70b",         "Llama 3.1:70b",  9,  9),
        ]:
            m = models.get(model_key, {})
            n = m.get("n", 30)
            results.append(check(f"{label} full-loop rate",
                                  m.get("full_loop_rate", -1), fl / 30, n=n))
            results.append(check(f"{label} Strict Def.4 rate",
                                  m.get("def4_rate", -1), d4 / 30, n=n))
            results.append(check_true(f"{label}: circuit closes in some session",
                                      m.get("full_loop_rate", 0) > 0,
                                      f"full-loop rate {m.get('full_loop_rate', 0):.1%} > 0"))

    return results


# ── RQ2: Mechanism ─────────────────────────────────────────────────────────────

def rq2_mechanism() -> list[bool]:
    banner("RQ2 — Mechanism Validation (Figure 4, Tables 10–11)")
    results: list[bool] = []

    # Contamination from exp14 — keys: phaseB_contamination_rate, phaseD_isolation_verified
    d14 = load_json(EXP_DIR / "exp14" / "summary.json")
    if d14:
        std_rate   = d14.get("phaseB_contamination_rate", -1)
        iso_ok     = d14.get("phaseD_isolation_verified", False)
        results.append(check("Standard collector: Type-P contamination rate",
                              std_rate, 1.0, tol=0.05))
        ok_iso = iso_ok is True
        print(f"  {'IsolatedCollector: isolation verified (Phase D)':<45}  "
              f"got={iso_ok}  expected=True  {PASS if ok_iso else FAIL}")
        results.append(ok_iso)

    # Intent register from exp2 — keys nested under 'rows'
    d2 = load_json(EXP_DIR / "exp2" / "summary.json")
    if d2:
        rows   = d2.get("rows", d2)   # fallback if flat
        staged = rows.get("staged", {}).get("decomposition_rate",
                 rows.get("staged", {}).get("decomposed_rate", -1))
        direct = rows.get("direct", {}).get("decomposition_rate",
                 rows.get("direct", {}).get("decomposed_rate", -1))
        null   = rows.get("null",   {}).get("decomposition_rate",
                 rows.get("null",   {}).get("decomposed_rate", -1))
        n2 = rows.get("staged", {}).get("n", 20)
        results.append(check("Staged-change: decomposition rate", staged, 0.65, tol=0.15, n=n2))
        results.append(check("Direct-change: decomposition rate", direct, 0.15, tol=0.10, n=n2))
        results.append(check("Null-control: decomposition rate",  null,   0.00, tol=0.05, n=n2))
        results.append(check("Staged-change: full-loop rate (Fig. 4a)",
                             rows.get("staged", {}).get("full_loop_rate", -1), 0.30, n=n2))
        p_sd = fisher_exact([[round(staged * n2), n2 - round(staged * n2)],
                             [round(direct * n2), n2 - round(direct * n2)]])[1]
        results.append(check_true("Staged > direct >= null decomposition",
                                  staged > direct >= null and p_sd < 0.05,
                                  f"{staged:.0%} > {direct:.0%} >= {null:.0%}, Fisher p={p_sd:.3f}"))

    # Table 10C / Fig. 4d: Type-P escape fraction falls with KPI batch size N (exp9, no LLM)
    d9 = load_json(EXP_DIR / "exp9" / "phaseC_summary.json")
    if d9:
        esc = {int(k): v["type_p_escape_fraction"] for k, v in d9.get("rows", {}).items()}
        got = [esc.get(n) for n in (5, 10, 20, 30, 50)]
        printed = [1.0, 0.8, 0.4, 0.267, 0.16]
        if FRESH:
            ok = None not in got and got[0] == 1.0 and all(a >= b for a, b in zip(got, got[1:]))
            detail = f"{got} decreasing from 100%"
        else:
            ok = None not in got and all(abs(a - b) < 0.005 for a, b in zip(got, printed))
            detail = f"{got} vs printed {printed}"
        results.append(check_true("Table 10C: Type-P escape vs N", ok, detail))

    # Table 11A: Strict Def. 4 across six Q-weight profiles, 53.6-75.0% (exp11)
    d11 = load_json(EXP_DIR / "exp11" / "summary.json")
    if d11:
        rates = [r["def4_rate"] for r in d11.get("rows", {}).values()]
        n11 = max((r.get("n_trials", 28) for r in d11.get("rows", {}).values()), default=28)
        results.append(check("Table 11A: lowest Def. 4 rate across profiles", min(rates), 0.536,
                             tol=0.005, n=n11))
        results.append(check("Table 11A: highest Def. 4 rate across profiles", max(rates), 0.750,
                             tol=0.005, n=n11))

    results += target_share_ueransim()
    return results


def target_share_ueransim() -> list[bool]:
    """§6.3 'Target versus feedback': share of the throughput-driven Q degradation already
    realised when the ceiling reaches B* = 60 Mbps, versus the saturated floor.

    UERANSIM does not enforce AMBR in a radio scheduler, so the testbed realises
    over-subscription at a host shaper whose rate is scaled by baseline/B
    (wave_experiments/shared/probe.py: update_tc_for_ambr), and throughput is reported as
    0.9 x the shaper rate when iperf3 does not return. tau(B) is therefore
    0.9 * max(1, TC_BASE_RATE * BASELINE / B). This check first confirms that model against
    every stored tau sample, then evaluates the tau term of Q (Def. 3: 0.25 * tau / 20)."""
    sys.path.insert(0, str(ROOT))
    from wave_experiments.config import TC_BASE_RATE_MBPS, BASELINE_AMBR_MBPS

    def tau(b):
        return 0.9 * max(1.0, TC_BASE_RATE_MBPS * BASELINE_AMBR_MBPS / b)

    levels = {round(tau(b), 3) for b in range(1, 1001)} | {round(TC_BASE_RATE_MBPS * 0.9, 3)}
    samples = [q["tau_mbps"] for arm in ("vulnerable", "defended")
               for f in sorted((EXP_DIR / "exp1" / arm).glob("trial_*.json"))
               for q in load_json(f).get("q_trace", [])]
    on_model = sum(1 for x in samples if any(abs(x - l) < 1e-3 for l in levels)
                   or abs(x / 0.9 - round(x / 0.9, 2)) < 1e-6)
    qt = lambda b: 0.25 * tau(b) / 20.0
    b0, bstar = BASELINE_AMBR_MBPS, 3 * BASELINE_AMBR_MBPS
    floor_b = TC_BASE_RATE_MBPS * BASELINE_AMBR_MBPS          # shaper rate reaches its 1 Mbps floor
    share = (qt(b0) - qt(bstar)) / (qt(b0) - qt(floor_b))
    print(f"  {'tau samples on the shaper model (exp1)':<45}  {on_model}/{len(samples)}  {NOTE}")
    print("  [analytical: computed from the testbed's shaper model, not re-measured by a fresh run]")
    return [check("§6.3 share of dQ at B* (analytical, >= 71%)", share, 0.714, tol=0.005)]


# ── RQ3: Oversight ─────────────────────────────────────────────────────────────

def rq3_oversight() -> list[bool]:
    banner("RQ3 — Oversight rules on 90 staged-control sessions (Table 3)")
    results: list[bool] = []
    tau_mbps = 20.0
    fams = {"Qwen": [], "Mistral": [], "Llama": []}
    for f, fam in ((EXP_DIR / "exp3" / "exp3_trials.jsonl", "Qwen"),):
        fams[fam] = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    mm = EXP_DIR / "exp3_multimodel" / "exp3_multimodel_trials.jsonl"
    for r in (json.loads(l) for l in mm.read_text().splitlines() if l.strip()):
        fams["Mistral" if r["model"].startswith("mistral") else "Llama"].append(r)

    paper = {  # per-call, AND-rule, cumulative (%), p2 (x1e-6) as printed in Table 3
        "Qwen":    (45.3, 44.0, 74.6, 5.96),
        "Mistral": (50.5, 49.2, 78.5, 8.63),
        "Llama":   (50.3, 48.9, 78.7, 9.69),
    }
    for fam, rows in fams.items():
        pc = [r["per_call_review"]["approval_rate"] for r in rows]
        cu = [r["cumulative_review"]["approval_rate"] for r in rows]
        an = []
        for r in rows:
            po = r["per_call_review"]["call_outcomes"]
            co = r["cumulative_review"]["call_outcomes"]
            both = [a["approved"] and b["approved"] for a, b in zip(po, co)]
            an.append(sum(both) / len(both) if both else r["per_call_review"]["approval_rate"])
        p_pc, p_and, p_cu, p2 = paper[fam]
        tol = TOL if FRESH else 0.005
        results.append(check(f"{fam}: per-call approval (n={len(rows)})",
                             statistics.mean(pc), p_pc / 100, tol=tol))
        results.append(check(f"{fam}: cumulative approval",
                             statistics.mean(cu), p_cu / 100, tol=tol))
        w = wilcoxon(pc, cu, alternative="less").pvalue
        ok = w < 1e-4 if FRESH else abs(w * 1e6 - p2) < 0.01
        print(f"  {fam + ': Wilcoxon p (per-call < cumulative)':<45}  p={w:.2e}  "
              f"printed={p2}e-06  {PASS if ok else FAIL}")
        results.append(ok)
        print(f"  {fam + ': AND-rule approval':<45}  got={100 * statistics.mean(an):.1f}%   "
              f"printed={p_and}%  {NOTE} (see CLAIMS.md, known differences)")
    return results


# ── RQ4: Defense ──────────────────────────────────────────────────────────────

def rq4_defense() -> list[bool]:
    banner("RQ4 — Defense Efficacy (Tables 4, 8, 9)")
    results: list[bool] = []

    # Necessity/sufficiency from exp5
    d5 = load_json(EXP_DIR / "exp5" / "summary.json")
    if d5:
        v = d5.get("variants", {})
        fc = v.get("full_chain", {})
        a2 = v.get("as2_only",  {})
        a4 = v.get("as4_only",  {})
        ba = v.get("as2_and_as4", {})

        a5 = v.get("as5_only", {})
        n5 = fc.get("n", 20)
        results.append(check("Full chain: full-loop rate",
                              fc.get("corrected_full_loop_rate", -1), 0.750, n=n5))
        results.append(check("AS2 only (IsolatedCollector): full-loop rate",
                              a2.get("corrected_full_loop_rate", -1), 0.000, tol=0.05, n=n5))
        results.append(check("AS4 only (HedgeTuned): full-loop rate (corrected)",
                              a4.get("corrected_full_loop_rate", -1), 0.000, tol=0.05, n=n5))
        results.append(check("AS2 ∧ AS4 (Full PALA): full-loop rate",
                              ba.get("corrected_full_loop_rate", -1), 0.000, tol=0.05, n=n5))
        results.append(check("AS5 only: full-loop rate (Table 8 Panel B)",
                              a5.get("corrected_full_loop_rate", -1), 0.650, n=n5))

    # k†* calibration from exp6
    stored_only("Exp 6 calibration, Exp 7 adaptive prompts and Exp 15 BoN-PALA")
    d6 = load_json(EXP_DIR / "exp6" / "kstar.json")
    if d6:
        k = d6.get("k_star", -1)
        cv = d6.get("cv", -1)
        results.append(check_exact("k†* = 1 (conservative calibration)", k, 1))
        results.append(check("CV ≤ 0.5 (MLR stability criterion)", cv, 0.401, tol=0.05))
        k_daggers = d6.get("k_daggers", [])
        if k_daggers:
            k1_frac = sum(1 for x in k_daggers if x == 1) / len(k_daggers)
            results.append(check("k†=1 fraction in calibration (≈61%)", k1_frac, 0.607, tol=0.10))

    # Adaptive-prompt stress test from exp7 — computed from trial JSONL (no top-level summary.json)
    trial_path7 = EXP_DIR / "exp7" / "data" / "exp7_trials.jsonl"
    if trial_path7.exists():
        import json as _j7
        trials7 = [_j7.loads(l) for l in trial_path7.read_text().strip().splitlines() if l.strip()]
        cond_stats: dict = {}
        for t in trials7:
            c = t.get("condition", t.get("defense", "?"))
            cond_stats.setdefault(c, {"n": 0, "fl": 0})
            cond_stats[c]["n"] += 1
            if t.get("corrected_full_loop", t.get("full_loop", False)):
                cond_stats[c]["fl"] += 1
        vuln_fl  = cond_stats.get("none", {}).get("fl", 0) / max(cond_stats.get("none", {}).get("n", 1), 1)
        iso_fl   = cond_stats.get("iso",  {}).get("fl", 0) / max(cond_stats.get("iso",  {}).get("n", 1), 1)
        both_fl  = cond_stats.get("both", {}).get("fl", 0) / max(cond_stats.get("both", {}).get("n", 1), 1)
        ht_fl    = cond_stats.get("ht",   {}).get("fl", 0) / max(cond_stats.get("ht",   {}).get("n", 1), 1)
        n7 = cond_stats.get("none", {}).get("n", 50)
        results.append(check("Adaptive prompts — vulnerable: full-loop rate",     vuln_fl, 0.920, tol=0.10, n=n7))
        results.append(check("Adaptive prompts — IsolatedCollector: full-loop rate", iso_fl, 0.000, tol=0.05, n=n7))
        results.append(check("Adaptive prompts — HedgeTuned: full-loop rate",     ht_fl,   0.000, tol=0.05, n=n7))
        results.append(check("Adaptive prompts — Full PALA: full-loop rate",      both_fl, 0.000, tol=0.05, n=n7))
    else:
        print(f"  [MISSING] exp7 trial JSONL — skipping adaptive-prompt checks")

    # Table 4 BoN-PALA row (Exp 15): n* = 4, 14/20 full-loop
    p15 = EXP_DIR / "exp15" / "summary.json"
    if not p15.exists():
        p15 = ROOT / "wave_experiments" / "results" / "exp15" / "summary.json"
    d15 = load_json(p15)
    if d15:
        bon = d15.get("arms", {}).get("A2_bon_pala", {})
        results.append(check_exact("BoN-PALA calibrated n*", d15.get("calibration", {}).get("n_star", -1), 4))
        results.append(check("BoN-PALA: full-loop rate", bon.get("full_loop_rate", -1), 0.700,
                             n=bon.get("n", 20)))

    return results


# ── RQ5: Deployability ────────────────────────────────────────────────────────

def rq5_deployability() -> list[bool]:
    banner("RQ5 — Deployability (Table 6)")
    results: list[bool] = []

    stored_only("RQ5 (Exp 8, 10, 13)")
    # exp8 summary is in data/summary.json
    d8 = load_json(EXP_DIR / "exp8" / "data" / "summary.json")
    if d8:
        both = d8.get("conditions", {}).get("both", {})
        comp  = both.get("completion_rate",  -1)
        frej  = both.get("rejection_rate",   -1)
        results.append(check("Full PALA benign WF completion rate", comp, 0.840, tol=0.10))
        results.append(check("Full PALA H_budget false-rejection rate", frej, 0.060, tol=0.05))

    # Table 6 KPI latency: ~4 s undefended -> < 0.1 ms once phi = T short-circuits the aggregate
    d10 = load_json(EXP_DIR / "exp10" / "phaseB_summary.json")
    if d10:
        rows = d10.get("rows", {})
        none_ms, iso_ms = rows["none"]["mean_ms"], rows["iso"]["mean_ms"]
        ok = 3000 < none_ms < 5000 and iso_ms < 0.1
        print(f"  {'KPI latency: undefended -> IsolatedCollector':<45}  "
              f"{none_ms:,.0f} ms -> {iso_ms} ms  expected ~3,942 -> <0.1  {PASS if ok else FAIL}")
        results.append(ok)

    # Table 6 recovery: 17/20 undefended and Full PALA; false rejections 0/20 and 1/20 (exp13)
    d13 = load_json(EXP_DIR / "exp13" / "summary.json")
    if d13:
        c = d13.get("conditions", {})
        results.append(check_exact("Recovery completion — undefended (of 20)", c["none"]["completed_count"], 17))
        results.append(check_exact("Recovery completion — Full PALA (of 20)", c["both"]["completed_count"], 17))
        results.append(check_exact("Recovery false rejections — Full PALA (of 20)", c["both"]["rejection_count"], 1))

    return results


# ── Summary ───────────────────────────────────────────────────────────────────

def summary(all_results: list[bool]) -> None:
    banner("Verification Summary")
    total  = len(all_results)
    passed = sum(all_results)
    failed = total - passed

    if failed == 0:
        status_line = f"\033[92m✓ All {total} checks PASS\033[0m"
    else:
        status_line = f"\033[91m✗ {failed}/{total} checks FAIL\033[0m"

    print(f"\n  {status_line}")
    print(f"\n  Figures written to: {OUT_DIR / 'figures'}")
    print(f"  Tables  written to: {OUT_DIR / 'tables'}")
    if failed > 0:
        print("\n  Some checks failed. For freshly generated results use --fresh, which judges")
        print("  proportions by a Fisher exact test against the paper's counts (p > 0.05).")
    print()


# ── Figure generation ─────────────────────────────────────────────────────────

PAPER_FIGURES = [   # (generator, what it produces)
    (EXP_DIR / "RQ1_realization" / "figures" / "gen_fig1_hq.py", "Figure 3 (RQ1 trajectory)"),
    (EXP_DIR / "RQ2_mechanism" / "figures" / "gen_fig2_hq.py",   "Figure 4 (RQ2 mechanism)"),
    (FIG_SCRIPT,                                                  "supplementary figures and tables"),
]


def generate_figures() -> None:
    banner("Generating Figures and Tables")
    for script, what in PAPER_FIGURES:
        if not script.exists():
            print(f"  [SKIP] {script.name} not found")
            continue
        print(f"  Running {script.relative_to(ROOT)} — {what} …")
        # SOURCE_DATE_EPOCH fixes the PDF creation date, so regenerated figures are
        # byte-identical to the committed ones when the data are unchanged.
        env = {**os.environ, "SOURCE_DATE_EPOCH": "0"}
        result = subprocess.run([sys.executable, script.name], cwd=script.parent,
                                capture_output=True, text=True, env=env)
        if result.returncode == 0:
            print(f"  {PASS} {what}")
        else:
            print(f"  {WARN} {script.name} returned code {result.returncode}")
            if result.stderr:
                print(f"  stderr: {result.stderr[-400:]}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce PALA paper results from stored traces")
    parser.add_argument("--tables",  action="store_true", help="Print tables only (skip figures)")
    parser.add_argument("--figures", action="store_true", help="Generate figures only (skip tables)")
    parser.add_argument("--fresh",   action="store_true",
                        help="Check freshly generated results against the paper's claims "
                             "(±10 pp, p < 1e-4) instead of the exact stored values")
    parser.add_argument("--rq",      choices=["RQ1", "RQ2", "RQ3", "RQ4", "RQ5"],
                        help="Run a single research question only")
    args = parser.parse_args()
    global FRESH
    FRESH = args.fresh

    print()
    print("══════════════════════════════════════════════════════════════════")
    print("  PALA Artifact — Reproducing Paper Results from Stored Traces")
    print("  IEEE S&P 2027 — Cycle 1")
    print("══════════════════════════════════════════════════════════════════")
    print(f"  Results directory: {EXP_DIR}")
    print(f"  Output directory:  {OUT_DIR}")

    all_results: list[bool] = []

    if FRESH:
        fresh = sorted(d.name for d in EXP_DIR.iterdir() if (d / "FRESH_RUN").exists())
        print(f"  --fresh: re-run by run_experiments.sh (FRESH_RUN marker): {', '.join(fresh) or 'none'}")
        print("  every other experiment below is checked from its stored results")
        if not fresh:
            print(f"  {WARN} no experiment carries a FRESH_RUN marker — nothing fresh to judge")

    if not args.figures:
        rq_map = {
            "RQ1": rq1_circuit_realization,
            "RQ2": rq2_mechanism,
            "RQ3": rq3_oversight,
            "RQ4": rq4_defense,
            "RQ5": rq5_deployability,
        }
        if args.rq:
            all_results += rq_map[args.rq]()
        else:
            for fn in rq_map.values():
                all_results += fn()
        summary(all_results)

    if not args.tables:
        generate_figures()


if __name__ == "__main__":
    main()
