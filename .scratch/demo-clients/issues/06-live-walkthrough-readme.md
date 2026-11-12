# 06: Live walkthrough, README, diary

**What to build:** Evidence that the demo client works on the real stack, and docs for it.

- `docker compose up --build`. Two windows: a private one for the Merchant, a normal one for `operador1`. Walk through:
  - anonymous chat;
  - Merchant chat with Sources;
  - ask for a person → Queue → claim → reply with the suggestion → Merchant sees "Agent" → handback → bot answers;
  - escalate → close;
  - the events panel shows the Judge events.

  Record trace ids.
- README: "Demo client" section (outside the core deliverable; how to open it, `DEMO_LOGIN`, two windows).
- Diary: session 5 entry (demo-clients part) (clock, commits, walkthrough).

**Blocked by:** 02, 03, 04 (05 if done)

**Status:** ready-for-agent

- [ ] Walkthrough done, trace ids recorded
- [ ] README section
- [ ] Diary entry with clock and evidence
