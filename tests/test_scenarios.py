from scripts.scenarios import Scenario, check_reply


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
