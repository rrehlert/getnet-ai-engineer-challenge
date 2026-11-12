# 02: Anonymous visitors (Knowledge only)

**What to build:** A visitor without a token can still chat, but only about Getnet products. Account questions get a fixed bilingual "log in to see your account" reply and the Customer Support Agent never runs.

- Missing token → anonymous (replaces the temporary 401 from 01). Invalid/expired token stays 401.
- The graph runs with no Merchant; the Router prompt says the visitor is not logged in.
- Routing: `knowledge` → Knowledge Agent as today; `unsupported` → refusal as today; `support` → a small deterministic node returning the PT + EN login reply.
- Anonymous requests are stateless: `conversation_id` without a token → 401 (once the field exists; until 03 lands, reject any such field), nothing stored.
- Request log `user_ref` is `anonymous`.
- Scenario dataset gains anonymous scenarios: product question answered, account question gets the login reply. Eval runner handles anonymous scenarios.
- CI smoke `/chat` with empty body → 422 holds without a token.

See ADR 0005.

**Blocked by:** 01

**Status:** done

- [x] No token + fake Router returning `support` → login reply; Customer Support node never called
- [x] No token + `knowledge` / `unsupported` behave as today
- [x] Invalid token still 401, not anonymous
- [x] Router prompt for anonymous says visitor is not logged in (scripted fake model asserts)
- [x] Log line carries `user_ref=anonymous`
- [x] Anonymous scenarios in dataset; scenario script and eval runner support them
- [x] No real LLM calls in tests

## Comments

Implementation notes (agent):
- Anonymous = `user_id` None in graph state. Enforced in the graph, not only the Router: `build_graph` sends `support` with no Merchant to a deterministic `login` node (`LOGIN_REPLY`, PT + EN), so the Customer Support Agent can't run anonymously whatever the Router says. `make_support` also raises if ever called without a Merchant.
- Response for that case: `intent` `support`, `agent` `router` (no specialist answered; `agent_for(intent, anonymous=...)`), `steps` `["router", "login"]`; `login` is not counted as a tool in the request log.
- Router prompt: identity paragraph swapped for "the visitor is not logged in" (`system_prompt(user_id)`); a Message naming any user id is another merchant's data (→ `unsupported`).
- `principal()` split: `optional_principal` (None without a token, 401 on a bad one), `principal` (401 when None, used by `/me`), `merchant` (None or Merchant, 403 operators).
- `ChatRequest.conversation_id: str | None` added only so an anonymous request carrying it is 401; with a token it is ignored until ticket 03.
- Judges: anonymous → route Judge sees "Merchant: none (not logged in)"; `answer` Judge uses a login-reply rubric for anonymous `support`.
- Dataset: anonymous scenarios use explicit `"user_id": null` (a missing key is still a dataset error). Baseline predates them, so the next eval warns about the dataset hash.
- Not verified live: real-LLM routing of the two anonymous scenarios; the new CI smoke step (not run locally).
