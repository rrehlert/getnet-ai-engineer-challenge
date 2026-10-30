import logging
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.graph import Source, build_graph
from app.judge import run_judges
from app.llm import is_provider_error, provider_error_code
from app.observability import log_request, setup_logging

log = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class ChatResponse(BaseModel):
    answer: str
    intent: str
    agent: str
    sources: list[Source]
    steps: list[str]
    trace_id: str


def load_default_index():
    """Open (or build) the Corpus index. Needs no LLM key."""
    from app.rag import FastEmbedder, build_index
    from app.settings import get_settings

    return build_index(get_settings().chroma_dir, FastEmbedder())


def build_default_graph(index):
    """The production graph: Router, Knowledge and Customer Support Agents."""
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
    return build_graph(make_router(model), make_knowledge(model, tools), make_support(model))


def _error(status: int, code: str, message: str, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "trace_id": trace_id},
    )


def create_app(
    graph: Any = None,
    load_index: Callable[[], Any] | None = None,
    judge_enabled: bool | None = None,
    judge_model: Any = None,
) -> FastAPI:
    """`graph` is anything with `.invoke(state) -> state`; built lazily if omitted.

    Judges run after a 200 when `judge_enabled` (default: `JUDGE_ENABLED`);
    `judge_model` defaults to `JUDGE_MODEL` via the model factory.

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
        if load_index is not None:
            app.state.index_thread = threading.Thread(target=_load, name="index", daemon=True)
            app.state.index_thread.start()
        yield

    app = FastAPI(title="Getnet Multi-Agent Support", lifespan=lifespan)
    app.state.graph = graph
    app.state.index = None
    app.state.needs_index = load_index is not None
    app.state.judge_model = judge_model

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

    def judge(trace_id: str, message: str, result: dict) -> None:
        try:
            model = get_judge_model()
        except Exception:
            log.exception("judge model unavailable trace_id=%s", trace_id)
            return
        run_judges(
            model,
            trace_id=trace_id,
            message=message,
            intent=result["intent"],
            answer=result.get("answer", ""),
            sources=result.get("sources", []),
            user_id=result.get("user_id", ""),
        )

    def ready() -> bool:
        return not app.state.needs_index or app.state.index is not None

    @app.get("/health")
    def health():
        if not ready():
            return JSONResponse(status_code=503, content={"status": "starting"})
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest, background: BackgroundTasks):
        trace_id = uuid.uuid4().hex
        started = time.perf_counter()

        def log_outcome(outcome: str, result: dict | None = None) -> None:
            log_request(
                trace_id=trace_id,
                user_id=request.user_id,
                message=request.message,
                latency_ms=round((time.perf_counter() - started) * 1000),
                outcome=outcome,
                result=result,
            )

        if not ready():
            return _error(503, "starting", "The service is starting; try again shortly.", trace_id)
        try:
            if app.state.graph is None:
                app.state.graph = build_default_graph(app.state.index)
            result = app.state.graph.invoke(
                {"message": request.message, "user_id": request.user_id}
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
        log_outcome("ok", result)
        if judges_on():
            background.add_task(judge, trace_id, request.message, result)
        return ChatResponse(
            answer=result.get("answer", ""),
            intent=intent,
            agent="router" if intent == "unsupported" else intent,
            sources=result.get("sources", []),
            steps=result.get("steps", []),
            trace_id=trace_id,
        )

    return app


setup_logging()
app = create_app(load_index=load_default_index)
