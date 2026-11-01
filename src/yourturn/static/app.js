"use strict";

const $ = (id) => document.getElementById(id);
function readPreference(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
const MAX_STEPS = 80;
const SECTION_LIMIT = 10;
const DECISION_ANSWER_PREVIEW_LIMIT = 120;
const NEW_RESULT_BADGE_HIGHLIGHT_MS = 1400;
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
  unknown: { label: "Status unknown", icon: "i-question" },
  dismissed: { label: "Reminder dismissed", icon: "i-question" },
};
const SECTION_ICONS = { waiting: "i-message-question", working: "i-working", new: "i-answer", earlier: "i-turn" };
const APP_NAME = { codex: "Codex", claude: "Claude Code", cursor: "Cursor" };

// Where the user acts on a chat; older payloads without `harness` are Codex chats.
function appName(chat) {
  return APP_NAME[chat?.harness] || APP_NAME.codex;
}

function quietHint(chat) {
  // A chat that never asks before running things cannot be waiting for approval.
  if (chat.approval_policy === "never") {
    const call = chat.pending_tool ? ` Its last call has no result yet (${chat.pending_tool}).` : "";
    return `No activity recorded.${call} It may be running a long command, or it may be stuck.`;
  }
  if (chat.pending_tool) return `No activity recorded. Its last call has no result yet (${chat.pending_tool}): it may be waiting for your approval in ${appName(chat)}, or still running.`;
  return `No activity recorded. It may be waiting for your approval in ${appName(chat)}, or running a long command.`;
}

// A chat the app keeps no messages of: neither finished nor running as far as anything recorded says.
function unavailableNote(chat) {
  return `${appName(chat)} keeps no local record of this chat’s messages, so whether it is working or finished is unknown.`;
}

// A working chat whose app may not write while a turn runs, so silence cannot be read as quiet.
function unverifiedNote(chat) {
  return `This is the last recorded state. ${appName(chat)} may not record activity while a turn runs, so it can’t be checked live.`;
}

function liveUnverified(chat) {
  return chat.status === "working" && chat.capabilities?.live_activity === false;
}

// The app's own one-line summary, labelled so it is never mistaken for the agent's answer.
function summaryText(chat) {
  return chat.summary ? `${appName(chat)} summary: ${chat.summary}` : "";
}

// Why a chat's state is unknown: no local record of its messages, or a last turn that ended unrecorded.
function unknownNote(chat) {
  return chat.content_available === false ? unavailableNote(chat)
    : "The last turn ended without a recorded result or reason, so whether it finished is unknown.";
}

// A next step not named by the source or the handoff; the others need no mark.
const BASIS = {
  inferred: { label: "Inferred", note: "Read from the answer’s wording: the answer has no handoff." },
  no_handoff: { label: "No handoff", note: "The answer did not say what comes next." },
  no_next_step: { label: "No next step", note: "The handoff has an outcome but no next step." },
};

