"use strict";

const $ = (id) => document.getElementById(id);
function readPreference(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
const MAX_STEPS = 80;
const SECTION_LIMIT = 10;
const visibleRows = new Map();
const sectionOpen = new Map();
let revealed = "";
const DECISION_PREVIEW_LIMIT = 3;
const NEW_WINDOW_MS = 24 * 60 * 60 * 1000;
const KEY_KINDS = new Set(["user", "answer", "question", "decision", "edit", "agent"]);
const ICONS = {
  turn: "i-turn", user: "i-user", message: "i-message", answer: "i-answer", thinking: "i-thinking",
  command: "i-command", edit: "i-edit", tool: "i-tool", agent: "i-agent", decision: "i-decision", question: "i-question",
};
const STATUS = {
  waiting: { label: "Needs you", icon: "i-message-question" },
  working: { label: "Working", icon: "i-working" },
  done: { label: "Done", icon: "i-answer" },
  interrupted: { label: "Stopped", icon: "i-stop" },
  idle: { label: "Not started", icon: "i-turn" },
  dismissed: { label: "Reminder dismissed", icon: "i-question" },
};
const SECTION_ICONS = { waiting: "i-message-question", working: "i-working", new: "i-answer", earlier: "i-turn" };
const APP_NAME = { codex: "Codex", claude: "Claude Code", cursor: "Cursor" };

// Where the user acts on a chat; older payloads without `harness` are Codex chats.
function appName(chat) {
  return APP_NAME[chat?.harness] || APP_NAME.codex;
}

function quietHint(chat) {
  return `No activity recorded. It may be waiting for your approval in ${appName(chat)}, or running a long command.`;
}
const QUIET_NOTIFY_MS = 5 * 60 * 1000;
const CHECK_TAGS = {
  failed: { label: "Check failed", className: "tag--interrupted" },
  unchecked: { label: "Edits unchecked", className: "tag--idle" },
};
const NEXT_LABEL = { answer: "Answer", review: "Review", approve: "Approve", run: "Run", decide: "Decide", do: "To do" };
const STEP_LABEL = {
  command: "Ran a command", edit: "Edited files", tool: "Called a tool", thinking: "Reasoning", agent: "Delegated work",
  decision: "Made a decision", message: "Progress update", answer: "Wrote a response", question: "Asked a question",
};
const INBOX_FILTERS = {
  earlier: { label: "Earlier", empty: "No other chats in this recent inbox window." },
  waiting: { label: "Needs you", empty: "No recent chats need you right now." },
  working: { label: "Working", empty: "No recent chats are currently working." },
  new: { label: "New results", empty: "No unseen results in the recent inbox from the last 24 hours." },
};
const SECTIONS = [
  { key: "waiting", label: "Needs you" },
  { key: "working", label: "Working" },
  { key: "new", label: "New results" },
  { key: "earlier", label: "Earlier" },
];

const params = new URLSearchParams(location.search);
const threadId = params.get("thread") || "";
const statusParam = params.get("status");
const inboxStatus = Object.hasOwn(INBOX_FILTERS, statusParam) ? statusParam : "";
const inboxReturn = inboxStatus ? `&status=${inboxStatus}` : "";
document.body.dataset.view = threadId ? "thread" : "inbox";
if (threadId) $("nav-inbox").removeAttribute("aria-current");
const wideDetail = matchMedia("(min-width: 1280px)");
const calm = matchMedia("(prefers-reduced-motion: reduce)");
let inboxData = null;
let inboxLayout = "";
let threadData = null;
let filter = "key";
let openId = "";
let threadSource = null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${name}`);
  svg.append(use);
  return svg;
}

// Every working glyph shares one phase, so live re-renders never restart the rotation.
function syncSpin(use) {
  use.style.animationDelay = `-${performance.now() % 1400}ms`;
}

const ROW_ICONS = {
  "files-summary": "i-edit", "session-files-summary": "i-edit", "decision-history-summary": "i-decision", "earlier-summary": "i-turn",
  "activity-summary": "i-thinking", "session-summary": "i-session", "tools-summary": "i-tool",
};

function tone(name, kind) {
  const chip = el("span", "tone");
  chip.dataset.tone = kind;
  chip.append(icon(name));
  return chip;
}

function rowLabel(id, text, value = "") {
  const target = $(id);
  if (!target.querySelector(".row-label")) {
    const lead = icon(ROW_ICONS[id]);
    lead.classList.add("row-icon");
    const chevron = icon("i-chevron");
    chevron.classList.add("disclosure-chevron");
    target.replaceChildren(lead, el("span", "row-label"), el("span", "row-value"), chevron);
  }
  const label = target.querySelector(".row-label");
  if (label.textContent !== text) label.textContent = text;
  const detail = target.querySelector(".row-value");
  if (detail.textContent !== value) detail.textContent = value;
}

function clock(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function ago(iso) {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function chatName(chat) {
  return chat.title || `Untitled chat · ${chat.cwd.split("/").pop() || chat.id.slice(0, 8)}`;
}

// The full `<harness>:<id>` key routes any harness; older payloads only had the Codex id.
function chatKey(chat) {
  return chat.key || chat.id;
}

function isChat(chat, id) {
  return id === chatKey(chat) || id === chat.id;
}

const HARNESS_LABEL = { codex: "Codex", claude: "Claude", cursor: "Cursor" };

function projectName(chat) {
  return chat.project || chat.cwd.split("/").pop() || "Unassigned";
}

const seen = {
  get: (id) => readPreference(`seen:${id}`) || "",
  set: (id, endedAt) => {
    try { if (endedAt) localStorage.setItem(`seen:${id}`, endedAt); } catch { /* Keep results unread if storage is unavailable. */ }
  },
};

function setConnection(state, text) {
  $("connection").dataset.state = state;
  $("connection-text").textContent = text;
}

function connect(url, event, render) {
  const source = new EventSource(url);
  source.onopen = () => setConnection("live", "Live");
  source.onerror = () => setConnection("offline", "Reconnecting");
  source.addEventListener(event, (message) => render(JSON.parse(message.data)));
  return source;
}

// Inbox

function needsAttention(chat) {
  return hasAttention(chat) && !reminderDismissed(chat);
}

function hasAttention(chat) {
  return Boolean(chat.needs_you);
}

function reminderDismissed(chat) {
  if (!chat.attention_key) return false;
  return readPreference(`reminder:v1:${chat.id}`) === chat.attention_key;
}

function attentionState(chat) {
  return hasAttention(chat) ? reminderDismissed(chat) ? "dismissed" : "waiting" : chat.status;
}

function isNewResult(chat) {
  const ended = new Date(chat.turn_ended_at).getTime();
  return !hasAttention(chat) && chat.status !== "working" && chat.status !== "interrupted" && Date.now() - ended < NEW_WINDOW_MS && chat.turn_ended_at > seen.get(chat.id);
}

function sectionOf(chat) {
  return needsAttention(chat) ? "waiting" : chat.status === "working" ? "working" : isNewResult(chat) ? "new" : "earlier";
}

function chatSummary(chat) {
  if (hasAttention(chat)) return chat.question || chat.next_text || chat.outcome;
  if (chat.next_kind !== "none" && chat.next_kind !== "unknown" && chat.next_text) return chat.next_text;
  return chat.outcome;
}

function renderRow(chat) {
  const state = attentionState(chat);
  const status = STATUS[state] || STATUS.idle;
  const unread = isNewResult(chat);
  const item = el("li");
  const link = el("a", "row");
  link.href = `/?thread=${encodeURIComponent(chatKey(chat))}${inboxReturn}`;
  link.dataset.status = state;
  link.dataset.id = chatKey(chat);
  link.dataset.unread = String(unread);
  if (isChat(chat, openId)) link.setAttribute("aria-current", "true");
  const glyph = el("span", "glyph");
  glyph.append(icon(status.icon));
  if (state === "working") syncSpin(glyph.querySelector("use"));
  const body = el("span", "row-body");
  const head = el("span", "row-head");
  const time = el("span", "row-time", ago(chat.updated_at));
  time.dataset.ago = chat.updated_at;
  head.append(el("span", "row-title", chatName(chat)));
  body.append(head);
  const summary = chatSummary(chat);
  const description = el("span", "row-description");
  const summaryNode = el("span", "row-text", summary || "");
  const meta = el("span", "row-tags");
  const action = chat.question ? "Answer" : NEXT_LABEL[chat.next_kind];
  const tag = state === "waiting" ? action || status.label : state === "done" || state === "idle" ? "" : status.label;
  if (state === "working" && chat.quiet) {
    const quiet = el("span", "tag tag--waiting", `Quiet ${quietFor(chat)}`);
    quiet.dataset.quietAt = chat.updated_at;
    quiet.title = quietHint(chat);
    meta.append(quiet);
  } else if (tag) meta.append(el("span", `tag tag--${state}`, tag));
  if (unread && sectionOf(chat) !== "new") meta.append(el("span", "tag tag--new", "New"));
  // A Run step already says the check is still to do.
  const check = state === "working" || (chat.check_state === "unchecked" && chat.next_kind === "run") ? "" : CHECK_TAGS[chat.check_state];
  if (check) meta.append(el("span", `tag ${check.className}`, check.label));
  if (meta.childNodes.length) description.append(meta);
  description.append(summaryNode);
  body.append(description);
  if (state === "waiting" && chat.question && chat.options?.length) body.append(el("span", "row-options", chat.options.join(" · ")));
  const project = el("span", "row-project");
  if (HARNESS_LABEL[chat.harness]) project.append(el("span", "harness-pill", HARNESS_LABEL[chat.harness]));
  project.append(el("span", "", projectName(chat)));
  project.title = projectName(chat);
  const chevron = icon("i-chevron");
  chevron.classList.add("row-chevron");
  link.dataset.section = sectionOf(chat);
  link.append(glyph, body, project, time, chevron);
  item.append(link);
  return item;
}

// `fold` is "open" or "closed" for a section the user can collapse, "" otherwise.
function renderSection({ key, label }, chats, fold = "") {
  const limit = visibleRows.get(key) || SECTION_LIMIT;
  const wrap = el("section", "group");
  wrap.dataset.section = key;
  const title = el("h2", "group-title");
  title.id = `section-${key}`;
  const content = [tone(SECTION_ICONS[key], key === "earlier" ? "muted" : key), el("span", "section-label", label)];
  wrap.setAttribute("aria-labelledby", title.id);
  const heading = el("div", "section-heading");
  heading.append(title);
  wrap.append(heading);
  if (fold) {
    const toggle = el("button", "section-toggle");
    toggle.type = "button";
    toggle.id = `toggle-${key}`;
    toggle.setAttribute("aria-expanded", String(fold === "open"));
    toggle.setAttribute("aria-controls", `list-${key}`);
    const chevron = icon("i-chevron");
    chevron.classList.add("disclosure-chevron");
    if (fold === "closed") content.push(el("span", "section-count", String(chats.length)));
    toggle.append(...content, chevron);
    toggle.addEventListener("click", () => {
      sectionOpen.set(key, fold === "closed");
      renderInbox(inboxData);
      $(toggle.id)?.focus({ preventScroll: true });
    });
    title.append(toggle);
    if (fold === "closed") return wrap;
  } else {
    title.append(...content);
  }
  const list = el("ol", "list");
  list.id = `list-${key}`;
  list.replaceChildren(...chats.slice(0, limit).map(renderRow));
  if (chats.length === 0) list.append(el("li", "empty column-empty", "No chats"));
  wrap.append(list);
  if (chats.length > limit) {
    const more = el("button", "button load-more", "Load more");
    more.type = "button";
    more.setAttribute("aria-label", `Load more ${label.toLowerCase()} chats`);
    more.addEventListener("click", () => {
      visibleRows.set(key, limit + SECTION_LIMIT);
      renderInbox(inboxData);
      document.querySelectorAll(`#sections [data-section="${key}"] .row`)[limit]?.focus({ preventScroll: true });
    });
    wrap.append(more);
  }
  return wrap;
}

