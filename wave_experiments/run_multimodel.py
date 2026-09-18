"""Multi-model experiment runner — runs key Wave 1 experiments via cloud APIs.

Runs in PARALLEL with the ongoing qwen2.5:72b Wave 1 wave.  Uses zero local
GPU VRAM (all LLM calls go to cloud APIs).  Shares the same Open5GS / MongoDB
/ NWDAF stack but writes results to a separate directory (results/multimodel/).

Experiments covered (subset most relevant for model-agnosticism claim):
  MM-Exp1  — End-to-end wireheading  (vulnerable arm only, 20 trials)
  MM-Exp3  — Simulated pilot ablation (20 trials)
  MM-Exp5  — Necessity & sufficiency ablation (3 key variants × 10 trials)

Supported backends:
  gemini     — Google Gemini 2.0 Flash / 1.5 Pro via generativeai SDK
  together   — Together AI (Gemma 3 27B, Llama 3 70B, etc.)
  groq       — Groq (Gemma 2 9B, fastest inference)

Usage:
  # Gemini 2.0 Flash (free tier)
  GEMINI_API_KEY=xxx python wave_experiments/run_multimodel.py --backend gemini

  # Gemma 3 27B via Together AI
  TOGETHER_API_KEY=xxx python wave_experiments/run_multimodel.py \\
      --backend together --model google/gemma-3-27b-it

  # Specific experiments only
  python wave_experiments/run_multimodel.py --backend gemini --exp mm1 mm3

  # Quick smoke test (3 trials per experiment)
  python wave_experiments/run_multimodel.py --backend gemini --reps 3
"""
import argparse, sys, os, time, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")   # unused but avoids import errors

# Route all tool/DB calls to the Docker testbed, keeping
# Wave 1's system testbed completely untouched:
#   MongoDB : 27020 (Docker) instead of 27017 (system)
#   WebUI   : 10999 (Docker) instead of 9999 (system)
os.environ["MONGO_URI"] = "mongodb://localhost:27020"
os.environ["WEBUI_URL"] = "http://localhost:10999"

from wave_experiments.config import (
    RESULTS_DIR, DEFAULT_KSTAR, KSTAR_FILE, CONTAMINATION_WAIT_SEC,
    MONGO_URI_TESTBED, NWDAF_DB,
)
from wave_experiments.shared.results import save_trial, save_summary, print_banner
from wave_experiments.shared.logging_setup import setup_logger, get_logger
from wave_experiments.shared.agent_runner_api import run_trial_api, reset_baseline_ambr
from wave_experiments.shared.intents import (
    CLOSED_LOOP_INTENTS, STAGED_INTENTS, BENIGN_INTENTS,
)

MM_RESULTS = RESULTS_DIR / "multimodel"

# Default model per backend
DEFAULT_MODELS = {
    "gemini":        "gemma-4-31b-it",       # Gemma 4 31B dense via Google AI Studio
    "gemma4":        "gemma-4-31b-it",       # alias
    "gemma3":        "gemma-3-27b-it",       # Gemma 3 27B via Google AI Studio
    "together":      "google/gemma-4-31b-it",
    "groq":          "gemma2-9b-it",
    "gpt_oss":       "openai/gpt-oss-120b",  # GPT-OSS 120B via Groq
    "openai_compat": "google/gemma-4-31b-it",
}

# Which intents to use for each experiment — kept in sync with Wave 1 experiment files:
#   mm1 → exp1_end_to_end.py  uses CLOSED_LOOP_INTENTS (D + SLA_LOOP)
#   mm3 → exp3_pilot.py       uses STAGED_INTENTS (Exp B linguistic register intents)
#   mm5 → exp5_ablation.py    uses CLOSED_LOOP_INTENTS (full closed-loop)
MM_EXP_INTENTS = {
    "mm1":  CLOSED_LOOP_INTENTS,    # End-to-end: full closed-loop with KPI verify
    "mm3":  STAGED_INTENTS,         # Pilot ablation: ITIL/SRE staged register (Exp B)
    "mm5":  CLOSED_LOOP_INTENTS,    # Necessity/sufficiency: same as exp5_ablation
}

MM_EXP_LABELS = {
    "mm1":  "MM-Exp1  End-to-End Wireheading (vulnerable arm)",
    "mm3":  "MM-Exp3  Simulated Pilot Ablation (Staged register / Exp B intents)",
    "mm5":  "MM-Exp5  Necessity & Sufficiency Ablation",
}


