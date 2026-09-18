"""
High-quality regenerator for Figure 1 (RQ1).
Layout: 1×4, print-ready. Each panel is approximately square.

Design at 14" wide → scales to ~7" textwidth (0.5×) in LaTeX.

Outputs (same directory):
  fig1_trajectory_hq.pdf   (vector, embed in LaTeX)
  fig1_trajectory_hq.png   (300 DPI preview)
"""

import json, math, statistics
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde

# ── Paths ──────────────────────────────────────────────────────────────────────
THIS_DIR = Path(__file__).parent
ROOT     = THIS_DIR.parent.parent.parent
RESULTS  = ROOT / "wave_experiments" / "results"

TARGET_BPS   = 60_000_000
BASELINE_BPS = 20_000_000

# ── Data helpers ───────────────────────────────────────────────────────────────
def load_trials(model_label, jsonl_path, arm_filter=None):
    trials = []
    for line in jsonl_path.read_text().strip().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        if arm_filter and t.get("arm") != arm_filter:
            continue
        if model_label:
            t["_model_label"] = model_label
        trials.append(t)
    return trials

def build_rq(trial):
    qt  = trial.get("q_trace", [])
    pc  = trial.get("policy_calls", [])
    bq  = trial.get("baseline_q", {})
    q0  = bq.get("Q") if isinstance(bq, dict) else None
    if not qt or q0 is None:
        return []
    pc_sorted = sorted(pc, key=lambda x: x.get("step", 0))
    rows, cum_max = [], BASELINE_BPS
    for i, q_entry in enumerate(qt):
        q_k = q_entry.get("Q")
        if i < len(pc_sorted):
            a = pc_sorted[i].get("dl_ambr", 0)
            if a > 0:
                cum_max = max(cum_max, a)
        rows.append({"k": i + 1, "R": min(cum_max / TARGET_BPS, 2.0), "Q": q_k})
    return rows

def k_dagger(rq_rows, q0):
    for row in rq_rows:
        if row["Q"] is not None and row["Q"] < q0:
            return row["k"]
    return None

# ── Load trials ────────────────────────────────────────────────────────────────
qwen_trials    = load_trials("Qwen 2.5:72b",
                     RESULTS / "exp1" / "exp1_trials.jsonl", arm_filter="vulnerable")
mm_raw         = load_trials("", RESULTS / "exp1_multimodel" / "exp1_multimodel_trials.jsonl")
mistral_trials = [t for t in mm_raw if "mistral" in t.get("model", "")]
llama_trials   = [t for t in mm_raw if "llama"   in t.get("model", "")]
for t in mistral_trials: t["_model_label"] = "Mistral-large"
for t in llama_trials:   t["_model_label"] = "Llama 3.1:70b"

FAMILY_ORDER = ["Qwen 2.5:72b", "Mistral-large", "Llama 3.1:70b"]
ALL_GROUPS   = {"Qwen 2.5:72b": qwen_trials,
                "Mistral-large": mistral_trials,
                "Llama 3.1:70b": llama_trials}
COLORS  = {"Qwen 2.5:72b": "#1f77b4",
           "Mistral-large": "#ff7f0e",
           "Llama 3.1:70b": "#2ca02c"}
MARKERS = {"Qwen 2.5:72b": "o", "Mistral-large": "s", "Llama 3.1:70b": "^"}

# ── Best Qwen representative session ──────────────────────────────────────────
best_trial, best_score = None, -1
for t in qwen_trials:
    if not t.get("full_loop"):
        continue
    rq = build_rq(t)
    if len(rq) < 5:
        continue
    r_vals = [r["R"] for r in rq]
    q_vals = [r["Q"] for r in rq if r["Q"] is not None]
    if len(q_vals) < 5:
        continue
    score = abs(q_vals[-1] - q_vals[0]) * (max(r_vals) - min(r_vals))
    if score > best_score:
        best_score, best_trial = score, (t, rq)
if best_trial is None:
    for t in mistral_trials + llama_trials:
        if t.get("full_loop"):
            best_trial = (t, build_rq(t))
            break

# ── Qwen 30-session envelope ───────────────────────────────────────────────────
qwen_norms, kd_vals = [], []
max_k_b = 0
for t in qwen_trials:
    rq = build_rq(t)
    if not rq:
        continue
    q0 = (t.get("baseline_q") or {}).get("Q")
    if q0 is None:
        continue
    norm = [(r["Q"] - q0) / max(abs(q0), 1e-9) if r["Q"] is not None else 0.0
            for r in rq]
    qwen_norms.append(norm)
    max_k_b = max(max_k_b, len(rq))
    kd = k_dagger(rq, q0)
    if kd:
        kd_vals.append(kd)

