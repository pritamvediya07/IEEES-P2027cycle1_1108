# INVALID — Anthropic API credit exhausted mid-tier

Cells 16-20 of the E6 frontier tier (the `sla_framing` half of the corpus) failed
with:

    400 invalid_request_error: Your credit balance is too low to access the
    Anthropic API.

Each returned in ~0.4 s with two error steps and no tool call. They were
checkpointed with `error: None` because `run_trial` itself returned normally, so
their empty stage indicators would have been read as **0/5 circuit closure** —
that is absence of data, not a null result, and reporting it would have been a
fabrication.

Fixed in `srsran/llm_common.py`: a trial whose every step is an error and which
reached no tool is now recorded as a failure, so it retries instead of being
cached as a result.

**The 15 `staged_change` cells are unaffected and valid.** Re-run the remaining 5
once credit is restored:

    .venv/bin/python srsran/e6_capability_sweep.py --n 20 --only-frontier \
        --frontier-backend anthropic --frontier-model claude-sonnet-4-5
