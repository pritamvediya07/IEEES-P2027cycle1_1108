# INVALID — E3-Φ first attempt: R taken from the write, not the readback

The first attempt to evaluate Definition 4 inside agent sessions. Retained rather
than deleted so the E-FINAL result can be diffed against it.

## Three defects, each sufficient on its own

1. **R was read from the agent's WRITE rather than from its READBACK.** The
   IsolatedCollector arm could therefore score a satisfied Definition 4 even
   though the analytics field the agent reads was blanked — the defended arm was
   not a control at all. E-FINAL reads R through `kpi_analyzer` INSIDE the
   defence context, and records the unfiltered ground truth separately.

2. **No pre-action Q0.** The first Φ sample was taken after the first policy
   call, by which point λ was already 253–313 ms — past the normaliser, with the
   latency term at its floor. There was no measurement of the do-nothing
   alternative a′, which Definition 4 requires. E-FINAL measures Φ before the
   agent acts and treats that as a′.

3. **8 of 12 sessions committed nothing**, and the accounting of the rest
   predated the `accepted` flag, so calls the tool never executed were counted
   as commits.

## Status

0 of 12 sessions committed a policy write. Nothing in this file supports any
claim. Superseded entirely by `E_FINAL_def4.json` (targeted stratum) and
`E_FINAL_def4_openended.json` (open-ended stratum), which were run against a
pre-registered operating point from `calibration_regime.json`.
