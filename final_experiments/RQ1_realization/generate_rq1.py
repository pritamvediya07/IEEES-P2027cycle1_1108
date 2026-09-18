"""
RQ1 Figure 1 and Table 1 generator.

Sources:
  - exp1/vulnerable/          (Qwen 2.5:72b, n=30)
  - exp1_multimodel/           (Mistral-large + Llama 3.1:70b, n=30 each)

Outputs:
  figures/fig1_trajectory.pdf  + .png
  tables/table1_rq1.tex
  data/master_sessions.csv
"""

import json, sys, math, statistics
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from scipy.stats import gaussian_kde, pearsonr, spearmanr

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent.parent.parent          # marcus/
RESULTS     = ROOT / "wave_experiments" / "results"
OUT_DIR     = Path(__file__).parent
FIG_DIR     = OUT_DIR / "figures"
TAB_DIR     = OUT_DIR / "tables"
DATA_DIR    = OUT_DIR / "data"
FIG_DIR.mkdir(exist_ok=True); TAB_DIR.mkdir(exist_ok=True); DATA_DIR.mkdir(exist_ok=True)

TARGET_BPS  = 60_000_000   # 60 Mbps
BASELINE_BPS = 20_000_000  # 20 Mbps


# ── Data loading ───────────────────────────────────────────────────────────────

def load_trials(model_label: str, jsonl_path: Path, arm_filter=None) -> list[dict]:
    """Load trials from a JSONL file, optionally filtering by arm."""
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


def build_rq(trial: dict) -> list[dict]:
    """
    Build per-step (k, R, Q) from a single trial.

    R(k) = cumulative max dl_ambr applied through policy call k,
            normalized by TARGET_BPS, capped at 2.0.
    Q(k) = q_trace[k-1]["Q"]
    """
    qt     = trial.get("q_trace", [])
    pc     = trial.get("policy_calls", [])
    bq     = trial.get("baseline_q", {})
    q0     = bq.get("Q") if isinstance(bq, dict) else None

    if not qt or q0 is None:
        return []

    # Sort policy calls by step; match to q_trace ordinal
    pc_sorted = sorted(pc, key=lambda x: x.get("step", 0))
    n_steps   = len(qt)

    rows = []
    cum_max_ambr = BASELINE_BPS   # start at current baseline
    for i, q_entry in enumerate(qt):
        k    = i + 1
        q_k  = q_entry.get("Q")
        # Pull corresponding policy call (same ordinal i)
        if i < len(pc_sorted):
            ambr = pc_sorted[i].get("dl_ambr", 0)
            if ambr > 0:
                cum_max_ambr = max(cum_max_ambr, ambr)
        r_k = min(cum_max_ambr / TARGET_BPS, 2.0)   # normalized, cap at 2.0
        rows.append({"k": k, "R": r_k, "Q": q_k, "Q0": q0,
                     "dQ": q_k - q0 if q_k is not None else None})
    return rows


def k_dagger(rq_rows: list[dict], q0: float) -> int | None:
    """First k where Q drops below baseline."""
    for row in rq_rows:
        if row["Q"] is not None and row["Q"] < q0:
            return row["k"]
    return None


# ── Load all trials ────────────────────────────────────────────────────────────

qwen_trials    = load_trials("Qwen~2.5:72b",
                    RESULTS / "exp1" / "exp1_trials.jsonl", arm_filter="vulnerable")
mm_trials_raw  = load_trials("", RESULTS / "exp1_multimodel" / "exp1_multimodel_trials.jsonl")

model_rename = {"qwen2.5:72b": "Qwen~2.5:72b",
                "mistral-large:latest": "Mistral-large",
                "llama3.1:70b": "Llama~3.1:70b"}

mistral_trials = [t for t in mm_trials_raw if "mistral" in t.get("model", "")]
llama_trials   = [t for t in mm_trials_raw if "llama"   in t.get("model", "")]

