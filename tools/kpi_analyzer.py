# tools/kpi_analyzer.py
# Tool 1 — KPI Analyzer
#
# What it does:
#   - Fetches N recent samples of any metric from the nwdaf_analytics DB
#   - Runs statistical analysis (mean, std, min, max, trend, z-score anomalies)
#   - Optionally trains a Random Forest Regressor and forecasts future values
#   - Saves the forecast plot to /tmp and returns its path
#
# The PALA LLM calls this tool when the operator asks questions like:
#   "Predict memory utilization for the internet slice"
#   "What is the average throughput over the last 500 samples?"
#   "Are there any KPI anomalies in the last hour?"

import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator

from config.db import get_nwdaf_db
from config.settings import NWDAF_UPF_METRICS, NWDAF_SMF_METRICS, NWDAF_PCF_METRICS

log = logging.getLogger(__name__)

# ── metric registry ──────────────────────────────────────────────────────────
# Maps logical metric names → (collection, document_field)
METRIC_REGISTRY: dict[str, tuple[str, str]] = {
    "memory_utilization":   (NWDAF_UPF_METRICS, "memory_util_pct"),
    "active_ue_count":      (NWDAF_UPF_METRICS, "active_ue_count"),
    "total_rx_bytes":       (NWDAF_UPF_METRICS, "total_rx_bytes"),
    "total_tx_bytes":       (NWDAF_UPF_METRICS, "total_tx_bytes"),
    "session_count":        (NWDAF_SMF_METRICS, "session_count"),
    "policy_count":         (NWDAF_PCF_METRICS, "policy_count"),
    # Type P metric: mean subscriber AMBR (Mbps) written by PolicyManager,
    # propagated via collector → D_ana. Used by V7 wireheading experiments.
    "ambr_dl_mean":         (NWDAF_SMF_METRICS, "ambr_dl_mean"),
    # E5 — the other two policy variables, read back through the same path
    "qos_5qi_mean":         (NWDAF_SMF_METRICS, "qos_5qi_mean"),
    "arp_priority_mean":    (NWDAF_SMF_METRICS, "arp_priority_mean"),
    "mbr_dl_mean":          (NWDAF_SMF_METRICS, "mbr_dl_mean"),
    "gbr_dl_mean":          (NWDAF_SMF_METRICS, "gbr_dl_mean"),
}


# ── request / response Pydantic models ───────────────────────────────────────

class KPIRequest(BaseModel):
    metric:      str = Field(..., description="Metric name from METRIC_REGISTRY")
    n_samples:   int = Field(500, ge=10, le=5000)
    run_ml:      bool = Field(True,  description="Train a Random Forest and forecast")
    forecast_steps: int = Field(50, ge=1, le=500)

    @field_validator("metric")
    @classmethod
    def metric_must_exist(cls, v: str) -> str:
        if v not in METRIC_REGISTRY:
            available = list(METRIC_REGISTRY.keys())
            raise ValueError(f"Unknown metric '{v}'. Available: {available}")
        return v


class StatsSummary(BaseModel):
    count:    int
    mean:     float
    std:      float
    min:      float
    max:      float
    trend:    str          # "rising" | "falling" | "stable"
    anomalies: list[int]   # indices of anomalous samples (|z| > 3)


class MLResult(BaseModel):
    train_r2: float
    test_r2:  float
    forecast: list[float]
    plot_path: str


class KPIResult(BaseModel):
    metric:     str
    stats:      StatsSummary
    ml:         MLResult | None = None
    raw_values: list[float]


# ── main class ───────────────────────────────────────────────────────────────

