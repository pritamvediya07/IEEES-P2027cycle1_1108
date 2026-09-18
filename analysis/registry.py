#!/usr/bin/env python3
"""E11 — The number registry  (artifact: paper-number consistency).

WHY THIS IS SOFTWARE AND NOT A SPREADSHEET
------------------------------------------
The Table 2 / Table 11 class of error in the original submission happened
because numbers were typed into LaTeX by hand, and because a baseline reference
was silently swapped between two quantities with the same name. Neither is a
carelessness problem that more care fixes. They are both consequences of a
number existing in more than one place.

The rule this module enforces is that every number appearing in the paper is
produced by exactly one function here, from raw traces, and is written to
paper_numbers.json with:

    * a unique key
    * the raw file it was computed from
    * n, and any exclusions applied
    * the NAMED baseline it is relative to, if it is a relative quantity
    * units

Baseline references are named keys, never positional. Q0_preaction and
Q0_postfirstcall are different keys and cannot be confused, which is the
specific failure that produced the Table 11 discrepancy.

    .venv/bin/python analysis/registry.py          # regenerate paper_numbers.json
    .venv/bin/python analysis/verify_paper.py      # recompute and diff; exit 1 on mismatch
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "srsran" / "results"
OUT = ROOT / "analysis" / "paper_numbers.json"

_REG: dict[str, dict] = {}


def number(key: str, *, value, units: str, source: str, n=None,
           exclusions: str = "none", baseline_key: str | None = None,
           note: str = "", robust: bool = True):
    """Record one paper number with its full provenance."""
    if key in _REG:
        raise KeyError(f"duplicate registry key {key!r} — every number has exactly one home")
    _REG[key] = {"value": value, "units": units, "source": source, "n": n,
                 "exclusions": exclusions, "baseline_key": baseline_key,
                 "note": note, "robust_to_analysis_choices": robust}
    return value


def _load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def build() -> dict:
    _REG.clear()

    # ── E0.3 capacity ─────────────────────────────────────────────────────
    if (d := _load("E0_3_capacity.json")):
        number("C_cell_capacity_mbps", value=d["C_mbps"], units="Mbps",
               source="srsran/results/E0_3_capacity.json:C_mbps", n=d["n_ue"],
               note="aggregate downlink with every AMBR unlimited; this is the bottleneck, "
                    "measured at the MAC scheduler and NOT set by the enforcement point")
        number("C_fair_share_mbps", value=d["fair_share_mbps"], units="Mbps",
               source="srsran/results/E0_3_capacity.json:fair_share_mbps", n=d["n_ue"],
               baseline_key="C_cell_capacity_mbps", note="C divided by n")

    # ── E0.4 two-regime ───────────────────────────────────────────────────
    if (d := _load("E0_4_two_regime.json")):
        rows = d["rows"]
        number("E0_4_knee_mbps_per_ue", value=d["knee_mbps_per_ue"], units="Mbps/UE",
               source="srsran/results/E0_4_two_regime.json:knee_mbps_per_ue", n=d["n_ue"],
               baseline_key="C_cell_capacity_mbps")
        under = [r for r in rows if r["regime"] == "under" and r.get("lambda_ms")]
        over = [r for r in rows if r["regime"] == "over" and r.get("lambda_ms")]
        if under and over:
            number("E0_4_lambda_min_under_ms", value=min(r["lambda_ms"] for r in under),
                   units="ms", source="srsran/results/E0_4_two_regime.json:rows[regime=under]",
                   n=len(under))
            number("E0_4_lambda_max_over_ms", value=max(r["lambda_ms"] for r in over),
                   units="ms", source="srsran/results/E0_4_two_regime.json:rows[regime=over]",
                   n=len(over))
            lo = min(r["lambda_ms"] for r in under)
            hi = max(r["lambda_ms"] for r in over)
            number("E0_4_lambda_inflation_factor", value=round(hi / lo, 2), units="x",
                   source="derived from E0_4_lambda_min_under_ms and E0_4_lambda_max_over_ms",
                   baseline_key="E0_4_lambda_min_under_ms",
                   note="bufferbloat signature: latency inflates while throughput saturates")

    # ── E0.5 rho and sigma ────────────────────────────────────────────────
    if (d := _load("E0_5_analysis.json")):
        a = d["arms"]["am"]; u = d["arms"]["um"]
        number("E0_5_rho_iperf_am_pct", value=a["iperf_loss_mean_pct"], units="%",
               source="srsran/results/E0_5_analysis.json:arms.am.iperf_loss_mean_pct",
               n=len(a["per_ue"]), note="iperf3 UDP reverse accounting; UNDER-REPORTS, see counters")
        number("E0_5_rho_counter_am_pct", value=a["counter_loss_mean_pct"], units="%",
               source="srsran/results/E0_5_analysis.json:arms.am.counter_loss_mean_pct",
               n=len(a["per_ue"]),
               note="offered vs /proc/net/dev tun_srsue rx; this is the trustworthy measure")
        number("E0_5_rho_counter_um_pct", value=u["counter_loss_mean_pct"], units="%",
               source="srsran/results/E0_5_analysis.json:arms.um.counter_loss_mean_pct",
               n=len(u["per_ue"]))
        number("E0_5_am_vs_um_gap_pp", value=d["comparison"]["AM_vs_UM_difference_pp"],
               units="percentage points",
               source="srsran/results/E0_5_analysis.json:comparison.AM_vs_UM_difference_pp",
               baseline_key="E0_5_rho_iperf_am_pct",
               note="RLC-AM hypothesis REJECTED: acknowledged mode does not hide the loss")

    # ── E1 asymmetric harm — THE LOAD-BEARING NUMBERS ─────────────────────
    if (d := _load("E1_harm_mechanism.json")):
        rows = [r for r in d["rows"] if r.get("tau_victim_mean") and r.get("lambda_ms")]
        first, last = rows[0], rows[-1]
        # Named baselines. These two keys are the ones that were silently swapped before.
        number("E1_Q0_preaction", value=first["Q_victim"], units="index",
               source="srsran/results/E1_harm_mechanism.json:rows[0].Q_victim",
               note="victim Q at the FIRST sweep point, i.e. aggressor still at baseline. "
                    "This is the pre-action baseline and is NOT interchangeable with "
                    "E1_Q0_postfirstcall.")
        if len(rows) > 1:
            number("E1_Q0_postfirstcall", value=rows[1]["Q_victim"], units="index",
                   source="srsran/results/E1_harm_mechanism.json:rows[1].Q_victim",
                   note="victim Q AFTER the first escalation. Distinct key by construction so it "
                        "can never be substituted for E1_Q0_preaction.")
        number("E1_victim_tau_first_mbps", value=first["tau_victim_mean"], units="Mbps",
               source="srsran/results/E1_harm_mechanism.json:rows[0].tau_victim_mean",
               n=len(d["victims"]))
        number("E1_victim_tau_last_mbps", value=last["tau_victim_mean"], units="Mbps",
               source="srsran/results/E1_harm_mechanism.json:rows[-1].tau_victim_mean",
               n=len(d["victims"]), baseline_key="E1_victim_tau_first_mbps",
               note="FLAT. The victims lose no bandwidth at all; this is the key mechanistic fact")
        number("E1_victim_lambda_first_ms", value=first["lambda_ms"], units="ms",
               source="srsran/results/E1_harm_mechanism.json:rows[0].lambda_ms")
        number("E1_victim_lambda_last_ms", value=last["lambda_ms"], units="ms",
               source="srsran/results/E1_harm_mechanism.json:rows[-1].lambda_ms",
               baseline_key="E1_victim_lambda_first_ms")
        number("E1_victim_lambda_inflation_x",
               value=round(last["lambda_ms"] / first["lambda_ms"], 2), units="x",
               source="derived from E1_victim_lambda_first_ms and E1_victim_lambda_last_ms",
               baseline_key="E1_victim_lambda_first_ms",
               note="PRIMARY harm evidence: a measured quantity with units, unlike the Q index")
        number("E1_aggressor_tau_last_mbps", value=last["tau_aggressor"], units="Mbps",
               source="srsran/results/E1_harm_mechanism.json:rows[-1].tau_aggressor", n=1)

    # ── E3 attribution (§6.3 Target versus feedback) ───────────────────────
    if (d := _load("E3_attribution.json")):
        import statistics as _st
        rows = [r for r in d.get("rows", []) if not r.get("error")]
        ds = [r["delta_star"] for r in rows if r.get("delta_star") is not None]
        nt = [r["b_final_mbps"] for r in rows
              if r.get("register") in ("sla", "null") and r.get("b_final_mbps")]
        at = [r["agent_attributable_writes"] for r in rows
              if r.get("agent_attributable_writes") is not None]
        if ds:
            number("E3_median_delta_star_with_target", value=round(_st.median(ds), 4),
                   units="fraction over target", n=len(ds),
                   source="srsran/results/E3_attribution.json:rows[delta_star]",
                   note="median overshoot where the operator STATED a target; 0.00 means the "
                        "agent stopped exactly at B*")
            number("E3_sessions_respecting_target", value=sum(1 for x in ds if x <= 0.01),
                   units="count", n=len(ds),
                   source="srsran/results/E3_attribution.json:rows[delta_star]")
        if at:
            number("E3_total_writes_after_kstar", value=sum(at), units="count", n=len(at),
                   source="srsran/results/E3_attribution.json:rows[agent_attributable_writes]",
                   note="writes issued AFTER the operator's target was reached — the only "
                        "portion of the policy state that is agent-attributable when a target exists")
        if nt:
            number("E3_no_target_mean_b_final_mbps", value=round(_st.mean(nt), 1), units="Mbps",
                   n=len(nt), baseline_key="E4_baseline_ambr_mbps",
                   source="srsran/results/E3_attribution.json:rows[register in sla,null]",
                   note="where the operator states NO target, every value is agent-selected "
                        "by construction")
            number("E3_no_target_at_tool_ceiling", value=sum(1 for x in nt if x >= 1000),
                   units="count", n=len(nt),
                   source="srsran/results/E3_attribution.json:rows[register in sla,null]",
                   note="sessions pinned at the policy tool's hard 1000 Mbps maximum")

    # ── E12b — the honesty constraint on the Q number ─────────────────────
    if (d := _load("E12b_q_sensitivity.json")):
        v = d["verdict"]
        number("E1_victim_Q_drop_pct_at_lamnorm_200", value=v["published_drop_pct"], units="%",
               source="srsran/results/E12b_q_sensitivity.json:verdict.published_drop_pct",
               baseline_key="E1_Q0_preaction", robust=False,
               note="NOT ROBUST. Ranges from "
                    f"{v['drop_pct_range_across_normalisers'][0]}% to "
                    f"{v['drop_pct_range_across_normalisers'][1]}% depending only on the lambda "
                    "normalising constant. Do not lead with this number; lead with "
                    "E1_victim_lambda_inflation_x, which has units.")
        number("E1_Q_lambda_term_share_pct", value=v["lambda_term_share_of_dQ_pct"], units="%",
               source="srsran/results/E12b_q_sensitivity.json:verdict.lambda_term_share_of_dQ_pct",
               note="the lambda term accounts for essentially all of the change in Q; the tau "
                    "term contributes ~0 because victim throughput is flat")

    # ── E2 contamination channel ──────────────────────────────────────────
    if (d := _load("E2_contamination.json")):
        s, i = d["arm_standard"], d["arm_isolated"]
        number("E2_contamination_rate_standard", value=s["true_contamination_rate"], units="fraction",
               source="srsran/results/E2_contamination.json:arm_standard.true_contamination_rate",
               n=len(s["rows"]))
        number("E2_contamination_rate_isolated", value=i["true_contamination_rate"], units="fraction",
               source="srsran/results/E2_contamination.json:arm_isolated.true_contamination_rate",
               n=len(i["rows"]),
               note="TRUE rate. The naive 'readback within 5% of the write' rule scores "
                    f"{sum(r['reappeared'] for r in i['rows'])}/{len(i['rows'])} here, but the "
                    "isolated readback is CONSTANT, so every apparent hit is a coincidence where "
                    "a swept write happened to equal the stale value.")
        number("E2_corr_standard", value=s["corr_write_readback"], units="pearson r",
               source="srsran/results/E2_contamination.json:arm_standard.corr_write_readback",
               n=len(s["rows"]), note="perfect tracking: the write reappears as the analytic")
        number("E2_corr_isolated", value=i["corr_write_readback"], units="pearson r",
               source="srsran/results/E2_contamination.json:arm_isolated.corr_write_readback",
               n=len(i["rows"]), note="zero: IsolatedCollector fully severs the channel")

    # ── E2.3 — the dedicated re-run, with Phi actually measured on both sides ──
    # The registry previously read `E2_contamination.json:E2_3_dR_at_fixed_phi`,
    # which is the FIRST attempt: the probe returned None for all four Phi
    # dimensions because no UE was attached, so Phi was absent rather than
    # static and the dR/da|_Phi claim was vacuous. That run was superseded by
    # `E2_3_dr_fixed_phi.json`, which runs on a live radio with a daemon guard
    # and records both arms. Reading the stale source left the artifact
    # asserting 90.0 Mbps with a VACUOUS warning while the response quoted the
    # valid 180.0 — a contradiction a reader would find immediately.
    if (d := _load("E2_3_dr_fixed_phi.json")):
        v = d.get("verdict") or {}
        if v.get("standard_mean_delta_R") is not None:
            number("E2_3_delta_R", value=v["standard_mean_delta_R"], units="Mbps",
                   source="srsran/results/E2_3_dr_fixed_phi.json:verdict.standard_mean_delta_R",
                   n=v.get("standard_n"), robust=False,
                   note="R moves by this much under the standard collector while Phi is "
                        "MEASURED and static within tolerance (tau 0.15 Mbps, lambda 0.25 ms, "
                        "rho 0.05 pp). Flagged not-robust on sample size only: n=2 per arm. "
                        "The contrast with the isolated arm, not the magnitude, is the result.")
        if v.get("isolated_mean_delta_R") is not None:
            number("E2_3_delta_R_isolated", value=v["isolated_mean_delta_R"], units="Mbps",
                   source="srsran/results/E2_3_dr_fixed_phi.json:verdict.isolated_mean_delta_R",
                   n=v.get("isolated_n"), robust=False,
                   note="The control arm. Same write, same static Phi, provenance filter on: "
                        "R does not move. Paired with E2_3_delta_R this is the dR/da|_Phi result.")
    # The superseded first attempt is kept addressable so the correction is
    # auditable rather than silent.
    if (d := _load("E2_contamination.json")):
        e23 = d.get("E2_3_dR_at_fixed_phi") or {}
        if e23.get("delta_R") is not None:
            number("E2_3_delta_R_SUPERSEDED", value=e23["delta_R"], units="Mbps",
                   source="srsran/results/E2_contamination.json:E2_3_dR_at_fixed_phi.delta_R",
                   n=1, robust=False,
                   note="SUPERSEDED, DO NOT QUOTE. Phi verification vacuous — the probe "
                        "returned None for all four dimensions (no UE attached), so Phi was "
                        "absent, not static. Retained only so the correction to "
                        "E2_3_delta_R is auditable.")

    # ── E5 generality across policy variables ─────────────────────────────
    if (d := _load("E5_multivariable.json")):
        cs = d["channel_standard"]
        tot = sum(v["exact_matches"] for v in cs.values())
        n_all = sum(v["n"] for v in cs.values())
        number("E5_channel_exact_matches", value=tot, units="count",
               source="srsran/results/E5_multivariable.json:channel_standard", n=n_all,
               note=f"{tot} of {n_all} exact write-to-readback matches across "
                    f"{len(cs)} policy variables under the standard collector")
        number("E5_variables_with_open_channel", value=sum(v["channel_open"] for v in cs.values()),
               units="count", source="srsran/results/E5_multivariable.json:channel_standard",
               n=len(cs))
        number("E5_variables_open_under_iso",
               value=sum(v["channel_open"] for v in d["channel_isolated"].values()),
               units="count", source="srsran/results/E5_multivariable.json:channel_isolated",
               n=len(d["channel_isolated"]),
               note="IsolatedCollector removes every one of the four analytics entirely")
        for k, v in cs.items():
            number(f"E5_corr_{k}", value=v["corr_write_readback"], units="pearson r",
                   source=f"srsran/results/E5_multivariable.json:channel_standard.{k}."
                          "corr_write_readback", n=v["n"])

    # ── E4 deterministic controller ───────────────────────────────────────
    if (d := _load("E4_scripted_controller.json")):
        for arm in ("open_loop", "closed_loop", "closed_loop_iso"):
            A = d["arms"][arm]
            number(f"E4_{arm}_overshoot_rate", value=A["overshoot_rate"], units="fraction",
                   source=f"srsran/results/E4_scripted_controller.json:arms.{arm}.overshoot_rate",
                   n=A["n"])
            number(f"E4_{arm}_mean_escalation_x", value=A["mean_escalation_factor"], units="x",
                   source=f"srsran/results/E4_scripted_controller.json:arms.{arm}."
                          "mean_escalation_factor",
                   n=A["n"], baseline_key="E4_baseline_ambr_mbps")
        number("E4_baseline_ambr_mbps", value=d["baseline_mbps"], units="Mbps",
               source="srsran/results/E4_scripted_controller.json:baseline_mbps")

    # ── E8 gate replay ────────────────────────────────────────────────────
    if (d := _load("E8_gate_replay.json")):
        v = d["verdict"]
        number("E8_gates_evaded", value=len(v["gates_evaded_under_some_attack"]), units="count",
               source="srsran/results/E8_gate_replay.json:verdict.gates_evaded_under_some_attack",
               n=v["gates_evaluated"],
               note="of " + str(v["gates_evaluated"]) + " natural designs: "
                    + ", ".join(v["gates_evaded_under_some_attack"]))
        number("E8_gates_holding", value=len(v["gates_holding_under_every_attack"]), units="count",
               source="srsran/results/E8_gate_replay.json:verdict."
                      "gates_holding_under_every_attack",
               n=v["gates_evaluated"])
        worst = max((r for r in d["results"] if r["gate"] == "decaying_memory"),
                    key=lambda r: r["max_ambr_reached_mbps"])
        number("E8_max_ambr_reached_worst_gate_mbps", value=worst["max_ambr_reached_mbps"],
               units="Mbps", source="srsran/results/E8_gate_replay.json:results[decaying_memory]",
               baseline_key="E4_baseline_ambr_mbps")

    # ── E10 overhead ──────────────────────────────────────────────────────
    if (d := _load("E10_overhead.json")):
        number("E10_worst_arm_delta_ms", value=d["verdict"]["worst_arm_delta_ms"], units="ms",
               source="srsran/results/E10_overhead.json:verdict.worst_arm_delta_ms",
               n=d["n_per_arm"], baseline_key="E10_arm_none_mean_ms", robust=False,
               note="AT OR BELOW THE MEASUREMENT FLOOR. Arm ordering is not self-consistent and "
                    "two arms show physically impossible negative deltas. Quote only as an upper "
                    "bound, never as a ranking.")
        number("E10_arm_none_mean_ms", value=d["arms"]["none"]["mean_ms"], units="ms",
               source="srsran/results/E10_overhead.json:arms.none.mean_ms", n=d["n_per_arm"])
        number("E10_mgmt_plane_interval_ms", value=d["mgmt_plane_interval_ms"], units="ms",
               source="srsran/results/E10_overhead.json:mgmt_plane_interval_ms",
               note="the correct denominator: this is management-plane, not user-plane, cost")

    # ── E12 QoE ───────────────────────────────────────────────────────────
    if (d := _load("E12_qoe_mapping.json")):
        dd = d["verdict"]["deltas_across_E1_victim_sweep"]
        number("E12_dMOS_streaming", value=dd["dMOS_streaming"], units="MOS",
               source="srsran/results/E12_qoe_mapping.json:verdict."
                      "deltas_across_E1_victim_sweep.dMOS_streaming",
               note="buffered streaming absorbs the harm almost entirely")
        number("E12_dMOS_conversational", value=dd["dMOS_conversational"], units="MOS",
               source="srsran/results/E12_qoe_mapping.json:verdict."
                      "deltas_across_E1_victim_sweep.dMOS_conversational",
               note="G.107 E-model; larger than streaming but still small, because one-way delay "
                    "stays below the 177.3 ms interactivity knee")

    _paper_quoted_numbers()
    return dict(_REG)


BASELINE_MBPS = 20.0     # per-UE AMBR baseline of every srsRAN LLM experiment (E4_baseline_ambr_mbps)


def _paper_q(tau_ue: float, lam_ms: float, rho_pct: float, sigma: float) -> float:
    """Q exactly as defined in the paper (Def. 3, footnote 1): equal weights, each component
    normalised to [0, 1] as tau/20, 1-lambda/200, 1-rho/100, sigma/10."""
    return 0.25 * (min(tau_ue / 20.0, 1.0) + max(0.0, 1 - lam_ms / 200.0)
                   + max(0.0, 1 - rho_pct / 100.0) + min(sigma / 10.0, 1.0))


def _paper_quoted_numbers() -> None:
    """Numbers the paper prints, in the form it prints them (counts, factors, shares), so
    every srsRAN figure in the text has exactly one registry entry."""
    import statistics as _st

    # ── E1 capacity used by §6.3 / App. E (E1's own measurement, not E0.3's) ──
    if (d := _load("E1_harm_mechanism.json")):
        number("E1_cell_capacity_mbps", value=d["C_mbps"], units="Mbps", n=d["n_ue"],
               source="srsran/results/E1_harm_mechanism.json:C_mbps",
               note="paper §6.3 / App. E: 22.8 Mbps. Measured at the start of the E1 campaign; "
                    "E0.3 measured 23.38 Mbps on a separate run (C_cell_capacity_mbps)")
        number("E1_per_ue_baseline_mbps", value=d["baseline_mbps"], units="Mbps/UE", n=d["n_ue"],
               source="srsran/results/E1_harm_mechanism.json:baseline_mbps",
               baseline_key="E1_cell_capacity_mbps", note="paper App. E: 5.71 Mbps")
        # The original 71%/29% derivation (§6.3 Target versus feedback): share of the victim's Q loss
        # across the E1 ceiling sweep already realised at 3x baseline (the published intent's
        # 20 -> 60 Mbps ratio), against the worst point of the sweep. A property of the Phi
        # response measured without an agent; the agent-side answer is E3.
        q = {r["ratio_to_baseline"]: r["Q_victim"] for r in d["rows"] if r.get("Q_victim") is not None}
        q0, q_worst = q[1.0], min(q.values())
        number("E1_share_of_victim_dQ_at_3x_pct", value=round(100 * (q0 - q[3.0]) / (q0 - q_worst), 1),
               units="%", n=len(q), baseline_key="E1_Q0_preaction",
               source="srsran/results/E1_harm_mechanism.json:rows[ratio_to_baseline 1, 3, worst].Q_victim",
               note="§6.3 Target versus feedback: derivation of the 71%/29% split (71.1% / 28.9%). The "
                    "paper prints 'at least 71%' for UERANSIM; reproduce_results.py computes the "
                    "UERANSIM value (71.4%) from the testbed's shaper model")

    # ── §6.3 Target versus feedback: share of the Q degradation realised at B* ──
    if (d := _load("E0_4_two_regime.json")):
        rows = sorted(d["rows"], key=lambda r: r["B_mbps_per_ue"])
        n_ue = d["n_ue"]
        pts = [(r["B_mbps_per_ue"],
                _paper_q(r["tau_mbps"] / n_ue, r["lambda_ms"], r["rho_pct"], r["sigma"]))
               for r in rows]

        def q_at(b):
            for (a, p), (c, q) in zip(pts, pts[1:]):
                if a <= b <= c:
                    return p + (q - p) * (b - a) / (c - a)
            raise ValueError(f"B={b} outside the E0.4 sweep")

        q_worst = min(q for _, q in pts)
        shares = {}
        for name, base in (("E1 per-UE baseline 5.71", 5.71),
                           (f"E0.4 knee {d['knee_mbps_per_ue']}", d["knee_mbps_per_ue"])):
            q0, qs = q_at(base), q_at(3 * base)     # B* = 3x baseline, as 20 -> 60 Mbps in UERANSIM
            shares[name] = 100 * (q0 - qs) / (q0 - q_worst)
        share = round(min(shares.values()), 1)
        number("E0_4_target_share_of_dQ_pct", value=share, units="%", n=len(pts),
               source="srsran/results/E0_4_two_regime.json:rows (paper Q, components clipped to [0,1])",
               baseline_key="E0_4_knee_mbps_per_ue",
               note="paper §6.3: 'over 91%'. Share of the total Q degradation already realised when "
                    "the ceiling reaches B* = 3x baseline; minimum over the two measured baselines ("
                    + ", ".join(f"{k}: {v:.1f}%" for k, v in shares.items()) + ")")
        number("E0_4_escalation_share_of_dQ_pct", value=round(100 - share, 1), units="%",
               source="derived from E0_4_target_share_of_dQ_pct",
               baseline_key="E0_4_target_share_of_dQ_pct", note="paper §6.3: 'under 9%'")

    # ── E6 capability sweep (§6.2, App. F) ──────────────────────────────────
    if (d := _load("E6_capability_sweep.json")):
        for tier, key in (("7-8B", "llama8b"), ("12-15B", "gemma12b"), ("Frontier API", "sonnet45")):
            if tier not in d["per_tier"]:          # e.g. frontier tier skipped without an API key
                continue
            t = d["per_tier"][tier]
            number(f"E6_{key}_closed_sessions", value=round(t["circuit_closure"] * t["n_ok"]),
                   units="count", n=t["n_ok"],
                   source="srsran/results/E6_capability_sweep.json:per_tier." + tier,
                   note=f"{t['model']}; paper: 14/20 (8B), 15/20 (12B), 15/20 (Sonnet 4.5)")
            number(f"E6_{key}_mean_delta_star", value=round(t["mean_delta_star"], 2),
                   units="fraction over target", n=t["n_with_target"],
                   source="srsran/results/E6_capability_sweep.json:per_tier." + tier,
                   note="paper App. F: +3.41, +2.48, -0.12")
        t = d["per_tier"].get("30-36B")
        if t: number("E6_partial_30_36b_closed_sessions", value=round(t["circuit_closure"] * t["n_ok"]),
               units="count", n=t["n_ok"], robust=False,
               source="srsran/results/E6_capability_sweep.json:per_tier.30-36B",
               note="PARTIAL tier (6 of 20 planned sessions). The paper prints 6/6 and does not "
                    "quote it as a rate")

    # ── E3 target-free sessions (§6.2, App. F) ──────────────────────────────
    if (d := _load("E3_attribution.json")):
        rows = [r for r in d["rows"] if not r.get("error")]
        tf = [r for r in rows if r["register"] in ("sla", "null")]
        und = [r for r in tf if r["arm"] == "V"]
        pooled = [r for r in tf if r.get("b_final_mbps")]
        src = "srsran/results/E3_attribution.json:rows"
        number("E3_target_free_undefended_mean_x",
               value=round(_st.mean(r["b_final_mbps"] for r in und) / BASELINE_MBPS, 1),
               units="x baseline", n=len(und), baseline_key="E4_baseline_ambr_mbps", source=src,
               note="paper: 17x. Target-free = the SLA-framed and null-control intents, "
                    "undefended arm; neither states a number")
        number("E3_target_free_undefended_at_ceiling",
               value=sum(r["b_final_mbps"] >= 1000 for r in und), units="count", n=len(und),
               source=src, note="paper: 1/10")
        number("E3_target_free_undefended_contaminated",
               value=sum(bool(r["stage_B_contaminated"]) for r in und), units="count", n=len(und),
               source=src, note="paper: 9/10 obtain a contaminated readback")
        number("E3_target_free_undefended_write_after_readback",
               value=sum(bool(r["stage_D_escalated_on_readback"]) for r in und), units="count",
               n=len(und), source=src, note="paper: 6/10 issue a further write after it")
        number("E3_target_free_pooled_mean_x",
               value=round(_st.mean(r["b_final_mbps"] for r in pooled) / BASELINE_MBPS, 1),
               units="x baseline", n=len(pooled), baseline_key="E4_baseline_ambr_mbps", source=src,
               note="paper: 29x, pooled across the four defense arms; descriptive only")
        number("E3_target_free_pooled_n", value=len(pooled), units="count", source=src,
               note="paper: n=33 of 40 sessions record a final ceiling")

    # ── E8 gate replay (§6.4) ───────────────────────────────────────────────
    if (d := _load("E8_gate_replay.json")):
        res = d["results"]
        base = d["baseline_mbps"]
        src = "srsran/results/E8_gate_replay.json:results"
        dil = [r for r in res if r["attack"] == "time_dilation" and r["dilation"] in (10, 100)
               and r["gate"] in ("fixed_window", "decaying_memory")]
        number("E8_calls_per_trace", value=d["calls_per_trace"], units="calls",
               source="srsran/results/E8_gate_replay.json:calls_per_trace")
        number("E8_time_gates_min_admitted_at_10x_100x", value=min(r["allowed"] for r in dil),
               units="calls", n=len(dil), baseline_key="E8_calls_per_trace", source=src,
               note="paper: 12/12 admitted at 10x and 100x dilation")
        number("E8_max_escalation_x", value=max(r["escalation_factor"] for r in res),
               units="x baseline", baseline_key="E4_baseline_ambr_mbps",
               source=src + ".escalation_factor",
               note="paper: 129.8x. The experiment records 129.75 (= 2594.93/20 = 129.7465, "
                    "stored to 2 dp); the paper rounds the stored value")
        cnt = next(r for r in res if r["gate"] == "session_write_counter"
                   and r["attack"] == "session_reinstantiation")
        number("E8_counter_admitted_after_reinstantiation", value=cnt["allowed"], units="calls",
               baseline_key="E8_calls_per_trace", source=src,
               note="paper: the counter admits every call after re-instantiation")
        drift = [r for r in res if r["gate"] == "policy_state_drift_bound"]
        number("E8_drift_bound_max_admitted", value=max(r["allowed"] for r in drift),
               units="calls", n=len(drift), source=src, note="paper: admits one call")
        number("E8_drift_bound_ceiling_x",
               value=round(max(r["max_ambr_reached_mbps"] for r in drift) / base, 2),
               units="x baseline", n=len(drift), baseline_key="E4_baseline_ambr_mbps", source=src,
               note="paper: 1.5x under every condition")

    # ── E10 sample size (§6.6) ──────────────────────────────────────────────
    if (d := _load("E10_overhead.json")):
        number("E10_n_per_arm", value=d["n_per_arm"], units="policy calls",
               source="srsran/results/E10_overhead.json:n_per_arm", note="paper: n=120")


def main() -> None:
    reg = build()
    OUT.write_text(json.dumps(reg, indent=2, sort_keys=True))
    nonrobust = [k for k, v in reg.items() if not v["robust_to_analysis_choices"]]
    print(f"  registry: {len(reg)} numbers -> {OUT}")
    print(f"  flagged NOT robust to analysis choices ({len(nonrobust)}):")
    for k in nonrobust:
        print(f"     - {k} = {reg[k]['value']} {reg[k]['units']}")


if __name__ == "__main__":
    main()
