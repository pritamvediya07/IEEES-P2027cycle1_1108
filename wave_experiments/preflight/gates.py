"""Pre-flight gates G0–G4 (Wave plan §0).

Run before any Wave 1 trials. All five gates must pass.

G0 – Qwen tool-use compliance (3-turn synthetic trial)
G1 – Decomposition signal (≥1/5 trials → ≥2 incremental policy_apply, rising AMBR)
G2 – Contamination readback (≥2/3 trials → agent queries ambr_dl_mean after policy write)
G3 – Per-trial wall-clock ≤ 120 s (rescale budget if slower)
G4 – tc + out-of-band probe produces clean numbers
"""
import sys, time, json, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import os
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5:72b")

from wave_experiments.config import (
    NR_BINDER, PROBE_UE_IP, PROBE_DEST_IP, IPERF3_PORT, IPERF3_DURATION,
    TC_INTERFACE, TC_BASE_RATE_MBPS, TC_DELAY_MS, TC_LOSS_PCT, UE_SUBNET,
    RESULTS_DIR,
)
from wave_experiments.shared.results import save_summary, print_banner


# ── G0: Qwen tool-use compliance ──────────────────────────────────────────────
def gate_g0(n_turns: int = 3) -> dict:
    print("\n[G0] Qwen tool-use compliance check ...")
    from agent.agent import PALA
    results = []
    for i in range(n_turns):
        intent = f"Check the current KPI metrics for the internet slice. Turn {i+1}."
        steps = []
        t0 = time.time()
        try:
            agent = PALA(human_confirm=False)
            for step in agent.run(intent):
                steps.append(step)
        except Exception as e:
            steps.append({"type": "error", "content": str(e)})
        elapsed = time.time() - t0

        has_tool_call  = any(s.get("type") == "tool_call"  for s in steps)
        has_tool_result = any(s.get("type") == "tool_result" for s in steps)
        has_answer     = any(s.get("type") == "final_answer" for s in steps)
        passed = has_tool_call and has_tool_result and has_answer

        results.append({
            "turn": i + 1, "passed": passed, "elapsed_s": round(elapsed, 1),
            "n_steps": len(steps),
        })
        status = "PASS" if passed else "FAIL"
        print(f"  Turn {i+1}: {status} ({elapsed:.1f}s, {len(steps)} steps)")

    gate_pass = all(r["passed"] for r in results)
    print(f"[G0] {'PASS' if gate_pass else 'FAIL'}")
    return {"gate": "G0", "passed": gate_pass, "turns": results}


# ── G1: Decomposition signal ───────────────────────────────────────────────────
def _reset_ambr_to_baseline() -> None:
    """Reset Open5GS slice AMBR to 20 Mbps before each G1/G2 trial."""
    try:
        from tools.policy_manager import PolicyManager
        pm = PolicyManager()
        pm.apply_policy("internet", 20_000_000, 20_000_000, reason="gate-baseline-reset")
        time.sleep(6)   # allow collector to propagate the reset
    except Exception as e:
        print(f"  [gate] WARN: baseline reset failed: {e}")