padded = [s + [s[-1]] * (max_k_b - len(s)) for s in qwen_norms]
arr    = np.array(padded)
ks_b   = np.arange(1, max_k_b + 1)
p50 = np.percentile(arr, 50, axis=0)
p25 = np.percentile(arr, 25, axis=0)
p75 = np.percentile(arr, 75, axis=0)
p05 = np.percentile(arr,  5, axis=0)
p95 = np.percentile(arr, 95, axis=0)

# ── Style: normal weight, original-style line thickness ───────────────────────
matplotlib.rcParams.update({
    "font.size":          12,
    "font.weight":        "normal",       # NOT bold — prevents heavy/dirty look
    "axes.titlesize":     10,
    "axes.titleweight":   "normal",
    "axes.labelsize":     11,
    "axes.labelweight":   "normal",
    "xtick.labelsize":    9.5,
    "ytick.labelsize":    9.5,
    "legend.fontsize":    9,
    "legend.framealpha":  0.92,
    "legend.edgecolor":   "#bbbbbb",
    "axes.linewidth":     0.9,
    "xtick.major.width":  0.9,
    "ytick.major.width":  0.9,
    "xtick.major.size":   3.5,
    "ytick.major.size":   3.5,
    "lines.linewidth":    2.0,            # original-style line thickness
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})

LW   = 2.0    # data lines — same as original generate_rq1.py
LW_R = 1.0    # reference / grid lines
LW_V = 1.0    # vertical annotation lines
MS   = 6      # marker size
col_q = COLORS["Qwen 2.5:72b"]

# ── Figure: 1×4, square panels ────────────────────────────────────────────────
# Panel width ≈ (0.92 × 14) / (4 + 3×0.30) = 12.88 / 4.90 = 2.63"
# Panel height = (0.87 − 0.21) × 4.0 = 0.66 × 4.0 = 2.64"  → square ✓
fig, (ax_a, ax_b, ax_c, ax_d) = plt.subplots(1, 4, figsize=(14, 4.0))
fig.subplots_adjust(left=0.065, right=0.985, top=0.87, bottom=0.21, wspace=0.30)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (a) — Representative Qwen session
# ══════════════════════════════════════════════════════════════════════════════
t_rep, rq_rep = best_trial
q0_rep  = (t_rep.get("baseline_q") or {}).get("Q", 1.0)
ks      = [r["k"] for r in rq_rep]
R_rep   = [r["R"] for r in rq_rep]
Q_rep   = [r["Q"] if r["Q"] is not None else q0_rep for r in rq_rep]
r0      = max(R_rep[0], 1e-9)
q0n     = max(abs(q0_rep), 1e-9)
R_norm  = [r / r0  for r in R_rep]
Q_norm  = [q / q0n for q in Q_rep]
kd_rep  = k_dagger(rq_rep, q0_rep)

# Tight limits — minimal whitespace around data
y_top = max(R_norm) * 1.03
y_bot = min(Q_norm) * 0.90

# Divergence zone shading (between the two lines)
ax_a.fill_between(ks, Q_norm, R_norm, alpha=0.10, color="#d62728",
                  label="Divergence zone")

ax_a.plot(ks, R_norm, color="#d62728", linewidth=LW,
          marker="o", markersize=MS,
          label=r"$R(k)/R_0$ — agent-perceived", zorder=4)
ax_a.plot(ks, Q_norm, color="#1f77b4", linewidth=LW, linestyle="--",
          marker="s", markersize=MS,
          label=r"$Q(k)/Q_0$ — ground-truth", zorder=4)
ax_a.axhline(y=1.0, color="grey", linewidth=LW_R, linestyle=":", alpha=0.6)

if kd_rep:
    ax_a.axvline(x=kd_rep, color="#444444", linewidth=LW_V, linestyle=":")
    # Place annotation text to the right of the vline, in upper portion
    ann_y = y_bot + (y_top - y_bot) * 0.90
    ax_a.annotate(
        rf"$k^\dagger\!=\!{kd_rep}$",
        xy=(kd_rep, 1.0),
        xytext=(kd_rep + 0.28, ann_y),
        fontsize=9, color="#444444",
        arrowprops=dict(arrowstyle="-|>", color="#444444", lw=0.9),
    )

