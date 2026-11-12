import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import TOKEN_TTL, AuthSettings
from app.main import create_app

SECRET = "test-secret-at-least-32-bytes-long"
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
EXP = int((NOW + TOKEN_TTL).timestamp())


def auth(demo_login=True, now=NOW):
    return AuthSettings(secret=SECRET, demo_login=demo_login, clock=lambda: now)


def make_app(**kw):
    """Fixed-secret auth with dev login on; Judges off whatever `.env` says (no real LLM calls)."""
    return create_app(**{"auth": auth(), "judge_enabled": False, **kw})


def claims_of(response):
    return jwt.decode(response.json()["access_token"], SECRET, algorithms=["HS256"], options={"verify_exp": False})


def test_dev_login_issues_a_merchant_token_with_expected_claims():
    client = TestClient(make_app())

    response = client.post("/dev/login", json={"user_id": "cliente1988"})

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert claims_of(response) == {"sub": "cliente1988", "role": "merchant", "exp": EXP}


def test_mock_operator_logs_in_with_operator_role():
    client = TestClient(make_app())

    assert claims_of(client.post("/dev/login", json={"user_id": "operador1"}))["role"] == "operator"


def test_unknown_id_logs_in_as_a_merchant():
    client = TestClient(make_app())

    assert claims_of(client.post("/dev/login", json={"user_id": "nobody"})) == {
        "sub": "nobody", "role": "merchant", "exp": EXP,
    }


@pytest.mark.parametrize("payload", [{"user_id": "cliente1988"}, {}])
def test_dev_login_is_404_when_disabled(payload):
    client = TestClient(make_app(auth=auth(demo_login=False)))

    response = client.post("/dev/login", json=payload)

    assert response.status_code == 404
    assert response.json() == client.post("/no-such-path", json=payload).json()


class CapturingGraph:
    def __init__(self):
        self.states = []

    def invoke(self, state):
        self.states.append(state)
        return {**state, "intent": "support", "answer": "ok", "steps": ["router", "support"]}


def login(client, user_id="cliente1988"):
    return client.post("/dev/login", json={"user_id": user_id}).json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_chat_takes_user_id_from_the_token_and_ignores_the_body():
    graph = CapturingGraph()
    client = TestClient(make_app(graph=graph))

    response = client.post(
        "/chat",
        json={"message": "hi", "user_id": "cliente2024"},
        headers=bearer(login(client, "cliente1988")),
    )

    assert response.status_code == 200
    [state] = graph.states
    assert state["user_id"] == "cliente1988"


def chat(client, headers):
    return client.post("/chat", json={"message": "hi"}, headers=headers)


def forged(claims, secret=SECRET):
    return jwt.encode(claims, secret, "HS256")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        bearer(forged({"sub": "cliente1988", "role": "merchant", "exp": int(NOW.timestamp()) + 60}, "another-secret-also-32-bytes-long!")),
        bearer(forged({"sub": "cliente1988", "role": "admin", "exp": int(NOW.timestamp()) + 60})),
        bearer(forged({"sub": "cliente1988", "role": "merchant"})),
        bearer("not-a-jwt"),
        {"Authorization": "Basic Y2xpZW50ZTE5ODg6eA=="},
    ],
    ids=["missing", "bad-signature", "bad-role", "no-exp", "garbage", "not-bearer"],
)
def test_chat_without_a_valid_token_is_401_and_never_runs_the_graph(headers):
    graph = CapturingGraph()
    client = TestClient(make_app(graph=graph))

    response = chat(client, headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] in {"unauthorized", "invalid_token"}
    assert graph.states == []