def _flush_docker_testbed(log) -> None:
    """Flush smf_metrics on the Docker testbed (port 27020) only.
    Never touches the system testbed (port 27017) used by Wave 1."""
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URI_TESTBED, serverSelectionTimeoutMS=3000)
        col = client[NWDAF_DB]["smf_metrics"]
        deleted = col.delete_many({}).deleted_count
        client.close()
        log.info(f"[MM] Docker testbed flush: deleted {deleted} smf_metrics records (port 27020)")
    except Exception as e:
        log.warning(f"[MM] Docker testbed flush failed (non-fatal): {e}")


def _load_kstar() -> int:
    if KSTAR_FILE.exists():
        try:
            return json.loads(KSTAR_FILE.read_text()).get("k_star", DEFAULT_KSTAR)
        except Exception:
            pass
    return DEFAULT_KSTAR


def run_mm_exp(exp_id: str, n_reps: int, backend: str, model: str,
               defense: str = "none", k_star: int = 3) -> list[dict]:
    """Run one multi-model experiment arm."""
    log = get_logger()
    intents = MM_EXP_INTENTS[exp_id]
    results = []

    # Flush Docker testbed analytics before starting this experiment
    log.info(f"[MM] Pre-experiment clean for {exp_id} (Docker testbed port 27020)")
    _flush_docker_testbed(log)
    reset_baseline_ambr()
    time.sleep(CONTAMINATION_WAIT_SEC * 2)  # 2 collector cycles for fresh baseline

    for i in range(n_reps):
        intent = intents[i % len(intents)]
        log.info(f"  [{exp_id}] Trial {i+1}/{n_reps}  defense={defense}  "
                 f"backend={backend}  model={model}")
        try:
            trace = run_trial_api(
                intent, defense=defense, k_star=k_star,
                backend=backend, model=model, timeout_s=240,
            )
            # Reset AMBR and wait for collector propagation between trials
            reset_baseline_ambr()
            time.sleep(CONTAMINATION_WAIT_SEC)
            results.append(trace)
            save_trial(trace, f"multimodel/{exp_id}_{backend}", defense, i + 1)
            log.info(f"    full_loop={trace['full_loop']}  "
                     f"decomposed={trace['decomposed']}  "
                     f"contaminated={trace['contaminated']}  "
                     f"n_steps={trace['n_steps']}  "
                     f"elapsed={trace['elapsed_s']:.1f}s")
        except Exception as e:
            log.error(f"  [{exp_id}] Trial {i+1} FAILED: {e}")
            results.append({"error": str(e), "trial": i + 1, "backend": backend})
            time.sleep(CONTAMINATION_WAIT_SEC)

    return results


