import itertools
import json
from datetime import UTC, datetime

import httpx
import openai
import pytest

from app.graph import build_graph
from scripts.eval import (
    aggregate,
    compare,
    eval_runs,
    format_comparison,
    format_summary,
    mixed_stats,
    report,
    run_eval,
    summarize,
    threshold_decision,
)
from tests.test_observability import FakeJudgeModel, coverage, verdict


def record(
    scenario="01",
    expected="knowledge",
    routing_ok=True,
    facts_ok=None,
    scores=None,
    coverage=None,
    tokens=10,
    error=None,
    intents_needed=(),
):
    """A run record as the runner writes it; `coverage` is (intents_needed, fully_answered)."""
    verdicts = {judge_type: {"score": score, "reason": "r"} for judge_type, score in (scores or {}).items()}
    if coverage is not None:
        needed, full = coverage
        verdicts["coverage"] = {
            "score": 1.0 if full else 0.4,
            "reason": "r",
            "intents_needed": list(needed),
            "fully_answered": full,
            "missing": "" if full else "the other part",
        }
    return {
        "scenario": scenario,
        "message": f"message {scenario}",
        "expected_intent": expected,
        "intents_needed": list(intents_needed),
        "intent": None if error else expected,
        "routing_ok": routing_ok,
        "facts_ok": facts_ok,
        "missing_facts": [],
        "verdicts": verdicts,
        "tokens": tokens,
        "latency_ms": 5,
        "error": error,
    }


def test_summarize_pass_rates_and_judge_mean_and_min():
    records = [
        record(routing_ok=True, facts_ok=True, scores={"route": 1.0, "answer": 0.5}, tokens=10),
        record(routing_ok=False, facts_ok=False, scores={"route": 0.0, "answer": 0.9}, tokens=20),
        record(routing_ok=True, facts_ok=True, scores={"route": 1.0}, tokens=30),
        record(routing_ok=True, facts_ok=None, tokens=40),
    ]

    stats = summarize(records)

    assert stats["runs"] == 4
    assert stats["routing_pass_rate"] == 0.75
    assert stats["fact_pass_rate"] == pytest.approx(2 / 3)  # runs without facts don't count
    assert stats["judges"]["route"] == {"mean": pytest.approx(2 / 3), "min": 0.0, "n": 3}
    assert stats["judges"]["answer"] == {"mean": pytest.approx(0.7), "min": 0.5, "n": 2}
    assert stats["tokens"] == 100


def test_summarize_counts_failed_runs_as_failures():
    records = [record(facts_ok=True), record(routing_ok=False, facts_ok=False, error="provider_unavailable", tokens=0)]

    stats = summarize(records)

    assert stats["errors"] == 1
    assert stats["routing_pass_rate"] == 0.5
    assert stats["fact_pass_rate"] == 0.5


def test_summarize_counts_missing_verdicts_per_judge_type():
    records = [
        record(scores={"route": 1.0, "answer": 1.0}, coverage=(["knowledge"], True)),
        record(scores={"route": 1.0}, coverage=(["knowledge"], True)),  # answer Judge failed
        record(scores={}),  # every Judge failed
        record(error="rate_limited"),  # graph failed: no Judges ran, nothing missing
    ]

    assert summarize(records)["judges_missing"] == {"route": 1, "answer": 2, "coverage": 1}


def test_summary_shows_missing_verdicts_only_when_some_are_missing(tmp_path):
    _, results = run(tmp_path)
    assert "missing verdicts" not in format_summary(results)

    results["overall"]["judges_missing"]["answer"] = 2
    assert "missing verdicts: answer 2" in format_summary(results)


def test_summarize_without_facts_or_judges_reports_none():
    stats = summarize([record(facts_ok=None)])

    assert stats["fact_pass_rate"] is None
    assert stats["judges"] == {}


def test_mixed_and_incomplete_rates():
    records = [
        record(coverage=(["support", "knowledge"], False)),
        record(coverage=(["support", "knowledge"], True)),
        record(coverage=(["knowledge"], True)),
        record(coverage=(["knowledge"], True)),
        record(error="rate_limited"),  # no coverage verdict: not counted
    ]

    stats = mixed_stats(records)

    assert stats["judged"] == 4
    assert stats["mixed"] == 2
    assert stats["mixed_rate"] == 0.5
    assert stats["incomplete"] == 1
    assert stats["incomplete_rate"] == 0.5
    assert stats["decision"] == "build multi-intent Router"


def test_zero_mixed_questions_gives_zero_rates():
    stats = mixed_stats([record(coverage=(["knowledge"], True))])

    assert stats["mixed_rate"] == 0
    assert stats["incomplete_rate"] == 0
    assert stats["decision"] == "not justified"


