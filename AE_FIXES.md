# Fixes from artifact evaluation (AE #59)

Every defect reported by reviewers 59A, 59B and 59C, what was changed, and how the
change was verified. Reviewer labels in brackets.

The offline verification path is unchanged in behaviour: `reproduce_results.py` still
reports **all 54 checks PASS**. The unit suite goes from **26 to 32 passed** — the six new
tests are additions; none of the original 26 changed.

---

## Blocking defects

### 1. Open5GS subscriber-schema mismatch [59A #1, 59C #5]

Open5GS 2.7+ (including 2.8.0, which the testbed images build) stores provisioned
sessions under `slice[].session[]`. All four tools queried only the legacy top-level
`session[]` array, so on a clean testbed policy writes matched nothing and the collector
read empty AMBR values.

New module **`tools/open5gs_schema.py`** provides `subscriber_query()`,
`iter_sessions()`, `iter_named_sessions()` and `session_update_doc()`. These match and
traverse **both** layouts, and persist edits back to whichever arrays a subscriber
actually carries — so documents written by the WebUI, which carry both, stay consistent.

Updated to use it: `tools/policy_manager.py`, `tools/session_manager.py`,
`tools/feasibility_checker.py`, `collector/collector.py`.

### 2. A write that changed nothing reported success [59C, "fix number 5 first"]

`PolicyManager._apply_via_direct_mongo` appended every matched subscriber to `affected`
whether or not a session actually matched the requested slice, then returned
`success=True`. Since `wave_experiments/shared/agent_runner.py:147` gates the Q-probe on
`pc.get("accepted")`, a vacuous write passed the gate that exists specifically to stop a
refused write from moving the enforcement point.

The loop now tracks whether a session was modified, skips the database write when none
was, and returns `success=False` with a message naming how many subscribers matched.

**Regression test:** `tests/test_open5gs_schema.py` — 6 tests covering the legacy
schema, the `slice[].session[]` schema, documents carrying both, readback agreement, and
the invariant that *a reported success implies the stored AMBR actually changed*. Three
of these fail against the pre-fix code and pass after it.

### 3. Missing `ca-certificates` in the UERANSIM image [59A #2, 59C #1]

`docker/testbed/Dockerfile.ueransim` installed `git` with `--no-install-recommends` and
never installed `ca-certificates`, so the UERANSIM clone failed certificate
verification. Added. (`Dockerfile.open5gs` already had it.)

### 4. YAML folded scalar collapsed the NWDAF Python block [59A #3, 59C #3]

`docker-compose.testbed.yml` used `command: >`, which folds newlines into spaces and made
the container restart-loop on `IndentationError`. Changed to `command: |`.

**Verified:** the compose file parses and the embedded program now `compile()`s.

### 5. `Collector()` constructor mismatch [59A #4, 59C #4]

The nwdaf service called `Collector(mongo_uri=…, db_name=…, interval_sec=5)` while
`Collector.__init__` took no arguments — an immediate `TypeError`. `__init__` now accepts
all three as optional arguments that default to the existing `config.settings` values, so
both the compose invocation and the previous no-argument form work.

### 6. `init-db` failures surfaced much later as an empty database [59C #2]

`quickstart.sh` sent `init-db` output to `/dev/null` and reported any failure as "may have
already run (normal on repeat starts)". It now shows the output and **verifies** the
subscriber count afterwards, failing immediately with a re-run command if the collection
is empty.

---

## Non-blocking defects

### 7. `UnicodeEncodeError` under a non-UTF-8 locale [59A, preamble]

`run_artifact.sh` now exports `PYTHONIOENCODING=utf-8`, and `reproduce_results.py`,
`analysis/verify_paper.py` and `analysis/verify_prompt_provenance.py` each call
`sys.stdout.reconfigure(encoding="utf-8")` defensively.

**Verified** by running the full suite under `LC_ALL=en_US.iso88591 LANG=en_US` with
`PYTHONIOENCODING` cleared — the exact configuration reviewer 59A reported. All 54 checks
pass.

### 8. Figure generator reported success while silently skipping figures [59B #1]

Investigating this found a larger problem than the exit code.
`final_paper_results/generate_all_figures.py` belongs to an earlier experiment layout: it
reads `e3_*`/`e4_*`/`e7_*` result files from `final_paper_results/results/`, a directory
that now contains no JSON at all, because those experiments were reorganised into
`final_experiments/exp1..exp15`. All eleven of its inputs were missing, every figure it
would build was skipped, and it still exited 0. Its outputs on disk date from April 2026.

None of them is in the paper. Figures 3 and 4 are built by
`final_experiments/RQ1_realization/figures/gen_fig1_hq.py` and
`final_experiments/RQ2_mechanism/figures/gen_fig2_hq.py`.

The script is therefore **removed from the verification chain**; `reproduce_results.py` runs
only those two generators, so the figure stage reports exactly what it rebuilt. The script
remains in the repository, marked superseded in its header, and can still be run by hand.

### 9. Silent fallback to system Python [59C, "smaller things"]

`run_experiments.sh` warned and continued when no `.venv` was present, producing four
confusing module-not-found failures several phases later. It now checks the imports up
front and stops with the exact `venv` + `pip install` command when they are missing.

### 10. Gemini backend offered without qualification [59C]

`quickstart.sh` offered Gemini as a peer of Ollama, though `MODEL_SETUP.md` states it is
not a paper model. The menu entry now says so and points to option 1 for reproducing paper
numbers. The backend itself is unchanged.

### 11. `STATUS.md` Zenodo wording [59C]

Reworded: the DOI is the version the evaluation assessed, and the post-evaluation version
is deposited before the camera-ready deadline.

### 12. Obsolete `version:` attribute in the compose file [59C]

Removed.

---

## Paid API keys are no longer required [@A1]

The administrator asked whether we could share an `ANTHROPIC_API_KEY` for the E6 frontier
tier. We would rather remove the need for one.

The 66 per-trial records from the paper's frontier run are archived under
`srsran/results/llm_trials/E6/`, and `e6_capability_sweep.py --summarise-only` recomputes
the tier statistics from them without issuing a single API call. `run_artifact.sh` now
takes that path automatically when `ANTHROPIC_API_KEY` is unset, instead of skipping the
tier.

**Verified:** with the key removed from the environment, the recomputed
`E6_capability_sweep.json` is byte-identical to the committed copy apart from its
`saved_at` timestamp — the frontier tier reproduces exactly (claude-sonnet-4-5, n=20,
closure 0.75).

Reviewers who want a genuinely fresh frontier run can still supply their own key; the live
path is unchanged. To be precise about what this is: the archived records are per-trial
*outcomes*, not stored model prompts and completions, so this reproduces the frontier
tier's reported statistics — it does not replay the model's text.

---

## Verification performed

| Check | Result |
|---|---|
| `python -m pytest tests/` | 26 → 32 passed (6 added, none changed) |
| `python -m pytest tests/test_open5gs_schema.py` | 6 passed (new) |
| Same 6 tests against pre-fix `policy_manager.py` | 3 failed — confirms genuine regression coverage |
| `reproduce_results.py` | all 54 checks PASS |
| `reproduce_results.py` under `LANG=en_US`, iso8859-1 | all 54 checks PASS |
| Compose file parses; embedded NWDAF program compiles | yes |
| `Collector(mongo_uri=…, db_name=…, interval_sec=5)` | constructs; no-argument form still works |
| E6 frontier tier with no API key | reproduces byte-identically (timestamp aside) |
| Regenerated figures and tables | byte-identical to the committed copies |
