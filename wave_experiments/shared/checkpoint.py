"""Checkpoint and resume utilities for Wave 1 + 2 experiments.

Provides trial-counting, gate-status, and wave-progress helpers so any
runner can auto-resume from exactly where it stopped.

Usage:
    from wave_experiments.shared.checkpoint import (
        count_trials, load_completed_trials,
        gate_status, wave_progress, next_wave_step,
        resume_info,
    )
"""
import json
from pathlib import Path

from wave_experiments.config import RESULTS_DIR

_GATES_FILE   = RESULTS_DIR / "preflight"  / "gates.json"
_W1_PROGRESS  = RESULTS_DIR / "wave1_run"  / "progress.json"
_W2_PROGRESS  = RESULTS_DIR / "wave2_run"  / "progress.json"


# ── Trial-level checkpoint ────────────────────────────────────────────────────

def count_trials(exp_id: str, arm: str) -> int:
    """Return number of completed trial JSON files for (exp_id, arm).

    Files are stored at results/<exp_id>/<arm>/trial_NNN.json.
    """
    arm_dir = RESULTS_DIR / exp_id / arm
    if not arm_dir.exists():
        return 0
    return len(list(arm_dir.glob("trial_*.json")))


def load_completed_trials(exp_id: str, arm: str) -> list[dict]:
    """Load all completed trial dicts for (exp_id, arm) sorted by trial number."""
    arm_dir = RESULTS_DIR / exp_id / arm
    if not arm_dir.exists():
        return []
    trials = []
    for p in sorted(arm_dir.glob("trial_*.json")):
        try:
            trials.append(json.loads(p.read_text()))
        except Exception:
            pass
    return trials


def resume_info(exp_id: str, arm: str, n_total: int) -> tuple[int, list[dict]]:
    """Return (start_from_1based, already_done_trials) for resuming a trial loop.

    Args:
        exp_id   – experiment ID ("exp1", "exp5", etc.)
        arm      – arm / variant / register name
        n_total  – total trials planned

    Returns:
        start    – 1-based index to start from (1 = fresh, n_total+1 = all done)
        done     – list of already-completed trial dicts (may be empty)

    Example:
        start, done = resume_info("exp1", "vulnerable", 30)
        if start > n_total:
            return done   # already complete
        for idx in range(start, n_total + 1):
            ...
    """
    done = load_completed_trials(exp_id, arm)
    return len(done) + 1, done


# ── Gate checkpoint ───────────────────────────────────────────────────────────

def gate_status() -> dict[str, bool]:
    """Return {G0: passed, G1: passed, ...} from the saved gates.json.

    Missing gates (not yet run) are absent from the returned dict.
    """
    if not _GATES_FILE.exists():
        return {}
    try:
        raw = json.loads(_GATES_FILE.read_text())
        return {g: v.get("passed", False) for g, v in raw.items()}
    except Exception:
        return {}


# ── Wave progress checkpoint ──────────────────────────────────────────────────

def wave_progress(wave: int = 1) -> dict:
    """Return the steps_so_far dict from progress.json (or {} if missing)."""
    path = _W1_PROGRESS if wave == 1 else _W2_PROGRESS
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get("steps_so_far", data.get("steps", {}))
    except Exception:
        return {}


def next_wave_step(step_order: list[str], wave: int = 1) -> str | None:
    """Find the first step in step_order that has not completed successfully.

    Returns None if all steps are done, or the first step name to run next.
    """
    progress = wave_progress(wave)
    for step in step_order:
        info = progress.get(step, {})
        if info.get("status") != "ok":
            return step
    return None   # all done


def summarise_resume(step_order: list[str], wave: int = 1) -> None:
    """Print a human-readable resume summary to stdout."""
    progress = wave_progress(wave)
    print(f"\n[Checkpoint] Wave {wave} progress ({len(progress)} steps recorded):")
    for step in step_order:
        info = progress.get(step, {})
        status = info.get("status", "pending")
        elapsed = info.get("elapsed_h", "")
        marker = {"ok": "✓", "FAILED": "✗", "skipped": "—"}.get(status, "○")
        eh = f"  ({elapsed}h)" if elapsed else ""
        print(f"  {marker} {step:<12} {status}{eh}")
    nxt = next_wave_step(step_order, wave)
    print(f"\n  → Next step to run: {nxt or 'ALL COMPLETE'}\n")
