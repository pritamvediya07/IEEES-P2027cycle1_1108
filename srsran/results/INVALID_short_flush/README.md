# INVALID — 120 s analytics flush window was too short

These cells ran with the collector daemon live (so the channel was open), but the
per-trial flush dropped only records older than 120 s. Trials take ~100 s, so the
PREVIOUS trial's writes survived the flush and were visible to the next trial.

Concrete symptom: a benign intent instructing "apply a modest 10% AMBR increase"
computed the increase against the leftover mean and wrote **358.54 Mbps**, having
just been reset to 20 Mbps.

Replaced by: full flush (`older_than_s=None`) followed by seeding 12 collector
ticks against the freshly reset baseline, so every trial starts from an identical
analytics state showing only the baseline. Within-trial contamination is
unaffected — the daemon keeps running throughout the trial.
