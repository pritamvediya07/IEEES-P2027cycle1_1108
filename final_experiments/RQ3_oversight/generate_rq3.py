"""
RQ3 Figure 3 and Table 3 generator.

Sources:
  - exp3/               Qwen 2.5:72b (n=30)
  - exp3_multimodel/    Mistral-large + Llama 3.1:70b (n=30 each)

Outputs:
  figures/fig3_oversight.pdf  + .png
  tables/table3_rq3.tex
  data/rq3_summary.json
"""

import json, math, statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import wilcoxon

ROOT     = Path(__file__).parent.parent.parent
RESULTS  = ROOT / "wave_experiments" / "results"
OUT_DIR  = Path(__file__).parent
FIG_DIR  = OUT_DIR / "figures"
TAB_DIR  = OUT_DIR / "tables"
DATA_DIR = OUT_DIR / "data"
FIG_DIR.mkdir(exist_ok=True)
TAB_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# ── Wilson CI ─────────────────────────────────────────────────────────────────
def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2*n)) / d
    m = z * math.sqrt(p*(1-p)/n + z**2/(4*n**2)) / d
    return max(0.0, c - m), min(1.0, c + m)

# ── Cohen's h ─────────────────────────────────────────────────────────────────
def cohen_h(p1, p2):
    return 2*math.asin(math.sqrt(min(p1, 1.0))) - 2*math.asin(math.sqrt(min(p2, 1.0)))

# ── Data loading ──────────────────────────────────────────────────────────────
qwen_trials = [
    json.loads(l) for l in
    (RESULTS / "exp3" / "exp3_trials.jsonl").read_text().strip().splitlines() if l
]
mm_trials = [
    json.loads(l) for l in
    (RESULTS / "exp3_multimodel" / "exp3_multimodel_trials.jsonl").read_text().strip().splitlines() if l
]
mistral_trials = [t for t in mm_trials if "mistral" in t.get("model", "").lower()]
llama_trials   = [t for t in mm_trials if "llama"   in t.get("model", "").lower()]

FAMILIES = [
    ("Qwen 2.5:72b",  qwen_trials),
    ("Mistral-large", mistral_trials),
    ("Llama 3.1:70b", llama_trials),
]

# ── Per-family statistics ─────────────────────────────────────────────────────
def compute_family_stats(trials, label):
    pc_rates  = [t["per_call_review"]["approval_rate"]   for t in trials]
    cum_rates = [t["cumulative_review"]["approval_rate"] for t in trials]
    decomposed = sum(1 for t in trials if t.get("decomposed"))

    # Wilcoxon signed-rank (paired, cumulative > per-call)
    diffs = [c - p for p, c in zip(pc_rates, cum_rates)]
    if any(d != 0 for d in diffs):
        _, wil_p = wilcoxon(cum_rates, pc_rates, alternative="greater")
    else:
        wil_p = 1.0

    mean_pc  = statistics.mean(pc_rates)
    mean_cum = statistics.mean(cum_rates)
    se_pc    = statistics.stdev(pc_rates)  / math.sqrt(len(pc_rates))
    se_cum   = statistics.stdev(cum_rates) / math.sqrt(len(cum_rates))

    # Cohen's h on session-mean proportions
    h = cohen_h(mean_cum, mean_pc)

    # Pooled call-level Wilson CI (for error bars on the bar chart)
    tot_pc  = sum(t["per_call_review"]["n_policy_calls"]  for t in trials)
    appr_pc = sum(t["per_call_review"]["approved_count"]  for t in trials)
    tot_cum = sum(t["cumulative_review"]["n_policy_calls"] for t in trials)
    appr_cum = sum(t["cumulative_review"]["approved_count"] for t in trials)
    pc_lo,  pc_hi  = wilson_ci(appr_pc,  tot_pc)
    cum_lo, cum_hi = wilson_ci(appr_cum, tot_cum)

    # Session-level blocking pattern (all 30 sessions, including 0-call ones)
    both_block = sum(1 for t in trials
                     if t["per_call_review"]["approval_rate"] < 1.0
                     and t["cumulative_review"]["approval_rate"] < 1.0)
    only_pc    = sum(1 for t in trials
                     if t["per_call_review"]["approval_rate"] < 1.0
                     and t["cumulative_review"]["approval_rate"] == 1.0)
    only_cum   = sum(1 for t in trials
                     if t["per_call_review"]["approval_rate"] == 1.0
                     and t["cumulative_review"]["approval_rate"] < 1.0)
    neither    = sum(1 for t in trials
                     if t["per_call_review"]["approval_rate"] == 1.0
                     and t["cumulative_review"]["approval_rate"] == 1.0)

    return {
        "label":       label,
        "n":           len(trials),
        "decomposed":  decomposed,
        "mean_pc":     mean_pc,
        "mean_cum":    mean_cum,
        "se_pc":       se_pc,
        "se_cum":      se_cum,
        "pc_lo":       pc_lo,  "pc_hi":  pc_hi,
        "cum_lo":      cum_lo, "cum_hi": cum_hi,
        "delta_pp":    (mean_cum - mean_pc) * 100,
        "wilcoxon_p":  wil_p,
        "cohen_h":     h,
        "both_block":  both_block,
        "only_pc":     only_pc,
        "only_cum":    only_cum,
        "neither":     neither,
    }

