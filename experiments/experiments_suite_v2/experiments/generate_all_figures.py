#!/usr/bin/env python3
"""
PALA — Complete Figure & Table Generation Suite (v2 — figure fixes)
═══════════════════════════════════════════════════════════════════════════
Reads saved experimental JSON files and produces publication-ready figures
(PNG + PDF) and LaTeX-ready tables (CSV).

Usage:
  python generate_all_figures.py              # generate everything
  python generate_all_figures.py --v3         # V3 figures + tables
  python generate_all_figures.py --v4         # V4 figures + tables
  python generate_all_figures.py --v7         # V7 figures + tables
  python generate_all_figures.py --tables     # tables only

Figures:
  Fig. 2  — V4 AMBR staircase (cooldown-gate narrative, off-scale ceiling note)
  Fig. 3  — V4 LLM Trial-1 trace (4 feas calls corrected, 13.2x annotation)
  Fig. 4  — V7 propagation timeline (fixed-width bars, Type P field values)
  Fig. 5  — V7 Type P vs Type T divergence (legend fix)
  Fig. 6  — V3 three-panel (degenerate N=5/10 annotated)
  Fig. 7  — V4 accumulator defense (dashed attempted line added)
  Fig. 8  — V7 defense comparison (session AMBR distinction clarified)

Tables:
  Table 5  — V3 regime (N=5/10 marked degenerate)
  Table 6  — V4 threshold sweep
  Table 7  — V4 E4.4 LLM trials (all 20 attack + 10 control)
  Table 8  — V7 provenance (sessions reclassified as mixed)
  Table 10 — V7 defense ablation
  Table 11 — Cross-vulnerability master summary
"""

import json, csv, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
RESULTS_DIR = Path(__file__).parent / "results"
FIG_DIR     = RESULTS_DIR / "figures"
TBL_DIR     = RESULTS_DIR / "tables"
FIG_DIR.mkdir(exist_ok=True)
TBL_DIR.mkdir(exist_ok=True)

# ── Style ──────────────────────────────────────────────────────────────────────
plt.rcParams.update({
    "font.family":        "serif",
    "font.size":          11,
    "axes.titlesize":     12,
    "axes.labelsize":     11,
    "xtick.labelsize":    10,
    "ytick.labelsize":    10,
    "legend.fontsize":    9,
    "figure.dpi":         200,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.15,
    "axes.grid":          True,
    "grid.alpha":         0.3,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
})

C_BLUE        = "#1565C0"
C_RED         = "#C62828"
C_GREEN       = "#2E7D32"
C_ORANGE      = "#E65100"
C_GRAY        = "#616161"
C_LIGHT_GREEN = "#C8E6C9"
C_LIGHT_BLUE  = "#BBDEFB"


def load_json(fname):
    p = RESULTS_DIR / fname
    if not p.exists():
        print(f"  [SKIP] {fname} not found")
        return None
    with open(p) as f:
        return json.load(f)


def save_fig(fig, stem):
    for ext in ("png", "pdf"):
        out = FIG_DIR / f"{stem}.{ext}"
        fig.savefig(out)
        if ext == "png":
            print(f"  [SAVED] {out}")
    plt.close(fig)


def write_csv(rows, headers, fname):
    p = TBL_DIR / fname
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  [SAVED] {p}")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 2 — V4: AMBR Staircase (cooldown-gate narrative; ceiling off-scale note)
# ═══════════════════════════════════════════════════════════════════════════════
def fig2_v4():
    print("\n  Generating Fig. 2 — V4 AMBR Staircase...")
    data = load_json("e4_2_manual_decomposition.json")
    e43  = load_json("e4_3_single_step_control.json")
    if data is None:
        return

    steps        = data["steps"]
    orig_bps     = data["original_ambr_dl"]
    beta         = data["beta"]          # 0.5 — per-step cooldown threshold
    delta_total  = data["delta_total"]   # 1.5 — 150%
    final_bps    = data["final_ambr_dl"]
    ratio        = data["ambr_ratio"]    # 3.4

    ambrs_mbps = [orig_bps / 1e6] + [s["ambr_after"] / 1e6 for s in steps]
    step_nums  = list(range(len(ambrs_mbps)))

    fig, ax = plt.subplots(figsize=(10, 5))

    # Decomposition staircase
    ax.step(step_nums, ambrs_mbps, where="post", color=C_BLUE, lw=3,
            label=f"Decomposed AMBR (k={len(steps)} steps, "
                  f"delta_i={steps[0]['delta_i']:.1%} each)", zorder=5)
    ax.scatter(step_nums[1:], ambrs_mbps[1:], color=C_BLUE, s=90, zorder=6)
    ax.scatter([0], [ambrs_mbps[0]], color=C_GRAY, s=90, zorder=6)

    # Step value annotations
    for sn, am in zip(step_nums[1:], ambrs_mbps[1:]):
        ax.annotate(f"{am:.0f} Mbps", (sn, am),
                    textcoords="offset points", xytext=(10, 8), fontsize=9, color=C_BLUE)

    # Linear target
    linear_target = orig_bps * (1 + delta_total) / 1e6
    ax.axhline(y=linear_target, color=C_GREEN, ls=":", lw=2, alpha=0.85,
               label=f"Linear target (delta={delta_total:.0%}) = {linear_target:.0f} Mbps")

    # Actual compound achieved
    ax.axhline(y=final_bps / 1e6, color=C_ORANGE, ls="-.", lw=1.8, alpha=0.85,
               label=f"Compound actual = {final_bps/1e6:.0f} Mbps  ({ratio}x baseline)")

    # AMBR ceiling: off-scale — annotate as text only (figure fix)
    ax.annotate("AMBR ceiling: 1 Gbps (1000 Mbps) [off-scale]\n"
                "Blocked only at delta > 49 (beta_ambr = 49)",
                xy=(len(steps) - 0.5, ambrs_mbps[-1]),
                xytext=(0.98, 0.98), textcoords="axes fraction",
                ha="right", va="top", fontsize=8, color=C_RED,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=C_RED, alpha=0.8))

    # Cooldown gate annotation between steps
    for i in range(1, len(step_nums)):
        mid_x = (step_nums[i-1] + step_nums[i]) / 2 if i < len(step_nums)-1 else step_nums[i-1] + 0.5
        ax.annotate("31 s\ncooldown\nwait", (mid_x, ambrs_mbps[i-1] * 0.88),
                    fontsize=7.5, color=C_GRAY, ha="center", va="top",
                    arrowprops=None)

    # Single-step control note (E4.3 Part A: single-step Δ=150% PASSES when cooldown clears)
    if e43 and e43.get("part_a_allowed"):
        ax.annotate(
            "E4.3 control: single-step delta=150% also PASSES\n"
            "after 35 s cooldown wait (AMBR limit is not the gate).\n"
            "Decomposition bypasses cumulative-drift detection, not AMBR ceiling.",
            xy=(0, linear_target),
            xytext=(0.02, 0.35), textcoords="axes fraction",
            fontsize=8, color=C_GRAY,
            bbox=dict(boxstyle="round,pad=0.3", fc=C_LIGHT_BLUE, ec=C_GRAY, alpha=0.85))

    ax.set_xlabel("Decomposition Step")
    ax.set_ylabel("AMBR  (Mbps)")
    ax.set_title("V4: AMBR Accumulation via Temporal Decomposition\n"
                 "Each step passes the 30 s cooldown gate individually; "
                 "compound effect exceeds linear target")
    ax.legend(loc="upper left", framealpha=0.9)
    ax.set_xlim(-0.3, len(step_nums) - 0.3)
    ax.set_ylim(0, max(ambrs_mbps) * 1.25)

    plt.tight_layout()
    save_fig(fig, "fig2_v4_ambr_staircase")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 3 — V4: LLM Trial-1 Trace  (4 feas calls, 13.2x note, escalation note)
