"""Pre-experiment smoke test — runs before any experiment to verify the stack is ready.

Checks (≤ 5 minutes total):
  S1  Ollama reachable + target model loaded
  S2  MongoDB reachable + nwdaf_analytics collection present
  S3  KPIAnalyzer returns data for at least one metric
  S4  PolicyManager.apply_policy writes a value + readback confirms it
  S5  Agent runs one step on a simple intent without crashing
  S6  tc + iperf3 produce a non-zero Q score (only if probe=True)

Returns a dict with {"passed": bool, "results": {Sn: {pass, msg, latency_ms}}}

Usage:
  from wave_experiments.shared.smoke_test import run_smoke_test
  result = run_smoke_test(exp_name="exp1", probe=True)
  if not result["passed"]:
      raise SystemExit("[Smoke] FAILED — fix the issues above before running.")
"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from wave_experiments.shared.logging_setup import get_logger

SMOKE_TIMEOUT_S = 60      # per check
SMOKE_INTENT    = "Check the current active_ue_count for the internet slice."


def _check(name: str, fn, log) -> dict:
    t0 = time.perf_counter()
    try:
        msg = fn()
        ms  = round((time.perf_counter() - t0) * 1000, 1)
        log.info(f"  [PASS] {name} ({ms} ms) — {msg}")
        return {"pass": True, "msg": msg, "latency_ms": ms}
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        log.warning(f"  [FAIL] {name} ({ms} ms) — {e}")
        return {"pass": False, "msg": str(e), "latency_ms": ms}


def _s1_ollama() -> str:
    import urllib.request, json as _json
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:72b")
    url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/") + "/api/tags"
    with urllib.request.urlopen(url, timeout=10) as r:
        tags = _json.loads(r.read())
    names = [m["name"] for m in tags.get("models", [])]
    if not any(model.split(":")[0] in n for n in names):
        raise RuntimeError(f"{model} not found in Ollama — available: {names[:5]}")
    return f"Ollama OK, {model} present"


def _s2_mongo() -> str:
    from pymongo import MongoClient
    from wave_experiments.config import MONGO_URI_STANDARD
    client = MongoClient(MONGO_URI_STANDARD, serverSelectionTimeoutMS=5000)
    client.server_info()
    db   = client["nwdaf_analytics"]
    cols = db.list_collection_names()
    if "smf_metrics" not in cols:
        raise RuntimeError(f"smf_metrics missing — collections: {cols}")
    count = db["smf_metrics"].count_documents({})
    client.close()
    return f"MongoDB OK, smf_metrics has {count} docs"


def _s3_kpi() -> str:
    from tools.kpi_analyzer import KPIAnalyzer
    kpi = KPIAnalyzer()
    # Use ambr_dl_mean from smf_metrics (always populated by collector).
    # n_samples must be >= 10 (KPIRequest validator enforces ge=10).
    # run_ml=False avoids the >10-sample ML requirement.
    for metric, run_ml in [("ambr_dl_mean", False), ("session_count", False),
                            ("active_ue_count", False)]:
        try:
            res = kpi.analyze(metric, n_samples=10, run_ml=False)
            raw = res.get("raw_values", [])
            if raw:
                return f"KPIAnalyzer OK, metric={metric}, {len(raw)} samples"
        except TypeError:
            # run_ml param not supported — try without it
            try:
                res = kpi.analyze(metric, n_samples=10)
                raw = res.get("raw_values", [])
                if raw:
                    return f"KPIAnalyzer OK, metric={metric}, {len(raw)} samples"
            except Exception:
                pass
        except Exception:
            pass
    raise RuntimeError(
        "KPIAnalyzer returned 0 samples for all metrics. "
        "DB may be empty — wait for collector to populate (5s interval)."
    )


def _s4_policy() -> str:
    from tools.policy_manager import PolicyManager
    from wave_experiments.shared.db import get_ambr_dl_mean
    from wave_experiments.config import BASELINE_DL_AMBR_BPS
    pm = PolicyManager()
    probe_mbps = 25.0
    probe_bps  = int(probe_mbps * 1e6)
    res = pm.apply_policy("internet", probe_bps, probe_bps)
    if not res.get("success"):
        raise RuntimeError(f"apply_policy failed: {res}")
    time.sleep(6)
    rb = get_ambr_dl_mean()   # returns Mbps
    # Reset to baseline
    pm.apply_policy("internet", BASELINE_DL_AMBR_BPS, BASELINE_DL_AMBR_BPS)
    if rb is None:
        raise RuntimeError("get_ambr_dl_mean returned None after policy write")
    # rb is in Mbps; compare with probe_mbps
    if abs(rb - probe_mbps) / probe_mbps > 0.20:
        raise RuntimeError(f"Readback mismatch: wrote {probe_mbps} Mbps, got {rb} Mbps")
    return f"PolicyManager OK, readback={rb:.1f} Mbps"


def _s5_agent() -> str:
    from wave_experiments.shared.agent_runner import run_trial, reset_baseline_ambr
    trace = run_trial(SMOKE_INTENT, defense="none", timeout_s=90)
    reset_baseline_ambr()
    # Agent runner returns 'n_steps' (not 'steps_taken')
    steps = trace.get("n_steps") or trace.get("steps_taken") or len(trace.get("step_log", []))
    if not steps:
        # Fallback: any non-empty policy or kpi calls counts as agent activity
        activity = len(trace.get("policy_calls", [])) + len(trace.get("kpi_calls", []))
        if activity == 0:
            raise RuntimeError("Agent produced no tool calls — model may be unresponsive")
        return f"Agent OK (via tool call count={activity}), success={trace.get('success_claimed')}"
    return f"Agent OK, n_steps={steps}, success={trace.get('success_claimed')}"


def _s6_probe() -> str:
    from wave_experiments.shared.probe import QProbe
    probe = QProbe()
    probe.setup_tc()
    probe.start_iperf3_server()
    q_result = probe.measure(0)
    probe.teardown_tc()
    probe.stop_iperf3_server()
    q = q_result.get("Q")
    if q is None or q <= 0:
        raise RuntimeError(f"Q score invalid: {q_result}")
    return f"QProbe OK, Q={q:.3f}"


def run_smoke_test(exp_name: str = "smoke", probe: bool = False) -> dict:
    log = get_logger()
    log.info(f"\n{'='*60}")
    log.info(f"SMOKE TEST — {exp_name}")
    log.info(f"{'='*60}")

    checks = {
        "S1_ollama":   lambda: _check("S1 Ollama+model",    _s1_ollama,  log),
        "S2_mongo":    lambda: _check("S2 MongoDB",          _s2_mongo,   log),
        "S3_kpi":      lambda: _check("S3 KPIAnalyzer",      _s3_kpi,     log),
        "S4_policy":   lambda: _check("S4 PolicyManager",    _s4_policy,  log),
        "S5_agent":    lambda: _check("S5 Agent one-step",   _s5_agent,   log),
    }
    if probe:
        checks["S6_probe"] = lambda: _check("S6 QProbe+tc", _s6_probe, log)

    results = {}
    for key, fn in checks.items():
        results[key] = fn()

    passed = all(r["pass"] for r in results.values())
    status = "ALL PASSED" if passed else "SOME CHECKS FAILED"
    log.info(f"\n[Smoke] {status}")
    for k, r in results.items():
        marker = "PASS" if r["pass"] else "FAIL"
        log.info(f"  {k:<14} {marker}  {r['msg'][:80]}")
    log.info("=" * 60)

    return {"passed": passed, "exp_name": exp_name, "results": results}


if __name__ == "__main__":
    # run_experiments.sh --phase preflight runs this file; exit non-zero if any check fails.
    import argparse
    ap = argparse.ArgumentParser(description="Preflight smoke test (S1-S5) for the live UERANSIM track")
    ap.add_argument("--probe", action="store_true", help="also run the QProbe check (S6)")
    a = ap.parse_args()
    sys.exit(0 if run_smoke_test(probe=a.probe)["passed"] else 1)
