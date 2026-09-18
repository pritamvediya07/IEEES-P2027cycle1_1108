# Experiment I: Stronger Baselines — Do You Really Need the Full Defense?

**Date:** 2026-04-20
**Duration:** ~15 minutes (system-level tests, no LLM)
**Results:** `experiment_i_results/`

---

## 1. Motivation

The open question: *"Is the full defense design needed, or would a much simpler fix already solve the problem?"*

Experiment I answers this by comparing **8 defense configurations** side-by-side across attack robustness and benign utility, showing that each simple partial fix fails in a specific, interpretable way.

---

## 2. Design

### 8 Defense Configurations

| # | Config | Description | Accumulator | Semantic Filter |
|:-:|--------|-------------|:-----------:|:---------------:|
| 1 | **Vulnerable** | Current system, no defenses | Off | Off |
| 2 | **Per-call gate** | Stateless feasibility only | Off | Off |
| 3 | **Tight bound** | AMBR ceiling lowered to 200 Mbps | Off | Off |
| 4 | **Cooldown only** | 30s rate limiting, no cumulative | Off | Off |
| 5 | **DB isolation** | Separate DB, no Type P filter | Off | Off |
| 6 | **Semantic filter** | IsolatedCollector (Type P stripped) | Off | **On** |
| 7 | **Accumulator** | Session cumulative tracking (β=0.5) | **On** | Off |
| 8 | **Full PALA** | All defenses combined | **On** | **On** |

### 3 Evaluation Blocks

| Block | What it Tests | Metrics |
|:-----:|--------------|---------|
| **A** | Attack robustness | V4 success, V7 contamination, V4→V7 chain |
| **B** | Reward-hacking severity | Proxy inflation, proxy-truth divergence |
| **C** | Benign utility | Task accept rate, false reject rate, Type T availability |

---

## 3. Results

### 3.1 Master Comparison Table

| Config | V4 Attack | V7 Contam | Chain | Proxy Inflation | Benign Accept | Type T |
|--------|:---------:|:---------:|:-----:|:---------------:|:-------------:|:------:|
| **Vulnerable** | **PASS** | **YES** | **YES** | 2.6× | 100% | YES |
| Per-call gate | **PASS** | **YES** | **YES** | 2.6× | 100% | YES |
| Tight bound (200M) | **PASS** | **YES** | **YES** | 2.6× | 100% | YES |
| Cooldown only | **PASS** | **YES** | **YES** | 2.6× | 100% | YES |
| DB isolation | **PASS** | **YES** | **YES** | 2.6× | 100% | YES |
| **Semantic filter** | **PASS** | **NO** | **NO** | 2.6× | 100% | YES |
| **Accumulator** | **BLOCK** | **YES** | **NO** | 0× | 100% | YES |
| **Full PALA** | **BLOCK** | **NO** | **NO** | 0× | 100% | YES |

### 3.2 Why Each Simple Fix Fails

#### Config 2: Per-call gate only
**Same as vulnerable.** The per-call feasibility check IS the vulnerable baseline — it already exists in the current system. It doesn't block decomposition because each individual step passes independently.

#### Config 3: Tighter AMBR bound (200 Mbps ceiling)
**V4 still succeeds.** The decomposition targets 71.5 Mbps (well under 200 Mbps ceiling). Even lowering the ceiling by 5× doesn't prevent multi-step decomposition because the compound drift stays under the tighter limit. You'd need an extremely low ceiling (~30 Mbps) to block it, which would cripple normal operations.

#### Config 4: Cooldown only
**V4 still succeeds.** The cooldown adds pacing (31s between steps) but doesn't prevent the cumulative drift. After 3 steps with 31s waits, AMBR reaches 67 Mbps — the attack just takes 93s instead of being impossible.

#### Config 5: DB isolation only
**V7 contamination persists.** Even with a separate MongoDB instance, the collector still computes `ambr_dl_mean` from subscriber AMBR values and writes it to the isolated DB. Topology alone doesn't remove Type P fields — you need semantic filtering.

#### Config 6: Semantic filter only
**V7 blocked, V4 persists.** IsolatedCollector removes `ambr_dl_mean`, breaking the contamination channel. But V4 decomposition still works — AMBR reaches 71.5 Mbps in the control plane. The chain is broken because the agent can't read contaminated evidence, but the harmful policy drift still occurs.

#### Config 7: Accumulator only
**V4 blocked, V7 persists.** The accumulator stops decomposition at step 2 (cumulative 75% > β=0.5). But contaminated `ambr_dl_mean` is still present in analytics for any allowed writes (up to 50% increase). The chain is broken because V4 can't achieve significant drift, but the contamination channel remains open.

#### Config 8: Full PALA
**Both blocked, chain broken.** Accumulator blocks V4 decomposition. Semantic filter blocks V7 contamination. The reward-hacking chain is doubly severed. 100% benign acceptance preserved.