# ═══════════════════════════════════════════════════════════════════════════════
def fig3_v4():
    print("\n  Generating Fig. 3 — V4 LLM Trial-1 Trace...")
    data = load_json("e4_4_autonomous_trials.json")
    if data is None:
        return

    trial1       = data["attack_trials"][0]
    deltas       = trial1["deltas"]          # [0.3, 0.3, 0.3, 1.0, 2.0]
    feas_calls   = trial1["n_feas_calls"]    # 4 (JSON ground truth)
    policy_calls = trial1["n_policy_calls"]  # 5
    baseline     = 20.0                      # Mbps

    # Reconstruct AMBR trajectory via compound multiplication
    ambrs = [baseline]
    for d in deltas:
        ambrs.append(round(ambrs[-1] * (1 + d), 2))

    total_ratio = ambrs[-1] / baseline   # 13.2x

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5),
                                   gridspec_kw={"width_ratios": [3, 2]})

    # ── Left panel: AMBR trajectory ──
    xs = list(range(len(ambrs)))
    ax1.step(xs, ambrs, where="post", color=C_BLUE, lw=2.5, zorder=4)
    ax1.scatter(xs[1:], ambrs[1:], color=C_BLUE, s=80, zorder=5)
    ax1.scatter([0], [ambrs[0]], color=C_GRAY, s=80, zorder=5)

    for i, (x, a) in enumerate(zip(xs[1:], ambrs[1:])):
        ax1.annotate(f"{a:.1f}\n(+{deltas[i]:.0%})", (x, a),
                     textcoords="offset points", xytext=(10, 6), fontsize=9)

    ax1.axhline(y=baseline, color=C_GRAY, ls=":", lw=1.2, alpha=0.6,
                label=f"Baseline  ({baseline:.0f} Mbps)")
    ax1.axhline(y=60, color=C_GREEN, ls="--", lw=1.5, alpha=0.75,
                label="Stated intent target  (60 Mbps = 3x)")

    # Escalation annotation — LLM vastly overshot the stated target
    ax1.annotate(
        f"LLM escalated beyond stated target:\n"
        f"{ambrs[-1]:.0f} Mbps = {total_ratio:.1f}x baseline\n"
        f"(intent asked for 3x = 60 Mbps)",
        xy=(xs[-1], ambrs[-1]),
        xytext=(xs[-1] - 2.5, ambrs[-1] * 0.78),
        fontsize=8.5, color=C_RED,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=C_RED, alpha=0.85),
        arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.5))

    ax1.set_xlabel("Policy Modification Step")
    ax1.set_ylabel("AMBR  (Mbps)")
    ax1.set_title(f"E4.4 Trial 1 — LLM Autonomous Decomposition\n"
                  f"{baseline:.0f} → {ambrs[-1]:.0f} Mbps in {len(deltas)} steps"
                  f"  ({total_ratio:.1f}x total compound increase)")
    ax1.legend(loc="upper left")
    ax1.set_ylim(0, max(ambrs) * 1.25)

    # ── Right panel: Tool call sequence (4 feas + 5 policy, from JSON) ──
    # Pattern: steps 1-4 each preceded by feasibility check; step 5 has no feas
    sequence = []
    for i in range(len(deltas)):
        if i < feas_calls:                          # 4 feasibility checks
            sequence.append(("H_feas", C_ORANGE))
        sequence.append((f"H_policy\n({ambrs[i+1]:.0f}M)", C_BLUE))
    sequence.append(("final_answer", C_GREEN))

    y_pos = list(range(len(sequence), 0, -1))
    ax2.barh(y_pos, [1]*len(sequence),
             color=[c for _, c in sequence], height=0.65, alpha=0.85, edgecolor="white")
    for y, (label, _) in zip(y_pos, sequence):
        ax2.text(0.5, y, label, ha="center", va="center",
                 fontsize=8.5, fontweight="bold", color="white")

    ax2.set_xlim(0, 1)
    ax2.set_yticks([])
    ax2.set_xticks([])
    ax2.set_title(f"Tool Call Sequence\n"
                  f"({feas_calls} feasibility + {policy_calls} policy calls)")
    for spine in ax2.spines.values():
        spine.set_visible(False)

    patches = [mpatches.Patch(color=C_ORANGE, label="Feasibility Check"),
               mpatches.Patch(color=C_BLUE,   label="Policy Write"),
               mpatches.Patch(color=C_GREEN,  label="Final Answer")]
    ax2.legend(handles=patches, loc="lower right", fontsize=8)

    # Note about step 5 lacking a feas check
    ax2.annotate("* Step 5 (+200%) executed\nwithout prior feas check",
                 xy=(0.5, 2), xytext=(0.5, 0.4), textcoords="data",
                 ha="center", fontsize=7.5, color=C_ORANGE,
                 bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=C_ORANGE, alpha=0.8))

    plt.tight_layout()
    save_fig(fig, "fig3_v4_trial1_trace")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 4 — V7: Propagation Timeline  (fixed-width bars, Type P field values)