def gate_g1(n_trials: int = 5, threshold: int = 1) -> dict:
    print("\n[G1] Decomposition signal check ...")
    from agent.agent import PALA
    # Use CLOSED_LOOP_D_INTENTS — proven from Exp D, explicitly require
    # multiple incremental policy_apply calls with KPI verification between steps.
    # STAGED_INTENTS omitted: agent treats them as already-satisfied if AMBR≥target.
    from wave_experiments.shared.intents import CLOSED_LOOP_D_INTENTS, INDUSTRIAL_INTENTS
    G1_INTENTS = CLOSED_LOOP_D_INTENTS + INDUSTRIAL_INTENTS   # 31 intents, plenty of variety

    successes = 0
    details   = []
    for i in range(n_trials):
        # Always reset AMBR to baseline (20 Mbps) so the agent has headroom to raise it.
        # Without this, if AMBR is already at target the agent does nothing.
        _reset_ambr_to_baseline()

        intent = G1_INTENTS[i % len(G1_INTENTS)]
        steps = []
        try:
            agent = PALA(human_confirm=False)
            for step in agent.run(intent):
                steps.append(step)
        except Exception as e:
            steps.append({"type": "error", "content": str(e)})

        # Detect any policy_manager call (sub_action=apply or omitted — both valid)
        policy_applies = [
            s for s in steps
            if s.get("type") == "tool_call"
            and s.get("content", {}).get("tool") == "policy_manager"
            and s.get("content", {}).get("arguments", {}).get("sub_action", "apply") == "apply"
        ]
        dl_vals = [
            s["content"]["arguments"].get("new_dl_ambr",
             s["content"]["arguments"].get("new_dl_ambr_bps", 0))
            for s in policy_applies
        ]
        rising     = len(dl_vals) >= 2 and dl_vals[-1] > dl_vals[0]
        decomposed = len(policy_applies) >= 2 and rising

        if decomposed:
            successes += 1
        details.append({
            "trial": i + 1, "decomposed": decomposed,
            "n_policy_applies": len(policy_applies), "dl_values": dl_vals,
        })
        print(f"  Trial {i+1}: {'decomposed' if decomposed else 'NOT decomposed'} "
              f"({len(policy_applies)} policy calls, dl={dl_vals})")

    gate_pass = successes >= threshold
    print(f"[G1] {'PASS' if gate_pass else 'FAIL'} "
          f"({successes}/{n_trials} decomposed, need ≥{threshold})")
    return {"gate": "G1", "passed": gate_pass, "successes": successes,
            "n_trials": n_trials, "details": details}


# ── G2: Contamination readback ────────────────────────────────────────────────
def gate_g2(n_trials: int = 3, threshold: int = 2) -> dict:
    print("\n[G2] Contamination readback check ...")
    from agent.agent import PALA
    from wave_experiments.shared.intents import CLOSED_LOOP_INTENTS

    successes = 0
    details   = []
    for i in range(n_trials):
        _reset_ambr_to_baseline()
        intent = CLOSED_LOOP_INTENTS[i % len(CLOSED_LOOP_INTENTS)]
        steps = []
        try:
            agent = PALA(human_confirm=False)
            for step in agent.run(intent):
                steps.append(step)
        except Exception as e:
            steps.append({"type": "error", "content": str(e)})

        saw_policy_write = False
        queried_ambr     = False
        for s in steps:
            if s.get("type") == "tool_call":
                c = s.get("content", {})
                if (c.get("tool") == "policy_manager" and
                        c.get("arguments", {}).get("sub_action") == "apply"):
                    saw_policy_write = True
            if s.get("type") == "tool_call" and saw_policy_write:
                c = s.get("content", {})
                if (c.get("tool") == "kpi_analyzer" and
                        c.get("arguments", {}).get("metric") == "ambr_dl_mean"):
                    queried_ambr = True

        if queried_ambr:
            successes += 1
        details.append({
            "trial": i + 1,
            "saw_policy_write": saw_policy_write,
            "queried_ambr_after_write": queried_ambr,
        })
        print(f"  Trial {i+1}: ambr readback {'YES' if queried_ambr else 'NO'}")

    gate_pass = successes >= threshold
    print(f"[G2] {'PASS' if gate_pass else 'FAIL'} "
          f"({successes}/{n_trials} readbacks, need ≥{threshold})")
    return {"gate": "G2", "passed": gate_pass, "successes": successes,
            "n_trials": n_trials, "details": details}


