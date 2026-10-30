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


def build_graph(route_fn: Node, knowledge: Node, support: Node):
    """Compile the graph. Inject fakes for any node in tests."""
    builder = StateGraph(GraphState)
    builder.add_node("router", route_fn)
    builder.add_node("knowledge", knowledge)
    builder.add_node("support", support)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        lambda state: state["intent"],
        {"knowledge": "knowledge", "support": "support", "unsupported": END},
    )
    builder.add_edge("knowledge", END)
    builder.add_edge("support", END)
    return builder.compile()
