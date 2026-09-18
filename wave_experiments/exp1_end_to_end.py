"""Experiment 1 — End-to-End Realization (§VI-B, RQ1, Theorem 5).

Two arms × 30 trials = 60 total.

Vulnerable arm : standard collector, no defense.
Full PALA arm  : IsolatedCollector + HedgeTuned k†* (requires Exp 6 Phase 1 first).

Intent rotation: sla_loop, gradual_loop, capacity_loop (10 each per arm).
tc enforcement : 15 Mbps cap + 20 ms delay + 3 % loss on lo.
Out-of-band Q  : iperf3 (τ), ping (λ), iperf3-UDP (ρ), /proc/net/dev (σ).

Run sequence:
  python exp1_end_to_end.py --arm vulnerable   # 30 trials
  # (then run exp6_hedgetune.py --phase 1)
  python exp1_end_to_end.py --arm defended     # 30 trials  (needs kstar.json)
"""
import argparse, sys, time, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")

from wave_experiments.config import (
    EXP1_TRIALS_PER_ARM, RESULTS_DIR, CONTAMINATION_WAIT_SEC,
)
from wave_experiments.shared.intents import CLOSED_LOOP_INTENTS
from wave_experiments.shared.agent_runner import run_trial, reset_baseline_ambr
from wave_experiments.shared.probe import QProbe
from wave_experiments.shared.defense import load_kstar
from wave_experiments.shared.results import (
    save_trial, save_summary, load_trials, compute_arm_stats,
    fisher_exact_p, print_banner,
)


def run_arm(arm: str, n_trials: int, k_star: int | None = None) -> list[dict]:
    from wave_experiments.shared.checkpoint import resume_info
    start, trials = resume_info("exp1", arm, n_trials)
    if start > n_trials:
        print(f"[Exp1|{arm}] All {n_trials} trials already complete — loading from disk.")
        return trials
    if start > 1:
        print(f"[Exp1|{arm}] Resuming from trial {start}/{n_trials} ({start-1} already done).")

    print_banner(f"Exp 1 — Arm: {arm.upper()}  ({n_trials} trials, start={start})")

    defense = "none" if arm == "vulnerable" else "both"
    pool    = CLOSED_LOOP_INTENTS
    intents = [pool[i % len(pool)] for i in range(n_trials)]

    probe = QProbe()
    probe.setup_tc()
    probe.start_iperf3_server()

    for idx, intent in enumerate(intents, 1):
        if idx < start:
            continue   # skip already-completed trials
        print(f"\n--- Trial {idx}/{n_trials} [{arm}] ---")
        print(f"    Intent: {intent[:80]}...")

        # Pre-flight check (trial 1 of each arm)
        if idx == 1:
            _preflight_check(arm, probe)

        probe.reset()
        # Take baseline Q before agent runs
        baseline_q = probe.measure(0)
        print(f"    Baseline Q={baseline_q['Q']:.4f}, τ={baseline_q['tau_mbps']:.1f} Mbps")

        trace = run_trial(
            intent,
            defense=defense,
            k_star=k_star or 3,
            probe=probe,
            timeout_s=240,
        )

        # Wait for contamination to propagate before next trial
        time.sleep(CONTAMINATION_WAIT_SEC)

        # Reset AMBR to baseline
        reset_baseline_ambr()
        time.sleep(5)

        result = {
            "trial": idx,
            "arm": arm,
            "intent_label": _label_intent(idx),
            "baseline_q": baseline_q,
            **trace,
        }
        save_trial(result, "exp1", arm, idx)
        trials.append(result)

        # Health check every 5 trials
        if idx % 5 == 0:
            _health_check(arm, trials)

    probe.teardown_tc()
    probe.stop_iperf3_server()
    return trials


def _label_intent(idx: int) -> str:
    # CLOSED_LOOP_INTENTS[0-14] = staged-change variants; [15-24] = SLA-framing variants
    pool_idx = (idx - 1) % len(CLOSED_LOOP_INTENTS)
    if pool_idx < 15:  return "staged_change"
    return "sla_framing"


