"""
Shared utilities for all experiments.
"""
import json, csv, time, subprocess, os, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from pymongo import MongoClient

# ── Add PALA to path so we can import its tools directly ──
# IMPORTANT: marcus root MUST be at position 0 so that 'from config.db import ...'
# inside PALA tools resolves to the config/ package (directory), not the
# experiment-level exp_config.py file.
MARCUS = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(MARCUS) in sys.path:
    sys.path.remove(str(MARCUS))
sys.path.insert(0, str(MARCUS))


# ═══════════════════════════════════════════════════════════════
#  MongoDB helpers
# ═══════════════════════════════════════════════════════════════
_client = None

def get_mongo():
    global _client
    if _client is None:
        _client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=3000)
        _client.admin.command("ping")
    return _client

def get_db(name):
    return get_mongo()[name]

def read_analytics(collection, field, n, sort_desc=True):
    """Fetch n most recent documents from nwdaf_analytics, return field values as list."""
    db = get_db("nwdaf_analytics")
    cursor = db[collection].find(
        {field: {"$exists": True}},
        {"_id": 0, field: 1, "timestamp": 1}
    ).sort("timestamp", -1 if sort_desc else 1).limit(n)
    docs = list(cursor)
    if sort_desc:
        docs.reverse()  # oldest first
    return [d[field] for d in docs], [d.get("timestamp") for d in docs]

def read_policy_data():
    """Read all policyData.ues documents from open5gs."""
    db = get_db("open5gs")
    return list(db["policyData"]["ues"].find())

def read_subscribers():
    """Read subscriber documents from open5gs."""
    db = get_db("open5gs")
    return list(db["subscribers"].find())

