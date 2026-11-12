// Merchant view (role `merchant`): own Conversations, chat with Sources and Mode, account panel.
// Loaded before app.js, whose ROLE_VIEWS names `merchantView`; uses app.js's helpers
// (el, api, messageNode, errorLine) only at call time, after both scripts ran.
// Untrusted text only through textContent (via `el`); tests/test_page.py checks every static .js.
// Wrapped in a function so its names can't collide with other view scripts (classic scripts
// share one global scope); only `merchantView` is global.
"use strict";

const merchantView = (() => {

const TURNS_POLL_MS = 2000;
const LIST_POLL_MS = 5000;

const MODE_LABELS = { bot: "Assistant", waiting_human: "Waiting", human: "Agent", closed: "Closed" };
const MODE_BANNERS = {
  waiting_human: "Waiting for an agent…",
  human: "Talking to an agent",
  closed: "This conversation is closed.",
};

function modeBadge(mode) {
  return el("span", { class: "badge mode mode-" + mode }, MODE_LABELS[mode] || mode);
}

function formatWhen(iso) {
  const date = new Date(iso);
  return isNaN(date) ? String(iso) : date.toLocaleString();
}

function merchantView(container) {
  const state = {
    current: null,      // open Conversation id; null = a new one, started by the first Message
    lastTurnId: 0,      // for ?after=
    shown: new Set(),   // Turn ids already rendered
    mode: "bot",
    busy: false,        // a /chat request is in flight: no Turn polling meanwhile (avoids duplicates)
    generation: 0,      // bumped on every switch, so late responses for another Conversation are dropped
    stopped: false,
  };

  // ---------- left: Conversation list + account ----------

  const list = el("ul", { class: "conv-list" });
  const listError = el("div", { class: "error", role: "alert" });
  const sidebar = el("aside", { class: "merchant-side" },
    el("section", { class: "card conversations" },
      el("div", { class: "card-head" },
        el("h2", {}, "Conversations"),
        el("button", { type: "button", class: "button secondary", onclick: () => newConversation() }, "New conversation")),
      list, listError),
    accountPanel());

  async function loadList() {
    try {
      const data = await api("/conversations");
      if (state.stopped) return;
      listError.textContent = "";
      renderList(data.conversations);
    } catch (err) {
      if (err.code !== "session_expired" && !state.stopped) listError.textContent = err.message;
    }
  }

  function renderList(conversations) {
    if (!conversations.length) {
      list.replaceChildren(el("li", { class: "muted" }, "No conversations yet."));
      return;
    }
    // The API returns them most recently updated first.
    list.replaceChildren(...conversations.map((c) => el("li", {},
      el("button", {
        type: "button",
        class: "conv-item" + (c.id === state.current ? " active" : ""),
        "aria-current": c.id === state.current ? "true" : null,
        title: c.id,
        onclick: () => openConversation(c.id),
      },
      el("span", { class: "conv-when" }, formatWhen(c.updated_at)),
      modeBadge(c.mode)))));
  }

  // ---------- right: chat ----------

  const banner = el("div", { class: "mode-banner", role: "status", hidden: true });
  const messages = el("div", { class: "messages", "aria-live": "polite" });
  const chatError = el("div", { class: "error", role: "alert" });
  const input = el("textarea", { rows: 2, placeholder: "Type a message…", "aria-label": "Message" });
  const sendButton = el("button", { type: "submit", class: "button" }, "Send");
  const form = el("form", { class: "composer", onsubmit: (event) => { event.preventDefault(); send(); } },
    input, sendButton);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });
  const restart = el("div", { class: "closed-actions", hidden: true },
    el("button", { type: "button", class: "button", onclick: () => newConversation() }, "Start a new conversation"));
  const chatTitle = el("h2", {}, "New conversation");
  const chat = el("section", { class: "card chat merchant-chat" },
    chatTitle, banner, messages, chatError, form, restart);

  const scroll = () => { messages.scrollTop = messages.scrollHeight; };

  function setMode(mode) {
    state.mode = mode;
    const text = MODE_BANNERS[mode];
    banner.hidden = !text;
    banner.className = "mode-banner mode-" + mode;
    banner.textContent = text || "";
    const closed = mode === "closed";
    input.disabled = closed;
    sendButton.disabled = closed || state.busy;
    form.hidden = closed;
    restart.hidden = !closed;
  }

  function showTurns(turns) {
    for (const turn of turns) {
      if (!state.shown.has(turn.id)) {
        state.shown.add(turn.id);
        messages.append(messageNode(turn.role, turn.content, turn.role === "assistant" ? turn.sources : null));
      }
      state.lastTurnId = Math.max(state.lastTurnId, turn.id);
    }
    if (turns.length) scroll();
  }

  // New Turns of the open Conversation (all of them when lastTurnId is 0), plus its Mode.
  async function syncTurns() {
    const id = state.current;
    const generation = state.generation;
    if (!id) return;
    try {
      const data = await api("/conversations/" + encodeURIComponent(id) + "/turns?after=" + state.lastTurnId);
      if (generation !== state.generation || state.stopped) return;
      showTurns(data.turns);
      setMode(data.mode);
    } catch (err) {
      if (err.code !== "session_expired" && generation === state.generation) chatError.textContent = err.message;
    }
  }

  function reset(id) {
    state.generation += 1;
    state.current = id;
    state.lastTurnId = 0;
    state.shown = new Set();
    state.busy = false;
    messages.replaceChildren();
    chatError.textContent = "";
    input.value = "";
    setMode("bot");
  }

  function newConversation() {
    reset(null);
    chatTitle.textContent = "New conversation";
    messages.append(el("p", { class: "muted" },
      "Ask about your account, Settlements, Terminals or Getnet products. Your first message starts a conversation."));
    loadList();
    input.focus();
  }

  function openConversation(id) {
    reset(id);
    chatTitle.textContent = "Conversation";
    messages.append(el("p", { class: "muted" }, "Loading…"));
    const generation = state.generation;
    syncTurns().then(() => {
      if (generation === state.generation) messages.querySelector("p.muted")?.remove();
    });
    loadList();
  }

  async function send() {
    const text = input.value.trim();
    if (!text || state.busy || state.mode === "closed") return;
    const generation = state.generation;
    state.busy = true;
    sendButton.disabled = true;
    chatError.textContent = "";
    input.value = "";
    if (!state.current) messages.replaceChildren();  // drop the intro
    // Shown until the stored Turns come back from the server (then replaced by them).
    const mine = messageNode("user", text);
    mine.classList.add("unsent");
    messages.append(mine);
    // Outside `bot` nobody answers right away: the Message waits for the agent.
    const pending = state.mode === "bot" ? el("div", { class: "msg assistant pending" }, "Thinking…") : null;
    if (pending) messages.append(pending);
    scroll();
    const body = { message: text };
    if (state.current) body.conversation_id = state.current;
    try {
      const reply = await api("/chat", { method: "POST", body });
      if (generation !== state.generation || state.stopped) return;
      mine.remove();
      pending?.remove();
      if (!state.current) {
        state.current = reply.conversation_id;
        chatTitle.textContent = "Conversation";
      }
      state.busy = false;
      await syncTurns();
      loadList();
    } catch (err) {
      if (err.code === "session_expired" || generation !== state.generation) return;
      mine.remove();
      pending?.remove();
      if (err.code === "conversation_closed") {
        setMode("closed");
        loadList();
      } else {
        input.value = text;  // nothing was stored: let the Merchant send it again
        chatError.textContent = err.message;
      }
    } finally {
      if (generation === state.generation) {
        state.busy = false;
        sendButton.disabled = state.mode === "closed";
        if (state.mode !== "closed") input.focus();
      }
    }
  }

  // ---------- polling (paused while the tab is hidden) ----------

  const turnsTimer = setInterval(() => {
    if (!document.hidden && !state.busy) syncTurns();
  }, TURNS_POLL_MS);
  const listTimer = setInterval(() => {
    if (!document.hidden) loadList();
  }, LIST_POLL_MS);
  const onVisible = () => {
    if (!document.hidden) { loadList(); if (!state.busy) syncTurns(); }
  };
  document.addEventListener("visibilitychange", onVisible);

  container.append(sidebar, chat);
  newConversation();

  return () => {
    state.stopped = true;
    state.generation += 1;
    clearInterval(turnsTimer);
    clearInterval(listTimer);
    document.removeEventListener("visibilitychange", onVisible);
  };
}

