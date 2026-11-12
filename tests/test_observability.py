import json
import logging

import httpx
import openai
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.graph import build_graph
from app.judge import run_judges
from app.main import create_app
from app.observability import LogPrivacy
from tests.test_auth import auth
from tests.test_chat_api import knowledge, post, raising, route_to, support


def lines(caplog, event):
    out = []
    for rec in caplog.records:
        try:
            data = json.loads(rec.getMessage())
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("event") == event:
            out.append((rec.levelno, data))
    return out


class FakeJudgeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kw):
        return self


def verdict(score, reason="r"):
    return AIMessage(
        content="",
        tool_calls=[{"name": "Verdict", "args": {"score": score, "reason": reason}, "id": "c1", "type": "tool_call"}],
    )


def coverage(intents_needed, fully_answered, missing="", score=1.0, reason="r"):
    args = {"intents_needed": intents_needed, "fully_answered": fully_answered, "missing": missing, "score": score, "reason": reason}
    return AIMessage(content="", tool_calls=[{"name": "Coverage", "args": args, "id": "c2", "type": "tool_call"}])


def app_for(route_fn, **kw):
    return create_app(graph=build_graph(route_fn, knowledge, support), **{"auth": auth(), "judge_enabled": False, **kw})


def test_request_log_line_has_spec_fields(caplog):
    caplog.set_level(logging.INFO)
    body = post(TestClient(app_for(route_to("knowledge"))), message="x" * 600).json()

    [(_, line)] = lines(caplog, "request")
    assert line["trace_id"] == body["trace_id"]
    assert "user_id" not in line and len(line["user_ref"]) == 16
    assert line["message"] == "x" * 500
    assert line["intent"] == "knowledge"
    assert line["agent"] == "knowledge"
    assert line["tools"] == ["search_corpus"]
    assert line["tokens"] == 13
    assert isinstance(line["latency_ms"], int)
    assert line["outcome"] == "ok"


def test_request_log_line_on_provider_and_unexpected_errors(caplog):
    caplog.set_level(logging.INFO)
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://llm.example"))
    post(TestClient(app_for(raising(timeout))))
    post(TestClient(app_for(raising(RuntimeError("x")))))

    assert [line["outcome"] for _, line in lines(caplog, "request")] == ["provider_error", "error"]


def test_judges_not_run_when_disabled(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([]))  # any call would fail
    post(TestClient(app_for(route_to("knowledge"), judge_enabled=False, judge_model=model)))

    assert lines(caplog, "judge") == []


def test_judges_run_in_background_when_enabled(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.4, "not grounded"), coverage(["knowledge"], True)]))
    body = post(TestClient(app_for(route_to("knowledge"), judge_enabled=True, judge_model=model))).json()

    judged = lines(caplog, "judge")
    assert [(lvl, j["judge_type"], j["judge_score"]) for lvl, j in judged] == [
        (logging.INFO, "route", 0.9),
        (logging.WARNING, "answer", 0.4),
        (logging.INFO, "coverage", 1.0),
    ]
    assert all(j["trace_id"] == body["trace_id"] and j["intent"] == "knowledge" for _, j in judged)
    assert judged[1][1]["reason"] == "not grounded"


def test_judge_failure_is_logged_not_raised(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([AIMessage("no tool call"), verdict(0.8), coverage(["unsupported"], True)]))

    verdicts = run_judges(model, privacy=LogPrivacy(key=b"k"), trace_id="t1", message="hi", intent="unsupported", answer="Não posso.", sources=[], evidence=[])

    assert [j["judge_type"] for _, j in lines(caplog, "judge")] == ["answer", "coverage"]
    assert set(verdicts) == {"answer", "coverage"}
    assert any(r.levelno == logging.ERROR and "route" in r.getMessage() for r in caplog.records)


def test_route_judge_uses_the_routers_intent_policy():
    from app.judge import JUDGES
    from app.router import INTENT_POLICY

    (_, system), (_, human) = JUDGES["route"][1](
        message="What's the euro exchange rate today?", intent="knowledge", user_id="cliente1988"
    )

    assert INTENT_POLICY in system
    assert "cliente1988" in human


def test_request_log_line_when_index_is_not_ready(caplog):
    import threading

    caplog.set_level(logging.INFO)
    release = threading.Event()
    app = create_app(load_index=lambda: release.wait(5), auth=auth())
    with TestClient(app) as client:
        body = post(client).json()
        release.set()
        app.state.index_thread.join(5)

    [(_, line)] = lines(caplog, "request")
    assert line["trace_id"] == body["trace_id"]
    assert line["outcome"] == "starting"
    assert line["intent"] is None


def answer_prompt(evidence, intent="knowledge"):
    from app.judge import JUDGES

    (_, system), (_, human) = JUDGES["answer"][1](
        message="Pix cai na hora?", intent=intent, answer="Sim.", sources=[], evidence=evidence
    )
    return system, human


def test_answer_judge_rates_every_claim_against_the_evidence():
    system, human = answer_prompt([{"tool": "search_corpus", "content": "O Pix cai na hora."}])

    assert "every claim" in system.lower() and "evidence" in system.lower()
    assert "search_corpus" in human
    assert "O Pix cai na hora." in human


