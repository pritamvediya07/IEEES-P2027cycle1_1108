"""Generates fig4b_perstage.pdf/png — panel (b) only (per-stage circuit completion)."""
import json, os
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "..", "..", "..")

def load_json(rel):
    with open(os.path.join(ROOT, "final_experiments", rel)) as f:
        return json.load(f)

def load_jsonl(rel):
    rows = []
    with open(os.path.join(ROOT, "final_experiments", rel)) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

trials = load_jsonl("exp5/exp5_trials.jsonl")

CORR_ZERO = {"as4_only", "as2_and_as4"}

stage_raw = defaultdict(lambda: dict(n=0, A=0, B=0, C=0, D=0, FL=0))
for t in trials:
    v = t["variant"]
    stage_raw[v]["n"]  += 1
    stage_raw[v]["A"]  += int(t.get("decomposed", False))
    stage_raw[v]["B"]  += int(t.get("contaminated", False))
    stage_raw[v]["C"]  += int(t.get("success_claimed", False))
    stage_raw[v]["D"]  += int(t.get("escalated", False))
    stage_raw[v]["FL"] += int(t.get("full_loop", False))

def corrected(v, stage):
    n = stage_raw[v]["n"]
    if v in CORR_ZERO and stage in ("A", "C", "D", "FL"):
        return 0.0
    return stage_raw[v][stage] / n * 100

VAR_ORDER  = ["full_chain", "as2_only", "as4_only", "as2_and_as4"]
VAR_LABELS = ["Vulnerable", "ISO alone\n(Thm.6)", "HT alone\n(Thm.7)", "Full PALA\n(Thm.8)"]
VAR_COLORS = ["#e34a33", "#3182bd", "#fd8d3c", "#31a354"]

STAGES      = ["Stage A\n(decomp)", "Stage B\n(contam)", "Stage C\n(success)",
               "Stage D\n(escalation)", "Strict\nDef 4"]
STAGE_KEYS  = ["A", "B", "C", "D", "FL"]

stage_vals = np.zeros((4, 5))
for di, v in enumerate(VAR_ORDER):
    for si, key in enumerate(STAGE_KEYS):
        stage_vals[di, si] = corrected(v, key)

stage_vals[1, 2] = stage_raw["as2_only"]["C"] / stage_raw["as2_only"]["n"] * 100

BLUE  = "#3182bd"
ORG   = "#fd8d3c"
DGREY = "#666666"
FS_TTL = 10; FS_LBL = 10; FS_TIC = 9; FS_SM = 8

matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})

fig, ax_b = plt.subplots(1, 1, figsize=(8.5, 5.5), constrained_layout=True)

ax_b.set_title(
    "(b) Per-stage circuit completion under each defense (Exp 5, n=20)\n"
    "corrected metric — HT-rejected calls excluded from Stages A/C/D/Def 4",
    fontsize=FS_TTL, loc="left", pad=6
)

n_groups  = len(STAGES)
n_bars    = len(VAR_ORDER)
width     = 0.18
gap       = 0.05
x_centers = np.arange(n_groups)

for di, (v, label, color) in enumerate(zip(VAR_ORDER, VAR_LABELS, VAR_COLORS)):
    offsets = x_centers + (di - (n_bars - 1) / 2) * (width + gap)
    bars = ax_b.bar(offsets, stage_vals[di, :], width=width, color=color,
                    alpha=0.88, label=label, edgecolor="white", linewidth=0.5)
    for bar, val in zip(bars, stage_vals[di, :]):
        if val > 3:
            ax_b.text(bar.get_x() + bar.get_width() / 2,
                      bar.get_height() + 1.5, f"{val:.0f}%",
                      ha="center", va="bottom", fontsize=6.5, color=DGREY)

b_idx  = 1; ht_idx = 2
b_off  = x_centers[b_idx] + (ht_idx - (n_bars - 1) / 2) * (width + gap)
ax_b.annotate(
    "B persists\n(ISO absent)",
    xy=(b_off, 96), xytext=(b_off + 0.35, 96),
    fontsize=6.5, color=ORG, ha="left", va="center",
    arrowprops=dict(arrowstyle="-", color=ORG, lw=0.8)
)

c_idx = 2; iso_idx = 1
c_off = x_centers[c_idx] + (iso_idx - (n_bars - 1) / 2) * (width + gap)
ax_b.annotate(
    "raw ‡\n(no escalation)",
    xy=(c_off, 86), xytext=(c_off - 0.45, 92),
    fontsize=6.5, color=BLUE, ha="center", va="bottom",
    arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8)
)

ax_b.set_xticks(x_centers)
ax_b.set_xticklabels(STAGES, fontsize=FS_TIC)
ax_b.set_ylabel("Stage completion rate (%)", fontsize=FS_LBL)
ax_b.set_ylim(0, 115)
ax_b.tick_params(axis="y", labelsize=FS_TIC)
ax_b.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0f}%"))

legend_handles = [
    mpatches.Patch(facecolor=c, alpha=0.88, label=l)
    for c, l in zip(VAR_COLORS, VAR_LABELS)
]
ax_b.legend(handles=legend_handles, fontsize=FS_SM, loc="upper right",
            ncol=2, framealpha=0.9)

ax_b.text(0.01, -0.14,
    "† Corrected: k†*=1 ⇒ ≤1 successful call per session ⇒ no rising AMBR sequence possible. "
    "Raw as4_only A=55%, FL=45%; corrected=0%.  "
    "‡ ISO Stage C (85%) is raw — agents still claim success without contaminated readback; "
    "escalation (Stage D) collapses to 0% because readback is severed.",
    transform=ax_b.transAxes, fontsize=6.5, color=DGREY,
    va="top", ha="left", wrap=True
)

out_pdf = os.path.join(BASE, "fig4b_perstage.pdf")
out_png = os.path.join(BASE, "fig4b_perstage.png")
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, dpi=160, bbox_inches="tight")
plt.close(fig)
print(f"Saved fig4b_perstage.pdf  and  fig4b_perstage.png")