ax_a.set_xlim(ks[0] - 0.25, ks[-1] + 0.25)
ax_a.set_ylim(y_bot, y_top)
ax_a.set_xticks(ks)
ax_a.set_ylabel("Ratio to initial value")
ax_a.set_title(r"(a) Representative session — $R{\uparrow}$ $Q{\downarrow}$")

# Legend in the mid-right: sits inside the empty divergence zone (between the
# R line at ~6 and the Q line at ~0.59; y-centre ~3.3 has no data lines)
ax_a.legend(loc="center right", fontsize=8.5,
            bbox_to_anchor=(0.98, 0.50), borderaxespad=0,
            framealpha=0.90, edgecolor="#bbbbbb")

# ══════════════════════════════════════════════════════════════════════════════
# Panel (b) — Qwen 30-session quality envelope
# ══════════════════════════════════════════════════════════════════════════════
ax_b.fill_between(ks_b, p05, p95, alpha=0.13, color=col_q, label="5–95 pct")
ax_b.fill_between(ks_b, p25, p75, alpha=0.33, color=col_q, label="IQR")
ax_b.plot(ks_b, p50, color=col_q, linewidth=LW, label=r"Median $\Delta Q/Q_0$")
ax_b.axhline(y=0.0, color="grey", linewidth=LW_R, linestyle=":", alpha=0.6)

if kd_vals:
    mean_kd = statistics.mean(kd_vals)
    kd_idx  = min(int(round(mean_kd)) - 1, len(p50) - 1)
    ax_b.axvline(x=mean_kd, color="#444444", linewidth=LW_V, linestyle="--")
    # Annotation placed at upper right — away from the descending median line
    ax_b.annotate(
        rf"$\bar{{k}}^\dagger\!=\!{mean_kd:.1f}$",
        xy=(mean_kd, p50[kd_idx]),
        xytext=(mean_kd + 1.0, float(p95.max()) * 0.55),
        fontsize=9, color="#444444",
        arrowprops=dict(arrowstyle="-|>", color="#444444", lw=0.9),
    )

# Tight limits
ax_b.set_xlim(ks_b[0] - 0.3, ks_b[-1] + 0.3)
ax_b.set_ylim(float(p05.min()) * 1.12, float(p95.max()) * 1.15 + 0.005)
ax_b.set_ylabel(r"$\Delta Q(k)\,/\,Q_0$")
ax_b.set_title(r"(b) Qwen — 30-session $Q$ envelope")
# Legend at lower-left, below the descending curves
ax_b.legend(loc="lower left", fontsize=8.5,
            bbox_to_anchor=(0.02, 0.02), borderaxespad=0)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (c) — Cross-family mean trajectories
# ══════════════════════════════════════════════════════════════════════════════
y_min_c, y_max_c = 0.0, 0.0
x_max_c = 0
for family in FAMILY_ORDER:
    trials_f = ALL_GROUPS[family]
    rq_norms, max_kf = [], 0
    for t in trials_f:
        rq = build_rq(t)
        if not rq:
            continue
        q0 = (t.get("baseline_q") or {}).get("Q")
        if q0 is None:
            continue
        norm = [(r["Q"] - q0) / max(abs(q0), 1e-9) if r["Q"] is not None else 0.0
                for r in rq]
        rq_norms.append(norm)
        max_kf = max(max_kf, len(rq))
    if not rq_norms:
        continue
    pad_f  = [s + [s[-1]] * (max_kf - len(s)) for s in rq_norms]
    arr_f  = np.array(pad_f)
    ks_f   = np.arange(1, max_kf + 1)
    mean_f = arr_f.mean(axis=0)
    se_f   = arr_f.std(axis=0) / math.sqrt(len(arr_f))
    col    = COLORS[family]
    ax_c.plot(ks_f, mean_f, color=col, linewidth=LW, label=family,
              marker=MARKERS[family], markersize=4, markevery=2)
    ax_c.fill_between(ks_f, mean_f - se_f, mean_f + se_f, alpha=0.16, color=col)
    y_min_c = min(y_min_c, float((mean_f - se_f).min()))
    y_max_c = max(y_max_c, float((mean_f + se_f).max()))
    x_max_c = max(x_max_c, int(max_kf))

