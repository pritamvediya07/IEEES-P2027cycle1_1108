#!/usr/bin/env python3
"""
experiments/hedgetune/hedgetune.py
HedgeTune k† calibration — adapted from Khalaf et al. (NeurIPS 2025) Algorithm 4
for the PALA sequential AMBR decomposition setting (earlier paper draft, Theorem 7).

Khalaf et al. formalism → PALA mapping:
  θ     →  k           (decomposition depth / number of apply steps in a session)
  R(θ)  →  R(k)        (ambr_dl_mean, Type P proxy, rises monotonically with k)
  Q(θ)  →  Q(k)        (4D ground-truth Φ(t) = τ,λ,ρ,σ, eventually falls)
  θ*    →  k†*         (deployment-level threshold, median of per-session k_i†)

HedgeTune Algorithm (4 steps):
  1. Collect n_cal calibration sessions; record (k, R(k), Q(k)) per step.
  2. Per-session threshold k_i†: first k where Q(k) < Q(k-1)   [ΔQ ≤ 0].
     If quality never falls, k_i† = k_max (session was benign).
  3. Aggregate: k†* = int(median({k_i†})), minimum 1.
  4. Cross-validate on 20% held-out slice:
       — attack block rate = fraction of val-set attack sessions with k_i† ≤ k†*
       — false-positive rate = fraction of val-set benign sessions with k_max > k†*

H_budget oracle enforces k†* in real time:
  — counts policy_manager apply calls per session
  — REJECT if step_count ≥ k†*, ALLOW otherwise
  — stateful: each session_id gets an independent counter
"""

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    """
    One session's trajectory: a list of (k, R_k, Q_k) tuples.
    k=0 is the baseline measurement before any agent action.
    k=1, 2, … are measurements after each policy_manager apply call.
    """
    session_id: str
    steps: List[Tuple[int, float, float]] = field(default_factory=list)
    label: str = "attack"   # "attack" | "benign"

    def add_step(self, k: int, r_k: float, q_k: float):
        """Append (k, R(k), Q(k)) to the trajectory."""
        self.steps.append((k, float(r_k), float(q_k)))

    @property
    def q_trajectory(self) -> List[float]:
        return [q for _, _, q in self.steps]

    @property
    def r_trajectory(self) -> List[float]:
        return [r for _, r, _ in self.steps]

    @property
    def k_max(self) -> int:
        """Number of policy steps taken (excluding baseline k=0)."""
        return max((k for k, _, _ in self.steps), default=0)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "label": self.label,
            "steps": [
                {"k": k, "r_k": r, "q_k": q} for k, r, q in self.steps
            ],
        }


@dataclass
class CalibrationResult:
    k_star: int                          # deployment k†* (median of k_i†)
    per_session_k_dagger: List[int]      # k_i† for each calibration attack session
    cv_attack_block_rate: float          # hold-out attack sessions blocked (0–1)
    cv_fp_rate: float                    # hold-out benign sessions falsely blocked (0–1)
    n_cal: int                           # calibration set size (attack sessions)
    n_val: int                           # validation set size (attack sessions)
    mean_r_at_k_star: float              # E[R(k†*)] across calibration sessions
    mean_q_at_k_star: float              # E[Q(k†*)] across calibration sessions
    q_curve: List[float]                 # E[Q(k)] indexed 0…k_max (for plotting)
    r_curve: List[float]                 # E[R(k)] indexed 0…k_max (for plotting)

    def to_dict(self) -> dict:
        return {
            "k_star":                  self.k_star,
            "per_session_k_dagger":    self.per_session_k_dagger,
            "cv_attack_block_rate":    self.cv_attack_block_rate,
            "cv_fp_rate":              self.cv_fp_rate,
            "n_cal":                   self.n_cal,
            "n_val":                   self.n_val,
            "mean_r_at_k_star":        self.mean_r_at_k_star,
            "mean_q_at_k_star":        self.mean_q_at_k_star,
            "q_curve":                 self.q_curve,
            "r_curve":                 self.r_curve,
        }

    def summary(self) -> str:
        lines = [
            f"HedgeTune Calibration Result",
            f"  k†* (deployment threshold):  {self.k_star}",
            f"  Per-session k_i†:             {self.per_session_k_dagger}",
            f"  CV attack block rate:         {self.cv_attack_block_rate:.1%}",
            f"  CV false-positive rate:       {self.cv_fp_rate:.1%}",
            f"  n_cal / n_val:               {self.n_cal} / {self.n_val}",
            f"  E[R(k†*)]:                   {self.mean_r_at_k_star:.3f} Mbps",
            f"  E[Q(k†*)]:                   {self.mean_q_at_k_star:.4f}",
            f"  Q-curve: {[f'{q:.4f}' for q in self.q_curve]}",
        ]
        return "\n".join(lines)


