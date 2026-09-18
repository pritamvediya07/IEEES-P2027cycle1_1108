"""Generates fig3b_session_pattern.pdf/png — panel (b) only (session-level blocking pattern)."""
import json, math, statistics
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from scipy.stats import wilcoxon

ROOT    = Path(__file__).parent.parent.parent.parent
RESULTS = ROOT / "wave_experiments" / "results"
FIG_DIR = Path(__file__).parent

qwen_trials    = [json.loads(l) for l in (RESULTS/"exp3"/"exp3_trials.jsonl").read_text().strip().splitlines() if l]
mm_trials      = [json.loads(l) for l in (RESULTS/"exp3_multimodel"/"exp3_multimodel_trials.jsonl").read_text().strip().splitlines() if l]
mistral_trials = [t for t in mm_trials if "mistral" in t.get("model","").lower()]
llama_trials   = [t for t in mm_trials if "llama"   in t.get("model","").lower()]
FAMILIES = [("Qwen 2.5:72b", qwen_trials), ("Mistral-large", mistral_trials), ("Llama 3.1:70b", llama_trials)]

def compute_family_stats(trials, label):
    pc_rates  = [t["per_call_review"]["approval_rate"]   for t in trials]
    cum_rates = [t["cumulative_review"]["approval_rate"] for t in trials]
    both_block = sum(1 for t in trials if t["per_call_review"]["approval_rate"]<1.0 and t["cumulative_review"]["approval_rate"]<1.0)
    only_pc    = sum(1 for t in trials if t["per_call_review"]["approval_rate"]<1.0 and t["cumulative_review"]["approval_rate"]==1.0)
    only_cum   = sum(1 for t in trials if t["per_call_review"]["approval_rate"]==1.0 and t["cumulative_review"]["approval_rate"]<1.0)
    neither    = sum(1 for t in trials if t["per_call_review"]["approval_rate"]==1.0 and t["cumulative_review"]["approval_rate"]==1.0)
    return {"label": label, "both_block": both_block, "only_pc": only_pc, "only_cum": only_cum, "neither": neither}

stats  = [compute_family_stats(t, lbl) for lbl, t in FAMILIES]
labels = [s["label"] for s in stats]

BLUE  = "#1f77b4"; GREY = "#7f7f7f"; LGREY = "#cccccc"
FS_LBL = 10.5; FS_TTL = 10.5; FS_TIC = 9.5

CAT_COLORS = ["#9ecae1", BLUE, "#fc8d59", "#74c476"]
CAT_LABELS = ["Both regimes block  ",
              "Only per-call blocks (cumul. approves all)  ",
              "Only cumulative blocks  [0/30]",
              "Neither blocks  [0/30]"]

matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})

fig, ax_b = plt.subplots(1, 1, figsize=(8.0, 5.5), constrained_layout=True)

n_total = 30
y_pos   = np.arange(3)
bar_h   = 0.52

for yi, s in enumerate(stats):
    counts = [s["both_block"], s["only_pc"], s["only_cum"], s["neither"]]
    left_x = 0
    for ci, (count, col) in enumerate(zip(counts, CAT_COLORS)):
        frac = count / n_total
        ax_b.barh(yi, frac*100, bar_h, left=left_x, color=col, edgecolor="white", linewidth=0.9, alpha=0.90)
        if count > 0:
            cx = left_x + frac*100/2
            ax_b.text(cx, yi, str(count), ha="center", va="center", fontsize=11, fontweight="bold",
                      color="white" if ci==1 else "black")
        left_x += frac*100

ax_b.axvline(x=50, color=GREY, linewidth=1.0, linestyle="--", alpha=0.7)

ax_b.text(75, 2.55,
          "← 0/30 across all families:\ncumulative never adds\nrestrictions per-call missed",
          ha="center", va="bottom", fontsize=8.5, color="#333333",
          bbox=dict(boxstyle="round,pad=0.35", facecolor="#fff8e7", alpha=0.95, edgecolor="#e0a000"))
ax_b.annotate("", xy=(75, 2.0+bar_h/2), xytext=(75, 2.45),
              arrowprops=dict(arrowstyle="->", color="#e0a000", lw=1.2))

ax_b.text(25, 3.05, "Both block",              ha="center", fontsize=8, color="#225588")
ax_b.text(75, 3.05, "Only per-call blocks →",  ha="center", fontsize=8, color=BLUE)

ax_b.set_yticks(y_pos); ax_b.set_yticklabels(labels, fontsize=FS_TIC)
ax_b.set_xlabel("Sessions (out of 30)", fontsize=FS_LBL)
ax_b.set_xlim(0, 100)
ax_b.set_xticks([0,10,20,30,40,50,60,70,80,90,100])
ax_b.set_xticklabels(["0","","6","","12","15","18","","24","","30"], fontsize=8)
ax_b.set_ylim(-0.5, 3.5)

legend_patches = [Patch(color=c, alpha=0.9, label=l) for c,l in zip(CAT_COLORS, CAT_LABELS)]
ax_b.legend(handles=legend_patches, fontsize=7.8, loc="lower right", framealpha=0.92, edgecolor=LGREY)
ax_b.set_title("(b) Session-level blocking-pattern asymmetry\nall 30 sessions per family — Qwen / Mistral / Llama", fontsize=FS_TTL)

out_pdf = FIG_DIR / "fig3b_session_pattern.pdf"
out_png = FIG_DIR / "fig3b_session_pattern.png"
fig.savefig(out_pdf, bbox_inches="tight", dpi=150)
fig.savefig(out_png, bbox_inches="tight", dpi=150)
plt.close(fig)
print(f"Saved {out_pdf.name}  and  {out_png.name}")