def test_answer_judge_evidence_is_cut_at_the_cap_with_a_marker():
    evidence = [
        {"tool": "search_corpus", "content": "A" * 4000},
        {"tool": "web_search", "content": "B" * 4000},
        {"tool": "web_search", "content": "C" * 100},
    ]
    _, human = answer_prompt(evidence)

    assert "A" * 4000 in human  # earlier items are kept whole
    assert 1500 < human.count("B") < 2000
    assert "C" * 100 not in human
    assert "[Evidence truncated" in human


def test_answer_judge_without_evidence_says_so():
    _, human = answer_prompt([], intent="unsupported")

    assert "Evidence: (none)" in human


class RecordingJudgeModel(FakeJudgeModel):
    seen: list = []

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def knowledge_with_evidence(state):
    return {
        **knowledge(state),
        "evidence": [{"tool": "search_corpus", "content": "Get Smart tem tela touchscreen."}],
    }


def test_evidence_reaches_the_answer_judge_but_not_the_chat_response():
    model = RecordingJudgeModel(messages=iter([verdict(0.9), verdict(0.9), coverage(["knowledge"], True)]), seen=[])
    graph = build_graph(route_to("knowledge"), knowledge_with_evidence, support)
    client = TestClient(create_app(graph=graph, judge_enabled=True, judge_model=model, auth=auth()))

    body = post(client).json()

    assert "evidence" not in body
    _route_call, answer_call, _coverage_call = model.seen
    assert "Get Smart tem tela touchscreen." in answer_call[-1].content


def judge_warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING and "JUDGE_MODEL" in r.getMessage()]


def start(app):
    with TestClient(app):
        pass


def test_startup_warns_when_judge_model_equals_llm_model(monkeypatch, caplog):
    from app.settings import get_settings

    monkeypatch.setenv("LLM_MODEL", "openai:same")
    monkeypatch.setenv("JUDGE_MODEL", "openai:same")
    get_settings.cache_clear()
    try:
        start(app_for(route_to("knowledge"), judge_enabled=True))
        warned_when_on = judge_warnings(caplog)
        caplog.clear()
        start(app_for(route_to("knowledge"), judge_enabled=False))
        start(app_for(route_to("knowledge"), judge_enabled=True, judge_model=FakeJudgeModel(messages=iter([]))))
    finally:
        get_settings.cache_clear()

    assert warned_when_on
    assert judge_warnings(caplog) == []  # Judges off, or Judge model injected


def judge_all(model, **kw):
    args = {"privacy": LogPrivacy(key=b"k"), "trace_id": "t1", "message": "Caixa 1 offline? E como configuro o Wi-Fi?",
            "intent": "support", "answer": "Caixa 1 está offline.", "sources": [], "evidence": []}
    return run_judges(model, **{**args, **kw})


def test_run_judges_returns_a_verdict_per_judge_type(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.8), coverage(["support", "knowledge"], False, "Wi-Fi setup steps", 0.5)]))

    verdicts = judge_all(model)

    assert list(verdicts) == ["route", "answer", "coverage"]
    assert [v.score for v in verdicts.values()] == [0.9, 0.8, 0.5]
    assert len(lines(caplog, "judge")) == 3


def test_coverage_verdict_is_parsed_logged_and_returned(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.9), coverage(["support", "knowledge"], False, "Wi-Fi setup steps", 0.5, "half answered")]))

    cov = judge_all(model)["coverage"]

    assert cov.intents_needed == ["support", "knowledge"]
    assert cov.fully_answered is False
    assert cov.missing == "Wi-Fi setup steps"
    [(level, line)] = [(lvl, j) for lvl, j in lines(caplog, "judge") if j["judge_type"] == "coverage"]
    assert level == logging.WARNING
    assert line["intents_needed"] == ["support", "knowledge"]
    assert line["fully_answered"] is False
    assert line["missing"] == "Wi-Fi setup steps"
    assert line["judge_score"] == 0.5 and line["reason"] == "half answered"


def test_fully_answered_coverage_scores_one_with_nothing_missing():
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.9), coverage(["support"], True, "leftover", 0.7)]))

    cov = judge_all(model)["coverage"]

    assert (cov.score, cov.missing) == (1.0, "")


def test_personal_data_in_coverage_missing_is_redacted(caplog):
    caplog.set_level(logging.INFO)
    missing = "status of card 4111 1111 1111 1111 for CPF 123.456.789-09"
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.9), coverage(["support"], False, missing, 0.3)]))

    judge_all(model)

    [line] = [j for _, j in lines(caplog, "judge") if j["judge_type"] == "coverage"]
    assert "4111 1111 1111 1111" not in line["missing"] and "123.456.789-09" not in line["missing"]


def test_coverage_judge_prompt_uses_the_intent_policy_and_sees_the_reply():
    from app.judge import JUDGES
    from app.router import INTENT_POLICY

    schema, build = JUDGES["coverage"]
    (_, system), (_, human) = build(message="m?", intent="support", answer="the reply", sources=[], evidence=[])

    assert schema.__name__ == "Coverage"
    assert INTENT_POLICY in system
    assert "the reply" in human and "Intent chosen: support" in human
