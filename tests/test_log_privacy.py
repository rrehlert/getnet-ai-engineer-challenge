import hashlib
import hmac
import json
import logging
import sys

import pytest
from fastapi.testclient import TestClient

from app.judge import JUDGES, run_judges
from app.observability import JsonFormatter, LogPrivacy, emit
from app.settings import Settings
from tests.test_chat_api import post, route_to
from tests.test_observability import FakeJudgeModel, app_for, coverage, lines, verdict


def emitted(caplog, text):
    caplog.clear()
    with caplog.at_level(logging.INFO):
        emit("probe", text=text)
    [record] = caplog.records
    return json.loads(record.getMessage())["text"]


@pytest.mark.parametrize(
    "raw, placeholder",
    [
        ("123.456.789-09", "[CPF]"),
        ("12345678909", "[CPF]"),
        ("12.345.678/0001-95", "[CNPJ]"),
        ("12345678000195", "[CNPJ]"),
        ("4111 1111 1111 1111", "[CARD]"),
        ("4111-1111-1111-1111", "[CARD]"),
        ("4111111111111111", "[CARD]"),
        ("378282246310005", "[CARD]"),  # 15-digit Amex
        ("joao.silva+loja@example.com.br", "[EMAIL]"),
        ("(11) 98765-4321", "[PHONE]"),
        ("+55 11 98765-4321", "[PHONE]"),
        ("11 3265-4321", "[PHONE]"),
        ("98765-4321", "[PHONE]"),
        ("+5511987654321", "[PHONE]"),
        ("+55-11-98765-4321", "[PHONE]"),
        ("11.98765.4321", "[PHONE]"),
        ("123e4567-e89b-42d3-a456-426614174000", "[PIX_KEY]"),
    ],
)
def test_personal_data_is_masked_in_events(caplog, raw, placeholder):
    out = emitted(caplog, f"meu dado é {raw}, ok?")

    assert raw not in out
    assert out == f"meu dado é {placeholder}, ok?"


def test_non_luhn_card_length_digits_are_not_masked_as_cards(caplog):
    out = emitted(caplog, "pedido 4111 1111 1111 1112 e 4111111111111112")

    assert "[CARD]" not in out
    assert "4111 1111 1111 1112" in out and "4111111111111112" in out


def test_amounts_dates_trace_ids_and_terminal_ids_survive(caplog):
    text = (
        "R$ 1.735,40 e R$ 1.234.567,89 (1735.40) em 2026-11-10 e 2026-11-10T08:55:00, "
        "trace 0123456789012345678901234567abcd, terminal GT-58A1-0093"
    )

    assert emitted(caplog, text) == text


def test_nested_fields_are_masked(caplog):
    caplog.clear()
    with caplog.at_level(logging.INFO):
        emit("probe", nested={"emails": ["a@b.co"]})
    data = json.loads(caplog.records[0].getMessage())

    assert data["nested"] == {"emails": ["[EMAIL]"]}


def formatted(msg, *args, exc_info=None):
    record = logging.LogRecord("app.main", logging.ERROR, __file__, 1, msg, args, exc_info)
    return json.loads(JsonFormatter().format(record))


def test_formatted_lines_start_with_utc_time_and_level():
    record = logging.LogRecord("app.main", logging.INFO, __file__, 1, '{"event": "probe"}', (), None)
    record.created = 1789214400.25

    line = JsonFormatter().format(record)

    assert line.startswith('{"time": "2026-09-12T12:00:00.250+00:00", "level": "INFO", "event": "probe"')


def test_non_event_log_line_is_redacted():
    line = formatted("provider error trace_id=%s: %r", "abc123", ValueError("cpf 123.456.789-09"))

    assert "123.456.789-09" not in line["message"]
    assert "[CPF]" in line["message"] and "abc123" in line["message"]


def test_exception_text_in_error_line_is_redacted():
    try:
        raise RuntimeError("no account for joao@example.com, card 4111111111111111")
    except RuntimeError:
        line = formatted("unexpected error trace_id=%s", "t1", exc_info=sys.exc_info())

    assert "joao@example.com" not in line["exc"] and "4111111111111111" not in line["exc"]
    assert "[EMAIL]" in line["exc"] and "[CARD]" in line["exc"]


def request_line(caplog, privacy, message="hi", user_id="cliente1988"):
    caplog.clear()
    caplog.set_level(logging.INFO)
    app = app_for(route_to("knowledge"), judge_enabled=False, log_privacy=privacy)
    post(TestClient(app), message=message, user_id=user_id)
    [(_, line)] = lines(caplog, "request")
    return json.dumps(line, ensure_ascii=False), line


def test_request_line_has_keyed_user_ref_instead_of_user_id(caplog):
    raw, line = request_line(caplog, LogPrivacy(key=b"k1"))
    _, again = request_line(caplog, LogPrivacy(key=b"k1"))
    _, other_key = request_line(caplog, LogPrivacy(key=b"k2"))

    assert "user_id" not in line and "cliente1988" not in raw
    assert line["user_ref"] == hmac.new(b"k1", b"cliente1988", hashlib.sha256).hexdigest()[:16]
    assert again["user_ref"] == line["user_ref"]
    assert other_key["user_ref"] != line["user_ref"]


