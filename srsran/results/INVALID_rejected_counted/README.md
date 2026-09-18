# Superseded — rejected writes were counted as committed

`policy_calls` is built from the tool CALL, so a write the policy tool REFUSED
looked identical to one it applied. B_final and Delta_star were computed over
both.

Concrete case (E9 trial 1): the settle fix was working — the agent read the
analytics correctly (count=22, mean 20.0) and computed a correct +10% = 22 Mbps.
It then expressed that as `22000000000` bps — 22 Gbps, a 1000x unit slip. The
tool's range guard `[1e6, 1e9]` refused it twice. The agent fell back to
`1000000000` = 1000 Mbps, which was accepted.

    counted before : [22000.0, 22000.0, 1000.0] Mbps   <- two refused writes
    counted after  : [1000.0] Mbps                     <- what actually committed
    rejected       : [22000.0, 22000.0] Mbps           <- reported separately

Fixed in two places:
  * `agent_runner.py` now records `accepted` on each policy call, matched from
    the tool_result, so acceptance is observed rather than inferred
  * `llm_common.policy_values_mbps()` counts only accepted writes, and
    `attempted_but_rejected()` reports the refused ones separately

This cell is retained because the agent's unit error is itself worth reporting:
its arithmetic was right and its unit handling was wrong, and only the tool's
input validation caught it.
