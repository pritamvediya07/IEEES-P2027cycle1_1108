# Experiment Suite — Section 5 Methodology

## Directory Structure

```
experiments/
├── run_all.py                      # Master runner (start here)
├── config.py                       # All parameters matching Section 5 v3
├── README.md                       # This file
├── utils/
│   └── __init__.py                 # MongoDB, iperf3, stats, PALA wrappers
├── v3_forecast/
│   ├── __init__.py
│   └── experiments.py              # E3.1–E3.4 + E3.5 amplification
├── v4_decomposition/
│   ├── __init__.py
│   └── experiments.py              # E4.1–E4.6 + ablations A4.1–A4.5
├── v7_wireheading/
│   ├── __init__.py
│   └── experiments.py              # E7.1–E7.6 + ablations A7.1–A7.5
└── results/                        # All outputs (JSON, CSV, PNG)
```

## Prerequisites

1. **Open5GS** running with subscribers registered
2. **UERANSIM** nr-gnb + nr-ue connected (`uesimtun0` interface up)
3. **PALA collector** running for ≥45 minutes (need 500+ upf_metrics samples)
4. **Ollama** serving `llama3.1` (only needed for V4 autonomous trials)
5. **iperf3** installed (`sudo apt install iperf3`)
6. **Python packages**: `pymongo`, `scikit-learn`, `numpy`, `scipy`, `matplotlib`

## Setup

```bash
# Copy experiments/ directory to the marcus project root
cp -r experiments/ /path/to/pala-artifact/experiments/

# Install any missing dependencies
cd /path/to/pala-artifact
source .venv/bin/activate
pip install scipy matplotlib

# Verify collector has enough data
python -c "
from pymongo import MongoClient
c = MongoClient('mongodb://localhost:27017')
n = c['nwdaf_analytics']['upf_metrics'].count_documents({})
print(f'Samples collected: {n}  (need ≥500 for full V3 sweep)')
print(f'Collector time needed: ~{max(0, (500-n)*5//60)} more minutes')
"
```

## Running Experiments

### Recommended order (matches Section 5 methodology)

```bash
cd /path/to/pala-artifact
source .venv/bin/activate

# V3 first — fastest, no LLM needed (~30 min)
python experiments/run_all.py v3

# V4 second — core contribution (1–3 hours)
# Quick experiments (threshold, manual decomp, defense):
python experiments/run_all.py v4

# V4.4 separately — LLM autonomous trials (1–3 hours):
python experiments/run_all.py v4.4

# V7 third — most involved (1–2 hours)
python experiments/run_all.py v7

# Generate all plots
python experiments/run_all.py plots

# Print summary of all results
python experiments/run_all.py summary
```

### Running individual experiments

```python
# From Python
from experiments.v3_forecast.experiments import run_e3_1
result = run_e3_1()

from experiments.v4_decomposition.experiments import run_e4_1
result = run_e4_1()
```

## Experiment-to-Paper Mapping

| Experiment | Paper Section | Figure/Table | What It Proves |
|-----------|---------------|--------------|----------------|
| E3.1 | §V-D | Fig. 6(a) | W(N) negatively correlated with N |
| E3.2 | §V-D | Fig. 6(b) | MAE decreases; R²_test < 0 for low N |
| E3.3 | §V-D | — | N ∈ [30,500] restricts pathological range |
| E3.4 | §V-D | — | R² guard catches residual overfitting |
| E4.1 | §V-B | — | Threshold β determined |
| E4.2 | §V-B | Fig. 2 | Manual decomposition crosses β |
| E4.3 | §V-B | Fig. 2 | Single-step blocked |
| E4.4 | §V-B | Fig. 3 | LLM produces decomposition (Fisher p<0.05) |
| E4.5 | §V-B | — | iperf3 confirms AMBR enforcement |
| E4.6 | §V-B | Fig. 7 | Accumulator defense blocks decomposition |
| E7.1 | §V-C | — | Baseline field inventory |
| E7.2 | §V-C | — | Policy modification recorded |
| E7.3 | §V-C | Fig. 4 | Type P field propagates to D_ana |
| E7.4a | §V-C | — | H_kpi reads Type P fields |
| E7.4b | §V-C | — | Type P fields causally affect H_kpi output |
| E7.4c | §V-C | Fig. 5 | Discriminating case: Δ_diverge > 0.10 |
| E7.6 | §V-C | Fig. 8 | DB isolation severs Type P propagation |

## V7 Defense Setup (E7.6)

E7.6 requires a second MongoDB instance:

```bash
# Create isolated data directory
mkdir -p /tmp/mongo_isolated

# Start second MongoDB on port 27018
mongod --port 27018 --dbpath /tmp/mongo_isolated --fork --logpath /tmp/mongo_isolated.log

# Reconfigure collector to write analytics to port 27018
# Edit /path/to/pala-artifact/config/settings.py:
#   Add: ANALYTICS_DB_PORT = 27018
# Then restart the collector
```

## Output Files

All results are saved as JSON in `results/`:
- Raw experiment data: `e{X}_{N}_{name}.json`
- CSV for plotting: `e3_1_sweep_data.csv`
- Figures: `fig{N}_{name}.png`
- Master log: `experiment_log.jsonl` (append-only log of all runs)

## Statistical Methods

| Test | Used In | Purpose |
|------|---------|---------|
| Spearman ρ | E3.1 | Rank correlation of W(N) with N |
| Fisher's exact | E4.4 | Attack vs control decomposition rate |
| Wilson CI | E4.4 | 95% confidence interval on success rate |
| Coefficient of variation | E4.5, E7.1 | iperf3 measurement stability |
| Rolling-origin CV | E3.1–E3.4 | Stable evaluation for small N |
