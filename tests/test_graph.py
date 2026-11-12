from app.graph import build_graph


def fake_route(intent, reply=""):
    def route(state):
        return {"intent": intent, "answer": reply, "steps": ["router"]}

    return route


def fake_specialist(name):
    def specialist(state):
        return {
            "answer": f"{name} answer to {state['message']} for {state['user_id']}",
            "sources": [{"url": f"https://{name}.example", "title": name}],
            "steps": [name, f"{name}_tool"],
            "tokens": 7,
        }

    return specialist


def run(route_fn, message="hi", user_id="cliente1988"):
    graph = build_graph(route_fn, fake_specialist("knowledge"), fake_specialist("support"))
    return graph.invoke({"message": message, "user_id": user_id})


def test_knowledge_intent_goes_to_knowledge_agent():
    result = run(fake_route("knowledge"), message="What is Get Smart?")

    assert result["intent"] == "knowledge"
    assert result["answer"] == "knowledge answer to What is Get Smart? for cliente1988"
    assert result["sources"] == [{"url": "https://knowledge.example", "title": "knowledge"}]
    assert result["steps"] == ["router", "knowledge", "knowledge_tool"]
    assert result["tokens"] == 7


def test_support_intent_goes_to_support_agent():
    result = run(fake_route("support"), user_id="cliente2024")

    assert result["intent"] == "support"
    assert result["answer"] == "support answer to hi for cliente2024"
    assert result["steps"] == ["router", "support", "support_tool"]


def test_unsupported_intent_ends_at_router_with_its_refusal():
    result = run(fake_route("unsupported", reply="Sorry, I can't help with that."))

    assert result["intent"] == "unsupported"
    assert result["answer"] == "Sorry, I can't help with that."
    assert result["steps"] == ["router"]
    assert result.get("sources", []) == []


def test_unparseable_router_output_falls_back_to_knowledge_agent():
    from app.router import make_router
    from tests.test_router import FakeStructuredModel

    route = make_router(FakeStructuredModel(parsing_error=ValueError("not json")))

    result = run(route)

    assert result["intent"] == "knowledge"
    assert result["steps"] == ["router", "knowledge", "knowledge_tool"]


def empty_specialist(state):
    return {"answer": " ", "sources": [], "steps": ["support"], "tokens": 5}


def test_specialist_empty_answer_gets_a_fixed_bilingual_fallback():
    from app.graph import EMPTY_ANSWER_FALLBACK

    for intent in ("knowledge", "support"):
        graph = build_graph(fake_route(intent), empty_specialist, empty_specialist)
        result = graph.invoke({"message": "hi", "user_id": "cliente1988"})

        assert result["answer"] == EMPTY_ANSWER_FALLBACK
        assert result["steps"] == ["router", "support"]
        assert result["tokens"] == 5
    assert "reformule" in EMPTY_ANSWER_FALLBACK and "rephrase" in EMPTY_ANSWER_FALLBACK


def test_anonymous_support_gets_the_login_reply_without_the_support_agent():
    from app.graph import LOGIN_REPLY

    result = run(fake_route("support"), user_id=None)

    assert result["answer"] == LOGIN_REPLY
    assert result["steps"] == ["router", "login"]
    assert result.get("tokens", 0) == 0


def test_anonymous_knowledge_still_goes_to_knowledge_agent():
    result = run(fake_route("knowledge"), user_id=None)

    assert result["steps"] == ["router", "knowledge", "knowledge_tool"]
