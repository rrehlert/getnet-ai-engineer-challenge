# 05: List Conversations and read Turns

**What to build:** A Merchant can list their own Conversations and read the Turns of one, to resume it. Another Merchant's Conversation looks like it doesn't exist.

- `GET /conversations`: the caller's Conversations, newest first (by `updated_at`).
- `GET /conversations/{id}/turns?after=<turn id>`: Turns in order, optionally only those after a Turn id. Owner check: other Merchant's or unknown id → 404.
- Anonymous → 401. Operator token → 403 (operator endpoints come with human takeover).

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Listing returns only the caller's Conversations, newest first
- [ ] Turns returned in order with role, content, intent, sources, created_at
- [ ] `after` filter returns only later Turns
- [ ] Other Merchant's / unknown id → 404
- [ ] No token → 401