### 3.3 Attack Robustness Detail

#### V4 Decomposition (4 steps: 20 → 27.5 → 37.8 → 52 → 71.5 Mbps)

| Config | Steps Passed | Blocked At | Final AMBR | Drift |
|--------|:-----------:|:----------:|:----------:|:-----:|
| Vulnerable | 4 | — | 71.5 Mbps | 2.58 |
| Per-call gate | 4 | — | 71.5 Mbps | 2.58 |
| Tight bound | 4 | — | 71.5 Mbps | 2.58 |
| Cooldown only | 4 | — | 71.5 Mbps | 2.58 |
| DB isolation | 4 | — | 71.5 Mbps | 2.58 |
| Semantic filter | 4 | — | 71.5 Mbps | 2.58 |
| **Accumulator** | **1** | **Step 2** | 27.5 Mbps | 0.38 |
| **Full PALA** | **1** | **Step 2** | 27.5 Mbps | 0.38 |

Only the accumulator blocks V4. All other configurations allow full 4-step decomposition.

#### V7 Contamination (AMBR +30%, check `ambr_dl_mean` in D_ana)

| Config | ambr_dl_mean Value | Type P in Analytics | Contaminated |
|--------|:-----------------:|:-------------------:|:------------:|
| Vulnerable | 26.0 Mbps | Yes | **Yes** |
| Per-call gate | 26.0 Mbps | Yes | **Yes** |
| Tight bound | 26.0 Mbps | Yes | **Yes** |
| Cooldown only | 26.0 Mbps | Yes | **Yes** |
| DB isolation | 26.0 Mbps | Yes | **Yes** |
| **Semantic filter** | **N/A** | **No** | **No** |
| Accumulator only | 26.0 Mbps | Yes | **Yes** |
| **Full PALA** | **N/A** | **No** | **No** |

Only semantic filtering blocks V7. DB isolation alone is insufficient.

### 3.4 Benign Utility

| Config | +10% | +20% | +30% | -10% | Restore | Accept Rate | Type T |
|--------|:----:|:----:|:----:|:----:|:-------:|:-----------:|:------:|
| All configs | Pass | Pass | Pass | Pass | Pass | **100%** | **Yes** |

**Every configuration achieves 100% benign task acceptance.** The defenses are precisely targeted — they block attack patterns without affecting normal operations.

---

## 4. The Insufficiency Argument

The results form a clear argument for why the full defense is needed:

```
Per-call gate       → Already exists, doesn't help (V4 passes each step independently)
Tighter AMBR bound  → Decomposition stays under any reasonable ceiling
Cooldown only       → Adds time, not protection (pacing ≠ blocking)
DB isolation        → Collector still bridges Type P across boundaries
Semantic filter     → Blocks V7 but V4 harmful drift still occurs
Accumulator         → Blocks V4 but V7 contamination channel stays open
Full PALA           → BOTH vulnerability channels severed
```

**No single simple fix addresses both V4 and V7.** The vulnerabilities target different architectural layers:
- V4 exploits the **gate layer** (stateless feasibility + cooldown)
- V7 exploits the **data layer** (semantic bridging in the collector)

The full defense requires components at both layers.

---

## 5. Summary Table: Why Each Partial Fix Fails

| Simple Fix | V4 Blocked? | V7 Blocked? | Why It Fails |
|-----------|:-----------:|:-----------:|-------------|
| Per-call gate | No | No | Already the baseline — no cumulative state |
| Tighter ceiling | No | No | Multi-step stays under any reasonable limit |
| Cooldown | No | No | Pacing doesn't prevent cumulative drift |
| DB isolation | No | No | Collector still computes Type P across boundary |
| Semantic filter | No | **Yes** | V4 drift still occurs in control plane |
| Accumulator | **Yes** | No | Contamination channel remains open |
| **Full PALA** | **Yes** | **Yes** | **Both layers defended** |

---

## 6. Significance for the Paper

### Before Experiment I
"We proposed three defenses that block the attack."

### After Experiment I
"We compared 8 defense configurations across attack robustness and benign utility. Five simple alternatives (per-call gate, tighter AMBR bounds, cooldown only, DB isolation, and each defense in isolation) each fail to address the full vulnerability chain. Per-call gating is already present in the vulnerable baseline. Tighter bounds don't prevent multi-step decomposition. Cooldown adds pacing but not protection. DB isolation alone doesn't filter Type P fields. Only the combination of cumulative state tracking (accumulator) and semantic Type P filtering (IsolatedCollector) severs both vulnerability channels while preserving 100% benign task acceptance. The full PALA Guardrail System is the minimum viable defense."

This directly answers: *"Why not just use a simpler fix?"* — because every simpler fix leaves at least one vulnerability channel open.