// ---------- account panel (GET /me) ----------

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const RECENT_SETTLEMENTS = 6;

function humanize(key) {
  const text = String(key).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function money(value) {
  return typeof value === "number" ? BRL.format(value) : String(value ?? "");
}

function accountPanel() {
  const body = el("div", {}, el("p", { class: "muted" }, "Loading…"));
  const panel = el("details", { class: "card account", open: true },
    el("summary", {}, el("h2", {}, "Account")), body);
  api("/me")
    .then((me) => body.replaceChildren(...accountBody(me.account)))
    .catch((err) => { if (err.code !== "session_expired") body.replaceChildren(errorLine(err.message)); });
  return panel;
}

function accountBody(account) {
  if (!account) return [el("p", { class: "muted" }, "Account not found.")];
  const profile = account.profile || {};
  const terminals = account.terminals || [];
  const settlements = [...(account.settlements || [])]
    .sort((a, b) => String(b.sale_date || "").localeCompare(String(a.sale_date || "")))
    .slice(0, RECENT_SETTLEMENTS);
  return [
    el("h3", {}, "Profile"),
    el("dl", { class: "kv" }, Object.entries(profile).flatMap(([key, value]) =>
      [el("dt", {}, humanize(key)), el("dd", {}, String(value))])),
    el("h3", {}, "Terminals (" + terminals.length + ")"),
    terminals.length
      ? el("ul", { class: "account-list" }, terminals.map((t) => el("li", {},
        el("strong", {}, t.nickname || t.serial || "Terminal"), " ",
        el("span", { class: "badge status-" + String(t.status || "") }, t.status || "unknown"),
        el("div", { class: "muted" }, [t.model, t.serial].filter(Boolean).join(" · ")))))
      : el("p", { class: "muted" }, "No Terminals."),
    el("h3", {}, "Recent Settlements"),
    settlements.length
      ? el("ul", { class: "account-list" }, settlements.map((s) => el("li", {},
        el("strong", {}, money(s.net_amount)), " ",
        el("span", { class: "badge status-" + String(s.status || "") }, s.status || "unknown"),
        el("div", { class: "muted" },
          [s.payment_method, s.sale_date && "sold " + s.sale_date,
            s.expected_date && "expected " + s.expected_date].filter(Boolean).join(" · ")))))
      : el("p", { class: "muted" }, "No Settlements."),
  ];
}

return merchantView;
})();
