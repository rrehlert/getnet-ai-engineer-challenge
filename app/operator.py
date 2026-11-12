"""Operator API (ADR 0006): the human side of a takeover.

Every route needs role `operator` (no token 401, a Merchant 403). Operators see
only Conversations that had a Handoff or carry a Review flag; any other id is
404, like an unknown one. Writes are audited (who, what, when; no content);
reads are not.

`operator_router(...)` builds the routes from the app's providers, so new
Operator endpoints go here, next to the ones that exist.
"""

import dataclasses
import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import Principal
from app.errors import AuthError, error_response
from app.graph import HandoffBrief, Node, Priority, Source, fallback_brief
from app.observability import EventBuffer
from app.store import (
    ActionResult,
    Conversation,
    HandoffOutcome,
    Mode,
    NewTurn,
    Role,
    Store,
)

log = logging.getLogger(__name__)


class QueueItem(BaseModel):
    conversation_id: str
    created_at: datetime  # when the Handoff opened (the Merchant started waiting)
    category: str
    priority: Priority
    customer_ask: str


class Queue(BaseModel):
    conversations: list[QueueItem]


class HandoffOut(BaseModel):
    brief: HandoffBrief
    created_at: datetime
    claimed_by: str | None
    claimed_at: datetime | None
    outcome: HandoffOutcome | None
    ended_at: datetime | None


class OperatorTurn(BaseModel):
    id: int
    role: Role
    content: str
    intent: str | None
    sources: list[Source]
    created_at: datetime


class ConversationDetail(BaseModel):
    conversation_id: str
    merchant: str
    mode: Mode
    needs_review: bool
    created_at: datetime
    updated_at: datetime
    handoff: HandoffOut | None  # `Store.current_handoff`; None for a flagged Conversation never escalated
    account: dict | None  # the Merchant's fixture account; None when there is none
    turns: list[OperatorTurn]


class ReviewItem(BaseModel):
    conversation_id: str
    mode: Mode
    created_at: datetime
    updated_at: datetime


class ReviewList(BaseModel):
    conversations: list[ReviewItem]


class EventList(BaseModel):
    # Log events as stdout has them (redacted JSON objects); their fields vary by event.
    events: list[dict]


# Fixed bilingual `assistant` Turns that tell the polling Merchant (and the bot's history) about a handover.
HANDBACK_TURN = (
    "Você está de volta com o assistente virtual. Como posso ajudar? "
    "You're back with the virtual assistant. How can I help?"
)
CLOSE_TURN = (
    "Esta conversa foi encerrada pelo atendente. Para continuar, inicie uma nova conversa. "
    "This conversation was closed by the agent. To continue, start a new conversation."
)


class ReplyRequest(BaseModel):
    content: str = Field(min_length=1)
    used_suggestion: bool  # the Handoff Brief's suggested reply sent unchanged (audited)


def _not_found():
    return error_response(404, "conversation_not_found", "Conversation not found.", uuid.uuid4().hex)


