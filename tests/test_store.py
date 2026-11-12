import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

from app.store import NewTurn, Store

T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def test_new_conversation_has_a_random_uuid_bot_mode_and_its_owner(tmp_path):
    store = Store(tmp_path / "db.sqlite", clock=Clock())

    cid = store.create_conversation("cliente1988")

    assert uuid.UUID(cid).version == 4
    conversation = store.conversation(cid, "cliente1988")
    assert conversation is not None
    assert (conversation.id, conversation.owner, conversation.mode) == (cid, "cliente1988", "bot")
    assert conversation.created_at == conversation.updated_at == T0
    assert store.create_conversation("cliente1988") != cid


def test_conversation_lookup_is_none_for_another_owner_or_an_unknown_id(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    cid = store.create_conversation("cliente1988")

    assert store.conversation(cid, "cliente2024") is None
    assert store.conversation(str(uuid.uuid4()), "cliente1988") is None
    assert store.conversation("not-a-uuid", "cliente1988") is None


def test_appended_turns_come_back_in_order_and_bump_updated_at(tmp_path):
    clock = Clock()
    store = Store(tmp_path / "db.sqlite", clock=clock)
    cid = store.create_conversation("cliente1988")
    clock.now = T0 + timedelta(minutes=5)

    store.append_turns(cid, [
        NewTurn("user", "minha maquininha está offline", intent="support"),
        NewTurn("assistant", "Vamos ver.", intent="support", sources=[{"url": "u", "title": "t"}]),
    ])
    store.append_turns(cid, [NewTurn("user", "é a Smart"), NewTurn("assistant", "Ok.")])

    turns = store.turns(cid)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "minha maquininha está offline"),
        ("assistant", "Vamos ver."),
        ("user", "é a Smart"),
        ("assistant", "Ok."),
    ]
    assert [t.id for t in turns] == sorted(t.id for t in turns)
    assert turns[1].intent == "support" and turns[1].sources == [{"url": "u", "title": "t"}]
    assert turns[2].intent is None and turns[2].sources == []
    assert {t.conversation_id for t in turns} == {cid}
    assert turns[0].created_at == T0 + timedelta(minutes=5)
    conversation = store.conversation(cid, "cliente1988")
    assert conversation is not None
    assert conversation.created_at == T0 and conversation.updated_at == T0 + timedelta(minutes=5)


def test_turns_of_one_conversation_do_not_leak_into_another(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    a, b = store.create_conversation("cliente1988"), store.create_conversation("cliente1988")

    store.append_turns(a, [NewTurn("user", "in a")])

    assert [t.content for t in store.turns(a)] == ["in a"]
    assert store.turns(b) == []


def test_data_survives_reopening_the_same_file(tmp_path):
    path = tmp_path / "state" / "conversations.db"
    first = Store(path)
    cid = first.create_conversation("cliente1988")
    first.append_turns(cid, [NewTurn("user", "oi"), NewTurn("assistant", "olá")])
    del first

    reopened = Store(path)

    assert reopened.conversation(cid, "cliente1988") is not None
    assert [t.content for t in reopened.turns(cid)] == ["oi", "olá"]
    later = reopened.create_conversation("cliente1988")
    assert reopened.conversation(later, "cliente1988") is not None


def test_database_uses_wal_mode(tmp_path):
    path = tmp_path / "db.sqlite"
    Store(path)

    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
