#!/usr/bin/env python3
"""
Master Experiment Runner for Section 5 Methodology
═══════════════════════════════════════════════════

Usage:
  python run_all.py              # Run everything (V3→V4→V7)
  python run_all.py v3           # Run V3 only (~30 min, no LLM needed)
  python run_all.py v4           # Run V4 only (1-3 hours with LLM trials)
  python run_all.py v7           # Run V7 only (1-2 hours)
  python run_all.py v4.4         # Run just E4.4 (LLM autonomous trials)
  python run_all.py plots        # Generate all plots from saved results
  python run_all.py summary      # Print summary of all completed experiments

Prerequisites:
  1. Open5GS running with subscribers registered
  2. UERANSIM nr-gnb + nr-ue connected (uesimtun0 up)
  3. PALA collector running (~45 min for 500+ samples)
  4. Ollama serving llama3.1 (for V4 autonomous trials)

Results saved to: experiments/results/
"""
import sys, os, json
from pathlib import Path
from datetime import datetime

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


def run_v3():
    from v3_forecast.experiments import run_all_v3
    return run_all_v3()

def run_v4():
    from v4_decomposition.experiments import run_all_v4
    return run_all_v4()

def run_v4_4():
    from v4_decomposition.experiments import run_e4_4
    return run_e4_4()

def run_v7():
    from v7_wireheading.experiments import run_all_v7
    return run_all_v7()


def print_summary():
    """Print summary of all completed experiments."""
    results_dir = Path(__file__).parent / "results"
    print("\n" + "="*70)
    print("EXPERIMENT RESULTS SUMMARY")
    print("="*70)

    experiment_files = {
        "V3": [
            ("E3.1 Width Sensitivity", "e3_1_width_sensitivity.json", ["spearman_rho", "accepted"]),
            ("E3.2 Error Metrics", "e3_2_error_metrics.json", ["mae_monotonic_decreasing", "accepted"]),
            ("E3.3 Defense Bounds", "e3_3_defense_bounds.json", ["width_range_reduction"]),
            ("E3.4 R² Guard", "e3_4_r2_guard.json", ["defended_false_positive_rate", "accepted"]),
            ("E3.5 Amplification", "e3_5_amplification.json", ["type"]),
        ],
        "V4": [
            ("E4.1 Threshold β", "e4_1_threshold.json", ["beta"]),
            ("E4.2 Manual Decomp.", "e4_2_manual_decomposition.json", ["decomposition_successful"]),
            ("E4.3 Single-Step", "e4_3_single_step_control.json", ["single_step_blocked", "accepted"]),
            ("E4.4 LLM Autonomous", "e4_4_autonomous_trials.json", ["success_rate", "fisher_p_value", "accepted"]),
            ("E4.5 Ground Truth", "e4_5_ground_truth.json", ["ratio", "accepted"]),
            ("E4.6 Defense", "e4_6_defense.json", ["blocked_at_step", "accepted"]),
            ("Ablations", "e4_ablations.json", []),
        ],
        "V7": [
            ("E7.1 Baseline", "e7_1_baseline.json", ["kpi_baseline"]),
            ("E7.2 Policy Mod", "e7_2_policy_modification.json", ["target_ambr"]),
            ("E7.3 Propagation", "e7_3_propagation.json", ["type_p_propagated", "accepted"]),
            ("E7.4a Instrumentation", "e7_4a_instrumentation.json", ["pcf_metrics_contains_ambr"]),
            ("E7.4b Type P Removal", "e7_4b_type_p_removal.json", ["delta", "type_p_causal"]),
            ("E7.4c Discriminating", "e7_4c_discriminating.json", ["delta_diverge", "discriminating_evidence"]),
            ("E7.6 Defense", "e7_6_defense.json", ["accepted"]),
            ("Ablations", "e7_ablations.json", ["circuit_latency_s"]),
        ],
    }

    for vuln, exps in experiment_files.items():
        print(f"\n  ── {vuln} ──")
        for name, fname, keys in exps:
            path = results_dir / fname
            if path.exists():
                with open(path) as f:
                    data = json.load(f)
                key_vals = []
                for k in keys:
                    v = data.get(k, "N/A")
                    if isinstance(v, float):
                        key_vals.append(f"{k}={v:.4f}")
                    else:
                        key_vals.append(f"{k}={v}")
                status = "✓" if data.get("accepted", "N/A") == True else ("✗" if data.get("accepted") == False else "○")
                print(f"    {status} {name}: {', '.join(key_vals) if key_vals else 'completed'}")
            else:
                print(f"    - {name}: not yet run")


