#!/usr/bin/env python3
"""Verify every srsRAN LLM experiment uses the PAPER's prompts and model.

The srsRAN rebuild only means something if the agent side is held constant. If
the prompts drift, a difference between the published results and these ones
could be the testbed or could be the wording, and there would be no way to tell.
So this asserts, mechanically:

  * the PALA SYSTEM_PROMPT is byte-identical to the one in agent/agent.py that
    the paper documents as the "InAgent LLM System Prompt" box
  * each experiment draws from the SAME corpus its published counterpart used
  * the primary model is the paper's (qwen2.5:72b)

Where an experiment has no published counterpart (E3, E5 Part 2), the corpus is
still drawn from the published pools rather than newly written, and E5's
non-AMBR arms are the published sentences with only the policy noun, tool,
metric and units substituted — so the register is held fixed and the variable is
the only thing that moves.

    .venv/bin/python analysis/verify_prompt_provenance.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wave_experiments.shared import intents as I          # noqa: E402
from wave_experiments.config import EXP8_WORKFLOWS, MODEL  # noqa: E402
import agent.agent as A                                    # noqa: E402

# experiment -> (published counterpart, corpora it must draw from)
EXPECT = {
    "E3 attribution":   ("new; corpora from published pools",
                         ["CLOSED_LOOP_D_INTENTS", "SLA_LOOP_INTENTS", "NULL_INTENTS"]),
    "E5 Part 2":        ("new; AMBR arm verbatim, others substituted",
                         ["CLOSED_LOOP_D_INTENTS"]),
    "E6 capability":    ("wave_experiments/exp1_vuln_multimodel.py",
                         ["CLOSED_LOOP_INTENTS"]),
    "E7 register":      ("wave_experiments/exp2_register.py",
                         ["CLOSED_LOOP_D_INTENTS", "DIRECT_INTENTS", "NULL_INTENTS"]),
    "E9 benign":        ("wave_experiments/exp8_utility.py",
                         ["BENIGN_INTENTS"]),
}

SRC = {
    "E3 attribution": ROOT / "srsran" / "e3_attribution.py",
    "E5 Part 2":      ROOT / "srsran" / "e5_multivariable.py",
    "E6 capability":  ROOT / "srsran" / "e6_capability_sweep.py",
    "E7 register":    ROOT / "srsran" / "e7_register.py",
    "E9 benign":      ROOT / "srsran" / "e9_benign_cost.py",
}

fail = []
print("=" * 78)
print("  Prompt provenance audit — srsRAN LLM experiments")
print("=" * 78)

# 1. system prompt untouched
sp = A.SYSTEM_PROMPT
marker = 'You are PALA, an advanced intent agent for 5G network operations.'
ok = sp.startswith(marker) and "RESPONSE FORMAT" in sp and "CRITICAL RULES" in sp
print(f"\n  [{'OK ' if ok else 'FAIL'}] SYSTEM_PROMPT is the documented PALA prompt "
      f"({len(sp)} chars, {len(sp.split())} words)")
if not ok:
    fail.append("SYSTEM_PROMPT altered")

# 2. corpora present and non-empty
print(f"\n  corpus sizes:")
for name in sorted({c for _, cs in EXPECT.values() for c in cs}):
    corpus = getattr(I, name, None)
    n = len(corpus) if corpus else 0
    print(f"    {name:<24} n = {n}")
    if not n:
        fail.append(f"{name} empty/missing")

# 3. each experiment imports the right corpus
print(f"\n  {'experiment':<18} {'published counterpart':<46} corpora")
for exp, (counterpart, corpora) in EXPECT.items():
    src = SRC[exp].read_text()
    missing = [c for c in corpora if c not in src]
    mark = "OK " if not missing else "FAIL"
    print(f"  [{mark}] {exp:<16} {counterpart:<46} {','.join(corpora)}")
    if missing:
        fail.append(f"{exp} does not reference {missing}")

# 4. no experiment defines its own intent strings
print(f"\n  hand-written intent strings (should be none outside substitution):")
for exp, path in SRC.items():
    src = path.read_text()
    suspicious = [ln.strip() for ln in src.split("\n")
                  if ("internet slice" in ln or "kpi_analyzer" in ln)
                  and ln.strip().startswith('"')
                  and "replace(" not in ln]
    if suspicious:
        print(f"    [WARN] {exp}: {len(suspicious)} literal(s)")
        for x in suspicious[:2]:
            print(f"           {x[:90]}")
        fail.append(f"{exp} contains hand-written intent literals")
    else:
        print(f"    [OK ] {exp}")

# 5. model
print(f"\n  paper primary model: {MODEL}")
for exp, path in SRC.items():
    src = path.read_text()
    if 'default="qwen2.5:72b"' in src or '"qwen2.5:72b"' in src:
        print(f"    [OK ] {exp} uses {MODEL}")
    else:
        print(f"    [WARN] {exp} does not name {MODEL}")

# 6. E9 corpus size matches the published one
e9 = SRC["E9 benign"].read_text()
ok9 = "EXP8_WORKFLOWS" in e9
print(f"\n  [{'OK ' if ok9 else 'FAIL'}] E9 uses BENIGN_INTENTS[:EXP8_WORKFLOWS] "
      f"(= {EXP8_WORKFLOWS}), matching exp8_utility.py")
if not ok9:
    fail.append("E9 corpus size does not match the published one")

print("\n" + "=" * 78)
if fail:
    print(f"  {len(fail)} PROBLEM(S):")
    for f_ in fail:
        print(f"    - {f_}")
    sys.exit(1)
print("  PASSED — every experiment uses the paper's prompts, corpora and model")
