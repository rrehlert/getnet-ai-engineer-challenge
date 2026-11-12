from datetime import date

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from app.knowledge import make_knowledge, make_search_corpus, make_web_search
from app.rag import Chunk, Hit

TODAY = date(2026, 10, 30)


class ScriptedModel(GenericFakeChatModel):
    """Replays scripted AIMessages; records the tools bound and the messages seen on each call."""

    bound: list = []
    seen: list = []

    def bind_tools(self, tools, **kwargs):
        self.bound = [t.name for t in tools]
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def call(name, query, id="c1"):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"query": query}, "id": id, "type": "tool_call"}],
        usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    )


def final(text):
    return AIMessage(content=text, usage_metadata={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25})


def scripted(*replies):
    return ScriptedModel(messages=iter(replies), seen=[])


class FakeIndex:
    def __init__(self, hits):
        self.hits = hits
        self.queries = []

    def search(self, query, k=4):
        self.queries.append((query, k))
        return self.hits[:k]


def hit(url, title, passage, similarity):
    return Hit(Chunk(text=f"{title}\n{passage}", url=url, title=title), similarity)


PIX_HITS = [
    hit("https://g/pix", "Pix", "O Pix cai na hora.", 0.76),
    hit("https://g/pix", "Pix", "Pix exige conta corrente.", 0.70),
    hit("https://g/taxas", "Taxas", "Consulte as taxas.", 0.45),
    hit("https://g/aluguel", "Aluguel", "Aluguel de maquininha.", 0.30),
]


def test_search_corpus_gives_all_chunks_to_the_model_but_only_relevant_pages_as_sources():
    index = FakeIndex(PIX_HITS)
    search = make_search_corpus(index, threshold=0.43)

    msg = search.invoke({"type": "tool_call", "id": "c1", "name": "search_corpus", "args": {"query": "pix"}})

    assert index.queries == [("pix", 4)]
    for h in PIX_HITS:
        assert h.chunk.text in msg.content
    assert msg.artifact == [
        {"url": "https://g/pix", "title": "Pix"},
        {"url": "https://g/taxas", "title": "Taxas"},
    ]


def test_web_search_falls_back_to_duckduckgo_when_tavily_reports_an_error():
    def tavily(query):
        return {"error": "quota exceeded"}

    def ddg(query):
        return [{"title": "Tempo em SP", "href": "https://w/sp", "body": "28 °C, ensolarado"}]

    search = make_web_search(tavily=tavily, ddg=ddg)
    msg = search.invoke({"type": "tool_call", "id": "c1", "name": "web_search", "args": {"query": "tempo sp"}})

    assert "28 °C" in msg.content
    assert msg.artifact == [{"url": "https://w/sp", "title": "Tempo em SP"}]


def test_web_search_uses_tavily_results_when_they_succeed():
    def tavily(query):
        return {"results": [{"title": "USD/BRL", "url": "https://w/fx", "content": "R$ 5,40"}]}

    def ddg(query):
        raise AssertionError("DuckDuckGo should not be called")

    search = make_web_search(tavily=tavily, ddg=ddg)
    msg = search.invoke({"type": "tool_call", "id": "c1", "name": "web_search", "args": {"query": "dólar"}})

    assert "R$ 5,40" in msg.content
    assert msg.artifact == [{"url": "https://w/fx", "title": "USD/BRL"}]


def test_web_search_reports_failure_without_sources_when_every_backend_fails():
    def broken(query):
        raise RuntimeError("down")

    search = make_web_search(tavily=None, ddg=broken)
    msg = search.invoke({"type": "tool_call", "id": "c1", "name": "web_search", "args": {"query": "x"}})

    assert msg.artifact == []
    assert "fail" in msg.content.lower()


def knowledge_with(model, hits=PIX_HITS, web=None):
    tools = [
        make_search_corpus(FakeIndex(hits), threshold=0.43),
        make_web_search(tavily=None, ddg=web or (lambda q: [])),
    ]
    return make_knowledge(model, tools, today=lambda: TODAY)