stats = [compute_family_stats(t, lbl) for lbl, t in FAMILIES]

for s in stats:
    print(f"{s['label']:20s}  PC={s['mean_pc']*100:.1f}%  CUM={s['mean_cum']*100:.1f}%"
          f"  Δ={s['delta_pp']:+.1f}pp  p={s['wilcoxon_p']:.2e}  h={s['cohen_h']:.3f}"
          f"  blocking: {s['both_block']}/{s['only_pc']}/{s['only_cum']}/{s['neither']}")

# ══════════════════════════════════════════════════════════════════════════════
# FIGURE 3 — 1×2 oversight failure
# ══════════════════════════════════════════════════════════════════════════════

fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(15, 5.5), constrained_layout=True)

BLUE    = "#1f77b4"
RED     = "#d62728"
GREY    = "#7f7f7f"
LGREY   = "#cccccc"
ORANGE  = "#ff7f0e"
TEAL    = "#17becf"
FS_LBL  = 10.5
FS_TTL  = 10.5
FS_TIC  = 9.5

# ── Panel (a): Cross-family approval rates ────────────────────────────────────
x_pos  = np.arange(3)
width  = 0.32
labels = [s["label"] for s in stats]

pc_heights  = [s["mean_pc"]  * 100 for s in stats]
cum_heights = [s["mean_cum"] * 100 for s in stats]

pc_errs  = [[1.96 * s["se_pc"]  * 100 for s in stats],
            [1.96 * s["se_pc"]  * 100 for s in stats]]
cum_errs = [[1.96 * s["se_cum"] * 100 for s in stats],
            [1.96 * s["se_cum"] * 100 for s in stats]]

ax_a.bar(x_pos - width/2, pc_heights,  width, color=BLUE, alpha=0.85,
         label="Per-call (AS6 condition)", edgecolor="white")
ax_a.bar(x_pos + width/2, cum_heights, width, color=RED,  alpha=0.85,
         label="Cumulative (counterfactual)", edgecolor="white")
ax_a.errorbar(x_pos - width/2, pc_heights,  yerr=pc_errs,
              fmt="none", color="black", linewidth=1.3, capsize=4)
ax_a.errorbar(x_pos + width/2, cum_heights, yerr=cum_errs,
              fmt="none", color="black", linewidth=1.3, capsize=4)

for i, (ph, ch) in enumerate(zip(pc_heights, cum_heights)):
    ax_a.text(x_pos[i] - width/2, ph + 1.5, f"{ph:.1f}%",
              ha="center", fontsize=8.5, color=BLUE, fontweight="bold")
    ax_a.text(x_pos[i] + width/2, ch + 1.5, f"{ch:.1f}%",
              ha="center", fontsize=8.5, color=RED, fontweight="bold")

# Gap arrow between per-call and cumulative for Qwen (leftmost group)
delta_qwen = cum_heights[0] - pc_heights[0]
ax_a.annotate("", xy=(x_pos[0] + width/2 - 0.01, cum_heights[0] * 0.5 + pc_heights[0] * 0.5),
              xytext=(x_pos[0] - width/2 + 0.01, cum_heights[0] * 0.5 + pc_heights[0] * 0.5),
              arrowprops=dict(arrowstyle="<->", color=GREY, lw=1.0))