function groupChats(chats) {
  const groups = new Map(SECTIONS.map(({ key }) => [key, []]));
  for (const chat of chats) groups.get(sectionOf(chat)).push(chat);
  for (const list of groups.values()) list.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  // Longest wait first: the chat that has been blocked on you the longest is the one you are most likely to have missed.
  groups.get("waiting").sort((a, b) => waitingSince(a).localeCompare(waitingSince(b)));
  groups.get("working").sort((a, b) => Number(b.quiet) - Number(a.quiet) || (a.quiet ? a.updated_at.localeCompare(b.updated_at) : 0));
  return groups;
}

function quietFor(chat) {
  return ago(chat.updated_at).replace(/ ago$/, "");
}

function waitingSince(chat) {
  return chat.turn_ended_at || chat.updated_at;
}

function layoutOf(groups) {
  return [...groups].map(([key, list]) => `${key}:${list.map((chat) => chat.id).join(",")}`).join("|");
}

// View transitions ignore ancestor clipping, so only rows visible in their scroller get a name;
// the rest cross-fade with the page instead of flying over other columns.
function nameVisibleRows(on) {
  const clips = [{ top: 0, left: 0, bottom: innerHeight, right: innerWidth }, $("sections").getBoundingClientRect()];
  for (const row of $("sections").querySelectorAll(".row")) {
    const item = row.parentElement;
    const box = item.getBoundingClientRect();
    const visible = [...clips, row.closest(".list").getBoundingClientRect()]
      .every((clip) => box.bottom > clip.top && box.top < clip.bottom && box.right > clip.left && box.left < clip.right);
    item.style.viewTransitionName = on && visible ? `row-${row.dataset.id.replace(/[^\w-]/g, "_")}` : "";
  }
}

