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

- [x] Aggregation unit tests on hand-built records: pass rates, means/mins, mixed and incomplete rates (incl. zero mixed → rate 0, no division error), threshold both ways
- [x] Runner with fake graph + fake Judge model on a two-scenario dataset writes a results file with expected structure and metadata
- [x] `EVAL_RUNS` respected; a failing run is recorded, not fatal
- [x] Token totals summed from graph `tokens`
- [x] No real LLM calls in tests

## Comments

2026-11-11, from the live check after 01/02 (rebuilt compose stack, trace `9dfda47e…`, `c0018a66…`):

- The Router is unstable on Mixed questions: the Caixa 1 offline + Wi-Fi message went to `support` on 11-10 and `knowledge` on 11-11. For scenarios with `intents_needed`, accept any Intent in that list as routing-correct; judge them on `coverage`.
- The `route` Judge marks the Router down for not picking both Intents (0.4, then 0.0), which overlaps with `coverage`. Add a rule to `ROUTE_PROMPT`: for a Mixed question, choosing one of the needed Intents is correct.
- The coverage Judge behaved as intended: mixed → `intents_needed: [support, knowledge]`, `fully_answered: false`, 0.4; Pix question → `[knowledge]`, fully answered, 1.0.
- `answer` gave 0.0 to the Pix reply for opening with "Yes" (the Corpus says a Pix key linked to the receiving account). Possibly harsh; check in the baseline whether it's a pattern.

2026-11-11, review decisions:

- Results file keeps raw `message`/`answer` (fixture data only; README note on 07).
- Judge failures: `judges_missing` per Judge Type (answered runs lacking a verdict), printed when non-zero.
- Failed runs count as routing/fact failures; errors reported alongside.
- Labelled-mixed agreement = exact set match; revisit if 06 shows disagreements are mostly extra Intents.
- Scenario id = hash of the Message (stable for the 04 baseline join); position kept as `index`.
