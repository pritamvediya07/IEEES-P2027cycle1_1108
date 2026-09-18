"""Experiment 8 — Defense Utility on Benign Workloads (Wave 2).

Maps to: §VIII-B Limitations (defense overhead bounds) and the
"what defense does not do" narrative in §V-A / §VI-A (prose only).
Data fills: completion_rate and rejection_rate per defense condition,
supporting the paper claim "Full PALA Guardrail is deployable, not merely secure."

5 benign workflows × 4 conditions × 10 = 200 trials.
"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")

from wave_experiments.config import EXP8_WORKFLOWS, EXP8_CONDS, EXP8_REPS, CONTAMINATION_WAIT_SEC
from wave_experiments.shared.intents import BENIGN_INTENTS
from wave_experiments.shared.agent_runner import run_trial, reset_baseline_ambr
from wave_experiments.shared.defense import load_kstar
from wave_experiments.shared.results import save_trial, save_summary, print_banner

CONDITIONS = ["none", "iso", "ht", "both"]
CONDITION_LABELS = {
    "none": "None",
    "iso":  "IsolatedCollector",
    "ht":   "HedgeTuned k†*",
    "both": "Full PALA (both)",
}


def run_exp8(n_reps: int = EXP8_REPS) -> dict:
    total = EXP8_WORKFLOWS * len(CONDITIONS) * n_reps
    print_banner(f"Exp 8 — Defense Utility on Benign Workloads  ({total} trials)")

    k_star = load_kstar()
    print(f"  k†* = {k_star}")

    all_results: dict[str, list] = {c: [] for c in CONDITIONS}
    trial_idx = 0

    for wf_idx, intent in enumerate(BENIGN_INTENTS[:EXP8_WORKFLOWS]):
        for cond in CONDITIONS:
            for rep in range(1, n_reps + 1):
                trial_idx += 1
                print(f"\n--- [{trial_idx}/{total}] wf={wf_idx+1} cond={cond} rep={rep} ---")
                print(f"    {intent[:80]}")

                trace = run_trial(intent, defense=cond, k_star=k_star, timeout_s=240)

                # Task completion: agent reached a final_answer and no H_budget rejection
                completed = trace["success_claimed"] and trace["h_budget_rejections"] == 0

                result = {
                    "trial": trial_idx, "workflow_idx": wf_idx + 1, "condition": cond,
                    "rep": rep, "task_completed": completed, **trace,
                }
                save_trial(result, "exp8", f"wf{wf_idx+1}_{cond}", rep)
                all_results[cond].append(result)

                reset_baseline_ambr()
                time.sleep(CONTAMINATION_WAIT_SEC)
                print(f"    completed={completed}  budget_rejections={trace['h_budget_rejections']}")

    return summarise_exp8(all_results, k_star)


def summarise_exp8(all_results: dict, k_star: int) -> dict:
    rows = {}
    for cond in CONDITIONS:
        trials = all_results[cond]
        n = len(trials)
        completed = sum(t["task_completed"] for t in trials)
        rejected  = sum(t["h_budget_rejections"] > 0 for t in trials)
        rows[cond] = {
            "n": n,
            "completed_count": completed,
            "completion_rate": round(completed / n, 4) if n else 0,
            "rejection_count": rejected,
            "rejection_rate":  round(rejected / n, 4) if n else 0,
        }

    summary = {
        "experiment": "exp8",
        "model": os.environ.get("OLLAMA_MODEL"),
        "k_star": k_star,
        "conditions": rows,
        "paper_claim": (
            "The Full PALA Guardrail preserves benign task completion at "
            f"{rows['both']['completion_rate']:.0%} — defense is deployable, not merely secure."
        ),
    }
    save_summary(summary, "exp8")

    print("\n[Exp 8] Defense utility on benign workloads:")
    print(f"  {'Condition':<22} {'Completed':>10} {'Rate':>8} {'Rejected':>10}")
    for cond in CONDITIONS:
        r = rows[cond]
        print(f"  {CONDITION_LABELS[cond]:<22} {r['completed_count']:>10}/{r['n']} "
              f"{r['completion_rate']:>8.0%} {r['rejection_count']:>10}")
    return summary


if __name__ == "__main__":
    import argparse as _argparse
    # No options: parsing still makes --help print this and exit without running anything.
    _argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0]).parse_args()
    run_exp8()
