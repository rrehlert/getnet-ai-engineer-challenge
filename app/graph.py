"""The LangGraph orchestration: Router Agent, then a specialist or END.

An anonymous visitor (`user_id` None, ADR 0005) never reaches the Customer
Support Agent or the Escalator Agent: `support` and `human` go to the
deterministic `login` node instead.

Escalation (ADR 0006): a Merchant's `human` Intent goes to the Escalator Agent;
so does a specialist that returns an `escalation_reason`. The Escalator returns
the transfer message as `answer` and the Handoff Brief as `handoff`; it touches
no store (`/chat` opens the Handoff).

Specialist interface (Knowledge / Customer Support Agents and the Router):
a callable that takes the `GraphState` and returns a partial update dict,
typically `{answer, sources, evidence, steps, tokens}`. `steps` and `tokens` are
accumulated across nodes, so each node returns only its own.
"""

import operator
from collections.abc import Callable, Iterable
from typing import Annotated, Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

Intent = Literal["knowledge", "support", "unsupported", "human"]
Agent = Literal["router", "knowledge", "support", "escalator"]


def agent_for(intent: Intent, anonymous: bool = False, escalated: bool = False) -> Agent:
    """The Agent that answers an Intent: the Escalator for an escalated Turn (any Intent);
    the Router itself refuses `unsupported` and answers an anonymous visitor's `support`
    or `human` Message with the login reply."""
    if escalated:
        return "escalator"
    if intent == "unsupported" or (anonymous and intent in ("support", "human")):
        return "router"
    if intent == "human":
        return "escalator"
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


Priority = Literal["low", "normal", "high"]


class HandoffBrief(TypedDict):
    """The Escalator Agent's summary of an Escalation for the Operator. Stored, never logged."""

    reason: str  # why it escalated
    customer_ask: str  # what the Merchant wants
    summary: str
    attempted: str  # what the Agents already tried
    category: str
    priority: Priority
    suggested_reply: str  # only ever sent by an Operator's choice
    language: str  # the Merchant's language


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
    # Set by a specialist that can't resolve the case: the graph goes on to the Escalator.
    escalation_reason: NotRequired[str]
    # Set by the Escalator: the brief for the Handoff that `/chat` opens.
    handoff: NotRequired[HandoffBrief]
    steps: Annotated[list[str], operator.add]
    tokens: Annotated[int, operator.add]


Node = Callable[[GraphState], dict]

EMPTY_ANSWER_FALLBACK = (
    "Não consegui gerar uma resposta. Por favor, reformule sua pergunta. "
    "I couldn't produce an answer. Please rephrase your question."
)


LOGIN_REPLY = (
    "Para ver os dados da sua conta (vendas, recebimentos e maquininhas) ou falar com um atendente, faça login. "
    "Sem login, posso ajudar com produtos e serviços da Getnet. "
    "To see your account data (sales, deposits and card machines) or talk to an agent, please log in. "
    "Without logging in, I can help with Getnet products and services."
)


LOGIN_STEP = "login"  # a graph step that is neither an Agent nor a tool


def login_reply(state: GraphState) -> dict:
    """An anonymous visitor's account question: a fixed reply, no model, no tools."""
    return {"answer": LOGIN_REPLY, "sources": [], "steps": [LOGIN_STEP]}


# The Merchant is told this when the Escalator's model gives no usable transfer message.
TRANSFER_FALLBACK = (
    "Vou transferir você para um atendente. Você pode continuar escrevendo enquanto aguarda. "
    "I'm transferring you to a human agent. You can keep writing while you wait."
)
# The escalation reason when the Merchant asked for a person (no specialist reason).
MERCHANT_ASKED = "The Merchant asked to talk to a person."
ESCALATOR_STEP = "escalator"


def escalation_reason(state: GraphState) -> str:
    """The specialist's reason, or the Merchant's own request for a person."""
    return (state.get("escalation_reason") or "").strip() or MERCHANT_ASKED


def fallback_brief(state: GraphState) -> HandoffBrief:
    """A brief built without a model: the reason and the Merchant's Message, nothing invented."""
    return {
        "reason": escalation_reason(state),
        "customer_ask": state["message"],
        "summary": "",
        "attempted": "",
        "category": "other",
        "priority": "normal",
        "suggested_reply": "",
        "language": "",
    }


def fallback_escalator(state: GraphState) -> dict:
    """The Escalator without a model: the fixed bilingual transfer message and `fallback_brief`."""
    return {"answer": TRANSFER_FALLBACK, "handoff": fallback_brief(state), "steps": [ESCALATOR_STEP]}


def _next(state: GraphState) -> str:
    """After the Router: the Intent's node, except `support` / `human` without a Merchant → `login`."""
    intent = state.get("intent")
    if intent is None:
        raise ValueError("the Router set no Intent")
    if intent in ("support", "human") and state["user_id"] is None:
        return LOGIN_STEP
    if intent == "human":
        return ESCALATOR_STEP
    return intent


def _after_specialist(state: GraphState) -> str:
    """A specialist that set an `escalation_reason` hands over to the Escalator; otherwise done.
    Anonymous visitors are never escalated (they have no Conversation to hand over)."""
    if (state.get("escalation_reason") or "").strip() and state["user_id"] is not None:
        return ESCALATOR_STEP
    return END


def _never_empty(specialist: Node) -> Node:
    """A specialist that returned no answer text gets the fixed fallback instead
    (unless it escalated: the Escalator writes the answer then)."""

    def node(state: GraphState) -> dict:
        update = specialist(state)
        if not (update.get("escalation_reason") or "").strip() and not (update.get("answer") or "").strip():
            update = {**update, "answer": EMPTY_ANSWER_FALLBACK}
        return update

    return node


def build_graph(route_fn: Node, knowledge: Node, support: Node, escalator: Node = fallback_escalator):
    """Compile the graph. Inject fakes for any node in tests; `escalator` defaults to the model-free fallback."""
    builder = StateGraph(GraphState)
    builder.add_node("router", route_fn)
    builder.add_node("knowledge", _never_empty(knowledge))
    builder.add_node("support", _never_empty(support))
    builder.add_node(LOGIN_STEP, login_reply)
    builder.add_node(ESCALATOR_STEP, escalator)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        _next,
        {
            "knowledge": "knowledge",
            "support": "support",
            LOGIN_STEP: LOGIN_STEP,
            ESCALATOR_STEP: ESCALATOR_STEP,
            "unsupported": END,
        },
    )
    builder.add_edge(LOGIN_STEP, END)
    for specialist in ("knowledge", "support"):
        builder.add_conditional_edges(specialist, _after_specialist, {ESCALATOR_STEP: ESCALATOR_STEP, END: END})
    builder.add_edge(ESCALATOR_STEP, END)
    return builder.compile()
