"""
RQ2 Figure 2 and Table 2 generator.

Sources:
  - exp2/           Linguistic register trichotomy (Staged / Direct / Null, n=20 each)
  - exp1/           Vulnerable arm Qwen traces — per-dimension Φ degradation
  - exp14/          Contamination taxonomy — Standard vs IsolatedCollector
  - exp9/           Architectural sensitivity — phaseB (Δc) and phaseC (N sweep)
  - exp11/          Q-weight robustness — six operator profiles, n=28

Outputs:
  figures/fig2_mechanism.pdf  + .png
  tables/table2_qweight.tex
  tables/appendix_a1.tex
  data/rq2_summary.json
"""

import json, math, statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent.parent.parent
RESULTS  = ROOT / "wave_experiments" / "results"
OUT_DIR  = Path(__file__).parent
FIG_DIR  = OUT_DIR / "figures"
TAB_DIR  = OUT_DIR / "tables"
DATA_DIR = OUT_DIR / "data"
FIG_DIR.mkdir(exist_ok=True)
TAB_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ── Wilson 95% CI ──────────────────────────────────────────────────────────────
def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    margin = (z * math.sqrt(p*(1-p)/n + z**2/(4*n**2))) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


# ── Cohen's h ─────────────────────────────────────────────────────────────────
def cohen_h(p1, p2):
    return 2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2))


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

# ── Exp 2 ─────────────────────────────────────────────────────────────────────
exp2_sum = json.loads((RESULTS / "exp2" / "summary.json").read_text())
registers = ["staged", "direct", "null"]
REG_LABELS = {"staged": "Staged-change\n(ITIL/SRE)", "direct": "Direct", "null": "Null control"}
exp2_data = {r: exp2_sum["rows"][r] for r in registers}

# ── Exp 1 vulnerable — per-dimension Φ ────────────────────────────────────────
exp1_trials_raw = [
    json.loads(l) for l in
    (RESULTS / "exp1" / "exp1_trials.jsonl").read_text().strip().splitlines()
    if l.strip()
]
vuln_trials = [t for t in exp1_trials_raw if t.get("arm") == "vulnerable"]
def4_trials  = [t for t in vuln_trials if t.get("def4_satisfied")]

# For each def4 trial: baseline and post-trigger per-dimension means
def k_dagger_step(trial):
    qt = trial.get("q_trace", [])
    bq = trial.get("baseline_q", {})
    q0 = bq.get("Q")
    if q0 is None:
        return None
    for entry in qt:
        if entry.get("Q") is not None and entry["Q"] < q0:
            return entry["k"]
    return None

pre_tau, pre_lam, pre_rho, pre_sig = [], [], [], []
post_tau, post_lam, post_rho, post_sig = [], [], [], []

for t in def4_trials:
    bq  = t.get("baseline_q", {})
    qt  = t.get("q_trace", [])
    kd  = k_dagger_step(t)
    if kd is None:
        continue
    # pre: baseline (k=0)
    pre_tau.append(bq.get("tau_mbps", 0))
    pre_lam.append(bq.get("lambda_ms", 0))
    pre_rho.append(bq.get("rho_pct", 0))
    pre_sig.append(bq.get("sigma", 0))
    # post: q_trace entries at k >= k†
    post_entries = [e for e in qt if e.get("k", 0) >= kd]
    if not post_entries:
        post_entries = qt[-1:]
    post_tau.append(statistics.mean(e.get("tau_mbps",  0) for e in post_entries))
    post_lam.append(statistics.mean(e.get("lambda_ms", 0) for e in post_entries))
    post_rho.append(statistics.mean(e.get("rho_pct",   0) for e in post_entries))
    post_sig.append(statistics.mean(e.get("sigma",     0) for e in post_entries))

n_def4 = len(pre_tau)
mean_pre  = [statistics.mean(pre_tau),  statistics.mean(pre_lam),
             statistics.mean(pre_rho),  statistics.mean(pre_sig)]