function transition(update, { rows = true } = {}) {
  if (!document.startViewTransition || calm.matches || document.hidden || threadId) {
    update();
    return Promise.resolve();
  }
  nameVisibleRows(rows);
  const view = document.startViewTransition(() => {
    update();
    nameVisibleRows(rows);
  });
  const clear = () => nameVisibleRows(false);
  view.finished.then(clear, clear);
  return view.updateCallbackDone.catch(() => {});
}

function liveInbox(chats) {
  notifyChanges(chats);
  if (inboxLayout && layoutOf(groupChats(chats)) !== inboxLayout) transition(() => renderInbox(chats));
  else renderInbox(chats);
}

function renderInbox(chats) {
  inboxData = chats;
  const focusedHref = document.activeElement.closest(".row, .show-all")?.getAttribute("href");
  const groups = groupChats(chats);
  inboxLayout = layoutOf(groups);
  // The approved inbox is a list at every width; wide screens can still open a detail pane.
  const shown = SECTIONS.filter(({ key }) => inboxStatus ? key === inboxStatus && groups.get(key).length > 0 : groups.get(key).length > 0);
  // Sections fold only when there is another section to see. Earlier is history, so it starts folded;
  // once it has been shown open it stays open, so a new chat never folds the list under the reader.
  const foldable = !inboxStatus && shown.length > 1;
  if (!foldable && groups.get("earlier").length > 0 && !sectionOpen.has("earlier")) sectionOpen.set("earlier", true);
  const openKey = shown.find(({ key }) => groups.get(key).some((chat) => isChat(chat, openId)))?.key;
  if (openKey && revealed !== `${openId}:${openKey}`) {
    revealed = `${openId}:${openKey}`;
    sectionOpen.set(openKey, true);
  }
  const fold = (key) => foldable ? ((sectionOpen.get(key) ?? key !== "earlier") ? "open" : "closed") : "";
  $("sections").replaceChildren(...shown.map((section) => renderSection(section, groups.get(section.key), fold(section.key))));
  $("inbox-empty").hidden = chats.length > 0;
  $("filter-empty").hidden = !inboxStatus || shown.length > 0 || chats.length === 0;
  $("filter-empty").textContent = inboxStatus ? INBOX_FILTERS[inboxStatus].empty : "";
  syncNavigation(chats);
  if (focusedHref) [...$("sections").querySelectorAll("a")].find((link) => link.getAttribute("href") === focusedHref)?.focus({ preventScroll: true });
  const needs = groups.get("waiting").length;
  document.title = needs ? `(${needs}) Your Turn` : "Your Turn";
  setFavicon(needs > 0);
}

function syncNavigation(chats) {
  const groups = groupChats(chats);
  const selector = $("compact-status");
  for (const option of selector.options) {
    const kind = option.value;
    const count = kind ? groups.get(kind).length : chats.length;
    option.textContent = `${kind ? INBOX_FILTERS[kind].label : "All chats"} (${count})`;
  }
  if (document.activeElement !== selector) selector.value = inboxStatus;
  for (const segment of document.querySelectorAll(".segment")) {
    const kind = segment.dataset.kind;
    segment.href = inboxUrl(kind, threadId ? "" : openId);
    const count = kind ? groups.get(kind).length : chats.length;
    segment.dataset.empty = String(count === 0);
    segment.querySelector(".segment-count").textContent = count;
    const label = kind ? INBOX_FILTERS[kind].label : "All recent chats";
    segment.setAttribute("aria-label", `${label}: ${count} ${count === 1 ? "chat" : "chats"}`);
    if (kind === inboxStatus) segment.setAttribute("aria-current", "page");
    else segment.removeAttribute("aria-current");
  }
  // The bar hides its scrollbar, so bring a newly selected tab into view without moving the page.
  const bar = document.querySelector(".segments");
  const current = bar?.querySelector('[aria-current="page"]');
  if (current && bar.dataset.shown !== inboxStatus) {
    bar.dataset.shown = inboxStatus;
    if (current.offsetLeft < bar.scrollLeft || current.offsetLeft + current.offsetWidth > bar.scrollLeft + bar.clientWidth) {
      bar.scrollLeft = current.offsetLeft - (bar.clientWidth - current.offsetWidth) / 2;
    }
  }
}

$("compact-status").addEventListener("change", (event) => {
  location.assign(inboxUrl(event.target.value, openId));
});

function setFavicon(alert) {
  const href = alert ? "/assets/icon-alert.svg" : "/assets/icon.svg";
  if ($("favicon").getAttribute("href") !== href) $("favicon").setAttribute("href", href);
}

// Notifications: opt-in, from the inbox page only, and only for changes after the page loaded.

const notifySupported = "Notification" in window && window.isSecureContext;
let alerts = null;

function notifyOn() {
  return notifySupported && Notification.permission === "granted" && readPreference("notify") === "on";
}

function alertOf(chat) {
  if (needsAttention(chat)) return { key: `need:${chat.attention_key || chat.turn_ended_at}`, title: `Needs you: ${chatName(chat)}`, body: chatSummary(chat) || "" };
  // Long builds also go quiet, so quiet chats notify later than they are tagged.
  if (chat.status === "working" && chat.quiet && Date.now() - new Date(chat.updated_at).getTime() > QUIET_NOTIFY_MS) {
    return { key: `quiet:${chat.updated_at}`, title: `Quiet ${quietFor(chat)}: ${chatName(chat)}`, body: quietHint(chat) };
  }
  return null;
}

function notifyChanges(chats) {
  const next = new Map(chats.map((chat) => [chat.id, alertOf(chat)?.key || ""]));
  if (alerts && notifyOn() && (document.hidden || !document.hasFocus())) {
    for (const chat of chats) {
      const alert = alertOf(chat);
      if (!alert || alerts.get(chat.id) === alert.key) continue;
      const notice = new Notification(alert.title, { body: alert.body, tag: chat.id, icon: "/assets/icon-alert.svg" });
      notice.onclick = () => {
        window.focus();
        notice.close();
        if (wideDetail.matches && !threadId) {
          history.pushState(null, "", inboxUrl(inboxStatus, chatKey(chat)));
          showPanel(chatKey(chat));
        } else location.assign(`/?thread=${encodeURIComponent(chatKey(chat))}${inboxReturn}`);
      };
    }
  }
  alerts = next;
}

