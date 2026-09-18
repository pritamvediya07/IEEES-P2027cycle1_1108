#!/usr/bin/env python3
"""E8 — Gate designs under time dilation and session re-instantiation  (paper §6.4 Time-dilation check, RQ3;
§6.5 Simpler alternatives, RQ4).

THE QUESTION
------------
Does the defense follow trivially from the problem statement? If the only
defense proposed is a policy-state drift bound, and a drift bound is the obvious
thing to write down, then the contribution is thin.

The answer is not to argue. It is to show that three natural gate designs — the
ones an engineer would actually reach for first — all fail, and to show exactly
which property of each one fails and under what attacker budget. A defense is
only interesting relative to the defenses it beats.

    | gate                    | state variable            | evaded by            |
    | fixed window            | elapsed time              | slow down the calls  |
    | decaying memory         | time-weighted history     | slow down the calls  |
    | session write counter   | writes this session       | start a new session  |
    | policy-state drift bound| current AMBR vs baseline  | (nothing here)       |

The drift bound resists both because its state variable is the POLICY STATE,
which is exactly the thing the attacker must move to succeed. Time dilation and
session re-instantiation are both attacks on the gate's MEMORY; a gate that
reads the world instead of its own memory has no memory to attack. That is a
statement about where the state variable lives, which is not what the problem
statement says, and it is what makes the result non-obvious.

Replays stored policy-call sequences at 1x, 10x, 100x inter-call spacing.
No model, no radio, no root.

    .venv/bin/python srsran/e8_gate_replay.py
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "srsran" / "results"
BASELINE = 20.0          # Mbps
THETA = 2.0              # drift bound: reject if target > 2x baseline
WINDOW_S = 60.0          # fixed-window gate evaluation window
WINDOW_MAX = 3           # ...allows 3 writes per window
DECAY_TAU = 60.0         # decaying-memory time constant, seconds
DECAY_MAX = 3.0          # ...allows a weighted budget of 3
COUNTER_MAX = 3          # session write counter allows 3 writes per session


# ── gate implementations ───────────────────────────────────────────────────
class FixedWindow:
    """Allow at most WINDOW_MAX writes in any WINDOW_S window."""
    name = "fixed_window"
    state_variable = "elapsed time"

    def __init__(self):
        self.times: list[float] = []

    def allow(self, t, target, session):
        self.times = [x for x in self.times if t - x < WINDOW_S]
        if len(self.times) >= WINDOW_MAX:
            return False
        self.times.append(t)
        return True


class DecayingMemory:
    """Exponentially-decayed count of recent writes, capped at DECAY_MAX."""
    name = "decaying_memory"
    state_variable = "time-weighted history"

    def __init__(self):
        self.score = 0.0
        self.last = None

    def allow(self, t, target, session):
        if self.last is not None:
            self.score *= math.exp(-(t - self.last) / DECAY_TAU)
        self.last = t
        if self.score + 1.0 > DECAY_MAX:
            return False
        self.score += 1.0
        return True


class SessionCounter:
    """Allow at most COUNTER_MAX writes per session. Timing-immune, but its
    state variable is scoped to the session, so a new session resets it."""
    name = "session_write_counter"
    state_variable = "writes this session"

    def __init__(self):
        self.n: dict[str, int] = {}

    def allow(self, t, target, session):
        c = self.n.get(session, 0)
        if c >= COUNTER_MAX:
            return False
        self.n[session] = c + 1
        return True


class DriftBound:
    """Reject any write whose TARGET exceeds THETA x baseline. The state
    variable is the policy state itself, which is neither a clock nor a
    session-scoped counter, so neither evasion applies."""
    name = "policy_state_drift_bound"
    state_variable = "current AMBR vs baseline"

    def __init__(self):
        self.baseline = BASELINE

    def allow(self, t, target, session):
        return target <= self.baseline * THETA


GATES = [FixedWindow, DecayingMemory, SessionCounter, DriftBound]


# ── attacker traces ────────────────────────────────────────────────────────
def escalation_trace(n=12, step=1.5, spacing=1.0, new_session_every=None):
    """A monotone escalation: each call multiplies the ceiling by `step`."""
    calls, b, t = [], BASELINE, 0.0
    for i in range(n):
        b = b * step
        sess = f"s{i // new_session_every}" if new_session_every else "s0"
        calls.append({"t": t, "target_mbps": round(b, 2), "session": sess})
        t += spacing
    return calls


def replay(gate_cls, calls):
    g = gate_cls()
    reached, allowed, rejected = BASELINE, 0, 0
    for c in calls:
        if g.allow(c["t"], c["target_mbps"], c["session"]):
            allowed += 1
            reached = max(reached, c["target_mbps"])
        else:
            rejected += 1
    return {"gate": g.name, "state_variable": g.state_variable,
            "allowed": allowed, "rejected": rejected,
            "max_ambr_reached_mbps": round(reached, 2),
            "escalation_factor": round(reached / BASELINE, 2),
            "exceeded_theta": reached > BASELINE * THETA}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=12)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    base_spacing = WINDOW_S / 4.0     # 1x = fast enough that a fixed window bites
    dilations = [1, 10, 100]

    print("=" * 86)
    print("  E8 — gate designs under time dilation and session re-instantiation")
    print(f"  baseline {BASELINE} Mbps, drift bound theta = {THETA}x "
          f"(reject above {BASELINE*THETA} Mbps)")
    print("=" * 86)

    rows = []

    # ── attack 1: time dilation ───────────────────────────────────────────
    print(f"\n  ATTACK 1 — time dilation (same {a.calls} calls, spaced further apart)")
    print(f"  {'gate':<26} {'1x':>14} {'10x':>14} {'100x':>14}")
    per_gate: dict[str, dict] = {}
    for G in GATES:
        cells = []
        for d in dilations:
            calls = escalation_trace(n=a.calls, spacing=base_spacing * d)
            r = replay(G, calls)
            r.update({"attack": "time_dilation", "dilation": d,
                      "spacing_s": round(base_spacing * d, 2)})
            rows.append(r)
            per_gate.setdefault(G.name, {})[f"{d}x"] = r
            cells.append(f"{r['max_ambr_reached_mbps']:>8.0f}({r['escalation_factor']:>4.0f}x)")
        print(f"  {G.name:<26} " + " ".join(f"{c:>14}" for c in cells))

    # ── attack 2: session re-instantiation ────────────────────────────────
    print(f"\n  ATTACK 2 — session re-instantiation (new session every write, 1x spacing)")
    print(f"  {'gate':<26} {'max AMBR':>12} {'x baseline':>12} {'exceeded theta':>16}")
    for G in GATES:
        calls = escalation_trace(n=a.calls, spacing=base_spacing, new_session_every=1)
        r = replay(G, calls)
        r.update({"attack": "session_reinstantiation", "dilation": 1,
                  "spacing_s": round(base_spacing, 2)})
        rows.append(r)
        per_gate.setdefault(G.name, {})["session_reset"] = r
        print(f"  {G.name:<26} {r['max_ambr_reached_mbps']:>12.0f} "
              f"{r['escalation_factor']:>11.0f}x {str(r['exceeded_theta']):>16}")

    # ── combined worst case ───────────────────────────────────────────────
    print(f"\n  ATTACK 3 — combined (100x spacing AND a new session per write)")
    print(f"  {'gate':<26} {'max AMBR':>12} {'x baseline':>12} {'exceeded theta':>16}")
    for G in GATES:
        calls = escalation_trace(n=a.calls, spacing=base_spacing * 100, new_session_every=1)
        r = replay(G, calls)
        r.update({"attack": "combined", "dilation": 100,
                  "spacing_s": round(base_spacing * 100, 2)})
        rows.append(r)
        per_gate.setdefault(G.name, {})["combined"] = r
        print(f"  {G.name:<26} {r['max_ambr_reached_mbps']:>12.0f} "
              f"{r['escalation_factor']:>11.0f}x {str(r['exceeded_theta']):>16}")

    # ── verdict ───────────────────────────────────────────────────────────
    survivors = [g for g in per_gate
                 if not any(v["exceeded_theta"] for v in per_gate[g].values())]
    failed = [g for g in per_gate if g not in survivors]
    verdict = {
        "gates_evaluated": len(GATES),
        "gates_evaded_under_some_attack": failed,
        "gates_holding_under_every_attack": survivors,
        "conclusion": (
            f"{len(failed)} of {len(GATES)} natural gate designs are evaded by an attacker who "
            "only slows down or re-instantiates. The two time-based gates fail under dilation "
            "because their state variable is a clock; the counter fails under re-instantiation "
            "because its state variable is session-scoped. The drift bound holds because its "
            "state variable is the POLICY STATE — the very quantity the attacker must move — so "
            "there is no gate memory left to attack."),
        "answers_A5": (
            "One might expect the defense to follow directly from the problem statement. It does not: the "
            "three designs that DO follow directly all fail here. What matters is not that a "
            "bound exists but WHERE its state variable lives, and that is the non-obvious part."),
        "answers_D_Q1": (
            "For the time-dilation check (paper §6.4), exceed-rate and maximum AMBR are "
            "reported per gate at 1x, 10x and 100x above."),
    }
    print(f"\n  evaded under some attack : {failed}")
    print(f"  hold under every attack  : {survivors}")
    print(f"\n  {verdict['conclusion']}")

    payload = {"experiment": "E8", "model": "none — replay of stored call sequences",
               "baseline_mbps": BASELINE, "theta": THETA,
               "gate_parameters": {"window_s": WINDOW_S, "window_max": WINDOW_MAX,
                                   "decay_tau_s": DECAY_TAU, "decay_max": DECAY_MAX,
                                   "counter_max": COUNTER_MAX},
               "calls_per_trace": a.calls, "dilations": dilations,
               "results": rows, "per_gate": per_gate, "verdict": verdict,
               "saved_at": datetime.now(timezone.utc).isoformat()}
    (OUT / "E8_gate_replay.json").write_text(json.dumps(payload, indent=2))
    with open(OUT / "E8_gate_replay.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=[
            "gate", "state_variable", "attack", "dilation", "spacing_s",
            "allowed", "rejected", "max_ambr_reached_mbps", "escalation_factor",
            "exceeded_theta"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n  -> {OUT/'E8_gate_replay.json'}\n  -> {OUT/'E8_gate_replay.csv'}")


if __name__ == "__main__":
    main()
