"""Operator side of the takeover (ADR 0006): reply, handback, close."""

import pytest

from app.store import Store
from tests.test_auth import bearer, login
from tests.test_operator import OPERATOR, as_operator, client_for, escalated

MERCHANT = "cliente1988"
OTHER_OPERATOR = "operador2"


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def claimed(store, operator=OPERATOR):
    cid = escalated(store)
    assert store.claim(cid, operator) is True
    return cid


def act(client, cid, action, operator=OPERATOR, **body):
    return client.post(f"/operator/conversations/{cid}/{action}", headers=as_operator(client, operator),
                       json=body or None)


def reply(client, cid, content="Olá, sou a Ana. Vou verificar sua maquininha.", used_suggestion=False,
          operator=OPERATOR):
    return act(client, cid, "reply", operator, content=content, used_suggestion=used_suggestion)


def merchant_turns(client, cid, after=0):
    response = client.get(f"/conversations/{cid}/turns", params={"after": after},
                          headers=bearer(login(client, MERCHANT)))
    assert response.status_code == 200
    return response.json()


# Reply


def test_reply_is_stored_as_an_operator_turn_the_merchant_sees_by_polling(store):
    cid = claimed(store)
    client = client_for(store)
    last_seen = merchant_turns(client, cid)["turns"][-1]["id"]

    response = reply(client, cid, used_suggestion=True)

    assert response.status_code == 200
    assert response.json()["mode"] == "human"
    polled = merchant_turns(client, cid, after=last_seen)
    assert [(t["role"], t["content"]) for t in polled["turns"]] == [
        ("operator", "Olá, sou a Ana. Vou verificar sua maquininha."),
    ]
    assert polled["mode"] == "human"
    [_, entry] = store.audit_log(cid)
    assert (entry.operator, entry.action, entry.used_suggestion) == (OPERATOR, "reply", True)


def test_reply_by_another_operator_is_403_and_stores_nothing(store):
    cid = claimed(store)
    client = client_for(store)
    before = store.turns(cid)

    response = reply(client, cid, operator=OTHER_OPERATOR)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_claimer"
    assert store.turns(cid) == before
    assert [e.action for e in store.audit_log(cid)] == ["claim"]


@pytest.mark.parametrize("mode", ["waiting_human", "bot", "closed"])
def test_reply_outside_human_mode_is_409_and_stores_nothing(store, mode):
    cid = escalated(store)  # waiting_human: nobody has claimed it
    if mode != "waiting_human":
        store.set_mode(cid, mode)
    client = client_for(store)
    before = store.turns(cid)

    response = reply(client, cid)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "wrong_mode"
    assert store.turns(cid) == before
    assert store.audit_log(cid) == []


def test_reply_needs_content_and_used_suggestion(store):
    cid = claimed(store)
    client = client_for(store)

    assert act(client, cid, "reply", content="", used_suggestion=False).status_code == 422
    assert act(client, cid, "reply", content="Olá").status_code == 422


# Handback


def test_handback_returns_the_conversation_to_the_bot_with_a_fixed_turn_the_merchant_sees(store):
    cid = claimed(store)
    client = client_for(store)
    last_seen = merchant_turns(client, cid)["turns"][-1]["id"]

    response = act(client, cid, "handback")

    assert response.status_code == 200
    assert response.json()["mode"] == "bot"
    assert response.json()["handoff"]["outcome"] == "handed_back"
    assert response.json()["handoff"]["ended_at"] is not None
    polled = merchant_turns(client, cid, after=last_seen)
    assert polled["mode"] == "bot"
    [turn] = polled["turns"]
    assert turn["role"] == "assistant"
    assert "You're back with the virtual assistant" in turn["content"]
    assert "assistente virtual" in turn["content"]  # bilingual: Portuguese too
    assert [(e.operator, e.action, e.used_suggestion) for e in store.audit_log(cid)][-1] == (OPERATOR, "handback", None)


def test_handback_while_waiting_is_409(store):
    cid = escalated(store)
    client = client_for(store)

    response = act(client, cid, "handback")

    assert response.status_code == 409
    assert store.operator_conversation(cid).mode == "waiting_human"
    assert store.handoffs(cid)[0].ended_at is None
    assert store.audit_log(cid) == []


def test_handback_by_another_operator_is_403(store):
    cid = claimed(store)
    client = client_for(store)

    response = act(client, cid, "handback", operator=OTHER_OPERATOR)

    assert response.status_code == 403
    assert store.operator_conversation(cid).mode == "human"
    assert store.handoffs(cid)[0].outcome is None
    assert [e.action for e in store.audit_log(cid)] == ["claim"]


# Close


def assert_closed_by(store, client, cid, operator, last_seen):
    polled = merchant_turns(client, cid, after=last_seen)
    assert polled["mode"] == "closed"
    [turn] = polled["turns"]
    assert turn["role"] == "assistant"
    assert "This conversation was closed by the agent" in turn["content"]
    assert "encerrada pelo atendente" in turn["content"]
    [handoff] = store.handoffs(cid)
    assert handoff.outcome == "closed" and handoff.ended_at is not None
    assert [(e.operator, e.action, e.used_suggestion) for e in store.audit_log(cid)][-1] == (operator, "close", None)