// Thread

function tokenCount(value, compact = false) {
  return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString(compact ? "en-US" : undefined, compact ? { notation: "compact", maximumFractionDigits: 1 } : {}) : "Not reported";
}

async function copyThreadId() {
  const value = $("session-thread-id").textContent;
  try {
    await navigator.clipboard.writeText(value);
    if ($("session-thread-id").textContent === value) $("copy-thread-status").textContent = "Thread ID copied.";
  } catch {
    $("copy-thread-status").textContent = "Couldn’t copy. Select the Thread ID above and copy it manually.";
  }
}
$("copy-thread-id").addEventListener("click", copyThreadId);

$("open-codex").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  const command = button.dataset.copy;
  if (!command) return;
  event.preventDefault();
  const text = button.firstChild;
  try {
    await navigator.clipboard.writeText(command);
    button.dataset.copied = "true";
    text.textContent = "Resume command copied";
  } catch {
    text.textContent = command;  // Shown so it can be selected and copied by hand.
  }
  setTimeout(() => {
    delete button.dataset.copied;
    if (button.dataset.copy === command) text.textContent = "Copy resume command";
  }, 2000);
});

function renderSessionInfo(thread, turn) {
  if ($("session-thread-id").textContent !== thread.id) {
    $("session-thread-id").textContent = thread.id;
    $("copy-thread-status").textContent = "";
  }
  const usage = thread.token_usage || {};
  const last = thread.last_token_usage || {};
  const contextWindow = thread.context_window;
  const hasContext = Number.isSafeInteger(last.total_tokens) && last.total_tokens >= 0 && Number.isSafeInteger(contextWindow) && contextWindow > 0;
  const brief = [
    Number.isSafeInteger(usage.total_tokens) ? `${tokenCount(usage.total_tokens, true)} tokens` : "",
    hasContext ? `${Math.round(last.total_tokens / contextWindow * 100)}% context` : "",
  ].filter(Boolean).join(" · ");
  rowLabel("session-summary", "Session details", brief);
  const usageLabels = {
    total_tokens: "Session total", input_tokens: "Input", output_tokens: "Output",
    cached_input_tokens: "Cached input (included in input)", cache_write_input_tokens: "Cache-write input",
    reasoning_output_tokens: "Reasoning (included in output)",
  };
  const groups = [
    {
      label: "Usage", icon: "i-usage",
      facts: Object.entries(usageLabels).filter(([key]) => Object.hasOwn(usage, key)).map(([key, label]) => [label, tokenCount(usage[key])]),
    },
    {
      label: "Runtime", icon: "i-runtime",
      facts: [["Model (latest turn)", thread.model], ["Reasoning effort", thread.reasoning_effort], ["Session provider", thread.model_provider], ["Session client", thread.cli_version]],
    },
    {
      label: "Workspace", icon: "i-workspace",
      facts: [["Project", projectName(thread)], ["Recorded Git branch", thread.git_branch], ["Working directory", thread.cwd]],
    },
    {
      label: "Turn", icon: "i-turn",
      facts: [
        ["Turn", turn?.index ? String(turn.index) : ""], ["Last request tokens", tokenCount(last.total_tokens)],
        ["Reported context window", contextWindow > 0 ? tokenCount(contextWindow) : "Not reported"],
        ["Totals reported", thread.token_usage_at && !Number.isNaN(new Date(thread.token_usage_at).getTime()) ? new Date(thread.token_usage_at).toLocaleString() : ""],
      ],
    },
  ];
  $("session-facts").replaceChildren(...groups.flatMap(({ label, icon: iconName, facts }) => {
    const entries = facts.filter(([, value]) => value);
    if (!entries.length) return [];
    const heading = el("h3", "session-group-title", label);
    heading.prepend(icon(iconName));
    const list = el("dl", "session-facts");
    list.append(...entries.map(([name, value]) => {
      const field = el("div");
      field.append(el("dt", "", name), el("dd", "", value));
      return field;
    }));
    const group = el("section", "session-group");
    group.append(heading, list);
    return [group];
  }));
}

function setStatusText(content, command = false) {
  const target = $("status-text");
  const text = typeof content === "string" ? content : "";
  // Leave the selected text untouched when an unrelated value changes.
  if (target.textContent === text && Boolean(target.querySelector("code")) === command) return;
  target.replaceChildren(command ? commandCode(text) : el("p", "", text));
}

