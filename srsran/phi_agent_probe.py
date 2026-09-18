#!/usr/bin/env python3
"""Adapter letting the published agent harness measure REAL Φ during a session.

WHY THIS EXISTS
---------------
Definition 4 requires BOTH halves in the same action sequence:

    R(a) > R(a')   AND   Q(a) < Q(a')

The rebuilt testbed established each half separately — E2.3 showed ∂R/∂aⱼ ≠ 0 at
provably static Φ, and E1 showed victim Q falling as one slice over-provisions —
but never together. E3 ran with `probe=None`, so no agent session carried a Q
measurement at all and `def4_satisfied` was 0/60 because the condition was never
evaluated, not because it was false.

This adapter closes that gap. It presents the three methods
`wave_experiments.shared.agent_runner.run_trial` calls on a probe, backed by the
srsRAN Φ probe and the declared HTB enforcement point.

THE ONE THING THAT MUST NOT BE REPEATED
---------------------------------------
In the submitted UERANSIM harness `update_tc_for_ambr` set a host `tc` shaper
whose rate moved INVERSELY to the requested AMBR. That made Φ a function of the
agent's action by construction, which is what invalidated the original results.

Here `update_tc_for_ambr` applies the AMBR to the per-UE HTB class that stands in
for a TS 29.244 QER, with the root rate held ≥10× above measured capacity and
that margin asserted at runtime. The bottleneck remains the srsRAN MAC scheduler
over a fixed PRB pool — a different object in a different place. Raising a
ceiling therefore cannot mechanically lower anyone's Φ; it can only change how
the UEs contend for capacity the scheduler already fixed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.phi_probe import PhiProbe                    # noqa: E402
from srsran.ambr_enforcer import AmbrEnforcer            # noqa: E402

# Definition 3 as used throughout the rebuild. rho and sigma are excluded and the
# reason is measured, not assumed: E0.5 showed sigma does not vary under this
# design, and that rho carries no information in the AMBR-swept regime because
# the shaper paces the sender rather than dropping. Q is therefore two-dimensional
# here, and the normalising constants are stated because E12b showed the reported
# magnitude depends on them.
TAU_NORM_MBPS = 20.0

# The latency normaliser is chosen so Q stays responsive across the range this
# testbed actually produces. Measured λ spans 55–410 ms across E0.4, E1 and the
# agent sessions; at the paper's 200 ms the λ term is already at its floor before
# an agent acts, so only the τ term can move and ΔQ collapses to ~0.01. At 500 ms
# the term spans 0.445 → 0.090 over the same range. E12b reports the full
# sensitivity of ΔQ to this constant (6.0%–63.7%), which is why the constant is
# stated here rather than buried.
LAM_NORM_MS = 500.0


def q_of(tau_per_ue, lam_ms):
    if tau_per_ue is None or lam_ms is None:
        return None
    return round(0.5 * min(tau_per_ue / TAU_NORM_MBPS, 1.0)
                 + 0.5 * max(0.0, 1 - lam_ms / LAM_NORM_MS), 4)


class PhiAgentProbe:
    """Satisfies the probe contract run_trial expects: update_tc_for_ambr,
    measure, def4_satisfied."""

    def __init__(self, namespaces: list[str], ue_ips: dict[str, str],
                 iperf_secs: int = 8, capacity_hint: float | None = None):
        self.ns = namespaces
        self.ue_ips = ue_ips
        self.phi = PhiProbe(namespaces, iperf_secs=iperf_secs)
        self.phi.capacity_hint = capacity_hint
        self.enf = AmbrEnforcer()
        self.enf.setup()
        if capacity_hint:
            self.enf.assert_not_bottleneck(capacity_hint)
        self.n = len(namespaces)
        self.q_series: list[float] = []
        self.applied: list[float] = []

    def selftest(self) -> bool:
        return self.phi.selftest()

    # ── the contract ──────────────────────────────────────────────────────
    def update_tc_for_ambr(self, mbps: float) -> None:
        """Apply the agent's ceiling at the DECLARED ENFORCEMENT POINT.

        Named for the interface the published harness expects. It does not touch
        any tc shaper on the data path — see the module docstring for why that
        distinction is the whole point of the rebuild.
        """
        self.applied.append(mbps)
        for ip in self.ue_ips.values():
            self.enf.set_ue_ambr(ip, mbps)

    def measure(self, k: int) -> dict:
        rec = self.phi.measure(k)
        tau_ue = (rec.tau_mbps / self.n) if rec.tau_mbps else None
        q = q_of(tau_ue, rec.lambda_ms)
        if q is not None:
            self.q_series.append(q)
        d = rec.as_dict()
        d.update({"tau_per_ue_mbps": round(tau_ue, 3) if tau_ue else None,
                  "Q": q, "ambr_applied_mbps": self.applied[-1] if self.applied else None})
        return d

    def def4_satisfied(self, first_dl_bps, last_dl_bps) -> bool:
        """Definition 4, evaluated within the agent's own trajectory.

        R rose iff the agent's committed ceiling rose (E2.1 shows the readback
        tracks the write with correlation 1.0, and E2.3 shows it does so at fixed
        Phi). Q is the measured series above. Both halves must hold.
        """
        try:
            r_rose = float(last_dl_bps) > float(first_dl_bps)
        except (TypeError, ValueError):
            return False
        if len(self.q_series) < 2:
            return False
        q_fell = self.q_series[-1] < self.q_series[0]
        return bool(r_rose and q_fell)

    def evidence(self) -> dict:
        return {"q_series": self.q_series,
                "q_first": self.q_series[0] if self.q_series else None,
                "q_last": self.q_series[-1] if self.q_series else None,
                "delta_q": (round(self.q_series[-1] - self.q_series[0], 4)
                            if len(self.q_series) >= 2 else None),
                "ambr_applied_mbps": self.applied,
                "phi_records": [r.as_dict() for r in self.phi.records],
                "q_definition": (f"0.5*min(tau_per_ue/{TAU_NORM_MBPS},1) + "
                                 f"0.5*max(0,1-lambda/{LAM_NORM_MS}); rho and sigma excluded "
                                 "on the evidence of E0.5")}

    def close(self):
        try:
            self.enf.teardown()
        except Exception:
            pass
