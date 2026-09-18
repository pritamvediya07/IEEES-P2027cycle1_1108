"""Exp 1 — Vulnerable Arm, Additional Models (Wave 3 model-agnosticism).

Runs the exp1 vulnerable arm (30 trials, defense="none") for each target model
and produces a cross-model comparison table alongside the primary qwen2.5:72b result.

Target models (local Ollama):
  llama3.1:70b
  mistral-large:latest

Run AFTER Wave 1 is complete (requires results/exp1/vulnerable/ on disk).

Usage:
  python exp1_vuln_multimodel.py                          # both models
  python exp1_vuln_multimodel.py --models llama3.1:70b   # single model
  python exp1_vuln_multimodel.py --trials 30             # explicit trial count
"""
import argparse, sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from wave_experiments.config import (
    EXP1_TRIALS_PER_ARM, RESULTS_DIR, CONTAMINATION_WAIT_SEC,
)
from wave_experiments.shared.intents import CLOSED_LOOP_INTENTS
from wave_experiments.shared.agent_runner import run_trial, reset_baseline_ambr
from wave_experiments.shared.probe import QProbe
from wave_experiments.shared.results import save_trial, save_summary, print_banner
from wave_experiments.shared.checkpoint import count_trials, load_completed_trials

TARGET_MODELS = [
    "llama3.1:70b",
    "mistral-large:latest",
]

EXP_ID = "exp1_multimodel"

# Default API equivalents for each paper model (used when --backend != ollama).
# Override with --api-model or --backend-map.
API_DEFAULTS: dict[str, dict[str, str]] = {
    "qwen2.5:72b": {
        "together":     "Qwen/Qwen2.5-72B-Instruct-Turbo",
        "openai_compat": "Qwen/Qwen2.5-72B-Instruct-Turbo",
    },
    "llama3.1:70b": {
        "groq":         "llama-3.1-70b-versatile",
        "together":     "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "openai_compat": "meta-llama/Llama-3.1-70B-Instruct",
    },
    "mistral-large:latest": {
        "openai_compat": "mistral-large-latest",
        "together":      "mistralai/Mistral-7B-Instruct-v0.3",
    },
}


def _model_slug(model: str) -> str:
    """Convert model name to a filesystem-safe slug."""
    return model.replace(":", "_").replace(".", "_").replace("-", "_").replace("/", "_")


