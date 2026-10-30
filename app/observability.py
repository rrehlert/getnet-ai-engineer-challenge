"""Structured JSON logging (spec: Observability). Each event is one JSON log line."""

import json
import logging
import sys
from typing import get_args

from app.graph import Agent, Intent, agent_for

log = logging.getLogger("app.events")

AGENTS = set(get_args(Agent))
MESSAGE_LIMIT = 500


def emit(event: str, level: int = logging.INFO, **fields) -> None:
    log.log(level, json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


def log_request(
    *, trace_id: str, user_id: str, message: str, latency_ms: int, outcome: str, result: dict | None = None
) -> None:
    result = result or {}
    intent: Intent | None = result.get("intent")
    emit(
        "request",
        trace_id=trace_id,
        user_id=user_id,
        message=message[:MESSAGE_LIMIT],
        intent=intent,
        agent=None if intent is None else agent_for(intent),
        tools=[s for s in result.get("steps", []) if s not in AGENTS],
        tokens=result.get("tokens", 0),
        latency_ms=latency_ms,
        outcome=outcome,
    )


class JsonFormatter(logging.Formatter):
    """Event lines pass through as JSON; other records are wrapped in a JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        try:
            data = json.loads(msg)
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            data = {"event": "log", "logger": record.name, "message": msg}
            if record.exc_info:
                data["exc"] = self.formatException(record.exc_info)
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