def test_no_coverage_verdicts_gives_zero_rates():
    stats = mixed_stats([record(error="rate_limited")])

    assert (stats["judged"], stats["mixed_rate"], stats["incomplete_rate"]) == (0, 0, 0)


@pytest.mark.parametrize(
    ("mixed_rate", "incomplete_rate", "decision"),
    [
        (0.10, 0.50, "build multi-intent Router"),
        (0.30, 0.90, "build multi-intent Router"),
        (0.09, 0.90, "not justified"),
        (0.50, 0.49, "not justified"),
        (0.0, 0.0, "not justified"),
    ],
)
def test_threshold_needs_ten_percent_mixed_and_half_of_those_incomplete(mixed_rate, incomplete_rate, decision):
    assert threshold_decision(mixed_rate, incomplete_rate) == decision


def test_aggregate_groups_by_scenario_and_expected_intent():
    records = [
        record("01", "knowledge", routing_ok=True, scores={"answer": 1.0}),
        record("01", "knowledge", routing_ok=False, scores={"answer": 0.0}),
        record("02", "support", routing_ok=True, facts_ok=True, scores={"answer": 0.8}),
    ]

    result = aggregate(records)

    assert set(result["per_scenario"]) == {"01", "02"}
    assert result["per_scenario"]["01"]["routing_pass_rate"] == 0.5
    assert result["per_scenario"]["01"]["judges"]["answer"]["min"] == 0.0
    assert result["per_scenario"]["01"]["message"] == "message 01"
    assert result["per_intent"]["knowledge"]["runs"] == 2
    assert result["per_intent"]["support"]["fact_pass_rate"] == 1.0
    assert result["overall"]["runs"] == 3
    assert result["overall"]["routing_pass_rate"] == pytest.approx(2 / 3)


def test_aggregate_reports_coverage_fields_per_scenario():
    records = [
        record("05", "support", coverage=(["support", "knowledge"], False), intents_needed=["support", "knowledge"]),
        record("05", "support", coverage=(["support", "knowledge"], True), intents_needed=["support", "knowledge"]),
    ]

    fields = aggregate(records)["per_scenario"]["05"]["coverage"]

    assert fields["fully_answered_rate"] == 0.5
    assert fields["intents_needed"] == [["support", "knowledge"], ["support", "knowledge"]]
    assert fields["missing"] == ["the other part"]


def test_labelled_mixed_scenarios_report_coverage_judge_agreement():
    needed = ["support", "knowledge"]
    records = [
        record("14", "support", coverage=(["knowledge", "support"], False), intents_needed=needed),  # order ignored
        record("14", "support", coverage=(["support"], True), intents_needed=needed),
        record("14", "support", error="rate_limited", intents_needed=needed),  # unjudged: not counted
        record("01", "knowledge", coverage=(["knowledge"], True)),  # not labelled mixed
    ]

    labelled = aggregate(records)["labelled_mixed"]

    assert labelled == {
        "scenarios": {"14": {"intents_needed": needed, "judged": 2, "agreed": 1, "agreement_rate": 0.5}},
        "judged": 2,
        "agreed": 1,
        "agreement_rate": 0.5,
    }


# --- Runner: fake graph and fake Judge model, no real LLM calls ---

NOW = datetime(2026, 11, 11, 20, 30, 5, tzinfo=UTC)


def dataset(tmp_path):
    path = tmp_path / "scenarios.json"
    path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {"message": "What is Get Smart?", "user_id": "cliente1988", "intent": "knowledge", "facts": [["touchscreen"]]},
                    {"message": "Caixa 1 offline, how to set Wi-Fi?", "user_id": "cliente2024", "intent": "support",
                     "intents_needed": ["support", "knowledge"]},
                ]
            }
        )
    )
    return path


def router(state):
    intent = "knowledge" if "Get Smart" in state["message"] else "support"
    return {"intent": intent, "steps": ["router"], "tokens": 3}


def knowledge(state):
    return {"answer": "Get Smart has a touchscreen.", "steps": ["knowledge"], "tokens": 10,
            "evidence": [{"tool": "search_corpus", "content": "Get Smart: touchscreen"}]}


def support(state):
    return {"answer": f"Terminal of {state['user_id']} is offline.", "steps": ["support"], "tokens": 20}


def judge_model():
    return FakeJudgeModel(messages=itertools.cycle([verdict(1.0), verdict(0.5), coverage(["support", "knowledge"], False, "Wi-Fi steps", 0.4)]))


def run(tmp_path, graph=None, runs=2):
    path = run_eval(
        dataset(tmp_path),
        graph=graph or build_graph(router, knowledge, support),
        judge_model=judge_model(),
        runs=runs,
        out_dir=tmp_path / "results",
        reply_model="openai:reply",
        judge_model_name="openai:judge",
        now=NOW,
    )
    return path, json.loads(path.read_text())


