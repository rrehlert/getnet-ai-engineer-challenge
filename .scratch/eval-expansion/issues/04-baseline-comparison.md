# 04: Baseline and comparison

**What to build:** a committed baseline results file (`evals/baseline.json`) and a comparison printed on every run.

- After the summary, the runner prints deltas vs baseline: routing and fact pass rates and mean score per Judge Type, per Intent and overall; mixed/incomplete rates; tokens.
- Warns (does not fail) when the Judge model, reply model or dataset hash differs from the baseline's: deltas are then not like-for-like.
- `--save-baseline` copies the run's results to `evals/baseline.json`.
- Missing baseline → note and no deltas.

**Blocked by:** 03

**Status:** ready-for-agent

- [x] Delta function unit tests: improvements, regressions, Intent present in only one side
- [x] Mismatched Judge model / dataset hash → warning in output
- [x] No baseline → runs fine, prints note
- [x] `--save-baseline` writes the file

## Comments

2026-11-11, review decisions:

- Tokens compared per run (total / runs): totals scale with `EVAL_RUNS`, which may differ from the baseline's. No `eval_runs` warning needed.
- Mixed/incomplete rate deltas are `-` when a side has no coverage verdicts / no Mixed questions (the 03 rate of 0 there is "undefined", not 0%).
- Not done: flagging `judges_missing` differences in the comparison (the summary already prints them); tolerating baselines in an older format (06 writes the first one).
- `evals/baseline.json` itself comes from the live run (06).