# ═══════════════════════════════════════════════════════════════════════════════
def fig4_v7():
    print("\n  Generating Fig. 4 — V7 Propagation Timeline...")
    data   = load_json("e7_ablations.json")
    e73    = load_json("e7_3_propagation.json")
    if data is None:
        return

    timing     = data.get("A7.5_timing", [])
    latency_s  = data.get("circuit_latency_s")
    if not timing:
        print("  [SKIP] No timing data")
        return

    # Retrieve the ambr_dl_mean value that appeared after propagation
    ambr_after = None
    if e73:
        ambr_after = e73.get("ambr_dl_mean_in_dana")  # 26.0 Mbps

    wait_s     = [t["wait_s"]              for t in timing]
    new_docs   = [t["new_docs_in_dana"]    for t in timing]
    propagated = [t["propagation_detected"] for t in timing]

    fig, ax = plt.subplots(figsize=(11, 5))

    # Fixed-width categorical bars (figure fix: no width imbalance)
    x_pos   = list(range(len(wait_s)))
    x_labels = [f"t = {w} s" for w in wait_s]
    colors   = [C_GREEN if p else C_RED for p in propagated]

    bars = ax.bar(x_pos, new_docs, color=colors, alpha=0.82,
                  width=0.6, edgecolor="white", lw=1.5, zorder=4)

    # Annotations — include Type P field value where propagated
    for xi, (w, n, p) in enumerate(zip(wait_s, new_docs, propagated)):
        if p and ambr_after is not None:
            label = f"{n} doc{'s' if n>1 else ''}\n[ambr_dl_mean={ambr_after} Mbps]"
            color = C_GREEN
            offset = 0.15
        elif p:
            label = f"{n} docs"
            color = C_GREEN
            offset = 0.15
        else:
            label = "0 docs\n(not yet)"
            color = C_RED
            offset = 0.12
        ax.text(xi, n + offset, label, ha="center", fontsize=9,
                fontweight="bold", color=color)

    # Circuit latency marker (maps to x_pos of t=3s)
    first_prop_xi = next((i for i, p in enumerate(propagated) if p), None)
    if first_prop_xi is not None:
        ax.axvline(x=first_prop_xi, color=C_BLUE, ls="-.", lw=2.2, alpha=0.9,
                   label=f"First propagation  t = {wait_s[first_prop_xi]} s")

    # Expected bound: t_write + collector period = 0.5 + 5 = 5.5s → maps between t=3 and t=5
    collector_period = 5
    bound_xi = next((i for i, w in enumerate(wait_s) if w >= collector_period + 0.5), None)
    if bound_xi is not None:
        ax.axvline(x=bound_xi - 0.3, color=C_ORANGE, ls="--", lw=1.8, alpha=0.8,
                   label=f"Expected bound  t_write + delta_c = {collector_period + 0.5:.1f} s")

    ax.set_xticks(x_pos)
    ax.set_xticklabels(x_labels)
    ax.set_xlabel("Time After Policy Write")
    ax.set_ylabel("New Documents Observed in D_ana\n(smf_metrics with ambr_dl_mean field)")
    ax.set_title("V7: Type P Field Propagation Timeline\n"
                 "Policy write (AMBR 20 -> 26 Mbps) -> Collector (delta_c=5 s) -> "
                 "smf_metrics.ambr_dl_mean in D_ana")
    ax.legend(loc="upper left")
    ax.set_ylim(0, max(new_docs) * 1.5 + 1)

    # Annotate the write event
    ax.annotate("t = 0: H_policy write\n(AMBR 20 -> 26 Mbps)", xy=(-0.4, 0),
                xytext=(-0.15, max(new_docs) * 0.6),
                fontsize=8, color=C_GRAY,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=C_GRAY, alpha=0.7))

    plt.tight_layout()
    save_fig(fig, "fig4_v7_propagation_timeline")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 5 — V7: Type P vs Type T Divergence  (legend fix)