def snapshot_analytics():
    """Take a complete snapshot of all analytics collections."""
    db = get_db("nwdaf_analytics")
    return {
        "upf": list(db["upf_metrics"].find().sort("timestamp", -1).limit(1)),
        "smf": list(db["smf_metrics"].find().sort("timestamp", -1).limit(1)),
        "pcf": list(db["pcf_metrics"].find().sort("timestamp", -1).limit(1)),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

def snapshot_policy():
    """Take a snapshot of policyData.ues (Type P source)."""
    docs = read_policy_data()
    return {
        "policies": [{k: v for k, v in d.items() if k != "_id"} for d in docs],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
#  iperf3 wrapper
# ═══════════════════════════════════════════════════════════════
def run_iperf3(duration=30, interface="uesimtun0", udp=True, bandwidth_mbps=None, server="10.45.0.1"):
    """
    Run iperf3 and return throughput in Mbps.
    bandwidth_mbps: offered load; if None, defaults to max.
    """
    cmd = ["iperf3", "-c", server, "-t", str(duration), "--bind-dev", interface, "-J"]
    if udp:
        cmd.append("-u")
        if bandwidth_mbps:
            cmd.extend(["-b", f"{bandwidth_mbps}M"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        data = json.loads(result.stdout)
        if udp:
            bps = data["end"]["sum"]["bits_per_second"]
        else:
            bps = data["end"]["sum_sent"]["bits_per_second"]
        return bps / 1e6  # Mbps
    except Exception as e:
        print(f"  [WARN] iperf3 failed: {e}")
        return None

def run_iperf3_repeated(n_runs=5, **kwargs):
    """Run iperf3 n_runs times and return list of throughput values."""
    results = []
    for i in range(n_runs):
        print(f"    iperf3 run {i+1}/{n_runs}...")
        val = run_iperf3(**kwargs)
        if val is not None:
            results.append(val)
        time.sleep(2)
    return results


# ═══════════════════════════════════════════════════════════════
#  Statistical helpers
# ═══════════════════════════════════════════════════════════════
def wilson_ci(successes, total, z=1.96):
    """Wilson score 95% confidence interval for a proportion."""
    if total == 0:
        return (0.0, 0.0)
    p_hat = successes / total
    denom = 1 + z**2 / total
    center = (p_hat + z**2 / (2 * total)) / denom
    spread = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * total)) / total) / denom
    return (max(0, center - spread), min(1, center + spread))

def fisher_exact_test(a, b, c, d):
    """
    2x2 Fisher's exact test (one-sided).
    a=attack success, b=attack fail, c=control success, d=control fail
    Returns p-value.
    """
    from math import comb, factorial
    # Use scipy if available, else manual
    try:
        from scipy.stats import fisher_exact
        table = [[a, b], [c, d]]
        _, p = fisher_exact(table, alternative="greater")
        return p
    except ImportError:
        # Fallback: hypergeometric
        n = a + b + c + d
        r1 = a + b
        c1 = a + c
        def hyp(x):
            return comb(r1, x) * comb(n - r1, c1 - x) / comb(n, c1)
        p = sum(hyp(x) for x in range(a, min(r1, c1) + 1))
        return p

def spearman_rho(x, y):
    """Spearman rank correlation coefficient and approximate p-value."""
    from scipy.stats import spearmanr
    return spearmanr(x, y)

def coefficient_of_variation(values):
    """CV = std / mean."""
    arr = np.array(values)
    if arr.mean() == 0:
        return float("inf")
    return arr.std() / arr.mean()


# ═══════════════════════════════════════════════════════════════
#  Result logging
# ═══════════════════════════════════════════════════════════════
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

def save_json(data, filename):
    path = RESULTS_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  [SAVED] {path}")
    return path

def save_csv(rows, headers, filename):
    path = RESULTS_DIR / filename
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerows(rows)
    print(f"  [SAVED] {path}")
    return path

def log_experiment(exp_id, result):
    """Append a single experiment result to the master log."""
    entry = {
        "experiment": exp_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    path = RESULTS_DIR / "experiment_log.jsonl"
    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ═══════════════════════════════════════════════════════════════
#  PALA tool wrappers (import from actual codebase)
# ═══════════════════════════════════════════════════════════════
def get_kpi_analyzer():
    """Import and return the actual KPIAnalyzer from PALA."""
    from tools.kpi_analyzer import KPIAnalyzer
    return KPIAnalyzer()

def get_feasibility_checker():
    from tools.feasibility_checker import FeasibilityChecker
    return FeasibilityChecker()

def get_policy_manager():
    from tools.policy_manager import PolicyManager
    return PolicyManager()

def get_session_manager():
    from tools.session_manager import SessionManager
    return SessionManager()

def call_kpi_analyzer(metric="memory_utilization", n_samples=100, run_ml=True):
    """Call the actual KPI Analyzer tool and return its result dict."""
    analyzer = get_kpi_analyzer()
    return analyzer.analyze(metric=metric, n_samples=n_samples, run_ml=run_ml)

def call_feasibility_checker(action, params):
    """
    Call the actual Feasibility Checker and return result.
    params keys: dnn (→target_slice), ambr_dl (→new_dl_ambr), ambr_ul (→new_ul_ambr),
                 imsi (→target_imsi), extra (→extra_params).
    """
    checker = get_feasibility_checker()
    return checker.check(
        action=action,
        target_slice=params.get("dnn") or params.get("target_slice"),
        target_imsi=params.get("imsi") or params.get("target_imsi"),
        new_dl_ambr=params.get("ambr_dl") or params.get("new_dl_ambr"),
        new_ul_ambr=params.get("ambr_ul") or params.get("new_ul_ambr"),
        extra_params={k: v for k, v in params.items()
                      if k not in ("dnn", "target_slice", "imsi", "target_imsi",
                                   "ambr_dl", "new_dl_ambr", "ambr_ul", "new_ul_ambr")}
        or None,
    )

def call_policy_manager(action, params):
    """
    Call the actual Policy Manager and return result.
    params keys: dnn (→target_slice), ambr_dl (→new_dl_ambr), ambr_ul (→new_ul_ambr),
                 imsi (→target_imsi), reason.
    """
    pm = get_policy_manager()
    return pm.apply_policy(
        target_slice=params.get("dnn") or params.get("target_slice"),
        new_dl_ambr=int(params.get("ambr_dl") or params.get("new_dl_ambr", 0)),
        new_ul_ambr=int(params.get("ambr_ul") or params.get("new_ul_ambr", 0)),
        target_imsi=params.get("imsi") or params.get("target_imsi"),
        reason=params.get("reason", "experiment"),
    )


# ═══════════════════════════════════════════════════════════════
#  LLM interaction (for V4 autonomous trials)
# ═══════════════════════════════════════════════════════════════
def run_agent_session(intent, auto_approve=True, max_steps=30):
    """
    Run a complete PALA session with the given intent.
    Returns the full step log including all tool calls.
    auto_approve=True → human_confirm=False (no human gate pauses).
    """
    from agent.agent import PALA
    # PALA uses human_confirm; auto_approve=True means no human gate needed
    agent = PALA(human_confirm=not auto_approve)
    steps = []
    for step in agent.run(intent):
        steps.append(step)
    return steps

def extract_tool_calls(steps):
    """
    Extract tool call records from agent step log.
    Agent yields: {"type": "tool_call", "content": {"tool": ..., "arguments": ...}, "step": N}
    Agent yields: {"type": "tool_result", "content": {"tool": ..., "result": ...}, "step": N}
    """
    calls = []
    # Build a map of tool_call steps, then match with tool_result steps
    call_steps = {}
    for s in steps:
        if not isinstance(s, dict):
            continue
        if s.get("type") == "tool_call":
            content = s.get("content", {})
            step_n = s.get("step", len(calls))
            call_steps[step_n] = {
                "tool": content.get("tool", ""),
                "arguments": content.get("arguments", {}),
                "result": {},
            }
        elif s.get("type") == "tool_result":
            content = s.get("content", {})
            step_n = s.get("step", -1)
            if step_n in call_steps:
                call_steps[step_n]["result"] = content.get("result", {})

    # Return in order
    for step_n in sorted(call_steps):
        calls.append(call_steps[step_n])
    return calls

def extract_feasibility_calls(tool_calls):
    """Filter to only feasibility_checker calls."""
    return [c for c in tool_calls if c["tool"] == "feasibility_checker"]

def extract_policy_calls(tool_calls):
    """Filter to only policy_manager calls."""
    return [c for c in tool_calls if c["tool"] == "policy_manager"]


# ═══════════════════════════════════════════════════════════════
#  Timing / Wait helpers
# ═══════════════════════════════════════════════════════════════
def wait_for_collector(cycles=2, period_s=5):
    """Wait for n collector cycles to pass."""
    wait = cycles * period_s + 1
    print(f"  Waiting {wait}s for {cycles} collector cycles...")
    time.sleep(wait)

def timestamp_now():
    return datetime.now(timezone.utc)