def test_runner_writes_timestamped_results_file_with_metadata(tmp_path):
    path, results = run(tmp_path)

    assert path == tmp_path / "results" / "20261111T203005Z.json"
    meta = results["metadata"]
    assert meta["reply_model"] == "openai:reply"
    assert meta["judge_model"] == "openai:judge"
    assert meta["eval_runs"] == 2
    assert meta["date"] == "2026-11-11T20:30:05+00:00"
    assert len(meta["dataset_sha256"]) == 64
    assert isinstance(meta["commit"], str) and isinstance(meta["dirty"], bool)
    assert set(results) >= {"metadata", "runs", "per_scenario", "per_intent", "overall", "mixed", "labelled_mixed", "tokens"}


def test_runner_records_each_run_with_checks_and_verdicts(tmp_path):
    _, results = run(tmp_path)

    first = results["runs"][0]
    assert first["index"] == 1
    assert first["intent"] == "knowledge"
    assert first["routing_ok"] is True and first["facts_ok"] is True
    assert first["verdicts"]["route"]["score"] == 1.0
    assert first["verdicts"]["coverage"]["intents_needed"] == ["support", "knowledge"]
    assert first["error"] is None and isinstance(first["latency_ms"], int)
    [mixed] = [s for s in results["per_scenario"].values() if s["expected_intent"] == "support"]
    assert mixed["routing_pass_rate"] == 1.0
    assert results["labelled_mixed"]["agreement_rate"] == 1.0


def test_logged_in_scenarios_pass_user_id_into_graph_state(tmp_path):
    _, results = run(tmp_path, runs=1)

    assert results["runs"][1]["answer"] == "Terminal of cliente2024 is offline."


def test_eval_runs_respected(tmp_path):
    _, results = run(tmp_path, runs=3)

    assert [r["index"] for r in results["runs"]] == [1, 1, 1, 2, 2, 2]
    assert [r["run"] for r in results["runs"][:3]] == [1, 2, 3]


def test_token_totals_summed_from_graph_tokens(tmp_path):
    _, results = run(tmp_path, runs=2)

    assert [r["tokens"] for r in results["runs"]] == [13, 13, 23, 23]
    assert results["tokens"]["total"] == 72
    assert results["per_intent"]["support"]["tokens"] == 46


def test_failing_run_is_recorded_not_fatal(tmp_path):
    calls = itertools.count()

    def flaky_router(state):
        if next(calls) == 0:
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://llm.example"))
        return router(state)

    _, results = run(tmp_path, graph=build_graph(flaky_router, knowledge, support), runs=2)

    failed, ok = results["runs"][0], results["runs"][1]
    assert failed["error"] == "provider_unavailable"
    assert failed["routing_ok"] is False and failed["facts_ok"] is False and failed["verdicts"] == {}
    assert ok["error"] is None
    assert results["overall"]["errors"] == 1
    assert len(results["runs"]) == 4


def test_scenario_ids_survive_reordering_the_dataset(tmp_path):
    _, results = run(tmp_path, runs=1)
    path = tmp_path / "scenarios.json"
    data = json.loads(path.read_text())
    data["scenarios"].reverse()
    path.write_text(json.dumps(data))
    reordered = json.loads(
        run_eval(path, graph=build_graph(router, knowledge, support), judge_model=judge_model(), runs=1,
                 out_dir=tmp_path / "other", reply_model="r", judge_model_name="j", now=NOW).read_text()
    )

    ids = {r["message"]: r["scenario"] for r in results["runs"]}
    assert len(set(ids.values())) == 2
    assert {r["message"]: r["scenario"] for r in reordered["runs"]} == ids


def test_eval_runs_defaults_to_three_and_reads_env():
    assert eval_runs({}) == 3
    assert eval_runs({"EVAL_RUNS": "5"}) == 5
    with pytest.raises(ValueError):
        eval_runs({"EVAL_RUNS": "0"})


def test_summary_shows_intents_overall_threshold_and_tokens(tmp_path):
    _, results = run(tmp_path)

    summary = format_summary(results)

    assert "knowledge" in summary and "support" in summary and "overall" in summary
    assert "build multi-intent Router" in summary
    assert "72" in summary


# --- Baseline comparison ---


def results_of(records, **metadata):
    meta = {"reply_model": "openai:reply", "judge_model": "openai:judge", "dataset_sha256": "abc"} | metadata
    aggregates = aggregate(records)
    return {"metadata": meta, **aggregates, "tokens": {"total": aggregates["overall"]["tokens"]}}


