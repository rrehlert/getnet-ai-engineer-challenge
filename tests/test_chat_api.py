import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app.graph import build_graph
from app.main import create_app


def route_to(intent, reply=""):
    return lambda state: {"intent": intent, "answer": reply, "steps": ["router"], "tokens": 3}


def knowledge(state):
    return {
        "answer": "Get Smart has a touchscreen.",
        "sources": [{"url": "https://getnet.example/smart", "title": "Get Smart"}],
        "steps": ["knowledge", "search_corpus"],
        "tokens": 10,
    }


def support(state):
    return {"answer": f"Account {state['user_id']}", "sources": [], "steps": ["support"]}


def client_for(route_fn):
    return TestClient(create_app(graph=build_graph(route_fn, knowledge, support)))


def raising(exc):
    def route(state):
        raise exc

    return route


def post(client, message="hi", user_id="cliente1988"):
    return client.post("/chat", json={"message": message, "user_id": user_id})


def test_knowledge_reply_has_spec_shape():
    response = post(client_for(route_to("knowledge")))

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Get Smart has a touchscreen."
    assert body["intent"] == "knowledge"
    assert body["agent"] == "knowledge"
    assert body["sources"] == [{"url": "https://getnet.example/smart", "title": "Get Smart"}]
    assert body["steps"] == ["router", "knowledge", "search_corpus"]
    assert body["trace_id"]


def test_support_uses_user_id_from_body():
    body = post(client_for(route_to("support")), user_id="cliente2024").json()

    assert body["agent"] == "support"
    assert body["answer"] == "Account cliente2024"


def test_unsupported_is_200_answered_by_router():
    response = post(client_for(route_to("unsupported", reply="Não posso ajudar com isso.")))

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "unsupported"
    assert body["agent"] == "router"
    assert body["answer"] == "Não posso ajudar com isso."
    assert body["sources"] == []
    assert body["steps"] == ["router"]


@pytest.mark.parametrize(
    "payload",
    [
        {"message": "", "user_id": "cliente1988"},
        {"message": "hi", "user_id": ""},
        {"message": "hi"},
        {"user_id": "cliente1988"},
    ],
)
def test_invalid_body_is_422(payload):
    response = client_for(route_to("knowledge")).post("/chat", json=payload)

    assert response.status_code == 422


def _response(status):
    return httpx.Response(status, request=httpx.Request("POST", "https://llm.example"))


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (openai.RateLimitError("rate limited", response=_response(429), body=None), "rate_limited"),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://llm.example")), "provider_unavailable"),
        (openai.InternalServerError("boom", response=_response(502), body=None), "provider_unavailable"),
    ],
)
def test_provider_errors_are_503(exc, code):
    response = post(client_for(raising(exc)))

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert body["trace_id"]


def test_unexpected_error_is_generic_500_without_details():
    response = post(client_for(raising(RuntimeError("secret internal detail"))))

    assert response.status_code == 500
    body = response.json()
    assert "secret internal detail" not in response.text
    assert body["error"]["code"] == "internal_error"
    assert body["trace_id"]


class FakeAnthropicRateLimitError(Exception):
    """A non-openai provider SDK error: only its name and status say what it is."""

    status_code = 429


class FakeOverloadedError(Exception):
    pass


class FakeGoogleError(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.status = status


def wrapped(cause):
    try:
        raise cause
    except Exception as inner:
        try:
            raise RuntimeError("graph node failed") from inner
        except RuntimeError as outer:
            return outer


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (FakeAnthropicRateLimitError("slow down"), "rate_limited"),
        (FakeOverloadedError("overloaded"), "provider_unavailable"),
        (FakeGoogleError(503), "provider_unavailable"),
        (httpx.ReadTimeout("timed out"), "provider_unavailable"),
        (httpx.ConnectError("refused"), "provider_unavailable"),
        (wrapped(FakeGoogleError(429)), "rate_limited"),
        (wrapped(FakeGoogleError(500)), "provider_unavailable"),
    ],
)
def test_any_providers_errors_are_503(exc, code):
    response = post(client_for(raising(exc)))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("exc", [FakeGoogleError(400), wrapped(ValueError("bad")), KeyError("intent")])
def test_non_provider_errors_stay_500(exc):
    response = post(client_for(raising(exc)))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
