from pathlib import Path

from app.rag import Chunk, Hit, build_index, chunk_page, collection_name, load_page, relevant_sources

PAGE = """---
url: "https://site.getnet.com.br/duvidas/pix/"
lang: "pt-BR"
title: "Perguntas frequentes: Pix"
---

## O que são Chaves Pix?
É um “apelido” que você escolhe para sua conta para facilitar o recebimento de transações.

## Como contratar o Pix?
""" + ("Acesse o Portal Minha Conta ou o Aplicativo Getnet e informe sua chave. " * 12)


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_page_front_matter_is_parsed(tmp_path):
    page = load_page(write(tmp_path, "pix.md", PAGE))

    assert page.url == "https://site.getnet.com.br/duvidas/pix/"
    assert page.title == "Perguntas frequentes: Pix"
    assert page.body.startswith("## O que são Chaves Pix?")


def test_every_chunk_is_small_and_prefixed_with_the_page_title(tmp_path):
    page = load_page(write(tmp_path, "pix.md", PAGE))

    chunks = chunk_page(page, size=300, overlap=50)

    assert len(chunks) > 2
    for chunk in chunks:
        title, _, passage = chunk.text.partition("\n")
        assert title == "Perguntas frequentes: Pix"
        assert 0 < len(passage) <= 300
        assert chunk.url == page.url and chunk.title == page.title
    assert "apelido" in chunks[0].text


def test_collection_name_changes_with_corpus_model_and_chunking(tmp_path):
    a = write(tmp_path, "a.md", PAGE)
    files = [a]
    base = collection_name(files, model="m1", size=300, overlap=50)

    assert base == collection_name(files, model="m1", size=300, overlap=50)
    assert base != collection_name(files, model="m2", size=300, overlap=50)
    assert base != collection_name(files, model="m1", size=400, overlap=50)
    assert base != collection_name(files, model="m1", size=300, overlap=20)
    a.write_text(PAGE + "\nnova linha", encoding="utf-8")
    assert base != collection_name(files, model="m1", size=300, overlap=50)
    # Chroma names: 3-512 chars of [a-zA-Z0-9._-].
    assert base.replace("-", "").isalnum() and 3 <= len(base) <= 63


def hit(url, similarity, title="T"):
    return Hit(Chunk(text=f"{title}\nx", url=url, title=title), similarity)


def test_only_hits_at_or_above_the_threshold_become_sources_once_per_url():
    hits = [hit("u1", 0.71, "A"), hit("u2", 0.43, "B"), hit("u1", 0.60, "A"), hit("u3", 0.42, "C")]

    assert relevant_sources(hits, threshold=0.43) == [
        {"url": "u1", "title": "A"},
        {"url": "u2", "title": "B"},
    ]


class KeywordEmbedder:
    """Deterministic stand-in for fastembed: one dimension per keyword."""

    WORDS = ["pix", "antecipação", "maquininha"]

    def __init__(self, model="keywords-v1"):
        self.model = model
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [self.embed_query(t) for t in texts]

    def embed_query(self, text):
        text = text.lower()
        return [float(text.count(w)) + 0.01 for w in self.WORDS]


def page(title, url, body):
    return f'---\nurl: "{url}"\nlang: "pt-BR"\ntitle: "{title}"\n---\n\n{body}\n'


def test_index_is_built_once_and_returns_most_similar_chunks(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write(corpus, "pix.md", page("Pix", "https://g/pix", "O Pix cai na hora. Pix sem taxa."))
    write(corpus, "ant.md", page("Antecipação", "https://g/ant", "Antecipação de vendas no app."))
    embedder = KeywordEmbedder()

    index = build_index(tmp_path / "chroma", embedder, corpus_dir=corpus)
    hits = index.search("como funciona o pix?", k=2)

    assert [h.chunk.url for h in hits] == ["https://g/pix", "https://g/ant"]
    assert hits[0].chunk.text.startswith("Pix\n")
    assert hits[0].similarity > 0.9 > hits[1].similarity

    build_index(tmp_path / "chroma", embedder, corpus_dir=corpus)
    assert embedder.calls == 1  # reused, not re-embedded


def test_index_is_rebuilt_when_the_embedders_model_changes(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write(corpus, "pix.md", page("Pix", "https://g/pix", "O Pix cai na hora."))
    build_index(tmp_path / "chroma", KeywordEmbedder("keywords-v1"), corpus_dir=corpus)

    other = KeywordEmbedder("keywords-v2")
    build_index(tmp_path / "chroma", other, corpus_dir=corpus)

    assert other.calls == 1  # a different model never reuses the old vectors


def test_log_says_whether_the_index_was_built_or_reused(tmp_path, caplog):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    write(corpus, "pix.md", page("Pix", "https://g/pix", "O Pix cai na hora."))

    with caplog.at_level("INFO", logger="app.rag"):
        build_index(tmp_path / "chroma", KeywordEmbedder(), corpus_dir=corpus)
        build_index(tmp_path / "chroma", KeywordEmbedder(), corpus_dir=corpus)

    messages = [r.getMessage() for r in caplog.records if r.name == "app.rag"]
    assert messages[0].startswith("corpus index built")
    assert messages[1].startswith("corpus index reused")