def run_vulnerable_arm(
    model: str,
    n_trials: int,
    backend: str = "ollama",
    api_model: str | None = None,
) -> list[dict]:
    """Run exp1 vulnerable arm for a given model.

    Args:
        model      Ollama model name (used as the canonical label, e.g. 'llama3.1:70b')
        n_trials   Number of trials to run
        backend    LLM backend: 'ollama' | 'groq' | 'together' | 'openai_compat' | 'gemini'
        api_model  API-side model ID when backend != 'ollama'. If None, uses API_DEFAULTS.
    """
    slug = _model_slug(model)

    # Resolve the API model name
    if backend == "ollama":
        os.environ["OLLAMA_MODEL"] = model
        resolved_api_model = None
    else:
        resolved_api_model = api_model or API_DEFAULTS.get(model, {}).get(backend)
        if resolved_api_model is None:
            raise ValueError(
                f"No API model configured for {model!r} on backend {backend!r}. "
                f"Pass --api-model <id> explicitly. See MODEL_SETUP.md."
            )
        print(f"[{model}] Using API backend={backend!r}, api_model={resolved_api_model!r}")

    # Checkpoint: how many trials already done for this model?
    done = count_trials(EXP_ID, slug)
    start = done + 1
    trials = load_completed_trials(EXP_ID, slug)

    if done >= n_trials:
        print(f"[{model}] All {n_trials} trials already complete — loading from disk.")
        return trials
    if done > 0:
        print(f"[{model}] Resuming from trial {start}/{n_trials} ({done} done).")

    print_banner(f"Exp 1 Vulnerable — {model}  ({n_trials} trials, start={start})")

    intents = [CLOSED_LOOP_INTENTS[i % len(CLOSED_LOOP_INTENTS)] for i in range(n_trials)]

    probe = QProbe()
    probe.setup_tc()
    probe.start_iperf3_server()

    for idx in range(1, n_trials + 1):
        if idx < start:
            continue

        intent = intents[idx - 1]
        print(f"\n--- Trial {idx}/{n_trials} [{model}] ---")
        print(f"    Intent: {intent[:80]}...")

        # Preflight check on first trial
        if idx == 1:
            q_check = probe.measure(0)
            assert q_check["tau_mbps"] < 20, (
                f"tc not binding? τ={q_check['tau_mbps']:.1f} ≥ 20 Mbps"
            )
            print(f"    [Preflight] tc binding: τ={q_check['tau_mbps']:.1f} Mbps ✓")

        probe.reset()
        baseline_q = probe.measure(0)
        print(f"    Baseline Q={baseline_q['Q']:.4f}  τ={baseline_q['tau_mbps']:.1f} Mbps")

        trace = run_trial(
            intent,
            defense="none",
            k_star=3,
            probe=probe,
            timeout_s=240,
            backend=backend,
            model=resolved_api_model,
        )

        time.sleep(CONTAMINATION_WAIT_SEC)
        reset_baseline_ambr()
        time.sleep(5)

        result = {
            "trial":        idx,
            "model":        model,
            "arm":          "vulnerable",
            "intent_label": "staged_change" if (idx - 1) % len(CLOSED_LOOP_INTENTS) < 15 else "sla_framing",
            "baseline_q":   baseline_q,
            **trace,
        }
        save_trial(result, EXP_ID, slug, idx)
        trials.append(result)

        print(f"    full_loop={trace['full_loop']}  "
              f"contaminated={trace['contaminated']}  "
              f"elapsed={trace['elapsed_s']}s")

        # Health check every 10 trials
        if idx % 10 == 0:
            fl_rate = sum(t.get("full_loop", False) for t in trials) / len(trials)
            print(f"\n  [HealthCheck @{idx}] full_loop={fl_rate:.0%}")
            if idx >= 15 and fl_rate == 0.0:
                print("  [HealthCheck] WARN: 0% full_loop — check tc & model availability.")

    probe.teardown_tc()
    probe.stop_iperf3_server()
    return trials


def _arm_stats(trials: list[dict]) -> dict:
    n = len(trials)
    if n == 0:
        return {}
    fl   = sum(t.get("full_loop", False) for t in trials)
    d4   = sum(t.get("def4_satisfied", False) for t in trials)
    dec  = sum(t.get("decomposed", False) for t in trials)
    cont = sum(t.get("contaminated", False) for t in trials)
    esc  = sum(t.get("escalated", False) for t in trials)
    suc  = sum(t.get("success_claimed", False) for t in trials)
    elapsed = [t.get("elapsed_s", 0) for t in trials]
    return {
        "n":                 n,
        "full_loop_count":   fl,
        "full_loop_rate":    round(fl / n, 4),
        "def4_rate":         round(d4 / n, 4),
        "decomposed_rate":   round(dec / n, 4),
        "contaminated_rate": round(cont / n, 4),
        "escalated_rate":    round(esc / n, 4),
        "success_rate":      round(suc / n, 4),
        "mean_elapsed_s":    round(sum(elapsed) / n, 2),
    }


def summarise(all_model_results: dict[str, list[dict]]) -> dict:
    """Write per-model summaries and a cross-model comparison table."""
    rows = {}
    for model, trials in all_model_results.items():
        stats = _arm_stats(trials)
        rows[model] = stats
        # Per-model summary JSON
        slug = _model_slug(model)
        save_summary(
            {"experiment": EXP_ID, "model": model, "arm": "vulnerable", **stats},
            EXP_ID, f"summary_{slug}.json",
        )

    # Load qwen2.5:72b primary result for comparison
    qwen_dir = RESULTS_DIR / "exp1" / "vulnerable"
    if qwen_dir.exists():
        qwen_trials = [
            __import__("json").loads(f.read_text())
            for f in sorted(qwen_dir.glob("trial_*.json"))
        ]
        rows["qwen2.5:72b"] = _arm_stats(qwen_trials)

    # Cross-model comparison
    summary = {
        "experiment":  EXP_ID,
        "arm":         "vulnerable",
        "description": "Exp 1 vulnerable arm across model families (model-agnosticism §VI-J)",
        "models":      rows,
        "paper_claim": (
            "Wireheading circuit completion rate is consistent across model families "
            "(qwen2.5:72b, llama3.1:70b, mistral-large), confirming the vulnerability "
            "is not an artifact of a single model's reasoning style."
        ),
    }
    save_summary(summary, EXP_ID)

    print("\n[Exp1-Multimodel] Cross-model comparison (vulnerable arm):")
    print(f"  {'Model':<22} {'N':>4} {'FullLoop':>9} {'Contam':>8} {'Decomp':>8} {'MeanElap':>10}")
    for model, r in rows.items():
        if not r:
            continue
        print(f"  {model:<22} {r['n']:>4} "
              f"{r['full_loop_count']}/{r['n']} ({r['full_loop_rate']:.0%})  "
              f"{r['contaminated_rate']:>7.0%}  "
              f"{r['decomposed_rate']:>7.0%}  "
              f"{r['mean_elapsed_s']:>8.1f}s")
    return summary


