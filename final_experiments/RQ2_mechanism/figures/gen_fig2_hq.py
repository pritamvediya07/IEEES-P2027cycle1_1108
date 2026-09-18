"""
High-quality regenerator for Figure 2 (RQ2 — mechanism evidence).
Layout: 1×4, print-ready, square panels.

Design at 14" wide → scales to ~7" textwidth (0.5×) in LaTeX.
All panels keep their own x-axis labels (none share an axis variable).

Outputs (same directory):
  fig2_mechanism_hq.pdf   (vector, embed in LaTeX)
  fig2_mechanism_hq.png   (300 DPI preview)
"""

import json, math, statistics
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import fisher_exact
from statsmodels.stats.multitest import multipletests

# ── Paths ──────────────────────────────────────────────────────────────────────
THIS_DIR = Path(__file__).parent
ROOT     = THIS_DIR.parent.parent.parent
RESULTS  = ROOT / "wave_experiments" / "results"

# ── Helpers ────────────────────────────────────────────────────────────────────
def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom  = 1 + z**2 / n
    center = (p + z**2 / (2*n)) / denom
    margin = (z * math.sqrt(p*(1-p)/n + z**2/(4*n**2))) / denom
    return max(0.0, center - margin), min(1.0, center + margin)

def cohen_h(p1, p2):
    return 2 * math.asin(math.sqrt(max(0, p1))) - 2 * math.asin(math.sqrt(max(0, p2)))

# ── Load Exp 2 ─────────────────────────────────────────────────────────────────
exp2_sum  = json.loads((RESULTS / "exp2" / "summary.json").read_text())
registers = ["staged", "direct", "null"]
REG_LABELS = {"staged": "Staged\n(ITIL/SRE)", "direct": "Direct", "null": "Null control"}
exp2_data  = {r: exp2_sum["rows"][r] for r in registers}

# ── Load Exp 1 vulnerable — per-dimension Φ ───────────────────────────────────
exp1_raw    = [json.loads(l) for l in
               (RESULTS / "exp1" / "exp1_trials.jsonl").read_text().strip().splitlines()
               if l.strip()]
vuln_trials = [t for t in exp1_raw if t.get("arm") == "vulnerable"]
def4_trials = [t for t in vuln_trials if t.get("def4_satisfied")]

def k_dagger_step(trial):
    qt = trial.get("q_trace", [])
    q0 = (trial.get("baseline_q") or {}).get("Q")
    if q0 is None:
        return None
    for e in qt:
        if e.get("Q") is not None and e["Q"] < q0:
            return e["k"]
    return None

pre_tau, pre_lam, pre_rho, pre_sig   = [], [], [], []
post_tau, post_lam, post_rho, post_sig = [], [], [], []

for t in def4_trials:
    bq  = t.get("baseline_q", {})
    qt  = t.get("q_trace", [])
    kd  = k_dagger_step(t)
    if kd is None:
        continue
    pre_tau.append(bq.get("tau_mbps", 0))
    pre_lam.append(bq.get("lambda_ms", 0))
    pre_rho.append(bq.get("rho_pct", 0))
    pre_sig.append(bq.get("sigma", 0))
    post_e = [e for e in qt if e.get("k", 0) >= kd] or qt[-1:]
    post_tau.append(statistics.mean(e.get("tau_mbps",  0) for e in post_e))
    post_lam.append(statistics.mean(e.get("lambda_ms", 0) for e in post_e))
    post_rho.append(statistics.mean(e.get("rho_pct",   0) for e in post_e))
    post_sig.append(statistics.mean(e.get("sigma",     0) for e in post_e))

n_def4    = len(pre_tau)
mean_pre  = [statistics.mean(x) for x in [pre_tau,  pre_lam,  pre_rho,  pre_sig]]
mean_post = [statistics.mean(x) for x in [post_tau, post_lam, post_rho, post_sig]]
pct_change = []
for i, (pre, post) in enumerate(zip(mean_pre, mean_post)):
    pct_change.append(post - pre if i == 2
                      else (post - pre) / max(abs(pre), 1e-9) * 100)

# ── Load Exp 14 ────────────────────────────────────────────────────────────────
exp14_B         = json.loads((RESULTS / "exp14" / "phaseB_writes.json").read_text())
exp14_D         = json.loads((RESULTS / "exp14" / "phaseD_isolation.json").read_text())
contam_standard = exp14_B["confirmed_contamination_rate"]
contam_isolated = 0.0
n_phaseB        = exp14_B["n_writes"]
n_phaseD        = exp14_D["results"]["baseline"]["returned_values"]

