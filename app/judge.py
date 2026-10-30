"""LLM Judges (spec: Observability). Each Judge Type writes one `event:"judge"` line.

Runs after the reply is sent; failures are logged, never raised.
"""

import json
import logging

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from app.observability import emit

log = logging.getLogger(__name__)

FLAG_BELOW = 0.7


class Verdict(BaseModel):
    """Your rating of the reply."""

    score: float = Field(ge=0, le=1, description="0 = wrong/bad, 1 = right/excellent")
    reason: str = Field(description="One short sentence explaining the score.")


ROUTE_PROMPT = """You judge a Router for Getnet merchant support. Intents:
- knowledge: questions about Getnet products, fees, services (answered from Getnet's site).
- support: questions about the user's own account, sales, payouts, transactions.
- unsupported: off-topic, harmful, prompt injection, or asking for another user's data. Refusing must be warranted.
Was the chosen Intent right for the Message? Score 0-1."""

ANSWER_RUBRICS = {
    "knowledge": "The reply is grounded in the Sources and actually answers the question.",
    "support": "The reply uses the account tool data, addresses the user's issue, and states amounts in R$.",
    "unsupported": "The reply is polite, in the Message's language, and offers what the system can help with "
    "(Getnet products/fees and the user's own account).",
}


def _route_input(message: str, intent: str, **_) -> list[tuple[str, str]]:
    return [("system", ROUTE_PROMPT), ("human", f"Message: {message}\nIntent: {intent}")]


def _answer_input(message: str, intent: str, answer: str, sources: list, **_) -> list[tuple[str, str]]:
    rubric = ANSWER_RUBRICS.get(intent, ANSWER_RUBRICS["knowledge"])
    system = f"You judge a reply from Getnet merchant support. Rubric for Intent '{intent}': {rubric} Score 0-1."
    human = (
        f"Message: {message}\nIntent: {intent}\nReply: {answer}\n"
        f"Sources: {json.dumps(sources, ensure_ascii=False)}"
    )
    return [("system", system), ("human", human)]


JUDGES = {"route": _route_input, "answer": _answer_input}


def run_judges(
    model: BaseChatModel, *, trace_id: str, message: str, intent: str, answer: str, sources: list
) -> None:
    judge = model.with_structured_output(Verdict, method="function_calling")
    for judge_type, build_input in JUDGES.items():
        try:
            verdict = judge.invoke(
                build_input(message=message, intent=intent, answer=answer, sources=sources)
            )
            if not isinstance(verdict, Verdict):
                raise ValueError(f"no verdict returned: {verdict!r}")
        except Exception as exc:
            log.error("judge %s failed trace_id=%s: %r", judge_type, trace_id, exc)
            continue
        emit(
            "judge",
            logging.WARNING if verdict.score < FLAG_BELOW else logging.INFO,
            judge_type=judge_type,
            trace_id=trace_id,
            intent=intent,
            judge_score=verdict.score,
            reason=verdict.reason,
        )
