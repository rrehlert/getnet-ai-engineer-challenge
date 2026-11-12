"""Operator side of the takeover (ADR 0006): queue, read, claim."""

import pytest
from fastapi.testclient import TestClient

from app.store import NewTurn, Store
from tests.test_auth import bearer, login, make_app
from tests.test_escalation import BRIEF

OPERATOR = "operador1"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def client_for(store, **kw):
    return TestClient(make_app(store=store, **kw))


def as_operator(client, user_id=OPERATOR):
    return bearer(login(client, user_id))


def escalated(store, owner="cliente1988", message="quero falar com uma pessoa", brief=BRIEF):
    """A Conversation that went through an Escalation: waiting for an Operator."""
    return store.escalate(None, owner, [NewTurn("user", message, intent="human"),
                                        NewTurn("assistant", "Vou transferir você.", intent="human")], brief)


# Role enforcement


@pytest.mark.parametrize(("method", "path"), [
    ("get", "/operator/queue"),
    ("get", "/operator/mine"),
    ("get", "/operator/conversations/some-id"),
    ("post", "/operator/conversations/some-id/claim"),
])
def test_operator_endpoints_need_a_token_and_the_operator_role(store, method, path):
    client = client_for(store)

    anonymous = client.request(method.upper(), path)
    as_merchant = client.request(method.upper(), path, headers=bearer(login(client, "cliente1988")))

    assert anonymous.status_code == 401
    assert as_merchant.status_code == 403
    assert as_merchant.json()["error"]["code"] == "forbidden"


# Queue


def test_queue_lists_waiting_conversations_newest_first_with_the_brief_fields(tmp_path):
    from datetime import datetime, timedelta

    from tests.test_store import T0, Clock

    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    clock.now = T0 - timedelta(minutes=5)
    chargeback = {**BRIEF, "customer_ask": "Contestar um chargeback", "category": "transaction", "priority": "normal"}
    newer = escalated(store, owner="cliente2024", brief=chargeback)
    clock.now = T0 - timedelta(minutes=10)
    oldest = escalated(store)
    clock.now = T0 - timedelta(minutes=1)
    claimed = escalated(store)
    store.set_mode(claimed, "human")
    store.create_conversation("cliente1988")  # bot, never escalated
    clock.now = T0
    client = client_for(store)

    response = client.get("/operator/queue", headers=as_operator(client))

    assert response.status_code == 200
    items = response.json()["conversations"]
    assert [i["conversation_id"] for i in items] == [newer, oldest]
    assert [datetime.fromisoformat(i["created_at"]) for i in items] == [T0 - timedelta(minutes=5), T0 - timedelta(minutes=10)]
    assert [(i["category"], i["priority"], i["customer_ask"]) for i in items] == [
        ("transaction", "normal", "Contestar um chargeback"),
        ("terminal", "high", BRIEF["customer_ask"]),
    ]


# Detail and visibility


def test_operators_cannot_see_a_conversation_that_never_had_a_handoff(store):
    from tests.test_conversations import chat, client_with

    private = chat(client_with(store), "minhas vendas de ontem").json()["conversation_id"]
    client = client_for(store)

    for cid in (private, "no-such-id"):
        response = client.get(f"/operator/conversations/{cid}", headers=as_operator(client))
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "conversation_not_found"
        claim = client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))
        assert claim.status_code == 404
    assert store.conversation(private, "cliente1988").mode == "bot"


def test_detail_shows_every_turn_the_brief_the_mode_and_the_merchants_account_from_the_fixture(store):
    cid = escalated(store)
    store.append_turns(cid, [NewTurn("user", "a maquininha T-1 ainda não liga")])  # sent while waiting
    client = client_for(store)

    response = client.get(f"/operator/conversations/{cid}", headers=as_operator(client))

    assert response.status_code == 200
    body = response.json()
    assert (body["conversation_id"], body["merchant"], body["mode"]) == (cid, "cliente1988", "waiting_human")
    assert [(t["role"], t["content"]) for t in body["turns"]] == [
        ("user", "quero falar com uma pessoa"),
        ("assistant", "Vou transferir você."),
        ("user", "a maquininha T-1 ainda não liga"),
    ]
    assert body["handoff"]["brief"] == BRIEF
    assert (body["handoff"]["claimed_by"], body["handoff"]["claimed_at"]) == (None, None)
    assert body["needs_review"] is False
    # Software resolves the account (data/merchants.json), never the model.
    assert body["account"]["profile"]["business_name"] == "Padaria Pão Dourado"
    assert body["account"]["profile"]["bank_account"] == "Banco Santander, agência 0123, conta ****4521-7"