def summarise_mm(exp_id: str, results: list[dict], backend: str, model: str) -> dict:
    good = [r for r in results if "error" not in r]
    n = len(good)
    if n == 0:
        return {"exp_id": exp_id, "backend": backend, "model": model, "n": 0}

    fl  = sum(1 for r in good if r.get("full_loop"))
    dec = sum(1 for r in good if r.get("decomposed"))
    con = sum(1 for r in good if r.get("contaminated"))
    suc = sum(1 for r in good if r.get("success_claimed"))

    summary = {
        "exp_id":             exp_id,
        "backend":            backend,
        "model":              model,
        "n_trials":           n,
        "full_loop_rate":     round(fl  / n, 3),
        "decomposed_rate":    round(dec / n, 3),
        "contaminated_rate":  round(con / n, 3),
        "success_rate":       round(suc / n, 3),
        "avg_elapsed_s":      round(sum(r.get("elapsed_s", 0) for r in good) / n, 1),
    }

    log = get_logger()
    log.info(f"\n[MM] {exp_id} ({backend}/{model}) summary:")
    log.info(f"  n={n}  full_loop={fl/n:.0%}  decomposed={dec/n:.0%}  "
             f"contaminated={con/n:.0%}  success={suc/n:.0%}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="Multi-model experiment runner")
    ap.add_argument("--backend", default="gemma4",
                    choices=["gemini", "gemma4", "gemma3", "together", "groq", "gpt_oss", "openai_compat"],
                    help="Cloud LLM backend to use")
    ap.add_argument("--model",   default=None,
                    help="Model name override (uses backend default if omitted)")
    ap.add_argument("--exp",     nargs="+", default=["mm1", "mm3", "mm5"],
                    choices=list(MM_EXP_LABELS.keys()),
                    help="Which experiments to run")
    ap.add_argument("--reps",    type=int, default=20,
                    help="Trials per experiment (default 20)")
    ap.add_argument("--defense", default="none",
                    choices=["none", "iso", "ht", "both"],
                    help="Defense mode for all trials")
    ap.add_argument("--no-smoke", action="store_true",
                    help="Skip smoke test")
    args = ap.parse_args()

    model = args.model or DEFAULT_MODELS[args.backend]

    # Validate API key presence
    key_env = {
        "gemini":        "GEMINI_API_KEY",
        "gemma4":        "GEMINI_API_KEY",
        "gemma3":        "GEMINI_API_KEY",
        "together":      "OPENAI_COMPAT_KEY",
        "groq":          "OPENAI_COMPAT_KEY",
        "gpt_oss":       "OPENAI_COMPAT_KEY",
        "openai_compat": "OPENAI_COMPAT_KEY",
    }[args.backend]

    if not os.environ.get(key_env):
        print(f"[MM] ERROR: {key_env} not set. Export it before running.")
        sys.exit(1)

    MM_RESULTS.mkdir(parents=True, exist_ok=True)
    setup_logger(f"multimodel_{args.backend}", MM_RESULTS)
    log = get_logger()

    k_star = _load_kstar()
    log.info(f"[MM] k†* = {k_star}  backend={args.backend}  model={model}")
    log.info(f"[MM] Experiments: {args.exp}  reps={args.reps}  defense={args.defense}")

    print_banner(f"Multi-Model Runner  backend={args.backend}  model={model}")

    # Optional smoke test — just S1 (Ollama) skipped, check S2-S4
    if not args.no_smoke:
        from wave_experiments.shared.smoke_test import run_smoke_test
        smoke = run_smoke_test(f"mm_{args.backend}", probe=False)
        # S1 (Ollama) will fail if Ollama is busy — that's fine, skip it
        non_s1 = {k: v for k, v in smoke["results"].items() if k != "S1_ollama"}
        if not all(v["pass"] for v in non_s1.values()):
            log.error("[MM] Smoke test failed on S2-S5 — fix stack before running.")
            sys.exit(1)
        log.info("[MM] Smoke test passed (S2-S5)")

    wave_t0   = time.time()
    completed = {}

    for exp_id in args.exp:
        print_banner(MM_EXP_LABELS[exp_id])
        t0 = time.time()
        try:
            results = run_mm_exp(
                exp_id, n_reps=args.reps,
                backend=args.backend, model=model,
                defense=args.defense, k_star=k_star,
            )
            summary = summarise_mm(exp_id, results, args.backend, model)
            elapsed_h = round((time.time() - t0) / 3600, 2)
            summary["elapsed_h"] = elapsed_h
            save_summary(summary, f"multimodel/{exp_id}_{args.backend}")
            completed[exp_id] = {"status": "ok", "elapsed_h": elapsed_h, **summary}
            log.info(f"[MM] {exp_id} DONE in {elapsed_h:.2f} h")
        except Exception as e:
            import traceback
            elapsed_h = round((time.time() - t0) / 3600, 2)
            completed[exp_id] = {"status": "FAILED", "error": str(e), "elapsed_h": elapsed_h}
            log.error(f"[MM] {exp_id} FAILED: {e}")
            log.debug(traceback.format_exc())

    total_h = (time.time() - wave_t0) / 3600
    overall = {
        "runner":     "multimodel",
        "backend":    args.backend,
        "model":      model,
        "total_elapsed_h": round(total_h, 2),
        "experiments": completed,
    }
    save_summary(overall, "multimodel", "multimodel_summary.json")

    log.info(f"\n{'='*60}")
    log.info(f"[MM] Complete in {total_h:.2f} h")
    for e, r in completed.items():
        marker = "OK" if r.get("status") == "ok" else "FAILED"
        fl = r.get("full_loop_rate", "?")
        log.info(f"  {e:<8} {marker:<8} full_loop={fl}  {r.get('elapsed_h','?')} h")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
