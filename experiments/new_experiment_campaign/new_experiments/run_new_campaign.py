#!/usr/bin/env python3
"""
NEW EXPERIMENT CAMPAIGN — Master Runner
═══════════════════════════════════════

Usage:
  python run_new_campaign.py all          # Run everything (2 weeks)
  python run_new_campaign.py priority1    # E7.7a+b only (4 hours) — HIGHEST VALUE
  python run_new_campaign.py priority2    # E4.7c Definition 4 (2 hours)
  python run_new_campaign.py priority3    # E7.7c+d explicit (4 hours)
  python run_new_campaign.py priority4    # E4.8 autonomous robustness (12 hours)
  python run_new_campaign.py priority5    # E-Cross + E7.7 ablations (7 hours)
  python run_new_campaign.py priority6    # E4.7a UPF enforcement (1 hour)
  python run_new_campaign.py figures      # Generate all new figures/tables
  python run_new_campaign.py summary      # Print status of all experiments

Execution Order (by priority):
  Priority 1: E7.7a + E7.7b  (behavioral comparison — highest priority)
  Priority 2: E4.7c          (Definition 4 instantiation — overclaim fix)
  Priority 3: E7.7c + E7.7d  (explicit self-eval comparison)
  Priority 4: E4.8a + E4.8b  (autonomous robustness)
  Priority 5: E-Cross + E7.7 ablations
  Priority 6: E4.7a          (UPF enforcement)
"""
import sys, json
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

RESULTS = Path(__file__).parent / "results"
RESULTS.mkdir(exist_ok=True)


def priority1():
    """E7.7a + E7.7b: Behavioral comparison (contaminated vs clean)."""
    print("\n" + "#"*60)
    print("# PRIORITY 1: V7 Behavioral Comparison")
    print("#" + " "*58 + "#")
    print("# This is the SINGLE HIGHEST-VALUE experiment.")
    print("# It converts V7 from 'contamination exists' to")
    print("# 'contamination changes agent behavior.'")
    print("#"*60)
    from e7_7_behavioral import run_e7_7a, run_e7_7b, analyze_e7_7
    print("\n  Phase 1: Contaminated (standard collector)...")
    run_e7_7a()
    print("\n  Phase 2: Clean (IsolatedCollector — write_port=27017, no port 27018 needed)...")
    run_e7_7b()
    analyze_e7_7()


def priority2():
    """E4.7c: Definition 4 instantiation."""
    print("\n" + "#"*60)
    print("# PRIORITY 2: Definition 4 Instantiation")
    print("#"*60)
    from e4_7_end_to_end import run_e4_7c
    run_e4_7c()


def priority3():
    """E7.7c + E7.7d: Explicit self-evaluation."""
    print("\n" + "#"*60)
    print("# PRIORITY 3: Explicit Self-Evaluation Comparison")
    print("#"*60)
    from e7_7_behavioral import run_e7_7c, run_e7_7d, analyze_e7_7
    run_e7_7c()
    run_e7_7d()
    analyze_e7_7()


def priority4():
    """E4.8a + E4.8b: Autonomous robustness."""
    print("\n" + "#"*60)
    print("# PRIORITY 4: Autonomous Robustness")
    print("#"*60)
    from e4_8_autonomous import run_all_e4_8
    run_all_e4_8()


def priority5():
    """E-Cross + E7.7 ablations."""
    print("\n" + "#"*60)
    print("# PRIORITY 5: Cross-Vulnerability + Ablations")
    print("#"*60)
    from e_cross_vulnerability import run_all_cross
    from e7_7_behavioral import run_e7_7_ablation_a1, run_e7_7_ablation_a2, run_e7_7_ablation_a3
    run_all_cross()
    print("\n  E7.7 Ablations...")
    run_e7_7_ablation_a1()
    run_e7_7_ablation_a2()
    run_e7_7_ablation_a3()


def priority6():
    """E4.7a: UPF enforcement test."""
    print("\n" + "#"*60)
    print("# PRIORITY 6: UPF Enforcement Test")
    print("#"*60)
    from e4_7_end_to_end import run_e4_7a
    run_e4_7a()