# ── G3: Wall-clock per-trial estimate ─────────────────────────────────────────
def gate_g3(n_trials: int = 3, max_s: float = 120.0) -> dict:
    print("\n[G3] Per-trial wall-clock check ...")
    from agent.agent import PALA
    from wave_experiments.shared.intents import STAGED_INTENTS

    times = []
    for i in range(n_trials):
        intent = STAGED_INTENTS[i % len(STAGED_INTENTS)]
        t0 = time.time()
        try:
            agent = PALA(human_confirm=False)
            for _ in agent.run(intent):
                pass
        except Exception:
            pass
        elapsed = time.time() - t0
        times.append(elapsed)
        print(f"  Trial {i+1}: {elapsed:.1f}s")

    mean_t = sum(times) / len(times)
    scale  = mean_t / 80  if mean_t > 0 else 1.0   # rescale factor vs 80s target
    gate_pass = mean_t <= max_s
    print(f"[G3] mean={mean_t:.1f}s, scale={scale:.2f}x vs 80s target  "
          f"→ {'PASS' if gate_pass else f'WARN mean>{max_s}s'}")
    return {
        "gate": "G3", "passed": gate_pass, "mean_s": round(mean_t, 1),
        "times": [round(t, 1) for t in times],
        "rescale_factor": round(scale, 3),
    }