function renderStatus(thread, turn) {
  const chat = { ...thread, next_kind: turn?.next_kind, next_text: turn?.next_text };
  const state = attentionState(chat);
  const status = STATUS[state] || STATUS.idle;
  $("status-card").dataset.status = state;
  const quiet = state === "working" && Boolean(thread.quiet);
  $("status-card").dataset.quiet = String(quiet);
  $("status-icon").setAttribute("href", `#${status.icon}`);
  if (state === "working") syncSpin($("status-icon"));
  // A waiting request says how long it has waited, so a fresh ask and a stale one read differently.
  const waited = state === "waiting" ? ago(turn?.ended_at || thread.updated_at) : "";
  $("status-title").textContent = quiet ? "Working · quiet" : waited && waited !== "just now" ? `${status.label} · ${waited}` : status.label;
  const failed = thread.status !== "working" && Boolean(turn?.checks.some((check) => check.exit_code !== null && check.exit_code !== 0));
  // Codex and Cursor open by deep link (Cursor: the project folder); Claude Code offers its resume command.
  const resume = thread.harness === "claude" ? thread.handoff?.resume_command || "" : "";
  const link = thread.harness === "cursor" ? thread.handoff?.open_uri || "" : `codex://threads/${encodeURIComponent(thread.id)}`;
  const action = resume ? "Copy resume command" : `Open in ${appName(thread)}`;
  // Keep "Resume command copied" visible until its timeout restores the label.
  if (!$("open-codex").dataset.copied) $("open-codex").firstChild.textContent = action;
  $("open-codex").dataset.copy = resume;
  $("open-codex").href = resume ? "#" : link;
  $("open-codex").setAttribute("aria-label", resume ? `${action}: ${resume}` : thread.harness === "cursor" ? "Open the project in Cursor" : "Open in Codex (full chat)");
  $("open-codex").title = resume;
  $("open-codex").hidden = !resume && !link;
  $("open-codex").dataset.emphasis = state === "waiting" || failed ? "" : "quiet";
  $("status-body").hidden = false;

  const pending = [...thread.decisions].reverse().find((d) => d.source === "asked" && d.chosen === null);
  let kind = turn ? turn.next_kind : "unknown";
  let label = NEXT_LABEL[kind] || "";
  if (thread.status === "working") {
    const step = [...thread.steps].reverse().find((step) => step.turn === turn?.index && !["turn", "user"].includes(step.kind));
    kind = "working";
    label = STEP_LABEL[step?.kind] || "";
    const listed = (step?.kind === "edit" && turn?.files.length > 0) || (step?.kind === "command" && turn?.checks.some((check) => check.command === step.title));
    if (listed) {
      setStatusText(`${label}, shown under ${step.kind === "edit" ? "What happened" : "Checks"}.`);
      label = "";
    } else setStatusText(step?.title || "Working on your request.", step?.kind === "command" && Boolean(step.title));
    if (thread.quiet) label = "Quiet";
  } else if (pending) {
    kind = "answer";
    label = NEXT_LABEL.answer;
    setStatusText(pending.question);
  } else if (kind === "none") {
    setStatusText(failed ? "No further action was requested, but a check failed." : "No further action was requested.");
  } else if (kind === "unknown") {
    setStatusText(failed ? "No next action was recorded, but a check failed." : "No next action was recorded.");
  } else {
    setStatusText(turn.next_text);
  }
  $("status-body").dataset.kind = kind;
  $("status-body").dataset.check = failed && (kind === "none" || kind === "unknown") ? "failed" : "";
  const quietNote = quiet ? `No activity since ${clock(thread.updated_at)} (${ago(thread.updated_at)}). ${quietHint(thread).replace(/^No activity recorded\. /, "")}` : "";
  $("quiet-note").hidden = !quiet;
  if ($("quiet-note").textContent !== quietNote) $("quiet-note").textContent = quietNote;
  // One headline per request: drop the kind label when the request already starts with it
  // ("Approve" above "Approve pending action in Cursor").
  if (label && $("status-text").textContent.trim().toLowerCase().startsWith(label.toLowerCase())) label = "";
  $("next-kind").hidden = !label;
  $("next-kind").textContent = label;
  const options = pending && thread.status !== "working" ? pending.options : [];
  $("next-options").hidden = options.length === 0;
  $("next-options").replaceChildren(...options.map((option) => el("li", "", option)));

  $("reminder-toggle").hidden = !hasAttention(chat) || !thread.attention_key;
  const dismissed = reminderDismissed(chat);
  $("reminder-toggle").setAttribute("aria-label", dismissed ? "Restore reminder" : "Dismiss reminder");
  $("reminder-toggle").title = dismissed ? "Restore reminder" : "Dismiss reminder (this browser only; does not answer the request)";
  $("reminder-icon").setAttribute("href", dismissed ? "#i-bell" : "#i-bell-off");
  $("reminder-note").textContent = dismissed ? `Only in this browser. The request is still open in ${appName(thread)}.` : "";

  const outcome = thread.status === "working" ? "" : turn?.outcome || "";
  const recap = thread.turns.findLast((each) => each.recap)?.recap || "";
  $("outcome-card").hidden = !outcome && !recap;
  $("outcome-wrap").hidden = !outcome && !recap && !turn?.files.length;
  $("recap-wrap").hidden = !recap;
  $("outcome-label").hidden = !recap || !outcome;
  $("outcome-latest").hidden = !outcome;
  if ($("recap").textContent !== recap) $("recap").textContent = recap;
  if ($("outcome").textContent !== outcome) $("outcome").textContent = outcome;
}

$("reminder-toggle").addEventListener("click", () => {
  if (!threadData || !threadData.attention_key) return;
  try {
    const key = `reminder:v1:${threadData.id}`;
    if (reminderDismissed(threadData)) localStorage.removeItem(key);
    else localStorage.setItem(key, threadData.attention_key);
    renderThread(threadData);
    if (inboxData) renderInbox(inboxData);
    if (attentionData) { syncNavigation(attentionData); setFavicon(attentionData.some(needsAttention)); }
  } catch {
    $("reminder-note").textContent = "Could not save this preference. The reminder remains active.";
  }
});

function syncThemeToggle() {
  const dark = document.documentElement.dataset.theme === "dark";
  const label = `Switch to ${dark ? "light" : "dark"} theme`;
  $("theme-toggle").setAttribute("aria-label", label);
  $("theme-toggle").title = label;
  $("theme-toggle").querySelector("use").setAttribute("href", dark ? "#i-sun" : "#i-moon");
}

$("theme-toggle").addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  window.YourTurnTheme.set(theme);
});
document.addEventListener("themechange", syncThemeToggle);
syncThemeToggle();

function syncAppearance() {
  const selected = window.YourTurnTheme.preference();
  for (const radio of document.querySelectorAll('[name="appearance"]')) radio.checked = radio.value === selected;
}

function syncSettingsNotifications() {
  const blocked = notifySupported && Notification.permission === "denied";
  $("notification-status").textContent = !notifySupported ? "This browser does not support desktop notifications here."
    : blocked ? "Blocked in this browser’s site settings. Enable permission there to use notifications."
    : notifyOn() ? "On while a Your Turn tab is open." : "Off in this browser.";
  $("settings-notify").disabled = !notifySupported || blocked;
  $("settings-notify").textContent = notifyOn() ? "Turn off notifications" : "Enable notifications";
}

document.addEventListener("themechange", syncAppearance);
syncAppearance();
syncSettingsNotifications();
$("appearance-form").addEventListener("change", (event) => {
  if (event.target.name !== "appearance") return;
  const saved = window.YourTurnTheme.set(event.target.value);
  $("appearance-note").textContent = saved ? "Appearance is saved in this browser. System follows your device."
    : "Applied for this page, but browser storage is unavailable.";
});
$("settings-notify").addEventListener("click", async () => {
  if (!notifySupported || Notification.permission === "denied") return;
  if (notifyOn()) {
    try { localStorage.removeItem("notify"); } catch { /* Stays on until storage works. */ }
  } else if (await Notification.requestPermission() === "granted") {
    try { localStorage.setItem("notify", "on"); } catch { /* Without storage the preference cannot be kept. */ }
  }
  syncSettingsNotifications();
});

