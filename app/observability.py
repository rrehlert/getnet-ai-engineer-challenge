"""Structured JSON logging (spec: Observability). Each event is one JSON log line."""

import hashlib
import hmac
import json
import logging
import secrets
import sys
import uuid
from dataclasses import dataclass
from typing import get_args

from app.graph import LOGIN_STEP, Agent, Intent, agent_for
from app.redact import redact, redact_value
from app.settings import MessageMode, Settings

log = logging.getLogger("app.events")

AGENTS = set(get_args(Agent))
NOT_TOOLS = AGENTS | {LOGIN_STEP}
MESSAGE_LIMIT = 500
ANONYMOUS = "anonymous"  # `user_ref` of a visitor without a token


@dataclass(frozen=True)
class LogPrivacy:
    """How log lines identify the Merchant and show the Message and reply."""

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

    def text_fields(self, **texts: str) -> dict:
        """Each text as a log field under this mode, final (not redacted again).

        `none` logs `<name>_length` instead; `redacted` redacts then caps; `full` only caps.
        """
        out: dict = {}
        for name, text in texts.items():
            if self.messages == "none":
                out[f"{name}_length"] = len(text)
            elif self.messages == "full":
                out[name] = text[:MESSAGE_LIMIT]
            else:
                out[name] = redact(text)[:MESSAGE_LIMIT]
        return out


def emit(event: str, level: int = logging.INFO, *, unredacted: dict | None = None, **fields) -> None:
    """Write one event line; every string in `fields` is redacted first, `unredacted` is not."""
    data = {"event": event, **redact_value(fields), **(unredacted or {})}
    log.log(level, json.dumps(data, ensure_ascii=False, default=str))


def _canonical_uuid(value: str | None) -> str | None:
    """Conversation ids are random UUIDs (the redactor would mask them as Pix keys); any other
    caller-supplied value is dropped rather than logged."""
    try:
        return value if value is not None and str(uuid.UUID(value)) == value else None
    except ValueError:
        return None


def log_request(
    *,
    privacy: LogPrivacy,
    trace_id: str,
    user_id: str | None,
    message: str,
    latency_ms: int,
    outcome: str,
    result: dict | None = None,
    conversation_id: str | None = None,
) -> None:
    result = result or {}
    intent: Intent | None = result.get("intent")
    emit(
        "request",
        unredacted={"conversation_id": _canonical_uuid(conversation_id), **privacy.text_fields(message=message)},
        trace_id=trace_id,
        user_ref=ANONYMOUS if user_id is None else privacy.user_ref(user_id),
        intent=intent,
        agent=None if intent is None else agent_for(
            intent, anonymous=user_id is None, escalated=user_id is not None and result.get("handoff") is not None
        ),
        tools=[s for s in result.get("steps", []) if s not in NOT_TOOLS],
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
