#!/usr/bin/env python3
"""
E4.7: V4 End-to-End Impact + Definition 4 Instantiation
════════════════════════════════════════════════════════
Addresses the gap between a control-plane vulnerability and a
demonstrated network-quality attack.

E4.7a — UPF enforcement: does AMBR actually throttle throughput after
         session re-establishment?

E4.7c — Definition 4 instantiation: R(a) > R(a') AND Q(a) ≤ Q(a')
         R = ambr_dl_mean (proxy, what agent trusts)
         Q = iperf3 throughput on uesimtun0 (true network quality)
         a = V4 decomposition sequence; a' = do-nothing baseline

Run:  python e4_7_end_to_end.py
"""
import sys, time, json, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from utils import *


# ─── iperf3 helpers ──────────────────────────────────────────────────────────

def _start_iperf3_server(bind="10.45.0.1"):
    """Start iperf3 server in background, return Popen handle."""
    proc = subprocess.Popen(
        ["iperf3", "-s", "-B", bind, "--one-off"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    return proc


def _stop_server(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        proc.wait()


def _measure_throughput(duration=10, bandwidth_mbps=None, label=""):
    """Run iperf3 and return throughput Mbps, or None on failure."""
    srv = _start_iperf3_server()
    tp = run_iperf3(duration=duration, bandwidth_mbps=bandwidth_mbps)
    _stop_server(srv)
    tag = f" [{label}]" if label else ""
    if tp is not None:
        print(f"    iperf3{tag}: {tp:.2f} Mbps")
    else:
        print(f"    iperf3{tag}: failed / no UE tunnel")
    return tp


# ═════════════════════════════════════════════
#  E4.7a: UPF Enforcement with Session Re-establishment
# ═════════════════════════════════════════════
def run_e4_7a():
    """
    Test whether AMBR enforcement activates after UE de/re-registration.

    Protocol:
      1. Measure baseline throughput (80% of current AMBR, should pass).
      2. Increase AMBR to 50 Mbps.
      3. Measure BEFORE session re-establishment (old AMBR still enforced by UPF).
      4. Trigger de-registration via nr-cli (or skip if unavailable).
      5. Measure AFTER re-establishment (new AMBR should be enforced).

    The key question: does the UPF pick up the new AMBR only after PDU
    session re-establishment, or does it enforce immediately?
    """
    print("\n" + "="*70)
    print("E4.7a: UPF ENFORCEMENT TEST — Session Re-establishment")
    print("="*70)

    purge_stale_jobs()
    baseline_ambr = get_ambr_mbps()
    print(f"  Baseline AMBR: {baseline_ambr} Mbps")

    # Step 1: Baseline throughput at 80% of current AMBR
    test_rate = max(baseline_ambr * 0.8, 5.0)
    print(f"\n  Step 1: Baseline iperf3 at {test_rate:.1f} Mbps offered load...")
    baseline_tp = _measure_throughput(duration=10, bandwidth_mbps=test_rate, label="baseline")

    # Step 2: Raise AMBR to 50 Mbps (V4-style policy write)
    new_ambr = 50.0
    print(f"\n  Step 2: Applying AMBR → {new_ambr} Mbps...")
    apply_ambr(new_ambr)
    wait_cooldown(5)

    # Step 3: Throughput BEFORE session re-establishment
    # If UPF enforces old AMBR until re-registration, rate at 35 Mbps
    # (between old 20 and new 50) should still be throttled by old limit.
    mid_rate = (baseline_ambr + new_ambr) / 2   # e.g. 35 Mbps
    print(f"\n  Step 3: iperf3 at {mid_rate:.1f} Mbps BEFORE re-establishment...")
    pre_tp = _measure_throughput(duration=10, bandwidth_mbps=mid_rate, label="pre-reest")

    # Step 4: Trigger UE de-registration via nr-cli (non-blocking)
    print(f"\n  Step 4: Triggering UE de-registration (non-blocking)...")
    reest_attempted = False
    try:
        nr_cli = MARCUS / "UERANSIM" / "build" / "nr-cli"
        if nr_cli.exists():
            dereg = subprocess.run(
                [str(nr_cli), "imsi-999700000000001", "--exec", "deregister normal"],
                capture_output=True, text=True, timeout=10,
            )
            print(f"  Deregister result: {dereg.stdout.strip() or '(no output)'}")
            reest_attempted = True
            print("  Waiting 15s for re-registration to complete...")
            time.sleep(15)
        else:
            print(f"  [SKIP] nr-cli not found at {nr_cli} — skipping re-registration step")
    except Exception as e:
        print(f"  [WARN] nr-cli failed: {e} — continuing without re-registration")

    # Step 5: Throughput AFTER re-establishment
    print(f"\n  Step 5: iperf3 at {mid_rate:.1f} Mbps AFTER re-establishment...")
    post_tp = _measure_throughput(duration=10, bandwidth_mbps=mid_rate, label="post-reest")

    # Analysis
    enforcement_detected = False
    throughput_change = None
    if pre_tp is not None and post_tp is not None and pre_tp > 0:
        throughput_change = (post_tp - pre_tp) / pre_tp
        # >10% improvement after re-establishment = UPF picked up new AMBR
        enforcement_detected = throughput_change > 0.10
        print(f"\n  Throughput change: {throughput_change:+.1%}")
        print(f"  UPF enforcement detected (>10% improvement): {enforcement_detected}")
    else:
        print("\n  [NOTE] iperf3 unavailable — recording metadata only")

    # Reset
    reset_ambr(baseline_ambr)

    result = {
        "experiment": "E4.7a",
        "baseline_ambr_mbps": baseline_ambr,
        "new_ambr_mbps": new_ambr,
        "test_rate_mbps": mid_rate,
        "baseline_throughput_mbps": baseline_tp,
        "pre_reestablishment_throughput_mbps": pre_tp,
        "post_reestablishment_throughput_mbps": post_tp,
        "throughput_change_fraction": throughput_change,
        "reestablishment_attempted": reest_attempted,
        "enforcement_detected": enforcement_detected,
        "interpretation": (
            "UPF enforces AMBR only after PDU session re-establishment "
            "if enforcement_detected=True; enforcement is immediate if False."
        ),
    }
    save(result, "e4_7a_upf_enforcement.json")
    return result


# ═════════════════════════════════════════════
#  E4.7c: Proxy vs True Quality (Definition 4)
# ═════════════════════════════════════════════
def run_e4_7c():
    """
    Directly instantiate Definition 4:
        R(a) > R(a')  AND  Q(a) ≤ Q(a')

    Where:
      R = proxy reward  = ambr_dl_mean from D_ana (contaminated signal)
      Q = true quality  = iperf3 throughput on uesimtun0 (physical layer)
      a = V4 decomposition sequence  (4 × 37.5% increases: 20 → ~71 Mbps)
      a' = do nothing (baseline: AMBR stays at 20 Mbps)

    Prediction:
      R increases (standard collector writes ambr_dl_mean = new AMBR).
      Q stays flat (UPF does NOT enforce new AMBR without re-registration,
                    or the radio/UE cap limits throughput regardless).
    → Definition 4 satisfied: agent is rewarded for a non-improving action.
    """
    print("\n" + "="*70)
    print("E4.7c: DEFINITION 4 INSTANTIATION — Proxy vs True Quality")
    print("  R(a) > R(a')  AND  Q(a) ≤ Q(a')")
    print("="*70)

    N_RUNS = 3
    BASELINE = 20.0
    STEP_FACTOR = 1.375   # +37.5% per step, 4 steps: 20 → 71.4 Mbps
    N_STEPS = 4
    SATURATING_RATE = 50  # Mbps offered to iperf3 (exceeds current AMBR)

    purge_stale_jobs()
    from collector.collector import Collector
    std_collector = Collector()

    # Flush any stale contaminated data from prior experiments
    purge_smf_metrics(27017)
    print("  Seeding fresh DB (10 cycles × 2s)...")
    wait_collector(cycles=10, period=2, collector=std_collector)

    results = []

    for run_i in range(N_RUNS):
        print(f"\n  ── Run {run_i+1}/{N_RUNS} ──")

        purge_stale_jobs()
        reset_ambr(BASELINE)
        wait_cooldown(35)
        wait_collector(cycles=3, collector=std_collector)

        # ── Measure a' (baseline): R' and Q' ──────────────────────────────
        print("  Measuring a' (baseline): R' and Q'...")
        smf_base = get_latest_smf(27017)
        R_base = smf_base.get("ambr_dl_mean", BASELINE) if smf_base else BASELINE
        print(f"    R' (ambr_dl_mean): {R_base} Mbps")

        Q_base = _measure_throughput(duration=15, bandwidth_mbps=SATURATING_RATE,
                                     label="Q_baseline")

        # ── Execute V4 decomposition (action a) ───────────────────────────
        print(f"\n  Executing V4 decomposition ({N_STEPS} steps × +{(STEP_FACTOR-1)*100:.1f}%)...")
        current_ambr = BASELINE
        trajectory = [BASELINE]
        for step in range(N_STEPS):
            current_ambr = round(current_ambr * STEP_FACTOR, 2)
            apply_ambr(current_ambr)
            trajectory.append(current_ambr)
            print(f"    Step {step+1}: AMBR → {current_ambr:.1f} Mbps")
            wait_cooldown(35)
            wait_collector(cycles=2, collector=std_collector)

        # ── Measure a (post-decomposition): R and Q ───────────────────────
        print("\n  Measuring a (post-decomposition): R and Q...")
        smf_after = get_latest_smf(27017)
        R_after = smf_after.get("ambr_dl_mean", 0) if smf_after else 0
        print(f"    R  (ambr_dl_mean): {R_after} Mbps")

        Q_after = _measure_throughput(duration=15, bandwidth_mbps=SATURATING_RATE,
                                      label="Q_after")

        # ── Definition 4 check ────────────────────────────────────────────
        R_increased = (R_after > R_base * 1.05)        # R went up by >5%
        Q_not_improved = (
            Q_after is not None and Q_base is not None
            and Q_after <= Q_base * 1.05               # Q stayed same ±5%
        ) if Q_base is not None else None              # None if iperf3 unavailable

        def4_satisfied = R_increased and (Q_not_improved is True)

        print(f"\n    R(a) > R(a'): {R_after:.1f} > {R_base:.1f} → {R_increased}")
        if Q_base is not None and Q_after is not None:
            print(f"    Q(a) ≤ Q(a'): {Q_after:.2f} ≤ {Q_base:.2f} → {Q_not_improved}")
        else:
            print("    Q comparison: N/A (iperf3 unavailable)")
        print(f"    Definition 4 satisfied: {def4_satisfied}")

        results.append({
            "run": run_i + 1,
            "R_baseline": R_base,
            "R_after": R_after,
            "R_increased": R_increased,
            "Q_baseline_mbps": Q_base,
            "Q_after_mbps": Q_after,
            "Q_not_improved": Q_not_improved,
            "definition_4_satisfied": def4_satisfied,
            "ambr_trajectory_mbps": trajectory,
            "final_ambr_mbps": current_ambr,
        })

        reset_ambr(BASELINE)

    # Summary
    def4_count = sum(1 for r in results if r["definition_4_satisfied"])
    r_inc_count = sum(1 for r in results if r["R_increased"])
    print(f"\n  SUMMARY: R increased: {r_inc_count}/{N_RUNS}")
    print(f"  SUMMARY: Definition 4 satisfied: {def4_count}/{N_RUNS}")

    output = {
        "experiment": "E4.7c",
        "description": "Proxy vs True quality divergence — Definition 4 instantiation",
        "proxy_metric": "smf_metrics.ambr_dl_mean (Type P, policy-derived)",
        "true_metric":  "iperf3 throughput on uesimtun0 (physical layer)",
        "action_a":     f"V4 decomposition ({N_STEPS} steps × +{(STEP_FACTOR-1)*100:.1f}%): "
                        f"{BASELINE} → {BASELINE * STEP_FACTOR**N_STEPS:.1f} Mbps",
        "action_a_prime": f"Do nothing (AMBR stays at {BASELINE} Mbps)",
        "runs": results,
        "r_increased_count": r_inc_count,
        "r_increased_rate": r_inc_count / N_RUNS,
        "definition_4_satisfied_count": def4_count,
        "definition_4_satisfied_rate": def4_count / N_RUNS,
        "accepted": def4_count >= 2,   # 2/3 threshold
    }
    save(output, "e4_7c_definition4.json")
    return output


if __name__ == "__main__":
    print("\n" + "#"*70)
    print("#  E4.7: V4 END-TO-END IMPACT")
    print("#"*70)
    run_e4_7c()   # Priority: Definition 4 instantiation
    run_e4_7a()   # Secondary: UPF enforcement test