def test_compare_reports_improvements_and_regressions():
    baseline = results_of([
        record(expected="knowledge", routing_ok=False, facts_ok=False, scores={"answer": 0.5}, tokens=100),
        record(expected="knowledge", routing_ok=True, facts_ok=True, scores={"answer": 0.7}, tokens=100),
    ])
    current = results_of([
        record(expected="knowledge", routing_ok=True, facts_ok=True, scores={"answer": 0.4}, tokens=150),
        record(expected="knowledge", routing_ok=True, facts_ok=True, scores={"answer": 0.4}, tokens=150),
    ])

    deltas = compare(current, baseline)

    knowledge = deltas["per_intent"]["knowledge"]
    assert knowledge["routing_pass_rate"] == pytest.approx(0.5)
    assert knowledge["fact_pass_rate"] == pytest.approx(0.5)
    assert knowledge["judges"]["answer"] == pytest.approx(-0.2)
    assert deltas["overall"]["judges"]["answer"] == pytest.approx(-0.2)
    assert deltas["tokens_per_run"] == 50


def test_compare_mixed_and_incomplete_rates():
    baseline = results_of([record(coverage=(["support"], True)), record(coverage=(["support", "knowledge"], True))])
    current = results_of([record(coverage=(["support", "knowledge"], False)), record(coverage=(["support", "knowledge"], True))])

    deltas = compare(current, baseline)

    assert deltas["mixed"]["mixed_rate"] == pytest.approx(0.5)
    assert deltas["mixed"]["incomplete_rate"] == pytest.approx(0.5)


def test_compare_tokens_per_run_so_run_counts_can_differ():
    baseline = results_of([record(tokens=100)] * 3)
    current = results_of([record(tokens=100)])

    assert compare(current, baseline)["tokens_per_run"] == 0


def test_compare_incomplete_rate_is_none_when_a_side_has_no_mixed_questions():
    baseline = results_of([record(coverage=(["support"], True))])
    current = results_of([record(coverage=(["support", "knowledge"], False))])

    deltas = compare(current, baseline)

    assert deltas["mixed"]["mixed_rate"] == 1.0
    assert deltas["mixed"]["incomplete_rate"] is None


def test_compare_marks_intents_and_judge_types_present_on_one_side_only():
    baseline = results_of([record(expected="knowledge", scores={"route": 1.0}), record(expected="support")])
    current = results_of([record(expected="knowledge", scores={"answer": 1.0}), record(expected="general")])

    deltas = compare(current, baseline)

    assert deltas["per_intent"]["general"] == {"only_in": "run"}
    assert deltas["per_intent"]["support"] == {"only_in": "baseline"}
    assert deltas["per_intent"]["knowledge"]["judges"] == {"route": None, "answer": None}


def test_compare_fact_rate_is_none_when_either_side_has_no_facts():
    deltas = compare(results_of([record(facts_ok=True)]), results_of([record(facts_ok=None)]))

    assert deltas["overall"]["fact_pass_rate"] is None


def test_comparison_shows_signed_deltas():
    baseline = results_of([record(routing_ok=False, scores={"answer": 0.5}, tokens=100)])
    current = results_of([record(routing_ok=True, scores={"answer": 0.3}, tokens=90)])

    text = format_comparison(current, baseline)

    assert "routing +100pp" in text
    assert "answer -0.20" in text
    assert "tokens/run -10" in text
    assert "not like-for-like" not in text


@pytest.mark.parametrize("field", ["judge_model", "reply_model", "dataset_sha256"])
def test_comparison_warns_when_baseline_differs_in_models_or_dataset(field):
    baseline = results_of([record()])
    current = results_of([record()], **{field: "other"})

    text = format_comparison(current, baseline)

    assert f"WARNING: {field} differs" in text
    assert "not like-for-like" in text


def test_comparison_without_baseline_prints_note():
    text = format_comparison(results_of([record()]), None)

    assert "no baseline" in text


def test_report_without_baseline_file_prints_summary_and_note(tmp_path):
    path, _ = run(tmp_path)

    text = report(path, baseline_path=tmp_path / "baseline.json")

    assert "overall" in text and "no baseline" in text
    assert not (tmp_path / "baseline.json").exists()


def test_report_compares_against_baseline_file(tmp_path):
    path, _ = run(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    text = report(path, baseline_path=baseline)

    assert "vs baseline" in text and "routing +0pp" in text


def test_save_baseline_copies_the_results_file(tmp_path):
    path, _ = run(tmp_path)
    baseline = tmp_path / "evals" / "baseline.json"

    text = report(path, baseline_path=baseline, save_baseline=True)

    assert baseline.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")
    assert "baseline saved" in text
