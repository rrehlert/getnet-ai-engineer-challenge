# 02: Merchant view

**What to build:** A logged-in Merchant sees their Conversations, chats in one, sees Sources and the Mode, sees Operator replies arrive, and sees their account.

- Left: own Conversations (`GET /conversations`, newest first, Mode badge) and "New conversation". Right: chat over `/chat` with `conversation_id`.
- Turns from `GET /conversations/{id}/turns`. Assistant Turns show collapsible Sources (title + link, `http(s)` only). Operator Turns are labelled "Agent", bot Turns "Assistant".
- Mode banner: `waiting_human` "Waiting for an agent…", `human` "Talking to an agent". `closed`: input disabled, "Start a new conversation" offered. A `/chat` 409 leads there too.
- Account panel from `GET /me` (profile, Terminals, recent Settlements), collapsible. For an unknown Merchant (`nobody`): "account not found".
- Polling: open Conversation's Turns with `?after=<last turn id>` every 2 s, list every 5 s, paused while the tab is hidden.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Conversation list with Mode badge; new Conversation; reopen an old one
- [ ] Sources under assistant Turns
- [ ] Mode banner and closed state
- [ ] Operator Turns appear by polling, labelled "Agent"
- [ ] Account panel, incl. unknown Merchant
