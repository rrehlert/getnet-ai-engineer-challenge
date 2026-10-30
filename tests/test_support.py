from datetime import date

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.support import load_merchants, make_support

TODAY = date(2026, 10, 30)  # a Friday


def test_day_offsets_resolve_relative_to_today():
    merchants = load_merchants(TODAY)

    debit = next(
        s for s in merchants["cliente1988"]["settlements"]
        if s["sale_date"] == "2026-10-29" and s["payment_method"] == "debit"
    )
    assert debit["expected_date"] == "2026-10-30"
    assert debit["status"] == "scheduled"
    assert not any(k.endswith("_day_offset") for k in debit)


class ScriptedModel(GenericFakeChatModel):
    """Replays scripted AIMessages; records the tools bound and the messages seen."""

    bound: list = []
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound = [t.name for t in tools]
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def call(name, id="c1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {}, "id": id, "type": "tool_call"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    )


def final(text):
    return AIMessage(
        content=text,
        usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25},
    )


def scripted(*replies):
    return ScriptedModel(messages=iter(replies), seen=[])


def tool_outputs(model):
    return [m for m in model.seen[-1] if isinstance(m, ToolMessage)]


def test_tools_read_the_merchant_from_context():
    model = scripted(call("get_terminal_status"), final("Your terminal is online."))
    support = make_support(model, today=lambda: TODAY)

    update = support({"message": "My card machine won't connect", "user_id": "cliente2024"})

    assert update["answer"] == "Your terminal is online."
    assert update["steps"] == ["support", "get_terminal_status"]
    assert update["sources"] == []
    assert update["tokens"] == 37
    [out] = tool_outputs(model)
    assert "GT-77C3-0451" in out.content
    assert "GT-58A1-0093" not in out.content


def test_yesterdays_settlements_with_dated_prompt_and_profile():
    model = scripted(call("get_settlement_schedule"), final("Hoje cai R$ 1.817,26."))
    support = make_support(model, today=lambda: TODAY)

    update = support({"message": "Quando cai o dinheiro das vendas de ontem?", "user_id": "cliente1988"})

    assert update["steps"] == ["support", "get_settlement_schedule"]
    prompt = model.seen[0][0].content
    assert "2026-10-30 (Friday)" in prompt
    assert '"yesterday" is 2026-10-29' in prompt
    assert "Padaria Pão Dourado" in prompt
    assert "R$" in prompt
    [out] = tool_outputs(model)
    assert '"sale_date": "2026-10-29", "payment_method": "debit"' in out.content
    assert '"net_amount": 1817.26, "expected_date": "2026-10-30", "status": "scheduled"' in out.content


def test_unknown_merchant_cannot_call_tools():
    # Even if the model tries, no tool is offered or executed.
    model = scripted(call("get_settlement_schedule"), final("Account not found."))
    support = make_support(model, today=lambda: TODAY)

    update = support({"message": "Quando cai o dinheiro?", "user_id": "cliente9999"})

    assert update["steps"] == ["support"]
    assert "cliente9999" in update["answer"]
    assert model.bound == []
    assert not tool_outputs(model)
    prompt = model.seen[0][0].content
    assert "wasn't found" in prompt
    assert "cliente9999" in prompt
