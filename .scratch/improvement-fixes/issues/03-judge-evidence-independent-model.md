# 03: Answer Judge rates against Evidence, with an independent model

**What to build:** the `answer` Judge rates a reply against the Evidence the specialist Agent actually saw, using a model from a different family than the one that wrote the reply.

- The Knowledge Agent records its `search_corpus` and `web_search` outputs as Evidence (including Chunks below the relevance threshold); the Customer Support Agent records its account tool outputs. The Router and unknown-Merchant runs record none. Evidence is an ordered list of `{tool, content}` in graph state and is not added to the `/chat` response.
- The `answer` Judge receives Evidence, capped at ~6,000 characters total (items truncated in order, with a marker that text was cut), and is asked whether every claim in the reply is supported by it. The `route` Judge is unchanged.
- `JUDGE_MODEL` defaults to `openai:anthropic/claude-haiku-5.5`; the "empty means same as `LLM_MODEL`" fallback is removed; a warning is logged at startup when `JUDGE_MODEL` equals `LLM_MODEL`. `.env.example` updated.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Knowledge node result contains Evidence items with tool name and output (fake model emitting tool calls)
- [ ] Customer Support node result contains Evidence from account tools; none for an unknown Merchant
- [ ] Evidence is absent from the `/chat` response
- [ ] `answer` Judge prompt contains the Evidence text; total is cut at the cap with a marker
- [ ] End to end: `create_app` with an injected graph returning Evidence and a fake Judge model passes Evidence to the Judge
- [ ] Default Judge model is Haiku 5.5; explicit `JUDGE_MODEL` overrides it
- [ ] Warning logged when `JUDGE_MODEL` equals `LLM_MODEL`
- [ ] `.env.example` documents the new default
- [ ] No real LLM calls in tests