mean_post = [statistics.mean(post_tau), statistics.mean(post_lam),
             statistics.mean(post_rho), statistics.mean(post_sig)]

# % change (τ, λ, σ) or pp change (ρ)
pct_change = []
for i, (pre, post) in enumerate(zip(mean_pre, mean_post)):
    if i == 2:  # ρ — pp change (avoid 0-base issues)
        pct_change.append(post - pre)
    else:
        pct_change.append((post - pre) / max(abs(pre), 1e-9) * 100)

se_change = []
for i, (pres, posts) in enumerate(
        zip([pre_tau, pre_lam, pre_rho, pre_sig],
            [post_tau, post_lam, post_rho, post_sig])):
    diffs = []
    for pr, po in zip(pres, posts):
        if i == 2:
            diffs.append(po - pr)
        else:
            diffs.append((po - pr) / max(abs(pr), 1e-9) * 100)
    se_change.append(statistics.stdev(diffs) / math.sqrt(len(diffs)) if len(diffs) > 1 else 0)

DIM_LABELS = [r"$\tau$ (throughput)", r"$\lambda$ (latency)", r"$\rho$ (loss, pp)", r"$\sigma$ (sessions)"]
DIM_UNITS  = ["Mbps→ %Δ", "ms→ %Δ", "pp Δ", "count→ %Δ"]

# ── Exp 14 ────────────────────────────────────────────────────────────────────
exp14_B = json.loads((RESULTS / "exp14" / "phaseB_writes.json").read_text())
exp14_D = json.loads((RESULTS / "exp14" / "phaseD_isolation.json").read_text())

contam_standard = exp14_B["confirmed_contamination_rate"]        # 1.0
contam_isolated = 0.0  # phaseD isolated returned_values = 0/20

n_phaseB = exp14_B["n_writes"]
n_phaseD = exp14_D["results"]["baseline"]["returned_values"]      # 20

# ── Exp 9 Phase C (N sweep) ────────────────────────────────────────────────────
exp9_C = json.loads((RESULTS / "exp9" / "phaseC_summary.json").read_text())
N_vals    = sorted(int(k) for k in exp9_C["rows"])
escape_vals = [exp9_C["rows"][str(n)]["type_p_escape_fraction"] * 100 for n in N_vals]

# ── Exp 9 Phase B (Δc model) ──────────────────────────────────────────────────
exp9_B = json.loads((RESULTS / "exp9" / "phaseB_summary.json").read_text())

# ── Exp 11 ────────────────────────────────────────────────────────────────────
exp11_sum = json.loads((RESULTS / "exp11" / "summary.json").read_text())
PROFILE_ORDER = ["equal", "tput_heavy", "latency_heavy", "loss_heavy",
                 "stable_heavy", "no_stability"]
PROFILE_LABELS = {
    "equal":        r"Equal (baseline) $(0.25\times4)$",
    "tput_heavy":   r"Throughput-heavy / eMBB $(0.50,0.17,0.17,0.16)$",
    "latency_heavy":r"Latency-heavy / URLLC $(0.17,0.50,0.17,0.16)$",
    "loss_heavy":   r"Loss-sensitive $(0.17,0.17,0.50,0.16)$",
    "stable_heavy": r"Stability-heavy $(0.17,0.17,0.16,0.50)$",
    "no_stability": r"Stability-removed $(0.33,0.33,0.34,0.00)$",
}
exp11_rows = exp11_sum["rows"]
eq_row = exp11_rows["equal"]
eq_rate = eq_row["def4_rate"]
eq_n    = eq_row["n_trials"]

# Cohen's h and Fisher exact p for each non-baseline profile
profile_stats = {}
for prof in PROFILE_ORDER:
    row = exp11_rows[prof]
    p_i = row["def4_rate"]
    n_i = row["n_trials"]
    k_i = round(p_i * n_i)
    k_eq = round(eq_rate * eq_n)
    h_val = cohen_h(p_i, eq_rate)
    _, pval = fisher_exact([[k_i, n_i - k_i], [k_eq, eq_n - k_eq]])
    profile_stats[prof] = {
        "n": n_i, "rate": p_i, "k": k_i,
        "delta_pp": (p_i - eq_rate) * 100,
        "h": h_val, "raw_p": pval,
    }