def test_empty_log_hash_key_gets_a_random_key_with_a_warning(caplog):
    caplog.set_level(logging.INFO)
    first = LogPrivacy.from_settings(Settings(_env_file=None, log_hash_key=""))
    second = LogPrivacy.from_settings(Settings(_env_file=None, log_hash_key=""))
    warned = [r for r in caplog.records if r.levelno == logging.WARNING and "LOG_HASH_KEY" in r.getMessage()]
    caplog.clear()
    keyed = LogPrivacy.from_settings(Settings(_env_file=None, log_hash_key="secret"))

    assert len(warned) == 2
    assert first.key and first.key != second.key
    assert keyed.key == b"secret"
    assert not [r for r in caplog.records if "LOG_HASH_KEY" in r.getMessage()]


MESSAGE = "meu cpf é 123.456.789-09 " + "x" * 600


def test_log_messages_redacted_is_the_default(caplog):
    _, line = request_line(caplog, LogPrivacy(key=b"k"), message=MESSAGE)

    assert Settings(_env_file=None).log_messages == "redacted"
    assert line["message"] == ("meu cpf é [CPF] " + "x" * 600)[:500]


def test_log_messages_none_logs_only_the_length(caplog):
    raw, line = request_line(caplog, LogPrivacy(key=b"k", messages="none"), message=MESSAGE)

    assert "message" not in line and "xxx" not in raw
    assert line["message_length"] == len(MESSAGE)


def test_log_messages_full_logs_raw_text_still_capped(caplog):
    _, line = request_line(caplog, LogPrivacy(key=b"k", messages="full"), message=MESSAGE)

    assert line["message"] == MESSAGE[:500]


def test_judge_reason_is_redacted_and_judges_are_told_not_to_quote_personal_data(caplog):
    caplog.set_level(logging.INFO)
    leaky = "Merchant joao@example.com with CPF 123.456.789-09 was answered."
    model = FakeJudgeModel(messages=iter([verdict(0.9, leaky), verdict(0.9, leaky), coverage(["knowledge"], True, reason=leaky)]))

    run_judges(model, privacy=LogPrivacy(key=b"k"), trace_id="t1", message="hi", intent="knowledge", answer="ok", sources=[], evidence=[])

    reasons = [j["reason"] for _, j in lines(caplog, "judge")]
    assert reasons == ["Merchant [EMAIL] with CPF [CPF] was answered."] * 3
    for _schema, build in JUDGES.values():
        (_, system), _ = build(message="hi", intent="knowledge", answer="ok", sources=[], evidence=[])
        assert "personal data" in system


def test_log_hash_key_warning_comes_at_startup_not_at_app_creation(monkeypatch, caplog):
    from app.settings import get_settings

    monkeypatch.setenv("LOG_HASH_KEY", "")
    get_settings.cache_clear()
    caplog.set_level(logging.INFO)
    try:
        app = app_for(route_to("knowledge"), judge_enabled=False)
        created = [r for r in caplog.records if "LOG_HASH_KEY" in r.getMessage()]
        with TestClient(app):
            pass
    finally:
        get_settings.cache_clear()

    assert created == []
    assert [r for r in caplog.records if "LOG_HASH_KEY" in r.getMessage()]


ANSWER = "enviamos para joao@example.com " + "y" * 600


def judge_lines(caplog, privacy):
    caplog.clear()
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.9)]))
    run_judges(
        model, privacy=privacy, trace_id="t1", message=MESSAGE, intent="knowledge", answer=ANSWER,
        sources=[], evidence=[],
    )
    judged = [j for _, j in lines(caplog, "judge")]
    assert [j["judge_type"] for j in judged] == ["route", "answer"]
    return judged


def test_judge_line_has_message_and_answer_redacted_and_capped_by_default(caplog):
    for line in judge_lines(caplog, LogPrivacy(key=b"k")):
        assert line["message"] == ("meu cpf é [CPF] " + "x" * 600)[:500]
        assert line["answer"] == ("enviamos para [EMAIL] " + "y" * 600)[:500]


def test_judge_line_under_log_messages_none_logs_only_lengths(caplog):
    for line in judge_lines(caplog, LogPrivacy(key=b"k", messages="none")):
        assert "message" not in line and "answer" not in line
        assert "xxx" not in json.dumps(line) and "yyy" not in json.dumps(line)
        assert (line["message_length"], line["answer_length"]) == (len(MESSAGE), len(ANSWER))


def test_judge_line_under_log_messages_full_logs_raw_text_still_capped(caplog):
    for line in judge_lines(caplog, LogPrivacy(key=b"k", messages="full")):
        assert line["message"] == MESSAGE[:500]
        assert line["answer"] == ANSWER[:500]


def test_app_judges_use_the_apps_log_privacy(caplog):
    caplog.set_level(logging.INFO)
    model = FakeJudgeModel(messages=iter([verdict(0.9), verdict(0.9)]))
    app = app_for(
        route_to("knowledge"), judge_enabled=True, judge_model=model,
        log_privacy=LogPrivacy(key=b"k", messages="none"),
    )
    post(TestClient(app), message="meu cpf é 123.456.789-09")

    judged = [j for _, j in lines(caplog, "judge")]
    assert len(judged) == 2
    assert all("message" not in j and j["message_length"] == len("meu cpf é 123.456.789-09") for j in judged)
