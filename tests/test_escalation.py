"""Escalation (ADR 0006): the Merchant asks for a person → Escalator Agent → `waiting_human`."""

import logging
import sqlite3
from contextlib import closing

import pytest

from app.graph import build_graph
from app.store import ModeChanged, NewTurn, Store
from tests.test_chat_mode import NeverInvokedGraph
from tests.test_conversations import chat, client_with
from tests.test_graph import fake_route, fake_specialist
from tests.test_observability import lines

BRIEF = {
    "reason": "The Merchant asked to talk to a person.",
    "customer_ask": "Falar com um atendente sobre a maquininha offline",
    "summary": "Maquininha offline desde ontem; o Merchant pediu um humano.",
    "attempted": "Nada ainda.",
    "category": "terminal",
    "priority": "high",
    "suggested_reply": "Olá! Vou verificar sua maquininha agora.",
    "language": "pt-BR",
}
TRANSFER = "Certo, vou transferir você para um atendente."


class SpyEscalator:
    def __init__(self):
        self.states = []

    def __call__(self, state):
        self.states.append(state)
        return {"answer": TRANSFER, "handoff": BRIEF, "steps": ["escalator"], "tokens": 3}


def run(route_fn, escalator, user_id="cliente1988", knowledge=None, support=None):
    graph = build_graph(
        route_fn, knowledge or fake_specialist("knowledge"), support or fake_specialist("support"), escalator=escalator
    )
    return graph.invoke({"message": "quero falar com uma pessoa", "user_id": user_id})


# Graph


def test_merchant_human_intent_goes_to_the_escalator():
    escalator = SpyEscalator()

    result = run(fake_route("human"), escalator)

    assert result["intent"] == "human"
    assert (result["answer"], result["handoff"]) == (TRANSFER, BRIEF)
    assert result["steps"] == ["router", "escalator"]
    assert escalator.states[0]["message"] == "quero falar com uma pessoa"


def test_anonymous_human_intent_gets_the_login_reply_and_no_escalation():
    from app.graph import LOGIN_REPLY

    escalator = SpyEscalator()

    result = run(fake_route("human"), escalator, user_id=None)

    assert result["answer"] == LOGIN_REPLY
    assert result["steps"] == ["router", "login"]
    assert "handoff" not in result
    assert escalator.states == []


def test_login_reply_covers_account_data_and_talking_to_an_agent_in_both_languages():
    from app.graph import LOGIN_REPLY

    assert "faça login" in LOGIN_REPLY and "log in" in LOGIN_REPLY
    assert "atendente" in LOGIN_REPLY and "agent" in LOGIN_REPLY
    assert "Getnet" in LOGIN_REPLY


def test_a_specialist_that_sets_an_escalation_reason_hands_over_to_the_escalator():
    """The seam ticket 05 plugs into: a specialist returns `escalation_reason`, the graph routes on."""
    escalator = SpyEscalator()

    def escalating_support(state):
        return {"answer": "", "escalation_reason": "chargeback dispute needs a human", "steps": ["support"]}

    result = run(fake_route("support"), escalator, support=escalating_support)

    assert result["intent"] == "support"
    assert result["steps"] == ["router", "support", "escalator"]
    assert escalator.states[0]["escalation_reason"] == "chargeback dispute needs a human"
    assert result["answer"] == TRANSFER


def test_intent_policy_and_router_prompts_cover_asking_for_a_person():
    from app.router import INTENT_POLICY, system_prompt

    assert "- human:" in INTENT_POLICY
    for user_id in ("cliente1988", None):
        assert "- human:" in system_prompt(user_id)
    assert "human" in system_prompt(None).split("not logged in", 1)[1]


def test_agent_for_names_the_escalator_for_an_escalated_turn():
    from app.graph import agent_for

    assert agent_for("human", escalated=True) == "escalator"
    assert agent_for("support", escalated=True) == "escalator"
    assert agent_for("human", anonymous=True) == "router"
    assert agent_for("support", anonymous=True) == "router"


# Escalator Agent