ax_a.text(x_pos[0], (cum_heights[0] + pc_heights[0]) / 2 + 2,
          f"+{delta_qwen:.0f} pp", ha="center", fontsize=7.5, color=GREY)

# Reference line and annotation: plan expected cumulative near 0
ax_a.axhline(y=0, color=GREY, linewidth=0.7, linestyle=":", alpha=0.5)
ax_a.text(0.01, 0.03, "Plan expected\ncumulative ≈ 0%",
          transform=ax_a.transAxes, fontsize=7, va="bottom", ha="left", color=GREY)

# Wilcoxon p per family — right side, staggered
for i, s in enumerate(stats):
    ax_a.text(x_pos[i] + width/2 + 0.01,
              cum_heights[i] + 7,
              f"p={s['wilcoxon_p']:.1e}",
              ha="center", fontsize=7, color="#444444")

ax_a.set_xticks(x_pos)
ax_a.set_xticklabels(labels, fontsize=FS_TIC)
ax_a.set_ylabel("Approval rate (%)", fontsize=FS_LBL)
ax_a.set_ylim(0, 108)
ax_a.set_title("(a) Per-call vs cumulative approval rates\nacross three model families (n=30 each)",
               fontsize=FS_TTL)
ax_a.legend(fontsize=8.5, loc="upper left")

# Cross-family clustering box — upper right
ax_a.text(0.98, 0.97,
          "Cross-family range:\n45–51% per-call\n75–79% cumulative",
          transform=ax_a.transAxes, fontsize=8, va="top", ha="right",
          bbox=dict(boxstyle="round,pad=0.35", facecolor="#f0f4ff", alpha=0.95, edgecolor=BLUE))

# ── Panel (b): Session-level blocking-pattern asymmetry ───────────────────────
n_total = 30

# 4 segment colours — clearly distinct
CAT_COLORS = ["#9ecae1",   # light blue: both block
              BLUE,        # solid blue: only per-call
              "#fc8d59",   # orange-red: only cumulative (0 — empty)
              "#74c476"]   # green: neither (0 — empty)
CAT_LABELS = [
    "Both regimes block  ",
    "Only per-call blocks (cumul. approves all)  ",
    "Only cumulative blocks  [0/30]",
    "Neither blocks  [0/30]",
]

y_pos = np.arange(3)  # 3 families
bar_h = 0.52

for yi, s in enumerate(stats):
    counts = [s["both_block"], s["only_pc"], s["only_cum"], s["neither"]]
    left_x = 0
    for ci, (count, col) in enumerate(zip(counts, CAT_COLORS)):
        frac = count / n_total
        ax_b.barh(yi, frac * 100, bar_h, left=left_x,
                  color=col, edgecolor="white", linewidth=0.9, alpha=0.90)
        if count > 0:
            cx = left_x + frac * 100 / 2
            ax_b.text(cx, yi, str(count), ha="center", va="center",
                      fontsize=11, fontweight="bold",
                      color="white" if ci == 1 else "black")
        left_x += frac * 100

# Vertical divider at the 50% mark — shows the split clearly
ax_b.axvline(x=50, color=GREY, linewidth=1.0, linestyle="--", alpha=0.7)

# Single shared annotation for the 0/30 empty zone — placed above the bars
ax_b.text(75, 2.55,
          "← 0/30 across all families:\ncumulative never adds\nrestrictions per-call missed",
          ha="center", va="bottom", fontsize=8.5, color="#333333",
          bbox=dict(boxstyle="round,pad=0.35", facecolor="#fff8e7",
                    alpha=0.95, edgecolor="#e0a000"))
# Arrow pointing down to the empty zone
ax_b.annotate("", xy=(75, 2.0 + bar_h/2),
              xytext=(75, 2.45),
              arrowprops=dict(arrowstyle="->", color="#e0a000", lw=1.2))

# Segment boundary labels at top
ax_b.text(25,  3.05, "Both block", ha="center", fontsize=8, color="#225588")
ax_b.text(75,  3.05, "Only per-call blocks →", ha="center", fontsize=8, color=BLUE)

