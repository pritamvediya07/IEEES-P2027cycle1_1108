# New Experiment Campaign — Behavioral and End-to-End Evidence

## Quick Start

```bash
# Copy to your project
cp -r new_experiments/ /path/to/pala-artifact/experiments/new_campaign/

# Run highest-priority experiment first (~4 hours)
cd /path/to/pala-artifact
python experiments/new_campaign/run_new_campaign.py priority1

# Check status
python experiments/new_campaign/run_new_campaign.py summary

# Generate figures after experiments
python experiments/new_campaign/run_new_campaign.py figures
```

## File Structure

```
new_experiments/
├── run_new_campaign.py       # Master runner (start here)
├── utils.py                  # Shared: MongoDB, agent interaction, iperf3
├── e7_7_behavioral.py        # E7.7a-d + ablations (Priority 1,3,5)
├── e4_7_end_to_end.py        # E4.7a,c (Priority 2,6)
├── e4_8_autonomous.py        # E4.8a-c (Priority 4)
├── e_cross_vulnerability.py  # E-Cross-1,2 (Priority 5)
├── generate_new_figures.py   # Figs 9-12, Tables 14-17
└── results/                  # All outputs
```

## Priority Execution Order

| Priority | Command | Time | What | Why |
|----------|---------|------|------|-----|
| 1 | `priority1` | 4h | E7.7a+b behavioral comparison | Highest priority |
| 2 | `priority2` | 2h | E4.7c Definition 4 | Fixes overclaim issue |
| 3 | `priority3` | 4h | E7.7c+d explicit self-eval | Strengthens V7 |
| 4 | `priority4` | 12h | E4.8a+b autonomous robustness | Shows rate varies |
| 5 | `priority5` | 7h | E-Cross + ablations | Cross-vulnerability evidence |
| 6 | `priority6` | 1h | E4.7a UPF enforcement | Nice to have |

## Prerequisites

### For E7.7 Clean Condition (Priority 1, Phase 2):
```bash
# Start isolated MongoDB
mkdir -p /tmp/mongo_isolated
mongod --port 27018 --dbpath /tmp/mongo_isolated --fork --logpath /tmp/mongo_isolated.log

# Start IsolatedCollector
python collector/collector_isolated.py

# Wait ~60s for baseline data to accumulate
```

### For E4.8a Temperature Variation:
The script modifies `config/settings.py` TEMPERATURE value.
Original (0.1) is restored after the experiment.
