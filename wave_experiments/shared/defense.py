"""Defense context managers for wave experiments.

IsolatedCollector: patches KPIAnalyzer.analyze to strip Type-P metrics.
HBudget:           patches PolicyManager to enforce session depth limit k†*.
AS5Guard:          patches KPIAnalyzer.analyze to enforce N bounds + R² floor.

Usage:
    with isolated_collector():
        for step in agent.run(intent): ...

    with h_budget(k_star=k_star_value) as counter:
        for step in agent.run(intent): ...

    with full_pala(k_star=k_star_value):
        for step in agent.run(intent): ...
"""
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from wave_experiments.config import TYPE_P_METRICS, AS5_N_MIN, AS5_N_MAX, AS5_R2_FLOOR


def _get_tools():
    from tools.kpi_analyzer import KPIAnalyzer
    from tools.policy_manager import PolicyManager
    return KPIAnalyzer, PolicyManager


# ── IsolatedCollector (AS2 enforced) ──────────────────────────────────────────
@contextmanager
def isolated_collector():
    """Prevents the agent from observing Type-P (policy-derived) KPI metrics."""
    KPIAnalyzer, _ = _get_tools()
    original_analyze = KPIAnalyzer.analyze

    def filtered_analyze(self, metric: str, n_samples: int = 500, **kwargs):
        if metric in TYPE_P_METRICS:
            return {
                "metric": metric,
                "stats": {"count": 0, "mean": None, "std": None,
                          "trend": "unknown", "anomalies": []},
                "raw_values": [],
                "ml": None,
                "error": "IsolatedCollector: provenance filter active — Type-P data unavailable",
            }
        return original_analyze(self, metric, n_samples, **kwargs)

    KPIAnalyzer.analyze = filtered_analyze
    try:
        yield
    finally:
        KPIAnalyzer.analyze = original_analyze


# ── HedgeTuned session budget (AS4 enforced) ──────────────────────────────────
@contextmanager
def h_budget(k_star: int):
    """Rejects policy_manager.apply calls beyond k†* per session."""
    _, PolicyManager = _get_tools()
    original_apply = PolicyManager.apply_policy
    counter = {"n": 0, "rejected": []}

    def budgeted_apply(self, target_slice, new_dl_ambr, new_ul_ambr=None, **kwargs):
        counter["n"] += 1
        if counter["n"] > k_star:
            msg = (f"H_budget REJECT: session depth {counter['n']} "
                   f"exceeds k†* = {k_star}")
            counter["rejected"].append(counter["n"])
            return {
                "success": False,
                "error": msg,
                "rejected_by": "H_budget",
                "session_depth": counter["n"],
                "k_star": k_star,
            }
        return original_apply(self, target_slice, new_dl_ambr, new_ul_ambr, **kwargs)

    PolicyManager.apply_policy = budgeted_apply
    try:
        yield counter
    finally:
        PolicyManager.apply_policy = original_apply


# ── Full PALA guardrail (AS2 ∧ AS4 enforced) ──────────────────────────────────
@contextmanager
def full_pala(k_star: int):
    """Combined IsolatedCollector + HedgeTuned budget."""
    with isolated_collector():
        with h_budget(k_star) as counter:
            yield counter


# ── AS5 guard: N-bounds + R² floor (Exp 5 as5_only variant) ──────────────────
@contextmanager
def as5_guard():
    """Enforces N ∈ [30,500] and R²_test ≥ -0.5 in KPIAnalyzer."""
    KPIAnalyzer, _ = _get_tools()
    original_analyze = KPIAnalyzer.analyze

    def guarded_analyze(self, metric: str, n_samples: int = 500, **kwargs):
        clipped_n = max(AS5_N_MIN, min(AS5_N_MAX, n_samples))
        result = original_analyze(self, metric, clipped_n, **kwargs)
        # If ML result has poor R², blank the forecast to prevent amplification
        ml = result.get("ml") or {}
        r2 = ml.get("test_r2", 1.0)
        if r2 is not None and r2 < AS5_R2_FLOOR:
            result["ml"]["forecast"] = []
            result["ml"]["forecast_suppressed"] = True
            result["ml"]["suppression_reason"] = (
                f"AS5 guard: R²_test={r2:.3f} < floor={AS5_R2_FLOOR}"
            )
        result["as5_n_clipped"] = clipped_n
        return result

    KPIAnalyzer.analyze = guarded_analyze
    try:
        yield
    finally:
        KPIAnalyzer.analyze = original_analyze


# ── Utility: load k†* from Exp 6 result file ─────────────────────────────────
def load_kstar(default: int = 3) -> int:
    import json
    from wave_experiments.config import KSTAR_FILE
    if KSTAR_FILE.exists():
        data = json.loads(KSTAR_FILE.read_text())
        return int(data["k_star"])
    return default
