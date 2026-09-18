# INVALID — the IsolatedCollector control arm was not isolated

E2.3 ran with the collector DAEMON active. The daemon writes standard
`ambr_dl_mean` records every 5 s regardless of what the experiment's own
`tick(isolated)` call does, so the "isolated_control" arm was reading a live
standard analytics stream throughout. Provenance was never severed.

    standard    mean dR = 180.0  (n=2)
    ISO control mean dR = 180.0  (n=3)

Lemma 6 predicts dR = 0 in the ISO arm. It shows the same 180.0 as the treatment
arm, because both arms were the same condition. The control establishes nothing,
and without a working control the treatment number establishes nothing either.

Two further weaknesses in the same run:

  * only 5/10 repeats passed the Phi-static check (tau swung 22.5->25.6 Mbps,
    lambda 280->434 ms). Phi is noisy here and the passes cleared a loose
    tolerance on a jittery signal.
  * dR = 180 is simply 200 - 20, the written value reappearing. E2.1 already
    establishes that at 30/30 with correlation 1.0. The FIXED-Phi part is what
    E2.3 exists for, and it is exactly the part the broken control fails to show.

**C2 is therefore NOT established by this run.** Re-run with the collector daemon
stopped for the duration, so the isolated arm has no standard writer behind it.