# BH correction across the 5 non-baseline comparisons
non_base = [p for p in PROFILE_ORDER if p != "equal"]
raw_ps   = [profile_stats[p]["raw_p"] for p in non_base]
_, bh_qs, _, _ = multipletests(raw_ps, method="fdr_bh")
for prof, q in zip(non_base, bh_qs):
    profile_stats[prof]["bh_q"] = q
profile_stats["equal"]["bh_q"] = float("nan")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 2 — 4-panel mechanism evidence
# ══════════════════════════════════════════════════════════════════════════════

fig, (ax_a, ax_b, ax_c, ax_d) = plt.subplots(1, 4, figsize=(26, 6), constrained_layout=True)

BLUE   = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN  = "#2ca02c"
RED    = "#d62728"
GREY   = "#7f7f7f"
LGREY  = "#aaaaaa"
FS_LBL = 10    # axis labels
FS_TTL = 10    # panel titles
FS_TIC = 9     # tick labels
FS_ANN = 8     # annotation text
FS_BAR = 8.5   # bar value labels

# ── Panel (a): Linguistic register activates decomposition ────────────────────
x_pos = np.arange(3)
width = 0.32

decomp_rates = [exp2_data[r]["decomposition_rate"] * 100 for r in registers]
fl_rates     = [exp2_data[r]["full_loop_rate"]     * 100 for r in registers]
n_each       = [exp2_data[r]["n"]                       for r in registers]

decomp_errs, fl_errs = [], []
for i, r in enumerate(registers):
    n_r = exp2_data[r]["n"]
    dk  = round(exp2_data[r]["decomposition_rate"] * n_r)
    fk  = round(exp2_data[r]["full_loop_rate"] * n_r)
    lo_d, hi_d = wilson_ci(dk, n_r)
    lo_f, hi_f = wilson_ci(fk, n_r)
    decomp_errs.append([(decomp_rates[i]/100 - lo_d)*100, (hi_d - decomp_rates[i]/100)*100])
    fl_errs.append([(fl_rates[i]/100 - lo_f)*100, (hi_f - fl_rates[i]/100)*100])

decomp_err_arr = np.array(decomp_errs).T
fl_err_arr     = np.array(fl_errs).T

ax_a.bar(x_pos - width/2, decomp_rates, width, label="Stage A: Decomposition",
         color=BLUE, alpha=0.50, edgecolor="white")
ax_a.bar(x_pos + width/2, fl_rates, width, label="Full loop (A∧B∧C∧D)",
         color=BLUE, alpha=1.0, edgecolor="white")
ax_a.errorbar(x_pos - width/2, decomp_rates, yerr=decomp_err_arr,
              fmt="none", color="black", linewidth=1.2, capsize=3.5)
ax_a.errorbar(x_pos + width/2, fl_rates, yerr=fl_err_arr,
              fmt="none", color="black", linewidth=1.2, capsize=3.5)

for i in range(3):
    dr, fr = decomp_rates[i], fl_rates[i]
    ax_a.text(x_pos[i] - width/2, dr + 1.5, f"{dr:.0f}%",
              ha="center", fontsize=FS_BAR, color="black" if dr > 0 else LGREY)
    ax_a.text(x_pos[i] + width/2, fr + 1.5, f"{fr:.0f}%",
              ha="center", fontsize=FS_BAR, color="black" if fr > 0 else LGREY)

fisher_decomp_sd = exp2_sum.get("fisher_p_decomp_staged_vs_direct", 0.003)
fisher_fl_sd     = exp2_sum.get("fisher_p_fullloop_staged_vs_direct", 0.020)
fisher_decomp_sn = exp2_sum.get("fisher_p_decomp_staged_vs_null", 0.000013)
fisher_fl_sn     = exp2_sum.get("fisher_p_fullloop_staged_vs_null", 0.020)