def test_sources_come_from_tool_artifacts_never_from_model_text():
    model = scripted(
        call("search_corpus", "Pix precisa de conta bancária"),
        final("Sim, o Pix exige conta. Fonte: https://invented.example/pix"),
    )

    update = knowledge_with(model)({"message": "Does Pix need a bank account?", "user_id": "cliente1988"})

    assert update["answer"].startswith("Sim, o Pix exige conta.")
    assert update["sources"] == [
        {"url": "https://g/pix", "title": "Pix"},
        {"url": "https://g/taxas", "title": "Taxas"},
    ]
    assert update["steps"] == ["knowledge", "search_corpus"]
    assert update["tokens"] == 37


def test_sources_from_both_tools_are_merged_in_call_order_and_deduplicated():
    web = lambda q: [  # noqa: E731
        {"title": "Pix", "href": "https://g/pix", "body": "dup"},
        {"title": "Clima", "href": "https://w/clima", "body": "28 °C"},
    ]
    model = scripted(call("search_corpus", "pix", "c1"), call("web_search", "clima", "c2"), final("ok"))

    update = knowledge_with(model, web=web)({"message": "pix e clima", "user_id": "u"})

    assert update["steps"] == ["knowledge", "search_corpus", "web_search"]
    assert update["sources"] == [
        {"url": "https://g/pix", "title": "Pix"},
        {"url": "https://g/taxas", "title": "Taxas"},
        {"url": "https://w/clima", "title": "Clima"},
    ]


def test_tool_call_limit_stops_executing_tools_after_four_calls():
    calls = [call("search_corpus", f"q{i}", f"c{i}") for i in range(6)]
    model = scripted(*calls, final("Com o que encontrei: ..."))

    update = knowledge_with(model)({"message": "pix", "user_id": "u"})

    assert update["answer"] == "Com o que encontrei: ..."
    executed = [m for m in model.seen[-1] if isinstance(m, ToolMessage) and m.status != "error"]
    assert len(executed) == 4
    assert len(update["evidence"]) == 4  # calls refused by the limit are not Evidence


def test_prompt_includes_todays_date():
    model = scripted(final("Não encontrei essa informação."))

    update = knowledge_with(model)({"message": "qual a taxa do plano X?", "user_id": "u"})

    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "2026-10-30" in system.content
    assert update["sources"] == []
    assert update["steps"] == ["knowledge"]


def test_evidence_records_every_tool_output_in_order_including_chunks_below_threshold():
    web = lambda q: [{"title": "Clima", "href": "https://w/clima", "body": "28 °C"}]  # noqa: E731
    model = scripted(call("search_corpus", "pix", "c1"), call("web_search", "clima", "c2"), final("ok"))

    update = knowledge_with(model, web=web)({"message": "pix e clima", "user_id": "u"})

    corpus, weather = update["evidence"]
    assert corpus["tool"] == "search_corpus"
    assert "Aluguel de maquininha." in corpus["content"]  # similarity 0.30, below the threshold
    assert weather["tool"] == "web_search"
    assert "28 °C" in weather["content"]


def test_no_evidence_when_no_tool_was_called():
    update = knowledge_with(scripted(final("Não encontrei.")))({"message": "x", "user_id": "u"})

    assert update["evidence"] == []


def test_prior_turns_reach_the_model_as_messages_before_the_current_message():
    from langchain_core.messages import HumanMessage

    model = scripted(final("Sim, a Smart aceita aproximação."))
    history = [
        {"role": "user", "content": "Does Get Smart take Pix?"},
        {"role": "assistant", "content": "Yes."},
    ]

    update = knowledge_with(model)({"message": "and contactless?", "user_id": "u", "history": history})

    [system, *rest] = model.seen[0]
    assert isinstance(system, SystemMessage)
    assert [(type(m), m.content) for m in rest] == [
        (HumanMessage, "Does Get Smart take Pix?"),
        (AIMessage, "Yes."),
        (HumanMessage, "and contactless?"),
    ]
    assert update["answer"] == "Sim, a Smart aceita aproximação."
    assert update["evidence"] == []
