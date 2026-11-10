# Spec: Conversations and identity

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md`. Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/` (0004 SQLite single store, 0005 identity from a verified token).
Builds on: `.scratch/improvement-fixes/spec.md` (log privacy, Evidence, index volume).

## Problem Statement

Every Message is handled on its own. A Merchant who says "my card machine is offline" and then "it's the Smart one" gets two unrelated answers, because nothing remembers the first Message.

The Merchant's identity is whatever `user_id` the caller puts in the request body. The tools are well protected from the model (it can never choose whose data they read), but nothing protects them from the caller: anyone who knows or guesses a user id gets that Merchant's account data.

Nothing is stored, so there is no record of past Conversations, and nothing an operator could later read to pick up a case.

## Solution

- Merchants log in and receive a signed token. Identity comes only from a verified token, never from the request body. In this demo, login is a dev stand-in ("log in as" a known Merchant, behind a flag); the real artifact is the verification boundary, which a real identity provider would plug into.
- Visitors without a token can still chat, but only with the Knowledge Agent: account questions get a fixed "log in to see your account" reply, and the Customer Support Agent never runs.
- Logged-in Merchants have Conversations. Each Conversation belongs to one Merchant, keeps its Turns in SQLite, and gives the Router and specialists the recent history, so follow-up Messages make sense.
- A Merchant can list their own Conversations and read their Turns; any other Merchant's Conversation is indistinguishable from one that doesn't exist.
- Stored Conversations are deleted after a retention period.

## User Stories

1. As a Merchant, I want to log in as my account in the demo, so that the assistant knows who I am without me typing my user id.
2. As a Merchant, I want my identity to come only from my login, so that nobody can read my account by sending my user id.
3. As a security reviewer, I want every authenticated request to carry a signed, expiring token, so that identity can't be forged or reused forever.
4. As a security reviewer, I want the dev login disabled unless explicitly enabled, so that a real deployment can't issue tokens for arbitrary users.
5. As a security reviewer, I want a request with an invalid or expired token rejected, so that a bad token never falls back to anonymous access.
6. As a maintainer, I want the token secret configurable, with a warning when it's generated at startup, so that I know tokens won't survive a restart.
7. As a visitor without an account, I want to ask about Getnet products without logging in, so that I can learn before becoming a Merchant.
8. As a visitor, I want account questions answered with a clear "log in to see your account" reply, so that I know why I got no account data.
9. As a security reviewer, I want the Customer Support Agent never to run without a verified identity, so that account data can't be reached anonymously.
10. As a visitor, I want off-topic and malicious Messages refused as before, so that anonymous access doesn't weaken the Router.
11. As a Merchant, I want my first Message to start a Conversation and return its id, so that I can continue it.
12. As a Merchant, I want to send follow-up Messages in the same Conversation, so that "it's the Smart one" is understood in context.
13. As a Merchant, I want the Router to see the recent history, so that a short follow-up is routed to the right Agent.
14. As a Merchant, I want the specialists to see the recent history, so that their answers build on what was already said.
15. As a maintainer, I want only the last 10 Turns sent to the model, so that cost and latency stay bounded.
16. As a Merchant, I want account answers to use fresh tool data, not data quoted in old Turns, so that I never act on stale amounts.
17. As a Merchant, I want to list my own Conversations, so that I can resume one.
18. As a Merchant, I want to read the Turns of one of my Conversations, so that I can see what was said.
19. As a security reviewer, I want another Merchant's Conversation to return "not found", so that Conversation ids can't be probed.
20. As a security reviewer, I want Conversation ids to be random, so that they can't be guessed.
21. As a Merchant, I want my Conversations deleted after a retention period, so that my data isn't kept forever.
22. As a maintainer, I want Conversations to survive a container restart, so that a deploy doesn't wipe active chats.
23. As a maintainer, I want the index and the database on one volume, so that all state lives in one place.
24. As a developer, I want the CLI helper and the scenario script to log in first, so that they keep working with token-based identity.
25. As a developer, I want the store and auth injectable into the app, so that tests run against a temporary database and a fixed secret.
26. As an operator (future), I want operator accounts to exist with an operator role, so that the human takeover can authorize operator actions.
27. As a log reader, I want request lines to carry the Conversation id and the pseudonymized identity (or anonymous), so that I can follow a Conversation without seeing personal data.

## Implementation Decisions

