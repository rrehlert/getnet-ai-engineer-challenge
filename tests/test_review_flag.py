"""Quality for the takeover (ADR 0006): the escalation rubric and the Review flag."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.graph import build_graph
from app.store import NewTurn, Store
from tests.test_auth import bearer, login, make_app
from tests.test_escalation import BRIEF, SpyEscalator
from tests.test_graph import fake_route, fake_specialist
from tests.test_observability import RecordingJudgeModel, coverage, verdict
from tests.test_operator import escalated
from tests.test_store import T0, Clock


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def judged_app(store, route, model):
    graph = build_graph(fake_route(route), fake_specialist("knowledge"), fake_specialist("support"),
                        escalator=SpyEscalator())
    return make_app(graph=graph, store=store, judge_enabled=True, judge_model=model)


def judge_model(route=0.9, answer=0.9, cov=1.0):
    return RecordingJudgeModel(
        messages=iter([verdict(route), verdict(answer), coverage(["knowledge"], cov == 1.0, score=cov)]), seen=[]
    )


def chat(client, message="quero falar com uma pessoa", conversation_id=None, token=None):
    body = {"message": message} | ({"conversation_id": conversation_id} if conversation_id else {})
    headers = {} if token is None else bearer(token)
    return client.post("/chat", json=body, headers=headers)


# Escalation rubric


def test_escalated_turn_is_judged_with_the_escalation_rubric_and_the_brief(store):
    model = judge_model()
    client = TestClient(judged_app(store, "human", model))

    chat(client, token=login(client))

    _route, (system, human), _coverage = model.seen
    assert "brief" in system.content.lower() and "faithful" in system.content.lower()
    assert BRIEF["customer_ask"] in human.content
    assert BRIEF["suggested_reply"] in human.content


def escalating_knowledge(state):
    return {"answer": "", "escalation_reason": "Chargeback dispute needs a human decision.",
            "evidence": [{"tool": "search_corpus", "content": "Chargebacks: contact support."}],
            "steps": ["knowledge"]}


def test_tool_escalation_is_judged_against_the_conversation_with_the_escalation_rubric(store):
    first = TestClient(make_app(graph=build_graph(fake_route("knowledge"), fake_specialist("knowledge"),
                                                  fake_specialist("support")), store=store))
    token = login(first)
    cid = chat(first, "Quero contestar um chargeback", token=token).json()["conversation_id"]
    model = judge_model()
    graph = build_graph(fake_route("knowledge"), escalating_knowledge, fake_specialist("support"),
                        escalator=SpyEscalator())
    client = TestClient(make_app(graph=graph, store=store, judge_enabled=True, judge_model=model))

    chat(client, "Ninguém resolve, e agora?", conversation_id=cid, token=token)

    _route, (system, human), _coverage = model.seen
    assert "faithful" in system.content.lower()
    assert "user: Quero contestar um chargeback" in human.content  # the Conversation the brief must match
    assert "Chargebacks: contact support." in human.content
    assert BRIEF["summary"] in human.content


def test_a_bot_reply_is_judged_with_its_intent_rubric_not_the_escalation_one(store):
    model = judge_model()
    client = TestClient(judged_app(store, "knowledge", model))

    chat(client, "Pix cai na hora?", token=login(client))

    _route, (system, human), _coverage = model.seen
    assert "faithful" not in system.content.lower() and "Handoff Brief" not in human.content


def test_an_anonymous_request_for_a_person_is_judged_as_a_login_reply(store):
    from app.graph import LOGIN_REPLY
    from app.judge import ANONYMOUS_COVERAGE_RULE, ANONYMOUS_SUPPORT_RUBRIC

    model = judge_model()
    client = TestClient(judged_app(store, "human", model))

    body = chat(client).json()

    assert body["answer"] == LOGIN_REPLY
    (_, route_human), (answer_system, _), (coverage_system, _) = model.seen
    assert ANONYMOUS_SUPPORT_RUBRIC in answer_system.content
    assert "faithful" not in answer_system.content.lower()
    assert "`human`" in ANONYMOUS_COVERAGE_RULE and ANONYMOUS_COVERAGE_RULE.strip() in coverage_system.content
    assert "not logged in" in route_human.content


# Review flag


def test_a_low_answer_score_sets_the_review_flag_without_changing_the_mode(store):
    client = TestClient(judged_app(store, "knowledge", judge_model(answer=0.69)))

    body = chat(client, "Pix cai na hora?", token=login(client)).json()

    [conversation] = store.conversations("cliente1988")
    assert conversation.id == body["conversation_id"]
    assert conversation.needs_review is True
    assert conversation.mode == "bot" and body["mode"] == "bot"


@pytest.mark.parametrize("scores", [{"answer": 0.7}, {"route": 0.1}, {"cov": 0.2}])
def test_route_and_coverage_scores_and_an_answer_at_the_threshold_set_no_flag(store, scores):
    client = TestClient(judged_app(store, "knowledge", judge_model(**scores)))

    chat(client, "Pix cai na hora?", token=login(client))

    [conversation] = store.conversations("cliente1988")
    assert conversation.needs_review is False


def test_an_escalated_turn_with_a_low_answer_score_is_flagged_and_stays_waiting(store):
    client = TestClient(judged_app(store, "human", judge_model(answer=0.2)))

    chat(client, token=login(client))

    [conversation] = store.conversations("cliente1988")
    assert (conversation.needs_review, conversation.mode) == (True, "waiting_human")


def test_an_anonymous_low_score_sets_nothing(store):
    client = TestClient(judged_app(store, "knowledge", judge_model(answer=0.1)))

    response = chat(client, "Pix cai na hora?")

    assert response.status_code == 200 and response.json()["conversation_id"] is None
    assert store.conversations("cliente1988") == []
    assert TestClient(make_app(store=store)).get("/operator/review", headers=operator(client)).json() == {
        "conversations": []
    }


# Operators: review list, detail, reviewed


def operator(client):
    return bearer(login(client, "operador1"))


def flagged(store, owner="cliente1988", message="Pix cai na hora?"):
    """A `bot` Conversation (never escalated) with a low-scored reply."""
    cid = store.create_conversation(owner)
    store.append_turns(cid, [NewTurn("user", message, intent="knowledge"),
                             NewTurn("assistant", "Talvez.", intent="knowledge")])
    store.flag_for_review(cid)
    return cid


def test_review_list_has_flagged_conversations_in_any_mode_newest_first(tmp_path):
    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    clock.now = T0 - timedelta(minutes=10)
    older = flagged(store)
    clock.now = T0 - timedelta(minutes=5)
    waiting = escalated(store, owner="cliente2024")
    store.flag_for_review(waiting)
    clock.now = T0 - timedelta(minutes=1)
    escalated(store)  # escalated but not flagged
    store.create_conversation("cliente1988")  # neither
    clock.now = T0
    client = TestClient(make_app(store=store))

    response = client.get("/operator/review", headers=operator(client))

    assert response.status_code == 200
    items = response.json()["conversations"]
    assert [(i["conversation_id"], i["mode"]) for i in items] == [(waiting, "waiting_human"), (older, "bot")]
    assert datetime.fromisoformat(items[1]["updated_at"]) == T0 - timedelta(minutes=10)


def test_a_flagged_bot_conversation_without_a_handoff_is_readable_by_operators(store):
    cid = flagged(store)
    client = TestClient(make_app(store=store))

    detail = client.get(f"/operator/conversations/{cid}", headers=operator(client))

    assert detail.status_code == 200
    body = detail.json()
    assert (body["mode"], body["needs_review"], body["handoff"]) == ("bot", True, None)
    assert [t["content"] for t in body["turns"]] == ["Pix cai na hora?", "Talvez."]


def test_reviewed_clears_the_flag_and_is_audited_without_changing_the_mode(store):
    waiting = escalated(store)
    store.flag_for_review(waiting)
    client = TestClient(make_app(store=store))

    response = client.post(f"/operator/conversations/{waiting}/reviewed", headers=operator(client))

    assert response.status_code == 200
    assert (response.json()["needs_review"], response.json()["mode"]) == (False, "waiting_human")
    assert client.get("/operator/review", headers=operator(client)).json()["conversations"] == []
    [entry] = [e for e in store.audit_log(waiting) if e.action == "reviewed"]
    assert (entry.operator, entry.used_suggestion) == ("operador1", None)


def test_a_reviewed_bot_conversation_is_no_longer_visible_to_operators(store):
    cid = flagged(store)
    client = TestClient(make_app(store=store))

    client.post(f"/operator/conversations/{cid}/reviewed", headers=operator(client))

    assert client.get(f"/operator/conversations/{cid}", headers=operator(client)).status_code == 404
    assert [e.action for e in store.audit_log(cid)] == ["reviewed"]


def test_reviewed_of_a_conversation_without_the_flag_is_409_and_not_audited(store):
    waiting = escalated(store)
    client = TestClient(make_app(store=store))

    response = client.post(f"/operator/conversations/{waiting}/reviewed", headers=operator(client))

    assert response.status_code == 409 and response.json()["error"]["code"] == "not_flagged"
    assert store.audit_log(waiting) == []


def test_reviewed_of_a_conversation_operators_cannot_see_is_404(store):
    cid = store.create_conversation("cliente1988")
    client = TestClient(make_app(store=store))

    assert client.post(f"/operator/conversations/{cid}/reviewed", headers=operator(client)).status_code == 404


@pytest.mark.parametrize(("method", "path"), [("get", "/operator/review"), ("post", "/operator/conversations/x/reviewed")])
def test_review_endpoints_need_the_operator_role(store, method, path):
    client = TestClient(make_app(store=store))

    assert client.request(method.upper(), path).status_code == 401
    assert client.request(method.upper(), path, headers=bearer(login(client))).status_code == 403