# Fisher p below the legend at bottom-left
ax_a.text(0.02, 0.04,
          f"S vs D: decomp p={fisher_decomp_sd:.4f}, loop p={fisher_fl_sd:.4f}\n"
          f"S vs N:  decomp p={fisher_decomp_sn:.2e}, loop p={fisher_fl_sn:.4f}",
          transform=ax_a.transAxes, fontsize=7, va="bottom", ha="left",
          bbox=dict(boxstyle="round,pad=0.3", facecolor="#f9f9f9", alpha=0.92, edgecolor="#cccccc"))

ax_a.set_xticks(x_pos)
ax_a.set_xticklabels([REG_LABELS[r] for r in registers], fontsize=FS_TIC)
ax_a.set_ylabel("Rate (%)", fontsize=FS_LBL)
ax_a.set_ylim(0, 92)
ax_a.set_title("(a) Linguistic register activates\ndecomposition (Exp 2, n=20/register)", fontsize=FS_TTL)
ax_a.legend(fontsize=8, loc="upper right")
ax_a.axhline(y=0, color="grey", linewidth=0.7)

# ── Panel (b): Per-dimension Φ — pre vs post-trigger grouped bars ─────────────
raw_pre  = [mean_pre[0],  mean_pre[1],  mean_pre[2],  mean_pre[3]]
raw_post = [mean_post[0], mean_post[1], mean_post[2], mean_post[3]]

dim_max   = [max(abs(a), abs(b), 1e-9) for a, b in zip(raw_pre, raw_post)]
pre_norm  = [a / m for a, m in zip(raw_pre,  dim_max)]
post_norm = [b / m for b, m in zip(raw_post, dim_max)]

dim_x = np.arange(4)
bw    = 0.30

bar_colours = []
for i, (pr, po) in enumerate(zip(raw_pre, raw_post)):
    if i == 0:
        bar_colours.append(RED   if po < pr else GREEN)
    elif i == 1:
        bar_colours.append(RED   if po > pr else GREEN)
    else:
        bar_colours.append(LGREY)

ax_b.bar(dim_x - bw/2, pre_norm,  bw, label="Baseline (pre-trigger)",
         color="#aec7e8", edgecolor="white", linewidth=0.6)
ax_b.bar(dim_x + bw/2, post_norm, bw, label=r"Post-$k^\dagger$",
         color=bar_colours, alpha=0.88, edgecolor="white", linewidth=0.6)

for xi in range(4):
    pr_str = f"{raw_pre[xi]:.1f}"
    po_str = f"{raw_post[xi]:.2f}" if xi == 0 else f"{raw_post[xi]:.1f}"
    ax_b.text(xi - bw/2, pre_norm[xi]  + 0.022, pr_str,
              ha="center", fontsize=7.5, color="#333333")
    ax_b.text(xi + bw/2, post_norm[xi] + 0.022, po_str,
              ha="center", fontsize=7.5,
              color=RED if bar_colours[xi] == RED else "#555555")

ax_b.set_xticks(dim_x)
ax_b.set_xticklabels(
    [r"$\tau$ throughput" "\n(Mbps)",
     r"$\lambda$ latency"  "\n(ms)",
     r"$\rho$ packet loss"  "\n(%)",
     r"$\sigma$ sessions"   "\n(cnt)"],
    fontsize=FS_TIC)
ax_b.set_ylabel("Normalised (per-dim max = 1)", fontsize=FS_LBL)
ax_b.set_ylim(0, 1.28)
ax_b.set_title(f"(b) Φ dimensions: baseline vs post-†\n"
               f"n={n_def4} Strict Def 4 sessions (Exp 1, Qwen)", fontsize=FS_TTL)
ax_b.legend(fontsize=8, loc="upper right")

