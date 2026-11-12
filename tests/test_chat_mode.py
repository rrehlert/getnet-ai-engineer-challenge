"""`/chat` by Mode (ADR 0006): only `bot` runs the graph."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.store import Store
from tests.test_auth import CapturingGraph, bearer, login, make_app
from tests.test_conversations import chat, client_with
from tests.test_observability import FakeJudgeModel, lines


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def test_bot_mode_runs_the_graph_and_the_response_says_bot(store):
    graph = CapturingGraph()

    response = chat(client_with(store, graph))

    assert response.status_code == 200
    assert response.json()["mode"] == "bot"
    assert response.json()["intent"] == "support" and response.json()["agent"] == "support"
    assert len(graph.states) == 1


class NeverInvokedGraph:
    def invoke(self, state):
        raise AssertionError("the graph must not run outside bot Mode")


def conversation_in(store, mode, user_id="cliente1988"):
    cid = chat(client_with(store), "minha maquininha está offline", user_id=user_id).json()["conversation_id"]
    store.set_mode(cid, mode)
    return cid


@pytest.mark.parametrize("mode", ["waiting_human", "human"])
def test_waiting_or_human_mode_keeps_the_message_for_the_operator_without_running_the_graph(store, mode):
    cid = conversation_in(store, mode)

    response = chat(client_with(store, NeverInvokedGraph()), "ainda estou esperando", conversation_id=cid)

    assert response.status_code == 200
    body = response.json()
    assert (body["answer"], body["mode"], body["intent"], body["agent"]) == ("", mode, None, None)
    assert (body["sources"], body["steps"], body["conversation_id"]) == ([], [], cid)
    last = store.turns(cid)[-1]
    assert (last.role, last.content, last.intent) == ("user", "ainda estou esperando", None)
    assert len(store.turns(cid)) == 3


def test_closed_conversation_refuses_new_messages_and_stores_nothing(store):
    cid = conversation_in(store, "closed")

    response = chat(client_with(store, NeverInvokedGraph()), "olá?", conversation_id=cid)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_closed"
    assert response.json()["trace_id"]
    assert len(store.turns(cid)) == 2


@pytest.mark.parametrize("mode", ["bot", "waiting_human", "human", "closed"])
def test_turns_listing_carries_the_conversations_mode(store, mode):
    cid = conversation_in(store, mode)
    client = client_with(store)

    response = client.get(f"/conversations/{cid}/turns", headers=bearer(login(client)))

    assert response.status_code == 200
    assert response.json()["mode"] == mode


def test_queued_message_is_logged_redacted_with_outcome_queued_and_no_judge_runs(store, caplog):
    cid = conversation_in(store, "waiting_human")
    judge_model = FakeJudgeModel(messages=iter([]))  # any Judge call would fail
    client = TestClient(make_app(graph=NeverInvokedGraph(), store=store, judge_enabled=True, judge_model=judge_model))
    caplog.set_level(logging.INFO)
    caplog.clear()

    body = chat(client, "meu CPF é 123.456.789-09", conversation_id=cid).json()

    [(_, line)] = lines(caplog, "request")
    assert line["outcome"] == "queued" and line["trace_id"] == body["trace_id"]
    assert line["conversation_id"] == cid
    assert "123.456.789-09" not in line["message"] and "[CPF]" in line["message"]
    assert line["intent"] is None and line["agent"] is None and line["tools"] == []
    assert lines(caplog, "judge") == []


def test_anonymous_message_is_answered_by_the_graph_as_before(store):
    graph = CapturingGraph()

    response = client_with(store, graph).post("/chat", json={"message": "O que é a Get Smart?"})

    assert response.status_code == 200
    body = response.json()
    assert (body["mode"], body["intent"], body["agent"], body["conversation_id"]) == ("bot", "support", "router", None)
    assert len(graph.states) == 1


@pytest.mark.parametrize("mode", ["waiting_human", "closed"])
def test_another_merchants_taken_over_or_closed_conversation_is_still_404(store, mode):
    theirs = conversation_in(store, mode, user_id="cliente2024")

    response = chat(client_with(store, NeverInvokedGraph()), "olá", conversation_id=theirs)

    assert response.status_code == 404
    assert len(store.turns(theirs)) == 2