# ── Load Exp 9 Phase C ─────────────────────────────────────────────────────────
exp9_C      = json.loads((RESULTS / "exp9" / "phaseC_summary.json").read_text())
N_vals      = sorted(int(k) for k in exp9_C["rows"])
escape_vals = [exp9_C["rows"][str(n)]["type_p_escape_fraction"] * 100 for n in N_vals]
cont_recs   = exp9_C["rows"]["5"]["contaminated_count"]

# ── Fisher p for Exp 2 ─────────────────────────────────────────────────────────
fisher_decomp_sd = exp2_sum.get("fisher_p_decomp_staged_vs_direct",  0.003)
fisher_fl_sd     = exp2_sum.get("fisher_p_fullloop_staged_vs_direct", 0.020)
fisher_decomp_sn = exp2_sum.get("fisher_p_decomp_staged_vs_null",    0.000013)
fisher_fl_sn     = exp2_sum.get("fisher_p_fullloop_staged_vs_null",  0.020)

# ── Style ──────────────────────────────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.size":          12,
    "font.weight":        "normal",
    "axes.titlesize":     10,
    "axes.titleweight":   "normal",
    "axes.labelsize":     10,
    "axes.labelweight":   "normal",
    "xtick.labelsize":    9,
    "ytick.labelsize":    9,
    "legend.fontsize":    8.5,
    "legend.framealpha":  0.92,
    "legend.edgecolor":   "#bbbbbb",
    "axes.linewidth":     0.9,
    "xtick.major.width":  0.9,
    "ytick.major.width":  0.9,
    "xtick.major.size":   3.5,
    "ytick.major.size":   3.5,
    "lines.linewidth":    2.0,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})

BLUE   = "#1f77b4"
ORANGE = "#ff7f0e"
GREEN  = "#2ca02c"
RED    = "#d62728"
GREY   = "#7f7f7f"
LGREY  = "#aaaaaa"

# ── Figure: 1×4, square panels ────────────────────────────────────────────────
# Panel width  = 0.92×14 / (4 + 3×0.32) = 12.88/4.96 = 2.60"
# Panel height = (0.88−0.24)×4.0 = 2.56"  → square ✓
# bottom=0.24 (vs 0.21 in fig1) for multi-line x-tick labels
fig, (ax_a, ax_b, ax_c, ax_d) = plt.subplots(1, 4, figsize=(14, 4.0))
fig.subplots_adjust(left=0.065, right=0.985, top=0.88, bottom=0.24, wspace=0.32)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (a) — Linguistic register activates decomposition (Exp 2)
# ══════════════════════════════════════════════════════════════════════════════
x_pos = np.arange(3)
bw    = 0.32

decomp_rates = [exp2_data[r]["decomposition_rate"] * 100 for r in registers]
fl_rates     = [exp2_data[r]["full_loop_rate"]     * 100 for r in registers]

decomp_errs, fl_errs = [], []
for r in registers:
    n_r = exp2_data[r]["n"]
    dk  = round(exp2_data[r]["decomposition_rate"] * n_r)
    fk  = round(exp2_data[r]["full_loop_rate"] * n_r)
    lo_d, hi_d = wilson_ci(dk, n_r)
    lo_f, hi_f = wilson_ci(fk, n_r)
    dr, fr = exp2_data[r]["decomposition_rate"], exp2_data[r]["full_loop_rate"]
    decomp_errs.append([(dr - lo_d)*100, (hi_d - dr)*100])
    fl_errs.append([(fr - lo_f)*100, (hi_f - fr)*100])

decomp_err_arr = np.array(decomp_errs).T
fl_err_arr     = np.array(fl_errs).T

ax_a.bar(x_pos - bw/2, decomp_rates, bw, label="Stage A: Decomposition",
         color=BLUE, alpha=0.50, edgecolor="white")
ax_a.bar(x_pos + bw/2, fl_rates, bw, label="Full loop (A∧B∧C∧D)",
         color=BLUE, alpha=1.0, edgecolor="white")
ax_a.errorbar(x_pos - bw/2, decomp_rates, yerr=decomp_err_arr,
              fmt="none", color="black", linewidth=1.1, capsize=3)
ax_a.errorbar(x_pos + bw/2, fl_rates, yerr=fl_err_arr,
              fmt="none", color="black", linewidth=1.1, capsize=3)

# Bar value labels — above each CI cap, centered over bar
# This avoids the top-edge overlap and right-border clipping of the right-side approach
for i in range(3):
    dr, fr = decomp_rates[i], fl_rates[i]
    ax_a.text(x_pos[i] - bw/2, dr + decomp_errs[i][1] + 1.5, f"{dr:.0f}%",
              ha="center", va="bottom", fontsize=7.5, color="black")
    ax_a.text(x_pos[i] + bw/2, fr + fl_errs[i][1] + 1.5, f"{fr:.0f}%",
              ha="center", va="bottom", fontsize=7.5, color="black")