def test_expired_token_is_401():
    graph = CapturingGraph()
    issued = TestClient(make_app(auth=auth(now=NOW)))
    token = login(issued)
    one_hour_later = TestClient(make_app(graph=graph, auth=auth(now=NOW + timedelta(hours=1))))
    just_before = TestClient(make_app(graph=graph, auth=auth(now=NOW + timedelta(minutes=59))))

    assert chat(just_before, bearer(token)).status_code == 200
    response = chat(one_hour_later, bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_operator_token_on_chat_is_403():
    graph = CapturingGraph()
    client = TestClient(make_app(graph=graph))

    response = chat(client, bearer(login(client, "operador1")))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert graph.states == []


def test_unknown_id_reaches_the_account_not_found_reply():
    from app.graph import build_graph
    from app.support import make_support
    from tests.test_support import call, scripted

    model = scripted(call("get_settlement_schedule"), call("get_settlement_schedule"))
    route = lambda state: {"intent": "support", "steps": ["router"]}  # noqa: E731
    graph = build_graph(route, lambda state: {}, make_support(model))
    client = TestClient(make_app(graph=graph))

    body = chat(client, bearer(login(client, "nobody"))).json()

    assert body["agent"] == "support"
    assert "Não encontramos uma conta Getnet para o usuário nobody" in body["answer"]
    assert model.bound == []


def test_me_returns_the_merchant_and_their_fixture_account():
    from app.support import load_merchants

    client = TestClient(make_app())

    body = client.get("/me", headers=bearer(login(client, "cliente1988"))).json()

    account = load_merchants(NOW.date())["cliente1988"]
    assert body == {"sub": "cliente1988", "role": "merchant", "account": account}
    assert account["profile"]["business_name"] == "Padaria Pão Dourado"


def test_me_for_an_unknown_merchant_has_no_account_and_operators_have_none_at_all():
    client = TestClient(make_app())

    assert client.get("/me", headers=bearer(login(client, "nobody"))).json() == {
        "sub": "nobody", "role": "merchant", "account": None,
    }
    assert client.get("/me", headers=bearer(login(client, "operador1"))).json() == {
        "sub": "operador1", "role": "operator",
    }


def test_me_without_a_valid_token_is_401():
    client = TestClient(make_app())

    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=bearer("x.y.z")).status_code == 401


def test_empty_jwt_secret_gets_a_random_secret_with_a_startup_warning(monkeypatch, caplog):
    from app.settings import get_settings

    monkeypatch.setenv("JWT_SECRET", "")
    monkeypatch.setenv("DEMO_LOGIN", "true")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO)
    try:
        app = make_app(auth=None)
        created = [r for r in caplog.records if "JWT_SECRET" in r.getMessage()]
        with TestClient(app) as client:
            token = login(client)
            assert client.get("/me", headers=bearer(token)).status_code == 200
    finally:
        get_settings.cache_clear()

    assert created == []
    assert [r for r in caplog.records if r.levelno == logging.WARNING and "JWT_SECRET" in r.getMessage()]
    assert app.state.auth.secret


def test_configured_jwt_secret_signs_tokens_without_a_warning(monkeypatch, caplog):
    from app.settings import get_settings

    monkeypatch.setenv("JWT_SECRET", SECRET)
    monkeypatch.setenv("DEMO_LOGIN", "true")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO)
    try:
        with TestClient(make_app(auth=None)) as client:
            token = login(client)
    finally:
        get_settings.cache_clear()

    assert jwt.decode(token, SECRET, algorithms=["HS256"])["sub"] == "cliente1988"
    assert not [r for r in caplog.records if "JWT_SECRET" in r.getMessage()]


def test_request_log_user_ref_is_the_pseudonym_of_the_token_sub(caplog):
    from app.observability import LogPrivacy
    from tests.test_observability import lines

    privacy = LogPrivacy(key=b"k1")
    client = TestClient(make_app(graph=CapturingGraph(), log_privacy=privacy))
    caplog.set_level(logging.INFO)

    client.post("/chat", json={"message": "hi", "user_id": "cliente2024"}, headers=bearer(login(client, "cliente1988")))

    [(_, line)] = lines(caplog, "request")
    assert line["user_ref"] == hmac.new(b"k1", b"cliente1988", hashlib.sha256).hexdigest()[:16]