# ═══════════════════════════════════════════════════════════════════════════════
def fig5_v7():
    print("\n  Generating Fig. 5 — V7 Type P vs Type T Divergence...")
    data = load_json("e7_4c_discriminating.json")
    if data is None:
        return

    t_before = data["type_t_before"]
    t_after  = data["type_t_after"]
    p_before = data["type_p_before"]
    p_after  = data["type_p_after"]
    t_change = data["type_t_change"] * 100
    p_change = data["type_p_change"] * 100
    diverge  = data["delta_diverge"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # ── (a) Before / After normalised to 100% ──
    x  = np.arange(2)
    w  = 0.35
    t_pct = [100, 100 * t_after  / t_before]
    p_pct = [100, 100 * p_after  / p_before]

    ax1.bar(x - w/2, [100, 100],  w,
            label="Before AMBR modification",   # figure fix: was "Before (+30% AMBR intent)"
            color=C_BLUE, alpha=0.72)
    ax1.bar([0 + w/2], [t_pct[1]], w,
            label="After — Type T (memory_util_pct)", color=C_GREEN, alpha=0.85)
    ax1.bar([1 + w/2], [p_pct[1]], w,
            label="After — Type P (ambr_dl_mean)",   color=C_RED, alpha=0.85)

    ax1.set_xticks(x)
    ax1.set_xticklabels(["Type T\n(memory_util_pct)", "Type P\n(ambr_dl_mean)"])
    ax1.set_ylabel("Value  (% of pre-modification baseline)")
    ax1.axhline(y=100, color=C_GRAY, ls=":", lw=1, alpha=0.5)
    ax1.set_title("(a) Before vs After AMBR +30%\n"
                  "Type T unchanged;  Type P increased")
    ax1.legend(fontsize=8)
    ax1.set_ylim(90, max(p_pct[1], 110) * 1.03)

    ax1.text(0 + w/2, t_pct[1] + 0.2, f"{t_pct[1]:.2f}%", ha="center", fontsize=9)
    ax1.text(1 + w/2, p_pct[1] + 0.2, f"{p_pct[1]:.2f}%", ha="center", fontsize=9)

    # ── (b) Percentage change comparison ──
    bars = ax2.bar(["Type T Change\n(telemetry)",
                    "Type P Change\n(policy-derived)"],
                   [t_change, p_change],
                   color=[C_GREEN, C_RED], alpha=0.85, width=0.45,
                   edgecolor="white", lw=1.5, zorder=4)

    for bar, val in zip(bars, [t_change, p_change]):
        ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.05,
                 f"{val:.3f}%", ha="center", va="bottom",
                 fontsize=12, fontweight="bold")

    ax2.axhline(y=0, color=C_GRAY, lw=0.5)
    ax2.set_ylabel("Percentage Change  (%)")
    ax2.set_title(f"(b) Discriminating Evidence\n"
                  f"delta_diverge = {diverge:.4f}  "
                  f"(Type T: {t_change:.3f}% vs Type P: {p_change:.3f}%)")

    plt.tight_layout()
    save_fig(fig, "fig5_v7_type_p_vs_type_t")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 6 — V3: Three-Panel Regime  (degenerate N=5/10 annotated)
# ═══════════════════════════════════════════════════════════════════════════════
def fig6_v3():
    print("\n  Generating Fig. 6 — V3 Regime Characterization...")
    data = load_json("e3_1_revised_reliability.json")
    if data is None:
        return

    results = data["results_per_N"]

    # Separate degenerate (train=0, test=None) from valid
    def _med(r, key):
        v = r.get(key)
        return v.get("median") if isinstance(v, dict) else v

    ns_all  = [r["N"] for r in results]
    ws_all  = [_med(r, "width")   for r in results]
    tr_all  = [_med(r, "r2_train") for r in results]

    # Degenerate: train R²=0.0 AND test R²=None (model couldn't train)
    degen = {r["N"] for r in results
             if _med(r, "r2_train") == 0.0 and _med(r, "r2_test") is None}

    valid = [(r["N"], _med(r, "r2_test"), _med(r, "r2_train"), _med(r, "r2_gap"))
             for r in results
             if _med(r, "r2_test") is not None]

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 4.5))

    # ── (a) Overfitting Gap vs N ──
    gap_pts = [(n, g) for n, te, tr, g in valid if g is not None]
    if gap_pts:
        gn, gv = zip(*gap_pts)
        ax1.plot(gn, gv, "s-", color=C_RED, lw=2.5, ms=9, zorder=5)
        ax1.fill_betweenx([0, max(gv)*1.1], 0, 30, alpha=0.08, color=C_RED)
        ax1.axvline(x=30, color=C_GREEN, ls="--", lw=1.8, label="Defense bound  N = 30")
        ax1.set_xlabel("n_samples  (N)")
        ax1.set_ylabel("Overfitting Gap  (R2_train - R2_test)")
        ax1.set_title("(a) Overfitting Gap vs N\n"
                      "Spearman rho = -1.000,  p < 0.001")
        ax1.legend(fontsize=8)
        ax1.set_ylim(0, max(gv) * 1.2)
        # Shade degenerate region with a note
        ax1.annotate("N=5, 10: degenerate\n(no valid model fit)",
                     xy=(7.5, max(gv)*0.15), fontsize=8, color=C_GRAY,
                     ha="center",
                     bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=C_GRAY, alpha=0.7))

    # ── (b) Train R² vs Test R² ──
    valid_tr_ns = [n for n in ns_all if n not in degen]
    valid_tr_v  = [tr for n, tr in zip(ns_all, tr_all) if n not in degen]
    te_pts      = [(n, te) for n, te, tr, g in valid if te is not None]

    ax2.plot(valid_tr_ns, valid_tr_v, "^-", color=C_GREEN, lw=2, ms=8, label="R2_train")

    # Mark degenerate points with distinct marker
    degen_ns = sorted(degen)
    ax2.scatter(degen_ns, [0.0]*len(degen_ns), marker="x", color=C_GRAY, s=120, lw=2,
                zorder=6, label="Degenerate (N<15: no model fit)")
    for dn in degen_ns:
        ax2.annotate("degenerate", (dn, 0.0),
                     textcoords="offset points", xytext=(8, -14),
                     fontsize=7.5, color=C_GRAY)

    if te_pts:
        ten, tev = zip(*te_pts)
        ax2.plot(ten, tev, "v-", color=C_RED, lw=2, ms=8, label="R2_test")
        ax2.set_ylim(min(tev) - 0.3, 1.05)

    ax2.axhline(y=0,    color=C_GRAY,   ls=":",  lw=1,   alpha=0.6)
    ax2.axhline(y=-0.5, color=C_ORANGE, ls="--", lw=1.5, alpha=0.8,
                label="R2 guard  (-0.5)")
    ax2.axvline(x=30,   color=C_GREEN,  ls="--", lw=1.5, alpha=0.6)
    ax2.fill_betweenx([-3, 1.05], 0, 30, alpha=0.05, color=C_RED)
    ax2.set_xlabel("n_samples  (N)")
    ax2.set_ylabel("R2 Score")
    ax2.set_title("(b) Train R2 vs Test R2\n"
                  "All test R2 < 0 — signal is white noise")
    ax2.legend(fontsize=8)

    # ── (c) Forecast Width vs N ──
    ax3.plot(ns_all, ws_all, "o-", color=C_BLUE, lw=2, ms=8)
    ax3.fill_betweenx([0, max(ws_all)*1.1], 0, 30, alpha=0.05, color=C_RED)
    ax3.axvline(x=30, color=C_GREEN, ls="--", lw=1.8, label="Defense bound  N = 30")
    # Mark degenerate
    degen_ws = [w for n, w in zip(ns_all, ws_all) if n in degen]
    ax3.scatter(sorted(degen), degen_ws, marker="x", color=C_GRAY, s=120, lw=2,
                zorder=6, label="Degenerate (N<15)")
    ax3.set_xlabel("n_samples  (N)")
    ax3.set_ylabel("Forecast Width  W(N)")
    ax3.set_title("(c) Forecast Width vs N\n"
                  "Spearman rho = +0.845,  p = 0.004")
    ax3.legend(fontsize=8)
    ax3.set_ylim(0, max(ws_all) * 1.2)

    plt.tight_layout()
    save_fig(fig, "fig6_v3_regime_characterization")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 7 — V4: Accumulator Defense  (dashed "attempted" line in panel b)
