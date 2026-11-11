# 05: Retrieval recall@4

**What to build:** a labelled set of ~10 Knowledge questions (`evals/retrieval.json`, each with ≥1 expected Corpus URL) and recall@4 computed directly against the index, reported by the runner in the same results file.

- recall@4 = share of questions where an expected URL is among the pages of the top 4 Chunks (`CorpusIndex.search`, `TOP_K`); no model, no threshold.
- Misses listed with the URLs that came back.
- Questions written in Portuguese (what the Knowledge Agent sends to `search_corpus`); expected URLs must exist in `corpus/` (loader checks).
- `--retrieval-only` runs just this (no LLM key needed).

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Fake index returning known pages: hits, misses, recall value, printed miss list
- [ ] Loader rejects an expected URL not in the Corpus
- [ ] Results file gains a `retrieval` section
- [ ] No real LLM calls in tests