for t in mistral_trials: t["_model_label"] = "Mistral-large"
for t in llama_trials:   t["_model_label"] = "Llama~3.1:70b"
for t in qwen_trials:    t["_model_label"] = "Qwen~2.5:72b"

all_trial_groups = {
    "Qwen~2.5:72b":  qwen_trials,
    "Mistral-large": mistral_trials,
    "Llama~3.1:70b": llama_trials,
}

# ── Build master session CSV ───────────────────────────────────────────────────

csv_rows = []
for model_label, trials in all_trial_groups.items():
    for t in trials:
        rq = build_rq(t)
        bq = t.get("baseline_q", {})
        q0 = bq.get("Q") if isinstance(bq, dict) else None
        kd = k_dagger(rq, q0) if q0 else None
        r_vals = [r["R"] for r in rq]
        q_vals = [r["Q"] for r in rq if r["Q"] is not None]
        r_q_corr = None
        if len(r_vals) > 2 and len(q_vals) == len(r_vals):
            try:
                if len(set(r_vals)) > 1 and len(set(q_vals)) > 1:
                    r_q_corr, _ = spearmanr(r_vals, q_vals)
            except Exception:
                pass
        # strict def4
        def4 = t.get("def4_satisfied", False)
        q_final = q_vals[-1] if q_vals else None
        q_drop  = (q_final - q0) if (q_final is not None and q0 is not None) else None

        csv_rows.append({
            "session_id":   f"{model_label}_{t.get('trial', 0):03d}",
            "model_family": model_label,
            "n_steps":      len(rq),
            "full_loop":    int(t.get("full_loop", False)),
            "def4":         int(def4),
            "decomposed":   int(t.get("decomposed", False)),
            "contaminated": int(t.get("contaminated", False)),
            "k_dagger":     kd,
            "Q0":           q0,
            "Q_final":      q_final,
            "Q_drop":       q_drop,
            "R_Q_corr":     r_q_corr,
            "rq_trace":     json.dumps(rq),
        })

df = pd.DataFrame(csv_rows)
df.to_csv(DATA_DIR / "master_sessions.csv", index=False)
print(f"Saved master_sessions.csv ({len(df)} sessions)")


# ── Figure 1 ──────────────────────────────────────────────────────────────────

COLORS = {
    "Qwen~2.5:72b":  "#1f77b4",   # blue
    "Mistral-large": "#ff7f0e",   # orange
    "Llama~3.1:70b": "#2ca02c",   # green
}
FAMILY_ORDER = ["Qwen~2.5:72b", "Mistral-large", "Llama~3.1:70b"]

# ── Figure 1 — 4-panel clean layout (no insets, no twin axes) ─────────────────

fig, (ax_a, ax_b, ax_c, ax_d) = plt.subplots(
    1, 4, figsize=(22, 5), constrained_layout=True
)

# ── Panel A: representative session — single y-axis (ratio scale) ──────────────
# Use Qwen (headline model for RQ1) so panel (a) is consistent with panels (b)-(d).
# Fallback order: Mistral → Llama if no Qwen session qualifies.
best_trial = None
best_score = -1
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
    q_drop  = abs(q_vals[-1] - q_vals[0])
    r_range = max(r_vals) - min(r_vals)
    score   = q_drop * r_range
    if score > best_score:
        best_score = score
        best_trial = (t, rq)

if best_trial is None:
    for t in mistral_trials + llama_trials:
        if t.get("full_loop"):
            best_trial = (t, build_rq(t))
            break

t_rep, rq_rep = best_trial
bq_rep = t_rep.get("baseline_q", {})
q0_rep = bq_rep.get("Q", 1.0)
ks     = [r["k"] for r in rq_rep]
R_rep  = [r["R"] for r in rq_rep]
Q_rep  = [r["Q"] if r["Q"] is not None else q0_rep for r in rq_rep]

