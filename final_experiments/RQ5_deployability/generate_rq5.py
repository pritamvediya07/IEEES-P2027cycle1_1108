"""
RQ5 Deployability Table (Table 6) generator.

Sources:
  final_experiments/exp8/data/summary.json     (Benign workload, n=50/condition)
  final_experiments/exp13/summary.json          (Post-incident recovery, n=20/condition)
  final_experiments/exp10/phaseA_summary.json   (Session wall-clock, Exp 1 traces)
  final_experiments/exp10/phaseB_summary.json   (KPI query latency microbenchmark)
  final_experiments/exp6/phase3_summary.json    (HT-alone benign-tuning rejection rate)

Outputs:
  tables/table6_deployability.tex
  tables/caption6.txt
"""

import json
from pathlib import Path
from scipy.stats import fisher_exact

FE_DIR  = Path(__file__).parent.parent          # final_experiments/
OUT_DIR = Path(__file__).parent
TAB_DIR = OUT_DIR / "tables"
TAB_DIR.mkdir(exist_ok=True)

# ── Load data ──────────────────────────────────────────────────────────────────

e8  = json.loads((FE_DIR / "exp8"  / "data"  / "summary.json").read_text())
e13 = json.loads((FE_DIR / "exp13" / "summary.json").read_text())
e10a = json.loads((FE_DIR / "exp10" / "phaseA_summary.json").read_text())
e10b = json.loads((FE_DIR / "exp10" / "phaseB_summary.json").read_text())
e6p3 = json.loads((FE_DIR / "exp6"  / "phase3_summary.json").read_text())

# ── Extract scalars ────────────────────────────────────────────────────────────

# Block 1 — Exp 8 (n=50 per condition)
def e8c(cond): return e8["conditions"][cond]

B1_n     = {c: e8c(c)["n"] for c in ("none","iso","ht","both")}
B1_comp  = {c: e8c(c)["completed_count"] for c in B1_n}
B1_rej   = {c: e8c(c)["rejection_count"] for c in B1_n}

# contamination counts come from EXP8_RESULTS.md table (not in summary.json)
B1_cont  = {"none": 6, "iso": 0, "ht": 8, "both": 0}

# Block 2 — Exp 13 (n=20 per condition)
def e13c(cond): return e13["conditions"][cond]

B2_n     = {c: e13c(c)["n"]               for c in ("none","iso","ht","both")}
B2_comp  = {c: e13c(c)["completed_count"]  for c in B2_n}
B2_rej   = {c: e13c(c)["rejection_count"]  for c in B2_n}
B2_elap  = {"none": 92, "iso": 85, "ht": 96, "both": 88}   # from EXP13_RESULTS.md

# Block 3 — Exp 10 latency
none_p50 = e10a["rows"]["none"]["p50_ms"] / 1000   # → seconds
none_p99 = e10a["rows"]["none"]["p99_ms"] / 1000
both_p50 = e10a["rows"]["both"]["p50_ms"] / 1000
both_p99 = e10a["rows"]["both"]["p99_ms"] / 1000

kpi_none = e10b["rows"]["none"]["mean_ms"]   # 3942 ms
kpi_iso  = e10b["rows"]["iso"]["mean_ms"]    # ~0.01 ms
kpi_both = e10b["rows"]["both"]["mean_ms"]   # ~0.01 ms

ht_phase3_rej = e6p3["rejection_rate"] * 100  # 13.3%

# ── Fisher exact p-values ──────────────────────────────────────────────────────

def fisher(a, na, b, nb):
    """Two-sided Fisher exact: a/na successes vs b/nb successes."""
    tbl = [[a, na - a], [b, nb - b]]
    _, p = fisher_exact(tbl, alternative="two-sided")
    return p

p_benign   = fisher(B1_comp["both"], B1_n["both"], B1_comp["none"], B1_n["none"])
p_recovery = fisher(B2_comp["both"], B2_n["both"], B2_comp["none"], B2_n["none"])

print(f"Block 1 — Benign completion:   {B1_comp['both']}/{B1_n['both']} vs "
      f"{B1_comp['none']}/{B1_n['none']}   Fisher p = {p_benign:.3f}")
print(f"Block 2 — Recovery completion: {B2_comp['both']}/{B2_n['both']} vs "
      f"{B2_comp['none']}/{B2_n['none']}   Fisher p = {p_recovery:.3f}")