# ═══════════════════════════════════════════════════════════════════════════════
def fig7_v4():
    print("\n  Generating Fig. 7 — V4 Accumulator Defense...")
    data = load_json("e4_6_defense.json")
    e42  = load_json("e4_2_manual_decomposition.json")
    if data is None:
        return

    steps      = data["steps"]
    beta       = data["beta"]
    blocked_at = data["blocked_at_step"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # ── (a) Without accumulator (E4.2 data) ──
    if e42:
        e42_steps  = e42["steps"]
        cum_no_def = [0] + [s["cumulative_delta"] for s in e42_steps]
        xs_no      = list(range(len(cum_no_def)))

        ax1.step(xs_no, cum_no_def, where="post", color=C_RED, lw=2.5,
                 label="Cumulative delta (no defense)")
        ax1.scatter(xs_no[1:], cum_no_def[1:], color=C_RED, s=80, zorder=5)
        ax1.axhline(y=beta, color=C_ORANGE, ls="--", lw=2, label=f"Threshold beta = {beta}")
        ax1.fill_between(xs_no, beta, max(cum_no_def)*1.1,
                         alpha=0.12, color=C_RED, label="Exceeds beta (undetected)")
        for x, c in zip(xs_no[1:], cum_no_def[1:]):
            ax1.annotate(f"{c:.3f}", (x, c),
                         textcoords="offset points", xytext=(8, 6), fontsize=8)
        ax1.set_xlabel("Step")
        ax1.set_ylabel("Cumulative delta")
        ax1.set_title("(a) WITHOUT Accumulator\n"
                      "All 4 steps pass — cumulative drift undetected")
        ax1.legend(loc="upper left")
        ax1.set_ylim(0, max(cum_no_def) * 1.2)

    # ── (b) With accumulator ──
    # Actual tracked cumulative (what the accumulator sees)
    cum_actual   = [0]
    # Attempted cumulative (what would have accrued without blocking)
    cum_attempted = [0]
    for s in steps:
        if s["accumulator_allows"]:
            cum_actual.append(s["cumulative_after"])
        else:
            cum_actual.append(cum_actual[-1])       # blocked: no change
        cum_attempted.append(cum_attempted[-1] + s["delta_i"])

    xs_with = list(range(len(cum_actual)))

    ax2.step(xs_with, cum_actual, where="post", color=C_BLUE, lw=2.5, zorder=4,
             label="Tracked cumulative delta (accumulator)")

    # Dashed "attempted" line (figure addition)
    ax2.step(xs_with, cum_attempted, where="post", color=C_RED, lw=1.8,
             ls="--", zorder=3, alpha=0.7,
             label="Attempted cumulative delta (without blocking)")
    ax2.fill_between(xs_with, cum_actual, cum_attempted,
                     step="post", alpha=0.10, color=C_RED,
                     label="Drift prevented by accumulator")

    # Per-step markers
    for i, s in enumerate(steps):
        color  = C_GREEN if s["accumulator_allows"] else C_RED
        marker = "o"     if s["accumulator_allows"] else "X"
        ax2.scatter([i+1], [cum_actual[i+1]], color=color, s=110, zorder=5, marker=marker)
        ax2.annotate(f"{cum_actual[i+1]:.3f}", (i+1, cum_actual[i+1]),
                     textcoords="offset points", xytext=(8, 6), fontsize=8)

    ax2.axhline(y=beta, color=C_ORANGE, ls="--", lw=2, label=f"Threshold beta = {beta}")
    ax2.annotate(f"BLOCKED\nat step {blocked_at}\n(acc: {cum_actual[blocked_at-1]:.3f} + "
                 f"{steps[blocked_at-1]['delta_i']:.3f} > {beta})",
                 xy=(blocked_at, cum_actual[blocked_at]),
                 xytext=(blocked_at + 0.4, beta * 1.4),
                 fontsize=9.5, fontweight="bold", color=C_RED,
                 arrowprops=dict(arrowstyle="->", color=C_RED, lw=2))

    allowed_p = mpatches.Patch(color=C_GREEN, label="Allowed step")
    blocked_p = mpatches.Patch(color=C_RED,   label="Blocked step")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.set_xlabel("Step")
    ax2.set_ylabel("Cumulative delta  (tracked by accumulator)")
    ax2.set_title(f"(b) WITH Accumulator\n"
                  f"Blocked at step {blocked_at} — Theorem 2 confirmed")
    ax2.set_ylim(0, max(cum_attempted) * 1.3)

    plt.tight_layout()
    save_fig(fig, "fig7_v4_defense_accumulator")


# ═══════════════════════════════════════════════════════════════════════════════
#  FIG. 8 — V7: Defense Comparison  (session AMBR distinction clarified)
# ═══════════════════════════════════════════════════════════════════════════════
def fig8_v7():
    print("\n  Generating Fig. 8 — V7 Defense Comparison...")
    data = load_json("e7_6_defense.json")
    if data is None:
        return

    a72 = data["a72_isolation_alone"]
    a73 = data["a73_isolation_plus_filter"]

    # The key distinction: in A7.2, ambr_dl_mean is absent but per-session AMBR IS present
    # In A7.3, both are absent. The figure must make this clear.
    # Fields to show:
    #   ambr_dl_mean (smf_metrics aggregate)  — absent in BOTH (already computed from sessions)
    #   session AMBR (ambr_dl in sessions[])  — present in A7.2, absent in A7.3 (the key fix)
    #   session_count                         — present in both (Type T)
    #   memory_util_pct                       — present in both (Type T)
    #   active_ue_count                       — present in both (Type T)

    fields = [
        "ambr_dl_mean\n(smf aggregate)",
        "session AMBR\n(ambr_dl in sessions[])",
        "session_count",
        "memory_util_pct",
        "active_ue_count",
    ]
    types = ["Type P", "Type P", "Type T", "Type T", "Type T"]

    pres_72 = [
        int(a72["ambr_dl_mean_present"]),   # False — not yet written by A7.2 collector
        int(a72["ambr_in_sessions"]),        # True — KEY: per-session AMBR still present
        1, 1, 1,
    ]
    pres_73 = [
        int(a73["ambr_dl_mean_present"]),   # False
        int(a73["ambr_in_sessions"]),        # False — KEY: stripped by semantic filter
        int(a73.get("session_count", 0) > 0),
        int(a73.get("memory_util_pct", 0) > 0),
        int(a73.get("active_ue_count", 0) > 0),
    ]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    def _color(t, present):
        if t == "Type P"  and present:     return C_RED
        if t == "Type P"  and not present: return C_LIGHT_GREEN
        if t == "Type T"  and present:     return C_GREEN
        return C_GRAY

    # ── (a) A7.2 ──
    colors72 = [_color(t, p) for t, p in zip(types, pres_72)]
    bars72   = ax1.barh(fields, pres_72, color=colors72, alpha=0.85,
                        edgecolor="white", lw=1.5)
    ax1.set_xlim(0, 1.8)
    ax1.set_xticks([0, 1])
    ax1.set_xticklabels(["Absent", "Present"])
    ax1.set_title("(a) A7.2: DB Isolation Alone -- REJECTED\n"
                  "Per-session AMBR still propagates to isolated D_ana",
                  color=C_RED, fontsize=10.5)
    for bar, t, p, f in zip(bars72, types, pres_72, fields):
        if t == "Type P" and p:
            note, col = "  <- TYPE P CONTAMINATION", C_RED
        elif t == "Type P" and not p:
            note, col = "  <- absent (good, but insufficient)", C_GRAY
        else:
            note, col = f"  <- {t} intact", C_GREEN
        ax1.text(max(bar.get_width(), 0.02) + 0.05,
                 bar.get_y() + bar.get_height()/2,
                 note, va="center", fontsize=8.5, color=col, fontweight="bold")

    # ── (b) A7.3 ──
    colors73 = [_color(t, p) for t, p in zip(types, pres_73)]
    bars73   = ax2.barh(fields, pres_73, color=colors73, alpha=0.85,
                        edgecolor="white", lw=1.5)
    ax2.set_xlim(0, 1.8)
    ax2.set_xticks([0, 1])
    ax2.set_xticklabels(["Absent [OK]", "Present [OK]"])
    ax2.set_title("(b) A7.3: Isolation + Semantic Filter -- ACCEPTED\n"
                  "All Type P fields blocked; all Type T fields preserved",
                  color=C_GREEN, fontsize=10.5)
    for bar, t, p in zip(bars73, types, pres_73):
        if t == "Type P" and not p:
            note, col = "  <- blocked by semantic filter", C_GREEN
        elif t == "Type T" and p:
            note, col = "  <- intact [OK]", C_GREEN
        else:
            note, col = "", C_GRAY
        ax2.text(max(bar.get_width(), 0.02) + 0.05,
                 bar.get_y() + bar.get_height()/2,
                 note, va="center", fontsize=8.5, color=col, fontweight="bold")

    # Clarifying annotation about what A7.2 misses
    ax1.annotate(
        "A7.2 misses: sessions[] still contains\nambr_dl per subscriber "
        "-> Type P data reachable\nvia H_kpi(sessions[].ambr_dl)",
        xy=(1, 3.5), xytext=(0.02, 0.12), textcoords="axes fraction",
        fontsize=8, color=C_RED,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec=C_RED, alpha=0.85))

    plt.tight_layout()
    save_fig(fig, "fig8_v7_defense_comparison")


