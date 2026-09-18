"""Per-experiment logging: file + console tee, JSONL trial log, and timing.

Usage (called automatically by print_banner / save_trial in results.py):
  from wave_experiments.shared.logging_setup import setup_logger, get_logger
  setup_logger("exp1")          # call once at the start of each experiment
  log = get_logger()            # get the active logger anywhere
  log.info("message")
"""
import logging
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

_active_logger: logging.Logger | None = None
_active_jsonl_path: Path | None = None
_exp_start_time: float = 0.0


class _TeeHandler(logging.StreamHandler):
    """Writes to both a file and stdout, without duplicating stdout."""
    pass


def setup_logger(exp_name: str, results_dir: Path | None = None) -> logging.Logger:
    """Set up a logger that writes to results/<exp_name>/<exp_name>.log and stdout."""
    global _active_logger, _active_jsonl_path, _exp_start_time

    if results_dir is None:
        from wave_experiments.config import RESULTS_DIR
        results_dir = RESULTS_DIR

    exp_dir = results_dir / exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)

    log_file   = exp_dir / f"{exp_name}.log"
    jsonl_file = exp_dir / f"{exp_name}_trials.jsonl"

    _active_jsonl_path = jsonl_file
    _exp_start_time    = time.time()

    logger = logging.getLogger(f"wave.{exp_name}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    _active_logger = logger

    # Write session header to log
    ts = datetime.now(timezone.utc).isoformat()
    logger.info("=" * 70)
    logger.info(f"Experiment: {exp_name}  started at {ts}")
    logger.info(f"Log file:   {log_file}")
    logger.info(f"JSONL log:  {jsonl_file}")
    logger.info("=" * 70)

    return logger


def get_logger(fallback_name: str = "wave") -> logging.Logger:
    """Return the active experiment logger (or a default console logger)."""
    if _active_logger is not None:
        return _active_logger
    fallback = logging.getLogger(fallback_name)
    if not fallback.handlers:
        fallback.setLevel(logging.INFO)
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        fallback.addHandler(ch)
    return fallback


def log_trial(trial_dict: dict) -> None:
    """Append a trial result to the per-experiment JSONL file."""
    if _active_jsonl_path is None:
        return
    elapsed = round(time.time() - _exp_start_time, 1) if _exp_start_time else None
    record  = {"_elapsed_s": elapsed, **trial_dict}
    with open(_active_jsonl_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def log_summary(summary_dict: dict) -> None:
    """Log a human-readable summary to the active logger."""
    log = get_logger()
    log.info("-" * 60)
    log.info("SUMMARY:")
    for k, v in summary_dict.items():
        if k == "paper_claim":
            log.info(f"  paper_claim: {v}")
        elif isinstance(v, dict):
            log.info(f"  {k}: (see JSON)")
        else:
            log.info(f"  {k} = {v}")
    log.info("-" * 60)


def elapsed_str() -> str:
    """Human-readable elapsed time since setup_logger was called."""
    if not _exp_start_time:
        return "—"
    s = time.time() - _exp_start_time
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"
