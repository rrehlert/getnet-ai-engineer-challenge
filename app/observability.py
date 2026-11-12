"""Structured JSON logging (spec: Observability). Each event is one JSON log line."""

import hashlib
import hmac
import json
import logging
import secrets
import sys
import threading
import uuid
from collections import deque
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


EVENT_BUFFER_SIZE = 2000


class EventBuffer(logging.Handler):
    """The last `capacity` log records in memory, for the Operator's events panel.

    Each record is formatted by `JsonFormatter`, i.e. the exact line stdout gets (already
    redacted), and kept parsed back to a dict. stdout stays the source of record: this
    buffer is per process, lost on restart, and drops its oldest events when full.
    Thread-safe: Judges log from background tasks while requests read it.
    """

    def __init__(self, capacity: int = EVENT_BUFFER_SIZE):
        super().__init__()
        self.setFormatter(JsonFormatter())
        self._events: deque[dict] = deque(maxlen=capacity)
        self._mutex = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            event = json.loads(self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise into the caller
            self.handleError(record)
            return
        with self._mutex:
            self._events.append(event)

    def events(self) -> list[dict]:
        """Every buffered event, oldest first."""
        with self._mutex:
            return list(self._events)

    def for_conversation(self, conversation_id: str) -> list[dict]:
        """Events of the Conversation's traces, oldest first: the `trace_id`s of its buffered
        `request` events (so later Judge events of those traces are included)."""
        events = self.events()
        traces = {
            e["trace_id"] for e in events
            if e.get("event") == "request" and e.get("conversation_id") == conversation_id and e.get("trace_id")
        }
        return [e for e in events if e.get("trace_id") in traces]


# The production buffer, installed by `setup_logging` and read by the app unless one is injected.
EVENTS = EventBuffer()


def setup_logging() -> None:
    """Install the JSON handler on the `app` loggers once (production entrypoint only),
    plus `EVENTS`, the in-memory buffer of the same lines."""
    app_log = logging.getLogger("app")
    if EVENTS not in app_log.handlers:
        app_log.addHandler(EVENTS)
    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JsonFormatter) for h in app_log.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
