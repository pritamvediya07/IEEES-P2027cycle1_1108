"""Consistent result persistence for wave experiments.

Every save_trial call also:
  1. Appends to results/<exp_id>/<exp_id>_trials.jsonl (one JSON per line)
  2. Logs a one-line summary via the active experiment logger

Every save_summary call also logs the summary dict.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path


def _serialisable(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Not serialisable: {type(obj)}")


def save_trial(result: dict, exp_id: str, arm: str, trial_idx: int) -> Path:
    """Save a single trial result JSON and append to the JSONL log.

    Args:
        result     – trial dict (must be JSON-serialisable)
        exp_id     – e.g. "exp1", "exp6_phase1"
        arm        – e.g. "vulnerable", "defended", "staged", "as2_only"
        trial_idx  – 1-based trial number
    """
    from wave_experiments.config import RESULTS_DIR
    out_dir = RESULTS_DIR / exp_id / arm
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"trial_{trial_idx:03d}.json"
    result.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
    result.setdefault("exp_id", exp_id)
    result.setdefault("arm", arm)
    path.write_text(json.dumps(result, indent=2, default=_serialisable))

    # Append to per-experiment JSONL (one record per line for easy grep/analysis)
    jsonl_path = RESULTS_DIR / exp_id / f"{Path(exp_id).name}_trials.jsonl"
    with open(jsonl_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(result, default=_serialisable) + "\n")

    # Emit one-line log via active logger (non-fatal if logging not yet set up)
    try:
        from wave_experiments.shared.logging_setup import get_logger, elapsed_str
        log = get_logger()
        fl  = result.get("full_loop", "—")
        suc = result.get("success_claimed", "—")
        rej = result.get("h_budget_rejections", "—")
        log.debug(
            f"[{exp_id}|{arm}|t{trial_idx:03d}] "
            f"full_loop={fl} success={suc} h_rej={rej}  elapsed={elapsed_str()}"
        )
    except Exception:
        pass

    return path


def save_summary(summary: dict, exp_id: str, filename: str = "summary.json") -> Path:
    from wave_experiments.config import RESULTS_DIR
    out_dir = RESULTS_DIR / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    summary.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(summary, indent=2, default=_serialisable))
    print(f"[Results] Summary → {path}")

    try:
        from wave_experiments.shared.logging_setup import log_summary
        log_summary(summary)
    except Exception:
        pass

    return path


def load_trials(exp_id: str, arm: str) -> list[dict]:
    from wave_experiments.config import RESULTS_DIR
    arm_dir = RESULTS_DIR / exp_id / arm
    if not arm_dir.exists():
        return []
    trials = []
    for p in sorted(arm_dir.glob("trial_*.json")):
        trials.append(json.loads(p.read_text()))
    return trials


def load_summary(exp_id: str, filename: str = "summary.json") -> dict | None:
    from wave_experiments.config import RESULTS_DIR
    path = RESULTS_DIR / exp_id / filename
    return json.loads(path.read_text()) if path.exists() else None


def compute_arm_stats(trials: list[dict], key: str) -> dict:
    """Compute mean / rate for a boolean or numeric key across trials."""
    vals = [t.get(key) for t in trials if key in t]
    if not vals:
        return {"n": 0, "mean": None}
    if isinstance(vals[0], bool):
        rate = sum(vals) / len(vals)
        return {"n": len(vals), "rate": round(rate, 4), "count": sum(vals)}
    numeric = [v for v in vals if v is not None]
    if not numeric:
        return {"n": 0, "mean": None}
    return {
        "n": len(numeric),
        "mean": round(sum(numeric) / len(numeric), 4),
        "min": round(min(numeric), 4),
        "max": round(max(numeric), 4),
    }


def fisher_exact_p(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value via scipy (or fallback chi2)."""
    try:
        from scipy.stats import fisher_exact
        _, p = fisher_exact([[a, b], [c, d]], alternative="two-sided")
        return float(p)
    except ImportError:
        # chi-squared fallback
        n = a + b + c + d
        if n == 0:
            return 1.0
        e = lambda r, col: (r * col) / n
        r1, r2, c1, c2 = a + b, c + d, a + c, b + d
        chi2 = sum([
            (a - e(r1, c1)) ** 2 / max(e(r1, c1), 1e-9),
            (b - e(r1, c2)) ** 2 / max(e(r1, c2), 1e-9),
            (c - e(r2, c1)) ** 2 / max(e(r2, c1), 1e-9),
            (d - e(r2, c2)) ** 2 / max(e(r2, c2), 1e-9),
        ])
        import math
        return float(math.exp(-chi2 / 2))


def print_banner(msg: str, exp_id: str | None = None) -> None:
    """Print a section banner and optionally initialise the file logger."""
    w  = min(72, len(msg) + 4)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    border = "=" * w
    print(border)
    print(f"  {msg}")
    print(border)
    print(f"  {ts}")
    print(border)

    # Auto-detect exp_id from message if not provided
    if exp_id is None:
        import re
        m = re.search(r"\bexp(\d+)\b", msg, re.IGNORECASE)
        if m:
            exp_id = f"exp{m.group(1)}"

    if exp_id:
        try:
            from wave_experiments.shared.logging_setup import setup_logger, get_logger
            import logging
            log = get_logger()
            # Only call setup_logger if no handlers yet or logger is the fallback
            if log.name == "wave" or not log.handlers:
                setup_logger(exp_id)
            else:
                log.info(border)
                log.info(f"  {msg}")
                log.info(f"  {ts}")
                log.info(border)
        except Exception:
            pass
