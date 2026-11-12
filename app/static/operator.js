// Operator view (ticket 03): Queue, Mine and Review lists, Conversation detail, claim/reply/handback/close/reviewed.
// Loaded after app.js and uses its helpers (el, api, sourcesNode, errorLine). Registers itself in ROLE_VIEWS.
// All Turns, brief fields, account data and error messages go in through textContent (via `el`), never as HTML.
"use strict";

// Hook for extra panels in the Operator's Conversation detail (ticket 04: the events panel).
// Each entry: { create(conversationId) -> { node, update(detail), stop() } }.
// `create` runs when a Conversation is opened; `node` goes into the detail's panel slot;
// `update(detail)` runs after every detail refresh (every 2 s while the tab is visible, and after
// each action); `stop()` runs when another Conversation is opened or the view is left.
const OPERATOR_PANELS = [];

(() => {
  const LIST_MS = 5000;
  const DETAIL_MS = 2000;
  const AUTHORS = { user: "Merchant", assistant: "Assistant", operator: "Operator" };
  const MODE_LABELS = { bot: "bot", waiting_human: "waiting for human", human: "human", closed: "closed" };
  const TABS = [
    { name: "queue", label: "Queue", path: "/operator/queue", empty: "Nobody is waiting for an Operator." },
    { name: "mine", label: "Mine", path: "/operator/mine", empty: "You have no claimed Conversations." },
    { name: "review", label: "Review", path: "/operator/review", empty: "No Conversations flagged for Review." },
  ];
  const PICK = "Pick a Conversation from the Queue, Mine or the Review list.";

  // The open Conversation's id survives a reload (forgotten on logout, or when it 404s).
  const OPEN_KEY = "demo.operator.open";
  const openStore = {
    get() { try { return localStorage.getItem(OPEN_KEY); } catch { return null; } },
    set(id) { try { localStorage.setItem(OPEN_KEY, id); } catch { /* private mode: not remembered */ } },
    clear() { try { localStorage.removeItem(OPEN_KEY); } catch { /* ignore */ } },
  };
  // Scripts are deferred, so the page (and its Logout button) exists by DOMContentLoaded.
  document.addEventListener("DOMContentLoaded", () => {
    const logout = document.getElementById("logout");
    if (logout) logout.addEventListener("click", () => openStore.clear());
  });

  function age(iso) {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
    if (seconds < 60) return seconds + "s";
    const m = Math.floor(seconds / 60);
    if (m < 60) return m + "m";
    const h = Math.floor(m / 60);
    return h < 24 ? h + "h " + (m % 60) + "m" : Math.floor(h / 24) + "d " + (h % 24) + "h";
  }

  function time(iso) {
    const d = new Date(iso);
    return isNaN(d) ? String(iso) : d.toLocaleString();
  }

  function modeBadge(mode) {
    return el("span", { class: "badge op-mode op-mode-" + mode }, MODE_LABELS[mode] || mode);
  }

  // ---------- account (shape comes from the fixture; rendered generically, as text) ----------

  function scalarText(value) {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(scalarText).join("; ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function isScalar(value) {
    return value === null || typeof value !== "object";
  }

  function recordList(record) {
    return el("dl", { class: "op-dl" }, Object.entries(record).flatMap(([key, value]) => [
      el("dt", {}, key.replace(/_/g, " ")),
      el("dd", {}, Array.isArray(value) && value.length > 1
        ? el("ul", {}, value.map((v) => el("li", {}, scalarText(v))))
        : scalarText(value)),
    ]));
  }

  function recordsNode(records) {
    if (!records.length) return el("p", { class: "muted" }, "None.");
    const flat = records.every((r) => r && typeof r === "object" && Object.values(r).every(isScalar));
    if (!flat) return el("div", { class: "op-records" }, records.map((r) => (r && typeof r === "object" ? recordList(r) : el("p", {}, scalarText(r)))));
    const columns = [...new Set(records.flatMap((r) => Object.keys(r)))];
    return el("div", { class: "op-table-wrap" }, el("table", { class: "op-table" },
      el("thead", {}, el("tr", {}, columns.map((c) => el("th", {}, c.replace(/_/g, " "))))),
      el("tbody", {}, records.map((r) => el("tr", {}, columns.map((c) => el("td", {}, scalarText(r[c]))))))));
  }

  function accountNode(merchant, account) {
    const card = el("section", { class: "card op-account" }, el("h3", {}, "Account: " + merchant));
    if (!account) {
      card.append(el("p", { class: "muted" }, "Account not found in the fixture."));
      return card;
    }
    for (const [key, value] of Object.entries(account)) {
      const title = key.replace(/_/g, " ");
      let body;
      if (Array.isArray(value)) body = recordsNode(value);
      else if (value && typeof value === "object") body = recordList(value);
      else body = el("p", {}, scalarText(value));
      const count = Array.isArray(value) ? " (" + value.length + ")" : "";
      card.append(el("details", { class: "op-section", open: key === "profile" }, el("summary", {}, title + count), body));
    }
    return card;
  }

  // ---------- brief ----------

  function briefNode(handoff) {
    const card = el("section", { class: "card op-brief" }, el("h3", {}, "Handoff Brief"));
    if (!handoff) {
      card.append(el("p", { class: "muted" }, "No Handoff: this Conversation is here for Review only."));
      return card;
    }
    const b = handoff.brief;
    card.append(
      el("div", { class: "op-brief-tags" },
        el("span", { class: "badge op-priority op-priority-" + b.priority }, b.priority),
        el("span", { class: "badge op-category" }, b.category),
        b.language ? el("span", { class: "muted" }, "language: " + b.language) : null),
      el("dl", { class: "op-dl" },
        el("dt", {}, "Customer ask"), el("dd", {}, b.customer_ask),
        el("dt", {}, "Reason"), el("dd", {}, b.reason),
        el("dt", {}, "Summary"), el("dd", {}, b.summary),
        el("dt", {}, "Already tried"), el("dd", {}, b.attempted),
        el("dt", {}, "Suggested reply"), el("dd", { class: "op-suggestion" }, b.suggested_reply)),
      el("p", { class: "muted" },
        "Opened " + time(handoff.created_at) +
        (handoff.claimed_by ? " · claimed by " + handoff.claimed_by + " " + time(handoff.claimed_at) : " · unclaimed") +
        (handoff.outcome ? " · " + handoff.outcome + " " + time(handoff.ended_at) : "")));
    return card;
  }

  function turnNode(turn) {
    const node = el("div", { class: "msg " + turn.role },
      el("span", { class: "author" }, (AUTHORS[turn.role] || turn.role) + " · " + time(turn.created_at) +
        (turn.intent ? " · " + turn.intent : "")),
      turn.content);
    if (turn.sources && turn.sources.length) node.append(sourcesNode(turn.sources));
    return node;
  }

  // ---------- the view ----------

  function operatorView(container, claims) {
    const me = claims.sub;
    let tab = "queue";
    let lists = { queue: null, mine: null, review: null };
    let openId = null;
    let detail = null;
    let panels = [];
    let listTimer = null;
    let detailTimer = null;
    let stopped = false;
    // The reply draft: prefilled with the brief's suggested reply only while the Operator hasn't typed.
    const draft = { prefilled: null, touched: false };

    // Left: tabs + list.
    const tabButtons = Object.fromEntries(TABS.map((t) => [t.name,
      el("button", { type: "button", class: "op-tab", onclick: () => switchTab(t.name) }, t.label)]));
    const listBody = el("div", { class: "op-list" }, el("p", { class: "muted" }, "Loading…"));
    const listError = el("div", { class: "error", role: "alert" });
    const listCard = el("section", { class: "card op-lists" },
      el("div", { class: "op-tabs", role: "tablist" }, Object.values(tabButtons)), listError, listBody);

    // Right: detail, built once per opened Conversation and updated in place.
    const detailCard = el("section", { class: "card op-detail" },
      el("p", { class: "muted" }, PICK));

    container.append(el("div", { class: "op-layout" }, listCard, detailCard));

    // ---------- lists ----------

    function switchTab(name) {
      tab = name;
      renderList();
    }

    async function loadLists() {
      try {
        const results = await Promise.all(TABS.map((t) => api(t.path)));
        if (stopped) return;
        lists = Object.fromEntries(TABS.map((t, i) => [t.name, results[i].conversations]));
        listError.textContent = "";
        renderList();
      } catch (err) {
        if (stopped || err.code === "session_expired") return;
        listError.textContent = err.message;
      }
    }

    function renderList() {
      for (const t of TABS) {
        const button = tabButtons[t.name];
        button.textContent = t.label + (lists[t.name] ? " (" + lists[t.name].length + ")" : "");
        button.classList.toggle("active", tab === t.name);
        button.setAttribute("aria-selected", String(tab === t.name));
      }
      const items = lists[tab];
      if (!items) return;
      if (!items.length) {
        listBody.replaceChildren(el("p", { class: "muted" }, TABS.find((t) => t.name === tab).empty));
        return;
      }
      listBody.replaceChildren(el("ul", { class: "op-items" }, items.map((item) => {
        const selected = item.conversation_id === openId;
        const lines = tab !== "review"
          ? [
            el("div", { class: "op-item-head" },
              el("span", { class: "badge op-priority op-priority-" + item.priority }, item.priority),
              el("span", { class: "op-item-category" }, item.category),
              el("span", { class: "muted op-age" },
                tab === "mine" ? "claimed " + age(item.claimed_at) + " ago" : age(item.created_at))),
            el("div", { class: "op-item-ask" }, item.customer_ask),
          ]
          : [
            el("div", { class: "op-item-head" }, modeBadge(item.mode),
              el("span", { class: "muted op-age" }, "updated " + age(item.updated_at) + " ago")),
            el("div", { class: "op-item-ask muted" }, item.conversation_id),
          ];
        return el("li", {}, el("button", {
          type: "button", class: "op-item" + (selected ? " selected" : ""),
          "aria-current": selected ? "true" : false,
          onclick: () => openConversation(item.conversation_id),
        }, lines));
      })));
    }

    // ---------- detail ----------

    let parts = null;  // the open Conversation's DOM pieces
    let restoring = null;  // the id reopened from storage on load, until its first detail answer

    function forgetOpen() {
      stopPanels();
      openId = null;
      detail = null;
      parts = null;
      detailCard.replaceChildren(el("p", { class: "muted" }, PICK));
      renderList();
    }

    function buildDetail(id) {
      const textarea = el("textarea", { rows: 4, "aria-label": "Reply to the Merchant" });
      textarea.addEventListener("input", () => { draft.touched = true; updateSuggestionHint(); });
      const hint = el("span", { class: "muted op-hint" });
      const sendButton = el("button", { type: "submit", class: "button" }, "Send reply");
      const composer = el("form", { class: "op-composer", hidden: true, onsubmit: (event) => { event.preventDefault(); sendReply(); } },
        el("label", {}, "Reply to the Merchant"), textarea,
        el("div", { class: "row" }, sendButton, hint));
      const panelSlot = el("div", { class: "op-panels", "data-slot": "operator-panels" });
      parts = {
        id,
        head: el("div", { class: "op-detail-head" }),
        actions: el("div", { class: "row op-actions" }),
        actionError: el("div", { class: "error", role: "alert" }),
        turns: el("div", { class: "messages op-turns", "aria-live": "polite" }),
        brief: el("div", {}),
        account: el("div", {}),
        composer, textarea, hint, sendButton, panelSlot,
        keys: {},
      };
      detailCard.replaceChildren(
        parts.head, parts.actions, parts.actionError,
        el("div", { class: "op-columns" },
          el("div", { class: "op-col-main" },
            el("section", { class: "op-conversation" }, el("h3", {}, "Turns"), parts.turns), composer),
          el("div", { class: "op-col-side" }, parts.brief, parts.account)),
        panelSlot);
      panels = OPERATOR_PANELS.map((p) => p.create(id));
      for (const p of panels) if (p && p.node) panelSlot.append(p.node);
    }

    // Only parts whose data changed are rebuilt; the composer is never rebuilt.
    function changed(key, value) {
      const json = JSON.stringify(value);
      if (parts.keys[key] === json) return false;
      parts.keys[key] = json;
      return true;
    }

    function renderDetail() {
      const d = detail;
      const handoff = d.handoff;
      const claimedBy = handoff && !handoff.ended_at ? handoff.claimed_by : null;
      const mine = d.mode === "human" && claimedBy === me;

      if (changed("head", [d.mode, d.needs_review, claimedBy, d.merchant])) {
        parts.head.replaceChildren(
          el("h2", {}, "Conversation"),
          el("div", { class: "op-meta" },
            modeBadge(d.mode),
            d.needs_review ? el("span", { class: "badge op-flag" }, "flagged for Review") : null,
            el("span", { class: "muted" }, "Merchant " + d.merchant),
            el("span", { class: "muted" }, claimedBy ? "claimed by " + (claimedBy === me ? "you" : claimedBy) : "unclaimed"),
            el("span", { class: "muted op-id" }, d.conversation_id)));
      }

      const can = {
        claim: d.mode === "waiting_human",
        reply: mine,
        handback: mine,
        close: d.mode === "waiting_human" || mine,
        reviewed: d.needs_review,
      };
      if (changed("actions", can)) {
        parts.actions.replaceChildren(...[
          can.claim ? el("button", { type: "button", class: "button", onclick: () => act("claim") }, "Claim") : null,
          can.handback ? el("button", { type: "button", class: "button secondary", onclick: () => act("handback") }, "Hand back to bot") : null,
          can.close ? el("button", { type: "button", class: "button secondary", onclick: () => act("close") }, "Close") : null,
          can.reviewed ? el("button", { type: "button", class: "button secondary", onclick: () => act("reviewed") }, "Mark reviewed") : null,
          !Object.values(can).some(Boolean) ? el("span", { class: "muted" },
            d.mode === "human" ? "Another Operator holds this Conversation." : "No actions in Mode " + d.mode + ".") : null,
        ].filter(Boolean));
      }

      if (changed("turns", d.turns.map((t) => t.id))) {
        const atBottom = parts.turns.scrollHeight - parts.turns.scrollTop - parts.turns.clientHeight < 40;
        parts.turns.replaceChildren(...(d.turns.length ? d.turns.map(turnNode) : [el("p", { class: "muted" }, "No Turns.")]));
        if (atBottom || parts.keys.turnsScrolled === undefined) parts.turns.scrollTop = parts.turns.scrollHeight;
        parts.keys.turnsScrolled = true;
      }

      if (changed("brief", handoff)) parts.brief.replaceChildren(briefNode(handoff));
      if (changed("account", [d.merchant, d.account])) parts.account.replaceChildren(accountNode(d.merchant, d.account));

      parts.composer.hidden = !can.reply;
      const suggestion = handoff ? handoff.brief.suggested_reply : null;
      // Prefill on first load, and again only when the brief changes while the textarea is untouched.
      if (suggestion !== draft.prefilled && !draft.touched) {
        parts.textarea.value = suggestion || "";
        draft.prefilled = suggestion;
      }
      updateSuggestionHint();

      for (const p of panels) if (p && p.update) p.update(d);
    }

    function currentSuggestion() {
      return detail && detail.handoff ? detail.handoff.brief.suggested_reply : null;
    }

    function updateSuggestionHint() {
      if (!parts) return;
      const suggestion = currentSuggestion();
      parts.hint.textContent = suggestion !== null && parts.textarea.value === suggestion
        ? "Suggested reply, unchanged"
        : suggestion !== null ? "Edited (not the suggested reply)" : "";
    }

    async function loadDetail() {
      const id = openId;
      if (!id) return;
      try {
        const data = await api("/operator/conversations/" + encodeURIComponent(id));
        if (stopped || id !== openId) return;
        if (restoring === id) restoring = null;
        detail = data;
        renderDetail();
      } catch (err) {
        if (stopped || id !== openId || err.code === "session_expired") return;
        if (err.status === 404 && restoring === id) {
          // The remembered Conversation is gone (purged, or not visible): forget it without a word.
          restoring = null;
          openStore.clear();
          forgetOpen();
          return;
        }
        parts.actionError.textContent = err.status === 404
          ? "This Conversation is no longer visible to Operators."
          : err.message;
      }
    }

    function stopPanels() {
      for (const p of panels) if (p && p.stop) p.stop();
      panels = [];
    }

    function openConversation(id) {
      if (id === openId) return;
      stopPanels();
      openId = id;
      openStore.set(id);
      detail = null;
      draft.prefilled = null;
      draft.touched = false;
      buildDetail(id);
      parts.turns.append(el("p", { class: "muted" }, "Loading…"));
      renderList();
      loadDetail();
    }

    // POST an action; the API answers with the fresh detail. 409/403: show its message and refresh.
    async function act(action, body) {
      const id = openId;
      const buttons = [...parts.actions.querySelectorAll("button"), parts.sendButton];
      buttons.forEach((b) => { b.disabled = true; });
      parts.actionError.textContent = "";
      try {
        const data = await api("/operator/conversations/" + encodeURIComponent(id) + "/" + action,
          { method: "POST", body });
        if (stopped || id !== openId) return true;
        detail = data;
        renderDetail();
        if (action === "claim") switchTab("mine");
        return true;
      } catch (err) {
        if (stopped || id !== openId || err.code === "session_expired") return false;
        parts.actionError.textContent = err.message;
        await loadDetail();
        return false;
      } finally {
        buttons.forEach((b) => { b.disabled = false; });
        loadLists();
      }
    }

    async function sendReply() {
      const text = parts.textarea.value;
      if (!text.trim()) { parts.actionError.textContent = "Write a reply first."; return; }
      // Byte-identical to the current brief's suggestion, or it doesn't count as using it.
      const usedSuggestion = currentSuggestion() !== null && text === currentSuggestion();
      const ok = await act("reply", { content: text, used_suggestion: usedSuggestion });
      if (ok && !stopped) {
        parts.textarea.value = "";
        draft.touched = false;  // stays empty: `prefilled` still matches the brief, so no refill
        updateSuggestionHint();
      }
    }

    // ---------- polling ----------

    function onVisibility() {
      if (document.hidden) return;
      loadLists();
      loadDetail();
    }

    listTimer = setInterval(() => { if (!document.hidden) loadLists(); }, LIST_MS);
    detailTimer = setInterval(() => { if (!document.hidden) loadDetail(); }, DETAIL_MS);
    document.addEventListener("visibilitychange", onVisibility);
    renderList();
    loadLists();
    const remembered = openStore.get();
    if (remembered) {
      restoring = remembered;
      openConversation(remembered);
    }

    return () => {
      stopped = true;
      clearInterval(listTimer);
      clearInterval(detailTimer);
      document.removeEventListener("visibilitychange", onVisibility);
      stopPanels();
    };
  }

  ROLE_VIEWS.operator = operatorView;
})();