def test_detail_account_is_null_for_a_merchant_missing_from_the_fixture(store):
    cid = escalated(store, owner="cliente9999")
    client = client_for(store)

    body = client.get(f"/operator/conversations/{cid}", headers=as_operator(client)).json()

    assert body["merchant"] == "cliente9999" and body["account"] is None


def test_a_database_file_from_before_the_operator_columns_still_opens(tmp_path):
    import sqlite3
    from contextlib import closing

    path = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(
            "CREATE TABLE conversations (id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL,"
            " updated_at TEXT NOT NULL, mode TEXT NOT NULL DEFAULT 'bot');"
            "CREATE TABLE handoffs (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,"
            " brief TEXT NOT NULL, created_at TEXT NOT NULL, claimed_by TEXT, claimed_at TEXT, outcome TEXT, ended_at TEXT);"
        )

    store = Store(path)
    cid = escalated(store)

    assert store.operator_conversation(cid).needs_review is False
    assert store.claim(cid, OPERATOR) is True


# Brief refresh on claim

FRESH_BRIEF = {**BRIEF, "summary": "Maquininha T-1 não liga; Merchant escreveu de novo enquanto esperava."}


class SpyEscalator:
    """Stands in for the Escalator Agent on claim: records the state, returns `FRESH_BRIEF` (or raises)."""

    def __init__(self, error=None):
        self.states, self.error = [], error

    def __call__(self, state):
        self.states.append(state)
        if self.error is not None:
            raise self.error
        return {"answer": "ignored transfer message", "handoff": FRESH_BRIEF, "steps": ["escalator"], "tokens": 5}


def claim(client, cid):
    return client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))


def test_claim_keeps_the_brief_when_the_merchant_wrote_nothing_since(store):
    escalator = SpyEscalator()
    cid = escalated(store)

    body = claim(client_for(store, escalator=escalator), cid).json()

    assert escalator.states == []
    assert body["handoff"]["brief"] == BRIEF


def test_claim_rewrites_the_brief_when_the_merchant_wrote_while_waiting(store):
    escalator = SpyEscalator()
    cid = escalated(store)
    store.append_turns(cid, [NewTurn("user", "a maquininha T-1 ainda não liga")])

    body = claim(client_for(store, escalator=escalator), cid).json()

    [state] = escalator.states
    assert state["message"] == "a maquininha T-1 ainda não liga"
    assert [t["content"] for t in state["history"]] == ["quero falar com uma pessoa", "Vou transferir você."]
    assert state["user_id"] == "cliente1988"
    assert state["intent"] == "human"
    assert state["escalation_reason"] == BRIEF["reason"]
    assert body["mode"] == "human"
    assert body["handoff"]["brief"] == FRESH_BRIEF
    assert store.handoffs(cid)[0].brief == FRESH_BRIEF
    # The transfer message is not used: nothing is said to the Merchant on claim.
    assert [t.content for t in store.turns(cid)][-1] == "a maquininha T-1 ainda não liga"


def test_a_rewritten_brief_is_not_rewritten_again_without_new_turns(store):
    cid = escalated(store)
    store.append_turns(cid, [NewTurn("user", "ainda aqui")])
    first = SpyEscalator()
    claim(client_for(store, escalator=first), cid)
    store.set_mode(cid, "waiting_human")  # back in the queue, nothing new written
    second = SpyEscalator()

    claim(client_for(store, escalator=second), cid)

    assert len(first.states) == 1 and second.states == []