const drawer = matchMedia("(max-width: 959px)");
const railTooltip = $("rail-tooltip");
for (const control of document.querySelectorAll(".rail-action")) {
  const show = () => {
    if (drawer.matches) return;
    railTooltip.textContent = control.dataset.tooltip;
    const box = control.getBoundingClientRect();
    railTooltip.style.top = `${box.top + box.height / 2}px`;
    railTooltip.hidden = false;
  };
  control.addEventListener("mouseenter", show);
  control.addEventListener("focus", show);
  control.addEventListener("mouseleave", () => { if (document.activeElement !== control) railTooltip.hidden = true; });
  control.addEventListener("blur", () => { railTooltip.hidden = true; });
}
document.addEventListener("keydown", (event) => { if (event.key === "Escape") railTooltip.hidden = true; });
function closeNavigation(restoreFocus = true) {
  document.body.dataset.navigation = "closed";
  $("menu-backdrop").hidden = true;
  $("menu-toggle").setAttribute("aria-expanded", "false");
  $("sidebar").removeAttribute("role");
  $("sidebar").removeAttribute("aria-modal");
  $("main-content").inert = false;
  document.querySelector(".bar").inert = false;
  if (restoreFocus && drawer.matches) $("menu-toggle").focus();
}
$("menu-toggle").addEventListener("click", () => {
  document.body.dataset.navigation = "open";
  $("menu-backdrop").hidden = false;
  $("menu-toggle").setAttribute("aria-expanded", "true");
  $("sidebar").setAttribute("role", "dialog");
  $("sidebar").setAttribute("aria-modal", "true");
  $("main-content").inert = true;
  document.querySelector(".bar").inert = true;
  $("menu-close").focus();
});
$("menu-close").addEventListener("click", () => closeNavigation());
$("menu-backdrop").addEventListener("click", () => closeNavigation());
drawer.addEventListener("change", () => closeNavigation(false));
document.addEventListener("keydown", (event) => {
  if (document.body.dataset.navigation !== "open") return;
  if (event.key === "Escape") { event.preventDefault(); closeNavigation(); }
  if (event.key !== "Tab") return;
  const nodes = [...$("sidebar").querySelectorAll("a, button")].filter(node => node.getClientRects().length && !node.disabled);
  const first = nodes[0], last = nodes[nodes.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});
for (const button of document.querySelectorAll("[data-dialog]")) {
  const dialog = $(button.dataset.dialog);
  button.addEventListener("click", () => {
    closeNavigation(false);
    syncAppearance(); syncSettingsNotifications();
    dialog.showModal();
  });
  dialog.addEventListener("close", () => (drawer.matches ? $("menu-toggle") : button).focus());
}
for (const button of document.querySelectorAll("[data-close-dialog]")) button.addEventListener("click", () => button.closest("dialog").close());

// Prime both small local plates; CSS always selects art using the same pre-paint theme as the UI.
if (!threadId) for (const theme of ["light", "dark"]) {
  const art = new Image();
  art.src = `/assets/header-${theme}.webp`;
  art.decode().catch(() => {});
}

window.addEventListener("storage", (event) => {
  if (event.key === null || event.key.startsWith("reminder:v1:") || event.key.startsWith("seen:")) {
    if (threadData) renderThread(threadData);
    if (inboxData) renderInbox(inboxData);
    if (attentionData) { syncNavigation(attentionData); setFavicon(attentionData.some(needsAttention)); }
  }
});

function commandCode(command) {
  const code = el("code", "command");
  let commandStart = true;
  // Presentation hints only, not a shell parser; preserve every character as inert text.
  for (const token of command.match(/"(?:\\.|[^"\\])*"|'[^']*'|&&|\|\||[|;\n]|[^\s&|;]+|[&]|[^\S\n]+/g) || []) {
    let kind = "";
    if (/^(?:&&|\|\||[|;\n])$/.test(token)) {
      kind = "operator";
      commandStart = true;
    } else if (token.trim()) {
      if (/^["']/.test(token)) kind = "string";
      else if (token.startsWith("-")) kind = "flag";
      else if (token.includes("/") || /^[\w.-]+\.[a-zA-Z0-9]+$/.test(token)) kind = "path";
      else if (commandStart) kind = "executable";
      commandStart = false;
    }
    code.append(kind ? el("span", `command-${kind}`, token) : document.createTextNode(token));
  }
  return code;
}

function relativePath(path, cwd) {
  return cwd && path.startsWith(`${cwd}/`) ? path.slice(cwd.length + 1) : path;
}

function renderChanges(thread, turn) {
  const files = turn ? turn.files : [];
  const checks = turn ? turn.checks : [];
  // Codex records exit codes; Claude Code only success or failure; Cursor records no results at all.
  const exitCodes = thread.capabilities?.exit_codes !== false;
  let warning = "";
  if (turn && turn.edited_after_check) warning = "Files changed after the last check ran.";
  else if (files.length && !checks.length) warning = "No tests or linters ran after these edits.";
  else if (checks.some((check) => check.exit_code === null)) warning = exitCodes ? "Some checks have no recorded exit result." : `${appName(thread)} doesn't record command results, so these checks show no outcome.`;
  $("checks-wrap").hidden = !warning && checks.length === 0;
  $("check-warning").hidden = !warning;
  $("check-warning-text").textContent = warning;
  $("checks").replaceChildren(...checks.map((check) => {
    const state = check.exit_code === null ? "unknown" : check.exit_code === 0 ? "passed" : "failed";
    const item = el("li", "list-row check");
    item.dataset.state = state;
    // Claude Code's 0/1 comes from is_error, not a real exit code, so it is not shown as one.
    const failure = exitCodes ? `Failed (exit ${check.exit_code})` : "Failed";
    const result = state === "unknown" ? (exitCodes ? "Exit not reported" : "Not recorded") : state === "passed" ? "Passed" : failure;
    item.append(icon(state === "unknown" ? "i-question" : state === "passed" ? "i-answer" : "i-alert"), commandCode(check.command), el("span", "check-result", result));
    return item;
  }));
  $("files-wrap").hidden = files.length === 0;
  rowLabel("files-summary", `${files.length} ${files.length === 1 ? "file" : "files"} changed`);
  $("files").replaceChildren(...files.map((path) => fileItem(path, thread.cwd)));
}

function fileItem(path, cwd) {
  const relative = relativePath(path, cwd);
  const item = el("li");
  item.title = path;
  item.append(el("code", "", relative.split("/").pop()), el("span", "file-dir", relative.split("/").slice(0, -1).join("/")));
  return item;
}

// The session's final set of changed files, most recently changed first; shown only when earlier
// turns changed files too, since What happened already lists the latest turn's files.
function renderSessionFiles(thread, turn) {
  const lastTurn = new Map();
  for (const each of thread.turns) for (const path of each.files) lastTurn.set(path, each.index);
  const earlier = thread.turns.some((each) => each !== turn && each.files.length > 0);
  $("session-files-wrap").hidden = !earlier;
  rowLabel("session-files-summary", "Files changed", `${lastTurn.size} ${lastTurn.size === 1 ? "file" : "files"}`);
  const paths = [...lastTurn].sort(([, a], [, b]) => b - a).map(([path]) => path);
  $("session-files").replaceChildren(...paths.map((path) => fileItem(path, thread.cwd)));
}

function renderDecisions(thread) {
  const decisions = thread.decisions.map((decision, index) => ({ decision, key: JSON.stringify([decision.at, decision.turn, decision.source, decision.question, index]) })).filter(({ decision }) => decision.chosen !== null).reverse();
  const existing = new Map([...$("decisions-wrap").querySelectorAll(".decision")].map((item) => [item.dataset.key, item]));
  const focused = document.activeElement.closest(".decision");
  const focusedKey = focused?.dataset.key;
  $("decisions-wrap").hidden = decisions.length === 0;
  const items = decisions.map(({ decision, key }) => {
    const item = existing.get(key) || el("li", "list-row decision");
    const record = JSON.stringify(decision);
    if (item.dataset.record === record) return item;
    const expanded = item.querySelector("details")?.open || false;
    item.dataset.key = key;
    item.dataset.record = record;
    const at = new Date(decision.at);
    const when = [decision.turn ? `Turn ${decision.turn}` : "", Number.isNaN(at.getTime()) ? "" : at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })].filter(Boolean).join(" · ");
    const answer = (decision.chosen || "").replace(/^#+\s*/, "");
    // Without answer text the question is the only information, so it leads instead of a placeholder.
    const lead = el("p", "decision-answer-text", answer || decision.question);
    const context = el("p", "decision-question", answer ? decision.question : `Answered in ${appName(thread)}; the answer was not recorded.`);
    if (answer) context.title = decision.question;
    const meta = el("p", "decision-meta");
    meta.append(el("span", "decision-role", decision.source === "agent" ? "Agent" : "You"), ...(when ? [` · ${when}`] : []));
    item.replaceChildren(lead, context, ...(decision.reason ? [el("p", "reason", decision.reason)] : []), meta);
    const alternatives = answer ? decision.options.filter((option) => option !== decision.chosen) : decision.options;
    if (alternatives.length) {
      const disclosure = el("details", "decision-alternatives");
      disclosure.open = expanded;
      const summary = el("summary");
      const chevron = icon("i-chevron");
      chevron.classList.add("disclosure-chevron");
      summary.append(el("span", "", `${answer ? "Other options" : "Options"} (${alternatives.length})`), chevron);
      const options = el("ul", "decision-other-options");
      options.replaceChildren(...alternatives.map((option) => el("li", "", option)));
      disclosure.append(summary, options);
      item.append(disclosure);
    }
    return item;
  });
  const older = items.slice(DECISION_PREVIEW_LIMIT);
  $("decision-history").hidden = older.length === 0;
  rowLabel("decision-history-summary", "Earlier decisions", String(older.length));
  for (const [list, wanted] of [[$("decisions"), items.slice(0, DECISION_PREVIEW_LIMIT)], [$("earlier-decisions"), older]]) {
    const retained = new Set(wanted);
    for (const [index, item] of wanted.entries()) {
      if (list.children[index] !== item) list.insertBefore(item, list.children[index] || null);
    }
    for (const child of [...list.children]) if (!retained.has(child)) child.remove();
  }
  if (focusedKey && document.activeElement === document.body) {
    const item = items.find((item) => item.dataset.key === focusedKey);
    if (item?.closest(".decision-history")) $("decision-history").open = true;
    const target = item?.querySelector("summary") || item?.querySelector("h3") || $(decisions.length ? "decisions-title" : "status-title");
    if (!target.matches("summary")) target.tabIndex = -1;
    target.focus({ preventScroll: true });
  }
}

function renderEarlier(turns) {
  const earlier = turns.slice(0, -1).reverse();
  $("earlier-wrap").hidden = earlier.length === 0;
  rowLabel("earlier-summary", "Earlier turns", String(earlier.length));
  $("earlier").replaceChildren(...earlier.map((turn) => {
    const item = el("li", "turn-row");
    item.append(el("span", "turn-index", `Turn ${turn.index}`));
    const body = el("span", "turn-body");
    if (turn.prompt) body.append(el("span", "turn-prompt", turn.prompt));
    body.append(el("span", "", turn.outcome || STATUS[turn.status]?.label || turn.status));
    item.append(body);
    return item;
  }));
}

function renderToolUsage(thread) {
  const tools = new Map();
  for (const step of thread.steps) {
    if (step.kind === "tool") tools.set(step.title, (tools.get(step.title) || 0) + 1);
  }
  const calls = [...tools.values()].reduce((total, count) => total + count, 0);
  $("tools-wrap").hidden = tools.size === 0;
  rowLabel("tools-summary", "MCP tools", `${calls} ${calls === 1 ? "call" : "calls"}`);
  const toolRows = [...tools].map(([name, count]) => {
    const [server, tool] = name.split(" · ");
    const item = el("li", "usage-item");
    const label = el("span", "usage-label");
    if (tool) label.append(el("span", "usage-name", tool), el("span", "usage-server", server));
    else label.append(el("span", "usage-name", name));
    item.append(label, el("span", "usage-total", `${count} ${count === 1 ? "call" : "calls"}`));
    return item;
  });
  $("mcp-tools").replaceChildren(...toolRows);
}

function renderTimeline(thread) {
  const steps = thread.steps
    .filter((step) => filter === "all" || KEY_KINDS.has(step.kind) || step.status !== "done")
    .reverse()
    .slice(0, MAX_STEPS);
  rowLabel("activity-summary", "Activity", `${thread.steps.length} ${thread.steps.length === 1 ? "step" : "steps"}`);
  $("timeline-empty").hidden = steps.length > 0;
  $("timeline").replaceChildren(...steps.map((step) => {
    const item = el("li", "step");
    item.dataset.kind = step.kind;
    item.dataset.status = step.status;
    const node = el("span", "step-node");
    node.append(icon(ICONS[step.kind] || "i-turn"));
    const card = el("div", "step-card");
    const head = el("div", "step-head");
    head.append(el("span", "step-title", step.title || step.kind));
    if (step.status === "failed") head.append(el("span", "tag tag--interrupted", "Failed"));
    card.append(head);
    const meta = [clock(step.at), step.detail].filter(Boolean).join(" · ");
    if (meta) card.append(el("span", "step-meta", meta));
    item.append(node, card);
    return item;
  }));
}

// The chat header's meta row: fixed slots in a fixed order (agent, project, branch, last event),
// each shown only when known, so every chat page reads the same way.
function metaItems(thread) {
  const items = [];
  if (APP_NAME[thread.harness]) {
    const pill = el("span", "harness-pill", appName(thread));
    pill.title = `Chat from ${appName(thread)}`;
    items.push(pill);
  }
  const item = (text, title) => {
    const node = el("span", "meta-item", text);
    if (title) node.title = title;
    return node;
  };
  items.push(item(projectName(thread), thread.cwd));
  if (thread.git_branch) items.push(item(thread.git_branch, "Recorded Git branch"));
  items.push(item(ago(thread.updated_at), "Last recorded event"));
  return items;
}

function renderThread(thread) {
  const title = threadId ? $("title") : $("panel-title");
  const openingPanel = !threadId && title.textContent === "Loading…";
  const subtitle = threadId ? $("subtitle") : $("panel-subtitle");
  if (!thread) {
    threadData = null;
    title.textContent = "Chat not found";
    if (threadId) document.title = "Chat not found · Your Turn";
    subtitle.hidden = true;
    $("status-card").dataset.status = "idle";
    $("status-icon").setAttribute("href", "#i-alert");
    $("status-title").textContent = "No rollout file for this chat";
    $("status-body").hidden = false;
    $("status-body").dataset.kind = "none";
    $("next-kind").hidden = true;
    setStatusText("It may have been archived. Go back to the inbox.");
    for (const id of ["open-codex", "next-options", "reminder-toggle", "quiet-note", "outcome-wrap", "checks-wrap", "decisions-wrap", "more"]) $(id).hidden = true;
    if (openingPanel) title.focus({ preventScroll: true });
    return;
  }
  threadData = thread;
  const turn = thread.turns[thread.turns.length - 1];
  title.textContent = chatName(thread);
  if (threadId) document.title = `${chatName(thread)} · Your Turn`;
  subtitle.hidden = false;
  subtitle.replaceChildren(...metaItems(thread));
  $("more").hidden = false;
  renderStatus(thread, turn);
  renderChanges(thread, turn);
  renderDecisions(thread);
  renderEarlier(thread.turns);
  renderSessionFiles(thread, turn);
  renderTimeline(thread);
  renderToolUsage(thread);
  renderSessionInfo(thread, turn);
  if (turn?.ended_at && seen.get(thread.id) !== turn.ended_at) {
    seen.set(thread.id, turn.ended_at);
    if (inboxData) renderInbox(inboxData);
    else if (attentionData) syncNavigation(attentionData);
  }
  if (openingPanel) title.focus({ preventScroll: true });
}

// Wide-screen detail pane (independent of the inbox list presentation).

function inboxUrl(status, id) {
  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (id) query.set("open", id);
  const text = query.toString();
  return text ? `/?${text}` : "/";
}

function cardFor(id) {
  return [...$("sections").querySelectorAll(".row")].find((row) => new URLSearchParams(row.search).get("thread") === id);
}

function resetThread() {
  $("panel-title").textContent = "Loading…";
  $("panel-subtitle").textContent = "";
  $("status-card").dataset.status = "idle";
  $("status-icon").setAttribute("href", "#i-turn");
  $("status-title").textContent = "Loading…";
  for (const id of ["status-body", "open-codex", "outcome-wrap", "checks-wrap", "decisions-wrap", "more"]) $(id).hidden = true;
  for (const details of $("thread-view").querySelectorAll("details")) details.open = false;
  $("thread-view").scrollTop = 0;
}

function showPanel(id) {
  if (id === openId) return Promise.resolve();
  threadSource?.close();
  threadSource = null;
  threadData = null;
  openId = id;
  return transition(() => {
    document.body.dataset.panel = id ? "open" : "closed";
    $("thread-view").hidden = !id;
    if (inboxData) renderInbox(inboxData);
    if (!id) return;
    cardFor(id)?.scrollIntoView({ block: "nearest" });
    resetThread();
    threadSource = connect(`/api/stream?thread=${encodeURIComponent(id)}`, "thread", renderThread);
  }, { rows: false });
}

function closePanel() {
  const id = openId;
  history.pushState(null, "", inboxUrl(inboxStatus, ""));
  showPanel("").then(() => (cardFor(id) || document.querySelector('.segments [aria-current="page"]'))?.focus());
}

if (!threadId) {
  $("sections").addEventListener("click", (event) => {
    const link = event.target.closest(".row");
    if (!link || !wideDetail.matches || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const id = new URLSearchParams(link.search).get("thread");
    if (id !== openId) history.pushState(null, "", inboxUrl(inboxStatus, id));
    showPanel(id);
  });
  $("panel-close").addEventListener("click", closePanel);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && openId && !document.querySelector("dialog[open]") && document.body.dataset.navigation !== "open") closePanel();
  });
  window.addEventListener("popstate", () => showPanel(wideDetail.matches ? new URLSearchParams(location.search).get("open") || "" : ""));
  wideDetail.addEventListener("change", () => {
    if (!wideDetail.matches && openId) location.assign(`/?thread=${encodeURIComponent(openId)}${inboxReturn}`);
    else if (inboxData) renderInbox(inboxData);
  });
}

for (const chip of document.querySelectorAll(".chip")) {
  chip.addEventListener("click", () => {
    filter = chip.dataset.filter;
    for (const other of document.querySelectorAll(".chip")) other.setAttribute("aria-pressed", String(other === chip));
    if (threadData) renderTimeline(threadData);
  });
}

// Nothing is written while a chat is quiet, so durations tick here instead of waiting for the server.
let attentionData = null;
setInterval(() => {
  const chats = inboxData || attentionData;
  if (chats) notifyChanges(chats);
  if (document.hidden) return;
  for (const node of document.querySelectorAll("[data-ago]")) node.textContent = ago(node.dataset.ago);
  for (const node of document.querySelectorAll("[data-quiet-at]")) node.textContent = `Quiet ${ago(node.dataset.quietAt).replace(/ ago$/, "")}`;
  if (threadData) renderStatus(threadData, threadData.turns[threadData.turns.length - 1]);
}, 30_000);


if (threadId) {
  $("thread-view").hidden = false;
  $("back").hidden = false;
  $("back").href = inboxStatus ? `/?status=${inboxStatus}` : "/";
  $("back-label").textContent = inboxStatus ? INBOX_FILTERS[inboxStatus].label : "Inbox";
  $("inbox-title").hidden = true;
  $("thread-heading").hidden = false;
  connect(`/api/stream?thread=${encodeURIComponent(threadId)}`, "thread", renderThread);
  // The favicon and notifications cover every chat, not just this one; the live label follows this chat's stream.
  new EventSource("/api/stream").addEventListener("inbox", (message) => {
    attentionData = JSON.parse(message.data);
    syncNavigation(attentionData);
    notifyChanges(attentionData);
    setFavicon(attentionData.some(needsAttention));
  });
} else {
  $("inbox-view").hidden = false;
  $("panel-head").hidden = false;
  if (inboxStatus) $("inbox-title").textContent = INBOX_FILTERS[inboxStatus].label;
  connect("/api/stream", "inbox", liveInbox);
  const open = params.get("open");
  if (open && wideDetail.matches) showPanel(open);
  else if (open) location.replace(`/?thread=${encodeURIComponent(open)}${inboxReturn}`);
}
