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


def app_for(route_fn, **kw):
    return create_app(graph=build_graph(route_fn, knowledge, support), **kw)


def test_request_log_line_has_spec_fields(caplog):
    caplog.set_level(logging.INFO)
    body = post(TestClient(app_for(route_to("knowledge"))), message="x" * 600).json()

    [(_, line)] = lines(caplog, "request")
    assert line["trace_id"] == body["trace_id"]
    assert line["user_id"] == "cliente1988"
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
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.4, "not grounded")]))
    body = post(TestClient(app_for(route_to("knowledge"), judge_enabled=True, judge_model=model))).json()

    judged = lines(caplog, "judge")
    assert [(lvl, j["judge_type"], j["judge_score"]) for lvl, j in judged] == [
        (logging.INFO, "route", 0.9),
        (logging.WARNING, "answer", 0.4),
    ]
    assert all(j["trace_id"] == body["trace_id"] and j["intent"] == "knowledge" for _, j in judged)
    assert judged[1][1]["reason"] == "not grounded"


def test_judge_failure_is_logged_not_raised(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([AIMessage("no tool call"), verdict(0.8)]))

    run_judges(model, trace_id="t1", message="hi", intent="unsupported", answer="Não posso.", sources=[])

    assert [j["judge_type"] for _, j in lines(caplog, "judge")] == ["answer"]
    assert any(r.levelno == logging.ERROR and "route" in r.getMessage() for r in caplog.records)


def test_route_judge_uses_the_routers_intent_policy():
    from app.judge import JUDGES
    from app.router import INTENT_POLICY

    (_, system), (_, human) = JUDGES["route"](
        message="What's the euro exchange rate today?", intent="knowledge", user_id="cliente1988"
    )

    assert INTENT_POLICY in system
    assert "cliente1988" in human


def test_request_log_line_when_index_is_not_ready(caplog):
    import threading

    caplog.set_level(logging.INFO)
    release = threading.Event()
    app = create_app(load_index=lambda: release.wait(5))
    with TestClient(app) as client:
        body = post(client).json()
        release.set()
        app.state.index_thread.join(5)

    [(_, line)] = lines(caplog, "request")
    assert line["trace_id"] == body["trace_id"]
    assert line["outcome"] == "starting"
    assert line["intent"] is None