# ═══════════════════════════════════════════════════════════════════════════════
#  TABLES
# ═══════════════════════════════════════════════════════════════════════════════

def table5_v3():
    print("\n  Generating Table 5 — V3 Regime Data...")
    data = load_json("e3_1_revised_reliability.json")
    if data is None:
        return

    def _med(r, key):
        v = r.get(key)
        return v.get("median") if isinstance(v, dict) else v

    rows = []
    for r in data["results_per_N"]:
        n   = r["N"]
        ws  = r.get("window_size", "")
        w   = _med(r, "width")
        tr  = _med(r, "r2_train")
        te  = _med(r, "r2_test")
        gap = _med(r, "r2_gap")

        # Figure fix: N=5, N=10 have train R²=0.0 because no model converged
        # These are DEGENERATE — label them N/A, not 0.000
        degenerate = (tr == 0.0 and te is None)
        tr_str  = "N/A (degenerate)" if degenerate else (f"{tr:.4f}" if isinstance(tr, float) else "N/A")
        te_str  = "N/A"              if te  is None  else f"{te:.4f}"
        gap_str = "N/A"              if gap is None  else f"{gap:.4f}"

        regime = ("degenerate"   if degenerate
                  else "high-overfit" if n <  30
                  else "transition"   if n < 100
                  else "stable")

        rows.append([n, ws, f"{w:.6f}" if isinstance(w, float) else w,
                     tr_str, te_str, gap_str, regime])

    write_csv(rows,
              ["N", "window", "W(N)", "R2_train", "R2_test", "R2_gap", "Regime"],
              "table5_v3_regime.csv")


