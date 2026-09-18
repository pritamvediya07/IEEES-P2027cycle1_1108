"""Generates fig3a_oversight.pdf/png — panel (a) only (bar chart, per-call vs cumulative).
HQ version: matches fig1/fig2 rcParams, spine cleanup, clean annotation style.
"""
import json, math, statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import wilcoxon

ROOT    = Path(__file__).parent.parent.parent.parent
RESULTS = ROOT / "wave_experiments" / "results"
FIG_DIR = Path(__file__).parent

def wilson_ci(k, n, z=1.96):
    if n == 0: return 0.0, 0.0
    p = k / n; d = 1 + z**2/n
    c = (p + z**2/(2*n)) / d
    m = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / d
    return max(0.0, c-m), min(1.0, c+m)

def cohen_h(p1, p2):
    return 2*math.asin(math.sqrt(min(p1,1.0))) - 2*math.asin(math.sqrt(min(p2,1.0)))

qwen_trials    = [json.loads(l) for l in (RESULTS/"exp3"/"exp3_trials.jsonl").read_text().strip().splitlines() if l]
mm_trials      = [json.loads(l) for l in (RESULTS/"exp3_multimodel"/"exp3_multimodel_trials.jsonl").read_text().strip().splitlines() if l]
mistral_trials = [t for t in mm_trials if "mistral" in t.get("model","").lower()]
llama_trials   = [t for t in mm_trials if "llama"   in t.get("model","").lower()]
FAMILIES = [("Qwen 2.5:72b", qwen_trials), ("Mistral-large", mistral_trials), ("Llama 3.1:70b", llama_trials)]

def compute_family_stats(trials, label):
    pc_rates  = [t["per_call_review"]["approval_rate"]   for t in trials]
    cum_rates = [t["cumulative_review"]["approval_rate"] for t in trials]
    diffs = [c-p for p,c in zip(pc_rates, cum_rates)]
    _, wil_p = wilcoxon(cum_rates, pc_rates, alternative="greater") if any(d!=0 for d in diffs) else (None, 1.0)
    mean_pc  = statistics.mean(pc_rates);  mean_cum = statistics.mean(cum_rates)
    se_pc    = statistics.stdev(pc_rates)/math.sqrt(len(pc_rates))
    se_cum   = statistics.stdev(cum_rates)/math.sqrt(len(cum_rates))
    return {"label": label, "mean_pc": mean_pc, "mean_cum": mean_cum,
            "se_pc": se_pc, "se_cum": se_cum,
            "delta_pp": (mean_cum-mean_pc)*100, "wilcoxon_p": wil_p,
            "cohen_h": cohen_h(mean_cum, mean_pc)}

stats  = [compute_family_stats(t, lbl) for lbl, t in FAMILIES]
labels = [s["label"] for s in stats]

# ── Style: matches fig1/fig2 HQ ───────────────────────────────────────────────
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

BLUE = "#1f77b4"; RED = "#d62728"; GREY = "#7f7f7f"

fig, ax_a = plt.subplots(1, 1, figsize=(8, 5.2))
fig.subplots_adjust(left=0.11, right=0.97, top=0.88, bottom=0.14)

x_pos = np.arange(3); width = 0.32
pc_heights  = [s["mean_pc"]  * 100 for s in stats]
cum_heights = [s["mean_cum"] * 100 for s in stats]
pc_errs  = [[1.96*s["se_pc"] *100 for s in stats], [1.96*s["se_pc"] *100 for s in stats]]
cum_errs = [[1.96*s["se_cum"]*100 for s in stats], [1.96*s["se_cum"]*100 for s in stats]]

bars_pc  = ax_a.bar(x_pos - width/2, pc_heights,  width, color=BLUE, alpha=0.85,
                    label="Per-call (AS6 condition)", edgecolor="white")
bars_cum = ax_a.bar(x_pos + width/2, cum_heights, width, color=RED,  alpha=0.85,
                    label="Cumulative (counterfactual)", edgecolor="white")
ax_a.errorbar(x_pos - width/2, pc_heights,  yerr=pc_errs,
              fmt="none", color="black", linewidth=1.1, capsize=3)
ax_a.errorbar(x_pos + width/2, cum_heights, yerr=cum_errs,
              fmt="none", color="black", linewidth=1.1, capsize=3)

# Value labels — above CI caps
for i, (ph, ch) in enumerate(zip(pc_heights, cum_heights)):
    ci_pc  = 1.96 * stats[i]["se_pc"]  * 100
    ci_cum = 1.96 * stats[i]["se_cum"] * 100
    ax_a.text(x_pos[i]-width/2, ph+ci_pc+1.5,  f"{ph:.1f}%",
              ha="center", fontsize=7.5, color="#333333")
    ax_a.text(x_pos[i]+width/2, ch+ci_cum+1.5, f"{ch:.1f}%",
              ha="center", fontsize=7.5, color="#333333")

# Oversight gap arrows + Δpp + p-value for each family
for i, s in enumerate(stats):
    ph  = pc_heights[i];  ch  = cum_heights[i]
    mid = (ph + ch) / 2
    ax_a.annotate("", xy=(x_pos[i]+width/2-0.01, mid),
                  xytext=(x_pos[i]-width/2+0.01, mid),
                  arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.9))
    ax_a.text(x_pos[i], mid + 2.5,
              f"+{s['delta_pp']:.0f} pp\np={s['wilcoxon_p']:.1e}",
              ha="center", fontsize=7, color="#444444")

ax_a.axhline(y=0, color=GREY, linewidth=0.6, linestyle=":", alpha=0.5)

# Cross-family summary box — upper left
ax_a.text(0.02, 0.97,
          "Cross-family range:\n  Per-call:   45–51%\n  Cumulative: 75–79%",
          transform=ax_a.transAxes, fontsize=7.5, va="top", ha="left",
          color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.7))

ax_a.set_xticks(x_pos)
ax_a.set_xticklabels(labels, fontsize=9)
ax_a.set_ylabel("Approval rate (%)")
ax_a.set_ylim(0, 97)
ax_a.set_yticks([0, 20, 40, 60, 80])
ax_a.set_title("(a) Per-call vs cumulative approval rates — Exp 3, n=30 per family")
ax_a.legend(fontsize=10, loc="upper right")
ax_a.spines["right"].set_visible(False)
ax_a.spines["top"].set_visible(False)

out_pdf = FIG_DIR / "fig3a_oversight.pdf"
out_png = FIG_DIR / "fig3a_oversight.png"
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, bbox_inches="tight", dpi=300)
plt.close(fig)
print(f"Saved {out_pdf.name}  and  {out_png.name}")
pc_vals  = [f"{s['mean_pc']*100:.1f}%" for s in stats]
cum_vals = [f"{s['mean_cum']*100:.1f}%" for s in stats]
print(f"  per-call  {pc_vals}")
print(f"  cumulative {cum_vals}")