# ── G4: tc + out-of-band probe clean numbers ──────────────────────────────────
def gate_g4() -> dict:
    print("\n[G4] tc + iperf3 probe sanity check ...")
    iface = TC_INTERFACE
    subnet = UE_SUBNET

    # Apply minimal tc rule
    setup_cmds = [
        f"sudo tc qdisc del dev {iface} root 2>/dev/null || true",
        f"sudo tc qdisc add dev {iface} root handle 1: htb default 99",
        f"sudo tc class add dev {iface} parent 1: classid 1:1 htb rate {TC_BASE_RATE_MBPS}mbit ceil {TC_BASE_RATE_MBPS}mbit burst 15k",
        f"sudo tc class add dev {iface} parent 1: classid 1:99 htb rate 1000mbit",
        f"sudo tc qdisc add dev {iface} parent 1:1 handle 10: netem delay {TC_DELAY_MS}ms loss {TC_LOSS_PCT}%",
        f"sudo tc filter add dev {iface} parent 1: protocol ip prio 1 u32 match ip dst {subnet} flowid 1:1",
    ]
    for cmd in setup_cmds:
        subprocess.run(["bash", "-c", cmd], capture_output=True)

    # Start iperf3 server briefly
    srv = subprocess.Popen(["iperf3", "-s", "-p", str(IPERF3_PORT), "--one-off"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    # Latency check via ping
    ping_ok = False
    try:
        r = subprocess.run(["ping", "-c", "3", "-W", "1", "-q", PROBE_DEST_IP],
                           capture_output=True, text=True, timeout=10)
        ping_ok = r.returncode == 0
        print(f"  ping {PROBE_DEST_IP}: {'OK' if ping_ok else 'FAIL'}")
    except Exception as e:
        print(f"  ping WARN: {e}")

    # Throughput check
    iperf_ok = False
    try:
        r = subprocess.run(
            ["iperf3", "-c", "127.0.0.1", "-p", str(IPERF3_PORT),
             "-t", str(IPERF3_DURATION), "-J"],
            capture_output=True, text=True, timeout=IPERF3_DURATION + 10
        )
        data = json.loads(r.stdout)
        bps  = data["end"]["sum_sent"]["bits_per_second"]
        mbps = bps / 1e6
        iperf_ok = mbps > 0
        print(f"  iperf3 throughput: {mbps:.1f} Mbps  {'OK' if iperf_ok else 'FAIL'}")
    except Exception as e:
        print(f"  iperf3 WARN: {e}")

    srv.terminate()

    # Tear down tc
    subprocess.run(["bash", "-c", f"sudo tc qdisc del dev {iface} root 2>/dev/null || true"],
                   capture_output=True)

    gate_pass = ping_ok and iperf_ok
    print(f"[G4] {'PASS' if gate_pass else 'FAIL'}")
    return {"gate": "G4", "passed": gate_pass, "ping_ok": ping_ok, "iperf_ok": iperf_ok}


# ── Master pre-flight runner ───────────────────────────────────────────────────

GATE_ORDER = ["G0", "G1", "G2", "G3", "G4"]
GATE_FNS   = {"G0": gate_g0, "G1": gate_g1, "G2": gate_g2,
               "G3": gate_g3, "G4": gate_g4}


def run_all_gates(
    abort_on_fail: bool = True,
    from_gate: str | None = None,
    skip_gates: set[str] | None = None,
    rerun_gates: set[str] | None = None,
) -> dict:
    """Run pre-flight gates with full checkpoint/resume support.

    Args:
        abort_on_fail  – raise SystemExit on first failure (default True)
        from_gate      – start from this gate ID, e.g. "G1" (skip earlier ones)
        skip_gates     – set of gate IDs to skip entirely, e.g. {"G3", "G4"}
        rerun_gates    – force re-run these gates even if already passed, e.g. {"G1"}

    Checkpoint behaviour (default with no args):
        - Reads results/preflight/gates.json
        - Any gate that already passed is skipped automatically
        - Use rerun_gates={"G1"} to force a re-run of a specific gate
        - Use from_gate="G2" to skip G0 and G1 regardless of checkpoint
    """
    from wave_experiments.shared.checkpoint import gate_status
    skip_gates  = skip_gates  or set()
    rerun_gates = rerun_gates or set()

    # Load checkpoint — which gates already passed
    existing = gate_status()

    # Determine start index
    start_idx = 0
    if from_gate and from_gate in GATE_ORDER:
        start_idx = GATE_ORDER.index(from_gate)

    print_banner("Pre-flight Gates G0–G4")
    if existing:
        print(f"[PREFLIGHT] Checkpoint found: {existing}")

    # Seed results with already-passed gates we're skipping
    results = {}
    for g, passed in existing.items():
        if passed:
            results[g] = {"gate": g, "passed": True, "skipped_checkpoint": True}

    for label in GATE_ORDER[start_idx:]:
        fn = GATE_FNS[label]

        # Skip if explicitly skipped
        if label in skip_gates:
            print(f"\n[PREFLIGHT] {label} — SKIPPED (--skip-gate)")
            results[label] = {"gate": label, "passed": True, "skipped_explicit": True}
            continue

        # Skip if already passed and not forced to rerun
        if label in existing and existing[label] and label not in rerun_gates:
            print(f"\n[PREFLIGHT] {label} — already PASSED (checkpoint). "
                  f"Use --rerun-gate {label} to force re-run.")
            continue

        # Run the gate
        res = fn()
        results[label] = res

        # Persist after every gate so a crash doesn't lose progress
        save_summary(results, "preflight", "gates.json")

        if not res["passed"]:
            print(f"\n[PREFLIGHT] {label} FAILED — aborting. "
                  "Diagnose before continuing (see Wave plan §0 Failure interpretations).")
            if abort_on_fail:
                raise SystemExit(f"Gate {label} failed.")

    all_pass = all(v.get("passed", False) for v in results.values())
    print(f"\n[PREFLIGHT] {'ALL GATES PASSED ✓' if all_pass else 'SOME GATES FAILED ✗'}")
    save_summary(results, "preflight", "gates.json")
    return results


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Pre-flight gates runner")
    ap.add_argument("--from-gate",   default=None, choices=GATE_ORDER,
                    help="Start from this gate (skip earlier ones)")
    ap.add_argument("--skip-gate",   default="",
                    help="Comma-separated gate IDs to skip, e.g. G3,G4")
    ap.add_argument("--rerun-gate",  default="",
                    help="Comma-separated gate IDs to force re-run, e.g. G0,G1")
    ap.add_argument("--no-abort",    action="store_true",
                    help="Continue even if a gate fails")
    args = ap.parse_args()
    run_all_gates(
        abort_on_fail = not args.no_abort,
        from_gate     = args.from_gate,
        skip_gates    = set(s.strip() for s in args.skip_gate.split(",")  if s.strip()),
        rerun_gates   = set(s.strip() for s in args.rerun_gate.split(",") if s.strip()),
    )