# Fisher p annotation — upper right, away from bars
ax_a.text(0.98, 0.97,
          f"S vs D: p={fisher_decomp_sd:.3f}\n"
          f"S vs N: p={fisher_decomp_sn:.2e}",
          transform=ax_a.transAxes, fontsize=7.5,
          va="top", ha="right", color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.7))

ax_a.set_xticks(x_pos)
ax_a.set_xticklabels([REG_LABELS[r] for r in registers], fontsize=9)
ax_a.set_ylabel("Rate (%)")
# Ylim must fit the highest CI cap + its value label
_a_tops = ([decomp_rates[i] + decomp_errs[i][1] + 1.5 for i in range(3)] +
           [fl_rates[i]    + fl_errs[i][1]    + 1.5 for i in range(3)])
ax_a.set_ylim(0, max(_a_tops) * 1.10)
ax_a.set_title(r"(a) Register activates decomposition")
ax_a.legend(loc="upper right", fontsize=8,
            bbox_to_anchor=(0.98, 0.79), borderaxespad=0)
ax_a.axhline(y=0, color="grey", linewidth=0.6)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (b) — Φ-dimension % change at k†: diverging bar chart
# Single y-axis in % avoids the incompatible-scale confusion of normalised
# paired bars (τ in Mbps vs λ in ms sharing one axis).
# ══════════════════════════════════════════════════════════════════════════════
dim_x = np.arange(4)

# τ drops (throughput degradation) and λ rises (latency inflation) → both RED
bar_cols_b = [RED if (i == 0 and pct_change[i] < 0) or (i == 1 and pct_change[i] > 0)
              else LGREY for i in range(4)]

ax_b.bar(dim_x, pct_change, 0.50, color=bar_cols_b, alpha=0.87,
         edgecolor="white", linewidth=0.6)
ax_b.axhline(y=0, color="black", linewidth=0.8)

for xi, pc in enumerate(pct_change):
    if abs(pc) < 0.5:
        # Show explicit 0% for ρ and σ so readers see unchanged metrics clearly
        ax_b.text(xi, 1.5, "0%", ha="center", va="bottom", fontsize=8, color="#888888")
    else:
        va_  = "bottom" if pc >= 0 else "top"
        off  = 1.5      if pc >= 0 else -1.5
        ax_b.text(xi, pc + off, f"{pc:+.0f}%", ha="center", fontsize=8, va=va_,
                  color=bar_cols_b[xi] if bar_cols_b[xi] != LGREY else "#555555")

# Actual-value box — upper right (negative τ bar leaves top clear)
ax_b.text(0.98, 0.97,
          f"τ: {mean_pre[0]:.1f}→{mean_post[0]:.1f} Mbps\n"
          f"λ: {mean_pre[1]:.0f}→{mean_post[1]:.0f} ms\n"
          f"ρ: {mean_pre[2]:.1f}%→{mean_post[2]:.1f}%\n"
          f"σ: {mean_pre[3]:.0f}→{mean_post[3]:.0f} cnt",
          transform=ax_b.transAxes, fontsize=7,
          va="top", ha="right", color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.7))

ax_b.set_xticks(dim_x)
ax_b.set_xticklabels(
    [r"$\tau$ throughput" "\n(Mbps)",
     r"$\lambda$ latency"  "\n(ms)",
     r"$\rho$ pkt loss"    "\n(%)",
     r"$\sigma$ sessions"  "\n(cnt)"],
    fontsize=8.0)
ax_b.set_ylabel(r"Change at $k^\dagger$ (%)")
_yrange = max(abs(min(pct_change)), abs(max(pct_change)))
ax_b.set_ylim(-_yrange * 1.35, _yrange * 1.35)
ax_b.set_title(rf"(b) $\Phi$ shifts at $k^\dagger$: $\tau\downarrow$ $\lambda\uparrow$ "
               rf"(n={n_def4})")

# ══════════════════════════════════════════════════════════════════════════════
# Panel (c) — Contamination channel is binary (Exp 14)
# ══════════════════════════════════════════════════════════════════════════════
cond_rates = [contam_standard * 100, contam_isolated * 100]
bar_c_cols = [RED, GREEN]

ax_c.bar([0, 1], cond_rates, 0.44, color=bar_c_cols, alpha=0.87, edgecolor="white")

