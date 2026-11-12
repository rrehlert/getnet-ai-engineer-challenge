// Events panel (ticket 04): the redacted log events of the open Conversation's traces, Judge events included.
// Loaded after operator.js; registers itself in its OPERATOR_PANELS and uses app.js's `el` and `api`.
// Every event field goes in through textContent (via `el`), never as HTML.
"use strict";

(() => {
  // Shown inline when present, in this order; the full event is in the expandable JSON.
  const KEY_FIELDS = ["intent", "agent", "tools", "judge_type", "judge_score", "fully_answered", "tokens", "latency_ms", "outcome"];

  function clock(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function fieldText(key, value) {
    if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
    if (key === "latency_ms") return value + " ms";
    return String(value);
  }

  function eventNode(event, json, expanded) {
    const level = String(event.level || "").toLowerCase();
    const fields = KEY_FIELDS
      .filter((k) => event[k] !== undefined && event[k] !== null)
      .map((k) => el("span", { class: "ev-field" }, el("span", { class: "ev-key" }, k.replace(/_/g, " ")), " " + fieldText(k, event[k])));
    const row = el("details", { class: "ev-row ev-level-" + level, open: expanded.has(json) },
      el("summary", {},
        el("span", { class: "ev-time", title: event.time || "" }, clock(event.time)),
        el("span", { class: "ev-name" }, event.event || "?"),
        el("span", { class: "ev-level" }, event.level || ""),
        el("span", { class: "ev-trace muted", title: "trace " + (event.trace_id || "") }, String(event.trace_id || "").slice(0, 8)),
        ...fields),
      el("pre", { class: "ev-json" }, JSON.stringify(event, null, 2)));
    row.addEventListener("toggle", () => { if (row.open) expanded.add(json); else expanded.delete(json); });
    return row;
  }

  OPERATOR_PANELS.push({
    create(conversationId) {
      let stopped = false;
      let loading = false;
      let lastJson = null;
      const expanded = new Set();  // events whose JSON is open, kept across refreshes
      const count = el("span", { class: "muted" });
      const status = el("div", { class: "muted ev-status" }, "Loading events…");
      const list = el("div", { class: "ev-list" });
      const node = el("section", { class: "card ev-panel" },
        el("h3", {}, "Events ", count),
        el("p", { class: "muted ev-note" },
          "Recent redacted log lines of this Conversation's traces, from this server's memory: lost on restart, oldest dropped first."),
        status, list);

      function render(events) {
        status.textContent = events.length ? "" : "No events buffered for this Conversation.";
        status.hidden = events.length > 0;
        const json = JSON.stringify(events);
        if (json === lastJson) return;  // unchanged: keep the rows (and what is expanded)
        lastJson = json;
        count.textContent = "(" + events.length + ")";
        list.replaceChildren(...events.map((e) => eventNode(e, JSON.stringify(e), expanded)));
      }

      async function load() {
        if (stopped || loading) return;
        loading = true;
        try {
          const data = await api("/operator/conversations/" + encodeURIComponent(conversationId) + "/events");
          if (!stopped) render(data.events || []);
        } catch (err) {
          if (stopped || err.code === "session_expired") return;
          status.hidden = false;
          status.textContent = err.status === 404 ? "Events unavailable: Conversation not visible." : "Events: " + err.message;
        } finally {
          loading = false;
        }
      }

      return {
        node,
        update() { load(); },
        stop() { stopped = true; },
      };
    },
  });
})();
