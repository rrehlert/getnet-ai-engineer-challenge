import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.store import Store
from tests.test_auth import CapturingGraph, bearer, login, make_app
from tests.test_observability import lines


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def client_with(store, graph=None):
    return TestClient(make_app(graph=graph or CapturingGraph(), store=store))


def chat(client, message="hi", conversation_id=None, user_id="cliente1988"):
    body = {"message": message}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/chat", json=body, headers=bearer(login(client, user_id)))


class SourcedGraph:
    def invoke(self, state):
        return {
            **state,
            "intent": "knowledge",
            "answer": f"re: {state['message']}",
            "sources": [{"url": "https://getnet.example/smart", "title": "Get Smart"}],
            "evidence": [{"tool": "search_corpus", "content": "raw chunk text"}],
            "steps": ["router", "knowledge", "search_corpus"],
        }


def test_first_message_starts_a_conversation_owned_by_the_merchant_and_returns_its_id(store):
    response = chat(client_with(store, SourcedGraph()), "minha maquininha está offline")

    assert response.status_code == 200
    cid = response.json()["conversation_id"]
    conversation = store.conversation(cid, "cliente1988")
    assert conversation is not None and conversation.mode == "bot"
    turns = store.turns(cid)
    assert [(t.role, t.content, t.intent) for t in turns] == [
        ("user", "minha maquininha está offline", "knowledge"),
        ("assistant", "re: minha maquininha está offline", "knowledge"),
    ]
    assert turns[1].sources == [{"url": "https://getnet.example/smart", "title": "Get Smart"}]


def test_evidence_and_raw_tool_output_are_not_stored(store, tmp_path):
    chat(client_with(store, SourcedGraph()))

    assert b"raw chunk text" not in (tmp_path / "conversations.db").read_bytes()
    wal = tmp_path / "conversations.db-wal"
    assert not wal.exists() or b"raw chunk text" not in wal.read_bytes()


def test_follow_up_with_the_id_appends_to_the_same_conversation(store):
    client = client_with(store, SourcedGraph())
    cid = chat(client, "minha maquininha está offline").json()["conversation_id"]

    response = chat(client, "é a Smart", conversation_id=cid)

    assert response.status_code == 200
    assert response.json()["conversation_id"] == cid
    assert [t.content for t in store.turns(cid)] == [
        "minha maquininha está offline",
        "re: minha maquininha está offline",
        "é a Smart",
        "re: é a Smart",
    ]


def test_each_message_without_an_id_starts_a_new_conversation(store):
    client = client_with(store)

    assert chat(client).json()["conversation_id"] != chat(client).json()["conversation_id"]


def test_another_merchants_conversation_and_an_unknown_id_are_the_same_404(store):
    graph = CapturingGraph()
    client = client_with(store, graph)
    theirs = chat(client, user_id="cliente2024").json()["conversation_id"]
    graph.states.clear()

    other = chat(client, conversation_id=theirs)
    unknown = chat(client, conversation_id=str(uuid.uuid4()))

    assert other.status_code == unknown.status_code == 404
    assert other.json()["error"] == unknown.json()["error"]
    assert other.json()["error"]["code"] == "conversation_not_found"
    assert graph.states == []
    assert len(store.turns(theirs)) == 2


class FailingGraph:
    def invoke(self, state):
        raise RuntimeError("boom")


def test_failed_graph_run_stores_nothing(store, tmp_path):
    client = client_with(store, SourcedGraph())
    cid = chat(client).json()["conversation_id"]
    failing = client_with(store, FailingGraph())

    assert chat(failing, conversation_id=cid).status_code == 500
    assert chat(failing).status_code == 500

    assert len(store.turns(cid)) == 2
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(tmp_path / "conversations.db")) as conn:
        assert conn.execute("SELECT count(*) FROM conversations").fetchone()[0] == 1


def test_request_log_line_carries_the_conversation_id(store, caplog):
    client = client_with(store)
    caplog.set_level(logging.INFO)

    cid = chat(client).json()["conversation_id"]
    unknown = str(uuid.uuid4())
    chat(client, conversation_id=unknown)
    chat(client, conversation_id="cliente1988@example.com")

    [(_, ok), (_, missing), (_, junk)] = lines(caplog, "request")
    assert ok["conversation_id"] == cid and ok["outcome"] == "ok"
    assert missing["conversation_id"] == unknown and missing["outcome"] == "conversation_not_found"
    assert junk["conversation_id"] is None and junk["outcome"] == "conversation_not_found"


def test_anonymous_message_is_answered_but_nothing_is_stored(store, tmp_path):
    import sqlite3
    from contextlib import closing

    client = client_with(store, SourcedGraph())

    response = client.post("/chat", json={"message": "What is Get Smart?"})

    assert response.status_code == 200
    assert response.json()["conversation_id"] is None
    with closing(sqlite3.connect(tmp_path / "conversations.db")) as conn:
        assert conn.execute("SELECT count(*) FROM conversations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM turns").fetchone()[0] == 0