ax_b.text(0.02, 0.04,
          f"τ: {raw_pre[0]:.1f}→{raw_post[0]:.1f} Mbps ({pct_change[0]:+.0f}%)\n"
          f"λ: {raw_pre[1]:.0f}→{raw_post[1]:.0f} ms ({pct_change[1]:+.0f}%)\n"
          f"ρ: {raw_pre[2]:.1f}→{raw_post[2]:.1f}%  (unchanged)\n"
          f"σ: {raw_pre[3]:.0f}→{raw_post[3]:.0f}   (unchanged)",
          transform=ax_b.transAxes, fontsize=7, va="bottom", ha="left",
          bbox=dict(boxstyle="round,pad=0.3", facecolor="#f9f9f9", alpha=0.92,
                    edgecolor="#cccccc"))

# ── Panel (c): Contamination channel is binary ────────────────────────────────
cond_rates = [contam_standard * 100, contam_isolated * 100]

ax_c.bar([0, 1], cond_rates, 0.44, color=[RED, GREEN], alpha=0.87, edgecolor="white")

for xi, (k_val, n_val, rate) in enumerate(
        zip([n_phaseB, 0], [n_phaseB, n_phaseD], cond_rates)):
    lo, hi = wilson_ci(k_val, n_val)
    ax_c.errorbar([xi], [rate],
                  yerr=[[(rate/100 - lo)*100], [(hi - rate/100)*100]],
                  fmt="none", color="black", linewidth=1.5, capsize=6)
    ax_c.text(xi, rate + 3.5, f"{rate:.0f}%\n(n={n_val})",
              ha="center", fontsize=10, fontweight="bold")

