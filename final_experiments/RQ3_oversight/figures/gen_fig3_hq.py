"""
High-quality Figure 3 regenerator (RQ3 — oversight failure).
Replaces the original 2-panel bar + horizontal-bar with a compact
dumbbell + session-strip layout that prints clearly at textwidth.

Design at 11" wide → ~5.5" print.  Square-ish panels, clean fonts.

Outputs (same directory):
  fig3_oversight_hq.pdf
  fig3_oversight_hq.png
"""

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

# ── Paths ──────────────────────────────────────────────────────────────────────
THIS_DIR  = Path(__file__).parent
DATA_FILE = THIS_DIR / ".." / "data" / "rq3_summary.json"

data     = json.loads(DATA_FILE.read_text())
families = data["families"]          # list of 3 dicts (Qwen, Mistral, Llama)
n_fam    = len(families)

# ── Style (matches fig1/fig2 HQ) ───────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.size":          12,
    "font.weight":        "normal",
    "axes.titlesize":     10,
    "axes.titleweight":   "normal",
    "axes.labelsize":     10,
    "axes.labelweight":   "normal",
    "xtick.labelsize":    9,
    "ytick.labelsize":    9,
    "legend.fontsize":    8.0,
    "legend.framealpha":  0.93,
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

BLUE_FILL  = "#1f77b4"
DARK_BLUE  = "#2166ac"
LIGHT_BLUE = "#92c5de"
RED        = "#d62728"
GREY       = "#7f7f7f"

# ── Figure: 1×2, left wider (dumbbell), right narrower (session strip) ─────────
fig, (ax_a, ax_b) = plt.subplots(
    1, 2, figsize=(11, 3.2),
    gridspec_kw={"width_ratios": [3, 2]},
)
fig.subplots_adjust(left=0.13, right=0.985, top=0.87, bottom=0.20, wspace=0.42)

# y-positions: families listed bottom→top so Qwen=0, Mistral=1, Llama=2
y_pos      = np.arange(n_fam)
fam_labels = [f["label"] for f in families]

# ══════════════════════════════════════════════════════════════════════════════
# Panel (a) — Dumbbell: per-call ○ ────── ● cumulative (the oversight gap)
# ══════════════════════════════════════════════════════════════════════════════
for yi, fam in enumerate(families):
    pc   = fam["mean_pc"]  * 100
    cum  = fam["mean_cum"] * 100
    # 95% CI half-widths from SE
    ci_pc  = fam["se_pc"]  * 100 * 1.96
    ci_cum = fam["se_cum"] * 100 * 1.96

    # CI bars
    ax_a.errorbar([pc],  [yi], xerr=ci_pc,
                  fmt="none", color=BLUE_FILL, linewidth=1.2, capsize=3, zorder=3)
    ax_a.errorbar([cum], [yi], xerr=ci_cum,
                  fmt="none", color=BLUE_FILL, linewidth=1.2, capsize=3, zorder=3)

    # Oversight-gap line (red = danger)
    ax_a.plot([pc, cum], [yi, yi], color=RED, linewidth=2.4,
              solid_capstyle="round", zorder=2)

    # Per-call dot (hollow circle = what AS6 evaluates per-call)
    ax_a.scatter([pc],  [yi], s=80, facecolor="white", edgecolor=BLUE_FILL,
                 linewidth=2.0, zorder=4, clip_on=False)

    # Cumulative dot (filled = what counterfactual session review shows)
    ax_a.scatter([cum], [yi], s=80, facecolor=BLUE_FILL, edgecolor=BLUE_FILL,
                 linewidth=1.5, zorder=4)

    # Δ + p annotation above the gap line
    mid = (pc + cum) / 2
    ax_a.text(mid, yi + 0.22,
              f"+{fam['delta_pp']:.0f} pp  (p={fam['wilcoxon_p']:.0e})",
              ha="center", va="bottom", fontsize=7.5, color=RED)

    # Value labels beside each dot
    ax_a.text(pc  - 1.0, yi, f"{pc:.1f}%",
              ha="right", va="center", fontsize=7.5, color="#333333")
    ax_a.text(cum + 1.0, yi, f"{cum:.1f}%",
              ha="left",  va="center", fontsize=7.5, color="#333333")

# Legend
legend_handles_a = [
    Line2D([0],[0], marker='o', color='w', markerfacecolor='white',
           markeredgecolor=BLUE_FILL, markeredgewidth=2.0, markersize=7,
           label=r"Per-call (AS6, $\circ$)"),
    Line2D([0],[0], marker='o', color='w', markerfacecolor=BLUE_FILL,
           markeredgecolor=BLUE_FILL, markersize=7,
           label="Cumulative (counterfactual)"),
    Line2D([0],[0], color=RED, linewidth=2.4, label="Oversight gap (pp)"),
]
ax_a.legend(handles=legend_handles_a, loc="lower right",
            fontsize=7.5, framealpha=0.93, borderaxespad=0.4)

