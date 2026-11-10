"""Structured JSON logging (spec: Observability). Each event is one JSON log line."""

import hashlib
import hmac
import json
import logging
import secrets
import sys
from dataclasses import dataclass
from typing import get_args

from app.graph import Agent, Intent, agent_for
from app.redact import redact, redact_value
from app.settings import MessageMode, Settings

log = logging.getLogger("app.events")

AGENTS = set(get_args(Agent))
MESSAGE_LIMIT = 500


@dataclass(frozen=True)
class LogPrivacy:
    """How the request line identifies the Merchant and shows the Message."""

    key: bytes
    messages: MessageMode = "redacted"

    @classmethod
    def from_settings(cls, settings: Settings) -> "LogPrivacy":
        """Uses `LOG_HASH_KEY`; when empty, a random key with a warning."""
        key = settings.log_hash_key.encode()
        if not key:
            log.warning("LOG_HASH_KEY is empty: using a random key, so user_ref values change on every restart")
            key = secrets.token_bytes(32)
        return cls(key=key, messages=settings.log_messages)

    def user_ref(self, user_id: str) -> str:
        """Keyed HMAC-SHA256 of the user id, first 16 hex characters."""
        return hmac.new(self.key, user_id.encode(), hashlib.sha256).hexdigest()[:16]

    def message_fields(self, message: str) -> dict:
        """The request line's Message fields under this mode, final (not redacted again)."""
        if self.messages == "none":
            return {"message_length": len(message)}
        if self.messages == "full":
            return {"message": message[:MESSAGE_LIMIT]}
        return {"message": redact(message)[:MESSAGE_LIMIT]}


def emit(event: str, level: int = logging.INFO, *, unredacted: dict | None = None, **fields) -> None:
    """Write one event line; every string in `fields` is redacted first, `unredacted` is not."""
    data = {"event": event, **redact_value(fields), **(unredacted or {})}
    log.log(level, json.dumps(data, ensure_ascii=False, default=str))


def log_request(
    *,
    privacy: LogPrivacy,
    trace_id: str,
    user_id: str,
    message: str,
    latency_ms: int,
    outcome: str,
    result: dict | None = None,
) -> None:
    result = result or {}
    intent: Intent | None = result.get("intent")
    emit(
        "request",
        unredacted=privacy.message_fields(message),
        trace_id=trace_id,
        user_ref=privacy.user_ref(user_id),
        intent=intent,
        agent=None if intent is None else agent_for(intent),
        tools=[s for s in result.get("steps", []) if s not in AGENTS],
        tokens=result.get("tokens", 0),
        latency_ms=latency_ms,
        outcome=outcome,
    )


class JsonFormatter(logging.Formatter):
    """Event lines (redacted by `emit`) pass through as JSON; other records are redacted and wrapped in a JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            data = json.loads(msg)
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            data = {"event": "log", "logger": record.name, "message": redact(msg)}
            if record.exc_info:
                data["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps({"level": record.levelname, **data}, ensure_ascii=False, default=str)


def setup_logging() -> None:
    """Install the JSON handler on the `app` loggers once (production entrypoint only)."""
    app_log = logging.getLogger("app")
    if any(isinstance(h.formatter, JsonFormatter) for h in app_log.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
