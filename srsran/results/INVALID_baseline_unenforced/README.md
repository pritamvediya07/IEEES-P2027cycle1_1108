# INVALID — the baseline ceiling was never enforced before Q0

`reset_baseline_ambr()` writes the AMBR into the Open5GS subscriber database. It
does NOT touch the HTB class that is this testbed's declared enforcement point.
`PhiAgentProbe.update_tc_for_ambr()` applies that class, and it only runs when the
AGENT issues a write — so at the moment Q0 is measured, no per-UE ceiling is in
force at all.

Evidence: with a nominal 5 Mbps/UE baseline and n=4, aggregate throughput could
not exceed 20 Mbps. Measured tau0 was 22.6, 24.4 and 25.0 Mbps across the three
sessions — full cell capacity — and lambda0 was 323, 351 and 353 ms rather than
the ~55-80 ms E0.4 records for that offered load.

The run therefore began in the saturated regime again, the exact condition that
makes Definition 4 unexhibitable. This is the second time the regime problem has
appeared, from a different cause each time.

Fixed by applying the baseline to the enforcement point before Q0 is measured,
and by asserting afterwards that aggregate tau does not exceed n x baseline. If
the ceiling is not actually holding, the run now aborts instead of recording.
