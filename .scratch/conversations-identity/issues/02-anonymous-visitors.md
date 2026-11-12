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

**Status:** ready-for-agent

- [ ] No token + fake Router returning `support` → login reply; Customer Support node never called
- [ ] No token + `knowledge` / `unsupported` behave as today
- [ ] Invalid token still 401, not anonymous
- [ ] Router prompt for anonymous says visitor is not logged in (scripted fake model asserts)
- [ ] Log line carries `user_ref=anonymous`
- [ ] Anonymous scenarios in dataset; scenario script and eval runner support them
- [ ] No real LLM calls in tests