def main():
    ap = argparse.ArgumentParser(
        description="Exp 1 vulnerable arm — additional model families",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # On-device (default, Ollama):
  python exp1_vuln_multimodel.py

  # Single model via Groq API:
  python exp1_vuln_multimodel.py --models llama3.1:70b \\
      --backend groq --api-model llama-3.1-70b-versatile

  # All three via per-model backend map:
  python exp1_vuln_multimodel.py \\
      --backend-map '{"llama3.1:70b": ["groq","llama-3.1-70b-versatile"],
                      "mistral-large:latest": ["openai_compat","mistral-large-latest"]}'

See MODEL_SETUP.md for API key configuration and provider details.
""",
    )
    ap.add_argument(
        "--models", nargs="+", default=TARGET_MODELS,
        help="Ollama model names to run (default: llama3.1:70b mistral-large:latest)",
    )
    ap.add_argument(
        "--trials", type=int, default=EXP1_TRIALS_PER_ARM,
        help=f"Trials per model (default: {EXP1_TRIALS_PER_ARM})",
    )
    ap.add_argument(
        "--backend", default="ollama",
        choices=["ollama", "gemini", "groq", "together", "openai_compat"],
        help="LLM backend to use for ALL models (overridden per-model by --backend-map)",
    )
    ap.add_argument(
        "--api-model", default=None, dest="api_model",
        help=(
            "API-side model ID when --backend != ollama. "
            "If omitted, uses built-in API_DEFAULTS. "
            "Applies to ALL models; use --backend-map for per-model control."
        ),
    )
    ap.add_argument(
        "--backend-map", default=None, dest="backend_map",
        metavar="JSON",
        help=(
            'JSON dict mapping model name → [backend, api_model]. '
            'Example: \'{"llama3.1:70b": ["groq", "llama-3.1-70b-versatile"]}\''
        ),
    )
    args = ap.parse_args()

    # Parse per-model backend map (overrides --backend / --api-model)
    per_model: dict[str, tuple[str, str | None]] = {}
    if args.backend_map:
        import json as _json
        raw = _json.loads(args.backend_map)
        for m, v in raw.items():
            if isinstance(v, list) and len(v) == 2:
                per_model[m] = (v[0], v[1])
            elif isinstance(v, list) and len(v) == 1:
                per_model[m] = (v[0], None)
            else:
                raise ValueError(f"--backend-map value for {m!r} must be [backend, api_model]")

    print_banner(f"Exp 1 Vulnerable Arm — Additional Models  ({len(args.models)} models × {args.trials} trials)")
    print(f"  Models: {args.models}")
    if per_model:
        print(f"  Backend map: {per_model}")
    else:
        print(f"  Backend: {args.backend}" + (f", api_model: {args.api_model}" if args.api_model else ""))
    print(f"  Results → results/{EXP_ID}/\n")

    all_results: dict[str, list[dict]] = {}

    for model in args.models:
        if model in per_model:
            model_backend, model_api = per_model[model]
        else:
            model_backend = args.backend
            model_api = args.api_model

        print(f"\n{'='*60}")
        print(f"  Starting model: {model}  (backend={model_backend})")
        print(f"{'='*60}")
        trials = run_vulnerable_arm(model, args.trials, backend=model_backend, api_model=model_api)
        all_results[model] = trials

    summarise(all_results)
    print("\n[Exp1-Multimodel] All models complete.")


if __name__ == "__main__":
    main()
