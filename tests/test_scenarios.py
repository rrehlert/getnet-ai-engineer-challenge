import json
from typing import get_args

import pytest

from app.graph import Intent
from scripts.scenarios import (
    INTENTS,
    DatasetError,
    Scenario,
    brl,
    check_reply,
    load_scenarios,
    parse_scenario,
)


def test_correct_intent_with_missing_fact_passes_routing_but_fails_facts():
    scenario = Scenario(
        "When will the money from yesterday's sales be deposited?",
        "cliente1988",
        "support",
        facts=[["1.817,26"], ["955,20"]],
    )
    body = {"intent": "support", "answer": "R$ 1.817,26 lands today."}

    result = check_reply(body, scenario)

    assert result.routing_ok is True
    assert result.facts_ok is False
    assert result.missing_facts == [["955,20"]]


def test_wrong_intent_with_facts_present_fails_routing_but_passes_facts():
    scenario = Scenario("Quando cai o dinheiro?", "cliente1988", "support", facts=[["1.817,26"]])
    body = {"intent": "knowledge", "answer": "Você recebe R$ 1.817,26 hoje."}

    result = check_reply(body, scenario)

    assert result.routing_ok is False
    assert result.facts_ok is True
    assert result.missing_facts == []


def test_a_fact_passes_when_any_alternative_appears():
    scenario = Scenario("m", "cliente1988", "support", facts=[["R$ 1.817,26", "R$1.817,26"]])
    body = {"intent": "support", "answer": "Debit: R$1.817,26 today."}

    assert check_reply(body, scenario).facts_ok is True


def test_facts_match_case_insensitively():
    scenario = Scenario("m", "cliente1988", "support", facts=[["Insufficient Funds"], ["offline"]])
    body = {"intent": "support", "answer": "Declined for INSUFFICIENT FUNDS; Caixa 1 is Offline."}

    assert check_reply(body, scenario).facts_ok is True


def test_scenario_without_facts_reports_facts_not_applicable():
    scenario = Scenario("What's the euro exchange rate today?", "cliente1988", "knowledge")
    body = {"intent": "knowledge", "answer": "About R$ 6,20."}

    result = check_reply(body, scenario)

    assert result.routing_ok is True
    assert result.facts_ok is None
    assert result.missing_facts == []


def test_error_body_without_answer_fails_declared_facts():
    scenario = Scenario("m", "cliente1988", "support", facts=[["offline"]])
    body = {"error": {"code": "internal_error", "message": "Internal server error."}}

    result = check_reply(body, scenario)

    assert result.routing_ok is False
    assert result.facts_ok is False
    assert result.missing_facts == [["offline"]]


# Shared dataset (evals/scenarios.json)


def test_dataset_intents_match_the_graph():
    assert INTENTS == set(get_args(Intent))


def test_dataset_starts_with_the_original_scenarios():
    scenarios = load_scenarios()

    assert len(scenarios) >= 13
    assert scenarios[0].message == "What's the difference between the Get Clássica and the Get Smart?"
    assert scenarios[12].message == "Quando cai o dinheiro das vendas de ontem?"
    assert all(not s.intents_needed for s in scenarios[:13])


def test_dataset_has_mixed_questions_with_two_or_more_intents():
    mixed = [s for s in load_scenarios() if s.intents_needed]

    assert 3 <= len(mixed) <= 4
    assert all(len(set(s.intents_needed)) >= 2 for s in mixed)


def test_brl_fact_expands_to_spellings():
    raw = {"message": "m", "user_id": "u", "intent": "support", "facts": [{"brl": "1817.26"}]}

    assert parse_scenario(raw, "s").facts == [brl("1817.26")]


@pytest.mark.parametrize(
    "raw, needle",
    [
        ({"message": "m", "user_id": "u"}, "intent"),
        ({"message": "m", "user_id": "u", "intent": "sales"}, "intent"),
        ({"message": "m", "user_id": "u", "intent": "support", "intents_needed": ["support"]}, "intents_needed"),
        ({"message": "m", "user_id": "u", "intent": "support", "intents_needed": ["support", "billing"]}, "intents_needed"),
        ({"message": "m", "user_id": "u", "intent": "support", "facts": [[]]}, "fact"),
        ({"message": "m", "user_id": "u", "intent": "support", "facts": [[""]]}, "fact"),
        ({"message": "", "user_id": "u", "intent": "support"}, "message"),
    ],
)
def test_invalid_scenarios_are_rejected_naming_the_scenario(raw, needle, tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"scenarios": [{"message": "ok", "user_id": "u", "intent": "knowledge"}, raw]}))

    with pytest.raises(DatasetError, match=r"scenario 2") as exc:
        load_scenarios(path)
    assert needle in str(exc.value)


def test_mixed_question_routed_to_any_needed_intent_passes_routing():
    scenario = Scenario("Caixa 1 is offline, how do I set up Wi-Fi?", "cliente1988", "support", intents_needed=["support", "knowledge"])

    assert check_reply({"intent": "knowledge", "answer": ""}, scenario).routing_ok is True
    assert check_reply({"intent": "unsupported", "answer": ""}, scenario).routing_ok is False
