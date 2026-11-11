# 03: In-process eval runner with aggregates and results file

**What to build:** `scripts/eval.py` builds the production graph in-process, runs every scenario from the dataset `EVAL_RUNS` times (default 3), runs the Judges synchronously with Evidence, and writes a timestamped JSON results file plus a printed summary.

- Graph and Judge model injectable (tests use fakes); defaults: `build_default_graph(load_default_index())` and `JUDGE_MODEL`. Needs an LLM key, no server.
- Logged-in scenarios pass `user_id` straight into graph state.
- Per run record: scenario id, intent, routing ok, facts ok + missing (reuses `check_reply`), Judge verdicts, tokens, latency, error (a provider error marks the run failed, the runner continues).
- Aggregation (pure functions over run records):
  - per scenario: routing pass rate, fact pass rate, mean and min score per Judge Type, coverage fields, tokens;
  - per expected Intent and overall: same rates and means;
  - Mixed-question rate: share of runs whose coverage `intents_needed` has >1 Intent; incomplete rate: share of those not `fully_answered`;
  - threshold check: ≥10% mixed **and** ≥50% of those incomplete → "build multi-intent Router", else "not justified".
  - also report dataset-labelled mixed scenarios: did the coverage Judge agree with `intents_needed`?
- Results file `evals/results/<UTC timestamp>.json` (gitignored dir): metadata (commit, dirty flag, reply model, Judge model, `EVAL_RUNS`, date, dataset hash), per-scenario, aggregates, token totals.
- Printed summary: per-Intent table, overall, mixed/incomplete rates vs threshold, token total.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Aggregation unit tests on hand-built records: pass rates, means/mins, mixed and incomplete rates (incl. zero mixed → rate 0, no division error), threshold both ways
- [ ] Runner with fake graph + fake Judge model on a two-scenario dataset writes a results file with expected structure and metadata
- [ ] `EVAL_RUNS` respected; a failing run is recorded, not fatal
- [ ] Token totals summed from graph `tokens`
- [ ] No real LLM calls in tests