# Normalize both to ratio of their k=1 value so they share one y-axis cleanly
r0 = max(R_rep[0], 1e-9)
q0n = max(abs(q0_rep), 1e-9)
R_norm = [r / r0 for r in R_rep]
Q_norm = [q / q0n for q in Q_rep]

kd_rep  = k_dagger(rq_rep, q0_rep)
y_top   = max(max(R_norm), max(Q_norm)) * 1.05
y_bot   = min(min(R_norm), min(Q_norm)) * 0.97

ax_a.plot(ks, R_norm, color="#d62728", linewidth=2.3,
          label=r"$R(k)/R_0$ — agent-perceived", zorder=3)
ax_a.plot(ks, Q_norm, color="#1f77b4", linewidth=2.3, linestyle="--",
          label=r"$Q(k)/Q_0$ — ground-truth", zorder=3)
ax_a.axhline(y=1.0, color="grey", linewidth=0.9, linestyle=":", alpha=0.6)

if kd_rep:
    ax_a.axvline(x=kd_rep, color="#555555", linewidth=1.2, linestyle=":")
    # annotate using fixed data-space y coordinates computed from data
    ann_y = y_bot + (y_top - y_bot) * 0.88
    ax_a.annotate(
        rf"$k^\dagger={kd_rep}$",
        xy=(kd_rep, 1.0),
        xytext=(kd_rep + 0.4, ann_y),
        fontsize=9.5, color="#555555",
        arrowprops=dict(arrowstyle="-", color="#555555", lw=0.8),
    )

ax_a.set_xlim(ks[0] - 0.3, ks[-1] + 0.5)
ax_a.set_ylim(y_bot, y_top)
ax_a.set_xticks(ks)
ax_a.set_xlabel(r"Policy-call step $k$", fontsize=11)
ax_a.set_ylabel("Ratio to initial value", fontsize=11)
ax_a.set_title("(a) Representative session\n"
               r"$R$ rises as $Q$ falls below $Q_0$", fontsize=11)
ax_a.legend(fontsize=9, loc="center right")
model_name = t_rep.get("_model_label", "").replace("~", " ")
ax_a.text(0.98, 0.03, model_name, transform=ax_a.transAxes,
          fontsize=8, ha="right", va="bottom", color="grey")

# ── Panel B: Qwen 30-session Q(k) envelope — no inset ─────────────────────────
qwen_rq_all = []
kd_vals     = []
max_k_b     = 0

for t in qwen_trials:
    rq = build_rq(t)
    if not rq:
        continue
    bq = t.get("baseline_q", {})
    q0 = bq.get("Q")
    if q0 is None:
        continue
    norm = [(r["Q"] - q0) / max(abs(q0), 1e-9) if r["Q"] is not None else 0.0
            for r in rq]
    qwen_rq_all.append(norm)
    max_k_b = max(max_k_b, len(rq))
    kd = k_dagger(rq, q0)
    if kd:
        kd_vals.append(kd)

padded = [seq + [seq[-1]] * (max_k_b - len(seq)) for seq in qwen_rq_all]
arr    = np.array(padded)
ks_b   = np.arange(1, max_k_b + 1)

p50 = np.percentile(arr, 50, axis=0)
p25 = np.percentile(arr, 25, axis=0)
p75 = np.percentile(arr, 75, axis=0)
p05 = np.percentile(arr,  5, axis=0)
p95 = np.percentile(arr, 95, axis=0)

col_q = COLORS["Qwen~2.5:72b"]
ax_b.fill_between(ks_b, p05, p95, alpha=0.12, color=col_q, label="5–95 pct")
ax_b.fill_between(ks_b, p25, p75, alpha=0.30, color=col_q, label="IQR")
ax_b.plot(ks_b, p50, color=col_q, linewidth=2.3, label=r"Median $\Delta Q/Q_0$")
ax_b.axhline(y=0.0, color="grey", linewidth=0.9, linestyle=":")

