"""Events ring buffer (demo-clients 04): recent redacted log lines of a Conversation's traces, for Operators."""

import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.observability import EVENTS, EventBuffer, JsonFormatter, LogPrivacy, emit, log_request, setup_logging
from app.store import Store
from tests.test_auth import bearer, login, make_app
from tests.test_operator import as_operator, escalated
from tests.test_review_flag import chat, judge_model, judged_app

PRIVACY = LogPrivacy(key=b"k")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


@pytest.fixture
def buffer():
    """A fresh buffer on the `app` logger, removed afterwards (the production `EVENTS` is shared)."""
    app_log = logging.getLogger("app")
    level = app_log.level
    buf = EventBuffer()
    app_log.addHandler(buf)
    app_log.setLevel(logging.INFO)
    yield buf
    app_log.removeHandler(buf)
    app_log.setLevel(level)


def request_event(conversation_id, trace_id=None, message="oi"):
    trace_id = trace_id or uuid.uuid4().hex
    log_request(privacy=PRIVACY, trace_id=trace_id, user_id="cliente1988", message=message, latency_ms=12,
                outcome="ok", result={"intent": "knowledge", "steps": ["router", "knowledge"]},
                conversation_id=conversation_id)
    return trace_id


def judge_event(trace_id, score=0.9):
    emit("judge", trace_id=trace_id, judge_type="answer", judge_score=score, intent="knowledge", reason="r")


def get_events(client, conversation_id, headers):
    return client.get(f"/operator/conversations/{conversation_id}/events", headers=headers)


# Role and visibility


def test_events_need_a_token_and_the_operator_role(store, buffer):
    client = TestClient(make_app(store=store, events=buffer))
    cid = escalated(store)

    assert get_events(client, cid, {}).status_code == 401
    as_merchant = get_events(client, cid, bearer(login(client, "cliente1988")))
    assert as_merchant.status_code == 403
    assert as_merchant.json()["error"]["code"] == "forbidden"


def test_events_of_a_conversation_operators_may_not_see_are_404(store, buffer):
    client = TestClient(make_app(store=store, events=buffer))
    hidden = store.create_conversation("cliente1988")  # bot, never escalated, no Review flag
    request_event(hidden)

    for cid in (hidden, str(uuid.uuid4())):
        response = get_events(client, cid, as_operator(client))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"


# Content


def test_events_are_this_conversations_traces_oldest_first_with_later_judge_events(store, buffer):
    client = TestClient(make_app(store=store, events=buffer))
    cid, other = escalated(store), escalated(store, owner="cliente2024")
    first = request_event(cid)
    other_trace = request_event(other)
    emit("judge", trace_id=uuid.uuid4().hex, judge_type="route", judge_score=1.0)  # a trace of no request here
    logging.getLogger("app.test").info("unrelated plain log line")
    second = request_event(cid)
    judge_event(other_trace)
    judge_event(first, score=0.4)  # the Judge runs after the reply: logged after the next request

    events = get_events(client, cid, as_operator(client)).json()["events"]

    assert [(e["event"], e["trace_id"]) for e in events] == [("request", first), ("request", second), ("judge", first)]
    assert all(e.get("conversation_id") in (cid, None) for e in events)
    assert events[2]["judge_score"] == 0.4 and events[2]["level"] == "INFO"
    assert events[0]["intent"] == "knowledge" and events[0]["latency_ms"] == 12
    assert all(e["time"].endswith("+00:00") for e in events)


def test_events_through_chat_include_the_background_judges(store, buffer):
    # A low `answer` score sets the Review flag, which makes the Conversation visible to Operators.
    client = TestClient(judged_app(store, "knowledge", judge_model(answer=0.3)))
    other = TestClient(judged_app(store, "knowledge", judge_model()))
    cid = chat(client, "qual a taxa?", token=login(client)).json()["conversation_id"]
    chat(other, "outra conversa", token=login(other, "cliente2024"))
    operator = TestClient(make_app(store=store, events=buffer))

    events = get_events(operator, cid, as_operator(operator)).json()["events"]

    assert [e["event"] for e in events] == ["request", "judge", "judge", "judge"]
    assert events[0]["conversation_id"] == cid
    assert len({e["trace_id"] for e in events}) == 1
    assert [e["judge_type"] for e in events[1:]] == ["route", "answer", "coverage"]


def test_no_events_when_none_are_buffered(store, buffer):
    client = TestClient(make_app(store=store, events=buffer))

    assert get_events(client, escalated(store), as_operator(client)).json() == {"events": []}


# The buffer


def test_buffer_is_bounded_and_drops_the_oldest():
    buf = EventBuffer(capacity=3)
    log = logging.getLogger("app.bounded")
    log.addHandler(buf)
    log.setLevel(logging.INFO)
    try:
        for i in range(5):
            log.info(json.dumps({"event": "x", "n": i}))
    finally:
        log.removeHandler(buf)

    assert [e["n"] for e in buf.events()] == [2, 3, 4]


def test_old_request_dropped_means_its_trace_is_no_longer_found(store):
    buf = EventBuffer(capacity=2)
    app_log = logging.getLogger("app")
    app_log.addHandler(buf)
    try:
        cid = escalated(store)
        trace = request_event(cid)
        judge_event(trace)
        judge_event(trace)  # pushes the request out
    finally:
        app_log.removeHandler(buf)

    assert buf.for_conversation(cid) == []


def test_buffer_holds_exactly_what_stdout_gets_redacted(buffer, caplog):
    caplog.set_level(logging.INFO)
    cid = str(uuid.uuid4())
    trace = request_event(cid, message="meu email é ana@example.com, CPF 123.456.789-09")
    emit("judge", trace_id=trace, reason="contato ana@example.com", judge_type="answer", judge_score=0.9)
    logging.getLogger("app.test").warning("failed for ana@example.com")

    stdout = [json.loads(JsonFormatter().format(r)) for r in caplog.records if r.name.startswith("app")]

    assert buffer.events() == stdout
    text = json.dumps(buffer.events(), ensure_ascii=False)
    assert "ana@example.com" not in text and "123.456.789-09" not in text
    assert "[EMAIL]" in text and "[CPF]" in text
    assert buffer.events()[0]["conversation_id"] == cid  # canonical UUIDs are kept, not masked


def test_setup_logging_installs_the_shared_buffer_once():
    setup_logging()
    setup_logging()

    handlers = logging.getLogger("app").handlers
    assert handlers.count(EVENTS) == 1
    assert sum(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonFormatter) for h in handlers) == 1
