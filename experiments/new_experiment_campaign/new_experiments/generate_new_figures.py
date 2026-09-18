#!/usr/bin/env python3
"""
Generate new figures and tables from E7.7, E4.7, E4.8, E-Cross results.

Figures 9-12 and Tables 14-17 for the updated paper.

Run:  python generate_new_figures.py
"""
import json, csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

RESULTS = Path(__file__).parent / "results"
FIGS = RESULTS / "figures"
TBLS = RESULTS / "tables"
FIGS.mkdir(exist_ok=True, parents=True)
TBLS.mkdir(exist_ok=True, parents=True)

plt.rcParams.update({
    "font.family": "serif", "font.size": 11, "axes.titlesize": 13,
    "axes.labelsize": 12, "figure.dpi": 200, "savefig.bbox": "tight",
    "axes.grid": True, "grid.alpha": 0.3,
    "axes.spines.top": False, "axes.spines.right": False,
})
C_BLUE, C_RED, C_GREEN, C_ORANGE = "#1565C0", "#C62828", "#2E7D32", "#E65100"
C_GRAY, C_PURPLE = "#616161", "#6A1B9A"

def load(fname):
    p = RESULTS / fname
    if not p.exists():
        print(f"  [SKIP] {fname}")
        return None
    with open(p) as f:
        return json.load(f)

def write_csv(rows, headers, fname):
    p = TBLS / fname
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  [SAVED] {p}")


# ═══════════════════════════════════════
#  FIG. 9 — V7 Behavioral Comparison
# ═══════════════════════════════════════
def fig9():
    """Bar chart: success rate + escalation rate, contaminated vs clean."""
    print("\n  Fig. 9 — V7 Behavioral Comparison...")

    summary = load("e7_7_summary.json")
    if summary is None:
        # Try building from individual files
        conditions = {}
        for cond, fname in [("Contaminated", "e7_7a_contaminated.json"),
                             ("Clean", "e7_7b_clean.json"),
                             ("Contam. Explicit", "e7_7c_contaminated_explicit.json"),
                             ("Clean Explicit", "e7_7d_clean_explicit.json")]:
            data = load(fname)
            if data:
                n = len(data)
                conditions[cond] = {
                    "success": sum(1 for t in data if t.get("claims_success")) / n,
                    "escalation": sum(1 for t in data if t.get("escalates_in_session") or t.get("followup_escalates")) / n,
                    "n": n,
                }
        if not conditions:
            print("    No E7.7 data found")
            return
    else:
        conditions = {}
        for key, val in summary.items():
            if isinstance(val, dict) and "success_rate" in val:
                label = key.replace("_", " ").title()
                conditions[label] = {
                    "success": val["success_rate"],
                    "escalation": val["escalation_rate"],
                    "n": val["n_trials"],
                }

    if not conditions:
        return

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    labels = list(conditions.keys())
    x = np.arange(len(labels))
    w = 0.5

    # Panel (a): Success rate
    success_rates = [conditions[l]["success"] * 100 for l in labels]
    colors = [C_RED if "contam" in l.lower() else C_GREEN for l in labels]
    bars1 = ax1.bar(x, success_rates, w, color=colors, alpha=0.85, edgecolor="white", lw=1.5)
    for bar, val in zip(bars1, success_rates):
        ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1.5,
                f"{val:.0f}%", ha="center", fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=15, ha="right")
    ax1.set_ylabel("Rate (%)")
    ax1.set_title("(a) Agent Claims Success")
    ax1.set_ylim(0, 110)

    # Panel (b): Escalation rate
    esc_rates = [conditions[l]["escalation"] * 100 for l in labels]
    bars2 = ax2.bar(x, esc_rates, w, color=colors, alpha=0.85, edgecolor="white", lw=1.5)
    for bar, val in zip(bars2, esc_rates):
        ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1.5,
                f"{val:.0f}%", ha="center", fontsize=12, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=15, ha="right")
    ax2.set_ylabel("Rate (%)")
    ax2.set_title("(b) Agent Escalates Further")
    ax2.set_ylim(0, 110)

    fig.suptitle("Fig. 9: V7 Behavioral Comparison — Contaminated vs Clean Analytics",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / "fig9_v7_behavioral.png")
    plt.savefig(FIGS / "fig9_v7_behavioral.pdf")
    print(f"  [SAVED] fig9_v7_behavioral.png")
    plt.close()


