"""LLM Judges (spec: Observability). Each Judge Type writes one `event:"judge"` line.

Runs after the reply is sent; failures are logged, never raised. `run_judges` also
returns the verdicts, so the eval runner can aggregate them.
"""

import json
import logging
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field, model_validator

from app.graph import Evidence, Intent
from app.observability import LogPrivacy, emit
from app.router import INTENT_POLICY

log = logging.getLogger(__name__)

FLAG_BELOW = 0.7
# Total characters of Evidence shown to the `answer` Judge.
EVIDENCE_CAP = 6000


class Verdict(BaseModel):
    """Your rating of the reply."""

    score: float = Field(ge=0, le=1, description="0 = wrong/bad, 1 = right/excellent")
    reason: str = Field(description="One short sentence explaining the score.")


class Coverage(Verdict):
    """Which specialists the Message needed and whether the reply covered all of it."""

    intents_needed: list[Intent] = Field(
        description="Every Intent the Message needs to be answered fully (more than one for a Mixed question)."
    )
    fully_answered: bool = Field(description="True if the reply answers every part of the Message.")
    missing: str = Field(default="", description="The parts left unanswered; empty when fully answered.")

    @model_validator(mode="after")
    def _full_coverage_scores_one(self) -> "Coverage":
        if self.fully_answered:
            self.score = 1.0
            self.missing = ""
        return self


# Reasons are logged (and redacted regardless); keep personal data out of them in the first place.
NO_PERSONAL_DATA = (
    "\nIn your reason, do not quote personal data (CPF, CNPJ, card numbers, emails, phone numbers, Pix keys)."
)

ROUTE_PROMPT = (
    """You judge the Router of Getnet merchant support. Score it against this routing policy
exactly, not your own view of what is in scope:

"""
    + INTENT_POLICY
    + """

The Merchant is the user id given; a Message asking about any other user id is another
merchant's data. Refusing must be warranted. The Router picks exactly one Intent: for a
Message that needs more than one specialist (e.g. the Merchant's own account AND Getnet
products in general), choosing any one of the needed Intents is correct; do not mark it
down for not choosing both. Was the chosen Intent right under this
policy? Score 0-1."""
    + NO_PERSONAL_DATA
)

ANSWER_RUBRICS = {
    "knowledge": "Every claim in the reply is supported by the Evidence, and the reply actually answers "
    "the question (saying plainly that nothing was found is fine when the Evidence has nothing relevant).",
    "support": "Every claim in the reply (amounts, dates, statuses, codes, hints) is supported by the "
    "account Evidence; the reply addresses the Merchant's issue and states amounts in R$.",
    "unsupported": "The reply is polite, in the Message's language, and offers what the system can help with "
    "(Getnet products/fees and the Merchant's own account).",
}

# An anonymous visitor's account question gets the fixed login reply, not account data.
ANONYMOUS_SUPPORT_RUBRIC = (
    "The visitor is not logged in, so the reply must give no account data and ask them to log in "
    "to see their account, offering help with Getnet products meanwhile."
)
ANONYMOUS_MERCHANT = "none (a visitor who is not logged in; account questions are still `support`)"
# Without it the coverage Judge marks the login reply as leaving the account question unanswered.
ANONYMOUS_COVERAGE_RULE = (
    "\n\nThe visitor is not logged in, so account data must not be given: for a `support` part, "
    "asking them to log in fully answers it."
)

ANSWER_PROMPT = """You judge a reply from Getnet merchant support.
Evidence is the tool output the Agent actually saw while answering. A claim that the
Evidence does not support counts against the reply, however plausible it sounds.
Rubric for Intent '{intent}': {rubric} Score 0-1.""" + NO_PERSONAL_DATA


COVERAGE_PROMPT = (
    """You judge whether a reply from Getnet merchant support covers everything the Message asks.
Each Intent below is handled by one specialist; the Router picks only one per Message:

"""
    + INTENT_POLICY
    + """

List every Intent the Message needs to be answered fully: a Message that asks about the
Merchant's own account AND about Getnet products in general needs both `support` and
`knowledge`. `unsupported` only on its own, for a Message the system must refuse entirely.
Then say whether the reply answers every part, and what is missing. Score 0-1: 1 when fully
answered, lower the more of the Message is left unanswered."""
    + NO_PERSONAL_DATA
)