def operator_router(
    *,
    principal: Callable[..., Principal],
    store: Callable[[], Store],
    today: Callable[[], date],
    escalator: Callable[[], Node],
    events: EventBuffer,
) -> APIRouter:
    """`principal`: the app's dependency for the verified caller (401 without a token).
    Providers, called per request: `store`; `today`, the date account data is resolved for;
    `escalator`, the Escalator Agent that rewrites a stale brief on claim.
    `events`: the in-memory buffer of recent log lines the events panel reads."""

    def operator(caller: Annotated[Principal, Depends(principal)]) -> Principal:
        if caller.role != "operator":
            raise AuthError(403, "forbidden", "Only Operators can use /operator.")
        return caller

    router = APIRouter(prefix="/operator")
    Operator = Annotated[Principal, Depends(operator)]

    @router.get("/queue", response_model=Queue)
    def queue(caller: Operator):
        """Conversations waiting for an Operator, oldest Handoff first, with the brief's key fields."""
        return Queue(conversations=[
            QueueItem(
                conversation_id=h.conversation_id,
                created_at=h.created_at,
                category=h.brief["category"],
                priority=h.brief["priority"],
                customer_ask=h.brief["customer_ask"],
            )
            for h in store().queue()
        ])

    def view(conversation: Conversation) -> ConversationDetail:
        # Lazily, like `/me`: keeps the agent stack out of app import.
        from app.support import load_merchants

        current = store().current_handoff(conversation.id)
        return ConversationDetail(
            conversation_id=conversation.id,
            merchant=conversation.owner,
            mode=conversation.mode,
            needs_review=conversation.needs_review,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            handoff=None if current is None else HandoffOut(
                brief=current.brief, created_at=current.created_at,
                claimed_by=current.claimed_by, claimed_at=current.claimed_at,
                outcome=current.outcome, ended_at=current.ended_at,
            ),
            # Resolved by software from the fixture, never by a model.
            account=load_merchants(today()).get(conversation.owner),
            turns=[
                OperatorTurn(id=t.id, role=t.role, content=t.content, intent=t.intent,
                             sources=[Source(url=s["url"], title=s["title"]) for s in t.sources],
                             created_at=t.created_at)
                for t in store().turns(conversation.id)
            ],
        )

    @router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
    def detail(conversation_id: str, caller: Operator):
        """The whole Conversation (Turns sent while waiting included), its current Handoff and the Merchant's account."""
        conversation = store().operator_conversation(conversation_id)
        if conversation is None:
            return _not_found()
        return view(conversation)

    @router.get("/conversations/{conversation_id}/events", response_model=EventList)
    def conversation_events(conversation_id: str, caller: Operator):
        """Buffered log events of the Conversation's traces, oldest first, including Judge events
        logged after the reply. Recent only: per process, lost on restart, oldest dropped first."""
        conversation = store().operator_conversation(conversation_id)
        if conversation is None:
            return _not_found()
        return EventList(events=events.for_conversation(conversation.id))

    @router.post("/conversations/{conversation_id}/claim", response_model=ConversationDetail)
    def claim(conversation_id: str, caller: Operator):
        """`waiting_human` → `human` for the caller; already claimed or any other Mode → 409.
        Returns the detail view, so the claiming Operator reads the current brief."""
        if store().operator_conversation(conversation_id) is None:
            return _not_found()
        if not store().claim(conversation_id, caller.sub):
            return error_response(
                409, "not_waiting", "This Conversation is not waiting for an Operator (already claimed or not escalated).",
                uuid.uuid4().hex,
            )
        # After the claim, outside its transaction: the model call never holds the database.
        refresh_brief(conversation_id)
        return view(store().operator_conversation(conversation_id))

    def refresh_brief(conversation_id: str) -> None:
        """If the Merchant wrote after the brief, the Escalator Agent rewrites it. A failed or
        unusable rewrite keeps the old brief (logged without content); the claim stands either way."""
        from app.escalator import rewrite_state  # lazily, like `load_merchants`

        handoff = store().current_handoff(conversation_id)
        turns = store().turns(conversation_id)
        # Only the open Handoff's brief is rewritten (just claimed, so it is open unless closed meanwhile).
        if handoff is None or handoff.ended_at is not None or not turns or turns[-1].id <= (handoff.brief_turn_id or 0):
            return
        latest = turns[-1]
        state = rewrite_state(store().operator_conversation(conversation_id).owner, turns, handoff.brief)
        try:
            brief = escalator()(state).get("handoff")
        except Exception as exc:  # noqa: BLE001 - any failure keeps the old brief; no traceback (it may quote content)
            log.warning("brief rewrite failed on claim conversation_id=%s (%s); keeping the old brief",
                        conversation_id, type(exc).__name__)
            return
        if not brief or brief == fallback_brief(state):
            log.warning("brief rewrite unusable on claim conversation_id=%s; keeping the old brief", conversation_id)
            return
        store().replace_brief(handoff.id, brief, latest.id)

    # --- Review flag (low `answer` Judge Scores): read after the fact, never a Mode change ---

    @router.get("/review", response_model=ReviewList)
    def review(caller: Operator):
        """Conversations with the Review flag, any Mode, most recently updated first."""
        return ReviewList(conversations=[
            ReviewItem(conversation_id=c.id, mode=c.mode, created_at=c.created_at, updated_at=c.updated_at)
            for c in store().review_list()
        ])

    @router.post("/conversations/{conversation_id}/reviewed", response_model=ConversationDetail)
    def reviewed(conversation_id: str, caller: Operator):
        """Clears the Review flag (audited); the Mode stays. Not flagged → 409. A never-escalated
        Conversation is no longer visible to Operators afterwards; the response is its last view."""
        conversation = store().operator_conversation(conversation_id)
        if conversation is None:
            return _not_found()
        if not store().clear_review(conversation_id, caller.sub):
            return error_response(409, "not_flagged", "This Conversation has no Review flag.", uuid.uuid4().hex)
        return view(dataclasses.replace(conversation, needs_review=False))

    # --- Reply, handback, close: the claiming Operator's actions ---

    def act(conversation_id: str, action: Callable[[], ActionResult]):
        """Run an Operator action on a visible Conversation; 403 when another Operator holds
        the claim, 409 when the Mode doesn't allow it. Returns the detail view on success."""
        if store().operator_conversation(conversation_id) is None:
            return _not_found()
        result = action()
        if result == "not_claimer":
            return error_response(403, "not_claimer", "Another Operator has claimed this Conversation.",
                                  uuid.uuid4().hex)
        if result == "wrong_mode":
            return error_response(409, "wrong_mode", "This action is not allowed in the Conversation's current Mode.",
                                  uuid.uuid4().hex)
        return view(store().operator_conversation(conversation_id))

    @router.post("/conversations/{conversation_id}/reply", response_model=ConversationDetail)
    def reply(conversation_id: str, request: ReplyRequest, caller: Operator):
        """The claiming Operator's message to the Merchant, stored as an `operator` Turn; `human` Mode only."""
        return act(conversation_id, lambda: store().reply(
            conversation_id, caller.sub, NewTurn("operator", request.content), request.used_suggestion))

    @router.post("/conversations/{conversation_id}/handback", response_model=ConversationDetail)
    def handback(conversation_id: str, caller: Operator):
        """`human` → `bot` by the claiming Operator; the Merchant sees `HANDBACK_TURN`."""
        return act(conversation_id, lambda: store().hand_back(
            conversation_id, caller.sub, NewTurn("assistant", HANDBACK_TURN)))

    @router.post("/conversations/{conversation_id}/close", response_model=ConversationDetail)
    def close(conversation_id: str, caller: Operator):
        """→ `closed`: by the claiming Operator in `human`, or by any Operator in `waiting_human`
        (spam, Merchant gave up; no claim needed). The Merchant sees `CLOSE_TURN`."""
        return act(conversation_id, lambda: store().close(
            conversation_id, caller.sub, NewTurn("assistant", CLOSE_TURN)))

    return router
