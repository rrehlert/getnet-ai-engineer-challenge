# 07: README: eval runner

**What to build (off the clock):** README section on the eval: how to run (`EVAL_RUNS`, `--save-baseline`, `--retrieval-only`), what is measured, the coverage Judge and the multi-intent threshold, baseline numbers; config table gains `EVAL_RUNS`. Semantic Quality gap marked closed.

**Blocked by:** 06

**Status:** done

## Comments

2026-11-11, from 03 review: README must say the results file (and so the committed baseline) holds raw Messages and replies, unredacted, unlike the logs. Fine while the eval only uses fixture Merchants (`data/merchants.json`); with real Merchant data, commit only aggregates and keep runs in a gitignored file. Run with `uv run python -m scripts.eval`.
