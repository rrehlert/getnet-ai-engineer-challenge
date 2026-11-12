"""The LangGraph orchestration: Router Agent, then a specialist or END.

An anonymous visitor (`user_id` None, ADR 0005) never reaches the Customer
Support Agent: `support` goes to the deterministic `login` node instead.

Specialist interface (Knowledge / Customer Support Agents and the Router):
a callable that takes the `GraphState` and returns a partial update dict,
typically `{answer, sources, evidence, steps, tokens}`. `steps` and `tokens` are
accumulated across nodes, so each node returns only its own.
"""

import operator
from collections.abc import Callable, Iterable
from typing import Annotated, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

Intent = Literal["knowledge", "support", "unsupported"]
Agent = Literal["router", "knowledge", "support"]


def agent_for(intent: Intent, anonymous: bool = False) -> Agent:
    """The Agent that answers an Intent: the Router itself refuses `unsupported`,
    and answers an anonymous visitor's `support` Message with the login reply."""
    if intent == "unsupported" or (anonymous and intent == "support"):
        return "router"
    return intent


class Source(TypedDict):
    url: str
    title: str


def dedup_sources(sources: Iterable[Source]) -> list[Source]:
    """Sources once per URL, first occurrence wins, in order."""
    seen: dict[str, Source] = {}
    for s in sources:
        seen.setdefault(s["url"], {"url": s["url"], "title": s["title"]})
    return list(seen.values())


class Evidence(TypedDict):
    """One tool output an Agent saw: the tool's name and the text it returned."""

    tool: str
    content: str


HISTORY_TURNS = 10  # Turns of history the Agents see before the current Message


class HistoryTurn(TypedDict):
    """A prior Turn as the Agents see it: who said it and the text. Context only, never Evidence."""

    role: Literal["user", "assistant", "operator"]
    content: str


class GraphState(TypedDict):
    message: str
    user_id: str | None  # the Merchant; None for an anonymous visitor
    # The last HISTORY_TURNS Turns of the Conversation before `message`, oldest first;
    # empty for a new Conversation or an anonymous visitor.
    history: NotRequired[list[HistoryTurn]]
    intent: NotRequired[Intent]
    answer: NotRequired[str]
    sources: NotRequired[list[Source]]
    evidence: NotRequired[list[Evidence]]
    steps: Annotated[list[str], operator.add]
    tokens: Annotated[int, operator.add]


Node = Callable[[GraphState], dict]

EMPTY_ANSWER_FALLBACK = (
    "Não consegui gerar uma resposta. Por favor, reformule sua pergunta. "
    "I couldn't produce an answer. Please rephrase your question."
)


LOGIN_REPLY = (
    "Para ver os dados da sua conta (vendas, recebimentos e maquininhas), faça login. "
    "Sem login, posso ajudar com produtos e serviços da Getnet. "
    "To see your account data (sales, deposits and card machines), please log in. "
    "Without logging in, I can help with Getnet products and services."
)


LOGIN_STEP = "login"  # a graph step that is neither an Agent nor a tool


def login_reply(state: GraphState) -> dict:
    """An anonymous visitor's account question: a fixed reply, no model, no tools."""
    return {"answer": LOGIN_REPLY, "sources": [], "steps": [LOGIN_STEP]}


def _next(state: GraphState) -> str:
    """After the Router: the Intent's node, except `support` without a Merchant → `login`."""
    intent = state.get("intent")
    if intent is None:
        raise ValueError("the Router set no Intent")
    if intent == "support" and state["user_id"] is None:
        return LOGIN_STEP
    return intent


def _never_empty(specialist: Node) -> Node:
    """A specialist that returned no answer text gets the fixed fallback instead."""

    def node(state: GraphState) -> dict:
        update = specialist(state)
        if not (update.get("answer") or "").strip():
            update = {**update, "answer": EMPTY_ANSWER_FALLBACK}
        return update

    return node


def build_graph(route_fn: Node, knowledge: Node, support: Node):
    """Compile the graph. Inject fakes for any node in tests."""
    builder = StateGraph(GraphState)
    builder.add_node("router", route_fn)
    builder.add_node("knowledge", _never_empty(knowledge))
    builder.add_node("support", _never_empty(support))
    builder.add_node(LOGIN_STEP, login_reply)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        _next,
        {"knowledge": "knowledge", "support": "support", LOGIN_STEP: LOGIN_STEP, "unsupported": END},
    )
    builder.add_edge(LOGIN_STEP, END)
    builder.add_edge("knowledge", END)
    builder.add_edge("support", END)
    return builder.compile()