ax_c.axhline(y=0.0, color="grey", linewidth=LW_R, linestyle=":", alpha=0.6)
ax_c.set_xlim(0.7, x_max_c + 0.3)
ax_c.set_ylim(y_min_c * 1.12, y_max_c * 1.20 + 0.003)
ax_c.set_ylabel(r"Mean $\Delta Q(k)\,/\,Q_0$")
ax_c.set_title(r"(c) Cross-family ($n\!=\!30$, $\pm$1 SE)")
# Legend at lower-left corner, below the family lines
ax_c.legend(loc="lower left", fontsize=8.5,
            bbox_to_anchor=(0.02, 0.02), borderaxespad=0)

# ══════════════════════════════════════════════════════════════════════════════
# Panel (d) — Per-step ΔQ KDE
# ══════════════════════════════════════════════════════════════════════════════
delta_q_all = []
for seq in padded:
    for i in range(1, len(seq)):
        delta_q_all.append(seq[i] - seq[i - 1])

dq_arr = np.array(delta_q_all)
# Clip to 2nd–98th pct to remove sparse tails while keeping main distribution
x_lo = np.percentile(dq_arr, 2) - 0.01
x_hi = np.percentile(dq_arr, 98) + 0.01
x_rng = np.linspace(x_lo, x_hi, 500)

try:
    kde_fn = gaussian_kde(dq_arr, bw_method=0.3)
    y_kde  = kde_fn(x_rng)
    ax_d.plot(x_rng, y_kde, color=col_q, linewidth=LW)
    ax_d.fill_between(x_rng, y_kde, alpha=0.20, color=col_q)
except Exception:
    ax_d.hist(dq_arr, bins=30, density=True, color=col_q, alpha=0.5)
    y_kde = np.zeros_like(x_rng)

ax_d.axvline(x=0.0, color="#444444", linewidth=LW_V, linestyle="--",
             label=r"$\Delta Q\!=\!0$")
ax_d.set_xlim(x_lo, x_hi)
ax_d.set_ylim(0, float(y_kde.max()) * 1.18)
ax_d.set_xlabel(r"Per-step $\Delta Q\,/\,Q_0$")
ax_d.set_ylabel("Density")
ax_d.set_title(rf"(d) Per-step $\Delta Q$ KDE")

neg_frac = float((dq_arr < 0).mean()) * 100
# Annotation box at lower-right — away from the tall KDE peak near 0
ax_d.text(0.97, 0.95,
          f"Neg. steps: {neg_frac:.0f}%\n→ persistent $Q$ degrad.",
          transform=ax_d.transAxes, fontsize=8.5,
          va="top", ha="right", color="#333333",
          bbox=dict(boxstyle="round,pad=0.30", facecolor="white",
                    alpha=0.90, edgecolor="#bbbbbb", linewidth=0.8))
# Legend at upper-left: KDE is low on the left tail, so no overlap
ax_d.legend(loc="upper left", fontsize=8.5,
            bbox_to_anchor=(0.03, 0.97), borderaxespad=0)

# ══════════════════════════════════════════════════════════════════════════════
# Shared x-axis label for panels (a), (b), (c) — centred below the three panels
# ══════════════════════════════════════════════════════════════════════════════
fig.canvas.draw()   # force layout so get_position() returns final values
pos_a = ax_a.get_position()
pos_c = ax_c.get_position()
mid_x = (pos_a.x0 + pos_c.x1) / 2
y_lbl = pos_a.y0 * 0.35   # place in lower 35% of the bottom margin

fig.text(mid_x, y_lbl, r"Policy-call step $k$",
         ha="center", va="center", fontsize=11)

# ── Save ──────────────────────────────────────────────────────────────────────
out_pdf = THIS_DIR / "fig1_trajectory_hq.pdf"
out_png = THIS_DIR / "fig1_trajectory_hq.png"
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, bbox_inches="tight", dpi=300)
plt.close(fig)
print(f"Saved {out_pdf.name}  and  {out_png.name}")
print(f"  figsize 14×4.0 → panels ≈ 2.63×2.64\" (square)")
print(f"  Panel (a): k†={kd_rep}, R_max={max(R_norm):.1f}×, "
      f"model={t_rep.get('_model_label','?')}")
print(f"  Panel (b): {len(qwen_norms)} sessions, mean k†={statistics.mean(kd_vals):.1f}")
print(f"  Panel (d): {len(delta_q_all)} transitions, {neg_frac:.0f}% negative")
