import logging
import uuid
from typing import Any

import openai
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.graph import Source, build_graph

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


def build_default_graph():
    """The production graph: real Router, specialists (stubs until 05/06)."""
    from app.llm import make_chat_model
    from app.router import make_router
    from app.settings import get_settings
    from app.stubs import stub_knowledge, stub_support

    model = make_chat_model(get_settings())
    from app.support import make_support

    return build_graph(make_router(model), stub_knowledge, make_support(model))


def _error(status: int, code: str, message: str, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "trace_id": trace_id},
    )


def create_app(graph: Any = None) -> FastAPI:
    """`graph` is anything with `.invoke(state) -> state`; built lazily if omitted."""
    app = FastAPI(title="Getnet Multi-Agent Support")
    app.state.graph = graph

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(request: ChatRequest):
        trace_id = uuid.uuid4().hex
        try:
            if app.state.graph is None:
                app.state.graph = build_default_graph()
            result = app.state.graph.invoke(
                {"message": request.message, "user_id": request.user_id}
            )
        except openai.APIError as exc:
            # Raised only after the SDK's own retries are exhausted.
            log.warning("provider error trace_id=%s: %r", trace_id, exc)
            if getattr(exc, "status_code", None) == 429:
                return _error(503, "rate_limited", "The language model is rate limited; try again shortly.", trace_id)
            return _error(503, "provider_unavailable", "The language model provider is unavailable; try again shortly.", trace_id)
        except Exception:
            log.exception("unexpected error trace_id=%s", trace_id)
            return _error(500, "internal_error", "Internal server error.", trace_id)

        intent = result["intent"]
        return ChatResponse(
            answer=result.get("answer", ""),
            intent=intent,
            agent="router" if intent == "unsupported" else intent,
            sources=result.get("sources", []),
            steps=result.get("steps", []),
            trace_id=trace_id,
        )

    return app


app = create_app()