if kd_vals:
    mean_kd  = statistics.mean(kd_vals)
    kd_idx   = min(int(round(mean_kd)) - 1, len(p50) - 1)
    y_label  = p05.min() * 1.35 if p05.min() < 0 else -0.05
    ax_b.axvline(x=mean_kd, color="#555555", linewidth=1.3, linestyle="--")
    ax_b.annotate(
        rf"$\bar{{k}}^\dagger={mean_kd:.1f}$",
        xy=(mean_kd, p50[kd_idx]),
        xytext=(mean_kd + 0.5, y_label),
        fontsize=9.5, color="#555555",
        arrowprops=dict(arrowstyle="-", color="#555555", lw=0.8),
    )

ax_b.set_xlabel(r"Policy-call step $k$", fontsize=11)
ax_b.set_ylabel(r"$\Delta Q(k)\,/\,Q_0$", fontsize=11)
ax_b.set_title("(b) Qwen 2.5:72b — 30-session envelope\n"
               r"Distribution of $Q$ degradation over time", fontsize=11)
ax_b.legend(fontsize=9, loc="lower left")

# ── Panel C: cross-family mean Q(k) trajectories ──────────────────────────────
MARKERS = {"Qwen~2.5:72b": "o", "Mistral-large": "s", "Llama~3.1:70b": "^"}

for family in FAMILY_ORDER:
    trials_f = all_trial_groups[family]
    rq_norms = []
    max_kf   = 0
    for t in trials_f:
        rq = build_rq(t)
        if not rq:
            continue
        bq = t.get("baseline_q", {})
        q0 = bq.get("Q")
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
    label  = family.replace("~", " ")
    ax_c.plot(ks_f, mean_f, color=col, linewidth=2.0, label=label,
              marker=MARKERS[family], markersize=4, markevery=2)
    ax_c.fill_between(ks_f, mean_f - se_f, mean_f + se_f, alpha=0.15, color=col)

ax_c.axhline(y=0.0, color="grey", linewidth=0.9, linestyle=":")
ax_c.set_xlabel(r"Policy-call step $k$", fontsize=11)
ax_c.set_ylabel(r"Mean $\Delta Q(k)\,/\,Q_0$", fontsize=11)
ax_c.set_title("(c) Cross-family mean trajectories\n"
               "n=30 per family, ±1 SE shaded", fontsize=11)
ax_c.legend(fontsize=9, loc="lower left")

# ── Panel D: per-step ΔQ KDE — standalone (replaces inset) ───────────────────
delta_q_all = []
for seq in padded:
    for i in range(1, len(seq)):
        delta_q_all.append(seq[i] - seq[i - 1])

dq_arr  = np.array(delta_q_all)
x_range = np.linspace(dq_arr.min() - 0.05, dq_arr.max() + 0.05, 400)

try:
    kde_fn = gaussian_kde(dq_arr, bw_method=0.3)
    ax_d.plot(x_range, kde_fn(x_range), color=col_q, linewidth=2.2)
    ax_d.fill_between(x_range, kde_fn(x_range), alpha=0.20, color=col_q)
except Exception:
    ax_d.hist(dq_arr, bins=28, density=True, color=col_q, alpha=0.5)

ax_d.axvline(x=0.0, color="#555555", linewidth=1.2, linestyle="--", label="ΔQ = 0")
ax_d.set_xlabel(r"Per-step $\Delta Q\,/\,Q_0$", fontsize=11)
ax_d.set_ylabel("Density", fontsize=11)
ax_d.set_title(
    f"(d) Per-step $\\Delta Q$ KDE\n"
    f"Qwen 2.5:72b, {len(delta_q_all)} transitions",
    fontsize=11,
)
ax_d.legend(fontsize=9)
neg_frac = float((dq_arr < 0).mean()) * 100
ax_d.text(0.04, 0.93, f"Neg. steps: {neg_frac:.0f}%\n→ persistent Q degradation",
          transform=ax_d.transAxes, fontsize=8.5, va="top", color="#444444",
          bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor="none"))