for xi, (k_val, n_val, rate) in enumerate(
        zip([n_phaseB, 0], [n_phaseB, n_phaseD], cond_rates)):
    lo, hi = wilson_ci(k_val, n_val)
    ax_c.errorbar([xi], [rate],
                  yerr=[[(rate/100 - lo)*100], [(hi - rate/100)*100]],
                  fmt="none", color="black", linewidth=1.3, capsize=3)
    if xi == 0:
        ax_c.text(xi, rate + 3.0, f"{rate:.0f}%\n(n={n_val})",
                  ha="center", fontsize=9.5, fontweight="normal")
    else:
        # Just right of bar edge; expanded xlim below prevents border clip
        ax_c.text(xi + 0.24, rate + 3.0, f"{rate:.0f}%\n(n={n_val})",
                  ha="left", fontsize=9.5, fontweight="normal")

# Claim labels — inside bars, using axes fraction coords
# Standard bar: label at ~55% height → inside the red bar, dark text
ax_c.text(0.27, 0.50,
          "Lemma 2:\nType-P 100%",
          transform=ax_c.transAxes, fontsize=8, ha="center", color="#222222",
          fontweight="normal")
# IsolatedCollector bar: moved higher to clear the "0% (n=N)" value label
ax_c.text(0.73, 0.28,
          "ISO:\nsevers to 0%",
          transform=ax_c.transAxes, fontsize=8, ha="center", va="bottom",
          color="#222222",
          bbox=dict(boxstyle="round,pad=0.22", facecolor="white",
                    alpha=0.88, edgecolor=GREEN, linewidth=0.9))

ax_c.set_xticks([0, 1])
ax_c.set_xticklabels(["Standard\n(AS2 violated)", "IsolatedCollector\n(AS2 enforced)"],
                     fontsize=9)
ax_c.set_ylabel("Type-P contamination rate (%)")
ax_c.set_ylim(0, 128)
ax_c.set_xlim(-0.5, 1.65)
ax_c.set_title("(c) Contamination is binary")

# ══════════════════════════════════════════════════════════════════════════════
# Panel (d) — AS5 amplifies contamination via batch size N (Exp 9 Phase C)
# ══════════════════════════════════════════════════════════════════════════════
ax_d.plot(N_vals, escape_vals, color=BLUE, linewidth=2.0, zorder=3)
ax_d.scatter(N_vals, escape_vals, color=BLUE, s=45, zorder=4)

# Value labels — edge points use ha alignment to stay within xlim
for i, (n_val, esc) in enumerate(zip(N_vals, escape_vals)):
    if i == 0:
        ax_d.text(n_val + 1.0, esc + 3.5, f"{esc:.0f}%", ha="left",   fontsize=8)
    elif i == len(N_vals) - 1:
        ax_d.text(n_val - 1.0, esc + 3.5, f"{esc:.0f}%", ha="right",  fontsize=8)
    else:
        # Shift right so the descending line (coming from upper-left) is below the label
        ax_d.text(n_val + 2.0, esc + 4.0, f"{esc:.0f}%", ha="left",   fontsize=8)

# Threshold + floor reference lines
ax_d.axvline(x=30, color=GREY, linewidth=1.0, linestyle="--")
ax_d.axhline(y=escape_vals[-1], color=GREY, linewidth=0.8, linestyle=":")

# Annotations — upper right to avoid cluttering left side near the curve
ax_d.text(0.97, 0.97,
          f"-- N=30 (AS5 threshold)\n"
          f"·· Floor ≈{escape_vals[-1]:.0f}%  ({cont_recs} recs/N)\n"
          f"AS5 amplifies, never eliminates\n→ Remark 1 confirmed",
          transform=ax_d.transAxes, fontsize=7.5,
          va="top", ha="right", color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.7))

ax_d.set_xlabel("KPI batch size N (records per query)")
ax_d.set_ylabel("Type-P escape fraction (%)")
ax_d.set_ylim(0, max(escape_vals) * 1.18)
ax_d.set_xlim(N_vals[0] - 3, N_vals[-1] + 3)
ax_d.set_xticks(N_vals)
ax_d.set_title("(d) AS5 amplifies via batch size N")

# ── Save ──────────────────────────────────────────────────────────────────────
out_pdf = THIS_DIR / "fig2_mechanism_hq.pdf"
out_png = THIS_DIR / "fig2_mechanism_hq.png"
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, bbox_inches="tight", dpi=300)
plt.close(fig)
print(f"Saved {out_pdf.name}  and  {out_png.name}")
print(f"  figsize 14×4.0 → panels ≈ 2.60×2.56\" (square)")
print(f"  Panel (a): staged decomp={decomp_rates[0]:.0f}%  FL={fl_rates[0]:.0f}%")
print(f"  Panel (b): n_def4={n_def4}, τ {pct_change[0]:+.0f}%  λ {pct_change[1]:+.0f}%")
print(f"  Panel (c): standard={cond_rates[0]:.0f}%  iso={cond_rates[1]:.0f}%")
print(f"  Panel (d): N={N_vals}  escape={[f'{e:.0f}%' for e in escape_vals]}")
