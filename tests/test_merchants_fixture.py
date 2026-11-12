"""The mock Merchant fixture (`data/merchants.json`): the eval Merchants stay
byte-identical, and the demo Merchants (C3) load through `load_merchants`."""

import hashlib
import json
from datetime import date

from app.support import DATA_PATH, load_merchants

TODAY = date(2026, 10, 30)

# sha256 of each entry's raw JSON text, as written in the file. The eval expected
# facts (evals/scenarios.json) depend on these two Merchants: don't edit them.
ORIGINAL = {
    "cliente1988": "f2e946c74f6bc60949e53099727daa4016d717602e573650e7b2eea1087ebe2b",
    "cliente2024": "a4bd37c87a9ab0b570bfa9d679b62fcd56d481f8e76f36b045bcaa19ad8a06a0",
}
NEW = ["cliente1975", "cliente2010", "cliente2077"]


def raw_entry(text: str, user_id: str) -> str:
    """The exact source text of one Merchant's JSON value."""
    key = f'"{user_id}": '
    start = text.index(key) + len(key)
    _, end = json.JSONDecoder().raw_decode(text, start)
    return text[start:end]


def test_original_merchants_are_byte_identical():
    text = DATA_PATH.read_text(encoding="utf-8")
    for user_id, digest in ORIGINAL.items():
        assert hashlib.sha256(raw_entry(text, user_id).encode()).hexdigest() == digest, user_id


def test_new_merchants_resolve_through_load_merchants_with_the_same_shape():
    merchants = load_merchants(TODAY)
    for user_id in NEW:
        account = merchants[user_id]
        assert set(account) == {"profile", "settlements", "terminals", "transactions"}
        assert account["profile"]["terminals"] == len(account["terminals"])
        for s in account["settlements"]:
            assert round(s["gross_amount"] - s["fee_amount"], 2) == s["net_amount"]
            assert "sale_date" in s and "expected_date" in s
        serials = {t["serial"] for t in account["terminals"]}
        assert all(t["terminal"] in serials for t in account["transactions"])
        assert not any(k.endswith("day_offset") for k in json.dumps(account).split('"'))


def test_each_new_merchant_has_its_demo_path():
    merchants = load_merchants(TODAY)

    held = merchants["cliente1975"]["settlements"]
    assert {"failed", "held"} <= {s["status"] for s in held}
    assert all("support staff" in s["note"] for s in held if s["status"] in ("failed", "held"))

    reader = merchants["cliente2010"]["terminals"][0]
    assert reader["status"] == "offline" and reader["last_error"].startswith("CARD_READER_FAULT")
    assert reader["last_seen_date"] == "2026-10-29"

    quiet = merchants["cliente2077"]
    assert len(quiet["transactions"]) <= 3
    assert sum(s["transactions"] for s in quiet["settlements"]) <= 3