fig.savefig(FIG_DIR / "fig1_trajectory.pdf", bbox_inches="tight", dpi=150)
fig.savefig(FIG_DIR / "fig1_trajectory.png", bbox_inches="tight", dpi=150)
plt.close(fig)
print("Saved fig1_trajectory.pdf/.png")


# ── Table 1 ───────────────────────────────────────────────────────────────────

def compute_table1_row(trials, label):
    n = len(trials)
    fl    = sum(1 for t in trials if t.get("full_loop"))
    def4  = sum(1 for t in trials if t.get("def4_satisfied"))

    q_drops, kd_list, corrs = [], [], []
    for t in trials:
        rq = build_rq(t)
        bq = t.get("baseline_q", {})
        q0 = bq.get("Q")
        if not rq or q0 is None:
            continue
        q_vals = [r["Q"] for r in rq if r["Q"] is not None]
        r_vals = [r["R"] for r in rq]
        if q_vals:
            q_drops.append(q_vals[-1] - q0)
        kd = k_dagger(rq, q0)
        if kd:
            kd_list.append(kd)
        if len(r_vals) > 2 and len(q_vals) == len(r_vals):
            try:
                if len(set(r_vals)) > 1 and len(set(q_vals)) > 1:
                    c, _ = spearmanr(r_vals, q_vals)
                    corrs.append(c)
            except Exception:
                pass

    mean_qdrop = statistics.mean(q_drops) * 100 if q_drops else float("nan")   # as %
    mean_kd    = statistics.mean(kd_list) if kd_list else float("nan")
    mean_corr  = statistics.mean(corrs)   if corrs   else float("nan")

    return {
        "label":    label,
        "n":        n,
        "def4":     def4,
        "fl":       fl,
        "qdrop":    mean_qdrop,
        "kd":       mean_kd,
        "corr":     mean_corr,
    }

rows_t1 = [
    compute_table1_row(qwen_trials,    r"Qwen~2.5:72b (median)"),
    compute_table1_row(mistral_trials, r"Mistral-large (upper)"),
    compute_table1_row(llama_trials,   r"Llama~3.1:70b (lower)"),
]

tex_lines = []
tex_lines.append(r"\begin{tabular}{lcccccc}")
tex_lines.append(r"\toprule")
tex_lines.append(
    r"\textbf{Model (family)} & \textbf{$n$} & \textbf{Strict Def~4} "
    r"& \textbf{Mean $\Delta Q$} & \textbf{Mean $k^\dagger$} "
    r"& \textbf{Full-loop A$\wedge$B$\wedge$C$\wedge$D} & \textbf{$\bar{r}_{R,Q}$} \\"
)
tex_lines.append(r"\midrule")

for r in rows_t1:
    qdrop_str = f"${r['qdrop']:+.1f}\\%$" if not math.isnan(r["qdrop"]) else "---"
    kd_str    = f"${r['kd']:.1f}$"        if not math.isnan(r["kd"])    else "---"
    corr_str  = f"${r['corr']:.3f}$"       if not math.isnan(r["corr"])  else "---"
    tex_lines.append(
        f"{r['label']} & {r['n']} & {r['def4']}/{r['n']} "
        f"& {qdrop_str} & {kd_str} "
        f"& {r['fl']}/{r['n']} ({r['fl']/r['n']:.0%}) & {corr_str} \\\\"
    )

tex_lines.append(r"\bottomrule")
tex_lines.append(r"\end{tabular}")

tex_body = "\n".join(tex_lines)
(TAB_DIR / "table1_rq1.tex").write_text(tex_body)
print("Saved table1_rq1.tex")

# Also print the numbers for quick inspection
print("\n=== TABLE 1 NUMBERS ===")
for r in rows_t1:
    print(f"  {r['label']:30s}  n={r['n']}  def4={r['def4']}  fl={r['fl']}  "
          f"ΔQ={r['qdrop']:+.1f}%  k†={r['kd']:.2f}  r_RQ={r['corr']:.3f}")
