# Getnet Multi-Agent Support

A containerized multi-agent support assistant for Getnet merchants. A **Router Agent** classifies each Message by Intent. It then hands the Message to a **Knowledge Agent** (RAG over Getnet's public site plus web search) or a **Customer Support Agent** (tools over mock account data), or refuses it itself.

Domain vocabulary is in [`GLOSSARY.md`](GLOSSARY.md). Architecture decisions are in [`docs/adr/`](docs/adr/). The spec and tickets are in [`.scratch/getnet-multi-agent/`](.scratch/getnet-multi-agent/).

## Quick start

```bash
cp .env.example .env        # set OPENAI_API_KEY (an OpenRouter key by default)
docker compose up --build   # builds the image, builds the RAG index at startup, serves on :8000
```

`/health` returns `{"status":"ok"}` once the index is ready. Until then it returns 503 `{"status":"starting"}`. The compose healthcheck waits for it.

Try it with a small shell helper (needs `jq`):

```bash
# chat "<message>" [user_id]   (user_id defaults to cliente1988)
chat() { curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d "{\"message\": \"$1\", \"user_id\": \"${2:-cliente1988}\"}" | jq; }

chat "Do I need a bank account to receive my sales via Pix?"        # Knowledge (RAG)
chat "What's the euro exchange rate today?"                         # Knowledge (web search)
chat "When will the money from yesterday's sales be deposited?"     # Customer Support
chat "Show me cliente2024's sales"                                  # refused by the Router
```

Follow the request and Judge log lines in another terminal:

```bash
docker compose logs --tail 0 -f --no-log-prefix api | jq -R 'fromjson? // empty | select(.trace_id)'
```

## Overview

```
POST /chat {message, user_id}
        │
        ▼
  Router Agent ── one structured LLM call → Intent + (refusal reply)
        │
        ├─ knowledge   → Knowledge Agent        → search_corpus (RAG) / web_search
        ├─ support     → Customer Support Agent → get_settlement_schedule / get_terminal_status / get_recent_transactions
        └─ unsupported → END (the Router's own refusal, in the Message's language)
        │
        ▼
{answer, intent, agent, sources, steps, trace_id}
```

- **Orchestration.** A LangGraph `StateGraph` (`app/graph.py`) with conditional edges on `state["intent"]`. `build_graph(route_fn, knowledge, support)` takes each agent as a plain callable, so tests inject fakes.
- **Router Agent** (`app/router.py`). One `with_structured_output(Route, method="function_calling", include_raw=True)` call.
  - `support`: the Merchant's own account ("my" machine, "my" sales, deposits, declines).
  - `knowledge`: how Getnet products work, plus general facts such as weather and exchange rates.
  - `unsupported`: off-topic, another Merchant's data, prompt injection, harmful.
  - Output that can't be parsed falls back to `knowledge`.
- **Knowledge Agent** (`app/knowledge.py`). A LangChain `create_agent` with `search_corpus` and `web_search` (Tavily, with DuckDuckGo as fallback), a tool-call limit of 4, and a dynamic prompt that includes today's date. It queries the Corpus in Portuguese and grounds every claim. **Sources come only from tool artifacts**, never from text the model writes.
- **Customer Support Agent** (`app/support.py`). A `create_agent` over `data/merchants.json` (mock merchants `cliente1988` and `cliente2024`). Dates in the data are relative to today, so "yesterday" always has data.
  - `user_id` reaches the tools through `ToolRuntime` context and is never a tool argument.
  - Unknown users get an agent with no tools.
- **RAG pipeline** (`scripts/fetch_corpus.py` → `app/rag.py` → `app/knowledge.py`):
  1. **Ingestion:** 68 curated pages (list in `PAGES` in `scripts/fetch_corpus.py`):
     - 5 from the suggested [getnet.net/en](https://www.getnet.net/en) (home and the 4 "our solutions" pages);
     - 63 from the Brazilian site [site.getnet.com.br](https://site.getnet.com.br/). This one carries the product detail the example questions need: Terminals, Wi-Fi/connectivity, error codes and declines, Pix, antecipação, crediário/parcelado, Link de Pagamento/WhatsApp, and the `/duvidas/` FAQs.

     Pages are fetched with httpx and extracted with trafilatura, plus lxml XPath for the FAQ modals and product cards that trafilatura drops. The output is committed as `corpus/*.md` with `url/lang/title` front matter ([ADR 0002](docs/adr/0002-corpus-committed-as-markdown.md)).
  2. **Chunking:** ~300 characters with 50 overlap; each Chunk is prefixed with its page title.
  3. **Embedding:** fastembed `paraphrase-multilingual-MiniLM-L12-v2`, run locally and baked into the image ([ADR 0003](docs/adr/0003-local-multilingual-embeddings.md)). It is multilingual, so English questions match Portuguese pages.
  4. **Storage:** persistent Chroma, cosine distance. The collection name is a hash of corpus, model and chunking settings, and the index is built at startup.
  5. **Retrieval:** the `search_corpus` tool, k=4. Only Chunks with similarity ≥ `RELEVANCE_THRESHOLD` (0.5) become Sources. The threshold was tuned on the scenarios: relevant hits score ≥ .58, off-topic ones ≤ .34.
  6. **Generation:** the Knowledge Agent decides when to call `search_corpus`. It writes the query in Portuguese and retries once with other wording on a miss. If the Corpus has nothing, it falls back to `web_search`. The answer must be grounded in the tool results and written in the Message's language. The `sources` in the response are taken from the tool artifacts, not from the model's text, so the model cannot invent a citation.
- **LLM** (`app/llm.py`). `init_chat_model(LLM_MODEL)` with `LLM_MODEL="provider:model"`. The default is OpenRouter through the OpenAI-compatible API. Any provider works by changing env vars only ([ADR 0001](docs/adr/0001-provider-agnostic-llm-via-env.md)).
- **Errors.**
  - Invalid input → 422.
  - Provider errors or rate limits, from any provider, after retries → 503 `{error:{code,message}, trace_id}`.
  - Unexpected errors → 500 with a generic message.
  - Unsupported Messages and unknown users are normal 200 responses.
- **Observability** (`app/observability.py`, `app/judge.py`). One JSON log line per request: `trace_id, user_id, message, intent, agent, tools, tokens, latency_ms, outcome`. When `JUDGE_ENABLED`, two background LLM judges each write one `event:"judge"` line with a 0–1 Judge Score, at WARNING level below 0.7:
  - `route`: was the Intent right?
  - `answer`: is the reply good for that Intent?

## Design choices

- **Router is one structured call, not an agent.** Routing is a classification, so a single function-calling call with a `Route` schema is cheaper, faster and easier to test than a tool loop. The intent policy lives in one place, `INTENT_POLICY`, and the route Judge reuses it, so the Router and its Judge always score against the same rules.
- **Specialists are tool-calling agents.** Knowledge and Support need to choose and chain tools (search, retry, fall back to the web; or settlements plus terminal status). `create_agent` gives them that loop, with a hard tool-call limit so a looping model cannot run up cost.
- **LangGraph for the orchestration.** The workflow is an explicit graph with conditional edges, which makes it easy to see, test with fake nodes, and extend. A fourth agent such as human escalation would be one more node and edge.
- **Agents are injected callables.** `build_graph(route_fn, knowledge, support)` keeps orchestration separate from the LLM, so every branch can be tested without a model.
- **Provider-agnostic LLM** ([ADR 0001](docs/adr/0001-provider-agnostic-llm-via-env.md)). Changing the model or provider takes only env vars.
- **Committed corpus** ([ADR 0002](docs/adr/0002-corpus-committed-as-markdown.md)). Builds are reproducible and offline, and the corpus can be reviewed in diffs. There is no scraping at startup.
- **Local multilingual embeddings** ([ADR 0003](docs/adr/0003-local-multilingual-embeddings.md)). They need no embedding API key and cost nothing per query, and they bridge English questions to Portuguese pages.
- **Mock data with relative dates.** "Yesterday's sales" always has data, whatever day the demo runs.

## How LLM tool calling is used

- **Router:** `with_structured_output(..., method="function_calling")`. The schema is the tool, so the Intent is always one of the three allowed values.
- **Knowledge Agent:** `search_corpus` and `web_search` tools. They return `(content, artifact)`, so the model reads the text while the code keeps the structured Sources.
- **Customer Support Agent:** 3 tools: `get_settlement_schedule`, `get_terminal_status` and `get_recent_transactions`. `user_id` is injected through `ToolRuntime` context, not passed as a tool argument, so the model cannot be talked into reading another Merchant's account.
- **Middleware:** `ToolCallLimitMiddleware` caps tool calls, and `dynamic_prompt` adds today's date and the Merchant context to the prompt.
- **Judges:** structured output (`Verdict`: score + reason).

## Guardrails and reliability

- **Scope guardrail:** the Router's `unsupported` Intent catches off-topic requests, attempts to read another Merchant's data, prompt injection ("ignore your instructions…") and harmful requests. It replies with a polite refusal in the Message's language and calls no tools.
- **Data isolation:** `user_id` lives in the tool runtime context, not the prompt. An unknown user gets an agent with no tools.
- **Grounding:** Sources come only from tool artifacts and are filtered by the relevance threshold.
- **Bounded cost:** tool-call and recursion limits; chat model `timeout=30s`, `max_retries=2`.
- **Graceful failure:**
  - output the Router can't parse falls back to `knowledge`;
  - an empty specialist answer gets a fixed fallback message;
  - provider errors or rate limits return a 503 with a `trace_id`;
  - Judge failures are logged and never affect the response.

## Evaluation and observability strategy

**Implemented:**
- One structured JSON log line per request, with a `trace_id` that is also returned to the client.
- Two online LLM Judges (`route`, `answer`) that score live traffic in the background. A score below 0.7 is logged at WARNING.
- `scripts/scenarios.py` as a small labelled eval set: 13 Messages with expected Intents.

**Production plan (not implemented):**
- **Dashboards** built from the log lines:
  - requests and Intent mix;
  - p50/p95 `latency_ms`;
  - tokens per request, so cost per Intent;
  - `outcome` error rate;
  - mean Judge Score per Judge Type and Intent;
  - share of Knowledge answers with zero Sources (a retrieval-gap signal).
- **Alerts:**
  - 5xx or 503 rate above a threshold (provider outage);
  - p95 latency regression;
  - mean Judge Score dropping below a baseline;
  - a spike in `unsupported`, which could be an attack or a Router regression.
- **Tracing:** add OpenTelemetry or LangSmith spans for each node and tool call, keyed by the existing `trace_id`.
- **Offline eval dataset:** grow the scenarios into a versioned golden set (Message, user, expected Intent, expected tools, reference facts). Use low-scoring production traffic flagged by the Judges as a source of new cases. Run it on every prompt, model or corpus change, and block a merge if Intent accuracy or the mean answer score drops.
- **RAG metrics:** retrieval hit rate and context precision on the golden set, used to tune k, chunk size and the threshold.

## Tech stack

| Area | Choice |
|---|---|
| Language / packaging | Python 3.12, [uv](https://docs.astral.sh/uv/) (`uv.lock`, pinned deps) |
| API | FastAPI (sync endpoints), uvicorn, pydantic-settings |
| Agents | LangChain 1.x `create_agent` (middleware: `ToolCallLimitMiddleware`, `dynamic_prompt`), LangGraph `StateGraph` |
| LLM | `init_chat_model`; default `openai:openai/gpt-6-luna` via OpenRouter |
| RAG | trafilatura + lxml (ingestion), `langchain-text-splitters`, fastembed (local multilingual embeddings), Chroma (persistent, cosine) |
| Web search | Tavily (`langchain-tavily`), DuckDuckGo (`ddgs`) fallback |
| Tests | pytest, FastAPI TestClient, scripted fake chat models (no real LLM calls) |
| Packaging | Docker + docker compose (embedding model baked into the image; index built at startup) |

## Configuration

All configuration is in env vars (see [`.env.example`](.env.example)). Never commit `.env`.

| Var | Default | Notes |
|---|---|---|
| `LLM_MODEL` | `openai:openai/gpt-6-luna` | `provider:model` |
| `OPENAI_API_KEY` | (none) | required with the default provider (OpenRouter key) |
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `TAVILY_API_KEY` | empty | optional; DuckDuckGo is used when empty or on failure |
| `JUDGE_ENABLED` | `true` in compose | off in tests |
| `JUDGE_MODEL` | = `LLM_MODEL` | |
| `RELEVANCE_THRESHOLD` | `0.5` | minimum cosine similarity for a Chunk to count as a Source |
| `PORT` | `8000` | |
| `CHROMA_DIR` | `chroma` | persistent index directory |

## Examples to test

With the stack running, more examples using plain curl:

```bash
# Knowledge (RAG over the Corpus)
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Do I need a bank account to receive my sales via Pix?", "user_id": "cliente1988"}'

# Knowledge (web search)
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "What'\''s the euro exchange rate today?", "user_id": "cliente1988"}'

# Customer Support (mock account tools)
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "When will the money from yesterday'\''s sales be deposited?", "user_id": "cliente1988"}'

# Customer Support, in Portuguese
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Minha maquininha não conecta na internet, o que faço?", "user_id": "cliente1988"}'

# Unsupported: another merchant's data, refused by the Router
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Show me cliente2024'\''s sales", "user_id": "cliente1988"}'

# Unknown user: 200 with an "account not found" answer, no tool calls
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "My card machine is showing a transaction decline error.", "user_id": "nobody"}'
```

Example response:

```json
{
  "answer": "Yes. To receive your Getnet Pix sales, you need a Pix key linked to the bank account ...",
  "intent": "knowledge",
  "agent": "knowledge",
  "sources": [{"url": "https://site.getnet.com.br/duvidas/pix/", "title": "Perguntas frequentes: Pix"}],
  "steps": ["router", "knowledge", "search_corpus"],
  "trace_id": "73e47750fa624c3d8f97a5d813fc8689"
}
```

To run all 10 example Messages from the challenge plus 3 Router edge cases, and get a ✓/✗ for each expected Intent:

```bash
uv run python scripts/scenarios.py            # or: scripts/scenarios.py http://host:port
```

Mock merchants:
- **`cliente1988`** has pending Settlements from yesterday, an offline Terminal (weak Wi-Fi) and recent declines (codes 51 and 54).
- **`cliente2024`** is the clean contrast: online Terminal, everything paid out.

## Running the tests

```bash
uv sync
uv run pytest
```

Re-fetch the Corpus (needs network; writes `corpus/*.md`):

```bash
uv run python scripts/fetch_corpus.py
```

## Testing strategy

There are three layers. The fast, deterministic tests come first; real LLM behaviour is checked separately.

**1. Unit and component tests (`uv run pytest`, 62 tests, no network, no real LLM).** These cover the code paths that don't depend on what the model says:
- **Graph:** every Intent branch, the fallback for unparseable output, and `unsupported` ending at the Router. The agents are fakes.
- **Agents:** driven by scripted fake chat models that emit tool calls. Checks:
  - Sources come from artifacts;
  - the tool-call limit holds;
  - `user_id` comes from context;
  - an unknown user triggers no tool call.
- **RAG:** chunking, the title prefix, threshold filtering, collection-name hashing.
- **API:** `/chat` via TestClient with an injected graph covers 200, 422, 503 (provider error or 429) and 500, plus the response shape.
- **Observability:** the log line fields, and Judge scoring/flagging.
- **Ingestion:** the extraction XPath, on saved HTML fixtures.

**2. End-to-end scenarios (`scripts/scenarios.py`).** These run against the real container and the real LLM: the 10 challenge Messages plus 3 Router edge cases (prompt injection, another Merchant's data, a Portuguese Message). Each gets a ✓/✗ on the expected Intent, and the answers and Sources are printed for review. The current result is 13/13.

**3. How I'd approach full integration testing:**
- **Orchestration contract tests:** run the real graph with a real model and assert on structure, not wording:
  - which agent ran;
  - which tools were called, and with what context;
  - Sources are non-empty for corpus questions;
  - no Support tool is called for another or unknown `user_id`;
  - the reply is in the Message's language.
- **Golden dataset + LLM-as-judge:** a versioned set of labelled cases, scored by the same `route`/`answer` Judges plus a groundedness check (are the claims supported by the retrieved Chunks?). Set thresholds on the aggregate scores rather than exact strings, to absorb LLM nondeterminism. Run each case a few times and track the pass rate.
- **Retrieval evaluation:** for each corpus question, the expected page URL(s), measured with hit@k and MRR. This isolates RAG regressions from generation regressions.
- **Adversarial suite:** prompt injection, cross-Merchant access, PII fishing, off-topic and harmful requests, all expected to end as `unsupported` with no tool calls.
- **Failure injection:** a stubbed provider that times out, returns 429 or returns malformed tool calls, plus an empty corpus and web search being down. Assert the documented 503/fallback behaviour.
- **Docker smoke test in CI:** `docker compose up`, wait for `/health`, run the scenarios, tear down. Unit tests run on every push. The paid LLM suites run on prompt, model or corpus changes and nightly.

## Folder structure

```
.
├── app/                    # the service
│   ├── main.py             # FastAPI app: /chat, /health, error mapping, request logging, judge scheduling
│   ├── graph.py            # LangGraph StateGraph, GraphState, Intent/Agent types, Source dedup
│   ├── router.py           # Router Agent (structured output) + shared intent policy
│   ├── knowledge.py        # Knowledge Agent + search_corpus / web_search tools
│   ├── support.py          # Customer Support Agent + account tools over mock data
│   ├── agents.py           # pieces shared by agents (language rule, tokens/steps summary)
│   ├── rag.py              # corpus loading, chunking, fastembed, Chroma index
│   ├── llm.py              # chat model factory + provider-error classification
│   ├── judge.py            # route / answer LLM judges
│   ├── observability.py    # JSON log lines
│   └── settings.py         # pydantic-settings (env vars)
├── corpus/                 # committed Getnet pages as markdown with url/lang/title front matter
├── data/merchants.json     # mock Merchant accounts (dates relative to today)
├── scripts/
│   ├── fetch_corpus.py     # ingestion: fetch + extract Getnet pages into corpus/
│   └── scenarios.py        # end-to-end scenario runner against a running API
├── tests/                  # pytest suite (+ fixtures/ with saved HTML)
├── docs/
│   ├── adr/                # architecture decision records
│   └── agents/             # config for the agent skills (issue tracker, labels, domain docs)
├── .scratch/getnet-multi-agent/  # spec.md + tickets (local issue tracker)
├── GLOSSARY.md             # domain vocabulary
├── Dockerfile, docker-compose.yml, .env.example
└── pyproject.toml, uv.lock
```

## Development process (Spec Driven Development + AI tooling)

The core solution was built in a 60-minute timebox. The git history is the clock: commit dates were never rewritten (no rebase, amend or squash), and every branch is merged with `--no-ff`.

| Time | Commit | Step |
|---|---|---|
| 15:58 | `00` | start clock |
| 16:10 | `01` | spec ([`spec.md`](.scratch/getnet-multi-agent/spec.md)), 7 tickets, glossary, 3 ADRs |
| 16:17 | `02` | skeleton: uv, settings, `/health`, Docker |
| 16:21 | `03` | Router Agent, graph, `/chat`, scenarios script |
| 16:24 | `06` | Customer Support Agent + tools |
| 16:30 | `04` | corpus ingestion (68 pages) |
| 16:36 | `05` | RAG index + Knowledge Agent |
| 16:41 | `07` | prompt tuning and relevance threshold → 13/13 scenarios |
| 16:43 | `08` | logging + LLM Judges |
| 16:46–16:53 | `09`–`10` | review fixes |

The README (`11`, `12`) and the video came after the timebox.

- **Spec first.** The challenge was turned into a spec covering the stack, config, orchestration, each agent's contract, errors, observability, testing and git rules. Then it was split into vertical-slice tickets under [`.scratch/getnet-multi-agent/issues/`](.scratch/getnet-multi-agent/issues/), each with acceptance criteria. Each ticket is one branch and one `NN:` commit.
- **AI tooling.** Development used Claude Code with a set of agent skills (spec/ticket writing, domain modeling, TDD, code review) configured in [`docs/agents/`](docs/agents/) and `CLAUDE.md`. [`GLOSSARY.md`](GLOSSARY.md) and the ADRs give the agent and human the same vocabulary and decisions. Each ticket was implemented by the agent against the spec and reviewed before merging.

## Known limitations / future improvements

- **Identity:** `user_id` comes from the request body. It should come from a session or JWT cookie, together with real auth.
- **Get Clássica:** the Corpus has little on it, so comparing it with Get Smart is weak.
- **Crediário installments:** retrieval sometimes misses the answer even though the Corpus has it.
- **Sources:** they can be noisy (every Chunk above the threshold from every search), so filter them to the ones the answer uses.
- **`steps`:** it counts tool calls that the limit blocked.
- **Answer Judge vs. web search:** the Judge sees only the answer and the Source URLs/titles, not what the tools returned. So it misreads web Sources as documents. Example: for the weather question it said a climate website had nothing to do with weather. Fix: pass the tool results (or snippets) to the Judge and tell it to judge grounding against them, not the Source titles.
- **Chroma:** old hash-named collections are never pruned.
- **Out of scope:** multi-turn memory, real Getnet APIs, JS-rendered pages, PDF manuals, LangSmith tracing.
- **Other bonuses (designed, not built):**
  - a Human Escalation Agent and handoff: a fourth graph node, triggered by a low-confidence Router, a low answer Judge Score or an explicit user request;
  - the dashboards, alerts and golden-set regression runs described in [Evaluation and observability strategy](#evaluation-and-observability-strategy).
