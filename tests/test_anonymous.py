"""Anonymous visitors (ADR 0005): no token → Knowledge only, account questions get a login reply."""

import logging

from fastapi.testclient import TestClient

from app.graph import build_graph
from tests.test_auth import CapturingGraph, bearer, login, make_app


def fake_route(intent, reply=""):
    def route(state):
        return {"intent": intent, "answer": reply, "steps": ["router"]}

    return route


def knowledge(state):
    return {"answer": f"knowledge answer to {state['message']}", "sources": [], "steps": ["knowledge"]}


class SpySupport:
    def __init__(self):
        self.calls = []

    def __call__(self, state):
        self.calls.append(state)
        return {"answer": "account data", "steps": ["support"]}


def anonymous_client(route_fn, support=None, **kw):
    graph = build_graph(route_fn, knowledge, support or SpySupport())
    return TestClient(make_app(graph=graph, **kw))


def test_anonymous_account_question_gets_the_login_reply_and_support_never_runs():
    from app.graph import LOGIN_REPLY

    support = SpySupport()
    client = anonymous_client(fake_route("support"), support)

    response = client.post("/chat", json={"message": "When will my money be deposited?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == LOGIN_REPLY
    assert body["intent"] == "support"
    assert body["agent"] == "router"
    assert body["steps"] == ["router", "login"]
    assert body["sources"] == []
    assert support.calls == []
    assert "faça login" in LOGIN_REPLY and "log in" in LOGIN_REPLY


def test_anonymous_graph_state_has_no_merchant():
    graph = CapturingGraph()
    client = TestClient(make_app(graph=graph))

    client.post("/chat", json={"message": "hi", "user_id": "cliente1988"})

    [state] = graph.states
    assert state["user_id"] is None


def test_anonymous_product_question_reaches_the_knowledge_agent():
    client = anonymous_client(fake_route("knowledge"))

    body = client.post("/chat", json={"message": "What is Get Smart?"}).json()

    assert body["answer"] == "knowledge answer to What is Get Smart?"
    assert body["agent"] == "knowledge"
    assert body["steps"] == ["router", "knowledge"]


def test_anonymous_unsupported_message_is_refused_as_today():
    client = anonymous_client(fake_route("unsupported", reply="Sorry, I can't help with that."))

    body = client.post("/chat", json={"message": "Write me a poem"}).json()

    assert body["answer"] == "Sorry, I can't help with that."
    assert body["intent"] == "unsupported"
    assert body["agent"] == "router"
    assert body["steps"] == ["router"]


def test_logged_in_merchant_still_reaches_customer_support():
    support = SpySupport()
    client = anonymous_client(fake_route("support"), support)

    body = client.post("/chat", json={"message": "my sales"}, headers=bearer(login(client))).json()

    assert body["answer"] == "account data"
    assert body["agent"] == "support"
    assert [s["user_id"] for s in support.calls] == ["cliente1988"]


def test_anonymous_conversation_id_is_401_and_never_runs_the_graph():
    graph = CapturingGraph()
    client = TestClient(make_app(graph=graph))

    response = client.post("/chat", json={"message": "hi", "conversation_id": "c1"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
    assert graph.states == []


def test_anonymous_empty_body_is_422():
    assert TestClient(make_app(graph=CapturingGraph())).post("/chat", json={}).status_code == 422


def test_me_without_a_token_is_still_401():
    response = TestClient(make_app()).get("/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_anonymous_request_log_user_ref_is_anonymous(caplog):
    from tests.test_observability import lines

    client = anonymous_client(fake_route("support"))
    caplog.set_level(logging.INFO)

    client.post("/chat", json={"message": "my sales"})

    [(_, line)] = lines(caplog, "request")
    assert line["user_ref"] == "anonymous"
    assert line["intent"] == "support"
    assert line["agent"] == "router"
    assert line["tools"] == []


class CapturingJudgeModel:
    """Records each Judge's prompt and returns a passing verdict."""

    def __init__(self):
        self.prompts = []  # one per Judge Type, in order: route, answer, coverage

    def with_structured_output(self, schema, method=None):
        from langchain_core.runnables import RunnableLambda

        def respond(messages):
            self.prompts.append(messages)
            if schema.__name__ == "Coverage":
                return schema(score=1, reason="r", intents_needed=["support"], fully_answered=True)
            return schema(score=1, reason="r")

        return RunnableLambda(respond)


def test_judges_are_told_an_anonymous_visitor_is_not_logged_in():
    from app.graph import LOGIN_REPLY
    from app.judge import run_judges
    from app.observability import LogPrivacy

    model = CapturingJudgeModel()

    run_judges(model, privacy=LogPrivacy(key=b"k"), trace_id="t", message="my sales", intent="support",
               answer=LOGIN_REPLY, sources=[], evidence=[], user_id=None)

    route, answer, coverage = model.prompts
    assert "not logged in" in route[1][1] and "None" not in route[1][1]
    assert "log in" in answer[0][1]
    assert "not logged in" in coverage[1][1] and "None" not in coverage[1][1]
    assert "asking them to log in fully answers" in coverage[0][1]


def test_coverage_judge_for_a_logged_in_merchant_has_no_login_rule():
    from app.judge import JUDGES

    _, build = JUDGES["coverage"]
    (_, system), (_, human) = build(message="m?", intent="support", answer="r", sources=[], evidence=[], user_id="c1")

    assert "log in" not in system
    assert "Merchant: c1" in human
