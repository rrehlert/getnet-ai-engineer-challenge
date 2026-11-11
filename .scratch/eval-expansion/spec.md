# Spec: Eval expansion

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md`. Vocabulary: `GLOSSARY.md`.
Builds on: `.scratch/improvement-fixes/spec.md` (Evidence, independent Judge model, scenario facts).

## Problem Statement

After the fixes, the Judges can see Evidence and use an independent model, and the scenario script checks facts. But the quality picture is still thin:

- Judge Scores only exist as log lines, one Message at a time. There is no aggregate, no baseline, and no way to compare two versions of the system.
- Each scenario runs once. LLM output varies between runs, so a single pass or fail says little.
- Nothing measures whether a Message needed more than one specialist, or whether the reply covered everything asked. The decision on whether to build a multi-intent Router has no data behind it.
- Retrieval quality is unmeasured: when the Knowledge Agent answers badly, we can't tell whether the Corpus search missed or the model misused good Chunks.

## Solution

- A shared scenario dataset used by both the live smoke script and a new in-process eval runner.
- The eval runner builds the real graph, runs every scenario several times, runs the Judges synchronously with full access to Evidence, and writes a results file with per-scenario and aggregate scores. A baseline result is committed.
- A new **coverage** Judge Type records which specialists a Message needed and whether the reply covered all of it, giving the mixed-question rate and the incomplete rate. The runner checks them against the pre-agreed multi-intent threshold.
- A small labelled retrieval set measures recall@4 of the Corpus search directly.

## User Stories

1. As an evaluator, I want one scenario dataset shared by the smoke script and the eval runner, so that both measure the same cases.
2. As an evaluator, I want mixed-question scenarios that need both account data and product knowledge, so that coverage gaps show up.
3. As an evaluator, I want each scenario run several times, so that results reflect the system, not one lucky run.
4. As an evaluator, I want the number of runs configurable, so that I can trade cost for confidence.
5. As an evaluator, I want the eval runner to run the graph in-process, so that the Judges see Evidence that the HTTP response doesn't expose.
6. As an evaluator, I want the Judges to run synchronously in the eval runner and return their verdicts, so that scores can be aggregated.
7. As an evaluator, I want per-scenario results (routing pass rate, fact pass rate, mean Judge Score per Judge Type), so that I can find weak cases.
8. As an evaluator, I want aggregate results per Intent and overall, so that I can compare versions at a glance.
9. As an evaluator, I want results written to a timestamped file with the model names and commit, so that runs are comparable and reproducible.
10. As an evaluator, I want a committed baseline, so that every later checkpoint can be compared against it.
11. As an evaluator, I want the runner to print a comparison against the baseline, so that regressions are visible.
12. As an evaluator, I want a coverage Judge Type that lists the Intents a Message needed, so that mixed questions are counted.
13. As an evaluator, I want the coverage Judge to say whether the reply covered every part and what was missing, so that incomplete answers are counted.
14. As a maintainer, I want the coverage Judge to also run on live traffic, so that the mixed-question rate reflects real use.
15. As a maintainer, I want the runner to report the mixed-question rate and incomplete rate against the agreed threshold, so that the multi-intent Router decision is made on data.
16. As an evaluator, I want recall@4 on a labelled set of Knowledge questions, so that retrieval misses are measured separately from answer quality.
17. As an evaluator, I want retrieval misses listed with the URLs that came back, so that I can tell a Corpus gap from a ranking problem.
18. As a maintainer, I want the eval runner to need an LLM key but no running server, so that it's easy to run locally.
19. As a maintainer, I want evaluation costs bounded by a run count and visible token totals, so that eval spend is predictable.
20. As an evaluator, I want the Judge model recorded in each result, so that runs with different Judges aren't compared blindly.

## Implementation Decisions

**Dataset**
- The scenarios move to one shared data file: Message, whether logged in and as whom, expected Intent, expected facts (from the fixes spec), and for mixed scenarios the expected set of needed Intents.
- Adds 3–4 mixed scenarios, e.g. a Terminal offline plus how to fix its Wi-Fi, a pending Settlement plus how receivables advance works.
- The live smoke script reads the same file (routing + facts, as in the fixes spec).

**Judges**
- `run_judges` also returns its verdicts (it still writes the log lines).
- New Judge Type `coverage`, structured output: `intents_needed` (list of Intents), `fully_answered` (bool), `missing` (text), plus a score (1 when fully answered). Runs with the other Judges on live traffic and in the runner.
- New domain terms in `GLOSSARY.md`: Judge Type gains `coverage`; **Mixed question** (a Message that needs more than one specialist).

**Eval runner**
- In-process: builds the production graph with the configured models, invokes it per scenario (logged-in scenarios use the scenario's Merchant directly, no HTTP), runs the Judges synchronously with Evidence.
- `EVAL_RUNS` (default 3) runs per scenario.
- Per scenario: routing pass rate, fact pass rate, mean and min Judge Score per Judge Type, coverage fields, tokens.
- Aggregates: per Intent and overall; mixed-question rate (share of Messages with more than one needed Intent across runs); incomplete rate (share of mixed questions not fully answered); threshold check (≥10% mixed and ≥50% of those incomplete → "build multi-intent Router").
- Output: a timestamped JSON results file with metadata (commit, reply model, Judge model, run count, date) and a printed summary. A baseline results file is committed and compared against on every run (deltas printed).

**Retrieval**
- A labelled set of ~10 Knowledge questions, each with one or more expected Corpus URLs.
- recall@4: share of questions where an expected URL is among the top 4 Chunks' pages, computed directly against the index (no model). Misses printed with the URLs that came back. Reported in the same results file.

## Testing Decisions

- No real LLM calls in pytest.
- **Coverage Judge:** fake Judge model returning coverage output; assert the verdict is parsed, logged and returned. Prior art: `tests/test_observability.py`.
- **`run_judges` returns verdicts** for each Judge Type, and still logs.
- **Aggregation:** pure functions over hand-built run records: pass rates, means, mixed and incomplete rates, threshold decision, baseline deltas.
- **Runner wiring:** with an injected fake graph and fake Judge model, a two-scenario dataset produces a results file with the expected structure and metadata.
- **Dataset:** loads and validates (every scenario has an expected Intent; mixed scenarios list ≥2 needed Intents).
- **Recall@4:** fake index returning known pages; hits, misses and the printed miss list. Prior art: `tests/test_rag.py`.
- Live: run the runner once with real models; commit the baseline and record the summary in the diary.

## Out of Scope

- Human calibration of the Judges; canaries; dashboards.
- Hybrid retrieval, BM25, rerankers (only if recall@4 shows misses that justify them).
- MRR and holdout splits.
- The multi-intent Router itself (built only if the threshold is met).

## Further Notes

- Depends on the fixes (Evidence, Judge model, scenario facts).
- Eval runs cost money: with the default Judge model and 3 runs, a full run is roughly 16 scenarios × 3 runs × (graph + 3 Judges). Token totals are printed.
- If conversations-identity lands first, logged-in scenarios still bypass HTTP; the runner passes the Merchant id straight into graph state.
- Tickets are written when this feature starts.