# ═══════════════════════════════════════
#  FIG. 10 — V7 Agent Reasoning Excerpts
# ═══════════════════════════════════════
def fig10():
    """Side-by-side text boxes showing contaminated vs clean reasoning."""
    print("\n  Fig. 10 — V7 Reasoning Comparison...")

    contam = load("e7_7a_contaminated.json")
    clean = load("e7_7b_clean.json")
    if not contam or not clean:
        return

    # Find representative trials
    contam_success = next((t for t in contam if t.get("claims_success")), contam[0] if contam else None)
    clean_fail = next((t for t in clean if not t.get("claims_success")), clean[0] if clean else None)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    def format_answer(fa):
        if fa is None:
            return "(no final answer)"
        if isinstance(fa, dict):
            text = fa.get("summary", fa.get("result", fa.get("content", str(fa))))
        else:
            text = str(fa)
        # Truncate
        if len(text) > 300:
            text = text[:297] + "..."
        # Wrap
        words = text.split()
        lines, line = [], ""
        for w in words:
            if len(line) + len(w) > 50:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}" if line else w
        if line:
            lines.append(line)
        return "\n".join(lines[:8])

    for ax, trial, title, color in [
        (ax1, contam_success, "CONTAMINATED\n(agent sees Type P: ambr_dl_mean)", C_RED),
        (ax2, clean_fail, "CLEAN\n(agent sees only Type T fields)", C_GREEN),
    ]:
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")

        # Title box
        ax.add_patch(plt.Rectangle((0.02, 0.85), 0.96, 0.13, fill=True,
                                    facecolor=color, alpha=0.15, edgecolor=color, lw=2))
        ax.text(0.5, 0.92, title, ha="center", va="center", fontsize=11,
                fontweight="bold", color=color)

        # Content
        if trial:
            text = format_answer(trial.get("final_answer"))
            success = trial.get("claims_success", False)
            status = "CLAIMS SUCCESS ✓" if success else "DOES NOT CLAIM SUCCESS"
            status_color = C_RED if success else C_GREEN

            ax.text(0.05, 0.78, "Agent's Final Answer:", fontsize=10, fontweight="bold")
            ax.text(0.05, 0.72, text, fontsize=8, verticalalignment="top",
                    family="monospace", wrap=True,
                    bbox=dict(boxstyle="round,pad=0.5", facecolor="lightyellow", alpha=0.8))
            ax.text(0.5, 0.08, status, ha="center", fontsize=13,
                    fontweight="bold", color=status_color,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor=status_color, lw=2))

    plt.tight_layout()
    plt.savefig(FIGS / "fig10_v7_reasoning.png")
    plt.savefig(FIGS / "fig10_v7_reasoning.pdf")
    print(f"  [SAVED] fig10_v7_reasoning.png")
    plt.close()


# ═══════════════════════════════════════
#  FIG. 11 — V4 Autonomous Rate
# ═══════════════════════════════════════
def fig11():
    """Bar chart: decomposition rate across temperature and intent."""
    print("\n  Fig. 11 — V4 Autonomous Rate vs Configuration...")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Temperature data
    temp_data = load("e4_8a_temperature.json")
    if temp_data:
        temps = sorted(temp_data.keys())
        rates = [temp_data[t]["rate"] * 100 for t in temps]
        labels_t = [t for t in temps]
        # Add original T=0.1 result
        labels_t = ["T=0.1\n(original)"] + labels_t
        rates = [5.0] + rates  # 1/20 = 5%

        bars = ax1.bar(range(len(labels_t)), rates, color=[C_GRAY] + [C_BLUE]*len(temps),
                      alpha=0.85, edgecolor="white", lw=1.5)
        for bar, val in zip(bars, rates):
            ax1.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                    f"{val:.0f}%", ha="center", fontsize=11, fontweight="bold")
        ax1.set_xticks(range(len(labels_t)))
        ax1.set_xticklabels(labels_t)
        ax1.set_ylabel("Decomposition Rate (%)")
        ax1.set_title("(a) Temperature Variation")
        ax1.set_ylim(0, max(rates) * 1.3 + 5)

    # Intent data
    intent_data = load("e4_8b_intent_variation.json")
    if intent_data:
        intents = list(intent_data.keys())
        rates_i = [intent_data[k]["rate"] * 100 for k in intents]
        short_labels = [k[:12] for k in intents]

        bars2 = ax2.bar(range(len(intents)), rates_i,
                       color=[C_GRAY if k=="original" else C_ORANGE for k in intents],
                       alpha=0.85, edgecolor="white", lw=1.5)
        for bar, val in zip(bars2, rates_i):
            ax2.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 1,
                    f"{val:.0f}%", ha="center", fontsize=11, fontweight="bold")
        ax2.set_xticks(range(len(intents)))
        ax2.set_xticklabels(short_labels, rotation=15, ha="right")
        ax2.set_ylabel("Decomposition Rate (%)")
        ax2.set_title("(b) Intent Phrasing Variation")
        ax2.set_ylim(0, max(rates_i) * 1.3 + 5 if rates_i else 30)

    fig.suptitle("Fig. 11: V4 Autonomous Decomposition Rate vs Model Configuration",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / "fig11_v4_autonomous_rate.png")
    plt.savefig(FIGS / "fig11_v4_autonomous_rate.pdf")
    print(f"  [SAVED] fig11_v4_autonomous_rate.png")
    plt.close()