def figures():
    """Generate all new figures and tables."""
    from generate_new_figures import generate_all
    generate_all()


def summary():
    """Print status of all new experiments."""
    print("\n" + "="*60)
    print("NEW EXPERIMENT CAMPAIGN — STATUS")
    print("="*60)

    experiments = [
        ("E7.7a", "e7_7a_contaminated.json", "V7 contaminated behavioral"),
        ("E7.7b", "e7_7b_clean.json", "V7 clean behavioral"),
        ("E7.7c", "e7_7c_contaminated_explicit.json", "V7 contaminated explicit"),
        ("E7.7d", "e7_7d_clean_explicit.json", "V7 clean explicit"),
        ("E7.7-A1", "e7_7_a1_type_t_query.json", "V7 Type T query ablation"),
        ("E7.7-A2", "e7_7_a2_v3_amplification.json", "V7 V3 amplification ablation"),
        ("E7.7-A3", "e7_7_a3_escalation_depth.json", "V7 escalation depth"),
        ("E7.7 Summary", "e7_7_summary.json", "V7 aggregate analysis"),
        ("E4.7a", "e4_7a_upf_enforcement.json", "V4 UPF enforcement"),
        ("E4.7c", "e4_7c_definition4.json", "V4 Definition 4"),
        ("E4.8a", "e4_8a_temperature.json", "V4 temperature variation"),
        ("E4.8b", "e4_8b_intent_variation.json", "V4 intent variation"),
        ("E4.8c", "e4_8c_defense_retest.json", "V4 defense re-test"),
        ("E-Cross-1", "e_cross_1_v3_amplifies_v7.json", "V3 amplifies V7"),
        ("E-Cross-2", "e_cross_2_v4_triggers_v7.json", "V4 triggers V7"),
    ]

    done = 0
    for exp_id, fname, desc in experiments:
        p = RESULTS / fname
        if p.exists():
            with open(p) as f:
                data = json.load(f)
            n = len(data) if isinstance(data, list) else "obj"
            print(f"  [DONE] {exp_id:12s} {desc:35s} ({n} entries)")
            done += 1
        else:
            print(f"  [    ] {exp_id:12s} {desc}")

    print(f"\n  Completed: {done}/{len(experiments)}")

    # Check figures
    fig_dir = RESULTS / "figures"
    if fig_dir.exists():
        figs = list(fig_dir.glob("*.png"))
        print(f"  Figures generated: {len(figs)}")


if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else ["summary"]

    print(f"\n{'#'*60}")
    print(f"# NEW EXPERIMENT CAMPAIGN — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"# Mode: {' '.join(args)}")
    print(f"{'#'*60}")

    def ablations_only():
        """E7.7 ablations only (A1+A2+A3) — skip cross-vulnerability."""
        print("\n" + "#"*60)
        print("# E7.7 ABLATIONS (A1 + A2 + A3)")
        print("#"*60)
        from e7_7_behavioral import run_e7_7_ablation_a1, run_e7_7_ablation_a2, run_e7_7_ablation_a3, analyze_e7_7
        run_e7_7_ablation_a1()
        run_e7_7_ablation_a2()
        run_e7_7_ablation_a3()
        analyze_e7_7()

    dispatch = {
        "priority1": priority1,
        "priority2": priority2,
        "priority3": priority3,
        "priority4": priority4,
        "priority5": priority5,
        "priority6": priority6,
        "ablations": ablations_only,
        "figures": figures,
        "summary": summary,
        "all": lambda: (priority1(), priority2(), priority3(),
                        priority4(), priority5(), priority6(), figures(), summary()),
    }

    for arg in args:
        fn = dispatch.get(arg)
        if fn:
            fn()
        else:
            print(f"  Unknown: {arg}")
            print(f"  Options: {', '.join(dispatch.keys())}")

    print(f"\n{'#'*60}")
    print(f"# Completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'#'*60}")
