# 02: Merchant view

**What to build:** A logged-in Merchant sees their Conversations, chats in one, sees Sources and the Mode, sees Operator replies arrive, and sees their account.

- Left: own Conversations (`GET /conversations`, newest first, Mode badge) and "New conversation". Right: chat over `/chat` with `conversation_id`.
- Turns from `GET /conversations/{id}/turns`. Assistant Turns show collapsible Sources (title + link, `http(s)` only). Operator Turns are labelled "Agent", bot Turns "Assistant".
- Mode banner: `waiting_human` "Waiting for an agent…", `human` "Talking to an agent". `closed`: input disabled, "Start a new conversation" offered. A `/chat` 409 leads there too.
- Account panel from `GET /me` (profile, Terminals, recent Settlements), collapsible. For an unknown Merchant (`nobody`): "account not found".
- Polling: open Conversation's Turns with `?after=<last turn id>` every 2 s, list every 5 s, paused while the tab is hidden.

**Blocked by:** 01

**Status:** done

- [x] Conversation list with Mode badge; new Conversation; reopen an old one
- [x] Sources under assistant Turns
- [x] Mode banner and closed state
- [x] Operator Turns appear by polling, labelled "Agent"
- [x] Account panel, incl. unknown Merchant

## Comments

- New `app/static/merchant.js`, loaded by `index.html` *before* `app.js` (both `defer`), because `ROLE_VIEWS` in `app.js` names `merchantView` when it runs. The file is one IIFE exporting only `const merchantView`, so its helper names can't clash with other view scripts (classic scripts share one global scope; 03's `operator.js` should do the same). `app.js`: only the placeholder `merchantView` removed (`ROLE_VIEWS` line unchanged). Uses `el`, `api`, `messageNode`, `errorLine` from `app.js` at call time.
- No backend change: `/conversations`, `/conversations/{id}/turns?after=`, `/chat` (`conversation_id`, 409 `conversation_closed`) and `/me` (`account`, null for `nobody`) were enough.
- Left: Conversations (API order = most recently updated first), each a button with `updated_at` (local time) + Mode badge (`bot` Assistant, `waiting_human` Waiting, `human` Agent, `closed` Closed), active one highlighted; "New conversation". Below: account `<details open>` from `/me`: profile key/values, Terminals (nickname, status, model · serial), last 6 Settlements by `sale_date` (net in BRL, status, method, sold/expected dates); `account: null` → "Account not found."
- Right: own chat panel (not `chatPanel`: it needs Turn ids, Mode and a closed state). Turns rendered by id (`shown` set, `lastTurnId` for `?after=`), so polling never duplicates. Sending shows the Message greyed (`unsent`) plus "Thinking…" only in `bot` (outside `bot` nobody answers right away; `/chat` returns `answer: ""`), then drops both and syncs the stored Turns. First Message of a new Conversation takes `conversation_id` from the reply. Errors: Message put back into the input, error shown inline (nothing was stored). 409 `conversation_closed` → closed state.
- Mode banner: `waiting_human` "Waiting for an agent…", `human` "Talking to an agent", `closed` "This conversation is closed." + composer hidden/disabled + "Start a new conversation". Mode comes from each Turns poll, so Claim/Close by an Operator shows up within 2 s.
- Polling: Turns of the open Conversation every 2 s (skipped while a `/chat` is in flight), list every 5 s, both skipped while `document.hidden`; a `visibilitychange` back to visible refreshes at once. A `generation` counter drops late responses for a Conversation no longer open. Cleanup (returned to `viewCleanup`): clears both intervals, removes the listener, ignores in-flight responses.
- CSS in the `/* Merchant view */` section at the end of `style.css`.
- Tests (`tests/test_page.py`, now 26): HTML-sink check now parametrized over every `app/static/*.js` (03's file is covered automatically); every static file served byte-identical; every `*.js` loaded by `index.html`; `merchant.js` before `app.js`; the other-origins check covers every static file. `node --check` on both scripts.
- Browser-verified (headless Chrome 157 over CDP, fake graph, no LLM, scratch script, not committed): account panel for `cliente1988` and "Account not found" for `nobody`; chat answer with Sources (collapsed, `https` link, `javascript:` URL as plain text, `<img onerror>` / `<b>` / `<script>` shown as text); escalation → "Waiting" banner + list badge; queued Message without "Thinking…" or duplicates; Operator claim → "Talking to an agent", Operator reply appears by polling labelled "Agent"; no requests while `document.hidden` (stubbed), polling resumes; Operator close + immediate send → 409 path → closed state, no stray Message; "Start a new conversation"; reopen old one shows all Turns once; no requests after Logout. Screenshot looked right at 1200 px. Not checked: narrow/mobile layout, a real tab switch (hidden was stubbed), a real model.
- Commit order slip: the test commit came before the `merchant.js` commit, so it fails on its own; green from the next commit on.
