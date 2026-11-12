# Getnet Multi-Agent Support

[![CI](https://github.com/rrehlert/getnet-ai-engineer-challenge/actions/workflows/ci.yml/badge.svg)](https://github.com/rrehlert/getnet-ai-engineer-challenge/actions/workflows/ci.yml)

A containerized multi-agent support assistant for Getnet merchants. A **Router Agent** classifies each Message by Intent. It then hands the Message to a **Knowledge Agent** (RAG over Getnet's public site plus web search) or a **Customer Support Agent** (tools over mock account data), or refuses it itself.

Domain vocabulary is in [`GLOSSARY.md`](GLOSSARY.md). Architecture decisions are in [`docs/adr/`](docs/adr/). The spec and tickets are in [`.scratch/getnet-multi-agent/`](.scratch/getnet-multi-agent/).

After the evaluation, an improvement run fixed several weak spots (Judge Evidence and model, scenario facts, log privacy, container, CI). Its specs are [`.scratch/improvement-fixes/`](.scratch/improvement-fixes/) and [`.scratch/eval-expansion/`](.scratch/eval-expansion/) (the [eval runner](#eval-runner)), and its clock, sessions and decisions are in [`IMPROVEMENT_RUN_DIARY.md`](IMPROVEMENT_RUN_DIARY.md).

## Quick start

```bash
cp .env.example .env        # set OPENAI_API_KEY (an OpenRouter key by default)
docker compose up --build   # builds the image, builds the RAG index at startup, serves on :8000
```

The container runs as a non-root user (`app`, uid 10001). All state lives on one named volume, `state` (mounted at `/app/state`): the Corpus index (`chroma/`) and the Conversations database (`conversations.db`). Recreating or restarting the container reuses both; the index is rebuilt only when the Corpus, embedding model or chunking settings change. `docker compose down -v` deletes both.

`/health` returns `{"status":"ok"}` once the index is ready. Until then it returns 503 `{"status":"starting"}`. The compose healthcheck waits for it.

Try it with a small shell helper (needs `jq`). `/chat` takes the Merchant only from a login token, so log in first for account questions; compose enables the dev login (`DEMO_LOGIN=true`). Without a token you are an anonymous visitor: product questions only.

```bash
# login [user_id]   (log in as a Merchant via the dev login; user_id defaults to cliente1988)
login() { TOKEN=$(curl -s localhost:8000/dev/login -H 'content-type: application/json' \
  -d "$(jq -n --arg u "${1:-cliente1988}" '{user_id: $u}')" | jq -r .access_token); }
# chat "<message>"   (as the logged-in Merchant; tokens last 1 hour)
chat() { curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d "$(jq -n --arg m "$1" '{message: $m}')" | jq; }

login
chat "Do I need a bank account to receive my sales via Pix?"        # Knowledge (RAG)
chat "What's the euro exchange rate today?"                         # Knowledge (web search)
chat "When will the money from yesterday's sales be deposited?"     # Customer Support
chat "Show me cliente2024's sales"                                  # refused by the Router

# no token: anonymous visitor, account questions get the "log in" reply
curl -s localhost:8000/chat -H 'content-type: application/json' -d '{"message": "When is my next deposit?"}' | jq
```

Follow the request and Judge log lines in another terminal:

```bash
docker compose logs --tail 0 -f --no-log-prefix api | jq -R 'fromjson? // empty | select(.trace_id)'
```

## Overview

```
POST /dev/login {user_id} → token (demo only)
POST /chat {message, conversation_id?} + Authorization: Bearer <token>   (Merchant = token `sub`; no token = anonymous visitor)
        │
        ▼
  Router Agent ── one structured LLM call → Intent + (refusal reply)
        │
        ├─ knowledge   → Knowledge Agent        → search_corpus (RAG) / web_search
        ├─ support     → Customer Support Agent → get_settlement_schedule / get_terminal_status / get_recent_transactions
        │                (anonymous: → login node, fixed PT + EN "log in to see your account" reply)
        └─ unsupported → END (the Router's own refusal, in the Message's language)
        │
        ▼
{answer, intent, agent, sources, steps, trace_id, conversation_id}
```

- **Identity** (`app/auth.py`, [ADR 0005](docs/adr/0005-identity-from-verified-token.md)). The Merchant comes only from a verified token, never from the request body.
  - `POST /dev/login {user_id}` returns `{access_token, token_type}`: an HS256 JWT (PyJWT) with `sub`, `role` (`merchant` or `operator`) and `exp` (1 hour), signed with `JWT_SECRET`. It is a "log in as" stand-in for an identity provider and proves nothing about the caller, so it exists only with `DEMO_LOGIN=true` (compose sets it; the default is off, and then it is 404). Ids in the fixture and unknown ids log in as Merchants (an unknown one gets the "account not found" reply); the mock operator `operador1` gets role `operator`.
  - Requests carry `Authorization: Bearer <token>`. Invalid or expired token → 401 (`invalid_token`), never downgraded to anonymous; an operator token on `/chat` → 403. A `user_id` in the `/chat` body is ignored. `GET /me` without a token → 401 (`unauthorized`).
  - **Anonymous visitors.** `/chat` without a token runs the graph with no Merchant (`user_id` None) and the Router prompt says the visitor is not logged in. `knowledge` and `unsupported` work as for a Merchant; `support` goes to a deterministic `login` node that returns a fixed bilingual "log in to see your account" reply (`agent` `router`, `steps` `["router", "login"]`), so the Customer Support Agent never runs. Anonymous requests are stateless: no Conversation is created and nothing is stored (`conversation_id` is null in the reply), and a `conversation_id` without a token → 401 (`unauthorized`). The request log's `user_ref` is `anonymous`.
  - `GET /me` returns `{sub, role}` and, for a Merchant, `account`: their fixture profile and data (null when they have no account).
  - The token's `sub` goes into graph state as `user_id`, so everything after the boundary (tools, `SupportContext`, logs) is unchanged.
- **Conversations** (`app/store.py`, [ADR 0004](docs/adr/0004-sqlite-single-store.md)). A Merchant's Messages are kept as Conversations of Turns in SQLite (WAL mode), the single store; no LangGraph checkpointer.
  - `/chat` without `conversation_id` starts a new Conversation owned by the token's `sub` and returns its id (a random UUID); with it, the Message is appended to that Conversation. An unknown id and another Merchant's id are the same 404 (`conversation_not_found`), and the graph doesn't run.
  - After a successful graph run, the user Turn and the assistant Turn (reply, Intent, Sources) are stored together; a failed run stores nothing. Raw tool output and Evidence are never stored.
  - Tables: `conversations` (`id`, `owner`, `created_at`, `updated_at`, `mode` = `bot`, for the future human takeover, [ADR 0006](docs/adr/0006-human-takeover-via-conversation-mode.md)) and `turns` (monotonic `id`, `conversation_id`, `role` `user`/`assistant`/`operator`, `content`, `intent`, `sources`, `created_at`).
  - Retention: at startup, Conversations not updated within `CONVERSATION_RETENTION_DAYS` (default 30) are deleted with their Turns; only the count is logged.
  - History is not yet passed to the Agents: that and listing Conversations are the next tickets of [`.scratch/conversations-identity/`](.scratch/conversations-identity/).
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
- **Observability** (`app/observability.py`, `app/judge.py`, `app/redact.py`). One JSON log line per request: `trace_id, conversation_id, user_ref, message, intent, agent, tools, tokens, latency_ms, outcome` (`message_length` instead of `message` when `LOG_MESSAGES=none`). All log output is redacted (see [Privacy](#privacy)). When `JUDGE_ENABLED`, three background LLM judges each write one `event:"judge"` line with a 0–1 Judge Score, at WARNING level below 0.7:
  - `route`: was the Intent right?
  - `answer`: is every claim in the reply supported by the **Evidence**, and does it answer the Message? Evidence is the tool output the specialist Agent actually saw (`search_corpus`/`web_search` results, including Chunks below the threshold, or the account tool data), capped at 6,000 characters with a truncation marker. It stays in graph state and is not returned by `/chat`.
  - `coverage`: which Intents did the Message need (`intents_needed`), and did the reply cover every part (`fully_answered`, `missing`)? It scores 1 when fully answered. A Message that needs more than one Intent is a **Mixed question**.

  A Judge line carries `judge_type, trace_id, intent, judge_score, reason` (and the coverage fields on `coverage` lines) plus the `message` and `answer` it scored (same `LOG_MESSAGES` mode and 500-character cap as the request line), so it can be read on its own. The Judges run on `JUDGE_MODEL`, by default a different model family from `LLM_MODEL`; a warning is logged at startup if they are equal.

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
- **Judges:** structured output (`Verdict`: score + reason; `Coverage` adds `intents_needed`, `fully_answered`, `missing`). The tool outputs are also kept as Evidence for the `answer` Judge.

## Guardrails and reliability

- **Scope guardrail:** the Router's `unsupported` Intent catches off-topic requests, attempts to read another Merchant's data, prompt injection ("ignore your instructions…") and harmful requests. It replies with a polite refusal in the Message's language and calls no tools.
- **Identity:** the Merchant comes only from a verified, expiring token (see [Overview](#overview)); a bad token is rejected, never treated as no token.
- **Anonymous access is Knowledge only:** without a token the graph routes `support` to a fixed login reply, never to the Customer Support Agent, whatever the Router says.
- **Data isolation:** `user_id` lives in the tool runtime context, not the prompt. An unknown user gets an agent with no tools.
- **Grounding:** Sources come only from tool artifacts and are filtered by the relevance threshold. The `answer` Judge checks claims against the Evidence.
- **Log privacy:** personal data is masked in every log line and the user id is pseudonymized (see [Privacy](#privacy)).
- **Bounded cost:** tool-call and recursion limits; chat model `timeout=30s`, `max_retries=2`.
- **Graceful failure:**
  - output the Router can't parse falls back to `knowledge`;
  - an empty specialist answer gets a fixed fallback message;
  - provider errors or rate limits return a 503 with a `trace_id`;
  - Judge failures are logged and never affect the response.

## Privacy

Merchants type personal data into Messages, so no log line writes it in clear text.

- **One redactor** (`app/redact.py`), applied centrally: to every structured event before it is written, and to every other log line and exception text in the JSON formatter. Judge prompts also ask the Judge not to quote personal data in its `reason`, which is redacted anyway.
- **Masked**, with typed placeholders; longer identifiers are matched before shorter ones (CNPJ before CPF, card before phone):

  | Data | Placeholder |
  |---|---|
  | CNPJ, formatted or 14 bare digits | `[CNPJ]` |
  | CPF, formatted or 11 bare digits | `[CPF]` |
  | card numbers, 13–19 digits, optionally grouped by spaces or dashes, only when Luhn-valid | `[CARD]` |
  | email addresses | `[EMAIL]` |
  | Brazilian phone numbers | `[PHONE]` |
  | Pix random keys (UUID with dashes) | `[PIX_KEY]` |

  BRL amounts, ISO dates, `trace_id`s and Terminal ids are left intact.
- **Pseudonymized user id.** The request line has `user_ref` instead of `user_id`: a keyed HMAC-SHA256 of the user id (the token's `sub`), first 16 hex characters, keyed by `LOG_HASH_KEY`. The same Merchant always gets the same ref (so events can be correlated), and without the key it can't be reversed by hashing every possible id. If `LOG_HASH_KEY` is empty, a random key is generated at startup with a warning, and refs change on every restart. An anonymous visitor's request line has `user_ref` `anonymous`.
- **Logging modes** (`LOG_MESSAGES`), for the Message on the request line and the Message and reply on Judge lines:

  | Mode | Logged |
  |---|---|
  | `none` | only the length (`message_length`, `answer_length`) |
  | `redacted` (default) | redacted text, capped at 500 characters |
  | `full` | raw text, capped at 500 characters (local debugging only) |

  Even under `full`, other fields and non-event lines are still redacted.

- **Retention.** Stored Conversations are not kept forever: at every startup, Conversations not updated within `CONVERSATION_RETENTION_DAYS` (default 30) are deleted together with their Turns. The startup log line gives only how many were deleted and the window, no ids or owners.

Tool outputs (account data) are never logged. The mock fixture itself holds mock personal data, which is out of scope.

## Evaluation and observability strategy

**Implemented:**
- One structured JSON log line per request, with a `trace_id` that is also returned to the client.
- Three online LLM Judges (`route`, `answer`, `coverage`) that score live traffic in the background, on a model from a different family than the reply model. The `answer` Judge rates the reply against the Evidence; `coverage` detects Mixed questions and incomplete replies. A score below 0.7 is logged at WARNING.
- One shared labelled dataset, [`evals/scenarios.json`](evals/scenarios.json): 17 Messages with expected Intents, 11 with expected facts, 4 Mixed questions. Used by the live smoke script (`scripts/scenarios.py`) and the in-process [eval runner](#eval-runner).
- The [eval runner](#eval-runner): every scenario several times, Judges run synchronously with Evidence, aggregate scores per Intent and overall, the multi-intent Router threshold, retrieval recall@4, and a committed baseline that every run is compared against.
- CI on every push and pull request: the test suite and a container smoke test.

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
- **Grow the eval dataset:** add expected tools, and use low-scoring production traffic flagged by the Judges as a source of new cases. Run the eval runner in CI on every prompt, model or corpus change, and block a merge if Intent accuracy or the mean answer score drops below the baseline.
- **More RAG metrics:** MRR and context precision next to recall@4, used to tune k, chunk size and the threshold.

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
| Packaging | Docker + docker compose (non-root user; embedding model baked into the image; index built at startup on a named volume) |
| CI | GitHub Actions: pytest + compose smoke test, no secrets |

## Configuration

All configuration is in env vars (see [`.env.example`](.env.example)). Never commit `.env`.

| Var | Default | Notes |
|---|---|---|
| `LLM_MODEL` | `openai:openai/gpt-6-luna` | `provider:model` |
| `OPENAI_API_KEY` | (none) | required with the default provider (OpenRouter key) |
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `TAVILY_API_KEY` | empty | optional; DuckDuckGo is used when empty or on failure |
| `JUDGE_ENABLED` | `true` in compose | off in tests |
| `JUDGE_MODEL` | `openai:anthropic/claude-haiku-5.5` | a different family from `LLM_MODEL` for independent Judge Scores; a startup warning is logged if they are equal |
| `RELEVANCE_THRESHOLD` | `0.5` | minimum cosine similarity for a Chunk to count as a Source |
| `PORT` | `8000` | |
| `STATE_DIR` | `state` | all persistent state: the Corpus index (`chroma/`) and the Conversations database (`conversations.db`); in compose, the named volume `state` at `/app/state` |
| `CONVERSATION_RETENTION_DAYS` | `30` | Conversations not updated within this many days are deleted, with their Turns, at startup; see [Privacy](#privacy) |
| `LOG_HASH_KEY` | empty | key for the `user_ref` HMAC in logs; empty means a random key per process, with a warning (refs change on restart) |
| `JWT_SECRET` | empty | HS256 key for login tokens; empty means a random secret per process, with a warning (tokens stop working on restart) |
| `DEMO_LOGIN` | `false` (`true` in compose) | enables `POST /dev/login` ("log in as" any user id); never enable it in a real deployment |
| `LOG_MESSAGES` | `redacted` | how much Message/reply text is logged; see [Privacy](#privacy) |
| `EVAL_RUNS` | `3` | runs per scenario in the [eval runner](#eval-runner) (≥1); not used by the service |

## Examples to test

With the stack running, more examples using plain curl (and `jq` to read the token):

```bash
# Log in as cliente1988 (dev login, DEMO_LOGIN=true)
TOKEN=$(curl -s localhost:8000/dev/login -H 'content-type: application/json' \
  -d '{"user_id": "cliente1988"}' | jq -r .access_token)

# Who am I: the principal and the fixture account
curl -s localhost:8000/me -H "authorization: Bearer $TOKEN"

# Knowledge (RAG over the Corpus)
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "Do I need a bank account to receive my sales via Pix?"}'

# Knowledge (web search)
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "What'\''s the euro exchange rate today?"}'

# Customer Support (mock account tools)
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "When will the money from yesterday'\''s sales be deposited?"}'

# Customer Support, in Portuguese
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "Minha maquininha não conecta na internet, o que faço?"}'

# Follow-up in the same Conversation: pass back the conversation_id from the previous reply
CID=$(curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "My card machine is offline"}' | jq -r .conversation_id)
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d "$(jq -n --arg c "$CID" '{message: "It is the Smart one", conversation_id: $c}')"

# Unsupported: another merchant's data, refused by the Router
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
  -d '{"message": "Show me cliente2024'\''s sales"}'

# Unknown user: logs in as a Merchant with no account; 200 with an "account not found" answer, no tool calls
NOBODY=$(curl -s localhost:8000/dev/login -H 'content-type: application/json' \
  -d '{"user_id": "nobody"}' | jq -r .access_token)
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer $NOBODY" \
  -d '{"message": "My card machine is showing a transaction decline error."}'

# No token: anonymous visitor. Product questions are answered...
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "What'\''s the difference between the Get Clássica and the Get Smart?"}'
# ...account questions get the fixed "log in to see your account" reply (agent "router", steps ["router", "login"])
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "Quanto vou receber hoje das minhas vendas?"}'

# Invalid token: 401, never treated as anonymous
curl -s localhost:8000/chat -H 'content-type: application/json' -H "authorization: Bearer not-a-token" \
  -d '{"message": "hi"}'
```

Example response:

```json
{
  "answer": "Yes. To receive your Getnet Pix sales, you need a Pix key linked to the bank account ...",
  "intent": "knowledge",
  "agent": "knowledge",
  "sources": [{"url": "https://site.getnet.com.br/duvidas/pix/", "title": "Perguntas frequentes: Pix"}],
  "steps": ["router", "knowledge", "search_corpus"],
  "trace_id": "73e47750fa624c3d8f97a5d813fc8689",
  "conversation_id": "5b0f6a0e-3c1d-4c63-9d0e-2f7c1b9e4a21"
}
```

To run the shared scenario dataset (the 10 example Messages from the challenge, 3 Router edge cases, 4 Mixed questions and 2 anonymous-visitor scenarios) against the running API, checking the expected Intent and, where declared, the expected facts in the reply:

```bash
uv run python scripts/scenarios.py            # or: scripts/scenarios.py http://host:port
```

It logs in as each scenario's user id through `POST /dev/login` (so it needs `DEMO_LOGIN=true`, as in compose) and sends the token. Scenarios with `"user_id": null` are anonymous visitors and are sent without a token: a product question (answered) and an account question (its facts check the login reply).

Each scenario prints a routing mark and a facts mark (`✓`, `✗`, or `-` when it declares no facts), then the Intent, agent, steps, `trace_id`, answer, Sources and any missing facts. The report ends with two separate totals (here, an all-pass run):

```
routing 19/19
facts 13/13
```

followed by the missing facts per scenario. A fact is a list of accepted alternatives, matched as case-insensitive substrings (e.g. an amount matches as `1.817,26`, `1817,26`, `1,817.26` or `1817.26`). Customer Support facts come from the fixture; Knowledge facts only where the fact is stable in the Corpus; refusals and web-search scenarios have none. A Mixed question routes correctly to any of its needed Intents. The exit code is non-zero if routing or facts are below 100%. For repeated runs, Judge Scores and a baseline, use the [eval runner](#eval-runner).

Mock merchants:
- **`cliente1988`** has pending Settlements from yesterday, an offline Terminal (weak Wi-Fi) and recent declines (codes 51 and 54).
- **`cliente2024`** is the clean contrast: online Terminal, everything paid out.

## Eval runner

`scripts/eval.py` measures quality offline. It builds the production graph in-process (needs an LLM key, no running server), so the Judges see the Evidence that `/chat` doesn't return.

```bash
uv run python -m scripts.eval                    # full eval: EVAL_RUNS runs per scenario + recall@4
EVAL_RUNS=1 uv run python -m scripts.eval        # cheaper: one run per scenario
uv run python -m scripts.eval --save-baseline    # also copy this run over evals/baseline.json
uv run python -m scripts.eval --retrieval-only   # only recall@4 against the index; no LLM key, no cost
```

**What a run does.** Every scenario of [`evals/scenarios.json`](evals/scenarios.json) is run `EVAL_RUNS` times (default 3). Scenarios with a user id pass it straight into graph state (no HTTP); anonymous ones (`"user_id": null`) pass `None`, as `/chat` does without a token, and the Judges are told the visitor is not logged in (the `answer` Judge rates an anonymous `support` reply on asking to log in, not on account Evidence). After each run, the three Judges run synchronously on `JUDGE_MODEL` with the Evidence, and their verdicts are kept.

**What is measured:**
- **Per scenario:** routing pass rate, fact pass rate (the same checks as `scripts/scenarios.py`), mean and min Judge Score per Judge Type, coverage fields (`fully_answered` rate, `intents_needed`, `missing`), tokens.
- **Per expected Intent and overall:** the same rates and Judge Scores, plus errors and missing verdicts.
- **Mixed questions:** the mixed-question rate (share of judged runs where the `coverage` Judge listed ≥2 needed Intents) and the incomplete rate (share of those not fully answered). The coverage Judge's agreement with the 4 labelled Mixed scenarios is reported as a sanity check.
- **Multi-intent Router threshold** (agreed before measuring): mixed-question rate **≥10%** and incomplete rate **≥50%** → "build multi-intent Router", otherwise "not justified". Today the Router picks one Intent per Message.
- **Retrieval recall@4:** on [`evals/retrieval.json`](evals/retrieval.json), 14 labelled Portuguese Knowledge questions with their expected Corpus URLs. A question hits when an expected URL is among the pages of the top 4 Chunks, computed against the index directly (no model). Misses are listed with the URLs that came back, to tell a Corpus gap from a ranking problem.
- **Tokens:** total and per Intent, so the cost of a run is visible. A full run is 19 scenarios × 3 runs × (graph + 3 Judges); with 17 scenarios it was about 160k tokens.

**Output.** Each run writes `evals/results/<UTC timestamp>.json` (gitignored) with metadata (commit, dirty tree, date, reply model, Judge model, run count, dataset hashes), the sections above and every run record. It prints a summary and the deltas against the committed baseline [`evals/baseline.json`](evals/baseline.json): rates in percentage points, Judge Score means, Mixed/incomplete rates, tokens per run. A warning is printed when the reply model, Judge model or scenario dataset hash differ from the baseline's, since the deltas are then not like-for-like.

**Privacy.** Unlike the logs, the results file (and so the committed baseline) holds raw Messages and replies, unredacted. That is fine while the eval only uses the fixture Merchants in `data/merchants.json`. With real Merchant data, commit only the aggregates and keep the run records in a gitignored file.

**Baseline** (`evals/baseline.json`, commit `ad0769b`, reply `openai:openai/gpt-6-luna`, Judge `openai:anthropic/claude-haiku-5.5`, 3 runs × 17 scenarios = 51 runs, 0 errors; taken before the 2 anonymous scenarios were added, so the next run warns that the dataset hash differs):

| Intent | Runs | Routing | Facts | `route` | `answer` | `coverage` |
|---|---|---|---|---|---|---|
| knowledge | 21 | 100% | 67% | 1.00 | 0.40 | 0.80 |
| support | 24 | 100% | 88% | 0.81 | 0.33 | 0.77 |
| unsupported | 6 | 100% | - | 1.00 | 1.00 | 1.00 |
| **overall** | 51 | 100% | 82% | 0.91 | 0.44 | 0.81 |

Judge columns are mean Judge Scores.

- Mixed questions 12/51 = 24% (≥10%); incomplete 11/12 = 92% (≥50%) → **build multi-intent Router**. The coverage Judge agreed with the labelled Mixed scenarios 12/12.
- recall@4 12/14 = 86%. Misses: the Pix app-enablement page (another Pix page ranked above it) and `/duvidas/taxas/` (not in the top 4).
- Tokens: 160,120.
- The `answer` Judge looks harsh (0.0 on some replies whose facts pass) and gives honest "not found" replies full marks. Its reasons often penalise omissions, which is the `coverage` Judge's job. See the diary for the per-scenario notes.

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

**1. Unit and component tests (`uv run pytest`, 253 tests, no network, no real LLM).** These cover the code paths that don't depend on what the model says:
- **Graph:** every Intent branch, the fallback for unparseable output, and `unsupported` ending at the Router. The agents are fakes.
- **Agents:** driven by scripted fake chat models that emit tool calls. Checks:
  - Sources come from artifacts;
  - the tool-call limit holds;
  - `user_id` comes from context;
  - an unknown user triggers no tool call.
- **RAG:** chunking, the title prefix, threshold filtering, collection-name hashing.
- **API:** `/chat` via TestClient with an injected graph covers 200, 422, 503 (provider error or 429) and 500, plus the response shape.
- **Auth:** with an injected secret, dev-login flag and clock: dev login on/off and token claims, invalid/expired token → 401 (never anonymous), operator token → 403, `user_id` taken from the token (a body `user_id` has no effect), `GET /me`, the empty-`JWT_SECRET` warning, `user_ref` derived from `sub`.
- **Anonymous visitors:** no token with a fake Router: `support` gets the login reply and the Customer Support node is never called, `knowledge`/`unsupported` as today, `conversation_id` → 401, `{}` → 422, `user_ref` `anonymous`; the Router prompt (scripted fake model) and the Judges are told the visitor is not logged in.
- **Conversations:** the store against a temporary SQLite file (create, append in order, ownership lookup, WAL, reopen the same file after close, retention purge with an injected clock incl. the window edge), and `/chat` with an injected store: first Message creates a Conversation, a follow-up appends to it, another Merchant's or an unknown id is the same 404, a failed run stores nothing, Evidence is not stored, the log line carries `conversation_id`; the purge runs at app startup (default 30 days, `CONVERSATION_RETENTION_DAYS`) and logs only a count. Apps built without a store keep their state under the test's `tmp_path` (`tests/conftest.py`), never in the repo.
- **Observability:** the log line fields, Judge scoring/flagging, the `coverage` verdict, `run_judges` returning verdicts, Evidence reaching the `answer` Judge (and its cap), the Judge model setting and warning.
- **Privacy:** each redaction pattern (formatted and bare) with negative cases, exception text, `user_ref`, every `LOG_MESSAGES` mode on request and Judge lines.
- **Scenario checking:** the pure function that scores routing and facts; the shared dataset loads and validates.
- **Eval runner:** aggregation over hand-built run records (pass rates, means, Mixed and incomplete rates, threshold decision, baseline deltas), the runner wiring with a fake graph and Judge model, and recall@4 with a fake index.
- **Ingestion:** the extraction XPath, on saved HTML fixtures.

**2. End-to-end scenarios (`scripts/scenarios.py`) and the eval runner (`scripts/eval.py`).** The scenarios run against the real container and the real LLM: the 10 challenge Messages, 3 Router edge cases (prompt injection, another Merchant's data, a Portuguese Message), 4 Mixed questions and 2 anonymous-visitor scenarios. Each gets a ✓/✗ on the expected Intent and on its expected facts, and the answers and Sources are printed for review. Before the Mixed questions, routing was consistently 13/13 and facts varied between runs (6/7, 7/7 and 5/7, the first before a fact was corrected; see the diary), mostly from nondeterministic retrieval. The [eval runner](#eval-runner) runs the same dataset in-process several times, with Judge Scores, so this variance is measured instead of eyeballed.

**CI (`.github/workflows/ci.yml`).** On every push and pull request (changes only under `.scratch/`, `docs/` or to the diary are skipped):
- `test`: `uv sync --locked`, then `uv run pytest`;
- `smoke`: `docker compose up -d --build`, wait up to 300 s for `/health` = 200, POST `{}` to `/chat` without a token (anonymous) and, after logging in via `/dev/login`, with the token, expecting 422 both times, print logs on failure, always `docker compose down -v`.

It uses no secrets: the app starts and builds its index without an LLM key, and `/chat` is never called with a valid body, so CI makes no LLM calls.

**3. How I'd approach full integration testing:**
- **Orchestration contract tests:** run the real graph with a real model and assert on structure, not wording:
  - which agent ran;
  - which tools were called, and with what context;
  - Sources are non-empty for corpus questions;
  - no Support tool is called for another or unknown `user_id`;
  - the reply is in the Message's language.
- **Golden dataset + LLM-as-judge:** built as the [eval runner](#eval-runner) (repeated runs, aggregate Judge Scores, baseline deltas). Next: thresholds on the aggregates that fail a CI job, and Judges calibrated against human labels.
- **Retrieval evaluation:** recall@4 is built; MRR is next. It isolates RAG regressions from generation regressions.
- **Adversarial suite:** prompt injection, cross-Merchant access, PII fishing, off-topic and harmful requests, all expected to end as `unsupported` with no tool calls.
- **Failure injection:** a stubbed provider that times out, returns 429 or returns malformed tool calls, plus an empty corpus and web search being down. Assert the documented 503/fallback behaviour.
- **Scenarios in CI:** the smoke test already exists (above); next, run the scenarios against it with an LLM key. The paid LLM suites run on prompt, model or corpus changes and nightly.

## Folder structure

```
.
├── app/                    # the service
│   ├── main.py             # FastAPI app: /chat, /me, /dev/login, /health, error mapping, request logging, judge scheduling
│   ├── auth.py             # tokens (issue/verify), Principal, mock operators
│   ├── store.py            # SQLite store: Conversations and Turns (WAL)
│   ├── graph.py            # LangGraph StateGraph, GraphState, Intent/Agent types, Source dedup
│   ├── router.py           # Router Agent (structured output) + shared intent policy
│   ├── knowledge.py        # Knowledge Agent + search_corpus / web_search tools
│   ├── support.py          # Customer Support Agent + account tools over mock data
│   ├── agents.py           # pieces shared by agents (language rule, tokens/steps summary)
│   ├── rag.py              # corpus loading, chunking, fastembed, Chroma index
│   ├── llm.py              # chat model factory + provider-error classification
│   ├── judge.py            # route / answer / coverage LLM judges (answer rated against Evidence)
│   ├── observability.py    # JSON log lines, user_ref, LOG_MESSAGES modes
│   ├── redact.py           # personal-data redactor for all log output
│   └── settings.py         # pydantic-settings (env vars)
├── corpus/                 # committed Getnet pages as markdown with url/lang/title front matter
├── data/merchants.json     # mock Merchant accounts (dates relative to today)
├── scripts/
│   ├── fetch_corpus.py     # ingestion: fetch + extract Getnet pages into corpus/
│   ├── scenarios.py        # end-to-end scenario runner against a running API
│   ├── eval.py             # in-process eval runner: repeated runs, Judges, aggregates, baseline deltas
│   └── retrieval.py        # recall@4 of the Corpus search
├── evals/
│   ├── scenarios.json      # shared scenario dataset (smoke script + eval runner)
│   ├── retrieval.json      # labelled Knowledge questions for recall@4
│   ├── baseline.json       # committed baseline results
│   └── results/            # per-run results (gitignored)
├── tests/                  # pytest suite (+ fixtures/ with saved HTML)
├── docs/
│   ├── adr/                # architecture decision records
│   └── agents/             # config for the agent skills (issue tracker, labels, domain docs)
├── .github/workflows/ci.yml  # tests + container smoke test
├── .scratch/getnet-multi-agent/  # spec.md + tickets (local issue tracker)
├── .scratch/improvement-fixes/   # improvement run: fixes spec + tickets
├── .scratch/eval-expansion/      # improvement run: eval expansion spec + tickets
├── IMPROVEMENT_RUN_DIARY.md  # improvement run: clock, sessions, decisions, scenario results
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

- **Identity:** the Merchant comes from a verified JWT, but tokens are issued by a demo "log in as" endpoint, not a real identity provider; no refresh or revocation.
- **Get Clássica:** the Corpus has little on it, so comparing it with Get Smart is weak.
- **Crediário installments:** retrieval sometimes misses the answer even though the Corpus has it.
- **Sources:** they can be noisy (every Chunk above the threshold from every search), so filter them to the ones the answer uses.
- **`steps`:** it counts tool calls that the limit blocked.
- ~~**Answer Judge vs. web search:** the Judge sees only the answer and the Source URLs/titles, not what the tools returned, and runs on the same model that wrote the reply.~~ **Fixed** in the improvement run: the `answer` Judge now rates the reply against the Evidence (capped tool output), and `JUDGE_MODEL` defaults to a different model family. Remaining: the Judges are not calibrated against human labels.
- ~~**Semantic quality:** Judge Scores existed only as single log lines, with no aggregate, baseline or repeated runs.~~ **Closed** in the improvement run by the [eval runner](#eval-runner): aggregate Judge Scores per Intent, a committed baseline with deltas, the `coverage` Judge and recall@4.
- **Multi-intent Router:** the baseline meets the agreed threshold (24% Mixed questions, 92% of them incomplete), so a Router that can hand one Message to both specialists is justified but not built yet.
- **Chroma:** old hash-named collections are never pruned.
- **Conversations:** Turns are stored, but the Agents don't see the history yet (next ticket).
- **Out of scope:** real Getnet APIs, JS-rendered pages, PDF manuals, LangSmith tracing.
- **Other bonuses (designed, not built):**
  - a Human Escalation Agent and handoff: a fourth graph node, triggered by a low-confidence Router, a low answer Judge Score or an explicit user request;
  - the dashboards, alerts and golden-set regression runs described in [Evaluation and observability strategy](#evaluation-and-observability-strategy).
