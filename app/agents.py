"""Pieces shared by the Agents: the language rule in their prompts, the chat
messages for a Message and its history, the `steps` / `tokens` / `evidence`
summary of a tool-calling agent's run, and the specialists' `escalate_to_human` tool."""

from collections.abc import Sequence
from typing import Any

from langchain.agents.middleware import AgentState, after_model
from langchain.tools import tool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.graph import GraphState

LANGUAGE_RULE = (
    "Detect the language from the Message's own words only: user ids, product names and "
    "Portuguese terms (e.g. `cliente2024`, `antecipação`, `Pix`) do not change it."
)


def run_summary(agent: str, messages: Sequence[BaseMessage]) -> dict:
    """`steps`: the agent, then each tool it called; `tokens`: total over its model calls;
    `evidence`: each tool output it saw, in order (calls refused by a tool limit excluded).
    A run that ended on `escalate_to_human` lists that tool last in `steps`."""
    escalated = [ESCALATE_TOOL] if escalation_update(messages) else []
    return {
        "evidence": [
            {"tool": m.name, "content": m.text}
            for m in messages
            if isinstance(m, ToolMessage) and m.status != "error"
        ],
        "steps": [agent] + [m.name for m in messages if isinstance(m, ToolMessage)] + escalated,
        "tokens": sum(
            (m.usage_metadata or {}).get("total_tokens", 0) for m in messages if isinstance(m, AIMessage)
        ),
    }


HUMAN_AGENT_PREFIX = "[Human agent]"  # marks an Operator Turn in the Agents' history (ADR 0006)


def conversation_messages(state: GraphState) -> list[BaseMessage]:
    """The history (prior Turns, oldest first) as chat messages, then the current Message.

    `user` Turns are human messages; `assistant` and `operator` Turns are the
    assistant's side, an Operator's prefixed `[Human agent]` so the model knows a
    human said it. Text only: no tool calls or Evidence are replayed.
    """
    prior: list[BaseMessage] = [
        HumanMessage(t["content"]) if t["role"] == "user"
        else AIMessage(f"{HUMAN_AGENT_PREFIX} {t['content']}") if t["role"] == "operator"
        else AIMessage(t["content"])
        for t in state.get("history", [])
    ]
    return [*prior, HumanMessage(state["message"])]


ESCALATE_TOOL = "escalate_to_human"

ESCALATION_RULE = """Answer first. Escalation is a last resort: call escalate_to_human(reason) only when
you can't give the Merchant a useful answer at all:
- they ask for an action that only a person can take and your tools or data don't cover
  (e.g. disputing a chargeback, contract or registration changes, refunds, unblocking an account);
- they are still stuck after your best answer in this Conversation (they say it didn't work,
  or repeat the problem);
- the case needs a human decision (exceptions, complaints, anything you may not promise).
Never escalate a question you can answer, even in part: if your tools or the Corpus answer
some of it, answer that part and say plainly what you couldn't find. A detail missing from the
Corpus is not a reason to escalate. Escalating discards your answer.
The reason is a short note for the Operator (the Getnet staff member who takes over), in English:
what the Merchant needs and why you can't resolve it. Never tell the Merchant you can't help when
escalating would."""


@tool(ESCALATE_TOOL)
def escalate_to_human(reason: str) -> str:
    """Hand the case to an Operator (a Getnet staff member) when you can't resolve it. `reason`: what the
    Merchant needs and why you can't resolve it. The Merchant is told they're being transferred."""
    # Never executed: `stop_on_escalation` ends the run as soon as the model calls it.
    return "Escalated to an Operator."


@after_model(tools=[escalate_to_human], can_jump_to=["end"])
def stop_on_escalation(state: AgentState, runtime: Any) -> dict | None:
    """Adds `escalate_to_human` to the agent and ends its loop the moment the model calls it
    (other tool calls in the same reply are not run; any draft is discarded)."""
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and any(c["name"] == ESCALATE_TOOL for c in last.tool_calls):
        return {"jump_to": "end"}
    return None


def escalation_update(messages: Sequence[BaseMessage]) -> dict:
    """The run's `escalation_reason` (and the step) if it ended on `escalate_to_human`; else `{}`.
    Put last in the node's update: the draft answer is dropped and the reason is never a Source."""
    last = messages[-1] if messages else None
    if not isinstance(last, AIMessage):
        return {}
    reasons = [str(c["args"].get("reason") or "").strip() for c in last.tool_calls if c["name"] == ESCALATE_TOOL]
    if not reasons:
        return {}
    # An empty reason still escalates: the model asked for a human.
    return {"answer": "", "escalation_reason": reasons[0] or "The Agent escalated without a reason."}
