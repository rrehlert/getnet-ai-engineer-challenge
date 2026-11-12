import logging
from datetime import timedelta

from fastapi.testclient import TestClient

from app.settings import get_settings
from app.store import NewTurn, Store
from tests.test_auth import make_app
from tests.test_store import T0, Clock


def store_with(tmp_path, ages_in_days):
    """A store whose clock reads T0, holding one Conversation last updated `age` days ago per entry."""
    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    ids = []
    for age in ages_in_days:
        clock.now = T0 - timedelta(days=age)
        cid = store.create_conversation("cliente1988")
        store.append_turns(cid, [NewTurn("user", "minha maquininha")])
        ids.append(cid)
    clock.now = T0
    return store, ids


def test_startup_purges_conversations_older_than_the_default_30_days(tmp_path, caplog):
    store, (old, recent) = store_with(tmp_path, [31, 29])
    caplog.set_level(logging.INFO)

    with TestClient(make_app(store=store)):
        assert store.conversation(old, "cliente1988") is None
        assert store.turns(old) == []
        assert store.conversation(recent, "cliente1988") is not None

    [line] = [r.getMessage() for r in caplog.records if "retention" in r.getMessage()]
    assert "1 conversation" in line and "30 days" in line
    assert "cliente1988" not in line and old not in line


def test_startup_uses_conversation_retention_days(tmp_path, monkeypatch):
    monkeypatch.setenv("CONVERSATION_RETENTION_DAYS", "7")
    get_settings.cache_clear()
    store, (old, recent) = store_with(tmp_path, [8, 6])

    with TestClient(make_app(store=store)):
        assert store.conversation(old, "cliente1988") is None
        assert store.conversation(recent, "cliente1988") is not None


def test_nothing_is_purged_until_the_app_starts(tmp_path):
    store, (old,) = store_with(tmp_path, [31])

    make_app(store=store)

    assert store.conversation(old, "cliente1988") is not None