def format_evidence(evidence: Sequence[Evidence]) -> str:
    """Evidence items in order, cut at `EVIDENCE_CAP` characters in total with a marker."""
    if not evidence:
        return "(none)"
    text = "\n\n".join(f"[{i}] {e['tool']}\n{e['content']}" for i, e in enumerate(evidence, 1))
    if len(text) <= EVIDENCE_CAP:
        return text
    return text[:EVIDENCE_CAP] + f"\n[Evidence truncated: {len(text) - EVIDENCE_CAP} more characters cut]"


def _route_input(message: str, intent: Intent, user_id: str | None = "", **_) -> list[tuple[str, str]]:
    merchant = ANONYMOUS_MERCHANT if user_id is None else user_id
    return [("system", ROUTE_PROMPT), ("human", f"Merchant: {merchant}\nMessage: {message}\nIntent: {intent}")]


def _answer_input(
    message: str, intent: Intent, answer: str, sources: list, evidence: Sequence[Evidence], user_id: str | None = "", **_
) -> list[tuple[str, str]]:
    if user_id is None and intent == "support":
        rubric = ANONYMOUS_SUPPORT_RUBRIC
    else:
        rubric = ANSWER_RUBRICS.get(intent, ANSWER_RUBRICS["knowledge"])
    human = (
        f"Message: {message}\nIntent: {intent}\nReply: {answer}\n"
        f"Sources: {json.dumps(sources, ensure_ascii=False)}\n"
        f"Evidence: {format_evidence(evidence)}"
    )
    return [("system", ANSWER_PROMPT.format(intent=intent, rubric=rubric)), ("human", human)]


def _coverage_input(message: str, intent: Intent, answer: str, user_id: str | None = "", **_) -> list[tuple[str, str]]:
    system = COVERAGE_PROMPT + (ANONYMOUS_COVERAGE_RULE if user_id is None else "")
    merchant = ANONYMOUS_MERCHANT if user_id is None else user_id
    human = f"Merchant: {merchant}\nMessage: {message}\nIntent chosen: {intent}\nReply: {answer}"
    return [("system", system), ("human", human)]


# Judge Type -> (structured output schema, prompt builder)
JUDGES = {
    "route": (Verdict, _route_input),
    "answer": (Verdict, _answer_input),
    "coverage": (Coverage, _coverage_input),
}


def run_judges(
    model: BaseChatModel,
    *,
    privacy: LogPrivacy,
    trace_id: str,
    message: str,
    intent: Intent,
    answer: str,
    sources: list,
    evidence: Sequence[Evidence],
    user_id: str | None = "",
) -> dict[str, Verdict]:
    """Run every Judge Type, log one line each, and return the verdicts by Judge Type.

    `user_id` None means an anonymous visitor (not logged in).

    A Judge that fails is logged as an error and left out of the result.
    """
    texts = privacy.text_fields(message=message, answer=answer)
    verdicts: dict[str, Verdict] = {}
    for judge_type, (schema, build_input) in JUDGES.items():
        try:
            verdict = model.with_structured_output(schema, method="function_calling").invoke(
                build_input(
                    message=message,
                    intent=intent,
                    answer=answer,
                    sources=sources,
                    evidence=evidence,
                    user_id=user_id,
                )
            )
            if not isinstance(verdict, schema):
                raise ValueError(f"no verdict returned: {verdict!r}")
        except Exception as exc:
            log.error("judge %s failed trace_id=%s: %r", judge_type, trace_id, exc)
            continue
        verdicts[judge_type] = verdict
        extra = verdict.model_dump(exclude={"score", "reason"}) if isinstance(verdict, Coverage) else {}
        emit(
            "judge",
            logging.WARNING if verdict.score < FLAG_BELOW else logging.INFO,
            unredacted=texts,
            judge_type=judge_type,
            trace_id=trace_id,
            intent=intent,
            judge_score=verdict.score,
            reason=verdict.reason,
            **extra,
        )
    return verdicts