def _preflight_check(arm: str, probe: QProbe) -> None:
    """Per-spec pre-flight checks on trial 1 of each arm."""
    print(f"  [Preflight] Running arm-specific checks for '{arm}' ...")
    if arm == "vulnerable":
        # Just verify tc is binding
        q = probe.measure(0)
        assert q["tau_mbps"] < 20, f"tc not binding? τ={q['tau_mbps']:.1f} ≥ 20 Mbps"
        print(f"  [Preflight] tc binding: τ={q['tau_mbps']:.1f} Mbps ✓")
    else:
        print("  [Preflight] Full PALA — IsolatedCollector + HBudget will be active.")


def _health_check(arm: str, trials_so_far: list[dict]) -> None:
    n = len(trials_so_far)
    full_loop_rate = sum(t.get("full_loop", False) for t in trials_so_far) / n
    def4_rate = sum(t.get("def4_satisfied", False) for t in trials_so_far) / n
    print(f"\n  [HealthCheck @{n}] full_loop={full_loop_rate:.0%}  def4={def4_rate:.0%}")
    if arm == "vulnerable" and n >= 15 and full_loop_rate == 0:
        print("  [HealthCheck] WARN: 0/15 full_loop in vulnerable arm — check tc & G1.")
    if arm == "defended" and def4_rate > 0:
        print("  [HealthCheck] WARN: Def 4 triggered in defended arm — defense may be misdeployed.")


def summarise(vuln_trials: list[dict], def_trials: list[dict], k_star: int) -> dict:
    def rates(trials):
        n = len(trials)
        return {
            "n": n,
            "full_loop_rate":    round(sum(t.get("full_loop",False) for t in trials)/n, 4),
            "def4_rate":         round(sum(t.get("def4_satisfied",False) for t in trials)/n, 4),
            "decomposed_rate":   round(sum(t.get("decomposed",False) for t in trials)/n, 4),
            "contaminated_rate": round(sum(t.get("contaminated",False) for t in trials)/n, 4),
            "mean_policy_calls": compute_arm_stats(trials, "n_policy_calls")["mean"],
            "mean_elapsed_s":    compute_arm_stats(trials, "elapsed_s")["mean"],
            "q_drop_mean": (
                sum(
                    (t["baseline_q"]["Q"] - t["q_trace"][-1]["Q"])
                    if t.get("q_trace") else 0
                    for t in trials
                ) / n if n else None
            ),
        }

    v = rates(vuln_trials)
    d = rates(def_trials)

    # Fisher's exact on full_loop counts
    a = int(v["full_loop_rate"] * v["n"])
    b = v["n"] - a
    c = int(d["full_loop_rate"] * d["n"])
    e_val = d["n"] - c
    p_val = fisher_exact_p(a, b, c, e_val)

    summary = {
        "experiment": "exp1",
        "model": os.environ.get("OLLAMA_MODEL", "qwen2.5:72b"),
        "k_star": k_star,
        "vulnerable": v,
        "defended": d,
        "fisher_p_full_loop": round(p_val, 6),
        "headline": (
            f"Vulnerable: {a}/{v['n']} strict Def 4 (full_loop), "
            f"mean ΔQ = {v.get('q_drop_mean', '?'):.3f} | "
            f"Full PALA: {c}/{d['n']} — p={p_val:.2e}"
        ),
    }
    save_summary(summary, "exp1")
    print(f"\n[Exp 1] {summary['headline']}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["vulnerable", "defended", "both"],
                    default="both")
    ap.add_argument("--trials", type=int, default=EXP1_TRIALS_PER_ARM)
    args = ap.parse_args()

    k_star = load_kstar()
    print(f"[Exp 1] Model: {os.environ['OLLAMA_MODEL']}  k†*={k_star}")

    vuln_trials = def_trials = []

    if args.arm in ("vulnerable", "both"):
        vuln_trials = run_arm("vulnerable", args.trials)
    else:
        vuln_trials = load_trials("exp1", "vulnerable")

    if args.arm in ("defended", "both"):
        if load_kstar() == 3 and not (RESULTS_DIR / "exp6" / "kstar.json").exists():
            print("[Exp 1] WARNING: kstar.json not found — using default k†*=3. "
                  "Run Exp 6 Phase 1 first for calibrated value.")
        def_trials = run_arm("defended", args.trials, k_star=k_star)
    else:
        def_trials = load_trials("exp1", "defended")

    if vuln_trials and def_trials:
        summarise(vuln_trials, def_trials, k_star)


if __name__ == "__main__":
    main()
