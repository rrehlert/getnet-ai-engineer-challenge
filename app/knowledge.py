"""Knowledge Agent: answers Getnet product questions from the Corpus and
general facts (weather, exchange rates) from web search.

Sources come only from the tools' artifacts, never from model-written text.
"""

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    ToolCallLimitMiddleware,
    dynamic_prompt,
)
from langchain.tools import BaseTool, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage

from app.agents import LANGUAGE_RULE, run_summary
from app.graph import GraphState, Node, Source, dedup_sources
from app.rag import TOP_K, Hit, relevant_sources

log = logging.getLogger(__name__)

KNOWLEDGE_TOOL_CALL_LIMIT = 4
# Backstop if the model keeps calling tools past the limit: ~4 graph steps per round
# (model, limit hook, tools, slack) for the allowed rounds plus 4 spare rounds.
KNOWLEDGE_RECURSION_LIMIT = 4 * (KNOWLEDGE_TOOL_CALL_LIMIT + 4)


class Index(Protocol):
    def search(self, query: str, k: int = TOP_K) -> list[Hit]: ...


def make_search_corpus(index: Index, threshold: float) -> BaseTool:
    @tool(response_format="content_and_artifact")
    def search_corpus(query: str) -> tuple[str, list[Source]]:
        """Search Getnet's public pages (products, fees, Pix, card machines, receivables
        anticipation, FAQs). The pages are in Portuguese: write the query in Portuguese."""
        hits = index.search(query, k=TOP_K)
        content = "\n\n".join(
            f"[{i}] ({h.chunk.url})\n{h.chunk.text}" for i, h in enumerate(hits, 1)
        )
        return content or "No results.", relevant_sources(hits, threshold)

    return search_corpus


SearchFn = Callable[[str], Any]


def _tavily_results(tavily: SearchFn, query: str) -> list[dict] | None:
    """Tavily returns `{"error": ...}` instead of raising; treat that as failure."""
    try:
        res = tavily(query)
    except Exception as exc:
        log.warning("tavily failed: %r", exc)
        return None
    if not isinstance(res, dict) or "error" in res or not res.get("results"):
        log.warning("tavily returned no results: %r", res if isinstance(res, dict) and "error" in res else "")
        return None
    return [{"title": r.get("title", ""), "url": r["url"], "body": r.get("content", "")} for r in res["results"]]


def _ddg_results(ddg: SearchFn, query: str) -> list[dict] | None:
    try:
        hits = ddg(query)
    except Exception as exc:
        log.warning("duckduckgo failed: %r", exc)
        return None
    return [{"title": h.get("title", ""), "url": h["href"], "body": h.get("body", "")} for h in hits]


def make_web_search(tavily: SearchFn | None, ddg: SearchFn) -> BaseTool:
    """`tavily` is None when no key is set; DuckDuckGo is the fallback."""

    @tool(response_format="content_and_artifact")
    def web_search(query: str) -> tuple[str, list[Source]]:
        """Search the web for general, non-Getnet facts such as weather, exchange
        rates or news. Not for Getnet products: use search_corpus for those."""
        results = _tavily_results(tavily, query) if tavily else None
        if results is None:
            results = _ddg_results(ddg, query)
        if results is None:
            return "Web search failed; no results are available.", []
        content = "\n\n".join(f"[{i}] {r['title']} ({r['url']})\n{r['body']}" for i, r in enumerate(results, 1))
        sources = [{"url": r["url"], "title": r["title"]} for r in results]
        return content or "No results.", sources

    return web_search


def default_web_search(tavily_api_key: str) -> BaseTool:
    tavily = None
    if tavily_api_key:
        from langchain_tavily import TavilySearch

        client = TavilySearch(max_results=3, tavily_api_key=tavily_api_key)
        tavily = lambda q: client.invoke({"query": q})  # noqa: E731

    def ddg(query: str) -> list[dict]:
        from ddgs import DDGS

        return DDGS(timeout=10).text(query, region="br-pt", max_results=3)

    return make_web_search(tavily, ddg)


PROMPT = """You are the Knowledge Agent of Getnet's support assistant for merchants.
Today is {today} ({weekday}).

Tools:
- search_corpus: Getnet's public pages (products, card machines, Pix, fees, receivables
  anticipation, FAQs). The pages are in Portuguese, so ALWAYS write the query in
  Portuguese, even when the Message is in another language.
- web_search: general facts that are not about Getnet, such as weather, exchange
  rates or news.
  Merchants are in Brazil: exchange rates are against the Brazilian real (BRL) unless
  the Message names another currency.

Rules:
- Ground every claim in what the tools returned. Never invent fees, rates, prices,
  deadlines or procedures.
- If the tools return nothing relevant, say plainly that you didn't find the
  information, and suggest Getnet's official channels for Getnet questions.
- Use at most a few searches, then answer with what you have.
- Do not list URLs or sources in the answer; they are attached separately.
- If a search misses, retry once with different Portuguese wording (synonyms,
  the product's name, the FAQ question form) before saying it wasn't found.
- Reply in the same language as the Merchant's Message, even when tool data is in
  Portuguese. """ + LANGUAGE_RULE + """ Be concise and practical."""


def build_prompt(today: date) -> str:
    return PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"))


def make_knowledge(model: BaseChatModel, tools: list[BaseTool], today: Callable[[], date] = date.today) -> Node:
    @dynamic_prompt
    def knowledge_prompt(request: ModelRequest) -> str:
        return build_prompt(today())

    agent = create_agent(
        model,
        tools=tools,
        middleware=[knowledge_prompt, ToolCallLimitMiddleware(run_limit=KNOWLEDGE_TOOL_CALL_LIMIT)],
    )

    def knowledge(state: GraphState) -> dict:
        out = agent.invoke(
            {"messages": [HumanMessage(state["message"])]},
            config={"recursion_limit": KNOWLEDGE_RECURSION_LIMIT},
        )
        messages = out["messages"]
        return {
            "answer": messages[-1].text,
            "sources": dedup_sources(
                s for m in messages if isinstance(m, ToolMessage) and m.artifact for s in m.artifact
            ),
            **run_summary("knowledge", messages),
        }

    return knowledge