ax_b.set_yticks(y_pos)
ax_b.set_yticklabels(labels, fontsize=FS_TIC)
ax_b.set_xlabel("Sessions (out of 30)", fontsize=FS_LBL)
ax_b.set_xlim(0, 100)
ax_b.set_xticks([0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
ax_b.set_xticklabels(
    ["0", "", "6", "", "12", "15", "18", "", "24", "", "30"],
    fontsize=8)
ax_b.set_ylim(-0.5, 3.5)

# Legend patches
from matplotlib.patches import Patch
legend_patches = [Patch(color=c, alpha=0.9, label=l)
                  for c, l in zip(CAT_COLORS, CAT_LABELS)]
ax_b.legend(handles=legend_patches, fontsize=7.8, loc="lower right",
            framealpha=0.92, edgecolor=LGREY)

ax_b.set_title("(b) Session-level blocking-pattern asymmetry\n"
               "all 30 sessions per family — Qwen / Mistral / Llama",
               fontsize=FS_TTL)

fig.savefig(FIG_DIR / "fig3_oversight.pdf", bbox_inches="tight", dpi=150)
fig.savefig(FIG_DIR / "fig3_oversight.png", bbox_inches="tight", dpi=150)
plt.close(fig)
print("Saved fig3_oversight.pdf/.png")


# ══════════════════════════════════════════════════════════════════════════════
# TABLE 3 — Oversight failure quantified
# ══════════════════════════════════════════════════════════════════════════════

def fmt_p(p):
    if p < 1e-4:
        exp = math.floor(math.log10(p))
        mant = p / (10 ** exp)
        return f"${mant:.2f}\\times10^{{{exp}}}$"
    return f"${p:.4f}$"

tex = [
    r"\begin{tabular}{lcccccccc}",
    r"\toprule",
    r"\textbf{Model family} & \textbf{$n$} & \textbf{Decomposed} "
    r"& \textbf{Per-call} & \textbf{Cumulative} & \textbf{$\Delta$ (cum$-$per)} "
    r"& \textbf{Wilcoxon $p$} & \textbf{Cohen $h$} \\",
    r"\midrule",
]

for s in stats:
    decomp_str = f"{s['decomposed']}/30 ({s['decomposed']/30*100:.0f}\\%)"
    pc_str     = f"{s['mean_pc']*100:.1f}\\%"
    cum_str    = f"{s['mean_cum']*100:.1f}\\%"
    delta_str  = f"+{s['delta_pp']:.1f} pp"
    p_str      = fmt_p(s["wilcoxon_p"])
    h_str      = f"{s['cohen_h']:.3f}"
    tex.append(
        f"{s['label']} & {s['n']} & {decomp_str} & {pc_str} & {cum_str} "
        f"& {delta_str} & {p_str} & {h_str} \\\\"
    )

tex += [r"\bottomrule", r"\end{tabular}"]
(TAB_DIR / "table3_rq3.tex").write_text("\n".join(tex))
print("Saved table3_rq3.tex")


# ══════════════════════════════════════════════════════════════════════════════
# JSON summary
# ══════════════════════════════════════════════════════════════════════════════

summary_out = {
    "families": [
        {k: (round(v, 5) if isinstance(v, float) else v)
         for k, v in s.items()}
        for s in stats
    ],
    "cross_family_pc_range":  [round(min(s["mean_pc"]  for s in stats)*100, 1),
                                round(max(s["mean_pc"]  for s in stats)*100, 1)],
    "cross_family_cum_range": [round(min(s["mean_cum"] for s in stats)*100, 1),
                                round(max(s["mean_cum"] for s in stats)*100, 1)],
    "zero_only_cum_sessions": "0/30 across all families",
}
(DATA_DIR / "rq3_summary.json").write_text(json.dumps(summary_out, indent=2))
print("Saved rq3_summary.json")

print("\n=== TABLE 3 NUMBERS ===")
for s in stats:
    print(f"  {s['label']:20s}: PC={s['mean_pc']*100:.1f}%  CUM={s['mean_cum']*100:.1f}%"
          f"  Δ={s['delta_pp']:+.1f}pp  p={s['wilcoxon_p']:.3e}  h={s['cohen_h']:.3f}"
          f"  decomp={s['decomposed']}/30")