class FakeStructuredModel:
    """Stands in for `with_structured_output(Escalation, include_raw=True, method="function_calling")`."""

    def __init__(self, parsed=None, parsing_error=None, tokens=0):
        from langchain_core.messages import AIMessage

        usage = {"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens}
        self.output = {"raw": AIMessage(content="", usage_metadata=usage), "parsed": parsed, "parsing_error": parsing_error}
        self.seen = None

    def with_structured_output(self, schema, include_raw=False, method=None):
        from langchain_core.runnables import RunnableLambda

        from app.escalator import Escalation

        assert schema is Escalation and include_raw is True and method == "function_calling"

        def respond(messages):
            self.seen = messages
            return self.output

        return RunnableLambda(respond)


ESCALATION_STATE = {
    "message": "quero falar com uma pessoa",
    "user_id": "cliente1988",
    "intent": "human",
    "history": [
        {"role": "user", "content": "minha maquininha está offline"},
        {"role": "assistant", "content": "Qual maquininha?"},
    ],
    "evidence": [{"tool": "get_terminal_status", "content": "T-1 offline since yesterday"}],
    "sources": [{"url": "https://getnet.example/wifi", "title": "Wi-Fi da maquininha"}],
    "steps": [],
    "tokens": 0,
}


def escalation(**overrides):
    from app.escalator import Escalation

    return Escalation(**{**BRIEF, "transfer_message": TRANSFER, **overrides})


def test_escalator_returns_the_transfer_message_as_answer_and_the_brief_as_handoff():
    from app.escalator import make_escalator

    update = make_escalator(FakeStructuredModel(escalation(), tokens=11))(ESCALATION_STATE)

    assert update["answer"] == TRANSFER
    assert update["handoff"] == BRIEF
    assert update["steps"] == ["escalator"] and update["tokens"] == 11


def test_escalator_sees_history_reason_intent_evidence_and_sources():
    from app.escalator import make_escalator

    model = FakeStructuredModel(escalation())
    make_escalator(model)({**ESCALATION_STATE, "intent": "support", "escalation_reason": "chargeback needs a human"})

    text = "\n".join(str(m.content) for m in model.seen)
    for expected in (
        "minha maquininha está offline", "Qual maquininha?", "quero falar com uma pessoa",
        "chargeback needs a human", "Intent: support", "T-1 offline since yesterday", "https://getnet.example/wifi",
    ):
        assert expected in text


def test_escalator_reason_defaults_to_the_merchant_asking_for_a_person():
    from app.escalator import make_escalator
    from app.graph import MERCHANT_ASKED

    model = FakeStructuredModel(escalation())
    make_escalator(model)(ESCALATION_STATE)

    assert MERCHANT_ASKED in "\n".join(str(m.content) for m in model.seen)


def test_missing_transfer_message_gets_the_fixed_bilingual_fallback_and_keeps_the_brief():
    from app.escalator import make_escalator
    from app.graph import TRANSFER_FALLBACK

    update = make_escalator(FakeStructuredModel(escalation(transfer_message="  ")))(ESCALATION_STATE)

    assert update["answer"] == TRANSFER_FALLBACK
    assert update["handoff"] == BRIEF
    assert "atendente" in TRANSFER_FALLBACK and "human agent" in TRANSFER_FALLBACK


def test_unparseable_output_gets_the_fallback_message_and_a_brief_without_invented_content():
    from app.escalator import make_escalator
    from app.graph import MERCHANT_ASKED, TRANSFER_FALLBACK

    update = make_escalator(FakeStructuredModel(parsing_error=ValueError("bad json")))(ESCALATION_STATE)

    assert update["answer"] == TRANSFER_FALLBACK
    assert update["handoff"]["reason"] == MERCHANT_ASKED
    assert update["handoff"]["customer_ask"] == "quero falar com uma pessoa"
    assert update["handoff"]["priority"] == "normal"
    assert update["steps"] == ["escalator"]


# /chat


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def escalating_graph(escalator=None):
    return build_graph(fake_route("human"), fake_specialist("knowledge"), fake_specialist("support"),
                       escalator=escalator or SpyEscalator())


def test_merchant_asking_for_a_person_is_told_they_are_transferred_and_the_conversation_waits(store):
    response = chat(client_with(store, escalating_graph()), "quero falar com uma pessoa")

    assert response.status_code == 200
    body = response.json()
    assert (body["answer"], body["intent"], body["agent"], body["mode"]) == (TRANSFER, "human", "escalator", "waiting_human")
    assert "handoff" not in body
    cid = body["conversation_id"]
    assert store.conversation(cid, "cliente1988").mode == "waiting_human"
    assert [(t.role, t.content, t.intent) for t in store.turns(cid)] == [
        ("user", "quero falar com uma pessoa", "human"),
        ("assistant", TRANSFER, "human"),
    ]
    [handoff] = store.handoffs(cid)
    assert handoff.brief == BRIEF
    assert handoff.created_at is not None
    assert (handoff.claimed_by, handoff.claimed_at, handoff.outcome, handoff.ended_at) == (None, None, None, None)


def test_an_existing_conversation_escalates_and_the_next_message_is_queued(store):
    cid = chat(client_with(store), "minha maquininha está offline").json()["conversation_id"]

    escalated = chat(client_with(store, escalating_graph()), "quero um atendente", conversation_id=cid)
    queued = chat(client_with(store, NeverInvokedGraph()), "ainda aqui", conversation_id=cid)

    assert escalated.json()["conversation_id"] == cid and escalated.json()["mode"] == "waiting_human"
    assert queued.status_code == 200 and queued.json()["mode"] == "waiting_human"
    assert [t.role for t in store.turns(cid)] == ["user", "assistant", "user", "assistant", "user"]
    assert len(store.handoffs(cid)) == 1


def test_at_most_one_open_handoff_per_conversation(store):
    cid = store.create_conversation("cliente1988")
    store.escalate(cid, "cliente1988", [NewTurn("user", "pessoa")], BRIEF)

    with pytest.raises(ModeChanged):  # only from `bot`
        store.escalate(cid, "cliente1988", [NewTurn("user", "pessoa de novo")], BRIEF)
    store.set_mode(cid, "bot")
    with pytest.raises(sqlite3.IntegrityError):  # the unique index is the backstop
        store.escalate(cid, "cliente1988", [NewTurn("user", "pessoa de novo")], BRIEF)

    assert len(store.handoffs(cid)) == 1
    assert len(store.turns(cid)) == 1  # the failed Escalation stored nothing


def test_brief_content_never_reaches_the_logs(store, caplog):
    caplog.set_level(logging.DEBUG)

    body = chat(client_with(store, escalating_graph()), "quero falar com uma pessoa").json()

    assert body["mode"] == "waiting_human"
    logged = caplog.text
    for field in ("customer_ask", "summary", "attempted", "suggested_reply"):
        assert BRIEF[field] not in logged
    [(_, line)] = lines(caplog, "request")
    assert line["agent"] == "escalator" and line["intent"] == "human" and line["outcome"] == "ok"
    assert line["tools"] == []


def test_anonymous_request_for_a_person_gets_the_login_reply_and_nothing_is_stored(store):
    from app.graph import LOGIN_REPLY

    escalator = SpyEscalator()
    for intent in ("human", "support"):
        graph = build_graph(fake_route(intent), fake_specialist("knowledge"), fake_specialist("support"), escalator=escalator)
        response = client_with(store, graph).post("/chat", json={"message": "quero falar com uma pessoa"})

        body = response.json()
        assert (body["answer"], body["intent"], body["agent"], body["mode"]) == (LOGIN_REPLY, intent, "router", "bot")
        assert body["conversation_id"] is None
    assert escalator.states == []
    assert store.conversations("anonymous") == [] and store.conversations("") == []


def test_retention_purge_removes_the_handoff_with_its_conversation(tmp_path):
    from datetime import timedelta

    from tests.test_store import T0, Clock

    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    clock.now = T0 - timedelta(days=31)
    cid = store.create_conversation("cliente1988")
    store.escalate(cid, "cliente1988", [NewTurn("user", "pessoa")], BRIEF)
    clock.now = T0

    assert store.purge(timedelta(days=30)) == 1

    assert store.handoffs(cid) == []
    with closing(sqlite3.connect(tmp_path / "db.sqlite")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] == 0
