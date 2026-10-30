# 05: RAG index and Knowledge Agent

Status: closed
Blocked by: 03, 04

- Index: splitter 300/50 with title prefix, fastembed multilingual MiniLM, persistent Chroma with cosine, hash-named collection, built at startup (lifespan); `/health` waits for it.
- `search_corpus` (k=4, threshold Sources) and `web_search` (Tavily → DDG), both `content_and_artifact`.
- `create_agent` with `ToolCallLimitMiddleware(run_limit=4)` and a `dynamic_prompt` that includes the date; Sources collected from artifacts.
- Dockerfile: the model is baked in at build time.
- Tests: chunking/title prefix, threshold, collection hash, scripted-fake agent → Sources only from artifacts.
