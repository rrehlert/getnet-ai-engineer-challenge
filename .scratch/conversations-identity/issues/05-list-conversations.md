# 05: List Conversations and read Turns

**What to build:** A Merchant can list their own Conversations and read the Turns of one, to resume it. Another Merchant's Conversation looks like it doesn't exist.

- `GET /conversations`: the caller's Conversations, newest first (by `updated_at`).
- `GET /conversations/{id}/turns?after=<turn id>`: Turns in order, optionally only those after a Turn id. Owner check: other Merchant's or unknown id → 404.
- Anonymous → 401. Operator token → 403 (operator endpoints come with human takeover).

**Blocked by:** 03

**Status:** done

- [x] Listing returns only the caller's Conversations, newest first
- [x] Turns returned in order with role, content, intent, sources, created_at
- [x] `after` filter returns only later Turns
- [x] Other Merchant's / unknown id → 404
- [x] No token → 401

## Comments

- Store: `conversations(owner)` (newest first by `updated_at`, ties by insertion) added at the end of `Store`; `turns(id, after=0)` gained an optional `after` (Turn id > after). Existing callers unchanged.
- API (after `/chat` in `create_app`): `GET /conversations` → `{conversations: [{id, created_at, updated_at, mode}]}` (`mode` included now for the human takeover); `GET /conversations/{id}/turns?after=` → `{conversation_id, turns: [{id, role, content, intent, sources, created_at}]}`. Unknown/other Merchant's id → same 404 body (`conversation_not_found`) as `/chat`. `after` < 0 → 422.
- Auth: new `owner` dependency on top of `principal`: no token → 401 `unauthorized`, bad token → 401 `invalid_token`, operator → 403 `forbidden` (per spec: operator endpoints come with human takeover).
- Tests: `tests/test_listing.py` (HTTP, 10) + 2 Store tests in `tests/test_store.py`. README Overview, examples, Testing strategy updated (260 tests).
