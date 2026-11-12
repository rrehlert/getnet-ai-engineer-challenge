// Merchant Support (demo): one static page, no framework, no build step.
// Every piece of user, model or server text goes into the DOM through textContent
// (via `el`), never as HTML; tests/test_page.py fails if this file uses innerHTML
// with anything but a static string literal.
"use strict";

const TOKEN_KEY = "demo.token";
const $ = (id) => document.getElementById(id);

// ---------- DOM helpers ----------

// el("div", {class: "x", onclick: fn}, child, "text", ...): strings become text nodes.
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// Only http(s) links are rendered as links; anything else stays plain text.
function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

// ---------- session ----------

const session = {
  token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  save(token) {
    try { localStorage.setItem(TOKEN_KEY, token); } catch { /* private mode: session lasts this page only */ }
    memoryToken = token;
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
    memoryToken = null;
  },
};
let memoryToken = null;
const currentToken = () => session.token() || memoryToken;

// The token's claims, decoded for display only (the server verifies the signature).
function claimsOf(token) {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(part).split("").map((c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join(""),
    );
    const claims = JSON.parse(json);
    return typeof claims.sub === "string" && typeof claims.role === "string" ? claims : null;
  } catch {
    return null;
  }
}

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

// fetch + JSON, with the token when there is one. Any 401 ends the session.
async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  const token = auth ? currentToken() : null;
  if (token) headers.Authorization = "Bearer " + token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server.");
  }
  const data = await response.json().catch(() => null);
  if (response.status === 401 && token) {
    endSession("Session expired. Log in again.");
    throw new ApiError(401, "session_expired", "Session expired.");
  }
  if (!response.ok) {
    const error = (data && data.error) || {};
    throw new ApiError(response.status, error.code || "http_" + response.status,
      error.message || (data && data.detail) || "Request failed (" + response.status + ").");
  }
  return data;
}

// ---------- app shell ----------

let sessionTimer = null;
let viewCleanup = null;  // set by a role view to stop its timers (polling in 02/03)

function endSession(notice) {
  session.clear();
  render(notice);
}

function stopView() {
  if (sessionTimer) clearInterval(sessionTimer);
  sessionTimer = null;
  if (viewCleanup) viewCleanup();
  viewCleanup = null;
}

function render(notice) {
  stopView();
  const main = $("main");
  main.replaceChildren();
  const token = currentToken();
  const claims = token ? claimsOf(token) : null;
  if (token && !claims) session.clear();
  if (!claims) {
    $("session").hidden = true;
    main.className = "main anonymous";
    main.append(loginCard(notice), anonymousChat());
    return;
  }
  showSessionHeader(claims);
  main.className = "main " + claims.role;
  const view = ROLE_VIEWS[claims.role] || unknownRoleView;
  viewCleanup = view(main, claims) || null;
}

function showSessionHeader(claims) {
  $("session").hidden = false;
  $("session-sub").textContent = claims.sub;
  $("session-role").textContent = claims.role;
  const tick = () => {
    const left = Math.floor(claims.exp - Date.now() / 1000);
    $("session-left").textContent = left > 0 ? formatLeft(left) + " left" : "expired";
  };
  tick();
  sessionTimer = setInterval(tick, 1000);
}

function formatLeft(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m >= 60 ? Math.floor(m / 60) + "h " + (m % 60) + "m" : m + "m " + String(s).padStart(2, "0") + "s";
}

// ---------- login ----------

// With DEMO_LOGIN: a dropdown from /dev/users plus a free-text id. Without it (404): paste a token.
function loginCard(notice) {
  const card = el("section", { class: "card login" }, el("h2", {}, "Log in"));
  if (notice) card.append(el("div", { class: "notice", role: "status" }, notice));
  const body = el("div", {}, el("p", { class: "muted" }, "Loading…"));
  card.append(body);
  api("/dev/users", { auth: false })
    .then((data) => body.replaceChildren(devLoginForm(data.users)))
    .catch((err) => body.replaceChildren(err.status === 404 ? pasteTokenForm() : errorLine(err.message)));
  return card;
}

function devLoginForm(users) {
  const idInput = el("input", { id: "login-id", name: "user_id", autocomplete: "off", placeholder: "any user id" });
  const select = el("select", { id: "login-pick", onchange: () => { idInput.value = select.value; } },
    el("option", { value: "" }, "Choose a demo user…"),
    users.map((u) => el("option", { value: u.id }, u.id + " (" + u.role + ")")));
  const error = el("div", { class: "error", role: "alert" });
  const submit = el("button", { type: "submit", class: "button" }, "Log in");
  const form = el("form", {
    onsubmit: async (event) => {
      event.preventDefault();
      const userId = idInput.value.trim();
      if (!userId) { error.textContent = "Choose a user or type an id."; return; }
      submit.disabled = true;
      try {
        const data = await api("/dev/login", { method: "POST", body: { user_id: userId }, auth: false });
        session.save(data.access_token);
        render();
      } catch (err) {
        error.textContent = err.message;
        submit.disabled = false;
      }
    },
  },
  el("label", { for: "login-pick" }, "Demo user"), select,
  el("label", { for: "login-id" }, "User id"), idInput,
  el("div", { class: "row" }, submit), error);
  return form;
}