**Identity**
- `POST /dev/login {user_id}` returns a signed JWT, only when `DEMO_LOGIN=true` (default `false`; compose sets `true`). Otherwise it returns 404. Accepted ids: Merchants in the fixture, a minimal mock operators list, and unknown ids (which log in as a Merchant with no account, keeping today's "account not found" path).
- Tokens: HS256 via PyJWT, claims `sub`, `role` (`merchant` | `operator`), `exp` (1 hour). Secret from `JWT_SECRET`; if empty, a random secret is generated at startup with a warning.
- Every request may carry `Authorization: Bearer <token>`. Valid → authenticated principal. Missing → anonymous. Present but invalid or expired → 401 (never downgraded to anonymous).
- `user_id` is removed from the `/chat` body. For authenticated Merchants it comes from `sub` and flows into graph state exactly as today, so `SupportContext` and the tools don't change.
- `GET /me` returns the principal (`sub`, `role`) and, for Merchants, the account profile and data from the fixture. Used by the frontend later.
- Operators cannot use `/chat` as a Merchant (403); their endpoints come with the human-takeover spec.

**Anonymous visitors**
- The graph runs with no Merchant. The Router prompt says the visitor is not logged in.
- Routing: `knowledge` → Knowledge Agent as today; `unsupported` → refusal as today; `support` → a fixed bilingual (PT + EN) "log in to see your account" reply from a small deterministic node, the Customer Support Agent never runs.
- Anonymous requests are stateless: no Conversation is created, `conversation_id` is rejected (401), and nothing is stored.

**Conversations and Turns**
- New domain terms: **Conversation** (an ordered series of Turns owned by one Merchant) and **Turn** (one Message and its reply, or a single message from one participant). Added to `GLOSSARY.md`; the existing "Message" entry loses "there is no conversation history".
- SQLite (WAL mode) is the single store (ADR 0004). No LangGraph checkpointer: the Turns table is the only history, passed explicitly into graph state.
- Tables:
  - `conversations`: `id` (random UUID), `owner`, `created_at`, `updated_at`, and a `mode` column defaulting to `bot` (used by human takeover);
  - `turns`: `id` (monotonic), `conversation_id`, `role` (`user` | `assistant` | `operator`, operator used later), `content`, `intent`, `sources`, `created_at`.
- `/chat` with a Merchant token: without `conversation_id` → a new Conversation owned by `sub`. With it → owner check: missing or owned by someone else → 404. The response gains `conversation_id`.
- Graph state gains `history`: the last 10 Turns before the current Message (role + content). Raw tool outputs and Evidence are not stored and not replayed; specialists call tools again for account facts.
- The Router and both specialists receive the history as prior chat messages. The Router prompt says to classify the latest Message in the light of the history.
- The user Turn and the assistant Turn are stored after a successful graph run. A failed run stores nothing.
- `GET /conversations`: the caller's Conversations, newest first. `GET /conversations/{id}/turns?after=<turn id>`: Turns in order; owner check as above. Anonymous → 401.

**Retention and storage**
- `CONVERSATION_RETENTION_DAYS` (default 30): Conversations not updated within the window are deleted, with their Turns, at startup.
- One state directory on the compose volume holding the Corpus index and the database. This moves the volume mount introduced by the fixes spec from the index directory to its parent.

**Logging**
- Request lines gain `conversation_id`; `user_ref` is the pseudonym of `sub`, or `anonymous`. Turn content is never logged beyond what `LOG_MESSAGES` already allows.

**Clients**
- The scenario script and the README's CLI helper log in via `/dev/login` first and send the token; the helper can carry a `conversation_id` across calls. Scenarios for anonymous access are added (product question answered, account question gets the login reply).

**Testability**
- `create_app` accepts an injected store and auth settings (secret, demo-login flag, clock for expiry), like it accepts an injected graph today.

**ADRs**
- 0004: SQLite as the single store (Turns, later takeover state and audit) instead of LangGraph checkpoints; Postgres as the documented next step for multiple instances.
- 0005: identity only from a verified token; dev login as the identity-provider stand-in; anonymous access limited to Knowledge.

## Testing Decisions

- Test external behaviour through `create_app` with TestClient, a temporary SQLite file and a fixed secret; graph and models are fakes. No real LLM calls.
- **Auth:** dev login on/off; token claims; missing token → anonymous; invalid signature and expired token → 401; operator token on `/chat` → 403.
- **Anonymous:** with a fake Router returning `support`, the Customer Support node is never called and the login reply is returned; `knowledge` and `unsupported` behave as today; `conversation_id` with no token → 401; nothing stored.
- **Identity flow:** with a fake graph capturing state, `user_id` equals the token's `sub`; a `user_id` in the body is ignored or rejected by validation.
- **Conversations:** first call creates and returns an id; second call with that id passes the previous Turns as `history`; history capped at 10 Turns; another Merchant's id → 404; unknown id → 404; failed graph run stores nothing.
- **Listing:** only the caller's Conversations; `after` filter on Turns.
- **History reaches agents:** with the existing scripted fake chat model, assert the Router and specialists receive prior Turns as messages before the current Message. Prior art: `tests/test_router.py`, `tests/test_knowledge.py`, `tests/test_support.py`.
- **Store:** create, append, list, ownership lookup, retention purge (with an injected clock), restart (reopen the same file).
- **Logging:** request line carries `conversation_id` and `user_ref`/`anonymous`. Prior art: `tests/test_observability.py`.
- Live check: compose up, log in, two-turn follow-up resolved, restart container, Conversation still listed.

## Out of Scope

- A real identity provider, passwords, refresh tokens, logout/revocation.
- Rolling summaries of older Turns.
- Anonymous memory and anonymous escalation.
- Human takeover, operator endpoints and audit (human-takeover spec).
- Frontend (demo-clients spec).
- Postgres, multiple instances.

## Further Notes

- Breaking API change: `user_id` leaves the body. README, CLI helper, scenarios and CI must be updated in the same feature.
- The CI smoke check (`/chat` with an empty body → 422) still holds: anonymous requests are allowed, so validation runs.
- Tickets are written when this feature starts, from the code as it is after the fixes.