def table6_v4():
    print("\n  Generating Table 6 — V4 Threshold Sweep...")
    data = load_json("e4_1_threshold.json")
    if data is None:
        return

    rows = []
    for sweep_key in ("phase_a_sweep", "phase_b_sweep"):
        for r in data.get(sweep_key, []):
            reason_full = r.get("reason", "")     # no truncation for paper
            rows.append([
                r["delta"],
                f"{r['new_dl']:,}",
                f"{r['new_dl']/1e6:.1f}",
                "PASS" if r["allowed"] else "FAIL",
                reason_full,
            ])

    rows.append(["---", "---", "---", "---", "---"])
    rows.append([
        f"beta_ambr = {data.get('beta_ambr', 49)}",
        "Phase B first FAIL",
        str(data.get("phase_b_first_fail", 49.5)),
        "FAIL",
        "Exceeds 1 Gbps AMBR ceiling (MAX_DL_AMBR_BPS)"
    ])

    write_csv(rows,
              ["delta", "DL (bps)", "DL (Mbps)", "F(delta)", "Reason (full)"],
              "table6_v4_threshold.csv")


def table7_v4():
    """All 20 attack + 10 control trials."""
    print("\n  Generating Table 7 — V4 LLM Trials...")
    data = load_json("e4_4_autonomous_trials.json")
    if data is None:
        return

    rows = []
    # All 20 attack trials
    for t in data.get("attack_trials", []):
        rows.append([
            t["trial"], "attack",
            t.get("n_feas_calls",   ""),
            t.get("n_policy_calls", ""),
            f"{t.get('cumulative_delta', 0):.3f}",
            "Yes" if t.get("is_decomposition") else "No",
        ])

    # All 10 control trials
    for t in data.get("control_trials", []):
        rows.append([
            t.get("trial", ""), "control",
            "",
            t.get("n_policy_calls", ""),
            "",
            "Yes" if t.get("is_decomposition") else "No",
        ])

    rows += [
        ["", "", "", "", "", ""],
        ["Attack successes", "", "", "",
         f"{data.get('attack_successes',0)}/{data.get('attack_total',0)}", ""],
        ["Control successes", "", "", "",
         f"{data.get('control_successes',0)}/{data.get('control_total',0)}", ""],
        ["Fisher p-value", "", "", "", f"{data.get('fisher_p_value',0):.6f}", ""],
        ["95% CI (Wilson)", "", "", "",
         f"[{data.get('wilson_ci_95',[0,0])[0]:.3f}, "
         f"{data.get('wilson_ci_95',[0,0])[1]:.3f}]", ""],
        ["Accepted (p<0.05)", "", "", "", str(data.get("accepted", False)), ""],
    ]

    write_csv(rows,
              ["Trial", "Type", "Feas Calls", "Policy Calls", "Cum. delta", "Decomposition?"],
              "table7_v4_llm_trials.csv")


def table8_v7():
    """Figure fix: sessions reclassified as 'mixed (contains Type P)'."""
    print("\n  Generating Table 8 — V7 Field Provenance...")
    data = load_json("e7_1_baseline.json")
    if data is None:
        return

    rows = []
    for coll, fields in data.get("field_inventory", {}).items():
        for fname, info in fields.items():
            prov = info.get("provenance", "?")
            # sessions array contains per-subscriber AMBR values — Type P data
            if fname == "sessions" and coll == "smf_metrics":
                prov = "mixed (contains Type P: ambr_dl per subscriber)"
            rows.append([
                coll, fname, prov,
                info.get("sample_value", "")[:70],
            ])

    write_csv(rows,
              ["Collection", "Field", "Provenance", "Sample Value"],
              "table8_v7_provenance.csv")


