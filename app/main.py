import logging
import threading
import time
import uuid
from pathlib import Path
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import OPERATORS, AuthSettings, InvalidToken, Principal, role_for
from app.auth import Role as PrincipalRole
from app.errors import AuthError
from app.errors import error_response as _error
from app.graph import HISTORY_TURNS, Agent, Intent, Node, Source, agent_for, build_graph
from app.judge import FLAG_BELOW, run_judges
from app.llm import is_provider_error, provider_error_code
from app.observability import EVENTS, EventBuffer, LogPrivacy, log_request, setup_logging
from app.operator import operator_router
from app.store import Mode, ModeChanged, NewTurn, Role, Store

log = logging.getLogger(__name__)

# The demo client (one static page, no build step), served at `/` and `/static/`.
STATIC_DIR = Path(__file__).parent / "static"
# Only what the page needs from its own origin: no inline script, no third party.
PAGE_CSP = "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
# A fixed id with no fixture account, so the demo can show "account not found".
UNKNOWN_DEMO_USER = "nobody"


class ChatRequest(BaseModel):
    """The Merchant comes from the token; any `user_id` in the body is ignored."""

    message: str = Field(min_length=1)
    # Continue this Conversation; omitted, the Message starts a new one. Needs a token (anonymous → 401).
    conversation_id: str | None = None


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DevUser(BaseModel):
    id: str
    role: PrincipalRole


class DevUsers(BaseModel):
    users: list[DevUser]


class ChatResponse(BaseModel):
    answer: str
    # Who answers this Conversation now (ADR 0006); outside `bot` the graph did not run, so no Intent or Agent.
    mode: Mode
    intent: Intent | None
    agent: Agent | None
    sources: list[Source]
    steps: list[str]
    trace_id: str
    conversation_id: str | None = None


class ConversationSummary(BaseModel):
    id: str
    created_at: datetime
    updated_at: datetime
    mode: Mode


class ConversationList(BaseModel):
    conversations: list[ConversationSummary]


class TurnOut(BaseModel):
    id: int
    role: Role
    content: str
    intent: str | None
    sources: list[Source]
    created_at: datetime


class TurnList(BaseModel):
    conversation_id: str
    mode: Mode
    turns: list[TurnOut]


def load_default_index():
    """Open (or build) the Corpus index. Needs no LLM key."""
    from app.rag import FastEmbedder, build_index
    from app.settings import get_settings

    return build_index(get_settings().chroma_dir, FastEmbedder())


def build_default_graph(index):
    """The production graph: Router, Knowledge, Customer Support and Escalator Agents."""
    from app.escalator import make_escalator
    from app.knowledge import default_web_search, make_knowledge, make_search_corpus
    from app.llm import make_chat_model
    from app.router import make_router
    from app.settings import get_settings
    from app.support import make_support

    settings = get_settings()
    model = make_chat_model(settings)
    tools = [
        make_search_corpus(index, settings.relevance_threshold),
        default_web_search(settings.tavily_api_key),
    ]
    return build_graph(
        make_router(model), make_knowledge(model, tools), make_support(model), escalator=make_escalator(model)
    )


