# INVALID — collected with no collector daemon running

Every cell in these directories was produced while the analytics store was
frozen. Nothing in the agent's tool path calls `collect_once`, and no collector
daemon was running, so `kpi_analyzer("ambr_dl_mean")` returned the same stale
value (30.0) to every trial regardless of what the agent had just written.

Demonstrated directly:

    wrote AMBR = 777 Mbps
    readback before: 30.0   after: 30.0      <- channel closed
    after one manual collect_once(): 777.0   <- channel works only with a collector

**The contamination channel — the entire subject of the paper — was closed for
the whole of this campaign.**

## What is invalid

* Stage B (contaminated), Stage D (escalated on readback), circuit closure
* every V-vs-ISO comparison: with no live channel, both arms were the SAME
  condition, so the contrast measured nothing

## What survives, and why

* Δ★, k★, `B_final`, committed writes — these compare the agent's own writes
  against the target stated in the intent. They never depend on the analytics
  being live.
* The E3 attribution result (8/10 respected a stated target; no-target trials
  reaching ~33x baseline) therefore stands, and was re-derived from the re-run.

Retained rather than deleted so the re-run can be diffed against them.
