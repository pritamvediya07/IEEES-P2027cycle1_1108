"""
High-quality concentric-ring polar chart for Figure 3 (RQ3).
Matches fig1/fig2 HQ typography (font.size 12, normal weight, pdf.fonttype 42).

Layout
------
Six concentric ring zones, each with 3 sector bars (one per model family):

  Inner 4 rings — session blocking outcomes (scale 0–30 per ring):
    Ring 1  nearest centre   Neither regime blocks      deep-purple
    Ring 2                   Only cumulative blocks     forest-green
    Ring 3                   Only per-call blocks       vivid-orange
    Ring 4  outermost inner  Both regimes block         cobalt-blue

  Outer 2 rings — approval rates:
    Ring 5                   Per-call approval  (%)    teal
    Ring 6  outermost        Oversight gap  (pp)        crimson

Each ring has a light background arc (= full scale) + coloured value bar.
Reference dashed circles at the 15 / 50% midpoint of every ring.
Ring boundaries are drawn as thin grey circles.

Legend is split into 4 groups placed in the 4 figure corners.

Outputs (same directory):
  fig3_oversight_polar_hq.pdf
  fig3_oversight_polar_hq.png
"""

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ── Paths ──────────────────────────────────────────────────────────────────────
THIS_DIR  = Path(__file__).parent
DATA_FILE = THIS_DIR / ".." / "data" / "rq3_summary.json"

data     = json.loads(DATA_FILE.read_text())
families = data["families"]   # [Qwen 2.5:72b, Mistral-large, Llama 3.1:70b]

# ── Style — matches fig1/fig2 HQ ──────────────────────────────────────────────
matplotlib.rcParams.update({
    "font.size":          12,
    "font.weight":        "normal",
    "axes.titlesize":     10,
    "axes.titleweight":   "normal",
    "legend.fontsize":    8.5,
    "legend.framealpha":  0.93,
    "legend.edgecolor":   "#bbbbbb",
    "legend.title_fontsize": 9.0,
    "lines.linewidth":    1.5,
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})

# ── Palette — 6 fully distinct colors, no repeated shades ─────────────────────
#   Ring key : (rich color, background color, label)
RING_STYLE = {
    "neither":    ("#7d3c98", "#e8daef", "Neither regime blocks"),
    "only_cum":   ("#1e8449", "#d5f5e3", "Only cumulative blocks"),
    "only_pc":    ("#d35400", "#fdebd0", "Only per-call blocks"),
    "both_block": ("#1a5276", "#d6eaf8", "Both regimes block"),
    "per_call":   ("#117a65", "#d1f2eb", "Per-call approval rate (%)"),
    "gap":        ("#c0392b", "#fadbd8", "Oversight gap (+pp)"),
}

SEP_GREY  = "#c8c8c8"
LINE_GREY = "#dedede"

# ── Polar layout ───────────────────────────────────────────────────────────────
# Three 96°-wide sectors: Qwen top (90°), Mistral lower-left (210°), Llama lower-right (330°)
ANGLES   = np.deg2rad([90, 210, 330])
SECTOR_W = np.deg2rad(96)

# Ring radial extents  (centre → edge, from innermost to outermost)
# Gap between rings = 0.01
RH = 0.085   # inner ring height  (each of 4 inner rings)
OH = 0.175   # outer ring height  (each of 2 outer rings)

R0 = 0.09    # bottom of ring 1

INNER_RINGS = [
    # (fam_key, max_val, r_bot, r_top, ring_key)
    ("neither",    30, R0,             R0 + RH,         "neither"),
    ("only_cum",   30, R0 + RH + 0.01, R0 + 2*RH+0.01, "only_cum"),
    ("only_pc",    30, R0 + 2*RH+0.02, R0 + 3*RH+0.02, "only_pc"),
    ("both_block", 30, R0 + 3*RH+0.03, R0 + 4*RH+0.03, "both_block"),
]

R_SEP_BOT = R0 + 4*RH + 0.04
R_SEP_TOP = R_SEP_BOT + 0.025

R_OUT_START = R_SEP_TOP + 0.01

