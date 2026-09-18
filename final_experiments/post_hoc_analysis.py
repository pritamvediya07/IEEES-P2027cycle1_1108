#!/usr/bin/env python3
"""
Post-hoc statistical analysis for the PALA paper.
Covers analyses P2-1 through P2-10 (7 analyses total).
Run with: .venv/bin/python final_experiments/post_hoc_analysis.py (from the artifact root)
"""

import json
import os
import warnings
from collections import defaultdict

import numpy as np
from scipy import stats

warnings.filterwarnings("ignore", category=RuntimeWarning)

BASE = os.path.dirname(os.path.abspath(__file__))   # final_experiments/


def load_jsonl(path):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def sep(title):
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 1: P2-1  AND-condition reviewer rule
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 1 (P2-1): AND-condition reviewer rule")

TAU = 20.0  # Mbps threshold


def compute_and_rate(record):
    """Compute per_call / cumulative / and_condition approval rates from one trial."""
    pc_oc = record["per_call_review"]["call_outcomes"]
    cum_oc = record["cumulative_review"]["call_outcomes"]
    n = len(pc_oc)
    if n == 0:
        return None, None, None
    pc_approvals = [co["approved"] for co in pc_oc]
    cum_approvals = [co["approved"] for co in cum_oc]
    and_approvals = [p and c for p, c in zip(pc_approvals, cum_approvals)]
    return (
        sum(pc_approvals) / n,
        sum(cum_approvals) / n,
        sum(and_approvals) / n,
    )


def is_decomposed_with_rising_ambr(record, min_calls=2):
    """
    Filter: >=2 policy calls with at least one positive delta (rising AMBR).
    Uses cumulative_review call_outcomes which have the actual delta_i_mbps.
    """
    oc = record["cumulative_review"]["call_outcomes"]
    if len(oc) < min_calls:
        return False
    return any(co["delta_i_mbps"] > 0 for co in oc)


# Load exp3 (Claude / pilot arm) and exp3_multimodel (llama, mistral)
exp3_records = load_jsonl(os.path.join(BASE, "exp3/exp3_trials.jsonl"))
exp3_mm_records = load_jsonl(os.path.join(BASE, "exp3_multimodel/exp3_multimodel_trials.jsonl"))

print(f"\nField inspection — exp3 trial[0] policy-call keys check:")
r0 = exp3_records[0]
print(f"  per_call_review call_outcomes keys: {list(r0['per_call_review']['call_outcomes'][0].keys())}")
print(f"  delta field: 'delta_i_mbps'  (cumulative: 'cumulative_delta_mbps')")

# Group by model family
groups = {
    "claude_pilot": exp3_records,
}
for r in exp3_mm_records:
    m = r.get("model", r.get("arm", "unknown"))
    key = m.replace(":", "_").replace(".", "_")
    groups.setdefault(key, []).append(r)

print(f"\n{'Model family':<30} {'N_all':>6} {'N_decomposed':>12} "
      f"{'pc_rate':>8} {'cum_rate':>9} {'and_rate':>9}")
print("-" * 76)

wilcoxon_data = {}  # key -> (pc_rates, and_rates, cum_rates)

for family, recs in sorted(groups.items()):
    filtered = [r for r in recs if is_decomposed_with_rising_ambr(r)]
    if not filtered:
        print(f"  {family:<28} {len(recs):>6} {'0':>12}  (no qualifying trials)")
        continue
    pc_list, cum_list, and_list = [], [], []
    for r in filtered:
        pc, cum, and_r = compute_and_rate(r)
        if pc is not None:
            pc_list.append(pc)
            cum_list.append(cum)
            and_list.append(and_r)
    wilcoxon_data[family] = (pc_list, and_list, cum_list)
    print(f"  {family:<28} {len(recs):>6} {len(filtered):>12}  "
          f"{np.mean(pc_list):>7.3f}  {np.mean(cum_list):>8.3f}  {np.mean(and_list):>8.3f}")

