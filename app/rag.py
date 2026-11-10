"""RAG index over the Corpus (ADR 0002, 0003).

Pages (`corpus/*.md`) are split into small Chunks prefixed with the page title,
embedded locally with fastembed and stored in a persistent Chroma collection
(cosine). The collection name hashes the corpus, model and chunking params, so
an unchanged corpus reuses the index and any change rebuilds it.
"""

import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.graph import Source, dedup_sources

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
TOP_K = 4
CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    body: str


@dataclass(frozen=True)
class Chunk:
    text: str  # "<page title>\n<Chunk>"
    url: str
    title: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    similarity: float  # 1 - cosine distance


def load_page(path: Path) -> Page:
    """Parse a Corpus file: `---` front matter of `key: "json string"` lines, then the body."""
    text = path.read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    meta = {}
    for line in front.splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        meta[key.strip()] = json.loads(value) if value.startswith('"') else value
    return Page(url=meta["url"], title=meta["title"], body=body.strip())


def chunk_page(page: Page, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap)
    return [
        Chunk(text=f"{page.title}\n{piece}", url=page.url, title=page.title)
        for piece in splitter.split_text(page.body)
    ]


def corpus_files(corpus_dir: Path = CORPUS_DIR) -> list[Path]:
    return sorted(corpus_dir.glob("*.md"))


def collection_name(files: Iterable[Path], model: str, size: int, overlap: int) -> str:
    digest = hashlib.sha256(f"{model}|{size}|{overlap}".encode())
    for path in sorted(files):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"corpus-{digest.hexdigest()[:16]}"


def relevant_sources(hits: Iterable[Hit], threshold: float) -> list[Source]:
    """Sources: pages of the hits at or above the threshold, deduplicated by URL."""
    return dedup_sources(
        {"url": h.chunk.url, "title": h.chunk.title} for h in hits if h.similarity >= threshold
    )


class Embedder(Protocol):
    model: str  # hashed into the collection name

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """fastembed, cached under `FASTEMBED_CACHE_PATH` (baked into the Docker image)."""

    def __init__(self, model: str = EMBEDDING_MODEL):
        from fastembed import TextEmbedding

        self.model = model
        self._model = TextEmbedding(model)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class CorpusIndex:
    def __init__(self, collection, embedder: Embedder):
        self.collection = collection
        self.embedder = embedder

    def search(self, query: str, k: int = TOP_K) -> list[Hit]:
        r = self.collection.query(
            query_embeddings=[self.embedder.embed_query(query)],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(Chunk(text=doc, url=meta["url"], title=meta["title"]), similarity=1 - dist)
            for doc, meta, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])
        ]


def build_index(
    chroma_dir: Path | str,
    embedder: Embedder,
    corpus_dir: Path = CORPUS_DIR,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> CorpusIndex:
    """Open the index for the current corpus, building it if it doesn't exist yet."""
    import chromadb

    files = corpus_files(corpus_dir)
    name = collection_name(files, embedder.model, size, overlap)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    existing = {c.name for c in client.list_collections()}
    collection = client.get_or_create_collection(
        name, configuration={"hnsw": {"space": "cosine"}}, embedding_function=None
    )
    count = collection.count()
    if name not in existing or count == 0:
        chunks = [c for f in files for c in chunk_page(load_page(f), size, overlap)]
        vectors = embedder.embed([c.text for c in chunks])
        batch = client.get_max_batch_size()
        for i in range(0, len(chunks), batch):
            part = chunks[i : i + batch]
            collection.add(
                ids=[f"{n}" for n in range(i, i + len(part))],
                embeddings=vectors[i : i + len(part)],
                documents=[c.text for c in part],
                metadatas=[{"url": c.url, "title": c.title} for c in part],
            )
        log.info("corpus index built: %s (%d chunks)", name, len(chunks))
    else:
        log.info("corpus index reused: %s (%d chunks)", name, count)
    return CorpusIndex(collection, embedder)
