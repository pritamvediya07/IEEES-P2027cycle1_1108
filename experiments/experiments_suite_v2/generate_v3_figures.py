#!/usr/bin/env python3
"""
V3 Figure Generator — fig6_v3_final.png
3-panel figure from e3_1_revised_data.csv:
  (a) Overfitting gap vs N   (ρ = -1.0, p = 0.0)
  (b) Train R² vs Test R²   with R²-guard threshold line
  (c) Forecast Width W(N) vs N
"""
import csv
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Paths ────────────────────────────────────────────────────────
HERE    = Path(__file__).parent
CSV     = HERE / "experiments" / "results" / "e3_1_revised_data.csv"
OUT_DIR = HERE / "experiments" / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUTFILE = OUT_DIR / "fig6_v3_final.png"

# ── Load CSV ─────────────────────────────────────────────────────
rows = []
with open(CSV) as fh:
    reader = csv.DictReader(fh)
    for r in reader:
        rows.append({k: (float(v) if v.strip() else float("nan")) for k, v in r.items()})

N_all       = np.array([r["N"]             for r in rows])
W_all       = np.array([r["W_median"]      for r in rows])
R2tr_all    = np.array([r["R2_train_median"] for r in rows])
R2te_all    = np.array([r["R2_test_median"]  for r in rows])
R2gap_all   = np.array([r["R2_gap_median"]   for r in rows])

# Masks for rows where values exist
mask_gap  = ~np.isnan(R2gap_all)   # N ≥ 20
mask_r2   = ~np.isnan(R2tr_all)    # N ≥ 15
mask_both = mask_gap & ~np.isnan(R2te_all)

N_gap   = N_all[mask_gap]
gap     = R2gap_all[mask_gap]
N_r2    = N_all[mask_r2]
r2_tr   = R2tr_all[mask_r2]
N_both  = N_all[mask_both]
r2_te   = R2te_all[mask_both]

# ── Spearman ρ annotation (pre-computed from E3.1) ───────────────
RHO   = -1.0
P_VAL = "< 0.001"

# ── Style ────────────────────────────────────────────────────────
BLUE    = "#1f77b4"
ORANGE  = "#ff7f0e"
GREEN   = "#2ca02c"
RED     = "#d62728"
GRAY    = "#7f7f7f"
LBLUE   = "#aec7e8"

plt.rcParams.update({
    "font.family":  "DejaVu Sans",
    "font.size":    10,
    "axes.spines.top":   False,
    "axes.spines.right": False,
})

fig, axes = plt.subplots(1, 3, figsize=(14, 4.2))
fig.suptitle(
    "V3: KPI Forecast Inflation — Overfitting Across Sample Sizes",
    fontsize=12, fontweight="bold", y=1.02,
)

# ════════════════════════════════════════════════════════════════
#  Panel (a): Overfitting Gap vs N
# ════════════════════════════════════════════════════════════════
ax = axes[0]
ax.plot(N_gap, gap, "o-", color=BLUE, linewidth=2, markersize=6, label="Gap (Train − Test R²)")
ax.axhline(0, color=GRAY, linewidth=0.8, linestyle="--")
ax.fill_between(N_gap, 0, gap, alpha=0.12, color=BLUE)

# Regime boundaries
ax.axvline(10,  color=RED,    linewidth=1.0, linestyle=":", alpha=0.7)
ax.axvline(100, color=GREEN,  linewidth=1.0, linestyle=":", alpha=0.7)
ax.text(10,  gap.max() * 0.95, "degenerate|overfit", rotation=90,
        fontsize=7, color=RED,   va="top", ha="right")
ax.text(100, gap.max() * 0.95, "overfit|reasonable",  rotation=90,
        fontsize=7, color=GREEN, va="top", ha="right")

