"""Customer Support Agent: answers questions about the Merchant's own account.

Account data is mock (`data/merchants.json`); dates are stored as day offsets
from today so "yesterday" always has data.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelRequest,
    ToolCallLimitMiddleware,
    dynamic_prompt,
)
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from app.agents import LANGUAGE_RULE, run_summary
from app.graph import GraphState, Node

SUPPORT_TOOL_CALL_LIMIT = 6
DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "merchants.json"


def _resolve(value: Any, today: date) -> Any:
    """Turn every `day_offset` / `<x>_day_offset` key into an ISO `date` / `<x>_date`."""
    if isinstance(value, list):
        return [_resolve(v, today) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, v in value.items():
        if key == "day_offset" or key.endswith("_day_offset"):
            key = key.removesuffix("day_offset") + "date"
            v = (today + timedelta(days=v)).isoformat()
        else:
            v = _resolve(v, today)
        out[key] = v
    return out


def load_merchants(today: date, path: Path = DATA_PATH) -> dict[str, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: _resolve(v, today) for k, v in raw.items() if not k.startswith("_")}


@dataclass(frozen=True)
class SupportContext:
    """Per-run context. `user_id` is the request's Merchant, never a tool argument."""

    user_id: str
    today: date


def _account(runtime: ToolRuntime[SupportContext]) -> dict:
    ctx = runtime.context
    return load_merchants(ctx.today).get(ctx.user_id, {})


def _dump(records: Any) -> str:
    return json.dumps({"currency": "BRL", "records": records}, ensure_ascii=False)


@tool
def get_settlement_schedule(runtime: ToolRuntime[SupportContext]) -> str:
    """The Merchant's Settlements (deposits of sales proceeds): sale date, payment
    method, gross/fee/net amounts in BRL, expected deposit date and status."""
    return _dump(_account(runtime).get("settlements", []))


@tool
def get_terminal_status(runtime: ToolRuntime[SupportContext]) -> str:
    """The Merchant's Terminals (card machines): online/offline status, connection
    type, Wi-Fi and chip signal, last seen, battery, last error and troubleshooting hints."""
    return _dump(_account(runtime).get("terminals", []))


@tool
def get_recent_transactions(runtime: ToolRuntime[SupportContext]) -> str:
    """The Merchant's recent card and Pix transactions: date, time, Terminal, amount
    in BRL, status, and for declines the decline code, reason and a hint."""
    return _dump(_account(runtime).get("transactions", []))


TOOLS = [get_settlement_schedule, get_terminal_status, get_recent_transactions]

PROMPT = """You are the Customer Support Agent of Getnet's support assistant for merchants.
Today is {today} ({weekday}). Dates in the tool data are ISO (YYYY-MM-DD); "yesterday" is {yesterday}.

The Merchant is `{user_id}`. Profile:
{profile}

Rules:
- Answer only about this Merchant's own account, using the tools: settlements
  (when money is deposited), terminals (card machines) and recent transactions.
- Use only facts returned by the tools. Never invent amounts, dates, fees, codes or
  procedures; for troubleshooting, use the hints in the tool data.
- Write every amount in Brazilian reais, e.g. R$ 1.817,26.
- Reply in the same language as the Merchant's Message, even when tool data is in
  Portuguese. """ + LANGUAGE_RULE + """ Be concise and practical."""

UNKNOWN_PROMPT = """You are the Customer Support Agent of Getnet's support assistant for merchants.
Today is {today} ({weekday}).

No Getnet account was found for user id `{user_id}`, so you have no account data
and no tools. Tell the Merchant, in the same language as their Message, that the
account wasn't found and that they should check their user id or contact Getnet
support. Do not guess or invent any account data."""


NOT_FOUND = (
    "Não encontramos uma conta Getnet para o usuário {user_id}. "
    "We couldn't find a Getnet account for user {user_id}."
)


def _build_prompt(ctx: SupportContext) -> str:
    fields = {
        "today": ctx.today.isoformat(),
        "weekday": ctx.today.strftime("%A"),
        "user_id": ctx.user_id,
    }
    account = load_merchants(ctx.today).get(ctx.user_id)
    if account is None:
        return UNKNOWN_PROMPT.format(**fields)
    return PROMPT.format(
        **fields,
        yesterday=(ctx.today - timedelta(days=1)).isoformat(),
        profile=json.dumps(account.get("profile", {}), ensure_ascii=False, indent=2),
    )


@dynamic_prompt
def support_prompt(request: ModelRequest) -> str:
    return _build_prompt(request.runtime.context)


def make_support(model: BaseChatModel, today: Callable[[], date] = date.today) -> Node:
    def agent(tools: list):
        return create_agent(
            model,
            tools=tools,
            middleware=[support_prompt, ToolCallLimitMiddleware(run_limit=SUPPORT_TOOL_CALL_LIMIT, exit_behavior="end")],
            context_schema=SupportContext,
        )

    with_tools = agent(TOOLS)
    # Unknown Merchant: an agent with no tools at all, so it cannot call any.
    without_tools = agent([])

    def support(state: GraphState) -> dict:
        ctx = SupportContext(user_id=state["user_id"], today=today())
        known = ctx.user_id in load_merchants(ctx.today)
        runner = with_tools if known else without_tools
        out = runner.invoke({"messages": [HumanMessage(state["message"])]}, context=ctx)
        messages = out["messages"]
        answer = messages[-1].text
        if not known and not answer.strip():
            # The model tried a tool call anyway; reply deterministically.
            answer = NOT_FOUND.format(user_id=ctx.user_id)
        return {"answer": answer, "sources": [], **run_summary("support", messages)}

    return support
