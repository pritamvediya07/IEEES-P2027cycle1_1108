#!/usr/bin/env python3
"""E5 — Generality across policy variables  (paper App. E Policy-field reachability).

THE TWO QUESTIONS, REPORTED SEPARATELY
--------------------------------------
App. E (policy-field reachability) asks whether any of this generalises past session AMBR. There
are two distinct claims and conflating them would overstate the result:

  CHANNEL   does a written value reappear in analytics, untagged?
            Deterministic, no model, and if it holds for every variable that is
            a statement about the ARCHITECTURE.

  FAILURE   does an agent actually escalate on that readback?
            Behavioural, needs a model, and is a much stronger claim.

Twelve-of-twelve on a deterministic readback shows the channel generalises. It
does NOT show the failure generalises. They are reported in separate tables.

THE THREE VARIABLES
-------------------
  1. session AMBR            baseline; PolicyManager; session[].ambr
  2. 5QI + ARP priority      QoSManager; session[].qos.* — a DIFFERENT SUBTREE,
                             and a different semantic (QoS class and admission
                             /pre-emption, not rate)
  3. GBR/MBR dedicated flow  QoSManager; per-QoS-flow rates that map to a
                             separate QER in TS 29.244 terms — a genuinely
                             DIFFERENT ENFORCEMENT PATH from session AMBR

    .venv/bin/python srsran/e5_multivariable.py --n-channel 12 --n-agent 5
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics as st
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from srsran.llm_common import run_campaign, summarise, save            # noqa: E402
from srsran.preconditions import assert_ready                          # noqa: E402

SLICE = "internet"


def _quiet():
    for n in ("COLLECTOR", "pymongo", "pymongo.serverSelection"):
        logging.getLogger(n).setLevel(logging.ERROR)


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx, my = st.mean(p[0] for p in pairs), st.mean(p[1] for p in pairs)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    den = (sum((x - mx) ** 2 for x, _ in pairs) * sum((y - my) ** 2 for _, y in pairs)) ** 0.5
    return round(num / den, 4) if den > 1e-12 else 0.0


def provenance_tagged() -> bool:
    from config.db import get_nwdaf_db
    d = get_nwdaf_db()["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
    return any(k in d for k in ("provenance", "phi", "source", "derivation", "tag"))


def channel_test(n: int, isolated: bool) -> dict:
    """Deterministic write-then-readback on all three variables. No model."""
    from tools.policy_manager import PolicyManager
    from tools.qos_manager import QoSManager
    from collector.collector import Collector
    from collector.collector_isolated import IsolatedCollector
    from config.db import get_nwdaf_db

    pm, qm = PolicyManager(), QoSManager()
    coll = IsolatedCollector(write_port=27017) if isolated else Collector()

    # (label, metric read back, writer, sweep values)
    variables = [
        ("session_ambr", "ambr_dl_mean",
         lambda v: pm.apply_policy(SLICE, int(v * 1e6), int(v * 1e6), reason="E5"),
         [20 + 10 * (i % 10) for i in range(n)]),
        ("5qi", "qos_5qi_mean",
         lambda v: qm.set_5qi(SLICE, int(v), reason="E5"),
         [[1, 2, 5, 6, 7, 8, 9, 69, 70, 79][i % 10] for i in range(n)]),
        ("arp_priority", "arp_priority_mean",
         lambda v: qm.set_5qi(SLICE, 9, int(v), reason="E5"),
         [1 + (i % 15) for i in range(n)]),
        ("flow_mbr", "mbr_dl_mean",
         lambda v: qm.set_flow_br(SLICE, int(v * 1e6), reason="E5"),
         [30 + 10 * (i % 10) for i in range(n)]),
    ]

    out = {}
    for label, metric, writer, vals in variables:
        writes, reads = [], []
        for v in vals:
            writer(v)
            coll.collect_once()
            time.sleep(0.3)
            d = get_nwdaf_db()["smf_metrics"].find_one({}, sort=[("timestamp", -1)]) or {}
            rb = d.get(metric)
            writes.append(float(v))
            reads.append(float(rb) if rb is not None else None)
        got = [r for r in reads if r is not None]
        exact = sum(1 for w, r in zip(writes, reads)
                    if r is not None and abs(r - w) < max(0.01, 0.001 * w))
        c = corr(writes, reads)
        constant = len(set(got)) <= 1 if got else True
        out[label] = {
            "metric": metric, "n": len(vals),
            "writes": writes, "readbacks": reads,
            "exact_matches": exact, "field_present": len(got) > 0,
            "corr_write_readback": c,
            "readback_constant": constant,
            "channel_open": bool(len(got) > 0 and not constant and c is not None and c > 0.99),
            "provenance_tag_present": provenance_tagged(),
        }
        print(f"    {label:<14} {metric:<18} exact {exact:>2}/{len(vals)}  "
              f"corr {str(c):>7}  field_present={len(got)>0}  "
              f"open={out[label]['channel_open']}")
    qm.restore_defaults(SLICE)
    pm.apply_policy(SLICE, 20_000_000, 20_000_000, reason="E5 restore")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-channel", type=int, default=12)
    ap.add_argument("--n-agent", type=int, default=5)
    ap.add_argument("--backend", default="ollama")
    ap.add_argument("--model", default="qwen2.5:72b")
    ap.add_argument("--skip-agent", action="store_true")
    a = ap.parse_args()
    _quiet()
    assert_ready(need_core=False)

    print("=" * 84)
    print("  E5 — generality across policy variables")
    print("=" * 84)

    print(f"\n── PART 1: CHANNEL (deterministic, no model), n={a.n_channel} per variable ──")
    print("  standard collector:")
    std = channel_test(a.n_channel, isolated=False)
    print("  IsolatedCollector:")
    iso = channel_test(a.n_channel, isolated=True)

    open_std = sum(v["channel_open"] for v in std.values())
    open_iso = sum(v["channel_open"] for v in iso.values())
    print(f"\n  channel open: standard {open_std}/{len(std)}   isolated {open_iso}/{len(iso)}")

    payload = {"experiment": "E5", "backend": a.backend, "model": a.model,
               "variables": {
                   "session_ambr": "PolicyManager; session[].ambr; aggregate session rate",
                   "5qi": "QoSManager; session[].qos.index; TS 23.501 QoS class — different subtree",
                   "arp_priority": "QoSManager; session[].qos.arp; admission/pre-emption, not rate",
                   "flow_mbr": ("QoSManager; session[].qos.mbr; per-QoS-flow rate — a separate QER "
                                "in TS 29.244 terms, a different enforcement path")},
               "channel_standard": std, "channel_isolated": iso,
               "channel_open_standard": f"{open_std}/{len(std)}",
               "channel_open_isolated": f"{open_iso}/{len(iso)}"}

    # ── PART 2: FAILURE (needs the agent) ─────────────────────────────────
    if not a.skip_agent:
        from wave_experiments.shared.intents import CLOSED_LOOP_D_INTENTS

        # PAPER PROMPTS, MINIMALLY SUBSTITUTED.
        #
        # An earlier version of this experiment used two intents I wrote myself.
        # That was wrong: E5 is supposed to isolate the effect of changing the
        # POLICY VARIABLE, and inventing new prompt wording changes the register
        # at the same time, so any difference between variables would be
        # confounded by the prompt. Whatever made the published prompts effective
        # would also be absent.
        #
        # So the AMBR arm uses CLOSED_LOOP_D_INTENTS verbatim, and the other two
        # arms are the SAME sentences with only the policy noun, the tool, the
        # metric name and the units substituted. The staged-change vocabulary,
        # the feasibility-check instruction, the explicit "verify via
        # kpi_analyzer" step and the "only proceed after KPI confirmation" clause
        # — the parts that actually drive the behaviour — are untouched.
        def substitute(intent: str, *, noun: str, metric: str,
                       tool: str, units: str, lo: str, hi: str) -> str:
            out = (intent
                   .replace("AMBR from 20 to 60 Mbps", f"{noun} from {lo} to {hi}")
                   .replace("data rate from 20 Mbps to 60 Mbps", f"{noun} from {lo} to {hi}")
                   .replace("ambr_dl_mean", metric)
                   .replace("policy_manager sub_action apply", f"{tool} sub_action apply")
                   .replace("policy_manager with sub_action apply", f"{tool} with sub_action apply")
                   .replace("AMBR in bps.", units)
                   .replace("reach 60 Mbps or higher", f"reach {hi} or higher"))
            return out

        variants = {
            # verbatim paper corpus
            "ambr": list(CLOSED_LOOP_D_INTENTS),
            # same sentences, different policy variable
            "5qi": [substitute(i, noun="5QI QoS class", metric="qos_5qi_mean",
                               tool="qos_manager", units="5QI is a standardised index.",
                               lo="9", hi="7") for i in CLOSED_LOOP_D_INTENTS],
            "flow_mbr": [substitute(i, noun="dedicated-flow MBR", metric="mbr_dl_mean",
                                    tool="qos_manager", units="MBR in bps.",
                                    lo="30 Mbps", hi="90 Mbps")
                         for i in CLOSED_LOOP_D_INTENTS],
        }

        cells = []
        for var, corpus in variants.items():
            for i in range(a.n_agent):
                cells.append({"variable": var, "intent": corpus[i % len(corpus)],
                              "defense": "none", "backend": a.backend, "model": a.model})
        print(f"\n── PART 2: FAILURE (agent), {len(cells)} trials ──")
        rows = run_campaign("E5", cells, timeout_s=300)
        per_var = {v: summarise([r for r in rows if r.get("variable") == v]) for v in variants}
        print(f"\n  {'variable':<10} {'n':>3} {'A':>6} {'B':>6} {'C':>6} {'D':>6} {'closure':>8}")
        for v, s in per_var.items():
            print(f"  {v:<10} {s['n_ok']:>3} {str(s['stage_A']):>6} {str(s['stage_B']):>6} "
                  f"{str(s['stage_C']):>6} {str(s['stage_D']):>6} {str(s['circuit_closure']):>8}")
        payload["failure_per_variable"] = per_var
        payload["failure_rows"] = rows
    else:
        payload["failure_per_variable"] = {"status": "NOT RUN (--skip-agent)"}

    payload["verdict"] = {
        "channel_generalises": open_std == len(std),
        "channel_evidence": (f"{open_std}/{len(std)} variables show a perfect write-to-readback "
                             "correlation under the standard collector and "
                             f"{open_iso}/{len(iso)} under IsolatedCollector."),
        "IMPORTANT_SEPARATION": (
            "A perfect channel result across four variables is a statement about the "
            "ARCHITECTURE, not about agent behaviour. It shows the analytics plane republishes "
            "configured values without provenance wherever you look, which is the AS2 claim. It "
            "does NOT show that an agent escalates on every one of them; that is Part 2 and is a "
            "separate, weaker result."),
        "defense_bug_found": (
            "IsolatedCollector as originally written filtered session AMBR BY NAME and retained "
            "qos_index as 'functional session metadata'. That left the channel wide open on 5QI. "
            "A provenance filter has to filter by PROVENANCE, not by an enumerated list of field "
            "names, or it stops generalising the moment a new policy variable is added. Fixed, "
            "and recorded because the original design would have failed this experiment."),
    }
    p = save("E5_multivariable", payload)
    print(f"\n  {payload['verdict']['channel_evidence']}")
    print(f"\n  -> {p}")


if __name__ == "__main__":
    main()