class KPIAnalyzer:
    """
    Fetch, analyse, and optionally forecast any NWDAF KPI metric.
    """

    # ── public ───────────────────────────────────────────────────────────────

    def analyze(self, metric: str, n_samples: int = 500,
                run_ml: bool = True, forecast_steps: int = 50) -> dict[str, Any]:
        """
        Entry point called by the MCP server.

        Returns a plain dict (JSON-serialisable) so the LLM can read it.
        """
        try:
            req = KPIRequest(
                metric=metric,
                n_samples=n_samples,
                run_ml=run_ml,
                forecast_steps=forecast_steps,
            )
        except ValidationError as exc:
            return {"error": str(exc.errors()[0]["msg"]), "metric": metric}

        values = self._fetch_values(req.metric, req.n_samples)
        if len(values) < 10:
            return {
                "error": f"Only {len(values)} samples available for '{metric}'. "
                         "Run the collector longer to accumulate data.",
                "available": len(values),
            }

        stats   = self._compute_stats(values)
        ml_res  = self._run_ml(values, req.forecast_steps) if req.run_ml else None

        result = KPIResult(metric=metric, stats=stats, ml=ml_res,
                           raw_values=[round(v, 6) for v in values[-20:]])
        out = result.model_dump()

        # convert numpy types for JSON serialisation
        out = _numpy_to_python(out)
        log.info("KPI analysis complete: metric=%s samples=%d", metric, len(values))
        return out

    def list_metrics(self) -> list[str]:
        return list(METRIC_REGISTRY.keys())

    # ── private ──────────────────────────────────────────────────────────────

    def _fetch_values(self, metric: str, n: int) -> list[float]:
        """Fetch the most recent N samples from nwdaf_analytics MongoDB."""
        collection_name, field = METRIC_REGISTRY[metric]
        db  = get_nwdaf_db()
        col = db[collection_name]

        docs = list(
            col.find(
                {field: {"$exists": True}},
                {field: 1, "_id": 0},
            )
            .sort("timestamp", -1)
            .limit(n)
        )
        docs.reverse()  # oldest first → chronological order

        values = []
        for doc in docs:
            raw = doc.get(field)
            if raw is not None:
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    pass
        return values

    def _compute_stats(self, values: list[float]) -> StatsSummary:
        arr = np.array(values)
        mean_, std_ = float(arr.mean()), float(arr.std())

        # trend: compare first-half mean vs second-half mean
        mid   = len(arr) // 2
        diff  = arr[mid:].mean() - arr[:mid].mean()
        if abs(diff) < 0.01 * mean_:
            trend = "stable"
        elif diff > 0:
            trend = "rising"
        else:
            trend = "falling"

        # anomalies: z-score > 3
        if std_ > 0:
            z = np.abs((arr - mean_) / std_)
            anomalies = [int(i) for i in np.where(z > 3)[0]]
        else:
            anomalies = []

        return StatsSummary(
            count=len(values),
            mean=round(mean_, 6),
            std=round(float(std_), 6),
            min=round(float(arr.min()), 6),
            max=round(float(arr.max()), 6),
            trend=trend,
            anomalies=anomalies,
        )

    def _run_ml(self, values: list[float], forecast_steps: int) -> MLResult:
        """
        Sliding-window Random Forest training + forecast.
        Matches the paper's Use Case 1 exactly.
        """
        # defer heavy imports so the module loads fast when ML is not needed
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.metrics import r2_score
        import matplotlib
        matplotlib.use("Agg")   # headless — no display needed
        import matplotlib.pyplot as plt

        WINDOW = 10  # sliding window size (look-back)

        arr = np.array(values, dtype=float)
        if len(arr) < WINDOW + 1:
            raise ValueError(
                f"Not enough samples for ML (need >{WINDOW}, got {len(arr)}). "
                "Use run_ml=False or supply more data."
            )
        X, y = [], []
        for i in range(WINDOW, len(arr)):
            X.append(arr[i - WINDOW : i])
            y.append(arr[i])
        X, y = np.array(X), np.array(y)

        split = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        if len(X_train) == 0:
            raise ValueError(
                f"Training set empty after 80/20 split ({len(X)} windows total). "
                "Provide more data or use run_ml=False."
            )

        model = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        model.fit(X_train, y_train)

        train_r2 = float(r2_score(y_train, model.predict(X_train)))
        test_r2  = float(r2_score(y_test,  model.predict(X_test)))

        # rolling forecast
        window = list(arr[-WINDOW:])
        forecast = []
        for _ in range(forecast_steps):
            pred = float(model.predict([window[-WINDOW:]])[0])
            forecast.append(round(pred, 6))
            window.append(pred)

        # ── plot ─────────────────────────────────────────────────────────
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        fig.suptitle("Memory Utilization Forecast with Random Forest", fontsize=13)

        ax = axes[0]
        ax.plot(range(len(arr)), arr, color="steelblue", linewidth=0.8,
                label="Historical", alpha=0.8)
        ax.axvline(WINDOW + split, color="gray", linestyle="--", linewidth=0.8,
                   label="Train/Test Split")
        ax.axvline(len(arr), color="orange", linestyle="--", linewidth=0.8,
                   label="Forecast Start")

        train_pred = model.predict(X_train)
        test_pred  = model.predict(X_test)
        ax.plot(range(WINDOW, WINDOW + split), train_pred,
                color="green", linewidth=1,
                label=f"Train (R²={train_r2:.3f})")
        ax.plot(range(WINDOW + split, WINDOW + len(X)), test_pred,
                color="red", linewidth=1,
                label=f"Test (R²={test_r2:.3f})")
        ax.plot(range(len(arr), len(arr) + forecast_steps), forecast,
                color="purple", linewidth=1, linestyle="-.", label="Forecast")
        ax.set_xlabel("Time steps (sample index)")
        ax.set_ylabel("Value")
        ax.legend(fontsize=8)
        ax.fill_between(range(WINDOW), arr[:WINDOW], alpha=0.1, color="steelblue",
                        label="Training Region (80%)")

        # zoomed view
        ax2 = axes[1]
        zoom_start = max(0, len(arr) - 80)
        ax2.plot(range(zoom_start, len(arr)), arr[zoom_start:],
                 color="steelblue", linewidth=1, label="Historical")
        ax2.plot(range(WINDOW + split, WINDOW + len(X)), test_pred,
                 color="red", linewidth=1.2, label=f"Test (R²={test_r2:.3f})")
        ax2.plot(range(len(arr), len(arr) + forecast_steps), forecast,
                 color="purple", linewidth=1.2, linestyle="-.", label="Forecast")
        ax2.set_title("Testing & Forecast Detail")
        ax2.legend(fontsize=8)

        plot_path = f"/tmp/nwdaf_forecast_{int(time.time())}.png"
        plt.tight_layout()
        fig.savefig(plot_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        log.info("Forecast plot saved to %s", plot_path)

        return MLResult(
            train_r2=round(train_r2, 4),
            test_r2=round(test_r2, 4),
            forecast=forecast,
            plot_path=plot_path,
        )


# ── helpers ──────────────────────────────────────────────────────────────────

def _numpy_to_python(obj: Any) -> Any:
    """Recursively convert numpy types to Python natives (for JSON)."""
    if isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numpy_to_python(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj
