import json

import pytest

from app.rag import TOP_K, Chunk, Hit
from scripts.eval import format_summary, run_retrieval
from scripts.retrieval import (
    RetrievalQuestion,
    format_retrieval,
    load_retrieval,
    recall_at_k,
)
from scripts.scenarios import DatasetError
from tests.test_eval import NOW, run_eval_with

PIX = "https://site.getnet.com.br/duvidas/pix/"
TAXAS = "https://site.getnet.com.br/duvidas/taxas/"
WIFI = "https://site.getnet.com.br/get-ajuda-configuracoes/como-configurar-o-wi-fi-na-sua-maquininha-getnet/"
SMART = "https://site.getnet.com.br/duvidas/get-smart/"


class FakeIndex:
    """Returns known pages per query, as `CorpusIndex.search` would (one Hit per Chunk)."""

    def __init__(self, pages: dict[str, list[str]]):
        self.pages = pages
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, k: int = TOP_K) -> list[Hit]:
        self.calls.append((query, k))
        return [Hit(Chunk(text="t", url=url, title="T"), similarity=0.5) for url in self.pages.get(query, [])[:k]]


QUESTIONS = [
    RetrievalQuestion("O que é chave Pix?", [PIX]),
    RetrievalQuestion("Como configurar o Wi-Fi da maquininha?", [WIFI]),
    RetrievalQuestion("Quais as taxas?", [TAXAS, SMART]),
]


def fake_index() -> FakeIndex:
    return FakeIndex(
        {
            "O que é chave Pix?": [TAXAS, PIX, PIX, SMART],
            "Como configurar o Wi-Fi da maquininha?": [SMART, SMART, TAXAS, PIX, WIFI],  # WIFI is 5th
            "Quais as taxas?": [SMART],
        }
    )


def test_recall_at_4_is_share_of_questions_with_an_expected_page_in_the_top_4_chunks():
    index = fake_index()

    result = recall_at_k(QUESTIONS, index)

    assert result["k"] == 4
    assert result["questions"] == 3
    assert result["hits"] == 2
    assert result["recall"] == pytest.approx(2 / 3)
    assert [k for _, k in index.calls] == [4, 4, 4]


def test_misses_list_the_urls_that_came_back():
    result = recall_at_k(QUESTIONS, fake_index())

    assert result["misses"] == [
        {
            "question": "Como configurar o Wi-Fi da maquininha?",
            "expected": [WIFI],
            "returned": [SMART, TAXAS, PIX],  # pages of the top 4 Chunks, deduplicated, in rank order
        }
    ]


def test_printed_summary_shows_recall_and_each_miss():
    text = format_retrieval(recall_at_k(QUESTIONS, fake_index()))

    assert "recall@4 2/3 = 67%" in text
    assert "Como configurar o Wi-Fi da maquininha?" in text
    assert f"expected {WIFI}" in text
    assert f"got {SMART}" in text and TAXAS in text


def test_no_misses_prints_none():
    index = FakeIndex({"O que é chave Pix?": [PIX]})

    text = format_retrieval(recall_at_k(QUESTIONS[:1], index))

    assert "recall@4 1/1 = 100%" in text
    assert "misses: none" in text


def write_set(tmp_path, questions):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "pix.md").write_text(f'---\nurl: "{PIX}"\ntitle: "Pix"\n---\n\nPix.', encoding="utf-8")
    path = tmp_path / "retrieval.json"
    path.write_text(json.dumps({"questions": questions}), encoding="utf-8")
    return path, corpus


def test_loader_reads_questions_with_expected_urls(tmp_path):
    path, corpus = write_set(tmp_path, [{"question": "O que é chave Pix?", "expected_urls": [PIX]}])

    assert load_retrieval(path, corpus) == [RetrievalQuestion("O que é chave Pix?", [PIX])]


def test_loader_rejects_an_expected_url_not_in_the_corpus(tmp_path):
    path, corpus = write_set(tmp_path, [{"question": "Quais as taxas?", "expected_urls": [PIX, TAXAS]}])

    with pytest.raises(DatasetError, match="question 1.*not in the Corpus.*duvidas/taxas"):
        load_retrieval(path, corpus)


@pytest.mark.parametrize(
    "raw",
    [{"question": "", "expected_urls": [PIX]}, {"question": "Pix?", "expected_urls": []}, {"question": "Pix?"}],
)
def test_loader_rejects_missing_question_or_expected_urls(tmp_path, raw):
    path, corpus = write_set(tmp_path, [raw])

    with pytest.raises(DatasetError, match="question 1"):
        load_retrieval(path, corpus)


@pytest.mark.parametrize("data", [{}, {"questions": []}, []])
def test_loader_rejects_a_file_without_questions(tmp_path, data):
    path, corpus = write_set(tmp_path, [])
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DatasetError, match="questions"):
        load_retrieval(path, corpus)


def test_committed_retrieval_set_loads_against_the_real_corpus():
    questions = load_retrieval()

    assert len(questions) >= 10


# --- Runner: retrieval section in the results file ---


def test_results_file_gains_a_retrieval_section(tmp_path):
    index = FakeIndex({q.question: [WIFI] for q in load_retrieval()})
    _, results = run_eval_with(tmp_path, index=index)

    retrieval = results["retrieval"]
    assert retrieval["k"] == 4 and retrieval["questions"] == len(load_retrieval())
    assert 0 < retrieval["hits"] < retrieval["questions"]
    assert {"question", "expected", "returned"} <= set(retrieval["misses"][0])
    assert "recall@4" in format_summary(results)


def test_retrieval_only_writes_metadata_and_retrieval_without_any_model(tmp_path):
    index = FakeIndex({"O que é chave Pix?": [PIX]})
    path, corpus = write_set(tmp_path, [{"question": "O que é chave Pix?", "expected_urls": [PIX]}])

    out = run_retrieval(index, path, corpus_dir=corpus, out_dir=tmp_path / "results", now=NOW)

    results = json.loads(out.read_text())
    assert out == tmp_path / "results" / "20261111T203005Z.json"
    assert set(results) == {"metadata", "retrieval"}
    assert results["metadata"]["retrieval_only"] is True
    assert len(results["metadata"]["retrieval_sha256"]) == 64
    assert results["metadata"]["date"] == "2026-11-11T20:30:05+00:00"
    assert results["retrieval"]["recall"] == 1.0