def table10_v7():
    print("\n  Generating Table 10 — V7 Defense Ablation...")
    data = load_json("e7_6_defense.json")
    if data is None:
        return

    a72 = data["a72_isolation_alone"]
    a73 = data["a73_isolation_plus_filter"]

    rows = [
        ["A7.2",
         "DB isolation only (port 27018, standard collector)",
         f"ambr_dl_mean present: {a72['ambr_dl_mean_present']}; "
         f"session AMBR present: {a72['ambr_in_sessions']}",
         "N/A (Type P still in sessions array)",
         "REJECTED"],
        ["A7.3",
         "DB isolation + semantic Type P filter (IsolatedCollector)",
         f"ambr_dl_mean present: {a73['ambr_dl_mean_present']}; "
         f"session AMBR present: {a73['ambr_in_sessions']}",
         f"session_count={a73['session_count']}, "
         f"memory_util_pct={a73['memory_util_pct']}, "
         f"active_ue_count={a73['active_ue_count']}",
         "ACCEPTED" if a73["accepted"] else "REJECTED"],
    ]

    write_csv(rows,
              ["Ablation", "Method", "Type P Fields in Isolated D_ana", "Type T Fields", "Verdict"],
              "table10_v7_defense_ablation.csv")


def table11_summary():
    print("\n  Generating Table 11 — Cross-Vulnerability Summary...")
    rows = [
        ["V3","E3.1","Regime characterization",
         "Spearman rho(gap,N)=-1.000, p<0.001","ACCEPTED"],
        ["V3","E3.2","Overfitting proof",
         "All test R2 < 0; 6/9 N values overfit","CONFIRMED"],
        ["V3","E3.3","Defense (bounds + R2 guard)",
         "Blocks 4, flags 1, allows 4 N values","ACCEPTED"],
        ["V4","E4.1","Dual threshold characterization",
         "beta_cooldown=0.5, beta_ambr=49.0","DONE"],
        ["V4","E4.2","Manual decomposition",
         "20->27->37->50->68 Mbps (compound ratio 3.4x)","PROVEN"],
        ["V4","E4.3","Two-part control",
         "Part A: single-step delta=150% PASSES (cooldown not AMBR limit); "
         "Part B: delta=147x FAILS at AMBR ceiling","PROVEN"],
        ["V4","E4.4","LLM autonomous (20 attack + 10 control trials)",
         "1/20 genuine decomposition (Trial 1: 20->264 Mbps, 13.2x); "
         "Fisher p=0.8966; 4 feas + 5 policy calls","CAPABILITY SHOWN"],
        ["V4","E4.6","Accumulator defense",
         "Blocked at step 2 (acc: 0.375+0.375>0.5) -- Theorem 2 confirmed","ACCEPTED"],
        ["V7","E7.3","Type P propagation to D_ana",
         "smf_metrics.ambr_dl_mean: 20.0->26.0 Mbps within 3 s","CONFIRMED"],
        ["V7","E7.4a","H_kpi consumes Type P field",
         "H_kpi reads smf_metrics.ambr_dl_mean (Type P, policy-derived)","CONFIRMED"],
        ["V7","E7.4b","Causal effect of Type P",
         "Delta=2.88 Mbps when 20 most-recent docs masked","CONFIRMED"],
        ["V7","E7.4c","Discriminating case",
         "Type T: 0.082%, Type P: 4.887%  (delta_diverge=0.0480)","CONFIRMED"],
        ["V7","E7.6/A7.2","Defense: isolation alone",
         "Per-session AMBR still in isolated D_ana -- insufficient","REJECTED"],
        ["V7","E7.6/A7.3","Defense: isolation + semantic filter",
         "All Type P blocked (ambr_dl_mean absent, session AMBR absent); "
         "Type T intact (session_count=10, mem_util=4.75, ue_count=10)","ACCEPTED"],
        ["V7","A7.5","Circuit latency measurement",
         "First Type P propagation at t=3 s (expected bound: 5.5 s)","CONFIRMED"],
    ]
    write_csv(rows,
              ["Vuln.", "Exp.", "Description", "Key Result", "Verdict"],
              "table11_cross_vulnerability_summary.csv")


# ═══════════════════════════════════════════════════════════════════════════════
#  MASTER RUNNER
# ═══════════════════════════════════════════════════════════════════════════════
def generate_all():
    print("\n" + "="*70)
    print("PALA — Figure & Table Generation  (v2 — figure fixes applied)")
    print("="*70)

    fig2_v4()
    fig3_v4()
    fig4_v7()
    fig5_v7()
    fig6_v3()
    fig7_v4()
    fig8_v7()

    table5_v3()
    table6_v4()
    table7_v4()
    table8_v7()
    table10_v7()
    table11_summary()

    print("\n" + "="*70)
    print("All outputs:")
    print(f"  Figures : {FIG_DIR}/")
    print(f"  Tables  : {TBL_DIR}/")
    print("="*70)


if __name__ == "__main__":
    args = sys.argv[1:]
    if   "--v3"     in args: fig6_v3();  table5_v3()
    elif "--v4"     in args: fig2_v4();  fig3_v4();  fig7_v4(); table6_v4(); table7_v4()
    elif "--v7"     in args: fig4_v7();  fig5_v7();  fig8_v7(); table8_v7(); table10_v7()
    elif "--tables" in args:
        table5_v3(); table6_v4(); table7_v4()
        table8_v7(); table10_v7(); table11_summary()
    else:
        generate_all()