OUTER_RINGS = [
    # (fam_key, max_val, r_bot, r_top, ring_key)
    ("mean_pc",  1.0,  R_OUT_START,        R_OUT_START + OH,        "per_call"),
    ("delta_pp", 35.0, R_OUT_START + OH + 0.01, R_OUT_START + 2*OH + 0.01, "gap"),
]

# Compute exact radii
for t in INNER_RINGS:
    pass   # values already set above

R_OUTER_TOP = OUTER_RINGS[-1][3]   # top of outermost outer ring
RMAX        = R_OUTER_TOP + 0.28   # headroom for family labels + legend corners

# ── Figure ─────────────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(9.5, 9.5), subplot_kw={"projection": "polar"})
ax.set_rmax(RMAX)
ax.set_rticks([])
ax.grid(False)
ax.spines["polar"].set_visible(False)
ax.set_xticks([])
ax.set_ylim(0, RMAX)

theta_full = np.linspace(0, 2 * np.pi, 720)
gap_right  = np.deg2rad(30)    # right gap centre  (Qwen 90° ↔ Llama 330°)
gap_left   = np.deg2rad(150)   # left gap centre   (Qwen 90° ↔ Mistral 210°)
gap_bot    = np.deg2rad(270)   # bottom gap centre (Mistral 210° ↔ Llama 330°)

# ── Background: white centre disc and separator band ──────────────────────────
ax.fill_between(theta_full, 0, R0 * 0.88, color="white", zorder=5)
ax.fill_between(theta_full, R_SEP_BOT, R_SEP_TOP, color=SEP_GREY, zorder=3)

# ── Draw concentric reference circles and ring content ────────────────────────
all_rings = INNER_RINGS + OUTER_RINGS

for (fkey, max_val, r_bot, r_top, rkey) in all_rings:
    ring_h  = r_top - r_bot
    r_mid   = r_bot + 0.5 * ring_h
    rich_c  = RING_STYLE[rkey][0]
    bg_c    = RING_STYLE[rkey][1]

    # Ring boundary circles (solid, grey)
    ax.plot(theta_full, np.full_like(theta_full, r_bot),
            color=SEP_GREY, linewidth=0.9, zorder=2)
    ax.plot(theta_full, np.full_like(theta_full, r_top),
            color=SEP_GREY, linewidth=0.9, zorder=2)

    # Midpoint reference circle (dashed — marks 15/30 or 50%)
    ax.plot(theta_full, np.full_like(theta_full, r_mid),
            color="#bbbbbb", linewidth=0.8, linestyle="--", zorder=2)

    # Per-family bars
    for idx, fam in enumerate(families):
        ang = ANGLES[idx]

        # Retrieve value and convert to fraction
        raw = fam[fkey]
        if fkey == "mean_pc":
            frac = raw          # already 0–1
        else:
            frac = raw / max_val

        bar_h = frac * ring_h

        # Full-scale background arc (light colour)
        ax.bar(ang, ring_h, width=SECTOR_W, bottom=r_bot,
               color=bg_c, edgecolor=LINE_GREY,
               linewidth=0.4, zorder=3)

        # Value bar (rich colour)
        if bar_h > 1e-4:
            ax.bar(ang, bar_h, width=SECTOR_W, bottom=r_bot,
                   color=rich_c, alpha=0.88,
                   edgecolor="white", linewidth=0.5, zorder=4)

        # Numeric label — black text, placed just above bar tip in light bg area
        # (matches fig1/fig2 style: labels are always on a light background)
        if fkey == "mean_pc":
            lbl = f"{raw*100:.1f}%"
        elif fkey == "delta_pp":
            lbl = f"+{raw:.0f} pp"
        else:
            lbl = str(int(raw))

        if bar_h >= 0.008:
            r_lbl = r_bot + bar_h + ring_h * 0.12   # just above bar, in bg area
        else:
            r_lbl = r_bot + ring_h * 0.52            # centre of ring for zero bars

        ax.text(ang, r_lbl, lbl,
                ha="center", va="center",
                fontsize=10.5, color="#111111",
                fontweight="bold", zorder=6,
                bbox=dict(boxstyle="round,pad=0.13", facecolor="white",
                          alpha=0.82, edgecolor="none"))

