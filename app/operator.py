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
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import Principal
from app.errors import AuthError, error_response
from app.graph import HISTORY_TURNS, GraphState, Node, Priority, Source, fallback_brief
from app.store import Conversation, Mode, Role, Store

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
    brief: dict  # the Handoff Brief
    created_at: datetime
    claimed_by: str | None
    claimed_at: datetime | None
    outcome: Literal["handed_back", "closed"] | None
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
    handoff: HandoffOut | None  # the current (latest) Handoff; None for a flagged Conversation never escalated
    account: dict | None  # the Merchant's fixture account; None when there is none
    turns: list[OperatorTurn]


class ReviewItem(BaseModel):
    conversation_id: str
    mode: Mode
    created_at: datetime
    updated_at: datetime


class ReviewList(BaseModel):
    conversations: list[ReviewItem]


def _not_found():
    return error_response(404, "conversation_not_found", "Conversation not found.", uuid.uuid4().hex)


def operator_router(
    *,
    principal: Callable[..., Principal],
    store: Callable[[], Store],
    today: Callable[[], date],
    escalator: Callable[[], Node],
) -> APIRouter:
    """`principal`: the app's dependency for the verified caller (401 without a token).
    Providers, called per request: `store`; `today`, the date account data is resolved for;
    `escalator`, the Escalator Agent that rewrites a stale brief on claim."""

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
                category=h.brief.get("category", ""),
                priority=h.brief.get("priority", "normal"),
                customer_ask=h.brief.get("customer_ask", ""),
            )
            for h in store().queue()
        ])

    def view(conversation: Conversation) -> ConversationDetail:
        # Lazily, like `/me`: keeps the agent stack out of app import.
        from app.support import load_merchants

        handoffs = store().handoffs(conversation.id)
        current = handoffs[-1] if handoffs else None
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
        handoffs = store().handoffs(conversation_id)
        handoff = handoffs[-1] if handoffs and handoffs[-1].ended_at is None else None
        turns = store().turns(conversation_id)
        if handoff is None or not turns or turns[-1].id <= (handoff.brief_turn_id or 0):
            return
        latest = turns[-1]
        state: GraphState = {
            "message": latest.content,
            "user_id": store().operator_conversation(conversation_id).owner,
            "history": [{"role": t.role, "content": t.content} for t in turns[:-1][-HISTORY_TURNS:]],
            # The escalated Turn's Intent; Turns sent while waiting have none.
            "intent": next((t.intent for t in reversed(turns) if t.intent), "human"),
            "escalation_reason": handoff.brief.get("reason", ""),
            "evidence": [],  # Evidence isn't stored; the brief being rewritten already used it
            "sources": [],
            "steps": [],
            "tokens": 0,
        }
        try:
            brief = escalator()(state).get("handoff")
        except Exception as exc:  # noqa: BLE001 - any failure keeps the old brief; no traceback (it may quote content)
            log.warning("brief rewrite failed on claim conversation_id=%s (%s); keeping the old brief",
                        conversation_id, type(exc).__name__)
            return
        if not brief or brief == fallback_brief(state):
            log.warning("brief rewrite unusable on claim conversation_id=%s; keeping the old brief", conversation_id)
            return
        store().replace_brief(handoff.id, dict(brief), latest.id)

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

    return router
