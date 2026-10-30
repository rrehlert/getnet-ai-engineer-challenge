"""The LangGraph orchestration: Router Agent, then a specialist or END.

Specialist interface (Knowledge / Customer Support Agents and the Router):
a callable that takes the `GraphState` and returns a partial update dict,
typically `{answer, sources, steps, tokens}`. `steps` and `tokens` are
accumulated across nodes, so each node returns only its own.
"""

import operator
from collections.abc import Callable
from typing import Annotated, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

Intent = Literal["knowledge", "support", "unsupported"]


class Source(TypedDict):
    url: str
    title: str


class GraphState(TypedDict):
    message: str
    user_id: str
    intent: NotRequired[Intent]
    answer: NotRequired[str]
    sources: NotRequired[list[Source]]
    steps: Annotated[list[str], operator.add]
    tokens: Annotated[int, operator.add]


Node = Callable[[GraphState], dict]

EMPTY_ANSWER_FALLBACK = (
    "Não consegui gerar uma resposta. Por favor, reformule sua pergunta. "
    "I couldn't produce an answer. Please rephrase your question."
)


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

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        lambda state: state["intent"],
        {"knowledge": "knowledge", "support": "support", "unsupported": END},
    )
    builder.add_edge("knowledge", END)
    builder.add_edge("support", END)
    return builder.compile()