def create_app(
    graph: Any = None,
    load_index: Callable[[], Any] | None = None,
    judge_enabled: bool | None = None,
    judge_model: Any = None,
    log_privacy: LogPrivacy | None = None,
    auth: AuthSettings | None = None,
    store: Store | None = None,
    escalator: Node | None = None,
    events: EventBuffer | None = None,
) -> FastAPI:
    """`graph` is anything with `.invoke(state) -> state`; built lazily if omitted.

    Judges run after a 200 when `judge_enabled` (default: `JUDGE_ENABLED`);
    `judge_model` defaults to `JUDGE_MODEL` via the model factory; at startup a
    warning is logged if that equals `LLM_MODEL`.

    `log_privacy` defaults to `LOG_HASH_KEY` / `LOG_MESSAGES`, resolved at startup
    (or on the first request if the app was never started); an empty key is
    replaced by a random one, with a warning.

    `auth` (token secret, dev-login flag, clock) defaults to `JWT_SECRET` /
    `DEMO_LOGIN`, resolved at startup like `log_privacy`.

    `store` (Conversations and Turns) defaults to the SQLite file in `STATE_DIR`,
    resolved at startup like `log_privacy`.

    `escalator` (the Escalator Agent that rewrites a stale Handoff Brief on an
    Operator's claim) defaults to one on `LLM_MODEL`, built on first use.

    `events` (recent log lines for the Operator's events panel) defaults to
    `EVENTS`, the buffer `setup_logging` installs; an injected one must be
    attached to the `app` logger by the caller.

    `load_index` runs in a background thread at startup; until it returns,
    `/health` and `/chat` answer 503. Without it there is no index to wait for.
    """

    def _load() -> None:
        try:
            app.state.index = load_index()
            log.info("corpus index ready")
        except Exception:
            log.exception("corpus index failed to build")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        get_log_privacy()
        get_auth()
        purge_stale_conversations(get_store())
        if judge_model is None and judges_on():
            from app.settings import get_settings, warn_if_judge_not_independent

            warn_if_judge_not_independent(get_settings())
        if load_index is not None:
            app.state.index_thread = threading.Thread(target=_load, name="index", daemon=True)
            app.state.index_thread.start()
        yield

    app = FastAPI(title="Getnet Multi-Agent Support", lifespan=lifespan)
    app.state.graph = graph
    app.state.index = None
    app.state.needs_index = load_index is not None
    app.state.judge_model = judge_model
    app.state.log_privacy = log_privacy
    app.state.auth = auth
    app.state.store = store
    app.state.escalator = escalator

    def get_escalator() -> Node:
        if app.state.escalator is None:
            from app.escalator import make_escalator
            from app.llm import make_chat_model
            from app.settings import get_settings

            app.state.escalator = make_escalator(make_chat_model(get_settings()))
        return app.state.escalator

    def get_store() -> Store:
        if app.state.store is None:
            from app.settings import get_settings

            app.state.store = Store(get_settings().database_path)
        return app.state.store

    def purge_stale_conversations(store: Store) -> None:
        """Retention: drop Conversations idle for `CONVERSATION_RETENTION_DAYS`; logs only the count."""
        from app.settings import get_settings

        days = get_settings().conversation_retention_days
        purged = store.purge(timedelta(days=days))
        log.info("retention purge: deleted %d conversation(s) not updated in %d days", purged, days)

    def get_auth() -> AuthSettings:
        if app.state.auth is None:
            from app.settings import get_settings

            app.state.auth = AuthSettings.from_settings(get_settings())
        return app.state.auth

    def optional_principal(authorization: Annotated[str | None, Header()] = None) -> Principal | None:
        """The verified caller, or None (anonymous) without a token.

        A bad token is always 401, never downgraded to anonymous (ADR 0005).
        """
        if authorization is None:
            return None
        scheme, _, token = authorization.partition(" ")
        try:
            if scheme.lower() != "bearer" or not token.strip():
                raise InvalidToken("not a bearer token")
            return get_auth().verify(token.strip())
        except InvalidToken:
            raise AuthError(401, "invalid_token", "The token is invalid or expired; log in again.") from None

    def principal(caller: Annotated[Principal | None, Depends(optional_principal)]) -> Principal:
        """The verified caller; 401 without a token."""
        if caller is None:
            raise AuthError(401, "unauthorized", "Log in and send `Authorization: Bearer <token>`.")
        return caller

    def merchant(caller: Annotated[Principal | None, Depends(optional_principal)]) -> Principal | None:
        """A Merchant, or None for an anonymous visitor (Knowledge only); operators are 403."""
        if caller is not None and caller.role != "merchant":
            raise AuthError(403, "forbidden", "Only Merchants can use /chat.")
        return caller

    @app.exception_handler(AuthError)
    def auth_error(_request: Request, exc: AuthError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return _error(exc.status, exc.code, exc.message, uuid.uuid4().hex, headers)

    def demo_login_enabled() -> None:
        # Checked before body validation, so a disabled endpoint looks like any unknown path.
        if not get_auth().demo_login:
            raise HTTPException(status_code=404, detail="Not Found")

    def get_log_privacy() -> LogPrivacy:
        if app.state.log_privacy is None:
            from app.settings import get_settings

            app.state.log_privacy = LogPrivacy.from_settings(get_settings())
        return app.state.log_privacy

    def judges_on() -> bool:
        if judge_enabled is not None:
            return judge_enabled
        from app.settings import get_settings

        return get_settings().judge_enabled

    def get_judge_model():
        if app.state.judge_model is None:
            from app.llm import make_chat_model
            from app.settings import get_settings

            settings = get_settings()
            app.state.judge_model = make_chat_model(settings, settings.judge_model)
        return app.state.judge_model

    def judge(
        trace_id: str, message: str, result: dict, history: list[dict],
        brief: dict | None, conversation_id: str | None,
    ) -> None:
        """Runs after the reply is sent. `brief`: the Handoff Brief of an escalated Turn.
        `conversation_id`: where a low `answer` Score sets the Review flag (None for anonymous)."""
        try:
            model = get_judge_model()
        except Exception:
            log.exception("judge model unavailable trace_id=%s", trace_id)
            return
        verdicts = run_judges(
            model,
            privacy=get_log_privacy(),
            trace_id=trace_id,
            message=message,
            intent=result["intent"],
            answer=result.get("answer", ""),
            sources=result.get("sources", []),
            evidence=result.get("evidence", []),
            user_id=result.get("user_id", ""),
            # An escalated Turn: the brief is judged (stored, never logged) against the Conversation.
            handoff=brief,
            history=history,
        )
        answer = verdicts.get("answer")
        # Only the `answer` Score flags; never a Mode change, never blocks the Merchant (ADR 0006).
        if conversation_id is not None and answer is not None and answer.score < FLAG_BELOW:
            try:
                get_store().flag_for_review(conversation_id)
            except Exception:
                log.exception("review flag not set trace_id=%s", trace_id)

    def ready() -> bool:
        return not app.state.needs_index or app.state.index is not None

    @app.get("/health")
    def health():
        if not ready():
            return JSONResponse(status_code=503, content={"status": "starting"})
        return {"status": "ok"}

    @app.post("/dev/login", response_model=LoginResponse, dependencies=[Depends(demo_login_enabled)])
    def dev_login(request: LoginRequest):
        """Demo stand-in for an identity provider: "log in as" any user id."""
        return LoginResponse(access_token=get_auth().issue(request.user_id))

    @app.get("/dev/users", response_model=DevUsers, dependencies=[Depends(demo_login_enabled)])
    def dev_users():
        """Who the demo can log in as: fixture Merchants, mock Operators and one unknown id."""
        from app.support import load_merchants

        ids = [*load_merchants(get_auth().clock().date()), *sorted(OPERATORS), UNKNOWN_DEMO_USER]
        return DevUsers(users=[DevUser(id=i, role=role_for(i)) for i in ids])

    @app.get("/", include_in_schema=False)
    def page():
        """The demo client."""
        return FileResponse(STATIC_DIR / "index.html", headers={"Content-Security-Policy": PAGE_CSP})

    @app.get("/me")
    def me(caller: Annotated[Principal, Depends(principal)]):
        """The principal and, for a Merchant, their fixture account (null when there is none)."""
        body: dict[str, Any] = {"sub": caller.sub, "role": caller.role}
        if caller.role == "merchant":
            from app.support import load_merchants

            body["account"] = load_merchants(get_auth().clock().date()).get(caller.sub)
        return body

    @app.post("/chat", response_model=ChatResponse)
    def chat(
        request: ChatRequest,
        background: BackgroundTasks,
        caller: Annotated[Principal | None, Depends(merchant)],
    ):
        if caller is None and request.conversation_id is not None:
            raise AuthError(401, "unauthorized", "Conversations need a login: send `Authorization: Bearer <token>`.")
        user_id = caller.sub if caller is not None else None  # None: anonymous visitor
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()
        conversation_id = request.conversation_id

        def log_outcome(outcome: str, result: dict | None = None) -> None:
            log_request(
                privacy=get_log_privacy(),
                trace_id=trace_id,
                user_id=user_id,
                message=request.message,
                latency_ms=round((time.perf_counter() - started) * 1000),
                outcome=outcome,
                result=result,
                conversation_id=conversation_id,
            )

        def mode_changed(exc: ModeChanged) -> JSONResponse:
            """A racing request changed the Mode after it was read: 409, nothing stored (ADR 0006)."""
            if exc.mode == "closed":
                log_outcome("conversation_closed")
                return _error(409, "conversation_closed", "This Conversation is closed; start a new one.", trace_id)
            log_outcome("mode_changed")
            return _error(
                409, "mode_changed", "The Conversation's Mode changed while this Message was handled; send it again.",
                trace_id,
            )

        if not ready():
            log_outcome("starting")
            return _error(503, "starting", "The service is starting; try again shortly.", trace_id)
        # Someone else's Conversation looks exactly like one that doesn't exist.
        # (An anonymous request never gets here with a conversation_id: that was a 401 above.)
        conversation = None if conversation_id is None else get_store().conversation(conversation_id, user_id or "")
        if conversation_id is not None and conversation is None:
            log_outcome("conversation_not_found")
            return _error(404, "conversation_not_found", "Conversation not found.", trace_id)
        if conversation is not None and conversation.mode == "closed":
            log_outcome("conversation_closed")
            return _error(409, "conversation_closed", "This Conversation is closed; start a new one.", trace_id)
        if conversation is not None and conversation.mode in ("waiting_human", "human"):
            # Taken over (ADR 0006): kept for the Operator; no Agent answers, no Judges.
            try:
                get_store().append_turns(conversation.id, [NewTurn("user", request.message)],
                                         while_in=("waiting_human", "human"))
            except ModeChanged as exc:
                return mode_changed(exc)
            log_outcome("queued")
            return ChatResponse(
                answer="", mode=conversation.mode, intent=None, agent=None, sources=[], steps=[],
                trace_id=trace_id, conversation_id=conversation.id,
            )
        # Prior Turns as context for the Agents (role + text only; account facts come from fresh tool calls).
        history = [] if conversation_id is None else [
            {"role": t.role, "content": t.content} for t in get_store().turns(conversation_id)[-HISTORY_TURNS:]
        ]
        try:
            if app.state.graph is None:
                app.state.graph = build_default_graph(app.state.index)
            result = app.state.graph.invoke(
                {"message": request.message, "user_id": user_id, "history": history}
            )
        except Exception as exc:
            if is_provider_error(exc):
                log.warning("provider error trace_id=%s: %r", trace_id, exc)
                log_outcome("provider_error")
                if provider_error_code(exc) == "rate_limited":
                    return _error(503, "rate_limited", "The language model is rate limited; try again shortly.", trace_id)
                return _error(503, "provider_unavailable", "The language model provider is unavailable; try again shortly.", trace_id)
            log.exception("unexpected error trace_id=%s", trace_id)
            log_outcome("error")
            return _error(500, "internal_error", "Internal server error.", trace_id)

        intent = result["intent"]
        # An Escalation (ADR 0006): the graph never escalates an anonymous visitor.
        brief = result.get("handoff") if user_id is not None else None
        # Only after a successful run, so a failed one stores nothing. Sources, never Evidence.
        # Anonymous requests are stateless: no Conversation, nothing stored.
        if user_id is not None:
            turns = [
                NewTurn("user", request.message, intent=intent),
                NewTurn("assistant", result.get("answer", ""), intent=intent, sources=result.get("sources", [])),
            ]
            # Each write is conditional on the `bot` Mode read above: a racing Escalation or
            # Operator action since then means 409 and nothing stored.
            try:
                if brief is not None:
                    # One transaction: Turns, the open Handoff (the brief is stored, never logged), Mode waiting_human.
                    conversation_id = get_store().escalate(conversation_id, user_id, turns, brief)
                elif conversation_id is None:
                    conversation_id = get_store().create_conversation(user_id)
                    get_store().append_turns(conversation_id, turns)
                else:
                    get_store().append_turns(conversation_id, turns, while_in=("bot",))
            except ModeChanged as exc:
                return mode_changed(exc)
        log_outcome("ok", result)
        if judges_on():
            background.add_task(
                judge, trace_id, request.message, result, history, brief,
                None if user_id is None else conversation_id,
            )
        return ChatResponse(
            answer=result.get("answer", ""),
            mode="bot" if brief is None else "waiting_human",
            intent=intent,
            agent=agent_for(intent, anonymous=user_id is None, escalated=brief is not None),
            sources=result.get("sources", []),
            steps=result.get("steps", []),
            trace_id=trace_id,
            conversation_id=conversation_id,
        )

    def owner(caller: Annotated[Principal, Depends(principal)]) -> Principal:
        """A Merchant who owns Conversations: 401 without a token, operators 403 (theirs come with takeover)."""
        if caller.role != "merchant":
            raise AuthError(403, "forbidden", "Only Merchants have Conversations.")
        return caller

    @app.get("/conversations", response_model=ConversationList)
    def list_conversations(caller: Annotated[Principal, Depends(owner)]):
        """The caller's Conversations, most recently updated first."""
        return ConversationList(conversations=[
            ConversationSummary(id=c.id, created_at=c.created_at, updated_at=c.updated_at, mode=c.mode)
            for c in get_store().conversations(caller.sub)
        ])

    @app.get("/conversations/{conversation_id}/turns", response_model=TurnList)
    def list_turns(
        conversation_id: str,
        caller: Annotated[Principal, Depends(owner)],
        after: Annotated[int, Query(ge=0, description="Only Turns with a larger id (for polling).")] = 0,
    ):
        """The Conversation's Turns, oldest first; another Merchant's or an unknown id is the same 404 as /chat."""
        conversation = get_store().conversation(conversation_id, caller.sub)
        if conversation is None:
            return _error(404, "conversation_not_found", "Conversation not found.", uuid.uuid4().hex)
        return TurnList(conversation_id=conversation_id, mode=conversation.mode, turns=[
            TurnOut(id=t.id, role=t.role, content=t.content, intent=t.intent,
                    sources=[Source(url=s["url"], title=s["title"]) for s in t.sources], created_at=t.created_at)
            for t in get_store().turns(conversation_id, after=after)
        ])

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(operator_router(
        principal=principal, store=get_store, today=lambda: get_auth().clock().date(), escalator=get_escalator,
        events=EVENTS if events is None else events,
    ))

    return app


setup_logging()
app = create_app(load_index=load_default_index)