function basisOf(chat) {
  return BASIS[chat.next_basis] || null;
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

// Pure triage helpers, shared by the inbox interactions and their unit tests.
const AWAY_DIGEST_MS = 10 * 60 * 1000;
function filterInbox(chats, query) {
  const terms = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return chats.filter((chat) => {
    const text = JSON.stringify([chat.title, chat.project, chat.outcome, chat.next_step, chat.next_text,
      chat.recap, chat.decisions, chat.changed_files]).toLocaleLowerCase();
    return terms.every((term) => text.includes(term));
  });
}

function awayDelta(previousKeys, currentKeys, elapsed) {
  return elapsed >= AWAY_DIGEST_MS ? [...currentKeys].filter((key) => !previousKeys.has(key)) : [];
}

function queueTarget(keys, current, direction) {
  if (!keys.length) return "";
  const index = keys.indexOf(current);
  return keys[index < 0 ? 0 : Math.max(0, Math.min(keys.length - 1, index + direction))];
}

function shortcutBlocked(target, modalOpen) {
  return modalOpen || Boolean(target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'));
}
// End pure triage helpers.
const params = new URLSearchParams(location.search);
const threadId = params.get("thread") || "";
const returnOpenId = params.get("returnOpen") || "";
const statusParam = params.get("status");
const inboxStatus = Object.hasOwn(INBOX_FILTERS, statusParam) ? statusParam : "";
const inboxReturn = inboxStatus ? `&status=${inboxStatus}` : "";
$("nav-inbox").dataset.category = inboxStatus || "all";
document.body.dataset.view = threadId ? "thread" : "inbox";
if (threadId) $("nav-inbox").removeAttribute("aria-current");
const wideDetail = matchMedia("(min-width: 1280px)");
const calm = matchMedia("(prefers-reduced-motion: reduce)");
const WORKING_SPIN_PERIOD_MS = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion-status-working"));
let inboxData = null;
let previousNewResultsCount = null;
let incomingBadgeTimer = null;
let inboxLayout = "";
let threadData = null;
let filter = "key";
let openId = "";
let threadSource = null;
let searchQuery = "";
let awaySnapshot = null;
let searchReturnFocus = null;

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
  use.style.animationDelay = `-${performance.now() % WORKING_SPIN_PERIOD_MS}ms`;
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

// Rows use the short form ("2d"); the chat header keeps "2d ago".
function ago(iso, suffix = " ago") {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m${suffix}`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h${suffix}`;
  return `${Math.round(seconds / 86400)}d${suffix}`;
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

// Server sharing with a versioned browser backup, including explicit reminder restores.
const stateSync = new window.YourTurnState();
const shared = stateSync.data;
function saveShared(change) {
  stateSync.save(change);
}
window.addEventListener("online", () => stateSync.flush());
window.addEventListener("storage", (event) => {
  if (event.key !== window.YourTurnState.storageKey && event.key !== null) return;
  stateSync.readBackup();
  stateSync.persist();
  stateSync.flush();
  renderShared();
});
const seen = {
  get: (key) => shared.seen[key] || "",
  set: (key, endedAt) => { if (endedAt) saveShared({ seen: { [key]: endedAt } }); },
};

// One-time move of the per-browser marks older versions kept in localStorage.
function migrateLocalMarks(chats) {
  let keys;
  try { keys = Object.keys(localStorage).filter((key) => key.startsWith("seen:") || key.startsWith("reminder:v1:")); } catch { return; }
  if (!keys.length) return;
  const change = { seen: {}, dismissed: {} };
  for (const chat of chats) {
    const seenAt = readPreference(`seen:${chat.id}`);
    const dismissed = readPreference(`reminder:v1:${chat.id}`);
    if (seenAt) change.seen[chatKey(chat)] = seenAt;
    if (dismissed) change.dismissed[chatKey(chat)] = dismissed;
  }
  for (const key of keys) try { localStorage.removeItem(key); } catch { /* Retried on the next inbox. */ }
  saveShared(change);
}

function setConnection(state, text) {
  $("connection").dataset.state = state;
  $("connection-text").textContent = text;
}

function connect(url, event, render) {
  const source = new EventSource(url);
  source.onopen = () => { setConnection("live", "Live"); stateSync.flush(); };
  source.onerror = () => setConnection("offline", "Reconnecting");
  source.addEventListener(event, (message) => render(JSON.parse(message.data)));
  source.addEventListener("state", (message) => {
    stateSync.receive(JSON.parse(message.data));
    renderShared();
  });
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
  return shared.dismissed[chatKey(chat)] === chat.attention_key;
}

function attentionState(chat) {
  return hasAttention(chat) ? reminderDismissed(chat) ? "dismissed" : "waiting" : chat.status;
}

// An end recorded without saying how, and with nothing to show, is no finished result.
function hasResult(chat) {
  return chat.status !== "working" && chat.status !== "interrupted" && !(chat.status === "unknown" && !chat.outcome);
}

function isNewResult(chat) {
  const ended = new Date(chat.turn_ended_at).getTime();
  return !hasAttention(chat) && hasResult(chat) && Date.now() - ended < NEW_WINDOW_MS && chat.turn_ended_at > seen.get(chatKey(chat));
}

function sectionOf(chat) {
  return needsAttention(chat) ? "waiting" : chat.status === "working" ? "working" : isNewResult(chat) ? "new" : "earlier";
}

function chatSummary(chat) {
  if (hasAttention(chat)) return chat.question || chat.next_text || chat.outcome;
  if (chat.status === "working" && chat.capabilities?.live_activity && chat.activity_summary) return chat.activity_summary;
  if (chat.content_available === false) return summaryText(chat);
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
  const time = el("span", "row-time", ago(chat.updated_at, ""));
  time.dataset.ago = chat.updated_at;
  time.dataset.short = "";
  time.title = new Date(chat.updated_at).toLocaleString();
  head.append(el("span", "row-title", chatName(chat)));
  body.append(head);
  const summary = chatSummary(chat);
  const description = el("span", "row-description");
  const summaryNode = el("span", "row-text", summary || "");
  const meta = el("span", "row-tags");
  const action = chat.question ? "Answer" : NEXT_LABEL[chat.next_kind];
  const tag = state === "waiting" ? action || status.label : ["done", "idle", "dismissed"].includes(state) ? "" : status.label;
  if (state === "working" && chat.quiet) {
    const quiet = el("span", "tag tag--waiting", `Quiet ${quietFor(chat)}`);
    quiet.dataset.quietAt = chat.updated_at;
    quiet.title = quietHint(chat);
    meta.append(quiet);
  } else if (tag) {
    const node = el("span", `tag tag--${state}`, tag);
    if (state === "unknown") node.title = unknownNote(chat);
    else if (state === "working" && liveUnverified(chat)) node.title = unverifiedNote(chat);
    meta.append(node);
  }
  const basis = basisOf(chat);
  if (basis) {
    const node = el("span", "tag tag--idle", basis.label);
    node.title = basis.note;
    meta.append(node);
  }
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
  const projectIcon = icon("i-workspace");
  projectIcon.classList.add("project-icon");
  project.append(projectIcon, el("span", "project-name", projectName(chat)));
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
    if (fold === "closed") {
      if (key === "working") syncSpin(content[0].querySelector("use"));
      content.push(el("span", "section-count", String(chats.length)));
    }
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
  stateSync.retain(chats.map(chatKey));
  migrateLocalMarks(chats);
  notifyChanges(chats);
  if (inboxLayout && layoutOf(groupChats(chats)) !== inboxLayout) transition(() => renderInbox(chats));
  else renderInbox(chats);
}

function renderInbox(chats) {
  inboxData = chats;
  const focusedHref = document.activeElement.closest(".row, .show-all")?.getAttribute("href");
  const groups = groupChats(filterInbox(chats, searchQuery));
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
  $("inbox-empty").hidden = chats.length > 0 || Boolean(searchQuery);
  const noMatches = Boolean(searchQuery.trim()) && shown.length === 0;
  $("search-empty").hidden = !noMatches;
  $("search-empty").textContent = noMatches ? `No chats match '${searchQuery}'` : "";
  $("filter-empty").hidden = noMatches || !inboxStatus || shown.length > 0 || chats.length === 0;
  $("filter-empty").textContent = inboxStatus ? INBOX_FILTERS[inboxStatus].empty : "";
  syncNavigation(chats);
  if (focusedHref) [...$("sections").querySelectorAll("a")].find((link) => link.getAttribute("href") === focusedHref)?.focus({ preventScroll: true });
  const needs = chats.filter(needsAttention).length;
  document.title = needs ? `(${needs}) Your Turn` : "Your Turn";
  setFavicon(needs > 0);
}

function syncNavigation(chats) {
  const groups = groupChats(chats);
  const newResultsCount = groups.get("new").length;
  const newResultsArrived = previousNewResultsCount !== null && newResultsCount > previousNewResultsCount;
  previousNewResultsCount = newResultsCount;
  const selector = $("compact-status");
  $("nav-inbox").dataset.category = inboxStatus || "all";
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
    const badge = segment.querySelector(".segment-count");
    badge.textContent = count;
    if (kind === "new" && newResultsArrived) {
      badge.classList.remove("is-incoming");
      void badge.offsetWidth;
      badge.classList.add("is-incoming");
      clearTimeout(incomingBadgeTimer);
      incomingBadgeTimer = setTimeout(() => badge.classList.remove("is-incoming"), NEW_RESULT_BADGE_HIGHLIGHT_MS);
    }
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

let faviconAlert = false;
function setFavicon(alert = faviconAlert) {
  faviconAlert = alert;
  const dark = document.documentElement.dataset.theme === "dark";
  const svgHref = dark ? (alert ? "/assets/icon-dark-alert.svg" : "/assets/icon-dark.svg")
    : alert ? "/assets/icon-alert.svg" : "/assets/icon.svg";
  const icoHref = dark ? (alert ? "/assets/favicon-dark-alert.ico" : "/assets/favicon-dark.ico")
    : alert ? "/assets/favicon-alert.ico" : "/assets/favicon.ico";
  const appIconHref = dark ? "/assets/app-icon-dark-180.png" : "/assets/app-icon-light-180.png";
  if ($("favicon").getAttribute("href") !== svgHref) $("favicon").setAttribute("href", svgHref);
  if ($("favicon-ico").getAttribute("href") !== icoHref) $("favicon-ico").setAttribute("href", icoHref);
  if ($("app-icon").getAttribute("href") !== appIconHref) $("app-icon").setAttribute("href", appIconHref);
}
document.addEventListener("themechange", () => setFavicon());
setFavicon();

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
      const iconHref = document.documentElement.dataset.theme === "dark" ? "/assets/icon-dark-alert.svg" : "/assets/icon-alert.svg";
      const notice = new Notification(alert.title, { body: alert.body, tag: chat.id, icon: iconHref });
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

async function copyFilePath(path, status) {
  try {
    await navigator.clipboard.writeText(path);
    status.textContent = `Path copied: ${path}`;
  } catch {
    status.textContent = `Couldn’t copy path: ${path}. Clipboard access was denied.`;
  }
}

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

function numberedNextSteps(text) {
  const prefix = text.match(/^(Next steps for you:)\s*1\.\s+/i);
  if (!prefix) return null;
  const body = text.slice(prefix[0].length);
  const markers = [...body.matchAll(/(?:^|\s)(\d+)\.\s+/g)];
  if (!markers.length) return null;
  const steps = [body.slice(0, markers[0].index).trim()];
  for (let index = 0; index < markers.length; index++) {
    const marker = markers[index];
    if (Number(marker[1]) !== index + 2) return null;
    const start = marker.index + marker[0].length;
    const end = markers[index + 1]?.index ?? body.length;
    steps.push(body.slice(start, end).trim());
  }
  return steps.some((step) => !step) ? null : { label: prefix[1], steps };
}

function setStatusText(content, command = false) {
  const target = $("status-text");
  const text = typeof content === "string" ? content : "";
  const structured = command ? null : numberedNextSteps(text);
  // Leave the selected text untouched when an unrelated value changes.
  if ((target.dataset.sourceText ?? target.textContent) === text && Boolean(target.querySelector("code")) === command) return;
  target.dataset.sourceText = text;
  if (command) target.replaceChildren(commandCode(text));
  else if (structured) {
    const list = el("ol", "status-steps");
    list.append(...structured.steps.map((step) => el("li", "", step)));
    target.replaceChildren(el("p", "status-steps-label", structured.label), list);
  } else target.replaceChildren(el("p", "", text));
}

function renderStatus(thread, turn) {
  // A chat without turns (content unavailable) still carries a pending approval on the thread itself.
  const next = turn || thread;
  const chat = { ...thread, next_kind: next.next_kind, next_text: next.next_text };
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
  // Claude keeps its terminal resume command and can also start a new Code session in Desktop.
  const resume = thread.harness === "claude" ? thread.handoff?.resume_command || "" : "";
  const link = thread.harness === "cursor" ? thread.handoff?.open_uri || "" : `codex://threads/${encodeURIComponent(thread.id)}`;
  const desktopLink = thread.harness === "claude" ? thread.handoff?.open_uri || "" : "";
  const action = resume ? "Copy resume command" : `Open in ${appName(thread)}`;
  // Keep "Resume command copied" visible until its timeout restores the label.
  if (!$("open-codex").dataset.copied) $("open-codex").firstChild.textContent = action;
  $("open-codex").dataset.copy = resume;
  $("open-codex").href = resume ? "#" : link;
  $("open-codex").setAttribute("aria-label", resume ? `${action}: ${resume}` : thread.harness === "cursor" ? "Open the project in Cursor" : "Open in Codex (full chat)");
  $("open-codex").title = resume;
  $("open-codex").hidden = !resume && !link;
  $("open-action-icon").setAttribute("href", resume ? "#i-copy" : "#i-external");
  $("open-claude-desktop").href = desktopLink || "claude://code/new";
  $("open-claude-desktop").hidden = !desktopLink;
  $("status-body").hidden = false;

  const pending = [...thread.decisions].reverse().find((d) => d.source === "asked" && d.chosen === null);
  let kind = next.next_kind || "unknown";
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
  } else if (thread.content_available === false && kind !== "approve") {
    kind = "unknown";
    label = thread.summary ? `${appName(thread)} summary` : "";
    setStatusText(thread.summary || unavailableNote(thread));
  } else if (kind === "none") {
    setStatusText(failed ? "No further action was requested, but a check failed." : "No further action was requested.");
  } else if (kind === "unknown") {
    const basis = basisOf(thread);
    if (basis) label = basis.label;
    const note = basis?.note || "No next action was recorded.";
    setStatusText(failed ? `${note.replace(/\.$/, "")}, but a check failed.` : note);
  } else {
    if (basisOf(thread)?.label === BASIS.inferred.label) label = `${label} · ${BASIS.inferred.label}`;
    setStatusText(next.next_text);
  }
  // An approval request names no step, so show the latest recorded one, and only while its turn is
  // still open: a turn that already ended has nothing left to approve, whatever the app reports.
  const lastStep = turn?.next_kind === "approve" && !turn.ended_at
    ? [...thread.steps].reverse().find((step) => step.turn === turn.index && ["command", "tool", "edit"].includes(step.kind))
    : null;
  $("pending-step").hidden = !lastStep;
  if (lastStep) {
    const text = lastStep.kind === "edit" ? `${lastStep.title}: ${lastStep.detail}` : lastStep.title;
    if ($("pending-step-text").textContent !== text) $("pending-step-text").replaceChildren(lastStep.kind === "command" ? commandCode(text) : el("p", "", text));
  }
  $("status-body").dataset.kind = kind;
  $("status-body").dataset.check = failed && (kind === "none" || kind === "unknown") ? "failed" : "";
  const quietNote = quiet ? `No activity since ${clock(thread.updated_at)} (${ago(thread.updated_at)}). ${quietHint(thread).replace(/^No activity recorded\. /, "")}`
    : thread.status === "unknown" && (thread.content_available !== false || thread.summary) ? unknownNote(thread)
    : liveUnverified(thread) ? unverifiedNote(thread) : "";
  $("quiet-note").hidden = !quietNote;
  $("quiet-note").dataset.tone = quiet ? "" : "muted";
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
  $("reminder-toggle").title = dismissed ? "Restore reminder" : "Dismiss reminder (does not answer the request)";
  $("reminder-icon").setAttribute("href", dismissed ? "#i-bell" : "#i-bell-off");
  $("reminder-note").textContent = dismissed ? `Hidden in every Your Turn tab. The request is still open in ${appName(thread)}.` : "";

  const outcome = thread.status === "working" ? "" : turn?.outcome || "";
  const recap = thread.turns.findLast((each) => each.recap)?.recap || "";
  $("outcome-card").hidden = !outcome && !recap;
  $("outcome-wrap").hidden = !outcome && !recap && !turn?.files.length;
  $("recap-wrap").hidden = !recap;
  $("outcome-label").hidden = !recap || !outcome;
  $("outcome-latest").hidden = !outcome;
  $("outcome-source").hidden = !outcome || turn.formatted;
  if ($("recap").textContent !== recap) $("recap").textContent = recap;
  if ($("outcome").textContent !== outcome) $("outcome").textContent = outcome;
}

$("reminder-toggle").addEventListener("click", () => {
  if (!threadData || !threadData.attention_key) return;
  saveShared({ dismissed: { [chatKey(threadData)]: reminderDismissed(threadData) ? null : threadData.attention_key } });
  renderShared();
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
    : blocked ? "Blocked in this browser’s site settings. Allow them there."
    : notifyOn() ? "On while a Your Turn tab is open." : "Off in this browser.";
  $("settings-notify").hidden = !notifySupported || blocked;
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
// Settings and Help dock beside the rail without a backdrop; on phones the panel covers the page instead.
function showAside(name, restoreFocus = true) {
  const current = document.body.dataset.aside || "";
  for (const button of document.querySelectorAll("[data-aside]")) button.setAttribute("aria-expanded", String(button.dataset.aside === name));
  for (const panel of document.querySelectorAll(".aside-panel")) panel.hidden = panel.id !== name;
  if (name) document.body.dataset.aside = name;
  else delete document.body.dataset.aside;
  const covered = Boolean(name) && drawer.matches;
  $("main-content").inert = covered;
  document.querySelector(".bar").inert = covered;
  if (name && name !== current) { syncAppearance(); syncSettingsNotifications(); $(`${name}-title`).focus(); }
  else if (!name && current && restoreFocus) (drawer.matches ? $("menu-toggle") : document.querySelector(`[data-aside="${current}"]`)).focus();
}
for (const button of document.querySelectorAll("[data-aside]")) button.addEventListener("click", () => {
  closeNavigation(false);
  showAside(document.body.dataset.aside === button.dataset.aside ? "" : button.dataset.aside);
});
for (const button of document.querySelectorAll("[data-close-aside]")) button.addEventListener("click", () => showAside(""));
// Escape closes the panel only from inside it, so it never steals Escape from the chat pane beside it.
document.addEventListener("keydown", (event) => {
  const panel = document.body.dataset.aside && $(document.body.dataset.aside);
  if (event.key !== "Escape" || !panel || !(drawer.matches || panel.contains(document.activeElement))) return;
  event.preventDefault();
  showAside("");
});
drawer.addEventListener("change", () => showAside(document.body.dataset.aside || "", false));

// Prime both small local plates; CSS always selects art using the same pre-paint theme as the UI.
if (!threadId) for (const theme of ["light", "dark"]) {
  const art = new Image();
  art.src = `/assets/header-${theme}.webp`;
  art.decode().catch(() => {});
}

function renderShared() {
  if (threadData) renderThread(threadData);
  if (inboxData) renderInbox(inboxData);
  if (attentionData) { syncNavigation(attentionData); setFavicon(attentionData.some(needsAttention)); }
}

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
  $("files").replaceChildren(...renderFileTree(files, thread.cwd, $("files-copy-status")));
}

function renderFileTree(paths, cwd, status) {
  const root = new Map();
  for (const path of paths) {
    let branch = root;
    const parts = relativePath(path, cwd).split("/").filter(Boolean);
    for (const [index, part] of parts.entries()) {
      if (!branch.has(part)) branch.set(part, new Map());
      branch = branch.get(part);
      if (index === parts.length - 1) branch.filePath = path;
    }
  }

  function renderBranch(branch) {
    return [...branch].map(([name, children]) => {
      const item = el("li", "file-tree-item");
      if (children.filePath) {
        item.classList.add("file-tree-file");
        item.title = children.filePath;
        const path = relativePath(children.filePath, cwd);
        const copy = el("button", "icon-button");
        copy.type = "button";
        copy.title = `Copy path ${path}`;
        copy.setAttribute("aria-label", `Copy path ${path}`);
        copy.append(icon("i-copy"));
        copy.addEventListener("click", () => copyFilePath(path, status));
        item.append(el("code", "", name), copy);
      } else {
        const folder = el("details", "file-tree-folder");
        folder.open = true;
        const label = el("summary", "", name);
        const nested = el("ul", "file-tree");
        nested.append(...renderBranch(children));
        folder.append(label, nested);
        item.append(folder);
      }
      return item;
    });
  }

  return renderBranch(root);
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
  $("session-files").replaceChildren(...renderFileTree(paths, thread.cwd, $("session-files-copy-status")));
}

function decisionPreview(text) {
  const preview = text.slice(0, DECISION_ANSWER_PREVIEW_LIMIT);
  const boundary = preview.lastIndexOf(" ");
  return `${preview.slice(0, boundary > DECISION_ANSWER_PREVIEW_LIMIT * 0.75 ? boundary : preview.length).trimEnd()}…`;
}

function positionDecisionOptions(popover, trigger) {
  const style = getComputedStyle(document.documentElement);
  const inset = Number.parseFloat(style.getPropertyValue("--space-3"));
  const gap = Number.parseFloat(style.getPropertyValue("--space-2"));
  const edge = Number.isFinite(inset) ? inset : 0;
  const spacing = Number.isFinite(gap) ? gap : 0;
  const anchor = trigger.getBoundingClientRect();
  const panel = popover.getBoundingClientRect();
  const left = Math.max(edge, Math.min(anchor.left, window.innerWidth - edge - panel.width));
  const below = anchor.bottom + spacing;
  const top = below + panel.height <= window.innerHeight - edge
    ? below
    : Math.max(edge, anchor.top - spacing - panel.height);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}

function showFullDecision({ question, answer, reason, options, meta }) {
  $("decision-dialog-question-wrap").hidden = !question;
  $("decision-dialog-question").textContent = question;
  $("decision-dialog-answer-wrap").hidden = !answer;
  $("decision-dialog-answer").textContent = answer;
  $("decision-dialog-reason-wrap").hidden = !reason;
  $("decision-dialog-reason").textContent = reason;
  $("decision-dialog-options-wrap").hidden = options.length === 0;
  $("decision-dialog-options-title").textContent = `${answer ? "Other options" : "Options"} (${options.length})`;
  $("decision-dialog-options").replaceChildren(...options.map((option) => el("li", "", option)));
  $("decision-dialog-meta").textContent = meta;
  $("decision-dialog").showModal();
  $("decision-dialog-title").focus({ preventScroll: true });
}

$("decision-dialog-close").addEventListener("click", () => $("decision-dialog").close());
$("decision-dialog").addEventListener("keydown", (event) => {
  // Let the native dialog handle Escape without also closing the chat-detail panel.
  if (event.key === "Escape") event.stopPropagation();
});
$("decision-dialog").addEventListener("click", (event) => {
  if (event.target === $("decision-dialog")) $("decision-dialog").close();
});

function renderDecisions(thread) {
  const decisions = thread.decisions.map((decision, index) => ({ decision, key: JSON.stringify([decision.at, decision.turn, decision.source, decision.question, index]) })).filter(({ decision }) => decision.chosen !== null).reverse();
  const existing = new Map([...$("decisions-wrap").querySelectorAll(".decision")].map((item) => [item.dataset.key, item]));
  const focused = document.activeElement.closest(".decision");
  const focusedKey = focused?.dataset.key;
  $("decisions-wrap").hidden = decisions.length === 0;
  const items = decisions.map(({ decision, key }, index) => {
    const item = existing.get(key) || el("li", "list-row decision");
    const record = JSON.stringify(decision);
    if (item.dataset.record === record) return item;
    item.dataset.key = key;
    item.dataset.record = record;
    const at = new Date(decision.at);
    const when = [decision.turn ? `Turn ${decision.turn}` : "", Number.isNaN(at.getTime()) ? "" : at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })].filter(Boolean).join(" · ");
    const answer = (decision.chosen || "").replace(/^#+\s*/, "");
    // Without answer text the question is the only information, so it leads instead of a placeholder.
    const longAnswer = answer.length > DECISION_ANSWER_PREVIEW_LIMIT;
    const lead = el("p", "decision-answer-text", longAnswer ? decisionPreview(answer) : answer || decision.question);
    const context = el("p", "decision-question", answer ? decision.question : `Answered in ${appName(thread)}; the answer was not recorded.`);
    if (answer) context.title = decision.question;
    const meta = el("p", "decision-meta");
    meta.append(el("span", "decision-role", decision.source === "agent" ? "Agent" : "You"), ...(when ? [` · ${when}`] : []));
    const alternatives = answer ? decision.options.filter((option) => option !== decision.chosen) : decision.options;
    const answerAction = longAnswer ? el("button", "decision-full-button", "Show full decision") : null;
    answerAction?.addEventListener("click", () => showFullDecision({
      question: decision.question,
      answer,
      reason: decision.reason || "",
      options: alternatives,
      meta: meta.textContent,
    }));
    const footer = el("div", "decision-footer");
    const actions = el("div", "decision-actions");
    if (alternatives.length) {
      const popoverId = `decision-options-${index}`;
      const optionsButton = el("button", "decision-options-button", `View options (${alternatives.length})`);
      optionsButton.type = "button";
      optionsButton.setAttribute("aria-haspopup", "true");
      optionsButton.setAttribute("aria-expanded", "false");
      optionsButton.setAttribute("aria-controls", popoverId);
      const popover = el("div", "decision-options-popover");
      popover.id = popoverId;
      popover.setAttribute("popover", "auto");
      popover.setAttribute("role", "region");
      const heading = el("h3", "decision-options-heading", `Other options (${alternatives.length})`);
      heading.id = `${popoverId}-title`;
      popover.setAttribute("aria-labelledby", heading.id);
      popover.tabIndex = -1;
      const options = el("ul", "decision-other-options");
      options.replaceChildren(...alternatives.map((option) => el("li", "", option)));
      popover.append(heading, options);
      const reposition = () => positionDecisionOptions(popover, optionsButton);
      optionsButton.addEventListener("click", () => {
        if (popover.matches(":popover-open")) {
          popover.hidePopover();
          return;
        }
        popover.showPopover();
        reposition();
        popover.focus({ preventScroll: true });
      });
      actions.addEventListener("keydown", (event) => {
        if (event.key !== "Escape" || !popover.matches(":popover-open")) return;
        event.preventDefault();
        event.stopPropagation();
        popover.hidePopover();
        optionsButton.focus({ preventScroll: true });
      }, { capture: true });
      popover.addEventListener("toggle", (event) => {
        const isOpen = event.newState === "open";
        optionsButton.setAttribute("aria-expanded", String(isOpen));
        if (isOpen) {
          window.addEventListener("resize", reposition);
          document.addEventListener("scroll", reposition, true);
        } else {
          window.removeEventListener("resize", reposition);
          document.removeEventListener("scroll", reposition, true);
          if (popover.contains(document.activeElement)) optionsButton.focus({ preventScroll: true });
        }
      });
      actions.append(optionsButton, popover);
    }
    if (answerAction) actions.append(answerAction);
    footer.append(actions, meta);
    item.replaceChildren(lead, context, ...(decision.reason ? [el("p", "reason", decision.reason)] : []), footer);
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
  const item = (text, title, iconName = "", monospaced = false) => {
    const node = el("span", "meta-item");
    if (iconName) {
      const glyph = icon(iconName);
      glyph.classList.add("meta-icon");
      node.append(glyph);
    }
    node.append(el("span", monospaced ? "meta-value meta-value--mono" : "meta-value", text));
    if (title) node.title = title;
    return node;
  };
  items.push(item(projectName(thread), thread.cwd, "i-workspace", true));
  if (thread.git_branch) items.push(item(thread.git_branch, "Recorded Git branch", "i-branch", true));
  items.push(item(ago(thread.updated_at), "Last recorded event"));
  return items;
}

// Evidence strip: one line that answers "can I trust it?" before the details, each chip jumping
// to its section. Missing evidence is shown as missing rather than left out.
function renderEvidence(thread, turn) {
  const checks = turn?.checks || [];
  const files = turn?.files || [];
  const exitCodes = thread.capabilities?.exit_codes !== false;
  const count = (test) => checks.filter(test).length;
  const failed = count((check) => check.exit_code !== null && check.exit_code !== 0);
  const passed = count((check) => check.exit_code === 0);
  const unknown = count((check) => check.exit_code === null);
  const decisions = thread.decisions.filter((decision) => decision.chosen !== null).length;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const chips = [
    failed && [`${failed} failed`, "#checks-wrap", "danger"],
    passed && [`${passed} passed`, "#checks-wrap", "passed"],
    unknown && [`${unknown} ${exitCodes ? "without exit code" : "not recorded"}`, "#checks-wrap", "muted"],
    files.length && !checks.length && ["No checks after edits", "#checks-wrap", "warning"],
    checks.length && turn.edited_after_check && ["Edited after last check", "#checks-wrap", "warning"],
    files.length && [`${plural(files.length, "file")} changed`, "#outcome-wrap", ""],
    decisions && [plural(decisions, "decision"), "#decisions-wrap", ""],
  ].filter(Boolean);
  const header = threadId ? $("thread-heading") : document.querySelector(".panel-heading");
  header.append($("evidence"));
  $("evidence").hidden = chips.length === 0;
  $("evidence-list").replaceChildren(...chips.map(([text, target, tone]) => {
    const link = el("a", "evidence-chip", text);
    link.href = target;
    if (tone) link.dataset.tone = tone;
    const item = el("li");
    item.append(link);
    return item;
  }));
}

$("evidence-list").addEventListener("click", (event) => {
  const link = event.target.closest("a");
  if (!link) return;
  event.preventDefault();
  const target = document.querySelector(link.getAttribute("href"));
  // Files sit in a closed disclosure; open it so the jump lands on the list itself.
  if (link.getAttribute("href") === "#outcome-wrap") $("files-wrap").querySelector("details").open = true;
  if (target) {
    if (document.body.dataset.panel === "open") target.style.setProperty("scroll-margin-top", `calc(var(--space-2) + ${$("panel-head").offsetHeight}px)`);
    target.scrollIntoView({ block: "start", behavior: calm.matches ? "auto" : "smooth" });
  }
});

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
    for (const id of ["open-codex", "next-options", "reminder-toggle", "quiet-note", "pending-step", "evidence", "outcome-wrap", "checks-wrap", "decisions-wrap", "more"]) $(id).hidden = true;
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
  renderEvidence(thread, turn);
  renderChanges(thread, turn);
  renderDecisions(thread);
  renderEarlier(thread.turns);
  renderSessionFiles(thread, turn);
  renderTimeline(thread);
  renderToolUsage(thread);
  renderSessionInfo(thread, turn);
  if (turn?.ended_at && seen.get(chatKey(thread)) < turn.ended_at) {
    seen.set(chatKey(thread), turn.ended_at);
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

function focusedChatUrl(id) {
  const query = new URLSearchParams();
  query.set("thread", id);
  if (inboxStatus) query.set("status", inboxStatus);
  query.set("returnOpen", id);
  return `/?${query}`;
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
  for (const id of ["status-body", "open-codex", "evidence", "outcome-wrap", "checks-wrap", "decisions-wrap", "more"]) $(id).hidden = true;
  for (const details of $("thread-view").querySelectorAll("details")) details.open = false;
  $("thread-view").scrollTop = 0;
}

function showPanel(id) {
  if (id === openId) return Promise.resolve();
  threadSource?.close();
  threadSource = null;
  threadData = null;
  openId = id;
  if (id) $("panel-focus").href = focusedChatUrl(id);
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
  const headerToggle = $("header-toggle");
  headerToggle.hidden = false;
  function syncHeaderToggle() {
    const compact = document.documentElement.dataset.header === "compact";
    headerToggle.setAttribute("aria-pressed", String(compact));
    headerToggle.title = compact ? "Show header artwork" : "Hide header artwork";
    headerToggle.setAttribute("aria-label", headerToggle.title);
  }
  syncHeaderToggle();
  let headerMotion = null;
  let requestedCompact = document.documentElement.dataset.header === "compact";
  headerToggle.addEventListener("click", () => {
    const compact = requestedCompact = !requestedCompact;
    const apply = () => {
      document.documentElement.dataset.header = compact ? "compact" : "full";
      try { localStorage.setItem("compact-header", String(compact)); } catch { /* Keep the page-local choice. */ }
      syncHeaderToggle();
    };
    if (calm.matches || !document.startViewTransition || openId) { apply(); return; }
    headerMotion?.skipTransition();
    document.documentElement.dataset.headerMotion = "true";
    const motion = document.startViewTransition(apply);
    motion.types?.add("header-focus");
    headerMotion = motion;
    const finish = () => {
      if (headerMotion !== motion) return;
      delete document.documentElement.dataset.headerMotion;
      headerMotion = null;
    };
    motion.finished.then(finish, finish);
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== "compact-header" && event.key !== null) return;
    document.documentElement.dataset.header = readPreference("compact-header") === "true" ? "compact" : "full";
    requestedCompact = document.documentElement.dataset.header === "compact";
    syncHeaderToggle();
  });
  const search = $("inbox-search");
  const searchToggle = $("search-toggle");
  searchToggle.hidden = false;
  function showSearch(show) {
    $("search-box").hidden = !show;
    searchToggle.setAttribute("aria-expanded", String(show));
    if (show) search.focus();
    else {
      search.value = searchQuery = "";
      if (inboxData) renderInbox(inboxData);
    }
  }
  searchToggle.addEventListener("click", () => {
    const show = $("search-box").hidden;
    showSearch(show);
    if (!show) searchToggle.focus();
  });
  search.addEventListener("focus", (event) => { searchReturnFocus = event.relatedTarget || searchReturnFocus; });
  search.addEventListener("input", () => {
    searchQuery = search.value;
    if (inboxData) renderInbox(inboxData);
  });
  search.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    showSearch(false);
    const previous = searchReturnFocus?.isConnected && searchReturnFocus.matches("a, button, [tabindex]") ? searchReturnFocus : null;
    const target = cardFor(searchReturnFocus?.dataset.id) || previous || document.querySelector("#sections .row") || $("main-content");
    target.focus();
  });
  $("away-dismiss").addEventListener("click", () => { $("away-digest").hidden = true; });
  window.addEventListener("blur", () => {
    if (!inboxData || awaySnapshot) return;
    awaySnapshot = { at: Date.now(), keys: new Set(inboxData.filter(needsAttention).map(chatKey)) };
  });
  window.addEventListener("focus", () => {
    if (!awaySnapshot || !inboxData) return;
    const delta = awayDelta(awaySnapshot.keys, new Set(inboxData.filter(needsAttention).map(chatKey)), Date.now() - awaySnapshot.at);
    awaySnapshot = null;
    $("away-digest").hidden = delta.length === 0;
    $("away-link").textContent = `While you were away: ${delta.length} ${delta.length === 1 ? "chat now needs" : "chats now need"} you`;
  });
  document.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey ||
        shortcutBlocked(event.target, Boolean(document.querySelector("dialog[open]"))) || document.body.dataset.navigation === "open") return;
    if (event.key === "/") {
      event.preventDefault();
      searchReturnFocus = document.activeElement;
      showSearch(true);
      return;
    }
    if (event.key === "n") {
      const oldest = inboxData && groupChats(inboxData).get("waiting")[0];
      if (!oldest) return;
      event.preventDefault();
      const row = cardFor(chatKey(oldest));
      if (row?.getClientRects().length) { row.focus(); row.scrollIntoView({ block: "nearest" }); }
      else location.assign(`/?thread=${encodeURIComponent(chatKey(oldest))}&status=waiting`);
      return;
    }
    const direction = ["j", "ArrowDown"].includes(event.key) ? 1 : ["k", "ArrowUp"].includes(event.key) ? -1 : 0;
    if (!direction) return;
    const rows = [...document.querySelectorAll("#sections .row")].filter((row) => row.getClientRects().length);
    const key = queueTarget(rows.map((row) => row.dataset.id), document.activeElement.dataset.id, direction);
    const row = rows.find((row) => row.dataset.id === key);
    if (row) { event.preventDefault(); row.focus(); row.scrollIntoView({ block: "nearest" }); }
  });
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
    if (event.key === "Escape" && openId && !event.defaultPrevented && document.body.dataset.navigation !== "open") closePanel();
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
  stateSync.flush();
  const chats = inboxData || attentionData;
  if (chats) notifyChanges(chats);
  if (document.hidden) return;
  for (const node of document.querySelectorAll("[data-ago]")) node.textContent = ago(node.dataset.ago, "short" in node.dataset ? "" : " ago");
  for (const node of document.querySelectorAll("[data-quiet-at]")) node.textContent = `Quiet ${ago(node.dataset.quietAt).replace(/ ago$/, "")}`;
  if (threadData) renderStatus(threadData, threadData.turns[threadData.turns.length - 1]);
}, 30_000);


if (threadId) {
  $("thread-view").hidden = false;
  $("back").hidden = false;
  $("back").href = inboxUrl(inboxStatus, returnOpenId);
  $("back-label").textContent = inboxStatus ? INBOX_FILTERS[inboxStatus].label : "Inbox";
  $("inbox-title").hidden = true;
  $("thread-heading").hidden = false;
  connect(`/api/stream?thread=${encodeURIComponent(threadId)}`, "thread", renderThread);
  // The favicon and notifications cover every chat, not just this one; the live label follows this chat's stream.
  new EventSource("/api/stream").addEventListener("inbox", (message) => {
    attentionData = JSON.parse(message.data);
    stateSync.retain(attentionData.map(chatKey));
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
