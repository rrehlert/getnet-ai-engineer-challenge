"""Ticket 05: the Knowledge and Customer Support Agents escalate via `escalate_to_human(reason)`."""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.graph import EMPTY_ANSWER_FALLBACK, build_graph
from app.store import Store
from app.support import make_support
from tests.test_auth import make_app
from tests.test_conversations import chat, client_with
from tests.test_escalation import TRANSFER, SpyEscalator
from tests.test_graph import fake_route, fake_specialist
from tests.test_knowledge import call as knowledge_call
from tests.test_knowledge import final, knowledge_with, scripted
from tests.test_support import TODAY as SUPPORT_TODAY
from tests.test_support import call as support_call
from tests.test_support import final as support_final
from tests.test_support import scripted as support_scripted


def escalate(reason, id="e1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": "escalate_to_human", "args": {"reason": reason}, "id": id, "type": "tool_call"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    )


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def test_knowledge_agent_escalates_the_merchant_waits_for_an_operator_and_the_draft_is_discarded(store):
    model = scripted(
        knowledge_call("search_corpus", "estorno contestação"),
        escalate("chargeback dispute is not covered by the Corpus"),
        final("draft that must never be sent"),
    )
    escalator = SpyEscalator()
    graph = build_graph(fake_route("knowledge"), knowledge_with(model), fake_specialist("support"), escalator=escalator)

    body = chat(client_with(store, graph), "quero contestar um estorno").json()

    assert body["mode"] == "waiting_human"
    assert body["agent"] == "escalator"
    assert body["intent"] == "knowledge"
    assert body["answer"] == TRANSFER
    [state] = escalator.states
    assert state["escalation_reason"] == "chargeback dispute is not covered by the Corpus"


def graph_with(knowledge=None, support=None, intent="knowledge"):
    escalator = SpyEscalator()
    graph = build_graph(
        fake_route(intent),
        knowledge or fake_specialist("knowledge"),
        support or fake_specialist("support"),
        escalator=escalator,
    )
    return graph, escalator


def test_evidence_and_sources_gathered_before_the_call_reach_the_escalator_and_the_reason_is_never_a_source():
    reason = "Merchant needs a chargeback reversed; see https://reason.example"
    with_draft = escalate(reason)
    with_draft.content = "Here is a half-answer draft"
    model = scripted(knowledge_call("search_corpus", "pix"), with_draft, final("never reached"))
    graph, escalator = graph_with(knowledge=knowledge_with(model))

    result = graph.invoke({"message": "estorno do pix", "user_id": "cliente1988"})

    [state] = escalator.states
    assert state["intent"] == "knowledge"
    assert state["escalation_reason"] == reason
    [evidence] = state["evidence"]
    assert evidence["tool"] == "search_corpus" and "O Pix cai na hora." in evidence["content"]
    assert state["sources"] == [{"url": "https://g/pix", "title": "Pix"}, {"url": "https://g/taxas", "title": "Taxas"}]
    assert "reason.example" not in str(result["sources"])
    assert result["answer"] == TRANSFER
    assert result["steps"] == ["router", "knowledge", "search_corpus", "escalate_to_human", "escalator"]


def test_customer_support_agent_escalates_with_its_evidence_and_the_conversation_waits(store):
    model = support_scripted(
        support_call("get_terminal_status"),
        escalate("terminal still offline after the hints; needs a replacement decision"),
        support_final("draft that must never be sent"),
    )
    escalator = SpyEscalator()
    support = make_support(model, today=lambda: SUPPORT_TODAY)
    graph = build_graph(fake_route("support"), fake_specialist("knowledge"), support, escalator=escalator)

    body = chat(client_with(store, graph), "a maquininha continua offline", user_id="cliente2024").json()

    assert (body["mode"], body["agent"], body["intent"]) == ("waiting_human", "escalator", "support")
    assert body["answer"] == TRANSFER
    assert body["sources"] == []
    [state] = escalator.states
    assert state["escalation_reason"] == "terminal still offline after the hints; needs a replacement decision"
    [evidence] = state["evidence"]
    assert evidence["tool"] == "get_terminal_status" and "GT-77C3-0451" in evidence["content"]


def test_a_merchant_missing_from_the_fixture_can_still_be_escalated(store):
    model = support_scripted(escalate("account cliente9999 not found; Merchant insists the id is right"))
    escalator = SpyEscalator()
    support = make_support(model, today=lambda: SUPPORT_TODAY)
    graph = build_graph(fake_route("support"), fake_specialist("knowledge"), support, escalator=escalator)

    body = chat(client_with(store, graph), "minha conta sumiu, preciso de ajuda", user_id="cliente9999").json()

    assert model.bound == ["escalate_to_human"]
    assert (body["mode"], body["agent"], body["intent"]) == ("waiting_human", "escalator", "support")
    [state] = escalator.states
    assert state["escalation_reason"] == "account cliente9999 not found; Merchant insists the id is right"
    assert state["evidence"] == []


def test_unknown_merchant_with_an_empty_reply_gets_the_fixed_not_found_answer():
    from app.support import NOT_FOUND

    support = make_support(support_scripted(support_final("")), today=lambda: SUPPORT_TODAY)

    update = support({"message": "Quando cai o dinheiro?", "user_id": "cliente9999"})

    assert update["answer"] == NOT_FOUND.format(user_id="cliente9999")
    assert "escalation_reason" not in update


@pytest.mark.parametrize("module", ["app.knowledge", "app.support"])
def test_specialist_prompts_say_when_to_escalate(module):
    import importlib

    prompt = importlib.import_module(module).PROMPT
    assert "escalate_to_human" in prompt
    for case in ("stuck", "don't cover", "human decision"):
        assert case in prompt


def test_anonymous_visitor_gets_no_escalation_tool_or_rule_in_the_knowledge_agent():
    model = scripted(final("O Pix cai na hora."))

    update = knowledge_with(model)({"message": "como funciona o pix?", "user_id": None})

    assert "escalate_to_human" not in model.bound
    assert "escalate_to_human" not in model.seen[0][0].content
    assert update["answer"] == "O Pix cai na hora."


def test_merchant_still_gets_the_escalation_tool_and_rule_in_the_knowledge_agent():
    model = scripted(final("O Pix cai na hora."))

    knowledge_with(model)({"message": "como funciona o pix?", "user_id": "cliente1988"})

    assert "escalate_to_human" in model.bound
    assert "escalate_to_human" in model.seen[0][0].content


def test_an_escalation_reason_without_a_merchant_ends_with_the_empty_answer_fallback_never_empty():
    def escalating(state):
        return {"answer": "", "escalation_reason": "can't resolve", "steps": ["knowledge"]}

    graph, escalator = graph_with(knowledge=escalating)

    response = TestClient(make_app(graph=graph)).post("/chat", json={"message": "como funciona o pix?"})

    assert response.status_code == 200
    assert response.json()["answer"] == EMPTY_ANSWER_FALLBACK
    assert response.json()["mode"] == "bot"
    assert escalator.states == []


def test_escalation_rule_says_answer_first_and_never_for_partial_answers():
    """Live check: specialists escalated Mixed questions they could partly answer, discarding the facts."""
    from app.agents import ESCALATION_RULE

    assert "last resort" in ESCALATION_RULE
    assert "even in part" in ESCALATION_RULE
    assert "Escalating discards your answer" in ESCALATION_RULE