def generate_plots():
    """Generate all figures from saved results."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  matplotlib not available. Install with: pip install matplotlib")
        return

    results_dir = Path(__file__).parent / "results"

    # ── Fig. 6: V3 W(N) and error metrics ──
    e31_path = results_dir / "e3_1_sweep_data.csv"
    if e31_path.exists():
        import csv
        with open(e31_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        ns = [int(r["N"]) for r in rows]
        ws = [float(r["W_median"]) for r in rows]
        maes = [float(r["MAE_median"]) for r in rows]
        r2_trains = [float(r["R2_train_median"]) for r in rows if r["R2_train_median"]]
        r2_tests = [(int(r["N"]), float(r["R2_test_median"])) for r in rows if r["R2_test_median"]]

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        # Panel (a): W(N) vs N
        ax1.plot(ns, ws, "o-", color="#2196F3", linewidth=2, markersize=8)
        ax1.axvline(x=30, color="red", linestyle="--", alpha=0.7, label="Defense lower bound (N=30)")
        ax1.set_xlabel("n_samples (N)", fontsize=12)
        ax1.set_ylabel("Forecast Width W(N)", fontsize=12)
        ax1.set_title("(a) Forecast Width vs Sample Size", fontsize=13)
        ax1.set_xscale("log")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Panel (b): R² vs N
        if r2_tests:
            r2_ns = [x[0] for x in r2_tests]
            r2_vs = [x[1] for x in r2_tests]
            ax2.plot(r2_ns, r2_vs, "s-", color="#F44336", linewidth=2, markersize=8, label="R²_test")
        ax2.plot(ns[:len(r2_trains)], r2_trains, "^-", color="#4CAF50", linewidth=2, markersize=8, label="R²_train")
        ax2.axhline(y=0, color="gray", linestyle=":", alpha=0.5)
        ax2.axhline(y=-0.5, color="orange", linestyle="--", alpha=0.7, label="R² guard threshold")
        ax2.axvline(x=30, color="red", linestyle="--", alpha=0.7)
        ax2.set_xlabel("n_samples (N)", fontsize=12)
        ax2.set_ylabel("R² Score", fontsize=12)
        ax2.set_title("(b) Generalization Quality vs Sample Size", fontsize=13)
        ax2.set_xscale("log")
        ax2.legend()
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        fig_path = results_dir / "fig6_v3_width_and_r2.png"
        plt.savefig(fig_path, dpi=150, bbox_inches="tight")
        print(f"  [SAVED] {fig_path}")
        plt.close()

    # ── Fig. 2: V4 AMBR staircase ──
    e42_path = results_dir / "e4_2_manual_decomposition.json"
    if e42_path.exists():
        with open(e42_path) as f:
            data = json.load(f)
        steps = data.get("steps", [])
        if steps:
            fig, ax = plt.subplots(figsize=(10, 5))
            step_nums = [0] + [s["step"] for s in steps]
            ambrs = [data["original_ambr_dl"]] + [s["ambr_after"] or data["original_ambr_dl"] for s in steps]

            ax.step(step_nums, [a / 1e6 for a in ambrs], where="post", color="#2196F3", linewidth=2.5, label="Decomposed (k steps)")
            ax.axhline(y=data["original_ambr_dl"] * (1 + data["beta"]) / 1e6, color="red",
                      linestyle="--", linewidth=2, label=f"Single-step threshold (β={data['beta']:.2f})")
            ax.axhline(y=data["original_ambr_dl"] * (1 + data["delta_total"]) / 1e6, color="green",
                      linestyle=":", linewidth=2, label=f"Target Δ={data['delta_total']:.2f}")
            ax.set_xlabel("Decomposition Step", fontsize=12)
            ax.set_ylabel("AMBR (Mbps)", fontsize=12)
            ax.set_title("V4: AMBR Accumulation via Decomposition vs Single-Step Block", fontsize=13)
            ax.legend()
            ax.grid(True, alpha=0.3)

            fig_path = results_dir / "fig2_v4_staircase.png"
            plt.savefig(fig_path, dpi=150, bbox_inches="tight")
            print(f"  [SAVED] {fig_path}")
            plt.close()

    print("\n  Plot generation complete. Check results/ directory.")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else ["all"]

    print(f"\n{'#'*70}")
    print(f"#  PALA EXPERIMENT SUITE — Section 5 Methodology")
    print(f"#  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"#  Mode: {' '.join(args)}")
    print(f"{'#'*70}")

    for arg in args:
        if arg == "v3":
            run_v3()
        elif arg == "v4":
            run_v4()
        elif arg == "v4.4":
            run_v4_4()
        elif arg == "v7":
            run_v7()
        elif arg == "plots":
            generate_plots()
        elif arg == "summary":
            print_summary()
        elif arg == "all":
            print("\n  Execution order: V3 → V4 → V7 (per methodology)")
            run_v3()
            run_v4()
            run_v7()
            generate_plots()
            print_summary()
        else:
            print(f"  Unknown argument: {arg}")
            print("  Usage: python run_all.py [v3|v4|v4.4|v7|plots|summary|all]")

    print(f"\n{'#'*70}")
    print(f"#  Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*70}")
