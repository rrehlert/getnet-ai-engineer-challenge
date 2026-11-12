# 01: Page, demo login, session, anonymous chat

**What to build:** Tracer bullet for the demo client. Opening `/` serves a static page. A visitor can chat anonymously, or log in, see who they are and log out.

- `app/static/` with `index.html`, `app.js`, `style.css`, served by FastAPI at `/`. No framework, no build step, no CDN.
- Styling: Getnet red as the primary/accent colour (exact hex taken from getnet.com.br's CSS), white surfaces, neutral greys. No logo or wordmark. Title "Merchant Support (demo)". UI labels in English.
- `GET /dev/users`: only with `DEMO_LOGIN=true` (else 404, like `/dev/login`). Returns the fixture Merchant ids (`load_merchants` keys), the `OPERATORS` ids, and `nobody`, each with its role.
- Login: a dropdown from `/dev/users` plus a free-text id field, calling `/dev/login`. Without `DEMO_LOGIN`: no dropdown; a "paste a token" field instead.
- The token is stored in `localStorage`. Header: `sub`, role, time left (decoded client-side, display only), Logout.
- Any 401 clears the token and returns to login with "Session expired".
- Anonymous (no token): a chat box over `/chat`, stateless, no list or account panel.
- Logged in: a placeholder view per role (filled in by 02 and 03).
- All untrusted text is rendered with `textContent`. A test fails if `app.js` uses `innerHTML` with anything other than a static string.

**Blocked by:** none

**Status:** done

- [x] `/` serves the page and its assets
- [x] `/dev/users` 404 without `DEMO_LOGIN`; with it, lists fixture Merchants, Operators and `nobody` with roles
- [x] Login via dropdown, free-text id, and pasted token
- [x] Session header, Logout, 401 → back to login
- [x] Anonymous chat works end to end
- [x] `innerHTML` check in the test suite

## Comments

- Static files in `app/static/` (`index.html`, `app.js`, `style.css`). `create_app` serves `GET /` (`FileResponse`, `include_in_schema=False`, CSP `default-src 'self'`, no inline script) and mounts `/static` (`StaticFiles`, `STATIC_DIR` in `app/main.py`). Docker: `COPY . .` already ships `app/static/`; `.dockerignore` excludes nothing under `app/`, so no change.
- Colour: `#ec0000`, the `--gnt-red` / `--primary` custom property in getnet.com.br's `header.min.css` (also the most used hex on the home page). Greys `#282828`, `#66707a`, `#e1e6eb`, `#f5f7fa` and tint `#fbe4e4` from the same site. No logo or wordmark.
- `GET /dev/users` (behind `demo_login_enabled`, so 404 like `/dev/login`): `DevUsers{users: [DevUser{id, role}]}`, `load_merchants` keys (today from the auth clock), sorted `OPERATORS`, then `nobody` (`UNKNOWN_DEMO_USER`). Roles from new `app.auth.role_for(sub)`, which `AuthSettings.issue` now uses too, so list and token can't disagree.
- `app.js`: `el(tag, attrs, ...children)` is the only DOM builder (strings become text nodes); `safeUrl` lets only http(s) links through. `api(path, {method, body, auth})` wraps fetch: adds the bearer token, maps the API error shape to `ApiError{status, code, message}`, and on any 401 with a token calls `endSession("Session expired…")` (clears `localStorage["demo.token"]`, back to login). A stored token is checked once with `/me` at load.
- Login: `/dev/users` 200 → dropdown + free-text id (the dropdown fills the id field; one submit path to `/dev/login`); 404 → paste-a-token form, checked against `/me` before it's stored. Header: `sub`, role badge, time left from the decoded `exp` (display only, ticks each second), Logout.
- Anonymous: `chatPanel` over `/chat` without a token, stateless, Sources shown collapsed under the answer, errors (503 starting/provider etc.) shown inline.
- Seams for 02/03: `ROLE_VIEWS = {merchant: merchantView, operator: operatorView}`, each `(container, claims)`, may return a cleanup function (`viewCleanup`, called on re-render/logout, for polling timers). Reusable: `chatPanel({title, intro, send})`, `messageNode(role, text, sources)` (authors You/Assistant/Agent), `sourcesNode`, `errorLine`, `api`. Placeholders say "coming soon".
- Tests: `tests/test_page.py` (22), `create_app` + TestClient, no graph built, Judges off: `/` + CSP, assets byte-identical, page works without DEMO_LOGIN, no external `src`/`href`/`@import`, `/dev/users` 404 off and exact list on, every listed user logs in with the listed role. HTML-sink check: `innerHTML` allowed only as `= "static literal";`; `insertAdjacentHTML`, `outerHTML`, `document.write`, `createContextualFragment`, `DOMParser` forbidden; the checker is itself tested with bad and good samples. `app.js` currently uses no `innerHTML` at all.
- Not tested: the JS itself (no browser automation, per spec); checked with `node --check` only, not clicked through in a browser. Live check belongs to 06. Ruff isn't configured in this repo, so no lint run.

