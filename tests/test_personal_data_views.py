"""Personal data outside the logs: card numbers never stored; the Operator view masks
everything unless the caller is the Operator handling the Conversation."""

import pytest

from app.redact import mask_cards
from app.store import NewTurn, Store
from tests.test_escalation import BRIEF
from tests.test_operator import OPERATOR, as_operator, client_for, escalated

CARD = "4111 1111 1111 1111"  # Luhn-valid test card
CPF = "529.982.247-25"
MESSAGE = f"Meu CPF é {CPF}, paguei com o cartão {CARD}"
BRIEF_WITH_DATA = {**BRIEF, "summary": f"Merchant de CPF {CPF} pagou com o cartão {CARD}.",
                   "customer_ask": f"Saber do pagamento do CPF {CPF}"}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "conversations.db")


def detail(client, cid, operator=OPERATOR):
    return client.get(f"/operator/conversations/{cid}", headers=as_operator(client, operator)).json()


# Cards are masked before they are stored


@pytest.mark.parametrize("kept", [
    CPF, "52998224725", "11.222.333/0001-81",
    "00000002000180",  # bare CNPJ that also passes Luhn: still a CNPJ, not a card
    "ana@example.com", "(11) 98765-4321", "123e4567-e89b-12d3-a456-426614174000",
    "4111 1111 1111 1112",  # fails Luhn
    "R$ 250,00",
])
def test_mask_cards_masks_only_card_numbers(kept):
    assert mask_cards(f"cartão {CARD}, e {kept}") == f"cartão [CARD], e {kept}"


def test_turns_and_briefs_are_stored_without_card_numbers(store):
    cid = escalated(store, message=MESSAGE, brief=BRIEF_WITH_DATA)
    store.append_turns(cid, [NewTurn("user", f"outro cartão {CARD}")])
    handoff = store.current_handoff(cid)
    store.replace_brief(handoff.id, {**BRIEF, "attempted": f"cartão {CARD}"}, 1)

    stored = [t.content for t in store.turns(cid)] + list(store.current_handoff(cid).brief.values())
    assert not any("4111" in s for s in stored)
    assert store.turns(cid)[0].content == f"Meu CPF é {CPF}, paguei com o cartão [CARD]"


# Operator view: need to know


def test_an_unclaimed_conversation_is_shown_redacted_in_the_detail_and_the_queue(store):
    cid = escalated(store, message=MESSAGE, brief=BRIEF_WITH_DATA)
    client = client_for(store)

    body = detail(client, cid)
    queue = client.get("/operator/queue", headers=as_operator(client)).json()["conversations"]

    assert body["redacted"] is True
    assert body["turns"][0]["content"] == "Meu CPF é [CPF], paguei com o cartão [CARD]"
    assert body["handoff"]["brief"]["summary"] == "Merchant de CPF [CPF] pagou com o cartão [CARD]."
    assert queue[0]["customer_ask"] == "Saber do pagamento do CPF [CPF]"


def test_the_claiming_operator_sees_personal_data_except_card_numbers(store):
    cid = escalated(store, message=MESSAGE, brief=BRIEF_WITH_DATA)
    client = client_for(store)

    claimed = client.post(f"/operator/conversations/{cid}/claim", headers=as_operator(client)).json()
    mine = client.get("/operator/mine", headers=as_operator(client)).json()["conversations"]

    for body in (claimed, detail(client, cid)):
        assert body["redacted"] is False
        assert body["turns"][0]["content"] == f"Meu CPF é {CPF}, paguei com o cartão [CARD]"
        assert body["handoff"]["brief"]["customer_ask"] == f"Saber do pagamento do CPF {CPF}"
    assert mine[0]["customer_ask"] == f"Saber do pagamento do CPF {CPF}"


def test_another_operator_sees_a_claimed_conversation_redacted(store):
    cid = escalated(store, message=MESSAGE, brief=BRIEF_WITH_DATA)
    store.claim(cid, OPERATOR)

    body = detail(client_for(store), cid, operator="operador2")

    assert body["redacted"] is True
    assert CPF not in body["turns"][0]["content"]


def test_a_review_flagged_conversation_is_redacted_once_its_handoff_ended(store):
    cid = escalated(store, message=MESSAGE, brief=BRIEF_WITH_DATA)
    store.claim(cid, OPERATOR)
    store.close(cid, OPERATOR, NewTurn("operator", "Encerrado."))
    store.flag_for_review(cid)

    body = detail(client_for(store), cid)

    assert body["redacted"] is True
    assert CPF not in body["turns"][0]["content"]
    assert CPF not in body["handoff"]["brief"]["summary"]
