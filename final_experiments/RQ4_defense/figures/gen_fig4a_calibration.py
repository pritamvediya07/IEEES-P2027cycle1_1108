"""Generates fig4a_calibration.pdf/png — panel (a) only (E[Q(k)] calibration curve).
HQ version: matches fig1/fig2 rcParams, spine cleanup, no monospace annotations.
"""
import json, os
from collections import defaultdict
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(BASE, "..", "..", "..")

def load_json(rel):
    with open(os.path.join(ROOT, "final_experiments", rel)) as f:
        return json.load(f)

exp6k  = load_json("exp6/kstar.json")
exp6p1 = load_json("exp6/phase1_summary.json")

KSTAR     = exp6k["k_star"]
K_DAGGERS = exp6k["k_daggers"]
MEAN_KD   = exp6k["mean_k_dagger"]
CV        = exp6k["cv"]
N_CALIB   = exp6k["n_sessions"]

kd_counts = defaultdict(int)
for kd in K_DAGGERS:
    kd_counts[kd] += 1

EQ_CURVE = exp6p1["eq_curve"]
k_vals   = [pt["k"] for pt in EQ_CURVE]
eq_means = [pt["eq_mean"] for pt in EQ_CURVE]
eq_ns    = [pt["n"] for pt in EQ_CURVE]
Q0_BASE  = EQ_CURVE[0]["eq_mean"]

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

BLUE  = "#1f77b4"
RED   = "#d62728"
DGREY = "#7f7f7f"

fig, ax_a = plt.subplots(1, 1, figsize=(8, 5.2))
fig.subplots_adjust(left=0.11, right=0.97, top=0.88, bottom=0.14)

ax_a.set_title(
    f"(a) E[Q(k)] calibration curve — Phase 1 (Exp 6), "
    f"n={N_CALIB} vulnerable sessions",
    fontsize=10,
)

ks = np.array(k_vals, dtype=float)
qs = np.array(eq_means)
sparse_start = next((i for i, n in enumerate(eq_ns) if n == 1), len(eq_ns))

# Solid segment (n ≥ 2)
ax_a.plot(ks[:sparse_start], qs[:sparse_start], "o-", color=BLUE,
          linewidth=2.0, markersize=7, zorder=5,
          label=r"$E[Q(k)]$ — $n{\geq}2$ observations")
ax_a.fill_between(ks[:sparse_start], qs[:sparse_start], alpha=0.12, color=BLUE)

# Dashed extension (n = 1)
ax_a.plot(ks[sparse_start - 1:], qs[sparse_start - 1:], "--",
          color=BLUE, linewidth=1.5, zorder=5, alpha=0.60, label="_nolegend_")
ax_a.fill_between(ks[sparse_start - 1:], qs[sparse_start - 1:],
                  alpha=0.05, color=BLUE)

# Hollow marker at first n=1 point
ax_a.plot([ks[sparse_start]], [qs[sparse_start]], "o",
          color=BLUE, markersize=9, zorder=6,
          markerfacecolor="white", markeredgewidth=2,
          label=r"$E[Q(k)]$ — $n{=}1$, single observation (dashed)")

# Baseline and threshold lines
ax_a.axhline(Q0_BASE, color=DGREY, linestyle=":", linewidth=1.3,
             label=f"$E[Q(0)]$ = {Q0_BASE:.3f}  (baseline)")
ax_a.axvline(KSTAR, color=RED, linestyle="--", linewidth=1.5, zorder=4,
             label=f"$k^{{\\dagger*}}$ = {KSTAR}  (calibrated threshold)")

# Per-point n labels
for k, q, n in zip(ks, qs, eq_ns):
    if n == 1:
        ax_a.annotate(
            "(n=1)", xy=(k, q), xytext=(k + 0.10, q + 0.025),
            fontsize=8, color=RED, ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.22", facecolor="#fff0f0",
                      edgecolor=RED, linewidth=0.8, alpha=0.9),
        )
    else:
        ax_a.annotate(f"n={n}", xy=(k, q), xytext=(k + 0.08, q + 0.018),
                      fontsize=8, color=DGREY, ha="left", va="bottom")

# k†ᵢ distribution summary — upper right, standard font
kd1 = kd_counts[1]; kd2 = kd_counts[2]; kd3 = kd_counts[3]
N_id = N_CALIB
kd_text = (
    f"$k^\\dagger_i$ distribution  (n={N_id} sessions)\n"
    f"  $k^\\dagger_i=1$: {kd1}/{N_id} ({kd1/N_id*100:.0f}%)   ← $k^{{\\dagger*}}={KSTAR}$\n"
    f"  $k^\\dagger_i=2$: {kd2}/{N_id} ({kd2/N_id*100:.0f}%)\n"
    f"  $k^\\dagger_i=3$: {kd3}/{N_id} ({kd3/N_id*100:.0f}%)\n"
    f"  CV = {CV:.3f}  (stable, <0.5 threshold)"
)
ax_a.text(0.97, 0.97, kd_text,
          transform=ax_a.transAxes, fontsize=7.5,
          va="top", ha="right", color="#444444",
          bbox=dict(boxstyle="round,pad=0.28", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.7))

ax_a.set_xlabel("Policy step $k$")
ax_a.set_ylabel("$E[Q(k)]$")
ax_a.set_xlim(-0.15, 3.35)
ax_a.set_ylim(0.52, 0.88)
ax_a.set_xticks([0, 1, 2, 3])
ax_a.set_yticks([0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85])
ax_a.legend(fontsize=10, loc="lower left",
            bbox_to_anchor=(0.02, 0.32), borderaxespad=0, framealpha=0.93)
ax_a.spines["right"].set_visible(False)
ax_a.spines["top"].set_visible(False)

# Footer note — below legend
ax_a.text(0.02, 0.03,
          "eq_curve from QProbe-instrumented subset of Phase 1; "
          "$k^{\\dagger*}$ derived from $k^\\dagger_i$ distribution (all sessions)",
          transform=ax_a.transAxes, fontsize=7, color=DGREY,
          va="bottom", ha="left", style="italic")

out_pdf = os.path.join(BASE, "fig4a_calibration.pdf")
out_png = os.path.join(BASE, "fig4a_calibration.png")
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, dpi=300, bbox_inches="tight")
plt.close(fig)
print(f"Saved fig4a_calibration.pdf  and  fig4a_calibration.png")
print(f"  k†* = {KSTAR},  k†_i distribution: 1→{kd1}, 2→{kd2}, 3→{kd3}")
print(f"  CV = {CV:.3f},  Q0 baseline = {Q0_BASE:.3f}")