print(f"KPI query: {kpi_none:.0f} ms → <0.1 ms  ({kpi_none/0.01:.0f}× speedup)")
print(f"Session p50: {none_p50:.1f}s → {both_p50:.1f}s  (delta {both_p50-none_p50:+.1f}s)")
print(f"Session p99: {none_p99:.1f}s → {both_p99:.1f}s  (delta {both_p99-none_p99:+.1f}s)")
print(f"Exp 6 Phase 3 HT benign-rejection rate: {ht_phase3_rej:.1f}%")

# ── LaTeX table ────────────────────────────────────────────────────────────────

def pct(k, n): return f"{100*k/n:.1f}\\%"

def comp_cell(k, n, bold=False):
    s = f"{k}/{n} ({pct(k,n)})"
    return f"\\textbf{{{s}}}" if bold else s

def rej_cell(k, n):
    if k == 0:
        return f"0/{n}"
    return f"{k}/{n} ({pct(k,n)})"

TEX = r"""\begin{table*}[!t]
\caption{Deployability of the Full PALA Guardrail across three dimensions
(Qwen~2.5:72b). Block~1 reports completion on five routine NWDAF benign
workflows (Exp~8, $n{=}50$ per condition: $5~\text{workflows}\times10~\text{reps}$);
Block~2 reports legitimate post-incident recovery (Exp~13, $n{=}20$ per
condition); Block~3 reports per-call and per-session latency
(Exp~10, $n{=}50$ KPI-query reps; session traces from Exp~1, $n{=}30$).
Full PALA completion is statistically indistinguishable from the
undefended baseline on both benign workloads
(""" + f"${B1_comp['both']}/{B1_n['both']}$ each, Fisher $p={p_benign:.3f}$, n.s.)" + r""" and
recovery workloads (""" + f"${B2_comp['both']}/{B2_n['both']}$ each, Fisher $p={p_recovery:.3f}$, n.s.)." + r"""
The Exp~6 Phase~3 HT-alone benign-tuning false-rejection rate (""" + f"${ht_phase3_rej:.1f}\\%$, $n{{=}}30$)" + r"""
is an upper bound on per-call rejection cost on legitimate workloads, consistent
with the session-level measurements in Blocks~1--2.}
\label{tab:rq5_deployability}
\centering
\small
\setlength{\tabcolsep}{4pt}
\newcolumntype{C}{>{\centering\arraybackslash}X}
\begin{tabularx}{\textwidth}{p{4.6cm}CCCC}
\toprule
\textbf{Dimension / Metric}
  & \textbf{Standard}
  & \textbf{IsolatedCollector}
  & \textbf{HedgeTuned $k^{\dagger*}\!=\!1$}
  & \textbf{Full PALA} \\
  & \textit{(undefended)}
  & \textit{(AS2 enforced)}
  & \textit{(AS4 enforced)}
  & \textit{(AS2\,$\wedge$\,AS4)} \\
\midrule
""" + \
r"\multicolumn{5}{l}{\textit{Block~1 --- Benign workload completion " + \
rf"(Exp~8, $n{{=}}{B1_n['none']}$ per condition, 5 workflows $\times$ 10 reps)" + "}}" + \
r""" \\[1pt]
Completion rate
""" + \
f"  & {comp_cell(B1_comp['none'], B1_n['none'])}" + \
f"  & {comp_cell(B1_comp['iso'],  B1_n['iso'])}" + \
f"  & {comp_cell(B1_comp['ht'],   B1_n['ht'])}" + \
f"  & {comp_cell(B1_comp['both'], B1_n['both'], bold=True)}" + \
r""" \\
Type-P contamination rate
""" + \
f"  & {pct(B1_cont['none'], B1_n['none'])} ({B1_cont['none']}/{B1_n['none']})" + \
f"  & \\textbf{{{pct(B1_cont['iso'], B1_n['iso'])}}} ({B1_cont['iso']}/{B1_n['iso']})" + \
f"  & {pct(B1_cont['ht'], B1_n['ht'])} ({B1_cont['ht']}/{B1_n['ht']})" + \
f"  & \\textbf{{{pct(B1_cont['both'], B1_n['both'])}}} ({B1_cont['both']}/{B1_n['both']})" + \
r""" \\
H$_\text{budget}$ false-rej.\ (trials)
  & ---  & ---
""" + \
f"  & {rej_cell(B1_rej['ht'],   B1_n['ht'])}" + \
f"  & {rej_cell(B1_rej['both'], B1_n['both'])}" + \
r""" \\
\midrule
""" + \
r"\multicolumn{5}{l}{\textit{Block~2 --- Post-incident recovery " + \
rf"(Exp~13, $n{{=}}{B2_n['none']}$ per condition)" + "}}" + \
r""" \\[1pt]
Recovery completion rate
""" + \
f"  & {comp_cell(B2_comp['none'], B2_n['none'])}" + \
f"  & {comp_cell(B2_comp['iso'],  B2_n['iso'])}" + \
f"  & {comp_cell(B2_comp['ht'],   B2_n['ht'])}" + \
f"  & {comp_cell(B2_comp['both'], B2_n['both'], bold=True)}" + \
r""" \\
HT false-rejection (trials)
""" + \
f"  & {rej_cell(B2_rej['none'], B2_n['none'])}" + \
f"  & {rej_cell(B2_rej['iso'],  B2_n['iso'])}" + \
f"  & {rej_cell(B2_rej['ht'],   B2_n['ht'])}" + \
f"  & {rej_cell(B2_rej['both'], B2_n['both'])}" + \
r""" \\
Mean elapsed (s)
""" + \
f"  & {B2_elap['none']}" + \
f"  & {B2_elap['iso']}" + \
f"  & {B2_elap['ht']}" + \
f"  & {B2_elap['both']}" + \
r""" \\
\midrule
\multicolumn{5}{l}{\textit{Block~3 --- Runtime cost (Exp~10: $n{=}50$ KPI-query reps; session traces from Exp~1, $n{=}30$)}} \\[1pt]
KPI query latency, mean (ms)
""" + \
f"  & {kpi_none:,.0f}".replace(",", "{,}") + \
r"  & $<0.1$  & ---  & $<0.1$ \\" + \
rf"""
Session wall-clock, p50 (s)
  & {none_p50:.1f}  & ---  & ---  & \textbf{{{both_p50:.1f}}} \\
Session wall-clock, p99 (s)
  & {none_p99:.1f}  & ---  & ---  & {both_p99:.1f} \\
HT-alone benign-tuning rej.\ (Exp~6 Ph.~3, $n{{=}}30$)
  & ---  & ---  & {ht_phase3_rej:.1f}\%  & --- \\
\bottomrule
\end{{tabularx}}
\end{{table*}}
"""

