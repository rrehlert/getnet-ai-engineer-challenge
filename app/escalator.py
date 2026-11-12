"""Escalator Agent: one structured call that writes the Handoff Brief and the transfer message.

It runs on any Escalation (ADR 0006): the Merchant's `human` Intent, or a
specialist that set `escalation_reason`. It summarises; it calls no tools and
touches no store. The brief is stored by `/chat`, never logged.
"""

import json
import logging
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from pydantic import BaseModel, Field

from app.agents import LANGUAGE_RULE, conversation_messages
from app.graph import (
    ESCALATOR_STEP,
    HISTORY_TURNS,
    TRANSFER_FALLBACK,
    GraphState,
    HandoffBrief,
    Node,
    Priority,
    escalation_reason,
    fallback_brief,
)
from app.judge import format_evidence
from app.store import Turn

log = logging.getLogger(__name__)

PROMPT = """You are the Escalator Agent of Getnet's support assistant for merchants.
The Conversation below is being handed to a human Operator. You do not answer the
Merchant's question and you call no tools: you write a Handoff Brief for the Operator
and a short transfer message for the Merchant.

Escalation reason: {reason}
Intent: {intent}
Evidence (tool output the Agents saw this Turn):
{evidence}
Sources (pages the Agents cited this Turn): {sources}

Brief rules:
- Use only what is in the Conversation, the reason, the Evidence and the Sources.
  Never invent amounts, dates, codes, account facts or steps that weren't taken.
- `attempted`: what the Agents already tried or told the Merchant; "nothing yet" if nothing.
- `priority`: high when the Merchant can't sell or is losing money now, low for general
  questions, otherwise normal.
- `language`: the language of the Merchant's Messages, e.g. pt-BR or en.
- `suggested_reply`: a reply the Operator may edit and send, written in `language`
  (the Merchant's language, not the language of these instructions).

`transfer_message`: one or two sentences, in the SAME language as the Merchant's
latest Message, saying they are being transferred to a person (a human attendant; don't
use the internal word "Operator" with the Merchant) and can keep writing while they wait. """ + LANGUAGE_RULE


class EscalatorOutput(BaseModel):
    """The Handoff Brief for the Operator, plus the transfer message for the Merchant."""

    reason: str = Field(description="Why the Conversation is escalated.")
    customer_ask: str = Field(description="What the Merchant wants, in one sentence.")
    summary: str = Field(description="Short summary of the Conversation so far.")
    attempted: str = Field(description="What the Agents already tried or told the Merchant.")
    category: str = Field(description="One word or two: e.g. terminal, settlement, transaction, product, other.")
    priority: Priority = "normal"
    language: str = Field(description="The language of the Merchant's Messages, e.g. pt-BR or en.")
    suggested_reply: str = Field(description="A reply the Operator may edit and send, written in `language`.")
    transfer_message: str = Field(default="", description="Tells the Merchant they are being transferred.")


def _brief(parsed: EscalatorOutput) -> HandoffBrief:
    return HandoffBrief(**parsed.model_dump(exclude={"transfer_message"}))


def rewrite_state(owner: str, turns: Sequence[Turn], brief: HandoffBrief) -> GraphState:
    """The Escalator's input for rewriting a stale `brief` on claim: the latest Turn as the
    Message, the Turns before it as history, the brief's reason as the escalation reason."""
    *prior, latest = turns
    return {
        "message": latest.content,
        "user_id": owner,
        "history": [{"role": t.role, "content": t.content} for t in prior[-HISTORY_TURNS:]],
        # The escalated Turn's Intent; Turns sent while waiting have none.
        "intent": next((t.intent for t in reversed(turns) if t.intent), "human"),
        "escalation_reason": brief["reason"],
        "evidence": [],  # Evidence isn't stored; the brief being rewritten already used it
        "sources": [],
        "steps": [],
        "tokens": 0,
    }


def make_escalator(model: BaseChatModel) -> Node:
    # function_calling, as in the Router: unparseable output fills `parsing_error` instead of raising.
    structured = model.with_structured_output(EscalatorOutput, include_raw=True, method="function_calling")

    def escalate(state: GraphState) -> dict:
        system = PROMPT.format(
            reason=escalation_reason(state),
            intent=state.get("intent", "human"),
            evidence=format_evidence(state.get("evidence", [])),
            sources=json.dumps(state.get("sources", []), ensure_ascii=False),
        )
        result = structured.invoke([SystemMessage(system), *conversation_messages(state)])
        usage = getattr(result.get("raw"), "usage_metadata", None) or {}
        update = {"steps": [ESCALATOR_STEP], "tokens": usage.get("total_tokens", 0)}
        parsed = result.get("parsed")

        if result.get("parsing_error") is not None or not isinstance(parsed, EscalatorOutput):
            log.warning("escalator output unparseable; using the fallback brief and transfer message")
            return {**update, "answer": TRANSFER_FALLBACK, "handoff": fallback_brief(state)}
        message = parsed.transfer_message.strip() or TRANSFER_FALLBACK
        return {**update, "answer": message, "handoff": _brief(parsed)}

    return escalate
