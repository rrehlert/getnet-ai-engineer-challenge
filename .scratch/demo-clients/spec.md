# Spec: Demo clients

Status: ready-for-agent

Run: improvement run, see `IMPROVEMENT_RUN_DIARY.md` (roadmap C1, C2, C3). Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/` (0004 SQLite, 0005 identity, 0006 takeover via Conversation Mode).
Builds on: `.scratch/conversations-identity/spec.md` (Conversations, Turns, tokens, `/me`) and `.scratch/human-takeover/spec.md` (Modes, Handoffs, Operator API). Outside the challenge's core deliverable.

## Problem Statement

Everything built so far is reachable only through curl and a shell helper. A reviewer can't see the takeover flow without juggling two terminals, two tokens and JSON. An Operator has no way to read a Handoff Brief, the Merchant's account and the logs for a Conversation in one place. The fixture has two Merchants, which is too thin to show the Escalation and account paths.

## Solution

- One static page, served by the app, with no build step. Logging in picks the view: **Merchant view**, **Operator view**, or anonymous chat when not logged in.
- Demo login from a dropdown of known users (`GET /dev/users`, behind `DEMO_LOGIN`). Without `DEMO_LOGIN` the page still works: paste a token, or chat anonymously.
- The token is kept in `localStorage`. The demo runs in two browser windows: a private window for the Merchant and a normal one for the Operator.
- The Operator view shows the live, redacted log events of a Conversation, held in an in-memory ring buffer.
- More mock Merchants, so the demo can show more paths (C3).
- Polling only, no SSE (C5 stays out).

## User Stories

1. As a reviewer, I want to open one URL and log in as any demo user from a list, so that I can try the system without curl.
2. As a reviewer, I want to run a Merchant and an Operator side by side in two browser windows, so that I can watch a takeover live.
3. As an anonymous visitor, I want to chat about products without logging in, so that I get help before I have an account.
4. As a Merchant, I want to see my Conversations and reopen one, so that I can continue where I left off.
5. As a Merchant, I want to start a new Conversation, so that a new topic doesn't mix with an old one.
6. As a Merchant, I want to see the Sources under an answer, so that I can check where it came from.
7. As a Merchant, I want to see whether I'm talking to the assistant or to an agent, and when I'm waiting for one, so that I know who is answering.
8. As a Merchant, I want Operator replies to appear without reloading, so that the Conversation feels live.
9. As a Merchant, I want a closed Conversation to be read-only with a way to start a new one, so that I know the case is finished.
10. As a Merchant, I want to see my account (profile, Terminals, recent Settlements), so that I can compare what the assistant says with my data.
11. As a user, I want to see who I'm logged in as, with which role and how long the session lasts, and to log out, so that I don't act as the wrong user.
12. As a user, I want an expired session to send me back to login with a clear message, so that I'm not left with silent errors.
13. As an Operator, I want a Queue of Conversations waiting for a human, with category, priority, ask and age, so that I pick the most urgent one.
14. As an Operator, I want a Review list of flagged Conversations, so that I can check low-scored bot replies.
15. As an Operator, I want to open a Conversation and see its Turns, Handoff Brief and the Merchant's account side by side, so that I understand the case at once.
16. As an Operator, I want the suggested reply prefilled and editable, so that I can answer faster.
17. As an Operator, I want only the actions valid for the Mode and my claim to be available, so that I don't hit errors by accident.
18. As an Operator, I want a clear message when another Operator got there first, so that I move on.
19. As an Operator, I want to see the Conversation's log events live, including Judge Scores that arrive later, so that I can see what the system did and how it was scored.
20. As a security reviewer, I want Operators to see events only for Conversations they may see, so that the events view doesn't leak other traffic.
21. As a security reviewer, I want all user and model text rendered as text, never as HTML, so that a Message can't inject script into the Operator's page.
22. As a reviewer, I want more Merchants with different account situations, so that the demo shows Escalation and account answers beyond the two original Merchants.

## Implementation Decisions

**Page**
- Vanilla HTML/JS/CSS in `app/static/` (`index.html`, `app.js`, `style.css`), served by FastAPI. No framework, no build step, no CDN, so it works offline in the container. Same origin as the API, so no CORS.
- UI labels in English. Chat content is in whatever language the user writes.
- Getnet red as the primary/accent colour (exact hex taken from getnet.com.br's CSS), white surfaces, neutral greys. No logo or wordmark. Title "Merchant Support (demo)".
- Untrusted text (Messages, answers, Operator replies, Handoff Brief, Source titles, events) is rendered only with `textContent`. Source links only for `http(s)` URLs. A test fails if `app.js` uses `innerHTML` with anything other than a static string.

**Login and session**
- `GET /dev/users` (exists only with `DEMO_LOGIN=true`, else 404) returns the fixture Merchant ids, the ids in `OPERATORS`, and a fixed unknown id (`nobody`). The page shows them as a dropdown, plus a free-text id field.
- Without `DEMO_LOGIN`: no dropdown; a "paste a token" field, and anonymous chat.
- The token is stored in `localStorage`. A header shows `sub`, role and the time left (decoded client-side, for display only), plus Logout.
- Any 401 clears the token and returns to login with "Session expired".

**Merchant view** (role `merchant`)
- Left: own Conversations (`GET /conversations`, newest first, Mode badge) and "New conversation". Right: chat.
- Assistant Turns show collapsible Sources (title + link). Operator Turns are labelled "Agent", bot Turns "Assistant".
- Mode banner: `waiting_human` "Waiting for an agent…", `human` "Talking to an agent". In `closed` the input is disabled and "Start a new conversation" is offered (a `/chat` 409 leads there too).
- Account panel from `GET /me` (profile, Terminals, recent Settlements), collapsible. An unknown Merchant sees "account not found".
- Anonymous (no token): chat only, no list, no account panel. Each Message is stateless, as on the API.

**Operator view** (role `operator`)
- Tabs: **Queue** (`GET /operator/queue`, oldest first: category, priority, customer_ask, age) and **Review** (`GET /operator/review`, newest first).
- Detail (`GET /operator/conversations/{id}`):
  - Turns;
  - Handoff Brief card;
  - account panel (fixture, from the API);
  - events panel;
  - reply textarea prefilled with `suggested_reply`. `used_suggestion = true` only when the sent text is byte-identical to it.
- Buttons by Mode and claim: Claim (`waiting_human`); Close (`waiting_human`, or `human` if claimed by me); Reply and Handback (`human`, claimed by me); Mark reviewed (flagged).
- 409 shows the conflict and refreshes the detail.

**Polling**
- The open Conversation's Turns (`?after=<last turn id>`) and events every 2 s. Lists every 5 s. Paused while the tab is hidden.

**Events ring buffer**
- A second logging handler keeps the last ~2000 formatted events in memory: the same redacted JSON that goes to stdout. stdout stays the source of record.
- `GET /operator/conversations/{id}/events` (role `operator`, same visibility rule as the detail, else 404): find the `request` events with this `conversation_id`, take their `trace_id`s, and return every buffered event with one of those `trace_id`s, oldest first. This picks up Judge events that arrive later.
- No global "tail all" view: it would show anonymous traffic and Conversations the Operator may not see.
- Limits: lost on restart, per process (single instance only), bounded size, so older events drop out. Documented in the README and in `IMPROVEMENT_RUN_DIARY.md`.

**More mock data (C3)**
- 2–3 new Merchants in `data/merchants.json`. `cliente1988` and `cliente2024` stay byte-identical (eval expected facts depend on them).
- Each new Merchant targets a path:
  - a failed or held Settlement, which should lead to an Escalation;
  - an inactive or defective Terminal;
  - a quiet Merchant with few transactions.
- No new eval scenarios; the dataset hash is unchanged.

## Testing Decisions

- Through `create_app` with TestClient, as in earlier specs. No browser automation.
- The page is served at `/` with its assets.
- `/dev/users`: 404 without `DEMO_LOGIN`; with it, lists the fixture Merchants, `OPERATORS` and `nobody`.
- Events endpoint: role enforcement (Merchant → 403); visibility (no Handoff, no flag → 404); returns only events of that Conversation's traces, including a Judge event emitted after the request; events of another Conversation are excluded; the buffer is bounded.
- `innerHTML` check over `app.js`.
- C3: the original Merchants are unchanged (eval dataset hash and expected facts still hold); the new Merchants load through `load_merchants`.
- Live check: two windows (private one for the Merchant, normal one for the Operator), walking through:
  - anonymous chat;
  - Merchant chat with Sources;
  - ask for a person → Queue → claim → reply with the suggestion → Merchant sees "Agent" → handback → bot answers;
  - escalate → close;
  - events panel showing the Judge events.

  Recorded in the diary.

## Out of Scope

- SSE / push delivery (roadmap C5); polling only.
- CLI changes (roadmap C4), dropped.
- Persistent event storage, global log tail, dashboards.
- Operator management, real identity provider.
- Browser automation tests.
- New eval scenarios.

## Further Notes

- Decisions from the demo-clients grilling (2026-11-12). No new Glossary terms or ADRs: the views and events panel are UI, and the ring buffer is easy to reverse.
- Planned tickets:
  1. page, `/dev/users`, login/session, anonymous chat (tracer bullet);
  2. Merchant view;
  3. Operator view;
  4. events ring buffer + endpoint + panel + README/diary notes on its limits;
  5. C3 mock Merchants (independent);
  6. live walkthrough, README "Demo client" section, diary entry.

  Order: 5 any time; 1 → 2 → 3 → 4 → 6.
- Tickets written after human-takeover was merged on `main` (`fd6d10f`); tickets in `issues/`.
- Continues improvement session 5 on the clock, same rules as A and B.