function pasteTokenForm() {
  const input = el("textarea", { id: "login-token", rows: 3, placeholder: "eyJ…", spellcheck: "false" });
  const error = el("div", { class: "error", role: "alert" });
  const submit = el("button", { type: "submit", class: "button" }, "Use token");
  return el("form", {
    onsubmit: async (event) => {
      event.preventDefault();
      const token = input.value.trim();
      if (!claimsOf(token)) { error.textContent = "That doesn't look like a token."; return; }
      submit.disabled = true;
      try {
        // Checked once against the server, so a bad token is rejected here rather than later.
        const response = await fetch("/me", { headers: { Authorization: "Bearer " + token } });
        if (!response.ok) throw new Error("The server rejected this token.");
        session.save(token);
        render();
      } catch (err) {
        error.textContent = err.message === "Failed to fetch" ? "Cannot reach the server." : err.message;
        submit.disabled = false;
      }
    },
  },
  el("p", { class: "muted" }, "Demo login is off on this server. Paste a token, or chat anonymously."),
  el("label", { for: "login-token" }, "Token"), input,
  el("div", { class: "row" }, submit), error);
}

function errorLine(text) {
  return el("div", { class: "error", role: "alert" }, text);
}

// ---------- chat building blocks (reused by the Merchant view, 02) ----------

const AUTHORS = { user: "You", assistant: "Assistant", operator: "Agent" };

// One message bubble. `sources`: [{title, url}], shown collapsed under an answer.
function messageNode(role, text, sources) {
  const node = el("div", { class: "msg " + role }, el("span", { class: "author" }, AUTHORS[role] || role), text);
  if (sources && sources.length) node.append(sourcesNode(sources));
  return node;
}

function sourcesNode(sources) {
  return el("details", { class: "sources" },
    el("summary", {}, "Sources (" + sources.length + ")"),
    el("ul", {}, sources.map((s) => {
      const href = safeUrl(s.url);
      const label = s.title || s.url;
      return el("li", {}, href ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, label) : label);
    })));
}

// A chat panel: message list + composer. `send(text)` resolves to {answer, sources} or throws.
function chatPanel({ title, intro, send }) {
  const messages = el("div", { class: "messages", "aria-live": "polite" });
  if (intro) messages.append(el("p", { class: "muted" }, intro));
  const input = el("textarea", { rows: 2, placeholder: "Type a message…", "aria-label": "Message" });
  const button = el("button", { type: "submit", class: "button" }, "Send");
  const scroll = () => { messages.scrollTop = messages.scrollHeight; };
  const form = el("form", {
    class: "composer",
    onsubmit: async (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      button.disabled = true;
      messages.append(messageNode("user", text));
      const pending = el("div", { class: "msg assistant pending" }, "Thinking…");
      messages.append(pending);
      scroll();
      try {
        const reply = await send(text);
        pending.replaceWith(messageNode("assistant", reply.answer, reply.sources));
      } catch (err) {
        if (err.code === "session_expired") return;  // the page already went back to login
        pending.replaceWith(errorLine(err.message));
      } finally {
        button.disabled = false;
        scroll();
        input.focus();
      }
    },
  }, input, button);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });
  return el("section", { class: "card chat" }, el("h2", {}, title), messages, form);
}

// ---------- anonymous ----------

// No token: stateless chat over /chat (each Message on its own, product questions only).
function anonymousChat() {
  return chatPanel({
    title: "Chat without logging in",
    intro: "Ask about Getnet products. Log in to ask about your account.",
    send: (message) => api("/chat", { method: "POST", body: { message }, auth: false }),
  });
}

// ---------- role views (filled in by tickets 02 and 03) ----------

// Each view gets (container, claims), renders into the container and may return a cleanup function.
function merchantView(container, claims) {
  container.append(el("section", { class: "card" },
    el("h2", {}, "Merchant view"),
    el("p", { class: "muted" }, "Logged in as " + claims.sub + ". Conversations and account are coming soon.")));
}

function operatorView(container, claims) {
  container.append(el("section", { class: "card" },
    el("h2", {}, "Operator view"),
    el("p", { class: "muted" }, "Logged in as " + claims.sub + ". Queue and Review are coming soon.")));
}

function unknownRoleView(container, claims) {
  container.append(el("section", { class: "card" }, el("h2", {}, "Unknown role"),
    el("p", {}, "This page has no view for role " + claims.role + ".")));
}

const ROLE_VIEWS = { merchant: merchantView, operator: operatorView };

// ---------- start ----------

document.addEventListener("DOMContentLoaded", () => {
  $("logout").addEventListener("click", () => endSession());
  render();
  // Check a stored token once: an expired one goes back to login with "Session expired".
  if (currentToken() && claimsOf(currentToken())) api("/me").catch(() => {});
});