ax.annotate(
    f"Spearman ρ = {RHO:.1f}\np {P_VAL}",
    xy=(N_gap[-1], gap[-1]), xytext=(200, gap.max() * 0.6),
    fontsize=9, color=BLUE,
    arrowprops=dict(arrowstyle="->", color=BLUE, lw=1),
)

ax.set_xlabel("Training samples N")
ax.set_ylabel("Overfitting gap (R²_train − R²_test)")
ax.set_title("(a) Overfitting gap vs N", fontsize=10)
ax.set_xscale("log")
ax.set_xticks([20, 30, 50, 100, 200, 300])
ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.grid(True, which="both", alpha=0.2)
ax.legend(fontsize=8)

# ════════════════════════════════════════════════════════════════
#  Panel (b): Train R² vs Test R² with guard threshold
# ════════════════════════════════════════════════════════════════
ax = axes[1]
# Train R² (available from N=15)
ax.plot(N_r2, r2_tr, "s-", color=ORANGE, linewidth=2, markersize=6, label="Train R²")
# Test R² (available from N=20)
ax.plot(N_both, r2_te, "^-", color=RED, linewidth=2, markersize=6, label="Test R²")

# R² guard threshold line at -0.5
GUARD = -0.5
ax.axhline(GUARD, color=GREEN, linewidth=1.5, linestyle="--", label=f"R² guard ({GUARD})")
ax.fill_between(
    [N_all.min(), N_all.max()], GUARD, min(r2_te.min() if len(r2_te) else GUARD, -2.5),
    alpha=0.06, color=RED, label="Blocked region (Test R² < guard)"
)

# Mark N values where test R² falls below guard
blocked_N = N_both[r2_te < GUARD]
blocked_R2 = r2_te[r2_te < GUARD]
if len(blocked_N):
    ax.scatter(blocked_N, blocked_R2, marker="x", s=80, color=RED,
               zorder=5, label=f"Blocked ({len(blocked_N)} points)")

ax.set_xlabel("Training samples N")
ax.set_ylabel("R²")
ax.set_title("(b) Train vs Test R² (R²-guard threshold)", fontsize=10)
ax.set_xscale("log")
ax.set_xticks([15, 20, 30, 50, 100, 200, 300])
ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.set_ylim(bottom=min(-2.5, r2_te.min() - 0.2) if len(r2_te) else -3)
ax.axhline(0, color=GRAY, linewidth=0.6, linestyle=":")
ax.grid(True, which="both", alpha=0.2)
ax.legend(fontsize=7.5, loc="lower right")

# ════════════════════════════════════════════════════════════════
#  Panel (c): Forecast Width W(N)
# ════════════════════════════════════════════════════════════════
ax = axes[2]
ax.plot(N_all, W_all, "D-", color=GREEN, linewidth=2, markersize=6, label="W(N) median")
ax.fill_between(N_all, 0, W_all, alpha=0.12, color=GREEN)

# Highlight degenerate regime (N ≤ 10, W = 0)
degen_mask = N_all <= 10
ax.scatter(N_all[degen_mask], W_all[degen_mask], marker="x", s=80, color=RED,
           zorder=5, label="W = 0 (degenerate)")

ax.axvline(10,  color=RED,   linewidth=1.0, linestyle=":", alpha=0.7)
ax.axvline(100, color=BLUE,  linewidth=1.0, linestyle=":", alpha=0.7)

ax.set_xlabel("Training samples N")
ax.set_ylabel("Forecast interval width W")
ax.set_title("(c) Forecast width W(N) vs N", fontsize=10)
ax.set_xscale("log")
ax.set_xticks([5, 10, 20, 50, 100, 200, 300])
ax.get_xaxis().set_major_formatter(matplotlib.ticker.ScalarFormatter())
ax.grid(True, which="both", alpha=0.2)
ax.legend(fontsize=8)

# ── Save ─────────────────────────────────────────────────────────
plt.tight_layout()
plt.savefig(OUTFILE, dpi=150, bbox_inches="tight")
print(f"[SAVED] {OUTFILE}")
