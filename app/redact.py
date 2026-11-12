"""Masks a Merchant's personal data in log text (spec: Observability, log privacy).

Patterns run longest identifier first; placeholders hold no digits, so later
patterns never re-match them. Digit runs must not touch a letter or digit, which
keeps hex `trace_id`s and Terminal ids like `GT-58A1-0093` intact.
"""

import re
from collections.abc import Callable

_START = r"(?<![\w.@-])"
_END = r"(?![\w@]|[.-]\d)"


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _mask_card_if_luhn(match: re.Match) -> str:
    raw = match.group()
    digits = re.sub(r"\D", "", raw)
    return "[CARD]" if _luhn_ok(digits) else raw


_PATTERNS: list[tuple[re.Pattern, str | Callable[[re.Match], str]]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    (re.compile(_START + r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}" + _END), "[PIX_KEY]"),
    (re.compile(_START + r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}" + _END), "[CNPJ]"),
    (re.compile(_START + r"\d{3}\.\d{3}\.\d{3}-\d{2}" + _END), "[CPF]"),
    (re.compile(_START + r"\d{14}" + _END), "[CNPJ]"),
    (re.compile(_START + r"\d(?:[ -]?\d){12,18}" + _END), _mask_card_if_luhn),
    (re.compile(_START + r"\d{11}" + _END), "[CPF]"),
    (
        re.compile(
            _START + r"(?:\+?55[\s.-]?)?(?:\(\d{2}\)|\d{2})[\s.-]?9?\d{4}[\s.-]?\d{4}" + _END
            + r"|" + _START + r"9?\d{4}-\d{4}" + _END
        ),
        "[PHONE]",
    ),
]


def redact(text: str) -> str:
    """`text` with CPF, CNPJ, card, email, phone and Pix random key values replaced by typed placeholders."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def mask_cards(text: str) -> str:
    """`text` with only card numbers replaced by `[CARD]`, for what is stored (nobody needs a card
    number; CPF, phone and the rest stay for the Operator). Same order as `redact`: identifiers
    matched before cards (a bare CNPJ can pass Luhn) are set aside, then put back unchanged."""
    kept: list[str] = []

    def keep(match: re.Match) -> str:
        kept.append(match.group())
        return f"\x00{chr(0xE000 + len(kept) - 1)}\x00"  # no digits, letters or `@`: invisible to later patterns

    for pattern, replacement in _PATTERNS:
        if replacement is _mask_card_if_luhn:
            text = pattern.sub(replacement, text)
            break
        text = pattern.sub(keep, text)
    return re.sub(r"\x00(.)\x00", lambda m: kept[ord(m.group(1)) - 0xE000], text)


def _map_strings(value: object, fn: Callable[[str], str]) -> object:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_map_strings(v, fn) for v in value]
    return value


def redact_value(value: object) -> object:
    """`redact` applied to every string inside nested dicts, lists and tuples."""
    return _map_strings(value, redact)


def mask_cards_value(value: object) -> object:
    """`mask_cards` applied to every string inside nested dicts, lists and tuples."""
    return _map_strings(value, mask_cards)
