"""
V3: KPI Forecast Inflation — Supporting Mechanism
Experiments E3.1–E3.4 + Ablations from Section 5 v3 Methodology.

Requires: collector running for ≥ 45 minutes to accumulate 500+ samples.
"""
import numpy as np
import json, time
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import sys, os
sys.path.insert(0, str(Path(__file__).parent.parent))
from exp_config import *
from utils import (read_analytics, save_json, save_csv, log_experiment,
                   spearman_rho, call_kpi_analyzer, RESULTS_DIR)


# ═══════════════════════════════════════════════════════════════
#  Core: Rolling-Origin Cross-Validation for a given N
# ═══════════════════════════════════════════════════════════════
def rolling_origin_cv(series, n_samples, window_size=10):
    """
    Rolling-origin cross-validation for Random Forest forecaster.

    For each origin o in [n_samples, n_samples+1, ..., L-h]:
      - train on the n_samples values ending at o (using sliding windows)
      - test on the next h = ceil(n_samples/5) values
      - record W(N), MAE, RMSE, and (if test set large enough) R²_test

    Returns dict with aggregated metrics.
    """
    L = len(series)
    h = max(1, int(np.ceil(n_samples / 5)))  # forecast horizon

    if n_samples + h > L:
        print(f"  [SKIP] N={n_samples}: need {n_samples + h} samples, have {L}")
        return None

    # Adaptive window: for small N, shrink window so features can be built.
    # Must satisfy: window_size + 1 <= n_samples  (need at least 1 training row)
    # Use at least 2 lag features; cap at original window_size.
    eff_window = min(window_size, max(2, n_samples - 2))

    results = {
        "N": n_samples, "h": h,
        "widths": [], "maes": [], "rmses": [], "r2_tests": [],
        "train_r2s": [],
    }

    # Determine origin range — step by h to avoid excessive overlap
    step = max(1, h)
    origins = list(range(n_samples, L - h + 1, step))
    if len(origins) > 200:  # cap for speed on large series
        origins = origins[::len(origins) // 200 + 1]

    for o in origins:
        # Extract training data: the n_samples values ending at index o
        train_vals = np.array(series[o - n_samples: o])

        # Build sliding-window features using adaptive window
        if len(train_vals) < eff_window + 1:
            continue

        X_train, y_train = [], []
        for i in range(eff_window, len(train_vals)):
            X_train.append(train_vals[i - eff_window: i])
            y_train.append(train_vals[i])
        X_train = np.array(X_train)
        y_train = np.array(y_train)

        if len(X_train) < 2:
            continue

        # Train Random Forest (same config as PALA)
        rf = RandomForestRegressor(n_estimators=100, random_state=42)
        rf.fit(X_train, y_train)

        # Train metrics
        train_pred = rf.predict(X_train)
        train_r2 = r2_score(y_train, train_pred)
        results["train_r2s"].append(train_r2)

        # Forecast h steps ahead (rolling prediction)
        window = list(train_vals[-eff_window:])
        forecast = []
        for _ in range(h):
            pred = rf.predict([window[-eff_window:]])[0]
            forecast.append(pred)
            window.append(pred)
        forecast = np.array(forecast)

        # Width
        W = float(forecast.max() - forecast.min())
        results["widths"].append(W)

        # Test against actual future values
        test_vals = np.array(series[o: o + h])
        # Use min of available test vals and forecast
        test_len = min(len(test_vals), len(forecast))
        test_actual = test_vals[:test_len]
        test_pred = forecast[:test_len]

        mae = mean_absolute_error(test_actual, test_pred)
        rmse = np.sqrt(mean_squared_error(test_actual, test_pred))
        results["maes"].append(mae)
        results["rmses"].append(rmse)

        # R² only if test set has >1 point and sufficient variance
        if test_len > 1 and np.std(test_actual) > 1e-10:
            r2 = r2_score(test_actual, test_pred)
            results["r2_tests"].append(r2)

    # Aggregate
    def agg(lst):
        if not lst:
            return {"median": None, "iqr_25": None, "iqr_75": None, "mean": None, "std": None, "n": 0}
        arr = np.array(lst)
        return {
            "median": float(np.median(arr)),
            "iqr_25": float(np.percentile(arr, 25)),
            "iqr_75": float(np.percentile(arr, 75)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "n": len(arr),
        }

    return {
        "N": n_samples,
        "n_origins": len(origins),
        "h": h,
        "width": agg(results["widths"]),
        "mae": agg(results["maes"]),
        "rmse": agg(results["rmses"]),
        "r2_test": agg(results["r2_tests"]) if n_samples >= 30 else {"note": "R² not reported for N<30 (unstable)"},
        "r2_train": agg(results["train_r2s"]),
    }


# ═══════════════════════════════════════════════════════════════
#  E3.1: Width Sensitivity
# ═══════════════════════════════════════════════════════════════
def run_e3_1():
    """
    E3.1: Sweep N values, compute W(N) via rolling-origin CV.
    Acceptance: Spearman ρ(W, N) < -0.7, p < 0.05.
    """
    print("\n" + "="*70)
    print("E3.1: WIDTH SENSITIVITY — n_samples sweep with rolling-origin CV")
    print("="*70)

    # Fetch reference series using KPI_FIELD from exp_config (total_tx_bytes has real variance)
    values, timestamps = read_analytics("upf_metrics", KPI_FIELD, V3_REFERENCE_SERIES_LEN)
    print(f"  Reference series: {len(values)} samples of '{KPI_FIELD}' collected")

    if len(values) < 50:
        print("  [ERROR] Need at least 50 samples. Let collector run longer.")
        return None

    all_results = []
    for n in V3_N_VALUES:
        if n > len(values):
            print(f"  [SKIP] N={n} > available samples ({len(values)})")
            continue
        print(f"\n  Processing N={n}...")
        result = rolling_origin_cv(values, n)
        if result:
            all_results.append(result)
            w_med   = result["width"]["median"]
            mae_med = result["mae"]["median"]
            if w_med is not None:
                print(f"    W(N) median = {w_med:.6f}")
            else:
                print(f"    W(N) median = N/A (insufficient data for window features)")
            if mae_med is not None:
                print(f"    MAE median  = {mae_med:.6f}")
            if isinstance(result["r2_test"], dict) and result["r2_test"].get("median") is not None:
                print(f"    R²_test median = {result['r2_test']['median']:.4f}")

    # Spearman correlation — only include N values where W(N) was computed
    valid_pairs = [(r["N"], r["width"]["median"])
                   for r in all_results if r["width"]["median"] is not None]
    ns = [p[0] for p in valid_pairs]
    ws = [p[1] for p in valid_pairs]
    if len(ws) >= 3:
        rho, p_val = spearman_rho(ns, ws)
        print(f"\n  Spearman ρ(W, N) = {rho:.4f}, p = {p_val:.6f}")
        accepted = rho < -0.7 and p_val < 0.05
        print(f"  ACCEPTED: {accepted}  (criterion: ρ < -0.7, p < 0.05)")
    else:
        rho, p_val, accepted = None, None, False
        print("  [WARN] Not enough data points for Spearman test")

    output = {
        "experiment": "E3.1",
        "description": "Width sensitivity: W(N) vs N via rolling-origin CV",
        "n_available_samples": len(values),
        "results_per_N": all_results,
        "spearman_rho": rho,
        "spearman_p": p_val,
        "accepted": accepted,
        "criterion": "Spearman ρ < -0.7, p < 0.05",
    }
    save_json(output, "e3_1_width_sensitivity.json")

    # Also save CSV for plotting
    rows = []
    for r in all_results:
        w = r["width"]
        m = r["mae"]
        rm = r["rmse"]
        rt = r["r2_train"]
        row = [
            r["N"],
            w["median"]  if w["median"]  is not None else "",
            w["iqr_25"]  if w["iqr_25"]  is not None else "",
            w["iqr_75"]  if w["iqr_75"]  is not None else "",
            m["median"]  if m["median"]  is not None else "",
            rm["median"] if rm["median"] is not None else "",
        ]
        if isinstance(r["r2_test"], dict) and r["r2_test"].get("median") is not None:
            row.append(r["r2_test"]["median"])
        else:
            row.append("")
        row.append(rt["median"] if rt["median"] is not None else "")
        rows.append(row)
    save_csv(rows,
             ["N", "W_median", "W_iqr25", "W_iqr75", "MAE_median", "RMSE_median", "R2_test_median", "R2_train_median"],
             "e3_1_sweep_data.csv")

    log_experiment("E3.1", {"spearman_rho": rho, "spearman_p": p_val, "accepted": accepted})
    return output


# ═══════════════════════════════════════════════════════════════
#  E3.2: Error Metrics (MAE, RMSE, R² for N≥30)
# ═══════════════════════════════════════════════════════════════
def run_e3_2():
    """
    E3.2: Detailed error characterization across N values.
    Acceptance: MAE monotonically decreasing with N; R²_test < 0 for N ≤ 20.
    """
    print("\n" + "="*70)
    print("E3.2: ERROR METRICS — MAE, RMSE, R² characterization")
    print("="*70)

    # Re-use E3.1 data if available
    e31_path = RESULTS_DIR / "e3_1_width_sensitivity.json"
    if e31_path.exists():
        with open(e31_path) as f:
            e31 = json.load(f)
        results = e31["results_per_N"]
        print("  Using cached E3.1 results")
    else:
        print("  Run E3.1 first")
        return None

    # Check MAE monotonicity
    maes = [(r["N"], r["mae"]["median"]) for r in results if r["mae"]["median"] is not None]
    maes.sort(key=lambda x: x[0])
    monotonic = all(maes[i][1] >= maes[i+1][1] for i in range(len(maes)-1))
    print(f"\n  MAE monotonically decreasing: {monotonic}")
    for n, m in maes:
        print(f"    N={n:4d}: MAE = {m:.6f}")

    # Check R² < 0 for N ≤ 20
    r2_low_n = []
    for r in results:
        if r["N"] <= 20 and isinstance(r["r2_test"], dict) and r["r2_test"].get("median") is not None:
            r2_low_n.append((r["N"], r["r2_test"]["median"]))
    r2_all_negative = all(r2 < 0 for _, r2 in r2_low_n) if r2_low_n else False
    print(f"\n  R²_test < 0 for N ≤ 20: {r2_all_negative}")
    for n, r2 in r2_low_n:
        print(f"    N={n:4d}: R²_test = {r2:.4f}")

    output = {
        "experiment": "E3.2",
        "mae_monotonic_decreasing": monotonic,
        "r2_negative_for_low_n": r2_all_negative,
        "mae_values": maes,
        "r2_low_n_values": r2_low_n,
        "accepted": monotonic,  # primary criterion
    }
    save_json(output, "e3_2_error_metrics.json")
    log_experiment("E3.2", output)
    return output


# ═══════════════════════════════════════════════════════════════
#  E3.3: Defense — N Bounds Clamping
# ═══════════════════════════════════════════════════════════════
def run_e3_3():
    """
    E3.3: Show that clamping N to [30, 500] restricts W(N) and MAE to non-pathological range.
    """
    print("\n" + "="*70)
    print("E3.3: DEFENSE — N-bounds clamping")
    print("="*70)

    e31_path = RESULTS_DIR / "e3_1_width_sensitivity.json"
    if not e31_path.exists():
        print("  Run E3.1 first")
        return None
    with open(e31_path) as f:
        e31 = json.load(f)
    results = e31["results_per_N"]

    # Split into undefended (N < 30) and defended (N ≥ 30)
    undefended = [r for r in results if r["N"] < V3_DEFENSE_N_MIN]
    defended = [r for r in results if V3_DEFENSE_N_MIN <= r["N"] <= V3_DEFENSE_N_MAX]

    print("\n  UNDEFENDED (N < 30):")
    for r in undefended:
        print(f"    N={r['N']:4d}: W={r['width']['median']:.6f}, MAE={r['mae']['median']:.6f}")

    print(f"\n  DEFENDED (N ∈ [{V3_DEFENSE_N_MIN}, {V3_DEFENSE_N_MAX}]):")
    for r in defended:
        w = r["width"]["median"]
        m = r["mae"]["median"]
        print(f"    N={r['N']:4d}: W={w:.6f}, MAE={m:.6f}")

    # Compute range reduction
    if undefended and defended:
        undef_w_max = max(r["width"]["median"] for r in undefended)
        def_w_max = max(r["width"]["median"] for r in defended)
        reduction = 1 - def_w_max / undef_w_max if undef_w_max > 0 else 0
        print(f"\n  Width range reduction: {reduction:.1%}")
    else:
        reduction = None

    output = {
        "experiment": "E3.3",
        "defense": f"N ∈ [{V3_DEFENSE_N_MIN}, {V3_DEFENSE_N_MAX}]",
        "undefended_results": [{k: v for k, v in r.items()} for r in undefended],
        "defended_results": [{k: v for k, v in r.items()} for r in defended],
        "width_range_reduction": reduction,
    }
    save_json(output, "e3_3_defense_bounds.json")
    log_experiment("E3.3", {"reduction": reduction})
    return output


# ═══════════════════════════════════════════════════════════════
#  E3.4: Defense — R² Guard
# ═══════════════════════════════════════════════════════════════
def run_e3_4():
    """
    E3.4: Test R² < -0.5 guard. Should flag 0% of N ≥ 30 runs under normal conditions.
    """
    print("\n" + "="*70)
    print("E3.4: DEFENSE — R² guard")
    print("="*70)

    e31_path = RESULTS_DIR / "e3_1_width_sensitivity.json"
    if not e31_path.exists():
        print("  Run E3.1 first")
        return None
    with open(e31_path) as f:
        e31 = json.load(f)

    threshold = V3_DEFENSE_R2_THRESHOLD
    flagged = {}
    for r in e31["results_per_N"]:
        n = r["N"]
        r2_data = r["r2_test"]
        if isinstance(r2_data, dict) and r2_data.get("median") is not None:
            is_flagged = r2_data["median"] < threshold
            flagged[n] = {"r2_median": r2_data["median"], "flagged": is_flagged}
            status = "FLAGGED" if is_flagged else "OK"
            print(f"    N={n:4d}: R²_test = {r2_data['median']:.4f} -> {status}")
        else:
            print(f"    N={n:4d}: R² not available (N < 30)")

    # Under clamped bounds, check N ≥ 30
    defended_flags = {n: v for n, v in flagged.items() if n >= V3_DEFENSE_N_MIN}
    false_positives = sum(1 for v in defended_flags.values() if v["flagged"])
    total_defended = len(defended_flags)
    fp_rate = false_positives / total_defended if total_defended > 0 else 0

    print(f"\n  False positive rate (N ≥ {V3_DEFENSE_N_MIN}): {false_positives}/{total_defended} = {fp_rate:.1%}")
    accepted = fp_rate == 0
    print(f"  ACCEPTED: {accepted}  (criterion: 0% FP for N ≥ {V3_DEFENSE_N_MIN})")

    output = {
        "experiment": "E3.4",
        "threshold": threshold,
        "per_N_results": flagged,
        "defended_false_positive_rate": fp_rate,
        "accepted": accepted,
    }
    save_json(output, "e3_4_r2_guard.json")
    log_experiment("E3.4", {"fp_rate": fp_rate, "accepted": accepted})
    return output


# ═══════════════════════════════════════════════════════════════
#  E3.5/E3.6: Amplification (Exploratory)
# ═══════════════════════════════════════════════════════════════
def run_e3_5_amplification():
    """
    E3.5: Exploratory — does small-N forecast influence V4 decomposition?
    Calls KPI analyzer with N=5 and N=100, compares forecast text.
    No formal acceptance criterion.
    """
    print("\n" + "="*70)
    print("E3.5: AMPLIFICATION — Small-N vs Large-N forecast character (exploratory)")
    print("="*70)

    results = {}
    for n in [5, 10, 100, 200]:
        print(f"\n  Calling KPI Analyzer with N={n}...")
        try:
            r = call_kpi_analyzer(metric="memory_utilization", n_samples=n, run_ml=True)
            results[n] = {
                "mean": r.get("stats", {}).get("mean"),
                "std": r.get("stats", {}).get("std"),
                "trend": r.get("stats", {}).get("trend"),
                "forecast_range": None,
                "train_r2": r.get("ml", {}).get("train_r2"),
                "test_r2": r.get("ml", {}).get("test_r2"),
            }
            forecast = r.get("ml", {}).get("forecast", [])
            if forecast:
                results[n]["forecast_range"] = float(max(forecast) - min(forecast))
                results[n]["forecast_min"] = float(min(forecast))
                results[n]["forecast_max"] = float(max(forecast))
            print(f"    mean={results[n]['mean']}, trend={results[n]['trend']}")
            print(f"    forecast range={results[n].get('forecast_range')}")
            print(f"    train_R²={results[n]['train_r2']}, test_R²={results[n]['test_r2']}")
        except Exception as e:
            print(f"    [ERROR] {e}")
            results[n] = {"error": str(e)}

    output = {
        "experiment": "E3.5",
        "type": "exploratory",
        "description": "Forecast character comparison across N values (no formal criterion)",
        "results": results,
    }
    save_json(output, "e3_5_amplification.json")
    log_experiment("E3.5", {"type": "exploratory"})
    return output


# ═══════════════════════════════════════════════════════════════
#  Master runner
# ═══════════════════════════════════════════════════════════════
def run_all_v3():
    """Run all V3 experiments in sequence."""
    print("\n" + "#"*70)
    print("#  V3: KPI FORECAST INFLATION — FULL EXPERIMENT SUITE")
    print("#"*70)

    r1 = run_e3_1()
    r2 = run_e3_2()
    r3 = run_e3_3()
    r4 = run_e3_4()
    r5 = run_e3_5_amplification()

    print("\n" + "="*70)
    print("V3 SUMMARY")
    print("="*70)
    if r1:
        print(f"  E3.1 Width Sensitivity: {'ACCEPTED' if r1.get('accepted') else 'NOT ACCEPTED'}")
    if r2:
        print(f"  E3.2 Error Metrics:     {'ACCEPTED' if r2.get('accepted') else 'NOT ACCEPTED'}")
    if r3:
        red = r3.get('width_range_reduction')
        print(f"  E3.3 Defense Bounds:    Reduction = {red:.1%}" if red else "  E3.3: N/A")
    if r4:
        print(f"  E3.4 R² Guard:          {'ACCEPTED' if r4.get('accepted') else 'NOT ACCEPTED'}")
    print(f"  E3.5 Amplification:    Exploratory (see results/e3_5_amplification.json)")

    return {"e3_1": r1, "e3_2": r2, "e3_3": r3, "e3_4": r4, "e3_5": r5}


if __name__ == "__main__":
    run_all_v3()