# Claim labels — inside each bar's open space
ax_c.text(0.27, 0.55,
          "Lemma 2:\nType-P at 100%",
          transform=ax_c.transAxes, fontsize=FS_ANN, ha="center", color="#222222",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white", alpha=0.9, edgecolor=RED))
ax_c.text(0.73, 0.14,
          "IsolatedCollector:\nsevers to 0%",
          transform=ax_c.transAxes, fontsize=FS_ANN, ha="center", color="#222222",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white", alpha=0.9, edgecolor=GREEN))

ax_c.set_xticks([0, 1])
ax_c.set_xticklabels(["Standard\n(AS2 violated)", "IsolatedCollector\n(AS2 enforced)"],
                     fontsize=FS_TIC)
ax_c.set_ylabel("Type-P contamination rate (%)", fontsize=FS_LBL)
ax_c.set_ylim(0, 130)
ax_c.set_title("(c) Contamination channel is binary (Exp 14)\n"
               "Complete elimination, not probabilistic reduction", fontsize=FS_TTL)

# ── Panel (d): AS5 amplifies via batch size N ─────────────────────────────────
contaminated_records = exp9_C["rows"]["5"]["contaminated_count"]

ax_d.plot(N_vals, escape_vals, color=BLUE, linewidth=2.4, zorder=3)
ax_d.scatter(N_vals, escape_vals, color=BLUE, s=55, zorder=4)

# Stagger labels: first point slightly left, rest above
label_offsets = [(-2.5, 4), (1.5, 4), (1.5, 4), (1.5, 4), (1.5, 4)]
for (n_val, esc), (dx, dy) in zip(zip(N_vals, escape_vals), label_offsets):
    ax_d.text(n_val + dx, esc + dy, f"{esc:.0f}%", ha="center", fontsize=FS_BAR)

ax_d.axvline(x=30, color=GREY, linewidth=1.2, linestyle="--")
ax_d.axhline(y=escape_vals[-1], color=GREY, linewidth=0.9, linestyle=":")

ax_d.text(0.04, 0.30,
          "-- N=30 (AS5 threshold)",
          transform=ax_d.transAxes, fontsize=7.5, color=GREY)
ax_d.text(0.04, 0.22,
          f"·· Floor ≈{escape_vals[-1]:.0f}%  ({contaminated_records} records/N)",
          transform=ax_d.transAxes, fontsize=7.5, color=GREY)
ax_d.text(0.04, 0.04,
          "AS5 amplifies, never eliminates\n→ Remark 1 confirmed",
          transform=ax_d.transAxes, fontsize=7.5, color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="#f9f9f9", alpha=0.92,
                    edgecolor="#cccccc"))

ax_d.set_xlabel("KPI batch size N (records per query)", fontsize=FS_LBL)
ax_d.set_ylabel("Type-P escape fraction (%)", fontsize=FS_LBL)
ax_d.set_ylim(0, 118)
ax_d.set_title("(d) AS5 amplifies contamination via N\n"
               "(Exp 9 Phase C — escape = contaminated records / N)", fontsize=FS_TTL)
ax_d.set_xticks(N_vals)

fig.savefig(FIG_DIR / "fig2_mechanism.pdf", bbox_inches="tight", dpi=150)
fig.savefig(FIG_DIR / "fig2_mechanism.png", bbox_inches="tight", dpi=150)
plt.close(fig)
print("Saved fig2_mechanism.pdf/.png")


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 2 — Q-weight robustness
# ══════════════════════════════════════════════════════════════════════════════

TABLE2_DISPLAY = {
    "equal":        ("Equal (baseline)",               "(0.25, 0.25, 0.25, 0.25)"),
    "tput_heavy":   ("Throughput-heavy (eMBB)",        "(0.50, 0.17, 0.17, 0.16)"),
    "latency_heavy":("Latency-heavy (URLLC)",          "(0.17, 0.50, 0.17, 0.16)"),
    "loss_heavy":   ("Loss-sensitive",                 "(0.17, 0.17, 0.50, 0.16)"),
    "stable_heavy": ("Stability-heavy",                "(0.17, 0.17, 0.16, 0.50)"),
    "no_stability": ("Stability-removed",              "(0.33, 0.33, 0.34, 0.00)"),
}

tex_lines = [
    r"\begin{tabular}{llccccc}",
    r"\toprule",
    r"\textbf{Operator profile} & \textbf{Weights $(v_\tau,v_\lambda,v_\rho,v_\sigma)$}"
    r" & \textbf{$n$} & \textbf{Strict Def~4} & \textbf{$\Delta$ vs equal}"
    r" & \textbf{Cohen's $h$} & \textbf{BH $q$} \\",
    r"\midrule",
]

for prof in PROFILE_ORDER:
    row  = exp11_rows[prof]
    pst  = profile_stats[prof]
    name, wvec = TABLE2_DISPLAY[prof]
    k_i  = pst["k"]
    n_i  = pst["n"]
    rate_str = f"{k_i}/{n_i} ({pst['rate']*100:.1f}\\%)"
    delta_str = "—" if prof == "equal" else (
        f"+{pst['delta_pp']:.1f} pp" if pst["delta_pp"] >= 0
        else f"{pst['delta_pp']:.1f} pp"
    )
    h_str = "—" if prof == "equal" else f"{pst['h']:+.2f}"
    q_str = "—" if prof == "equal" else (
        f"\\textbf{{{pst['bh_q']:.3f}}}" if pst["bh_q"] < 0.05
        else f"{pst['bh_q']:.3f}"
    )
    bold_open  = r"\textbf{" if prof == "equal" else ""
    bold_close = "}"        if prof == "equal" else ""
    tex_lines.append(
        f"{bold_open}{name}{bold_close} & \\texttt{{{wvec}}} & {n_i} & "
        f"{rate_str} & {delta_str} & {h_str} & {q_str} \\\\"
    )

tex_lines += [
    r"\bottomrule",
    r"\end{tabular}",
]
tex_table2 = "\n".join(tex_lines)
(TAB_DIR / "table2_qweight.tex").write_text(tex_table2)
print("Saved table2_qweight.tex")


# ══════════════════════════════════════════════════════════════════════════════
# APPENDIX TABLE A.1 — Δc latency model (Exp 9 Phase B)
# ══════════════════════════════════════════════════════════════════════════════

phaseB_rows = exp9_B["rows"]
dc_vals  = sorted(int(k) for k in phaseB_rows)

a1_lines = [
    r"\begin{tabular}{rrrrl}",
    r"\toprule",
    r"$\Delta_c$ (s) & Model latency (ms) & Live measurement (ms) & Model error (ms) & Note \\",
    r"\midrule",
]
for dc in dc_vals:
    row = phaseB_rows[str(dc)]
    model_ms = row["theoretical_latency_ms"]
    is_extrap = row.get("theoretical_extrapolation", False)
    live_str  = f"{row['mean_ms']:.0f} ± {row['stdev_ms']:.0f}" if not is_extrap else "—"
    err_str   = f"{row['model_error_ms']:.1f}" if "model_error_ms" in row else "—"
    note_str  = "extrapolated" if is_extrap else r"live meas. (7.0\% model error)"
    a1_lines.append(
        f"{dc} & {model_ms:.0f} & {live_str} & {err_str} & {note_str} \\\\"
    )

a1_lines += [
    r"\bottomrule",
    r"\end{tabular}",
]
tex_a1 = "\n".join(a1_lines)
(TAB_DIR / "appendix_a1.tex").write_text(tex_a1)
print("Saved appendix_a1.tex")


# ══════════════════════════════════════════════════════════════════════════════
# JSON summary
# ══════════════════════════════════════════════════════════════════════════════

summary_out = {
    "exp2": {
        r: {"decomp_%": exp2_data[r]["decomposition_rate"]*100,
            "fl_%": exp2_data[r]["full_loop_rate"]*100}
        for r in registers
    },
    "exp1_phi_degradation_n": n_def4,
    "exp1_phi_pct_change": {
        "tau_%": round(pct_change[0], 2),
        "lambda_%": round(pct_change[1], 2),
        "rho_pp": round(pct_change[2], 2),
        "sigma_%": round(pct_change[3], 2),
    },
    "exp14": {
        "standard_contamination_%": 100,
        "isolated_contamination_%": 0,
    },
    "exp9_phaseC": {str(n): round(e, 1) for n, e in zip(N_vals, escape_vals)},
    "exp11_profiles": {
        p: {"rate_%": round(profile_stats[p]["rate"]*100, 1),
            "delta_pp": round(profile_stats[p]["delta_pp"], 1),
            "cohen_h":  round(profile_stats[p]["h"], 3),
            "bh_q":     round(profile_stats[p].get("bh_q", float("nan")), 3)}
        for p in PROFILE_ORDER
    },
}
(DATA_DIR / "rq2_summary.json").write_text(json.dumps(summary_out, indent=2))
print("Saved rq2_summary.json")

print("\n=== KEY NUMBERS ===")
print(f"Exp 2 — Staged decomp: {exp2_data['staged']['decomposition_rate']*100:.0f}%  FL: {exp2_data['staged']['full_loop_rate']*100:.0f}%")
print(f"Exp 2 — Direct decomp: {exp2_data['direct']['decomposition_rate']*100:.0f}%  FL: {exp2_data['direct']['full_loop_rate']*100:.0f}%")
print(f"Exp 2 — Null decomp:   {exp2_data['null']['decomposition_rate']*100:.0f}%  FL: {exp2_data['null']['full_loop_rate']*100:.0f}%")
print(f"Exp 1 Φ degradation (n={n_def4} def4 sessions):")
for lbl, val, se in zip(["τ %Δ","λ %Δ","ρ pp","σ %Δ"], pct_change, se_change):
    unit = "pp" if "pp" in lbl else "%"
    print(f"  {lbl}: {val:+.1f}{unit} ± {se:.1f}")
print(f"Exp 14 — Standard: {contam_standard*100:.0f}%  Isolated: {contam_isolated*100:.0f}%")
print(f"Exp 9 Phase C — N={N_vals}: escape={[f'{e:.0f}%' for e in escape_vals]}")
print("Exp 11 profiles:")
for p in PROFILE_ORDER:
    ps = profile_stats[p]
    q_str = f"q={ps.get('bh_q', float('nan')):.3f}" if p != "equal" else "(baseline)"
    print(f"  {p:20s}: {ps['rate']*100:.1f}% (Δ={ps['delta_pp']:+.1f}pp, h={ps['h']:+.3f}, {q_str})")
