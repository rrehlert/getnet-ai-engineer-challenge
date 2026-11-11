# 04: Baseline and comparison

**What to build:** a committed baseline results file (`evals/baseline.json`) and a comparison printed on every run.

- After the summary, the runner prints deltas vs baseline: routing and fact pass rates and mean score per Judge Type, per Intent and overall; mixed/incomplete rates; tokens.
- Warns (does not fail) when the Judge model, reply model or dataset hash differs from the baseline's: deltas are then not like-for-like.
- `--save-baseline` copies the run's results to `evals/baseline.json`.
- Missing baseline → note and no deltas.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Delta function unit tests: improvements, regressions, Intent present in only one side
- [ ] Mismatched Judge model / dataset hash → warning in output
- [ ] No baseline → runs fine, prints note
- [ ] `--save-baseline` writes the file
