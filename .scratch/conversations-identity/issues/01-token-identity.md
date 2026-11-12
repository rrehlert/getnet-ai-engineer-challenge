# 01: Token identity on /chat

**What to build:** Merchants log in through a dev stand-in and get a signed token; `/chat` takes identity only from that token. `user_id` leaves the request body (breaking change), so every client switches to login-first in this same ticket.

- `POST /dev/login {user_id}` returns a JWT only when `DEMO_LOGIN=true` (default `false`, compose sets `true`); otherwise 404. Accepts fixture Merchants, a minimal mock operators list (role `operator`), and unknown ids (log in as a Merchant with no account, keeping the "account not found" path).
- Tokens: HS256 (PyJWT), claims `sub`, `role` (`merchant` | `operator`), `exp` (1 hour). Secret from `JWT_SECRET`; empty → random secret at startup with a warning.
- `Authorization: Bearer <token>`: valid → principal; present but invalid/expired → 401, never downgraded. **Missing token → 401 for now** (ticket 02 turns this into anonymous access).
- Merchant `sub` flows into graph state as `user_id` exactly as today; `SupportContext` and tools unchanged. A `user_id` in the body is ignored or rejected by validation.
- Operator token on `/chat` → 403.
- `GET /me`: `sub`, `role`, and for Merchants the account profile and data from the fixture.
- Request log `user_ref` is the pseudonym of `sub`.
- `create_app` accepts injected auth settings (secret, demo-login flag, clock for expiry).
- Clients: scenario script and README CLI helper log in via `/dev/login` first and send the token; README curl examples and the API section updated; CI smoke still green (empty body → 422 needs a token until 02, adjust accordingly).

See ADR 0005.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Dev login on → token with expected claims; off → 404
- [x] Unknown id logs in as Merchant; Support path gives "account not found"
- [x] Invalid signature → 401; expired token (injected clock) → 401; missing token → 401
- [x] Operator token on `/chat` → 403
- [x] Fake graph capturing state: `user_id` equals token `sub`; body `user_id` has no effect
- [x] `GET /me` returns principal and, for a Merchant, fixture account data
- [x] Empty `JWT_SECRET` → startup warning
- [x] Request log line `user_ref` derives from `sub`
- [x] Scenario script, CLI helper, README examples and CI smoke use login-first and pass
- [x] No real LLM calls in tests

## Comments

2026-11-11, implementation notes:
- Live stack not run; scenario script verified against a local uvicorn with a fake graph (login per user id; DEMO_LOGIN off → clear error, exit 2). CI smoke logs in, then `{}` → 422.
- Body `user_id` is ignored (pydantic default), not rejected.
- `/me`: operators get `{sub, role}` only; Merchants get `account` (null when not in the fixture).
- Mock operator: `operador1` (`app/auth.py` `OPERATORS`).
- Fixed a pre-existing leak: `tests/test_chat_api.py` and `tests/test_observability.py` app helpers picked up `JUDGE_ENABLED=true` from a local `.env` and scheduled real Judge calls; they now pass `judge_enabled=False`.
- Missing token → 401 is marked temporary in `principal()` and the README; ticket 02 changes it.
