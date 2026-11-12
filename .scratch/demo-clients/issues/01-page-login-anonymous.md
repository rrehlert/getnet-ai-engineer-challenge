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

**Status:** ready-for-agent

- [ ] `/` serves the page and its assets
- [ ] `/dev/users` 404 without `DEMO_LOGIN`; with it, lists fixture Merchants, Operators and `nobody` with roles
- [ ] Login via dropdown, free-text id, and pasted token
- [ ] Session header, Logout, 401 → back to login
- [ ] Anonymous chat works end to end
- [ ] `innerHTML` check in the test suite