def test_a_failing_brief_rewrite_keeps_the_old_brief_and_the_claim_succeeds(store, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    escalator = SpyEscalator(error=RuntimeError("provider down: a maquininha T-1 ainda não liga"))
    cid = escalated(store)
    store.append_turns(cid, [NewTurn("user", "a maquininha T-1 ainda não liga")])

    response = claim(client_for(store, escalator=escalator), cid)

    assert response.status_code == 200
    assert response.json()["mode"] == "human"
    assert response.json()["handoff"]["brief"] == BRIEF
    assert store.handoffs(cid)[0].claimed_by == OPERATOR
    assert "brief" in caplog.text and cid in caplog.text
    assert "a maquininha T-1" not in caplog.text and BRIEF["summary"] not in caplog.text


def test_an_unparseable_brief_rewrite_keeps_the_old_brief(store):
    from app.graph import fallback_escalator

    cid = escalated(store)
    store.append_turns(cid, [NewTurn("user", "ainda aqui")])

    body = claim(client_for(store, escalator=fallback_escalator), cid).json()

    assert body["handoff"]["brief"] == BRIEF


# Mine


def test_mine_lists_only_my_claimed_human_conversations_newest_claim_first(tmp_path):
    from datetime import datetime, timedelta

    from tests.test_store import T0, Clock

    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    chargeback = {**BRIEF, "customer_ask": "Contestar um chargeback", "category": "transaction", "priority": "normal"}
    clock.now = T0 - timedelta(minutes=30)
    first = escalated(store, owner="cliente2024", brief=chargeback)  # escalated first, claimed last
    second = escalated(store)
    others = escalated(store)
    waiting = escalated(store)
    handed_back = escalated(store)
    closed = escalated(store)
    clock.now = T0 - timedelta(minutes=20)
    store.claim(second, OPERATOR)
    store.claim(others, "operador2")
    store.claim(handed_back, OPERATOR)
    store.claim(closed, OPERATOR)
    store.hand_back(handed_back, OPERATOR, NewTurn("assistant", "back"))
    store.close(closed, OPERATOR, NewTurn("assistant", "closed"))
    clock.now = T0 - timedelta(minutes=10)
    store.claim(first, OPERATOR)
    clock.now = T0
    client = client_for(store)

    response = client.get("/operator/mine", headers=as_operator(client))

    assert response.status_code == 200
    items = response.json()["conversations"]
    assert [i["conversation_id"] for i in items] == [first, second]
    assert waiting not in [i["conversation_id"] for i in items]
    assert [datetime.fromisoformat(i["claimed_at"]) for i in items] == [T0 - timedelta(minutes=10), T0 - timedelta(minutes=20)]
    assert [datetime.fromisoformat(i["created_at"]) for i in items] == [T0 - timedelta(minutes=30)] * 2
    assert (items[0]["category"], items[0]["priority"], items[0]["customer_ask"]) == (
        "transaction", "normal", "Contestar um chargeback")
    other = client.get("/operator/mine", headers=as_operator(client, "operador2")).json()["conversations"]
    assert [i["conversation_id"] for i in other] == [others]


def test_mine_is_empty_after_a_claim_is_handed_back_and_the_conversation_escalates_again(store):
    cid = escalated(store)
    store.claim(cid, OPERATOR)
    store.hand_back(cid, OPERATOR, NewTurn("assistant", "back"))
    store.escalate(cid, "cliente1988", [NewTurn("user", "pessoa de novo", intent="human")], BRIEF)
    client = client_for(store)

    assert client.get("/operator/mine", headers=as_operator(client)).json()["conversations"] == []


# Claim


def test_claim_moves_the_conversation_to_human_and_records_the_operator(store):
    cid = escalated(store)
    client = client_for(store)

    response = client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "human"
    assert body["handoff"]["claimed_by"] == OPERATOR and body["handoff"]["claimed_at"] is not None
    assert body["handoff"]["brief"] == BRIEF
    assert store.conversation(cid, "cliente1988").mode == "human"
    assert client.get("/operator/queue", headers=as_operator(client)).json()["conversations"] == []
    [entry] = store.audit_log(cid)
    assert (entry.operator, entry.action, entry.conversation_id, entry.used_suggestion) == (OPERATOR, "claim", cid, None)
    assert entry.created_at is not None


def test_a_second_claim_fails_with_409_and_keeps_the_first_operator(store):
    cid = escalated(store)
    client = client_for(store)
    client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))

    again = client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "not_waiting"
    [handoff] = store.handoffs(cid)
    assert handoff.claimed_by == OPERATOR
    assert [e.action for e in store.audit_log(cid)] == ["claim"]


@pytest.mark.parametrize("mode", ["bot", "closed"])
def test_claim_of_a_conversation_not_waiting_fails_with_409(store, mode):
    cid = escalated(store)
    store.set_mode(cid, mode)  # e.g. handed back or closed; still visible (it had a Handoff)
    client = client_for(store)

    response = client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))

    assert response.status_code == 409
    assert store.conversation(cid, "cliente1988").mode == mode
    assert store.audit_log(cid) == []


def test_audit_row_holds_no_message_text_or_brief_content(store):
    import sqlite3
    from contextlib import closing

    cid = escalated(store)
    client = client_for(store)
    client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client))

    with closing(sqlite3.connect(store.path)) as conn:
        rows = conn.execute("SELECT * FROM audit").fetchall()
    dumped = repr(rows)
    assert len(rows) == 1
    for text in ("quero falar com uma pessoa", "Vou transferir", *BRIEF.values()):
        assert text not in dumped


def test_retention_purge_keeps_audit_rows(tmp_path):
    from datetime import timedelta

    from tests.test_store import T0, Clock

    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    clock.now = T0 - timedelta(days=31)
    cid = escalated(store)
    assert store.claim(cid, OPERATOR) is True
    clock.now = T0

    assert store.purge(timedelta(days=30)) == 1

    assert store.handoffs(cid) == []
    assert [(e.action, e.conversation_id) for e in store.audit_log(cid)] == [("claim", cid)]