# ═══════════════════════════════════════
#  FIG. 12 — Cross-Vulnerability Evidence
# ═══════════════════════════════════════
def fig12():
    """Cross-vulnerability chain evidence."""
    print("\n  Fig. 12 — Cross-Vulnerability Chains...")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # V3→V7
    cross1 = load("e_cross_1_v3_amplifies_v7.json")
    if cross1:
        summary = cross1.get("summary_by_N", {})
        ns = sorted([int(v["n_samples"]) for v in summary.values()])
        rates = [summary[f"N={n}"]["rate"] * 100 for n in ns]

        ax1.bar(range(len(ns)), rates, color=[C_RED if n < 30 else C_BLUE for n in ns],
               alpha=0.85, tick_label=[f"N={n}" for n in ns], edgecolor="white", lw=1.5)
        for i, (n, r) in enumerate(zip(ns, rates)):
            ax1.text(i, r + 2, f"{r:.0f}%", ha="center", fontsize=11, fontweight="bold")
        ax1.set_ylabel("Agent Claims Success (%)")
        ax1.set_title("(a) V3 → V7: N Controls Self-Assessment Confidence")
        ax1.set_ylim(0, max(rates) * 1.3 + 10 if rates else 100)

    # V4→V7
    cross2 = load("e_cross_2_v4_triggers_v7.json")
    if cross2:
        trials = cross2.get("trials", [])
        labels = ["V4\n(decomp.)", "V7\n(self-eval)", "Claims\nSuccess", "Full\nChain"]
        counts = [
            sum(1 for t in trials if t.get("has_v4_decomposition")),
            sum(1 for t in trials if t.get("has_v7_self_eval")),
            sum(1 for t in trials if t.get("claims_success")),
            sum(1 for t in trials if t.get("v4_triggers_v7")),
        ]
        total = len(trials)
        rates_c = [c/total*100 if total > 0 else 0 for c in counts]
        colors = [C_BLUE, C_PURPLE, C_ORANGE, C_RED]

        ax2.bar(range(len(labels)), rates_c, color=colors, alpha=0.85,
               tick_label=labels, edgecolor="white", lw=1.5)
        for i, r in enumerate(rates_c):
            ax2.text(i, r + 2, f"{r:.0f}%\n({counts[i]}/{total})",
                    ha="center", fontsize=10, fontweight="bold")
        ax2.set_ylabel("Rate (%)")
        ax2.set_title(f"(b) V4 → V7: Decomposition Triggers Self-Evaluation\n({total} trials)")
        ax2.set_ylim(0, 110)

    fig.suptitle("Fig. 12: Cross-Vulnerability Chain Evidence",
                 fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    plt.savefig(FIGS / "fig12_cross_vulnerability.png")
    plt.savefig(FIGS / "fig12_cross_vulnerability.pdf")
    print(f"  [SAVED] fig12_cross_vulnerability.png")
    plt.close()


# ═══════════════════════════════════════
#  TABLES
# ═══════════════════════════════════════
def table14():
    """Table 14: V7 behavioral trial summary."""
    print("\n  Table 14 — V7 Behavioral Trials...")
    rows = []
    for cond, fname in [("contaminated", "e7_7a_contaminated.json"),
                         ("clean", "e7_7b_clean.json"),
                         ("contam_explicit", "e7_7c_contaminated_explicit.json"),
                         ("clean_explicit", "e7_7d_clean_explicit.json")]:
        data = load(fname)
        if not data:
            continue
        for t in data:
            rows.append([
                t.get("trial", ""), cond,
                t.get("post_ambr_dl_mean", t.get("post_memory_util", "N/A")),
                "Yes" if t.get("claims_success") else "No",
                "Yes" if t.get("escalates_in_session") or t.get("followup_escalates") else "No",
                t.get("n_policy_calls", ""),
                t.get("n_kpi_calls", ""),
            ])
    if rows:
        write_csv(rows,
                  ["Trial", "Condition", "Key Metric Value", "Claims Success?",
                   "Escalates?", "Policy Calls", "KPI Calls"],
                  "table14_v7_behavioral.csv")

def table15():
    """Table 15: V4 proxy vs true quality (Definition 4)."""
    print("\n  Table 15 — V4 Definition 4...")
    data = load("e4_7c_definition4.json")
    if not data:
        return
    rows = []
    for r in data.get("runs", []):
        rows.append([
            r.get("run", ""),
            f"{r.get('R_baseline', ''):.1f}",
            f"{r.get('R_after', ''):.1f}",
            f"{r.get('Q_baseline', ''):.2f}" if r.get("Q_baseline") else "N/A",
            f"{r.get('Q_after', ''):.2f}" if r.get("Q_after") else "N/A",
            "Yes" if r.get("R_increased") else "No",
            "Yes" if r.get("Q_not_improved") else "No",
            "YES" if r.get("definition_4_satisfied") else "No",
        ])
    rows.append(["", "", "", "", "", "", "",
                 f"{data.get('definition_4_satisfied_count', 0)}/{len(data.get('runs', []))} satisfied"])
    write_csv(rows,
              ["Run", "R_baseline", "R_after", "Q_baseline", "Q_after",
               "R increased?", "Q not improved?", "Def. 4?"],
              "table15_v4_definition4.csv")

def table16():
    """Table 16: V4 autonomous robustness."""
    print("\n  Table 16 — V4 Autonomous Robustness...")
    rows = []

    # Original result
    rows.append(["T=0.1, original", 20, 1, "5.0%", "[0.9%, 23.6%]"])

    for fname, prefix in [("e4_8a_temperature.json", ""),
                           ("e4_8b_intent_variation.json", "T=0.1, ")]:
        data = load(fname)
        if not data:
            continue
        for key, val in data.items():
            if isinstance(val, dict) and "rate" in val:
                n = val.get("total", 0)
                s = val.get("successes", 0)
                rate = f"{val['rate']*100:.1f}%"
                # Wilson CI
                if n > 0:
                    from scipy.stats import norm
                    z = 1.96
                    p_hat = s / n
                    denom = 1 + z**2/n
                    center = (p_hat + z**2/(2*n)) / denom
                    spread = z * np.sqrt((p_hat*(1-p_hat) + z**2/(4*n))/n) / denom
                    ci = f"[{max(0,center-spread)*100:.1f}%, {min(1,center+spread)*100:.1f}%]"
                else:
                    ci = "N/A"
                label = f"{prefix}{key}" if prefix else key
                rows.append([label, n, s, rate, ci])

    if rows:
        write_csv(rows,
                  ["Condition", "Trials", "Successes", "Rate", "95% CI (Wilson)"],
                  "table16_v4_robustness.csv")

def table17():
    """Table 17: Cross-vulnerability interaction evidence."""
    print("\n  Table 17 — Cross-Vulnerability Interactions...")
    rows = []

    cross1 = load("e_cross_1_v3_amplifies_v7.json")
    if cross1:
        for key, val in cross1.get("summary_by_N", {}).items():
            rows.append([
                "V3→V7", key,
                f"{val['successes']}/{val['total']}",
                f"{val['rate']*100:.0f}%",
                "V3 controls V7 self-assessment confidence",
            ])

    cross2 = load("e_cross_2_v4_triggers_v7.json")
    if cross2:
        chain = cross2.get("chain_demonstrated", 0)
        total = cross2.get("total_trials", 0)
        rows.append([
            "V4→V7", "Decomposition→Self-eval",
            f"{chain}/{total}",
            f"{chain/total*100:.0f}%" if total > 0 else "N/A",
            "V4 output feeds V7 wireheading circuit",
        ])

    if rows:
        write_csv(rows,
                  ["Chain", "Condition", "Evidence", "Rate", "Interpretation"],
                  "table17_cross_vulnerability.csv")


# ═══════════════════════════════════════
#  MASTER
# ═══════════════════════════════════════
def generate_all():
    print("\n" + "="*70)
    print("NEW FIGURE & TABLE GENERATION")
    print("="*70)
    fig9(); fig10(); fig11(); fig12()
    table14(); table15(); table16(); table17()
    print(f"\n  Outputs in {FIGS}/ and {TBLS}/")

if __name__ == "__main__":
    generate_all()