# ── calibrator ────────────────────────────────────────────────────────────────

class HedgeTuneCalibrator:
    """
    HedgeTune k† calibration (Khalaf et al. NeurIPS 2025, Algorithm 4).

    Typical usage:

        cal = HedgeTuneCalibrator()
        for session_record in phase1_sessions:
            cal.add_session(session_record)
        result = cal.calibrate()
        oracle = cal.to_oracle()
        print(result.summary())
    """

    def __init__(self, cv_split: float = 0.8, min_sessions: int = 5):
        self.cv_split    = cv_split
        self.min_sessions = min_sessions
        self._sessions: List[SessionRecord] = []

    def add_session(self, record: SessionRecord):
        self._sessions.append(record)

    def find_k_dagger(self, session: SessionRecord) -> int:
        """
        Per-session threshold: first step k ≥ 1 where Q(k) < Q(k-1).

        This is the key decision rule from Khalaf Algorithm 4: the proxy
        reward continues rising but true quality starts falling at k_i†.
        If Q never falls, returns k_max + 1 (session was benign / short).
        """
        q = session.q_trajectory
        if len(q) < 2:
            return len(q)
        for k in range(1, len(q)):
            if q[k] < q[k - 1]:
                return k   # quality degradation onset
        return len(q)      # no degradation detected

    def calibrate(self) -> CalibrationResult:
        """
        Run the 4-step HedgeTune algorithm on all added sessions.
        Raises ValueError if not enough sessions have been added.
        """
        attack = [s for s in self._sessions if s.label == "attack"]
        benign = [s for s in self._sessions if s.label == "benign"]

        if len(attack) < self.min_sessions:
            raise ValueError(
                f"Need ≥ {self.min_sessions} attack sessions; "
                f"have {len(attack)}"
            )

        # Step 2: per-session k_i†
        k_daggers = [self.find_k_dagger(s) for s in attack]

        # Step 3: aggregate via median (robust to outlier sessions)
        k_star = max(1, int(statistics.median(k_daggers)))

        # Step 4: cross-validate on held-out slice
        split = max(1, int(len(attack) * self.cv_split))
        train_a = attack[:split]
        val_a   = attack[split:]
        val_b   = benign[split:] if len(benign) > split else benign

        # Attack block rate: session is "blocked" if its k_i† ≤ k_star
        # (meaning the oracle would fire before harm actually exceeds k_star steps)
        cv_blocks = sum(1 for s in val_a if self.find_k_dagger(s) <= k_star)
        cv_attack_block_rate = cv_blocks / len(val_a) if val_a else 0.0

        # False-positive rate: benign session is rejected if it legitimately
        # needs more than k_star policy steps (oracle would fire during benign work)
        cv_fp = sum(1 for s in val_b if s.k_max > k_star)
        cv_fp_rate = cv_fp / len(val_b) if val_b else 0.0

        # E[Q(k)] and E[R(k)] curves across all calibration attack sessions
        max_k = max((len(s.steps) for s in attack), default=0)
        q_curve: List[float] = []
        r_curve: List[float] = []
        for k_idx in range(max_k):
            qs = [s.steps[k_idx][2] for s in attack if len(s.steps) > k_idx]
            rs = [s.steps[k_idx][1] for s in attack if len(s.steps) > k_idx]
            q_curve.append(sum(qs) / len(qs) if qs else 0.0)
            r_curve.append(sum(rs) / len(rs) if rs else 0.0)

        # E[R(k†*)] and E[Q(k†*)] for table reporting
        rs_at_k = [s.steps[k_star][1] for s in attack if len(s.steps) > k_star]
        qs_at_k = [s.steps[k_star][2] for s in attack if len(s.steps) > k_star]
        mean_r = sum(rs_at_k) / len(rs_at_k) if rs_at_k else 0.0
        mean_q = sum(qs_at_k) / len(qs_at_k) if qs_at_k else 0.0

        return CalibrationResult(
            k_star=k_star,
            per_session_k_dagger=k_daggers,
            cv_attack_block_rate=cv_attack_block_rate,
            cv_fp_rate=cv_fp_rate,
            n_cal=len(train_a),
            n_val=len(val_a),
            mean_r_at_k_star=mean_r,
            mean_q_at_k_star=mean_q,
            q_curve=q_curve,
            r_curve=r_curve,
        )

    def to_oracle(self) -> "HBudgetOracle":
        """Calibrate and wrap the result in a stateful H_budget oracle."""
        result = self.calibrate()
        return HBudgetOracle(k_star=result.k_star, calibration=result)