# Cross-family range annotation (top-left)
pc_lo, pc_hi   = data["cross_family_pc_range"]
cum_lo, cum_hi = data["cross_family_cum_range"]
ax_a.text(0.02, 0.97,
          f"Cross-family range:\n"
          f"  Per-call:   {pc_lo:.0f}–{pc_hi:.0f}%\n"
          f"  Cumulative: {cum_lo:.0f}–{cum_hi:.0f}%",
          transform=ax_a.transAxes, fontsize=7.2, va="top", ha="left",
          color="#444444",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                    alpha=0.93, edgecolor="#bbbbbb", linewidth=0.7))

ax_a.set_yticks(y_pos)
ax_a.set_yticklabels(fam_labels, fontsize=9)
ax_a.set_xlabel("Approval rate (%)")
ax_a.set_xlim(28, 98)
ax_a.set_ylim(-0.65, n_fam - 0.35)
ax_a.axvline(x=50, color=GREY, linewidth=0.8, linestyle="--", alpha=0.55, zorder=1)
ax_a.set_title(r"(a) Per-call $\circ$ vs cumulative $\bullet$ approval — "
               r"Exp 3, $n{=}30$ per family")
ax_a.spines["right"].set_visible(False)
ax_a.spines["top"].set_visible(False)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (b) — Session-strip: per-session blocking pattern (only 2 active categories)
# ══════════════════════════════════════════════════════════════════════════════
for yi, fam in enumerate(families):
    both    = fam["both_block"]
    only_pc = fam["only_pc"]

    # "Both regimes block" segment
    ax_b.barh(yi, both, height=0.50, left=0,
              color=DARK_BLUE, edgecolor="white", linewidth=0.5)

    # "Only per-call blocks (cumul. approves)" segment
    ax_b.barh(yi, only_pc, height=0.50, left=both,
              color=LIGHT_BLUE, edgecolor="white", linewidth=0.5)

    # Value labels inside segments
    if both >= 3:
        ax_b.text(both / 2, yi, str(both),
                  ha="center", va="center", fontsize=9, color="white")
    if only_pc >= 3:
        ax_b.text(both + only_pc / 2, yi, str(only_pc),
                  ha="center", va="center", fontsize=9, color="#1a1a1a")

# Key 0/30 finding
ax_b.text(0.98, 0.04,
          f"Only-cumulative: 0/30\n"
          f"Neither blocks:  0/30\n"
          f"(consistent, all families)",
          transform=ax_b.transAxes, fontsize=7.2, ha="right", va="bottom",
          color="#444444",
          bbox=dict(boxstyle="round,pad=0.25", facecolor="#f5f5f5",
                    edgecolor="#cccccc", linewidth=0.7))

legend_handles_b = [
    Patch(facecolor=DARK_BLUE,  edgecolor="white", label="Both regimes block"),
    Patch(facecolor=LIGHT_BLUE, edgecolor="white", label="Only per-call blocks"),
]
ax_b.legend(handles=legend_handles_b, loc="upper right",
            fontsize=7.5, framealpha=0.93, borderaxespad=0.4)

ax_b.set_yticks(y_pos)
ax_b.set_yticklabels(fam_labels, fontsize=9)
ax_b.set_xlabel("Sessions (n = 30 per family)")
ax_b.set_xlim(0, 30)
ax_b.set_ylim(-0.65, n_fam - 0.35)
ax_b.axvline(x=15, color=GREY, linewidth=0.8, linestyle=":", alpha=0.55, zorder=1)
ax_b.set_title("(b) Per-session blocking pattern — Exp 3")
ax_b.spines["right"].set_visible(False)
ax_b.spines["top"].set_visible(False)

# ── Save ──────────────────────────────────────────────────────────────────────
out_pdf = THIS_DIR / "fig3_oversight_hq.pdf"
out_png = THIS_DIR / "fig3_oversight_hq.png"
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, bbox_inches="tight", dpi=300)
plt.close(fig)

print(f"Saved {out_pdf.name}  and  {out_png.name}")
print(f"  figsize 11×3.2 → prints at ~5.5×1.6\" at textwidth")
pc_vals  = [f"{f['mean_pc']*100:.1f}%" for f in families]
cum_vals = [f"{f['mean_cum']*100:.1f}%" for f in families]
print(f"  Panel (a): dumbbell, per-call {pc_vals}")
print(f"             cumulative  {cum_vals}")
print(f"  Panel (b): both_block  {[f['both_block'] for f in families]}")
print(f"             only_pc     {[f['only_pc']    for f in families]}")
