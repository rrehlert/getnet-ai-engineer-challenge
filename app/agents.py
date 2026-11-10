"""Pieces shared by the Agents: the language rule in their prompts and the
`steps` / `tokens` / `evidence` summary of a tool-calling agent's run."""

from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

LANGUAGE_RULE = (
    "Detect the language from the Message's own words only: user ids, product names and "
    "Portuguese terms (e.g. `cliente2024`, `antecipação`, `Pix`) do not change it."
)


def run_summary(agent: str, messages: Sequence[BaseMessage]) -> dict:
    """`steps`: the agent, then each tool it called; `tokens`: total over its model calls;
    `evidence`: each tool output it saw, in order (calls refused by a tool limit excluded)."""
    return {
        "evidence": [
            {"tool": m.name, "content": m.text}
            for m in messages
            if isinstance(m, ToolMessage) and m.status != "error"
        ],
        "steps": [agent] + [m.name for m in messages if isinstance(m, ToolMessage)],
        "tokens": sum(
            (m.usage_metadata or {}).get("total_tokens", 0) for m in messages if isinstance(m, AIMessage)
        ),
    }
