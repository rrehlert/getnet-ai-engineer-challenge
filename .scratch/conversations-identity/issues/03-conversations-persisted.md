# 03: Conversations persisted in SQLite

**What to build:** A logged-in Merchant's first Message starts a Conversation and returns its id; follow-ups with that id are appended to the same Conversation. Conversations live in SQLite and survive a container restart. (History is not yet passed to the Agents; that's 04.)

- Store: SQLite in WAL mode, the single store (ADR 0004, no LangGraph checkpointer). Injectable into `create_app` (tests use a temporary file).
- Tables: `conversations` (`id` random UUID, `owner`, `created_at`, `updated_at`, `mode` default `bot`); `turns` (`id` monotonic, `conversation_id`, `role` `user`|`assistant`|`operator`, `content`, `intent`, `sources`, `created_at`).
- `/chat` with a Merchant token: no `conversation_id` → new Conversation owned by `sub`; with it → missing or owned by someone else → 404 (indistinguishable). Response gains `conversation_id`.
- User Turn and assistant Turn stored after a successful graph run; a failed run stores nothing. Raw tool outputs and Evidence are not stored.
- Request log lines carry `conversation_id`; Turn content never logged beyond what `LOG_MESSAGES` allows.
- Compose: one state directory on the volume holding the Corpus index and the database (moves the existing index mount to its parent).
- `GLOSSARY.md`: add Conversation and Turn; Message entry loses "there is no conversation history".

**Blocked by:** 01

**Status:** done

- [x] First call creates a Conversation and returns its id; second call with it appends Turns
- [x] Another Merchant's id → 404; unknown id → 404 (same response)
- [x] Failed graph run stores nothing
- [x] Store unit tests: create, append, ownership lookup, reopen same file after close
- [x] Log line carries `conversation_id`
- [x] Compose uses a single state volume for index + database
- [x] Glossary updated
- [x] No real LLM calls in tests

## Comments

- Store: `app/store.py`, stdlib `sqlite3`, one short-lived connection per call (threadpool-safe), WAL, `foreign_keys` on, `turns.id` `AUTOINCREMENT` (never reused after a purge, so ticket 05's `after` stays monotonic). Interface: `Store(path, clock=utc_now)`, `create_conversation(owner) -> id`, `conversation(id, owner) -> Conversation | None` (ownership lookup; other owner and missing look the same), `append_turns(id, [NewTurn])` (one transaction, bumps `updated_at`), `turns(id) -> list[Turn]` (no owner check). Timestamps are UTC ISO strings from the injectable clock (for 06's purge).
- `create_app(store=...)`; default `Store(settings.database_path)` resolved at startup (lifespan) like auth/log privacy.
- Setting: `STATE_DIR` (default `state`) replaces `CHROMA_DIR`; index at `STATE_DIR/chroma`, database at `STATE_DIR/conversations.db`. Compose volume `state:/app/state` (was `chroma:/app/chroma`); Dockerfile creates `/app/state` owned by `app`. A local `chroma/` from before is no longer used (rebuilt under `state/`).
- `/chat`: the ownership check runs before the graph (404 `conversation_not_found`, graph not run). The new Conversation is created only after a successful run, then both Turns appended (two transactions; a crash between them would leave an empty Conversation, which 06's retention would purge). Intent is stored on both Turns; Sources on the assistant Turn; Evidence never.
- Logging: `conversation_id` on the request line is passed unredacted (the redactor masks UUIDs as Pix keys), but only when it is a canonical UUID; any other caller-supplied value is logged as null.
- Tests: `tests/conftest.py` points `STATE_DIR` at `tmp_path` for every test, so apps built without a store never write into the repo.
- Verified live in a container (no LLM): `/app/state` holds `chroma/` + `conversations.db`, owned by `app`; unknown `conversation_id` → 404; a Conversation written in the container was still there after `docker restart`. The full two-turn `/chat` flow across a restart was not run live (needs an LLM key; ticket 07).