# ── Scale tick labels in the right gap ────────────────────────────────────────
# Inner zone: "0", "15", "30" labels shared across all 4 rings
#   — "0" at the base of the innermost ring
#   — "30" at the top of the outermost inner ring
#   — "15" shown via the midpoint dashed circles; label placed at avg mid-height
r_in_bot = INNER_RINGS[0][2]
r_in_top = INNER_RINGS[-1][3]

# Inner zone: "15" at midpoint, "30" at top (skip "0" — too close to centre disc)
for r_mark, lbl in [
        (r_in_bot + 0.5*(r_in_top - r_in_bot), "15"),
        (r_in_top,                              "30"),
]:
    ax.text(gap_right, r_mark, lbl,
            ha="center", va="center",
            fontsize=9.5, color="#333333", fontweight="bold", zorder=6)

# Outer ring A (per-call): "50 %" at mid, "100 %" at top (skip "0%" — overlaps "30")
r_pc_bot, r_pc_top = OUTER_RINGS[0][2], OUTER_RINGS[0][3]
for r_mark, lbl in [
        (r_pc_bot + 0.5*(r_pc_top - r_pc_bot), "50 %"),
        (r_pc_top,                             "100 %"),
]:
    ax.text(gap_right, r_mark, lbl,
            ha="center", va="center",
            fontsize=9.0, color="#333333", fontweight="bold", zorder=6)

# Outer ring B (gap): "18 pp" at mid, "35 pp" at top (skip "0" — overlaps "100%")
r_gp_bot, r_gp_top = OUTER_RINGS[1][2], OUTER_RINGS[1][3]
for r_mark, lbl in [
        (r_gp_bot + 0.5*(r_gp_top - r_gp_bot), "18 pp"),
        (r_gp_top,                             "35 pp"),
]:
    ax.text(gap_right, r_mark, lbl,
            ha="center", va="center",
            fontsize=9.0, color="#333333", fontweight="bold", zorder=6)

# ── Zone labels in left and bottom gaps ───────────────────────────────────────
# Left gap — zone titles
ax.text(gap_left, (r_in_bot + r_in_top) * 0.5,
        "Session\nblocking\n(n = 30)",
        ha="center", va="center", fontsize=10, color="#222222",
        style="italic", zorder=4)

ax.text(gap_left, (OUTER_RINGS[0][2] + OUTER_RINGS[1][3]) * 0.5,
        "Approval\nrates",
        ha="center", va="center", fontsize=10, color="#222222",
        style="italic", zorder=4)

# Bottom gap — key finding (only_cum=0, neither=0)
ax.text(gap_bot, (r_in_bot + r_in_top) * 0.5,
        "Only-cum: 0 / 30\nNeither:     0 / 30\n(all families)",
        ha="center", va="center", fontsize=9.5, color="#222222",
        linespacing=1.45,
        bbox=dict(boxstyle="round,pad=0.30", facecolor="#f7f7f7",
                  edgecolor="#aaaaaa", linewidth=0.9),
        zorder=4)

# ── Family name labels outside the outer ring ─────────────────────────────────
for idx, fam in enumerate(families):
    ax.text(ANGLES[idx], R_OUTER_TOP + 0.10,
            fam["label"],
            ha="center", va="center",
            fontsize=11, fontweight="bold", color="#111111", zorder=7)

# ── Centre label ──────────────────────────────────────────────────────────────
ax.text(0, 0, "Exp 3\nRQ3\nn = 30",
        ha="center", va="center",
        fontsize=11, color="#111111", fontweight="bold", zorder=8)

# ── Four-corner legends ────────────────────────────────────────────────────────
def make_patch(rkey, label=None):
    c   = RING_STYLE[rkey][0]
    bgc = RING_STYLE[rkey][1]
    lbl = label or RING_STYLE[rkey][2]
    return mpatches.Patch(facecolor=c, alpha=0.88, edgecolor="white", label=lbl)