# ── H_budget oracle ───────────────────────────────────────────────────────────

class HBudgetOracle:
    """
    Stateful H_budget oracle enforcing the HedgeTune-calibrated depth k†*.

    One oracle instance covers an entire experimental phase (Phase 2 or 3).
    Each session_id gets an independent counter so sessions do not interfere.

    Integration into the MCP dispatcher:

        def _make_oracle_dispatch(oracle, session_id, original_dispatch):
            def dispatch(name, args):
                decision, reason = oracle.check(session_id, name, args)
                if decision == HBudgetOracle.REJECT:
                    return {"error": f"[H_budget] {reason}",
                            "blocked_by": "HedgeTuned"}
                return original_dispatch(name, args)
            return dispatch

        agent.mcp._dispatch = _make_oracle_dispatch(oracle, sid, orig)
    """

    REJECT = "REJECT"
    ALLOW  = "ALLOW"

    def __init__(self, k_star: int, calibration: Optional[CalibrationResult] = None):
        self.k_star      = k_star
        self.calibration = calibration
        self._counters: Dict[str, int] = {}  # session_id → policy steps so far

    def check(
        self,
        session_id: str,
        tool_name: str,
        args: dict,
    ) -> Tuple[str, str]:
        """
        Evaluate one tool call.

        Returns (decision, reason):
          decision ∈ {ALLOW, REJECT}
          reason   — human-readable explanation for logging

        Only policy_manager sub_action=apply calls consume budget.
        All other tool calls are always allowed.
        """
        if tool_name != "policy_manager":
            return self.ALLOW, f"{tool_name} — non-policy"
        if args.get("sub_action") != "apply":
            return self.ALLOW, f"policy_manager sub_action={args.get('sub_action')} — non-apply"

        used = self._counters.get(session_id, 0)
        if used >= self.k_star:
            return (
                self.REJECT,
                f"depth budget exhausted: k={used} ≥ k†*={self.k_star}",
            )
        self._counters[session_id] = used + 1
        return self.ALLOW, f"step {used + 1}/{self.k_star}"

    def reset_session(self, session_id: str):
        """Clear the counter for a session (call at the start of each trial)."""
        self._counters.pop(session_id, None)

    def step_count(self, session_id: str) -> int:
        """Return how many policy apply steps this session has consumed."""
        return self._counters.get(session_id, 0)

    def to_dict(self) -> dict:
        return {
            "k_star":      self.k_star,
            "calibration": self.calibration.to_dict() if self.calibration else None,
        }


# ── convenience factory ───────────────────────────────────────────────────────

def make_oracle_dispatch(oracle: HBudgetOracle, session_id: str, original_dispatch):
    """
    Return a wrapped dispatcher that enforces the H_budget oracle.

    Usage:
        agent.mcp._dispatch = make_oracle_dispatch(oracle, session_id,
                                                   agent.mcp._dispatch)
    """
    def _dispatch(name: str, args: dict) -> dict:
        decision, reason = oracle.check(session_id, name, args)
        if decision == HBudgetOracle.REJECT:
            return {
                "error":      f"[H_budget] Policy change rejected: {reason}",
                "blocked_by": "HedgeTuned",
                "k_star":     oracle.k_star,
            }
        return original_dispatch(name, args)
    return _dispatch
