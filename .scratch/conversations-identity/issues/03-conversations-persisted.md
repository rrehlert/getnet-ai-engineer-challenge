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

**Status:** ready-for-agent

- [ ] First call creates a Conversation and returns its id; second call with it appends Turns
- [ ] Another Merchant's id → 404; unknown id → 404 (same response)
- [ ] Failed graph run stores nothing
- [ ] Store unit tests: create, append, ownership lookup, reopen same file after close
- [ ] Log line carries `conversation_id`
- [ ] Compose uses a single state volume for index + database
- [ ] Glossary updated
- [ ] No real LLM calls in tests