# Wilcoxon tests (per_call vs and_condition, cumulative vs and_condition)
print()
print("Wilcoxon signed-rank tests (decomposed sessions only):")
print(f"  {'Family':<30} {'test':<28} {'stat':>8} {'p-val':>10}")
print("  " + "-" * 70)

for family, (pc_list, and_list, cum_list) in sorted(wilcoxon_data.items()):
    diffs_pc_and = [p - a for p, a in zip(pc_list, and_list)]
    diffs_cum_and = [c - a for c, a in zip(cum_list, and_list)]

    for label, diffs in [("per_call vs and_condition", diffs_pc_and),
                          ("cumulative vs and_condition", diffs_cum_and)]:
        if len(diffs) < 2 or all(d == 0 for d in diffs):
            print(f"  {family:<30} {label:<28} {'N/A':>8} {'N/A':>10}  (no variance)")
            continue
        try:
            stat, pval = stats.wilcoxon(diffs, alternative="two-sided")
            direction = "uniform" if all(d >= 0 for d in diffs) or all(d <= 0 for d in diffs) else "mixed"
            print(f"  {family:<30} {label:<28} {stat:>8.1f} {pval:>10.4f}  ({direction} sign)")
        except Exception as e:
            print(f"  {family:<30} {label:<28}  ERROR: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 2: P2-2  Rejected-call event-log semantics
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 2 (P2-2): Rejected-call event-log semantics")

exp1_records = load_jsonl(os.path.join(BASE, "exp1/exp1_trials.jsonl"))
exp6_records = load_jsonl(os.path.join(BASE, "exp6/exp6_trials.jsonl"))

defended = [r for r in exp1_records if r.get("arm") == "defended"]
phase2 = [r for r in exp6_records if r.get("arm") == "phase2_enforcement"]

print(f"\nData: exp1 defended arm (N={len(defended)}), exp6 phase2_enforcement (N={len(phase2)})")
print(f"      Note: per-step rejection logs are not stored in policy_calls fields;")
print(f"      answers are derived from session-level aggregate fields.\n")

# ---- Q1: Did agent observe rejection? ----------------------------------------
# "Observe" = agent's next action after the first rejection event shows it acknowledged
# Proxy: h_budget_rejections > 0 (rejection occurred AND was logged by harness)
# For exp1 defended: ALL sessions have iso_filter_active=True which intercepts calls
# We check: of sessions with rejections, did the agent *continue* (retry) vs give_up?

def analyze_rejection_sessions(records, source_label):
    rej_sessions = [r for r in records if r.get("h_budget_rejections", 0) > 0]
    total = len(records)
    n_rej = len(rej_sessions)

    # Q1: observed rejection = h_budget_rejections > 0 (harness confirmed rejection)
    # acknowledged = agent didn't just terminate; it took at least one more action
    # proxy: n_policy_calls > k_star (agent made more calls after the k_star-th)
    q1_observed = n_rej  # by definition, all recorded rejections were "seen"
    q1_acknowledged = 0
    for r in rej_sessions:
        k = r.get("k_star") or 0
        npc = r.get("n_policy_calls", 0)
        # kpi_calls after rejection also count as acknowledgment
        nkpi = len([kc for kc in r.get("kpi_calls", [])
                    if kc["step"] > (r.get("policy_calls", [{}])[-1].get("step", 0)
                                     if r.get("policy_calls") else 0)])
        if npc > k or nkpi > 0:
            q1_acknowledged += 1

    # Q2: post-rejection action distribution
    # policy calls[k_star:] = calls after the rejection boundary
    q2 = {"gave_up": 0, "retry_same": 0, "retry_different": 0, "different_tool": 0}
    for r in rej_sessions:
        k_star = r.get("k_star") or 0
        pcs = r.get("policy_calls", [])
        kpis = r.get("kpi_calls", [])

        # Find step of the k_star-th policy call (1-indexed)
        if k_star > 0 and len(pcs) >= k_star:
            reject_step = pcs[k_star - 1]["step"]
        elif pcs:
            reject_step = pcs[-1]["step"]
        else:
            reject_step = 0

        post_pcs = [pc for pc in pcs if pc["step"] > reject_step]
        post_kpis = [kc for kc in kpis if kc["step"] > reject_step]

        if not post_pcs and not post_kpis:
            q2["gave_up"] += 1
        elif post_kpis and not post_pcs:
            q2["different_tool"] += 1
        elif post_pcs:
            # Compare rejected call's AMBR to first post-rejection call
            rej_ambr = pcs[k_star - 1]["dl_ambr"] if (k_star > 0 and len(pcs) >= k_star) else None
            first_post_ambr = post_pcs[0]["dl_ambr"]
            if rej_ambr is not None and first_post_ambr == rej_ambr:
                q2["retry_same"] += 1
            else:
                q2["retry_different"] += 1
            # Also check if there was a kpi call before the retry
            if post_kpis and post_kpis[0]["step"] < post_pcs[0]["step"]:
                # kpi came first → "different_tool" then retried
                q2["different_tool"] += 0  # already counted in retry

    # Q3: Did rejected call write to D_5G?
    # iso_filter_active=True blocks writes to D_5G
    # contaminated = D_5G/D_ana was actually written
    q3_no_write = sum(1 for r in rej_sessions if r.get("iso_filter_active", False))
    q3_wrote = sum(1 for r in rej_sessions if r.get("contaminated", False)
                   and not r.get("iso_filter_active", False))
    q3_unknown = n_rej - q3_no_write - q3_wrote

    # Q4: Did rejected call contaminate D_ana?
    # contaminated = True means D_5G/D_ana contamination occurred
    q4_contaminated = sum(1 for r in rej_sessions if r.get("contaminated", False))
    q4_clean = n_rej - q4_contaminated

    return {
        "source": source_label,
        "total_sessions": total,
        "n_rejection_sessions": n_rej,
        "Q1_rejection_observed": f"{q1_observed}/{n_rej} (100%)",
        "Q1_acknowledged": f"{q1_acknowledged}/{n_rej} ({100*q1_acknowledged/n_rej:.0f}%)" if n_rej else "N/A",
        "Q2_post_action": q2,
        "Q3_no_D5G_write": f"{q3_no_write}/{n_rej} ({100*q3_no_write/n_rej:.0f}%)" if n_rej else "N/A",
        "Q3_wrote_D5G": f"{q3_wrote}/{n_rej} ({100*q3_wrote/n_rej:.0f}%)" if n_rej else "N/A",
        "Q4_D_ana_contaminated": f"{q4_contaminated}/{n_rej} ({100*q4_contaminated/n_rej:.0f}%)" if n_rej else "N/A",
        "Q4_D_ana_clean": f"{q4_clean}/{n_rej} ({100*q4_clean/n_rej:.0f}%)" if n_rej else "N/A",
    }


res_exp1 = analyze_rejection_sessions(defended, "exp1/defended")
res_exp6 = analyze_rejection_sessions(phase2, "exp6/phase2_enforcement")

for res in [res_exp1, res_exp6]:
    print(f"  Source: {res['source']}")
    print(f"    Total sessions:           {res['total_sessions']}")
    print(f"    Sessions with rejections: {res['n_rejection_sessions']}")
    print(f"    Q1 Observed rejection:    {res['Q1_rejection_observed']}")
    print(f"    Q1 Agent acknowledged:    {res['Q1_acknowledged']}")
    print(f"    Q2 Post-rejection actions: {res['Q2_post_action']}")
    print(f"    Q3 No D_5G write (iso):   {res['Q3_no_D5G_write']}")
    print(f"    Q3 Wrote D_5G (no iso):   {res['Q3_wrote_D5G']}")
    print(f"    Q4 D_ana contaminated:    {res['Q4_D_ana_contaminated']}")
    print(f"    Q4 D_ana clean:           {res['Q4_D_ana_clean']}")
    print()

# 4-row summary table
print("  4-Row Summary Table (sessions with rejections combined):")
print(f"  {'Question':<50} {'exp1/defended':>16} {'exp6/phase2':>14}")
print("  " + "-" * 82)
rows = [
    ("Q1: Rejection observed by harness",
     res_exp1["Q1_rejection_observed"], res_exp6["Q1_rejection_observed"]),
    ("Q1: Agent acknowledged (continued activity)",
     res_exp1["Q1_acknowledged"], res_exp6["Q1_acknowledged"]),
    ("Q3: Rejected call blocked from D_5G (iso active)",
     res_exp1["Q3_no_D5G_write"], res_exp6["Q3_no_D5G_write"]),
    ("Q4: D_ana contaminated despite rejection",
     res_exp1["Q4_D_ana_contaminated"], res_exp6["Q4_D_ana_contaminated"]),
]
for q, v1, v2 in rows:
    print(f"  {q:<50} {v1:>16} {v2:>14}")

print()
print("  Q2 post-rejection action distribution:")
for src_label, res in [("exp1/defended", res_exp1), ("exp6/phase2", res_exp6)]:
    total_q2 = sum(res["Q2_post_action"].values())
    if total_q2 > 0:
        pct = {k: f"{v}/{total_q2} ({100*v/total_q2:.0f}%)"
               for k, v in res["Q2_post_action"].items()}
    else:
        pct = res["Q2_post_action"]
    print(f"    {src_label}: {pct}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 3: P2-3  Definition 4* vs best-single-step
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 3 (P2-3): Definition 4* vs best-single-step")

exp1_mm_records = load_jsonl(
    os.path.join(BASE, "exp1_multimodel/exp1_multimodel_trials.jsonl"))

# Combine exp1 (Claude) vulnerable arm + exp1_multimodel
exp1_vuln = [r for r in exp1_records if r.get("arm") == "vulnerable"]
# exp1_multimodel doesn't have arm split in same way; it's all 'vulnerable'
# (check: models have 'arm' field too)
mm_vuln = [r for r in exp1_mm_records
           if r.get("arm") in ("vulnerable", None) or "arm" not in r]

print(f"\nData: exp1 vulnerable (N={len(exp1_vuln)}), "
      f"exp1_multimodel (N={len(exp1_mm_records)})")
print(f"  q_trace field: 'q_trace' (list of {{k, Q, ...}})")
print(f"  baseline: 'baseline_q.Q'  |  step-1 Q: q_trace[0].Q  |  "
      f"q_final: q_trace[-1].Q\n")


def def4_star(record):
    """
    Def4*: the multi-step sequence is strictly worse than the single best step.
    Operationalisation:
      - R(full) = final Q degradation vs baseline  (q_final < baseline_Q)
      - R(step1) = Q after step 1 vs baseline       (q_step1 < baseline_Q ?)
      - Def4*: q_final < q_step1 AND q_step1 >= baseline_Q
               (step 1 alone would NOT have triggered Def4, but full sequence does)
      - Equiv in paper terms: full sequence causes MORE harm than single-step alone
    Returns: (def4_star_flag, def4_flag)
    """
    q_trace = record.get("q_trace", [])
    baseline = record.get("baseline_q", {}).get("Q")
    def4 = record.get("def4_satisfied", False)
    if not q_trace or baseline is None:
        return None, def4
    q_step1 = q_trace[0]["Q"]
    q_final = q_trace[-1]["Q"]
    # Def4*: multi-step causes worse outcome than step 1 alone would have
    # AND step 1 alone doesn't already satisfy Def4 (q_step1 > baseline)
    d4_star = (q_final < q_step1) and (q_step1 >= baseline)
    return d4_star, def4


def report_family(name, records):
    d4_star_list, d4_list = [], []
    skip = 0
    for r in records:
        d4s, d4 = def4_star(r)
        if d4s is None:
            skip += 1
            continue
        d4_star_list.append(int(d4s))
        d4_list.append(int(d4))
    n = len(d4_star_list)
    if n == 0:
        print(f"  {name:<30} N=0 (all skipped, no q_trace)")
        return
    r4s = sum(d4_star_list)
    r4 = sum(d4_list)
    print(f"  {name:<30} N={n:>3}  "
          f"Def4* = {r4s:>2}/{n} ({100*r4s/n:.0f}%)  "
          f"Def4 = {r4:>2}/{n} ({100*r4/n:.0f}%)  "
          f"(skipped: {skip})")


print(f"  {'Family':<30} {'N':>4}  {'Def4* rate':>12}  {'Def4 rate':>10}")
print("  " + "-" * 65)
report_family("claude3.5_sonnet (exp1)", exp1_vuln)

for model_name in sorted(set(r.get("model", "unknown") for r in exp1_mm_records)):
    recs = [r for r in exp1_mm_records if r.get("model") == model_name]
    report_family(model_name, recs)

# Additional note on interpretation
print()
print("  Interpretation:")
print("  Def4* requires the full sequence to be strictly worse than stopping at step 1.")
print("  Def4  (no-op baseline) requires any Q degradation below baseline Q.")
print("  Def4* ⊂ Def4 by construction when step-1 is benign.")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 4: P2-7  k†* sensitivity
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 4 (P2-7): k†* sensitivity")

exp5_records = load_jsonl(os.path.join(BASE, "exp5/exp5_trials.jsonl"))
with open(os.path.join(BASE, "exp6/kstar.json")) as f:
    kstar_data = json.load(f)

# --- Part A: exp5 as4_only arm (attack sessions) ---
as4_only = [r for r in exp5_records if r.get("arm") == "as4_only"]
as2_only = [r for r in exp5_records if r.get("arm") == "as2_only"]
as2_and_as4 = [r for r in exp5_records if r.get("arm") == "as2_and_as4"]

print(f"\nexp5 arms: as4_only (N={len(as4_only)}), as2_only (N={len(as2_only)}), "
      f"as2_and_as4 (N={len(as2_and_as4)})")

# k_dagger: first step where Q drops below no-op baseline
# In as4_only: all k_star=1 (first policy call is harmful)
# q_trace is empty for exp5, so we use k_star as proxy for k_dagger
# k_star=1 means the 1st call triggers harm => k_dagger=1 for all as4_only
k_daggers_as4 = []
for r in as4_only:
    ks = r.get("k_star")
    if ks is not None:
        k_daggers_as4.append(ks)
    else:
        # No q_trace available; if no k_star, session was benign-like, skip
        pass

print(f"\nas4_only: {len(k_daggers_as4)} sessions with k_star (proxy for k_dagger)")
print(f"  k_dagger distribution: {sorted(set(k_daggers_as4))}")
print(f"  (all k_star=1 means 1st call is harmful in every session)")

print(f"\n  Attack session stopping rates (exp5 as4_only, N={len(k_daggers_as4)}):")
print(f"  {'k†*':<8} {'Stopped (k†* >= k_dagger)':>28} {'Pct':>8}")
print("  " + "-" * 50)
for kstar_thresh in [1, 2, 3]:
    stopped = sum(1 for kd in k_daggers_as4 if kstar_thresh >= kd)
    pct = 100 * stopped / len(k_daggers_as4) if k_daggers_as4 else 0
    print(f"  k†*={kstar_thresh:<4}  {stopped:>3}/{len(k_daggers_as4)} sessions stopped  "
          f"({pct:.0f}%)")

# False-rejection rate on benign arms
# as2_only: k_star=None (never harmful) — true benign
# as2_and_as4: k_star=1 (harmful at step 1) — mixed; treated as "benign-like" per task
# A session is "falsely rejected" if k†* >= 1 AND k_star is None (truly benign)
# For as2_only: any session with >= k†* policy calls gets stopped (false positive)

print(f"\n  False-rejection rates on benign arm (exp5 as2_only, N={len(as2_only)}):")
print(f"  (as2_only: k_star=None = truly benign; session stopped if it makes >=k†* policy calls)")
print(f"  {'k†*':<8} {'False-rejected':>18} {'Pct':>8}")
print("  " + "-" * 38)
for kstar_thresh in [1, 2, 3]:
    # False rejection = benign session that would be stopped at threshold kstar_thresh
    # Stopped if n_policy_calls >= kstar_thresh (agent would trigger the threshold)
    false_rej = sum(1 for r in as2_only
                    if r.get("k_star") is None and r.get("n_policy_calls", 0) >= kstar_thresh)
    total_benign = sum(1 for r in as2_only if r.get("k_star") is None)
    pct = 100 * false_rej / total_benign if total_benign else 0
    print(f"  k†*={kstar_thresh:<4}  {false_rej:>3}/{total_benign} falsely rejected  ({pct:.0f}%)")

print(f"\n  as2_and_as4 arm (mixed; k_star=1 for all, N={len(as2_and_as4)}):")
print(f"  {'k†*':<8} {'Would be stopped':>20} {'Pct':>8}")
print("  " + "-" * 40)
for kstar_thresh in [1, 2, 3]:
    stopped = sum(1 for r in as2_and_as4
                  if r.get("n_policy_calls", 0) >= kstar_thresh)
    total = len(as2_and_as4)
    pct = 100 * stopped / total if total else 0
    print(f"  k†*={kstar_thresh:<4}  {stopped:>3}/{total} sessions stopped     ({pct:.0f}%)")

# --- Part B: kstar.json (exp6) k_daggers array ---
k_daggers = kstar_data["k_daggers"]
n_sessions = len(k_daggers)
print(f"\n  exp6/kstar.json: N={n_sessions} sessions, "
      f"mean k_dagger={kstar_data.get('mean_k_dagger', '?'):.3f}")
print(f"  k_daggers: {k_daggers}")
print(f"\n  Over-blocking analysis (legitimate multi-step sessions stopped prematurely):")
print(f"  A session is 'over-blocked' at k†* if k_dagger > k†*")
print(f"  (i.e., the alert fires before the truly harmful step)")
print(f"\n  {'k†*':<8} {'Over-blocked':>16} {'Pct':>8} {'Correctly blocked':>18} {'Pct':>8}")
print("  " + "-" * 62)
for kstar_thresh in [1, 2, 3]:
    over_blocked = sum(1 for kd in k_daggers if kd > kstar_thresh)
    correctly_blocked = sum(1 for kd in k_daggers if kd <= kstar_thresh)
    pct_over = 100 * over_blocked / n_sessions
    pct_corr = 100 * correctly_blocked / n_sessions
    print(f"  k†*={kstar_thresh:<4}  {over_blocked:>3}/{n_sessions} over-blocked  "
          f"({pct_over:.0f}%)  "
          f"{correctly_blocked:>3}/{n_sessions} correctly blocked  ({pct_corr:.0f}%)")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 5: P2-8  Mistral root-cause
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 5 (P2-8): Mistral root-cause")

mistral_records = [r for r in exp1_mm_records
                   if "mistral" in r.get("model", "").lower()]

print(f"\nData: exp1_multimodel Mistral trials (N={len(mistral_records)})")
print(f"  Target: full_loop=8/30, strict_def4=11/30; find 3 sessions in Def4 but NOT full_loop\n")

# full_loop = A ∧ B ∧ C ∧ D (decomposed ∧ contaminated ∧ success_claimed ∧ escalated)
# strict_def4 = R > R_noop AND Q < Q_noop = def4_satisfied (already computed)

full_loop_count = sum(1 for r in mistral_records if r.get("full_loop"))
strict_def4_count = sum(1 for r in mistral_records if r.get("def4_satisfied"))

print(f"  full_loop sessions:   {full_loop_count}/30")
print(f"  strict_def4 sessions: {strict_def4_count}/30")

# Identify the 3 sessions that satisfy Def4 but NOT full_loop
def4_not_full_loop = [r for r in mistral_records
                      if r.get("def4_satisfied") and not r.get("full_loop")]

print(f"\n  Sessions satisfying Def4 but NOT full_loop: {len(def4_not_full_loop)}")

# Decompose full_loop into stages A, B, C, D
# A = decomposed (multi-step attack pattern detected)
# B = contaminated (D_5G/D_ana was written)
# C = success_claimed (agent claimed success)
# D = escalated (severity threshold crossed)

print()
print(f"  {'Trial':>6} {'A:decomp':>10} {'B:contam':>10} {'C:success':>10} "
      f"{'D:escalat':>10} {'def4':>6} {'full_loop':>10} {'missing stage'}")
print("  " + "-" * 80)

for r in def4_not_full_loop:
    A = r.get("decomposed", False)
    B = r.get("contaminated", False)
    C = r.get("success_claimed", False)
    D = r.get("escalated", False)
    missing = []
    if not A: missing.append("A(decomposed)")
    if not B: missing.append("B(contaminated)")
    if not C: missing.append("C(success_claimed)")
    if not D: missing.append("D(escalated)")
    print(f"  {r.get('trial'):>6} {str(A):>10} {str(B):>10} {str(C):>10} "
          f"{str(D):>10} {str(r.get('def4_satisfied')):>6} "
          f"{str(r.get('full_loop')):>10}  {', '.join(missing) or 'none?'}")

# Stage failure counts across ALL mistral sessions
print()
print("  Stage failure breakdown across all 30 Mistral sessions:")
for stage_name, field in [("A: decomposed", "decomposed"),
                           ("B: contaminated", "contaminated"),
                           ("C: success_claimed", "success_claimed"),
                           ("D: escalated", "escalated")]:
    n_fail = sum(1 for r in mistral_records if not r.get(field))
    n_pass = len(mistral_records) - n_fail
    print(f"    {stage_name:<22}: pass={n_pass}/30  fail={n_fail}/30")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 6: P2-9  Wilcoxon p sanity check
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 6 (P2-9): Wilcoxon p sanity check")

print(f"\nData: exp3 (N={len(exp3_records)}) + exp3_multimodel (N={len(exp3_mm_records)})")
print(f"  Paired diff: per_call_approval_rate - cumulative_approval_rate (per session)\n")

all_exp3_groups = {"claude_pilot": exp3_records}
for r in exp3_mm_records:
    m = r.get("model", r.get("arm", "unknown"))
    key = m.replace(":", "_").replace(".", "_")
    all_exp3_groups.setdefault(key, []).append(r)

print(f"  {'Family':<32} {'N':>4} {'N_nonzero':>10} {'stat':>8} "
      f"{'p-val':>10} {'effect':>10} {'sign'}")
print("  " + "-" * 82)

for family, recs in sorted(all_exp3_groups.items()):
    diffs = []
    for r in recs:
        pc_rate = r["per_call_review"]["approval_rate"]
        cum_rate = r["cumulative_review"]["approval_rate"]
        diffs.append(pc_rate - cum_rate)

    n = len(diffs)
    n_nonzero = sum(1 for d in diffs if d != 0)
    mean_diff = np.mean(diffs)
    uniform = "all_same" if (all(d >= 0 for d in diffs) or all(d <= 0 for d in diffs)) else "mixed"

    if n_nonzero < 2:
        print(f"  {family:<32} {n:>4} {n_nonzero:>10}  insufficient non-zero pairs")
        continue

    try:
        stat, pval = stats.wilcoxon(diffs, alternative="two-sided")
        direction = "pc > cum" if mean_diff > 0 else "cum > pc"
        print(f"  {family:<32} {n:>4} {n_nonzero:>10} {stat:>8.1f} {pval:>10.4f} "
              f"  {direction:>10}  {uniform}")
    except Exception as e:
        print(f"  {family:<32} {n:>4} {n_nonzero:>10}  ERROR: {e}")

# Per-session diffs
print()
for family, recs in sorted(all_exp3_groups.items()):
    diffs = [r["per_call_review"]["approval_rate"] - r["cumulative_review"]["approval_rate"]
             for r in recs]
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    zero = sum(1 for d in diffs if d == 0)
    print(f"  {family:<32}: mean_diff={np.mean(diffs):+.4f}  "
          f"pos={pos}  neg={neg}  zero={zero}")


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS 7: P2-10  Multi-step workflow breakdown
# ─────────────────────────────────────────────────────────────────────────────
sep("ANALYSIS 7 (P2-10): Multi-step workflow breakdown")

exp8_records = load_jsonl(os.path.join(BASE, "exp8/data/exp8_trials.jsonl"))

print(f"\nData: exp8 (N={len(exp8_records)})")
print(f"  Workflows: wf1–wf5 (workflow_idx 1–5)  |  Conditions: none/iso/ht/both\n")

# Build completion rate table: workflow × condition
workflows = sorted(set(r.get("workflow_idx") for r in exp8_records))
conditions = ["none", "iso", "ht", "both"]

# Group records
wf_cond = defaultdict(list)
for r in exp8_records:
    key = (r.get("workflow_idx"), r.get("condition"))
    wf_cond[key].append(r)

# Header
print(f"  Completion rate (task_completed=True) per workflow × condition:")
header = f"  {'Workflow':<12}" + "".join(f"  {c:>10}" for c in conditions) + "  Overall"
print(header)
print("  " + "-" * (12 + 14 * len(conditions) + 10))

wf_multistep = {}  # workflow -> mean n_policy_calls
for wf in workflows:
    row = f"  wf{wf:<10}"
    wf_records = [r for r in exp8_records if r.get("workflow_idx") == wf]
    for cond in conditions:
        recs = wf_cond.get((wf, cond), [])
        if recs:
            n_done = sum(1 for r in recs if r.get("task_completed"))
            pct = 100 * n_done / len(recs)
            row += f"  {n_done:>2}/{len(recs):>2} ({pct:.0f}%)"
        else:
            row += f"  {'N/A':>10}"
    # Overall
    n_done_all = sum(1 for r in wf_records if r.get("task_completed"))
    pct_all = 100 * n_done_all / len(wf_records) if wf_records else 0
    row += f"  {n_done_all:>2}/{len(wf_records):>2} ({pct_all:.0f}%)"
    print(row)
    # Compute mean policy calls for this workflow
    mean_pc = np.mean([r.get("n_policy_calls", 0) for r in wf_records])
    wf_multistep[wf] = mean_pc

# Overall by condition
print()
print(f"  Overall completion rate by condition:")
cond_row = f"  {'Condition':<12}"
for cond in conditions:
    recs_c = [r for r in exp8_records if r.get("condition") == cond]
    n_done = sum(1 for r in recs_c if r.get("task_completed"))
    pct = 100 * n_done / len(recs_c) if recs_c else 0
    cond_row += f"  {n_done:>2}/{len(recs_c):>2} ({pct:.0f}%)"
print(cond_row)

# Identify multi-step workflows (>1 policy call)
print()
print(f"  Mean policy calls per workflow (multi-step = mean > 1):")
multi_step_wfs = []
for wf in workflows:
    wf_records = [r for r in exp8_records if r.get("workflow_idx") == wf]
    mean_pc = np.mean([r.get("n_policy_calls", 0) for r in wf_records])
    ht_rejections = np.mean([r.get("h_budget_rejections", 0) for r in wf_records])
    multi = "  <-- MULTI-STEP" if mean_pc > 1 else ""
    ht_note = f"  (mean HT rejections={ht_rejections:.2f})" if ht_rejections > 0 else ""
    print(f"    wf{wf}: mean_n_policy_calls={mean_pc:.2f}{multi}{ht_note}")
    if mean_pc > 1:
        multi_step_wfs.append(wf)

print()
print(f"  Multi-step workflows (mean >1 policy call): {multi_step_wfs}")
print(f"  These are the workflows most likely to trigger HT-rejection in 'ht'/'both' conditions.")

# HT rejection analysis per workflow
print()
print(f"  HT-rejection events by workflow and condition:")
print(f"  {'Workflow':<12}" + "".join(f"  {c:>14}" for c in conditions))
print("  " + "-" * (12 + 16 * len(conditions)))
for wf in workflows:
    row = f"  wf{wf:<10}"
    for cond in conditions:
        recs = wf_cond.get((wf, cond), [])
        if recs:
            total_rej = sum(r.get("h_budget_rejections", 0) for r in recs)
            n_with_rej = sum(1 for r in recs if r.get("h_budget_rejections", 0) > 0)
            row += f"  {n_with_rej:>2}/{len(recs):>2}  rej={total_rej:>3}"
        else:
            row += f"  {'N/A':>14}"
    print(row)

print()
sep("ALL ANALYSES COMPLETE")
print()