# ── TOP-LEFT: session-blocking rings with real data ───────────────────────────
leg1_handles = [make_patch("both_block"), make_patch("only_pc")]
leg1 = ax.legend(handles=leg1_handles,
                 loc="upper left", bbox_to_anchor=(0.01, 0.99),
                 fontsize=8.5, title="Blocking outcomes (inner)",
                 framealpha=0.93, edgecolor="#bbbbbb",
                 borderpad=0.6, labelspacing=0.4)
ax.add_artist(leg1)

# ── TOP-RIGHT: zero-count rings ───────────────────────────────────────────────
leg2_handles = [make_patch("only_cum"), make_patch("neither")]
leg2 = ax.legend(handles=leg2_handles,
                 loc="upper right", bbox_to_anchor=(0.99, 0.99),
                 fontsize=8.5, title="Zero-count outcomes (inner)",
                 framealpha=0.93, edgecolor="#bbbbbb",
                 borderpad=0.6, labelspacing=0.4)
ax.add_artist(leg2)

# ── BOTTOM-LEFT: approval rate rings ─────────────────────────────────────────
leg3_handles = [make_patch("per_call"), make_patch("gap")]
leg3 = ax.legend(handles=leg3_handles,
                 loc="lower left", bbox_to_anchor=(0.01, 0.01),
                 fontsize=8.5, title="Approval rates (outer, Wilcoxon p<0.001)",
                 framealpha=0.93, edgecolor="#bbbbbb",
                 borderpad=0.6, labelspacing=0.4)
ax.add_artist(leg3)

# ── BOTTOM-RIGHT: family sector layout ───────────────────────────────────────
fam_labels = [f["label"] for f in families]
sector_pos  = ["top sector (90°)", "lower-left (210°)", "lower-right (330°)"]
leg4_handles = [
    mpatches.Patch(facecolor="#aaaaaa", edgecolor="white",
                   label=f"{fl}  —  {sp}")
    for fl, sp in zip(fam_labels, sector_pos)
]
leg4 = ax.legend(handles=leg4_handles,
                 loc="lower right", bbox_to_anchor=(0.99, 0.01),
                 fontsize=8.5, title="Model family → sector",
                 framealpha=0.93, edgecolor="#bbbbbb",
                 borderpad=0.6, labelspacing=0.4)
ax.add_artist(leg4)

# ── Title ─────────────────────────────────────────────────────────────────────
fig.suptitle(
    r"Figure 3  —  Oversight failure: session blocking (inner rings, 0–30)"
    r"  ·  approval rates (outer rings)   $|$   RQ3, Exp 3, $n{=}30$ per family",
    fontsize=10, y=1.002, ha="center", color="#222222"
)

# ── Save ──────────────────────────────────────────────────────────────────────
fig.subplots_adjust(top=0.94, bottom=0.06, left=0.06, right=0.94)
out_pdf = THIS_DIR / "fig3_oversight_polar_hq.pdf"
out_png = THIS_DIR / "fig3_oversight_polar_hq.png"
fig.savefig(out_pdf, bbox_inches="tight")
fig.savefig(out_png, bbox_inches="tight", dpi=300)
plt.close(fig)

print(f"Saved  {out_pdf.name}  and  {out_png.name}")
print(f"  figsize 9.5 × 9.5 in  |  6 concentric rings  |  4-corner legends")
print(f"  Inner rings  scale 0–30:")
for fkey, mv, rb, rt, rk in INNER_RINGS:
    vals = [f[fkey] for f in families]
    print(f"    {rk:12s}  r={rb:.3f}–{rt:.3f}  vals={vals}")
print(f"  Outer rings:")
for fkey, mv, rb, rt, rk in OUTER_RINGS:
    if fkey == "mean_pc":
        vals = [f"{f[fkey]*100:.1f}%" for f in families]
    else:
        vals = [f"{f[fkey]:.1f} pp" for f in families]
    print(f"    {rk:12s}  r={rb:.3f}–{rt:.3f}  vals={vals}")
