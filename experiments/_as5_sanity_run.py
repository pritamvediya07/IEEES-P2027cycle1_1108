
import sys, json
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]   # artifact root
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "experiments"))
from exp5_necessity_ablation import run_trial, MODEL_NAME
from probe.q_probe import QProbeHarness

MODEL_NAME = "qwen2.5:72b"
probe = QProbeHarness(baseline_ambr_mbps=20.0)
readback_seen = False
for i in [1, 2]:
    try:
        trial, events = run_trial("as5_enforced", i, probe)
        if trial.get("contam_readback"):
            readback_seen = True
        print(f"Sanity trial {i}: contam_readback={trial.get('contam_readback')} policy_calls={trial.get('policy_calls')}")
    except Exception as e:
        print(f"Sanity trial {i} error: {e}")

print(f"Readback seen: {readback_seen}")
sys.exit(0 if readback_seen else 2)
