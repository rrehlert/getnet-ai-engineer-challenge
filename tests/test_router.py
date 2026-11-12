from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.router import Route, make_router


class FakeStructuredModel:
    """Stands in for a chat model's `with_structured_output(..., include_raw=True)`."""

    def __init__(self, parsed=None, parsing_error=None, tokens=0):
        self.output = {
            "raw": AIMessage(
                content="",
                usage_metadata={"input_tokens": tokens, "output_tokens": 0, "total_tokens": tokens},
            ),
            "parsed": parsed,
            "parsing_error": parsing_error,
        }
        self.seen = None

    def with_structured_output(self, schema, include_raw=False, method=None):
        assert schema is Route
        assert include_raw is True
        # json_schema raises on bad output instead of filling parsing_error.
        assert method == "function_calling"

        def respond(messages):
            self.seen = messages
            return self.output

        return RunnableLambda(respond)


STATE = {"message": "Show me cliente2024's sales", "user_id": "cliente1988"}


def test_routes_to_parsed_intent():
    route = make_router(FakeStructuredModel(Route(intent="support", reply=""), tokens=42))

    update = route(STATE)

    assert update["intent"] == "support"
    assert update["steps"] == ["router"]
    assert update["tokens"] == 42


def test_unsupported_uses_router_reply_as_answer():
    refusal = "Desculpe, só posso ajudar com a sua própria conta."
    route = make_router(FakeStructuredModel(Route(intent="unsupported", reply=refusal)))

    update = route(STATE)

    assert update["intent"] == "unsupported"
    assert update["answer"] == refusal


def test_parsing_error_falls_back_to_knowledge():
    route = make_router(FakeStructuredModel(parsing_error=ValueError("bad json")))

    assert route(STATE)["intent"] == "knowledge"


def test_missing_parsed_falls_back_to_knowledge():
    route = make_router(FakeStructuredModel(parsed=None))

    assert route(STATE)["intent"] == "knowledge"


def test_router_is_told_who_the_merchant_is_and_gets_the_message():
    model = FakeStructuredModel(Route(intent="unsupported", reply="no"))

    make_router(model)(STATE)

    text = " ".join(str(m.content) for m in model.seen)
    assert "cliente1988" in text
    assert STATE["message"] in text


def test_unsupported_with_empty_reply_gets_a_fixed_bilingual_refusal():
    from app.router import REFUSAL

    route = make_router(FakeStructuredModel(Route(intent="unsupported", reply="  \n")))

    update = route(STATE)

    assert update["intent"] == "unsupported"
    assert update["answer"] == REFUSAL
    assert "Getnet" in REFUSAL and "Desculpe" in REFUSAL and "Sorry" in REFUSAL


def test_router_is_told_an_anonymous_visitor_is_not_logged_in():
    model = FakeStructuredModel(Route(intent="support"))

    update = make_router(model)({"message": "When is my deposit?", "user_id": None})

    system = str(model.seen[0].content)
    assert "not logged in" in system
    assert "None" not in system
    assert update["intent"] == "support"


def test_router_prompt_for_a_merchant_does_not_say_not_logged_in():
    model = FakeStructuredModel(Route(intent="support"))

    make_router(model)(STATE)

    assert "not logged in" not in str(model.seen[0].content)
