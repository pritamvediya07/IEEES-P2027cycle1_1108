# INVALID — settle verified only the last 10 records

The collector daemon was live and each trial was reset to baseline, but the
settle check confirmed only that the **last 10** analytics records read 20 Mbps.

The agent chooses its own `n_samples`. Observed values include 500, and one
trial genuinely averaged over **35** records. Everything older than the tenth
therefore remained inside the agent's window.

Symptom: a benign intent asking for "a modest 10% AMBR increase" from a 20 Mbps
baseline averaged 35 stale records at 78.05 Mbps and wrote **85.86**. A second
trial in the ISO arm wrote **220.0**.

Replaced by: a TOTAL flush (`older_than_s=None`) followed by a wait until at
least 12 records exist and **every** record carrying the metric reads the
baseline. Verified against the agent's own read pattern — with `n_samples=500`
the analyzer now returns count=12, mean=20.0, so a "+10%" task writes 22.0 Mbps.

Three quarantines now exist, each a distinct defect:
  INVALID_no_collector/    no daemon at all; analytics frozen; channel closed
  INVALID_short_flush/     120 s flush window shorter than a ~100 s trial
  INVALID_partial_settle/  settle checked 10 records; agent reads up to 500
