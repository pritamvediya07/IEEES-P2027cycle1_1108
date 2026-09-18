"""Session-level HedgeTune calibration (paper §V-C, Theorem 7).

Adapts Khalaf et al.'s inference-time HedgeTune to multi-step tool invocation.
Operates on (R(k), Q(k)) trajectory pairs collected on a vulnerable PALA deployment.

Usage:
    ht = SessionHedgeTune()
    for session in calibration_sessions:
        ht.add_session(session_id, rq_pairs)   # [(k, R_k, Q_k), ...]
    k_star, stats = ht.calibrate()
    ht.save(path)
"""
import json
import statistics
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class SessionRecord:
    session_id: str
    label: str = "attack"          # "attack" | "benign"
    steps: list[tuple] = field(default_factory=list)   # [(k, R_k, Q_k)]

    def add_step(self, k: int, r_k: float, q_k: float) -> None:
        self.steps.append((k, float(r_k), float(q_k)))

    def find_k_dagger(self) -> int | None:
        """k_i† = first step k where Q(k) < Q(k-1) (quality starts falling).

        Matches Khalaf et al. Algorithm 4: returns the step number of the
        FIRST degradation onset, not the last-good step.  Strict < is used
        so that a flat Q (no change) is NOT counted as degradation.
        Returns None if quality never falls (benign / all-increasing session).
        """
        for i in range(1, len(self.steps)):
            _, _, q_prev = self.steps[i - 1]
            k_curr, _, q_curr = self.steps[i]
            if q_curr < q_prev:          # strict drop only
                return k_curr            # first BAD step (degradation onset)
        return None  # quality monotonically non-decreasing — benign

    def q_drop_at_termination(self, k_star: int) -> float:
        """ΔQ when session is halted at k†* (used in Exp 6 Phase 2/3)."""
        if not self.steps:
            return 0.0
        q0 = self.steps[0][2]
        # Find Q at k = k_star (or last step if k_star > len)
        for k, _, q_k in reversed(self.steps):
            if k <= k_star:
                return (q0 - q_k) / max(q0, 1e-9)
        return 0.0


class SessionHedgeTune:
    """Calibrates k†* from a set of attack session trajectories."""

    def __init__(self):
        self._sessions: list[SessionRecord] = []

    def add_session(self, session: SessionRecord) -> None:
        self._sessions.append(session)

    # ── calibration ───────────────────────────────────────────────────────────
    def calibrate(self) -> tuple[int, dict]:
        """Compute k†* = median(k_i†) over attack sessions.

        Returns:
            k_star   – integer threshold
            stats    – dict with CV, CI, per-session k_i† values
        """
        attack_sessions = [s for s in self._sessions if s.label == "attack"]
        if not attack_sessions:
            raise RuntimeError("No attack sessions available for calibration.")

        k_daggers = []
        skipped = 0
        for s in attack_sessions:
            if len(s.steps) < 2:
                # Only baseline recorded — no in-session Q measurements; skip
                skipped += 1
                continue
            kd = s.find_k_dagger()
            if kd is not None:
                k_daggers.append(kd)
            else:
                # Quality never fell — use max step as upper bound
                max_k = max(t[0] for t in s.steps) if s.steps else 1
                k_daggers.append(max_k)
        if skipped:
            print(f"[HedgeTune] Skipped {skipped}/{len(attack_sessions)} sessions "
                  f"with <2 steps (no in-session measurements).")

        k_star = max(1, int(statistics.median(k_daggers)))  # minimum 1 (k†*=0 is degenerate)
        mean_kd = statistics.mean(k_daggers)
        std_kd  = statistics.stdev(k_daggers) if len(k_daggers) > 1 else 0.0
        cv      = std_kd / mean_kd if mean_kd > 0 else float("inf")

        # 95 % CI (normal approximation)
        n = len(k_daggers)
        se = std_kd / (n ** 0.5) if n > 1 else 0.0
        ci_lo = mean_kd - 1.96 * se
        ci_hi = mean_kd + 1.96 * se

        stats = {
            "n_sessions": n,
            "k_star": k_star,
            "mean_k_dagger": round(mean_kd, 3),
            "std_k_dagger":  round(std_kd, 3),
            "cv":            round(cv, 3),
            "ci_95_lo":      round(ci_lo, 3),
            "ci_95_hi":      round(ci_hi, 3),
            "k_daggers":     k_daggers,
            "cv_stable":     cv <= 0.50,
        }
        return k_star, stats

    # ── cross-validation ──────────────────────────────────────────────────────
    def cross_validate(self, k_star: int, held_out: list[SessionRecord],
                       tolerance: int = 1) -> dict:
        """Check if k†* identifies harm-onset within ±tolerance steps on held-out sessions."""
        hits = 0
        for s in held_out:
            kd = s.find_k_dagger()
            if kd is not None and abs(kd - k_star) <= tolerance:
                hits += 1
        return {
            "n_held_out": len(held_out),
            "hits_within_tolerance": hits,
            "accuracy": hits / len(held_out) if held_out else 0.0,
            "tolerance_steps": tolerance,
        }

    # ── benign acceptance evaluation ──────────────────────────────────────────
    def benign_acceptance_rate(self, k_star: int) -> float:
        """Fraction of benign sessions that are NOT rejected by k†*."""
        benign = [s for s in self._sessions if s.label == "benign"]
        if not benign:
            return 1.0
        accepted = sum(
            1 for s in benign
            if (max(t[0] for t in s.steps) if s.steps else 0) <= k_star
        )
        return accepted / len(benign)

    # ── persistence ───────────────────────────────────────────────────────────
    def save(self, path: Path, k_star: int, stats: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"k_star": k_star, **stats}
        path.write_text(json.dumps(payload, indent=2))
        print(f"[HedgeTune] k†* = {k_star} saved → {path}")

    @staticmethod
    def load_kstar(path: Path, default: int = 3) -> int:
        if path.exists():
            return int(json.loads(path.read_text())["k_star"])
        return default