def test_the_claiming_operator_closes_a_conversation_in_human(store):
    cid = claimed(store)
    client = client_for(store)
    last_seen = merchant_turns(client, cid)["turns"][-1]["id"]

    response = act(client, cid, "close")

    assert response.status_code == 200
    assert response.json()["mode"] == "closed"
    assert_closed_by(store, client, cid, OPERATOR, last_seen)


def test_any_operator_closes_a_waiting_conversation_without_claiming_it(store):
    cid = escalated(store)
    client = client_for(store)
    last_seen = merchant_turns(client, cid)["turns"][-1]["id"]

    response = act(client, cid, "close", operator=OTHER_OPERATOR)

    assert response.status_code == 200
    assert_closed_by(store, client, cid, OTHER_OPERATOR, last_seen)
    assert store.handoffs(cid)[0].claimed_by is None
    assert [e.action for e in store.audit_log(cid)] == ["close"]
    assert client.get("/operator/queue", headers=as_operator(client)).json()["conversations"] == []


def test_close_of_human_by_another_operator_is_403(store):
    cid = claimed(store)
    client = client_for(store)

    response = act(client, cid, "close", operator=OTHER_OPERATOR)

    assert response.status_code == 403
    assert store.operator_conversation(cid).mode == "human"
    assert store.handoffs(cid)[0].ended_at is None
    assert [e.action for e in store.audit_log(cid)] == ["claim"]


@pytest.mark.parametrize("mode", ["bot", "closed"])
def test_handback_or_close_without_an_open_handoff_is_409(store, mode):
    cid = escalated(store)
    store.set_mode(cid, mode)
    client = client_for(store)

    assert act(client, cid, "handback").status_code == 409
    assert act(client, cid, "close").status_code == 409
    assert store.audit_log(cid) == []


def test_after_close_the_merchant_cannot_chat_in_that_conversation(store):
    from tests.test_chat_mode import NeverInvokedGraph
    from tests.test_conversations import chat, client_with

    cid = escalated(store)
    act(client_for(store), cid, "close")

    response = chat(client_with(store, NeverInvokedGraph()), "ainda está aí?", conversation_id=cid)

    assert response.status_code == 409


# After handback


def test_after_handback_the_next_message_runs_the_graph_with_the_operator_turn_in_history(store):
    from tests.test_auth import CapturingGraph
    from tests.test_conversations import chat, client_with

    cid = claimed(store)
    client = client_for(store)
    reply(client, cid, content="Reiniciei sua maquininha remotamente.")
    act(client, cid, "handback")
    graph = CapturingGraph()

    response = chat(client_with(store, graph), "obrigado, voltou a funcionar", conversation_id=cid)

    assert response.status_code == 200
    assert response.json()["mode"] == "bot"
    [state] = graph.states
    assert {"role": "operator", "content": "Reiniciei sua maquininha remotamente."} in state["history"]
    assert state["history"][-1]["content"].startswith("Você está de volta com o assistente virtual")


def test_agents_see_operator_turns_as_assistant_messages_prefixed_human_agent():
    from langchain_core.messages import AIMessage, HumanMessage

    from app.agents import conversation_messages

    messages = conversation_messages({
        "message": "obrigado",
        "history": [
            {"role": "user", "content": "quero falar com uma pessoa"},
            {"role": "assistant", "content": "Vou transferir você."},
            {"role": "user", "content": "ainda aqui"},  # sent while waiting: passes through unchanged
            {"role": "operator", "content": "Reiniciei sua maquininha remotamente."},
        ],
    })

    assert [(type(m), m.content) for m in messages] == [
        (HumanMessage, "quero falar com uma pessoa"),
        (AIMessage, "Vou transferir você."),
        (HumanMessage, "ainda aqui"),
        (AIMessage, "[Human agent] Reiniciei sua maquininha remotamente."),
        (HumanMessage, "obrigado"),
    ]


# Audit and roles


def test_audit_rows_for_reply_handback_and_close_hold_no_message_text(store):
    import sqlite3
    from contextlib import closing

    from app.operator import CLOSE_TURN, HANDBACK_TURN

    client = client_for(store)
    handed_back = claimed(store)
    reply(client, handed_back, content="Reiniciei sua maquininha remotamente.", used_suggestion=False)
    act(client, handed_back, "handback")
    closed = claimed(store)
    act(client, closed, "close")

    assert [(e.action, e.used_suggestion) for e in store.audit_log(handed_back)] == [
        ("claim", None), ("reply", False), ("handback", None)]
    assert [e.action for e in store.audit_log(closed)] == ["claim", "close"]
    with closing(sqlite3.connect(store.path)) as conn:
        dumped = repr(conn.execute("SELECT * FROM audit").fetchall())
    for text in ("Reiniciei", HANDBACK_TURN, CLOSE_TURN):
        assert text not in dumped


@pytest.mark.parametrize("action", ["reply", "handback", "close"])
def test_actions_need_the_operator_role_and_a_visible_conversation(store, action):
    from tests.test_conversations import chat, client_with

    client = client_for(store)
    cid = escalated(store)
    body = {"content": "Olá", "used_suggestion": False} if action == "reply" else None
    path = f"/operator/conversations/{cid}/{action}"

    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers=bearer(login(client, MERCHANT))).status_code == 403
    private = chat(client_with(store), "minhas vendas de ontem").json()["conversation_id"]
    for hidden in (private, "no-such-id"):
        response = client.post(f"/operator/conversations/{hidden}/{action}", json=body,
                               headers=as_operator(client))
        assert response.status_code == 404
    assert store.audit_log(cid) == []
