"""Retrieval recall@k over a labelled set of Knowledge questions (`evals/retrieval.json`).

Computed directly against the Corpus index (`CorpusIndex.search`), no model: a question hits
when one of its expected Corpus URLs is among the pages of the top `TOP_K` Chunks.
Questions are in Portuguese, as the Knowledge Agent writes `search_corpus` queries.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.rag import CORPUS_DIR, TOP_K, Hit, Index, corpus_files, load_page
from scripts.scenarios import DatasetError

RETRIEVAL_SET = Path(__file__).resolve().parent.parent / "evals" / "retrieval.json"


@dataclass(frozen=True)
class RetrievalQuestion:
    question: str
    expected_urls: list[str]


def load_retrieval(path: Path = RETRIEVAL_SET, corpus_dir: Path = CORPUS_DIR) -> list[RetrievalQuestion]:
    """The labelled set, validated; every expected URL must be a page of the Corpus."""
    corpus_urls = {load_page(f).url for f in corpus_files(corpus_dir)}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list) or not data["questions"]:
        raise DatasetError(f"{path}: needs a non-empty \"questions\" list")
    questions = []
    for i, raw in enumerate(data["questions"], 1):
        question, urls = raw.get("question"), raw.get("expected_urls")
        where = f"question {i} ({question!r})"
        if not isinstance(question, str) or not question:
            raise DatasetError(f"{where}: missing question")
        if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
            raise DatasetError(f"{where}: expected_urls must be a non-empty list of URLs")
        unknown = [u for u in urls if u not in corpus_urls]
        if unknown:
            raise DatasetError(f"{where}: expected URL not in the Corpus: {', '.join(unknown)}")
        questions.append(RetrievalQuestion(question, urls))
    return questions


def _pages(hits: list[Hit]) -> list[str]:
    """Page URLs of the hits, deduplicated, in rank order."""
    return list(dict.fromkeys(h.chunk.url for h in hits))


def recall_at_k(questions: list[RetrievalQuestion], index: Index, k: int = TOP_K) -> dict:
    """recall@k (share of questions with an expected page among the top k Chunks' pages) and the misses."""
    misses = []
    for q in questions:
        returned = _pages(index.search(q.question, k=k))
        if not set(q.expected_urls) & set(returned):
            misses.append({"question": q.question, "expected": q.expected_urls, "returned": returned})
    found = len(questions) - len(misses)  # questions with an expected page in the top k
    return {
        "k": k,
        "questions": len(questions),
        "hits": found,
        "recall": found / len(questions) if questions else 0,
        "misses": misses,
    }


def format_retrieval(result: dict) -> str:
    lines = [f"recall@{result['k']} {result['hits']}/{result['questions']} = {result['recall']:.0%}"]
    if not result["misses"]:
        lines.append("misses: none")
    for miss in result["misses"]:
        lines.append(f"miss: {miss['question']}")
        lines += [f"  expected {url}" for url in miss["expected"]]
        lines += [f"  got {url}" for url in miss["returned"]] or ["  got nothing"]
    return "\n".join(lines)
