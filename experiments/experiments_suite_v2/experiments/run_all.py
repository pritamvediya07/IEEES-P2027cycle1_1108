#!/usr/bin/env python3
"""Master Runner - corrected after V3 results. Use: python run_all.py v3|v4|v7|plots|summary|all"""
import sys, json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent))

def run_v3():
    from v3_forecast.experiments_v2 import run_all_v3
    return run_all_v3()
def run_v4():
    from v4_decomposition.experiments import run_all_v4
    return run_all_v4()
def run_v7():
    from v7_wireheading.experiments import run_all_v7
    return run_all_v7()
def print_summary():
    rd = Path(__file__).parent / "results"
    print("\n" + "="*70 + "\nEXPERIMENT RESULTS SUMMARY\n" + "="*70)
    for f in sorted(rd.glob("*.json")):
        with open(f) as fh: data = json.load(fh)
        a = data.get("accepted"); s = "Y" if a==True else ("X" if a==False else "o")
        print(f"  [{s}] {data.get('experiment', f.stem)}: {f.name}")

if __name__ == "__main__":
    args = sys.argv[1:] or ["all"]
    print(f"\n{'#'*60}\n# PALA Experiments (corrected) — {' '.join(args)}\n{'#'*60}")
    for a in args:
        {"v3": run_v3, "v4": run_v4, "v7": run_v7, "summary": print_summary,
         "all": lambda: (run_v3(), run_v4(), run_v7(), print_summary())
        }.get(a, lambda: print(f"Unknown: {a}"))()
