import threading

from fastapi.testclient import TestClient

from app.main import create_app
from tests.test_auth import auth, bearer, login


def test_health_returns_ok_when_no_index_is_needed():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_not_ready_until_the_index_is_built_at_startup():
    release = threading.Event()
    index = object()

    def load_index():
        release.wait(5)
        return index

    app = create_app(load_index=load_index, auth=auth())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503
        chat = client.post("/chat", json={"message": "oi"}, headers=bearer(login(client)))
        assert chat.status_code == 503

        release.set()
        app.state.index_thread.join(5)

        assert client.get("/health").json() == {"status": "ok"}
        assert app.state.index is index