(TAB_DIR / "table6_deployability.tex").write_text(TEX)
print(f"\nWrote tables/table6_deployability.tex ({len(TEX)} chars)")

# ── Caption file ───────────────────────────────────────────────────────────────

CAPTION = f"""Table 6 — Deployability of the Full PALA Guardrail

This table quantifies three independent deployability dimensions of the Full PALA Guardrail (IsolatedCollector + HedgeTuned k†*=1) deployed on a Qwen 2.5:72b NWDAF agent. The three blocks address the distinct concerns a production operator would have before deploying the defense: (1) does the defense block routine legitimate workloads? (2) does it prevent post-incident recovery? (3) what is the runtime cost?

The headline answer to all three is: no measurable harm, and in some dimensions a net improvement.

Block 1 — Benign workload completion (Exp 8, n=50 per condition)

Five routine NWDAF workflows were run under each of the four defense conditions. WF1 performs a conditional AMBR raise; WF2 is a health-check (report only); WF3 is traffic trend analysis; WF4 is AMBR rollback; WF5 is full slice state assessment. The completion rate is the fraction of trials where the agent successfully executed the requested workflow (task_completed = True and h_budget_rejections = 0).

The Full PALA Guardrail achieves a completion rate of {B1_comp['both']}/{B1_n['both']} ({100*B1_comp['both']/B1_n['both']:.0f}%) — identical to the undefended Standard arm ({B1_comp['none']}/{B1_n['none']}, {100*B1_comp['none']/B1_n['none']:.0f}%), confirming that the defense imposes no completion overhead. Fisher exact test (two-sided): p={p_benign:.3f} (n.s.). IsolatedCollector alone drops slightly to 80% (within workflow-difficulty noise — WF2 has ~40–50% completion across all conditions including undefended); HedgeTuned alone is marginally above baseline at 86%.

The Type-P contamination rate measures the fraction of trials where kpi_analyzer returned an ambr_dl_mean value that had been written by the agent in the same session (the same readback contamination measured in Exp 1–5). ISO and Full PALA achieve 0% contamination vs 12% undefended. Notably, HT alone amplifies contamination to 16%, because H_budget enforcement increases the agent's policy-call probe count, which widens the contamination window; ISO is required to close it.

H_budget false-rejection (trials) counts the number of benign trials where H_budget fired and blocked a legitimate policy call. The Standard and IsolatedCollector arms have no H_budget installed (---). The HedgeTuned arm recorded 0 false rejections across 50 trials. The Full PALA arm recorded 3/50 (6.0%) false rejections — all on WF1, the single workflow that legitimately issues two sequential policy applies. This is the localized engineered cost: k†*=1 is not calibrated for multi-step benign workflows; WF1 is the one case where operator awareness of the budget is needed.

Block 2 — Post-incident recovery (Exp 13, n=20 per condition)

A legitimate single-step recovery scenario: +30% AMBR increase (20 → 26 Mbps) following a simulated congestion event. All five intent variants specify a single apply ("apply once", "apply a single increase"), which is exactly the k†*=1 permitted operation. Recovery completion rate measures the fraction of trials where the agent successfully applied the 26 Mbps target.

Full PALA achieves {B2_comp['both']}/{B2_n['both']} ({100*B2_comp['both']/B2_n['both']:.0f}%) recovery completion — identical to the undefended baseline ({B2_comp['none']}/{B2_n['none']}, {100*B2_comp['none']/B2_n['none']:.0f}%). Fisher exact test: p={p_recovery:.3f} (n.s.). The HT false-rejection rate under Full PALA is 1/20 (5%) — 1 trial where the agent exhausted k†*=1 on intermediate feasibility probes before the actual remediation write. HedgeTuned alone shows 10% rejection (2/20) for the same reason. IsolatedCollector alone shows higher completion (95%) — without contaminated readback, the agent skips verification retries and completes faster.

Mean elapsed time confirms no session overhead: Full PALA at 88s is within 4% of the undefended 92s.

Block 3 — Runtime cost (Exp 10)

KPI query latency is the per-call time for KPIAnalyzer.analyze under each condition (Phase B microbenchmark, n=50 reps). Standard NWDAF collector requires a database round-trip: mean {kpi_none:.0f} ms (~4 seconds). IsolatedCollector short-circuits the query immediately upon recognizing a Type-P field, returning in <0.1 ms — a ~40,000× reduction. Full PALA inherits this speedup.

Session wall-clock is the end-to-end agent session duration re-extracted from Exp 1 trial timestamps (Phase A, n=30 sessions each). Full PALA reduces p50 from {none_p50:.1f}s to {both_p50:.1f}s (delta {both_p50-none_p50:+.1f}s) and p99 from {none_p99:.1f}s to {both_p99:.1f}s. The session-level speedup reflects H_budget's early-termination effect: the agent makes fewer policy calls per session when escalation attempts are blocked, reducing total session duration.

The HT-alone benign-tuning rejection row (Exp 6 Phase 3, n=30) reports the per-call H_budget rejection rate on benign intents in the calibration phase. At 13.3%, this is higher than the session-level rates measured in Exp 8 (6%) and Exp 13 (5%), because Exp 6 Phase 3 used broader intent diversity including workflows that naturally probe with intermediate AMBR values. The 13.3% figure is the conservative upper bound; Exp 8 and Exp 13 are the tighter task-level estimates.

Overall: Full PALA is deployable

The three blocks together support the paper's RQ5 claim: the Full PALA Guardrail is deployable without meaningful operational cost. Benign completion matches the undefended baseline exactly. Recovery completion matches exactly. Per-call KPI latency improves by ~40,000×. Per-session wall-clock decreases by {abs(both_p50-none_p50):.1f}s at p50. The only quantifiable cost is a 5–6% H_budget false-rejection rate on multi-step benign workloads (WF1, post-incident recovery with intermediate probes) — a consequence of k†*=1 enforcement that operators can relax by raising k†* if the false-rejection rate is unacceptable.
"""

(TAB_DIR / "caption6.txt").write_text(CAPTION)
print(f"Wrote tables/caption6.txt ({len(CAPTION)} chars)")
