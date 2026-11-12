"""GET /conversations and GET /conversations/{id}/turns: a Merchant resumes their own Conversations."""

import uuid

import pytest

from tests.test_auth import bearer, login
from tests.test_conversations import SourcedGraph, chat, client_with, store  # noqa: F401  (fixture)


def get(client, path, user_id="cliente1988"):
    return client.get(path, headers=bearer(login(client, user_id)))


def test_listing_returns_only_the_callers_conversations_newest_first(store):
    client = client_with(store)
    older = chat(client).json()["conversation_id"]
    newer = chat(client).json()["conversation_id"]
    chat(client, user_id="cliente2024")
    chat(client, "back to the first one", conversation_id=older)

    response = get(client, "/conversations")

    assert response.status_code == 200
    listed = response.json()["conversations"]
    assert [c["id"] for c in listed] == [older, newer]
    assert set(listed[0]) == {"id", "created_at", "updated_at", "mode"}
    assert listed[0]["mode"] == "bot"
    assert get(client, "/conversations", user_id="nobody").json() == {"conversations": []}


def test_turns_come_back_in_order_with_role_content_intent_sources_created_at(store):
    client = client_with(store, SourcedGraph())
    cid = chat(client, "minha maquininha está offline").json()["conversation_id"]
    chat(client, "é a Smart", conversation_id=cid)

    response = get(client, f"/conversations/{cid}/turns")

    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == cid
    turns = body["turns"]
    assert [(t["role"], t["content"], t["intent"]) for t in turns] == [
        ("user", "minha maquininha está offline", "knowledge"),
        ("assistant", "re: minha maquininha está offline", "knowledge"),
        ("user", "é a Smart", "knowledge"),
        ("assistant", "re: é a Smart", "knowledge"),
    ]
    assert [t["id"] for t in turns] == sorted(t["id"] for t in turns)
    assert turns[1]["sources"] == [{"url": "https://getnet.example/smart", "title": "Get Smart"}]
    assert turns[0]["sources"] == []
    assert set(turns[0]) == {"id", "role", "content", "intent", "sources", "created_at"}


def test_after_returns_only_turns_after_that_turn_id(store):
    client = client_with(store, SourcedGraph())
    cid = chat(client, "first").json()["conversation_id"]
    seen = get(client, f"/conversations/{cid}/turns").json()["turns"]
    chat(client, "second", conversation_id=cid)

    later = get(client, f"/conversations/{cid}/turns?after={seen[-1]['id']}").json()["turns"]

    assert [t["content"] for t in later] == ["second", "re: second"]
    assert get(client, f"/conversations/{cid}/turns?after={later[-1]['id']}").json()["turns"] == []
    assert get(client, f"/conversations/{cid}/turns?after=-1").status_code == 422


def test_another_merchants_conversation_and_an_unknown_id_are_the_same_404_as_chat(store):
    client = client_with(store)
    theirs = chat(client, user_id="cliente2024").json()["conversation_id"]

    other = get(client, f"/conversations/{theirs}/turns")
    unknown = get(client, f"/conversations/{uuid.uuid4()}/turns")
    via_chat = chat(client, conversation_id=theirs)

    assert other.status_code == unknown.status_code == via_chat.status_code == 404
    assert other.json()["error"] == unknown.json()["error"] == via_chat.json()["error"]


@pytest.mark.parametrize("path", ["/conversations", f"/conversations/{uuid.uuid4()}/turns"])
def test_no_token_is_401(store, path):
    response = client_with(store).get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("path", ["/conversations", f"/conversations/{uuid.uuid4()}/turns"])
def test_invalid_token_is_401(store, path):
    response = client_with(store).get(path, headers=bearer("not-a-jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


@pytest.mark.parametrize("path", ["/conversations", f"/conversations/{uuid.uuid4()}/turns"])
def test_operator_token_is_403(store, path):
    response = get(client_with(store), path, user_id="operador1")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
