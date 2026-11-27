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
const CHECK_REASONS = {
  edited_after_check: "Edited after last check",
  unproven: "Check exit code was not captured (piped or chained)",
  no_check: "No check command recorded after code edits",
};

function checkTag(state, reason) {
  const check = CHECK_TAGS[state];
  if (!check) return null;
  const node = el("span", `tag ${check.className}`, check.label);
  if (state === "unchecked" && CHECK_REASONS[reason]) node.title = CHECK_REASONS[reason];
  return node;
}
const NEXT_LABEL = { answer: "Answer", review: "Review", approve: "Approve", run: "Run", decide: "Decide", do: "To do" };
// The primary action names the step it completes ("Approve in Codex"), so a waiting step is never a generic "Open".
function stepVerb(chat, waiting) {
  if (!waiting) return "Open";
  if (chat.next_kind === "approve") return "Approve";
  if (chat.question || chat.next_kind === "answer") return "Answer";
  return chat.next_kind === "run" ? "Run" : "Open";
}
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

const UNDO_MS = 8000;

// Pure triage helpers, shared by the inbox interactions and their unit tests.
const AWAY_DIGEST_MS = 10 * 60 * 1000;
const DECK_TERMINAL_PREVIEW_ROWS = 5;
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

// The row to focus once `removed` leaves the list: the next one, else the previous one.
function focusAfterRemoval(keys, removed) {
  const rest = keys.filter((key) => key !== removed);
  const index = keys.indexOf(removed);
  return index < 0 ? "" : rest[Math.min(index, rest.length - 1)] || "";
}

function shortcutBlocked(target, modalOpen) {
  return modalOpen || Boolean(target?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])'));
}

// How full a chat's context was at its last request, or null when the app reports no window size.
// ponytail: fixed 50%/80% bands for every model; tune per model if they mislead.
function contextFill(used, size) {
  if (!Number.isSafeInteger(used) || !Number.isSafeInteger(size) || used <= 0 || size <= 0) return null;
  const percent = Math.min(100, Math.round(used / size * 100));
  return { percent, level: percent >= 80 ? "heavy" : percent >= 50 ? "filling" : "ok" };
}

function fillTone(percent, base = "") {
  return percent >= 90 ? "red" : percent >= 75 ? "amber" : base;
}

// The context window to measure against. Claude Code records none, but its windows are 200K or 1M,
// so usage past 200K can only be a 1M window; below that the size stays unknown (0).
// Claude transcripts omit the window; usage past the 200K window proves the 1M one. Else unknown.
function contextSize(chat) {
  if (chat.context_window > 0) return chat.context_window;
  return chat.harness === "claude" && chat.context_used > 200000 ? 1000000 : 0;
}

// Deck order changes only when something meaningful does: the inbox sorts by latest write, which on
// a glanceable screen would swap working keys every time an agent writes. Working keys keep the order
// they started in and new results the order they arrived in, so a newcomer joins the end and no key
// moves for a routine update. Needs you keeps longest wait first, which already appends newcomers.
function deckOrder(groups) {
  const by = (field) => (a, b) => (a[field] || "").localeCompare(b[field] || "");
  return new Map([...groups].map(([key, chats]) =>
    [key, key === "working" ? [...chats].sort(by("working_since")) : key === "new" ? [...chats].sort(by("turn_ended_at")) : chats]));
}

// Delegated chats ride under their orchestrator instead of filling the queue: a Codex subagent names its
// parent thread, and a relay or delegate-code worker runs in <repo>/.relay/<slug> or <repo>/.delegate-code/<slug>,
// so its parent is the latest chat in <repo> that started before it, preferring one still active when it started
// (working, or written to since) over a newer idle chat. A child `canParent(parent, chat)` refuses (say a parent
// the view hides) stays on its own.
const WORKER_FOLDER = /\/\.(?:relay|delegate-code)\//;

function workerFolder(chat) {
  return (chat.cwd || "").match(WORKER_FOLDER)?.[0].slice(1, -1) || "";
}

// Returns the top-level chats, parent key -> children, child key -> parent, and the child keys whose parent was
// inferred from the relay folder rather than named.
function deckDelegates(chats, canParent = () => true) {
  const byId = new Map(chats.map((chat) => [chat.id, chat]));
  const children = new Map();
  const parents = new Map();
  const inferred = new Set();
  const top = [];
  for (const chat of chats) {
    let parent = chat.parent_id && byId.get(chat.parent_id);
    const relay = !parent && (chat.cwd || "").split(WORKER_FOLDER);
    if (relay?.length === 2) {
      const started = chat.started_at || "";
      const before = chats.filter((other) => other.cwd === relay[0] && (other.started_at || "") <= started);
      const active = before.filter((other) => other.status === "working" || (other.updated_at || "") >= started);
      parent = (active.length ? active : before).sort((a, b) => (b.started_at || "").localeCompare(a.started_at || ""))[0];
    }
    if (!parent || parent === chat || !canParent(parent, chat)) { top.push(chat); continue; }
    const key = chatKey(parent);
    if (!children.has(key)) children.set(key, []);
    children.get(key).push(chat);
    parents.set(chatKey(chat), parent);
    if (relay?.length === 2) inferred.add(chatKey(chat));
  }
  return { top, children, parents, inferred };
}

// The worktree slug a relay or delegate-code worker runs in: /r/.delegate-code/fix-csv/src -> "fix-csv".
function workerSlug(chat) {
  return (chat.cwd || "").split(WORKER_FOLDER)[1]?.split("/")[0] || "";
}

const LIVE = ["working", "waiting"];
const endedAt = (chat) => Date.parse(chat.turn_ended_at || chat.updated_at || "");

// A worker's finished handoff was meant for its orchestrator, so once the orchestrator settled a later recorded
// turn it no longer needs you; a worker whose worktree is gone is settled even with its orchestrator out of view.
// A live run, a source-level approval or question, and a failed check are never superseded. A file mtime is no
// turn end, so a parent without `turn_ended_at` supersedes nothing.
function isSupersededSubtask(chat, parent) {
  if (LIVE.includes(chat.status) || chat.next_basis === "source" || chat.check_state === "failed") return false;
  if (chat.worktree_removed) return true;
  if (!parent || parent.needs_you || LIVE.includes(parent.status)) return false;
  const parentEnded = Date.parse(parent.turn_ended_at || "");
  const chatEnded = endedAt(chat);
  return Number.isFinite(parentEnded) && Number.isFinite(chatEnded) && parentEnded > chatEnded;
}

// Flags superseded subtasks on the chats as they arrive, so every view (rows, roll-ups, counts) reads one answer.
function markSuperseded(chats) {
  const { parents } = deckDelegates(chats);
  for (const chat of chats) chat.superseded = isSupersededSubtask(chat, parents.get(chatKey(chat)));
  return chats;
}

// An unchecked subtask its orchestrator verified with a passing check after the subtask ended raises no warning;
// an earlier or undated parent check never clears it, and a failed check always shows.
function effectiveCheckState(chat, parent) {
  const checked = Date.parse(parent?.check_passed_at || "");
  const ended = endedAt(chat);
  const verified = Number.isFinite(checked) && Number.isFinite(ended) && checked > ended;
  return chat.check_state === "unchecked" && verified && isSupersededSubtask(chat, parent) ? "" : chat.check_state || "";
}

function formatCompactTokens(n) {
  return n.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
}

// Time spent in finished turns: "45s", "9m 16s", "1h 5m".
function formatActive(seconds) {
  const s = Math.round(seconds), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h ? `${h}h ${m}m` : m ? `${m}m ${s % 60}s` : `${s}s`;
}

// Work done across subtasks (or one), "9m 16s · 41K out"; "" when nothing was recorded. Output tokens, not the
// session total, which is mostly cache reads and overstates the work.
function subtaskMetrics(children) {
  const sum = (field) => children.reduce((total, chat) => total + (Number(chat[field]) || 0), 0);
  const seconds = sum("active_seconds");
  const output = sum("output_tokens");
  return [seconds && formatActive(seconds), output && `${formatCompactTokens(output)} out`].filter(Boolean).join(" · ");
}

// Subtask states from most to least urgent: a parent lists its subtasks in this order and takes the tone of the
// most urgent exception among them.
const SUBTASK_ORDER = ["waiting", "failed", "stopped", "quiet", "working", "done"];
const SUBTASK_EXCEPTIONS = { waiting: "needs you", failed: "failed check", stopped: "stopped", quiet: "quiet" };

// One line for a parent: how many subtasks are done, then each exception by count, most urgent first.
function subtaskRollup(kinds) {
  const count = (kind) => kinds.filter((each) => each === kind).length;
  const exceptions = Object.keys(SUBTASK_EXCEPTIONS).filter(count);
  return {
    text: [`${count("done")} of ${kinds.length} done`, ...exceptions.map((kind) => `${count(kind)} ${SUBTASK_EXCEPTIONS[kind]}`)].join(" · "),
    tone: exceptions[0] || "",
  };
}

// Usage limits are per account, so the chat that reported last speaks for all; an ended window is dropped.
function latestQuota(chats, now = Date.now()) {
  const newest = chats.reduce((best, chat) => (chat.rate_limits_at || "") > (best?.rate_limits_at || "") ? chat : best, null);
  return (newest?.rate_limits || []).filter((window) => !window.resets_at || new Date(window.resets_at).getTime() > now);
}

function windowLabel(minutes) {
  if (minutes === 10080) return "Week";
  return minutes % 1440 === 0 ? `${minutes / 1440}d` : minutes % 60 === 0 ? `${minutes / 60}h` : `${minutes}m`;
}

// Time left until `iso`, rounded to what a glance needs: "<1m", "12m", "4h", "6d"; "" once passed.
function untilShort(iso, now = Date.now()) {
  const minutes = (new Date(iso).getTime() - now) / 60000;
  if (!(minutes > 0)) return "";
  if (minutes < 1) return "<1m";
  return minutes < 60 ? `${Math.round(minutes)}m` : minutes < 1440 ? `${Math.round(minutes / 60)}h` : `${Math.round(minutes / 1440)}d`;
}
function deckElapsed(since, now = Date.now()) {
  const started = new Date(since).getTime();
  if (!Number.isFinite(started)) return "";
  const seconds = Math.max(0, Math.floor((now - started) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${seconds}s`;
}

function deckTelemetry(chats, working, waits, now = Date.now()) {
  const recent = (at, duration) => { const time = Date.parse(at); return time <= now && time > now - duration; };
  const claude = chats.filter((chat) => chat.harness === "claude");
  const messages = claude.flatMap((chat) => chat.message_minutes || []).filter((at) => recent(at, 5 * 3600000));
  const reset = messages.length ? new Date(Math.min(...messages.map(Date.parse)) + 5 * 3600000).toISOString() : "";
  const captured = latestQuota(claude, now).find((window) => window.window_minutes === 300 && window.resets_at);
  const quota = latestQuota(chats.filter((chat) => chat.harness === "codex"), now).sort((a, b) => a.window_minutes - b.window_minutes)[0];
  const active = working.filter((chat) => chat.harness === "codex").length;
  const samples = chats.flatMap((chat) => chat.usage_minutes || []);
  const burn = working.flatMap((chat) => chat.usage_minutes || []).filter(([at]) => recent(at, 15 * 60000)).reduce((sum, [, tokens]) => sum + tokens, 0);
  const today = new Date(now); today.setHours(0, 0, 0, 0);
  const tokens = samples.filter(([at]) => Date.parse(at) >= today.getTime() && Date.parse(at) <= now).reduce((sum, [, count]) => sum + count, 0);
  const fills = chats.map((chat) => contextFill(chat.context_used, contextSize(chat))).filter(Boolean);
  const peak = fills.length ? Math.max(...fills.map((fill) => fill.percent)) : null;
  const earliest = waits.map(Date.parse).filter((at) => Number.isFinite(at) && at <= now);
  const note = "Local logs only; truncated histories and unsupported agents may omit usage.";
  return [
    // One reset reading per account: the captured 5-hour window when there is one (as the usage card shows),
    // otherwise a labelled estimate in minutes, never a seconds clock that looks more exact than it is.
    captured ? { id: "claude", label: "CLAUDE RESET", value: untilShort(captured.resets_at, now) || "—", tone: "",
      note: "From Claude Code's reported 5-hour window (status line capture)." }
      : { id: "claude", label: "CLAUDE RESET EST.", value: reset ? untilShort(reset, now) : claude.length ? "READY" : "—", tone: "",
        note: "Estimated from the earliest recorded Claude message in the last 5h; not an account quota reset. Turn on `install --claude-usage` for the reported value." },
    { id: "codex", label: "CODEX", value: `${active} ACTIVE${quota ? ` / ${Math.max(0, Math.round(100 - quota.used_percent))}%` : ""}`, tone: "", note: quota ? `Latest recorded ${windowLabel(quota.window_minutes)} account quota remaining.` : "Working Codex chats; quota not reported." },
    { id: "burn", label: "BURN", value: samples.length ? `${(burn / 15000).toFixed(1)}k/min` : "—", tone: "", note: `Recorded tokens over 15 minutes in currently working chats. ${note}` },
    { id: "peak", label: "PEAK CTX", value: peak === null ? "—" : `${peak}%`, tone: fillTone(peak), note: "Highest context utilization among chats with a known window." },
    { id: "wait", label: "MAX WAIT", value: earliest.length ? deckElapsed(new Date(Math.min(...earliest)).toISOString(), now) : "—", tone: earliest.length ? "amber" : "", note: "Longest wait among Needs you chats." },
    { id: "today", label: "TODAY", value: samples.length ? `${(tokens / 1000000).toFixed(1)}M TOK` : "—", tone: "", note: `Recorded tokens since local midnight. ${note}` },
  ];
}

// Apportion six cells, keeping at least one for each active status so rare work stays visible.
function deckMagazine(counts, filter = "") {
  const kinds = ["waiting", "working", "new"];
  if (filter) return Array.from({ length: 6 }, (_, index) => index < Math.min(6, counts[filter] || 0) ? filter : "");
  const total = kinds.reduce((sum, kind) => sum + counts[kind], 0);
  if (!total) return Array(6).fill("");
  // Up to six chats, one cell per chat; beyond that the cells become proportional shares.
  if (total <= 6) return [...kinds.flatMap((kind) => Array(counts[kind]).fill(kind)), ...Array(6 - total).fill("")];
  const shares = kinds.map((kind, index) => ({ kind, index, quota: counts[kind] / total * 6 }));
  const cells = shares.flatMap(({ kind, quota }) => Array(Math.floor(quota)).fill(kind));
  const remainder = [...shares].sort((a, b) => (b.quota % 1) - (a.quota % 1) || a.index - b.index);
  for (let i = 0; cells.length < 6; i++) cells.push(remainder[i].kind);
  for (const share of shares) {
    if (counts[share.kind] && !cells.includes(share.kind)) {
      const donor = shares.filter(({ kind }) => cells.filter((cell) => cell === kind).length > 1)
        .sort((a, b) => (cells.filter((cell) => cell === b.kind).length - b.quota) - (cells.filter((cell) => cell === a.kind).length - a.quota))[0];
      cells[cells.indexOf(donor.kind)] = share.kind;
    }
  }
  return kinds.flatMap((kind) => cells.filter((cell) => cell === kind));
}

function deckSwipe(dx, dy, width, hero = false, velocity = 0) {
  const travel = hero && Math.abs(dx) >= 12 && Math.sign(velocity) === Math.sign(dx) ? dx + velocity * 120 : dx;
  if (Math.abs(travel) < Math.max(40, Math.min(80, width * .16)) || Math.abs(dx) < Math.abs(dy) * 1.4) return "";
  return hero ? dx < 0 ? "next" : "previous" : dx < 0 ? "review" : "focus";
}

function deckUrgent(waits, now = Date.now()) {
  return waits.some((at) => { const elapsed = now - Date.parse(at); return elapsed > 15 * 60000; });
}

function deckTerminalState(chat, connected = true) {
  const reportedLive = chat.capabilities?.live_activity === true;
  const live = connected && reportedLive && !chat.quiet;
  const records = reportedLive ? (chat.activity_log || []).slice(-12) : [];
  const pending = reportedLive && chat.pending_tool;
  const events = pending ? [...records.slice(-11),{ at: "", kind: pending.startsWith("Bash: ") ? "command" : "tool", title: pending.replace(/^Bash: /, ""), pending: true }] : records;
  const label = !connected ? "OFFLINE" : !reportedLive ? "LAST KNOWN STATE" : chat.quiet ? "QUIET" : pending ? "CALL PENDING" : "RUNNING...";
  const fallback = reportedLive && chat.activity_summary ? chat.activity_summary : "Awaiting agent completion checkpoint…";
  return { label, live, events, fallback };
}

function deckTerminalRows(events, limit = DECK_TERMINAL_PREVIEW_ROWS) {
  return limit === null ? events : events.slice(-limit);
}

function deckHandoffText(chat, kind) {
  // A chat waiting on you has no outcome yet; a "still running" placeholder would contradict the question above it.
  const outcome = chat.outcome?.trim() || (kind === "new" ? "Completion checkpoint not recorded yet." : "");
  const next = chat.question?.trim() || (chat.next_kind !== "none" && chat.next_text?.trim())
    || (chat.next_kind === "none" ? "No further action requested." : "Open this chat to review the handoff.");
  return { outcome, next, pending: !chat.outcome?.trim() };
}

// Quiet for this long, a Working chat may be stuck (the same five minutes that notify).
const DECK_STALL_MS = 5 * 60_000;

function deckQuiet(chat, kind) {
  return kind === "working" && Boolean(chat.quiet);
}

function deckCanReview(chat, kind, now = Date.now()) {
  // A Working chat quiet past the stall threshold may be dead (closed terminal, crashed agent): let it be set
  // aside until it writes again. Earlier, a quiet chat may just be running a long command.
  if (chat.status === "working") return deckQuiet(chat, kind) && now - Date.parse(chat.updated_at) > DECK_STALL_MS;
  return kind === "new" || kind === "waiting" && Boolean(chat.attention_key);
}

function deckFallback(counts) {
  return counts.waiting || counts.working || counts.new ? "active" : counts.earlier ? "earlier" : "standby";
}
// End pure triage helpers.
const params = new URLSearchParams(location.search);
const threadId = params.get("thread") || "";
const returnOpenId = params.get("returnOpen") || "";
const deckView = params.get("view") === "deck" || location.pathname === "/deck";
const statusParam = params.get("status");
const inboxStatus = Object.hasOwn(INBOX_FILTERS, statusParam) ? statusParam : "";
const inboxReturn = inboxStatus ? `&status=${inboxStatus}` : "";
$("nav-inbox").dataset.category = inboxStatus || "all";
document.body.dataset.view = threadId ? "thread" : deckView ? "deck" : "inbox";
if (threadId && deckView) document.body.dataset.origin = "deck";
if (threadId) $("nav-inbox").removeAttribute("aria-current");
const wideDetail = matchMedia("(min-width: 1280px)");
const RESUME_LABEL = "Resume command";
// The page footer, and a marker where it lives when no chat pane is open (see showPanel).
const pageFooter = document.querySelector(".footer");
const footerHome = document.createComment("footer");
pageFooter.before(footerHome);
const calm = matchMedia("(prefers-reduced-motion: reduce)");
const WORKING_SPIN_PERIOD_MS = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--motion-status-working"));
let inboxData = null;
const inboxProgressRows = new Map();
let inboxChildren = new Map(); // orchestrator key -> delegated chats nested under its row, from renderInbox
let inboxRelations = new Map(); // orchestrator key -> every delegated chat, whatever the filter shows, from renderInbox
const delegateOpen = new Set(); // orchestrator keys whose finished subtasks are unfolded in the inbox
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

// A recorded option, with an agent's trailing "(Recommended)" shown as a quiet label instead of raw text.
function optionItem(option) {
  const match = /^(.+?)\s*\(recommended\)\s*$/i.exec(option);
  const item = el("li", "", match ? match[1] : option);
  if (match) item.append(el("span", "option-recommended", "Recommended"));
  return item;
}

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

function harnessPill(harness, label) {
  const pill = el("span", "harness-pill");
  pill.dataset.harness = harness;
  const mark = icon(`i-harness-${harness}`);
  mark.classList.add("harness-icon");
  pill.append(mark, document.createTextNode(label));
  return pill;
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
  document.body.dataset.connection = state;
  if (deckView && !threadId && deckData) renderDeck(deckData);
  showUnreachable(state !== "live");
}

// Offline before anything loaded: say the server is unreachable instead of leaving a blank page.
// Once data arrives the normal render owns these panels (Deck standby text, Inbox empty state).
function showUnreachable(offline) {
  if (threadId) return;
  if (deckView) {
    if (deckData) return;
    $("deck-empty").hidden = !offline;
    $("deck-empty").dataset.connected = "false";
    $("deck-standby-title").textContent = "NO CONNECTION · RETRYING";
    $("deck-standby-description").textContent = "Can't reach the local Your Turn server. Retrying on its own; if it stopped, start it again with your-turn serve (or make up in a clone).";
  } else {
    $("inbox-loading").hidden = Boolean(inboxData) || offline;
    $("inbox-unreachable").hidden = !offline || Boolean(inboxData);
  }
}

// Open streams keep a page out of the browser's back/forward cache: close them on leaving, reopen on return.
const streams = new Map();
addEventListener("pagehide", () => { for (const source of streams.keys()) source.close(); });
addEventListener("pageshow", (event) => {
  if (!event.persisted) return;
  for (const [source, open] of [...streams]) { streams.delete(source); open(); }
  rememberPage();
});

function stream(url, setup) {
  const source = new EventSource(url);
  streams.set(source, () => stream(url, setup));
  setup(source);
  return source;
}

function connect(url, event, render) {
  return stream(url, (source) => {
    connected(source, event, render);
    if (event === "inbox" && !deckView) {
      source.addEventListener("inbox-progress", (message) => renderInboxProgress(JSON.parse(message.data)));
    }
  });
}

function connected(source, event, render) {
  source.onopen = () => { setConnection("live", "Live"); stateSync.flush(); };
  source.onerror = () => setConnection("offline", "Reconnecting");
  source.addEventListener(event, (message) => {
    const data = JSON.parse(message.data);
    render(event === "inbox" ? markSuperseded(data) : data);
  });
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
  return Boolean(chat.needs_you) && !chat.superseded;
}

function reminderDismissed(chat) {
  if (!chat.attention_key) return false;
  return shared.dismissed[chatKey(chat)] === chat.attention_key;
}

function attentionState(chat) {
  return hasAttention(chat) ? reminderDismissed(chat) ? "dismissed" : "waiting" : chat.status;
}

function inboxDismissal(chat) {
  if (needsAttention(chat) && chat.attention_key) return "reminder";
  return isNewResult(chat) ? "result" : "";
}

// An end recorded without saying how, and with nothing to show, is no finished result; the app's
// own summary of a chat it keeps no messages of is something to show.
function hasResult(chat) {
  return chat.status !== "working" && chat.status !== "interrupted" && !(chat.status === "unknown" && !chat.outcome && !chat.summary);
}

// How long a working chat's turn has run: "5m", "<1m", or "" when its start is unknown.
function workingFor(since) {
  const elapsed = ago(since || "", "");
  return elapsed === "just now" ? "<1m" : elapsed;
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

function renderRow(chat, parent = null) {
  const state = attentionState(chat);
  const status = STATUS[state] || STATUS.idle;
  const unread = isNewResult(chat);
  const item = el("li");
  const link = el("a", "row");
  link.href = `/?thread=${encodeURIComponent(chatKey(chat))}${inboxReturn}`;
  link.dataset.status = state;
  link.dataset.id = chatKey(chat);
  link.dataset.unread = String(unread);
  // Exceptions the row marks on its own; everything else is carried by the section heading.
  if (chat.check_state === "failed") link.dataset.check = "failed";
  if (state === "working" && chat.quiet) link.dataset.quiet = "true";
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
  // The tooltip carries the full step and options, since the step text is clamped to one line.
  const options = state === "waiting" && chat.question && chat.options?.length ? chat.options.join(" · ") : "";
  if (summary) summaryNode.title = options ? `${summary}\n${options}` : summary;
  const meta = el("span", "row-tags");
  const action = chat.question ? "Answer" : NEXT_LABEL[chat.next_kind];
  const tag = state === "waiting" ? action || status.label : ["done", "idle", "dismissed"].includes(state) ? "" : status.label;
  if (state === "working" && chat.quiet) {
    const quiet = el("span", "tag tag--waiting", `Quiet ${quietFor(chat)}`);
    quiet.dataset.quietAt = chat.updated_at;
    quiet.title = quietHint(chat);
    meta.append(quiet);
  } else if (tag) {
    const elapsed = state === "working" ? workingFor(chat.working_since) : "";
    const node = el("span", `tag tag--${state}`, elapsed ? `${tag} ${elapsed}` : tag);
    if (elapsed) node.dataset.workingSince = chat.working_since;
    if (state === "unknown") node.title = unknownNote(chat);
    else if (state === "working" && liveUnverified(chat)) node.title = unverifiedNote(chat);
    meta.append(node);
  }
  const subtasks = inboxRelations.get(chatKey(chat));
  if (subtasks?.length) {
    const rollup = subtaskRollup(subtasks.map(subtaskKind));
    const node = el("span", "tag tag--subtasks", rollup.text);
    if (rollup.tone) node.dataset.tone = rollup.tone;
    node.title = `Subtasks: ${rollup.text}`;
    meta.append(node);
  }
  const basis = basisOf(chat);
  if (basis) {
    const node = el("span", "tag tag--idle", basis.label);
    node.title = basis.note;
    meta.append(node);
  }
  if (unread && sectionOf(chat) !== "new") meta.append(el("span", "tag tag--new", "New"));
  // Exception readings, shown only past a threshold, the same ones the Deck uses: a context window past 75%,
  // and a running turn clearly slower than this chat's own average (Δ over +20%).
  const fill = contextFill(chat.context_used, contextSize(chat));
  if (fill && fill.percent >= 75) {
    const ctx = el("span", "tag tag--reading", `CTX ${fill.percent}%`);
    ctx.dataset.tone = fill.percent >= 90 ? "red" : "amber";
    ctx.title = "Context window used";
    meta.append(ctx);
  }
  const lap = state === "working" ? deckLapDelta(chat) : null;
  if (lap) {
    const delta = deckDeltaMark(lap, "tag tag--reading");
    delta.textContent = `Δ ${delta.textContent}`;
    if (["amber", "red"].includes(delta.dataset.tone)) meta.append(delta);
  }
  // A Run step already says the check is still to do.
  const checkState = effectiveCheckState(chat, parent);
  const check = state === "working" || (checkState === "unchecked" && chat.next_kind === "run") ? null : checkTag(checkState, chat.check_reason);
  if (check) meta.append(check);
  if (meta.childNodes.length) description.append(meta);
  description.append(summaryNode);
  body.append(description);
  if (options) body.append(el("span", "row-options", options));
  const project = el("span", "row-project");
  if (HARNESS_LABEL[chat.harness]) {
    project.append(harnessPill(chat.harness, HARNESS_LABEL[chat.harness]));
  }
  const projectIcon = icon("i-workspace");
  projectIcon.classList.add("project-icon");
  project.append(projectIcon, el("span", "project-name", projectName(chat)));
  project.title = projectName(chat);
  const chevron = icon("i-chevron");
  chevron.classList.add("row-chevron");
  link.dataset.section = sectionOf(chat);
  link.append(glyph, body, project, time, chevron);
  item.append(link);
  // A sibling of the link, not inside it: a link cannot contain a button.
  const dismissal = inboxDismissal(chat);
  if (dismissal) {
    const dismiss = el("button", "icon-button row-dismiss");
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", `Dismiss ${dismissal === "reminder" ? "reminder" : "result"}: ${chatName(chat)}`);
    dismiss.title = `Dismiss ${dismissal === "reminder" ? "reminder" : "result"} (e)`;
    const label = el("span", "row-dismiss-label", "Dismiss");
    label.setAttribute("aria-hidden", "true");
    dismiss.append(icon("i-bell-off"), label);
    dismiss.addEventListener("click", () => dismissFromInbox(chat, dismissal));
    item.append(dismiss);
  }
  return item;
}

let undoTimer = 0;
function dismissFromInbox(chat, dismissal = inboxDismissal(chat)) {
  const key = chatKey(chat);
  const rows = [...document.querySelectorAll("#sections .row")].filter((row) => row.getClientRects().length);
  const next = focusAfterRemoval(rows.map((row) => row.dataset.id), key);
  if (dismissal === "reminder") saveShared({ dismissed: { [key]: chat.attention_key } });
  else {
    saveShared({ seen: { [key]: chat.turn_ended_at } });
    hideUndo();
  }
  transition(renderShared).then(() => cardFor(next)?.focus({ preventScroll: true }));
  if (dismissal !== "reminder") {
    const toast = el("div", "undo-toast-body");
    toast.append(el("span", "", `Result dismissed: ${chatName(chat)}`));
    $("undo-toast").replaceChildren(toast);
    restartUndoTimer();
    return;
  }
  const undo = el("button", "button", "Undo");
  undo.type = "button";
  undo.addEventListener("click", () => {
    hideUndo();
    saveShared({ dismissed: { [key]: null } });
    transition(renderShared).then(() => cardFor(key)?.focus({ preventScroll: true }));
  });
  const toast = el("div", "undo-toast-body");
  toast.append(el("span", "", `Reminder dismissed: ${chatName(chat)}`), undo);
  $("undo-toast").replaceChildren(toast);
  restartUndoTimer();
}

function restartUndoTimer() {
  clearTimeout(undoTimer);
  undoTimer = setTimeout(hideUndo, UNDO_MS);
}

function hideUndo() {
  clearTimeout(undoTimer);
  $("undo-toast").replaceChildren();
}

// Keep Undo available while it is being read or operated, in either inbox layout.
const undoToast = $("undo-toast");
undoToast.addEventListener("pointerenter", () => clearTimeout(undoTimer));
undoToast.addEventListener("focusin", () => clearTimeout(undoTimer));
undoToast.addEventListener("pointerleave", () => { if (undoToast.childNodes.length && !undoToast.contains(document.activeElement)) restartUndoTimer(); });
undoToast.addEventListener("focusout", (event) => { if (undoToast.childNodes.length && !undoToast.contains(event.relatedTarget)) restartUndoTimer(); });

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
  // Delegated chats follow their orchestrator as indented sibling rows, so each keeps its own swipe and Dismiss.
  list.replaceChildren(...chats.slice(0, limit).flatMap((chat) => [renderRow(chat), ...renderDelegates(chat)]));
  if (chats.length === 0) list.append(el("li", "empty column-empty", "No chats"));
  wrap.append(list);
  if (chats.length > limit) {
    // Says what the click adds and how much is still hidden, not just "Load more".
    const hidden = chats.length - limit;
    const next = Math.min(SECTION_LIMIT, hidden);
    const more = el("button", "button load-more", `Show ${next} more`);
    // The count only adds news when one click will not show everything.
    if (hidden > next) more.append(el("span", "load-more-count", `${hidden} left`));
    more.type = "button";
    more.setAttribute("aria-label", `Show ${next} more ${label.toLowerCase()} chats${hidden > next ? `, ${hidden} not shown` : ""}`);
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
  // A failed check leads (the exception outranks the queue); then longest wait first, the one you most likely missed.
  const failed = (chat) => Number(chat.check_state === "failed");
  groups.get("waiting").sort((a, b) => failed(b) - failed(a) || waitingSince(a).localeCompare(waitingSince(b)));
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
  // Set now, not in the view transition's deferred callback, so the open chat below reads this update.
  inboxData = chats;
  inboxProgressRows.clear();
  stateSync.retain(chats.map(chatKey));
  migrateLocalMarks(chats);
  notifyChanges(chats);
  if (inboxLayout && layoutOf(groupChats(chats)) !== inboxLayout) transition(() => renderInbox(chats));
  else renderInbox(chats);
  syncOpenThread();
}

function renderInboxProgress({ chats, scanned, total }) {
  for (const chat of chats) inboxProgressRows.set(chatKey(chat), chat);
  previousNewResultsCount = null;
  renderInbox(markSuperseded([...inboxProgressRows.values()]), { loading: true });
  $("inbox-loading").textContent = `Loading chats… ${scanned} of ${total}`;
}

// An orchestrator's nested subtasks. With three or more, finished ones already seen fold into one line, unless a
// search is running or one of them is open; running, quiet and failed subtasks always stay visible.
function renderDelegates(chat) {
  const key = chatKey(chat);
  const kids = inboxChildren.get(key) || [];
  const foldable = kids.length >= 3 && !searchQuery.trim()
    ? kids.filter((child) => subtaskKind(child) === "done" && !isNewResult(child) && !isChat(child, openId)) : [];
  const canFold = foldable.length >= 2;
  const folded = canFold && !delegateOpen.has(key);
  const rows = (folded ? kids.filter((child) => !foldable.includes(child)) : kids).map((child) => {
    const item = renderRow(child, chat);
    item.dataset.delegate = "";
    item.querySelector(".row-title").prepend(el("span", "sr-only", `Delegated by ${chatName(chat)}: `));
    // The parent's row already names the agent; a subtask repeats it only when it differs.
    if (child.harness === chat.harness) item.querySelector(".harness-pill")?.remove();
    return item;
  });
  if (!canFold) return rows;
  const item = el("li", "delegate-fold");
  item.dataset.delegate = "";
  const button = el("button", "delegate-fold-button", folded ? `${foldable.length} done` : `Hide ${foldable.length} done`);
  button.type = "button";
  button.dataset.foldKey = key;
  button.setAttribute("aria-expanded", String(!folded));
  button.setAttribute("aria-label", `${folded ? "Show" : "Hide"} ${foldable.length} finished subtasks of ${chatName(chat)}`);
  button.prepend(icon(folded ? STATUS.done.icon : "i-chevron"));
  button.addEventListener("click", () => {
    if (delegateOpen.has(key)) delegateOpen.delete(key);
    else delegateOpen.add(key);
    renderInbox(inboxData);
    document.querySelector(`[data-fold-key="${CSS.escape(key)}"]`)?.focus();
  });
  item.append(button);
  return [...rows, item];
}

function renderInbox(chats, { loading = false } = {}) {
  inboxData = chats;
  $("inbox-loading").hidden = !loading;
  const focusedHref = document.activeElement.closest(".row, .show-all")?.getAttribute("href");
  // Delegated chats nest under their orchestrator's row, unless they need you or a status filter would hide it.
  const delegates = deckDelegates(filterInbox(chats, searchQuery), (parent, child) => !needsAttention(child)
    && (inboxStatus ? sectionOf(parent) === inboxStatus : sectionOf(parent) !== "earlier" || sectionOf(child) === "earlier"));
  inboxChildren = delegates.children;
  // The roll-up counts every subtask, including ones lifted to the top level or hidden by search.
  inboxRelations = deckDelegates(chats).children;
  const groups = groupChats(delegates.top);
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
  $("inbox-empty").hidden = loading || chats.length > 0 || Boolean(searchQuery);
  $("inbox-unreachable").hidden = true;
  const noMatches = Boolean(searchQuery.trim()) && shown.length === 0;
  $("search-empty").hidden = loading || !noMatches;
  $("search-empty").textContent = noMatches ? `No chats match '${searchQuery}'` : "";
  $("filter-empty").hidden = loading || noMatches || !inboxStatus || shown.length > 0 || chats.length === 0;
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
    text.textContent = "Copied";
  } catch {
    text.textContent = command;  // Shown so it can be selected and copied by hand.
  }
  setTimeout(() => {
    delete button.dataset.copied;
    if (button.dataset.copy === command) text.textContent = RESUME_LABEL;
  }, 2000);
});

// Ask the computer running Your Turn to open the app: a phone has no such app, and embedded browsers (the Claude
// app's pane, IDE previews) drop custom-scheme links. Locally, a failed call falls back to the link itself.
const REMOTE = !["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);
document.addEventListener("click", async (event) => {
  const link = event.target.closest?.("a[data-open-key]");
  if (!link) return;
  event.preventDefault();
  const text = link.firstChild;
  const label = text.textContent;
  link.dataset.copied = "true";  // Holds the result label through live re-renders, like a copied command.
  let opened = false;
  try {
    const response = await fetch(`/api/open/${encodeURIComponent(link.dataset.openKey)}`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: "{}", signal: AbortSignal.timeout(10000) });
    opened = response.ok;
  } catch { /* Shown as not opened below. */ }
  if (!opened && !REMOTE) {
    delete link.dataset.copied;
    location.href = link.href;
    return;
  }
  text.textContent = opened ? "Opened on your Mac" : "Couldn’t open on your Mac";
  setTimeout(() => {
    delete link.dataset.copied;
    text.textContent = label;
  }, 2000);
});

function setOpenKey(link, key) {
  if (key) link.dataset.openKey = key;
  else delete link.dataset.openKey;
}

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
  if (command) {
    // A long command is cut to one line in the quiet status line; focus (a tap or Tab) shows all of it.
    const code = commandCode(text);
    code.tabIndex = 0;
    code.title = text;
    target.replaceChildren(code);
  }
  else if (structured) {
    const list = el("ol", "status-steps");
    list.append(...structured.steps.map((step) => el("li", "", step)));
    target.replaceChildren(el("p", "status-steps-label", structured.label), list);
  } else target.replaceChildren(...(text ? [el("p", "", text)] : []));
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
  const elapsed = state === "working" && !turn?.ended_at ? workingFor(turn?.started_at) : "";
  $("status-title").textContent = quiet ? "Working · quiet" : waited && waited !== "just now" ? `${status.label} · ${waited}`
    : elapsed ? `${status.label} · ${elapsed}` : status.label;
  const failed = thread.status !== "working" && Boolean(turn?.checks.some((check) => check.exit_code !== null && check.exit_code !== 0));
  // Claude keeps its terminal resume command and can also start a new Code session in Desktop.
  const resume = thread.harness === "claude" ? thread.handoff?.resume_command || "" : "";
  const link = thread.harness === "cursor" ? thread.handoff?.open_uri || "" : `codex://threads/${encodeURIComponent(thread.id)}`;
  const desktopLink = thread.harness === "claude" ? thread.handoff?.open_uri || "" : "";
  // Claude Code gets two short actions: "Resume command" copies the command that continues this chat in the CLI, and
  // "New in app" starts a new session in its folder (the app has no link to reopen an existing chat).
  const action = resume ? RESUME_LABEL : `${stepVerb(chat, state === "waiting")} in ${appName(thread)}`;
  // Keep "Copied" visible until its timeout restores the label.
  if (!$("open-codex").dataset.copied) $("open-codex").firstChild.textContent = action;
  $("open-codex").dataset.copy = resume;
  $("open-codex").href = resume ? "#" : link;
  $("open-codex").setAttribute("aria-label", resume ? `Copy the resume command: ${resume}` : thread.harness === "cursor" ? `${action} (opens the project)` : `${action} (full chat)`);
  $("open-codex").title = resume ? `Copy the resume command: ${resume}` : "";
  $("open-codex").hidden = !resume && !link;
  setOpenKey($("open-codex"), !resume && link ? chatKey(thread) : "");
  setOpenKey($("open-claude-desktop"), desktopLink ? chatKey(thread) : "");
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
    } else setStatusText(step?.title || "", step?.kind === "command" && Boolean(step.title));
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
    setStatusText(failed ? "No further action was requested, but a check failed." : "Nothing needs you.");
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
  // A failed check is the reason behind the request, so it sits in the box with it instead of only under Checks.
  const failedCheck = failed ? [...turn.checks].reverse().find((check) => check.exit_code !== null && check.exit_code !== 0) : null;
  $("failed-check").hidden = !failedCheck;
  if (failedCheck) {
    $("failed-check-label").textContent = `Failed check · exit ${failedCheck.exit_code}`;
    if ($("failed-check-text").textContent !== failedCheck.command) $("failed-check-text").replaceChildren(commandCode(failedCheck.command));
  }
  $("status-body").dataset.kind = kind;
  // Only a chat that needs you is loud. A finished chat that asks nothing, and one still running normally, collapse to
  // one quiet line with link actions; a quiet (stalled) run stays framed because it may need you.
  const settled = (kind === "none" && !failed) || (state === "working" && !quiet);
  $("status-card").dataset.settled = String(settled);
  $("open-codex").classList.toggle("open-codex--primary", !settled);
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
  $("next-options").replaceChildren(...options.map(optionItem));

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
  // Only a state the switch cannot show gets words: unsupported, or blocked with the way out.
  $("notification-status").hidden = notifySupported && !blocked;
  $("notification-status").textContent = !notifySupported ? "This browser does not support desktop notifications here."
    : "Blocked in this browser’s site settings. Allow them there.";
  $("settings-notify").disabled = !notifySupported || blocked;
  $("settings-notify").checked = notifySupported && notifyOn();
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
// Deck (beta): rail entry, on by default, and theme, saved per browser and applied without a reload.
function syncDeckSettings() {
  const root = document.documentElement.dataset;
  $("deck-form").elements["deck-enabled"].checked = root.deckEnabled === "true";
  for (const radio of document.querySelectorAll('[name="deck-theme"]')) radio.checked = radio.value === root.deckTheme;
}
syncDeckSettings();
$("deck-form").addEventListener("change", (event) => {
  const root = document.documentElement.dataset;
  try {
    if (event.target.name === "deck-enabled") {
      root.deckEnabled = String(event.target.checked);
      localStorage.setItem("your-turn.deck.enabled", root.deckEnabled);
    } else if (event.target.name === "deck-theme") {
      root.deckTheme = event.target.value;
      localStorage.setItem("your-turn.deck.theme", root.deckTheme);
    }
  } catch { /* Applied to this page; the choice resets when storage is unavailable. */ }
});
$("settings-notify").addEventListener("change", async () => {
  if (!notifySupported || Notification.permission === "denied") return;
  if (notifyOn()) {
    try { localStorage.removeItem("notify"); } catch { /* Stays on until storage works. */ }
  } else if (await Notification.requestPermission() === "granted") {
    try { localStorage.setItem("notify", "on"); } catch { /* Without storage the preference cannot be kept. */ }
  }
  syncSettingsNotifications();
});

// Full screen ends on every page load, so the app runs in a full-screen frame and navigates inside it.
const inFullscreenShell = (() => {
  try { return Boolean(window.frameElement?.hasAttribute("data-fullscreen-shell")); } catch { return false; }
})();
// The click that asks is the only gesture that may enter full screen, so the frame opens on this page.
function enterFullscreen(here) {
  const frame = document.createElement("iframe");
  frame.className = "fullscreen-frame";
  frame.title = "Your Turn";
  frame.dataset.fullscreenShell = "";
  frame.src = here;
  document.body.append(frame);
  frame.requestFullscreen().then(() => {
    for (const source of streams.keys()) source.close();
    streams.clear();
    document.addEventListener("fullscreenchange", () => {
      if (document.fullscreenElement) return;
      const inner = frame.contentWindow.location;
      location.assign(inner.pathname + inner.search);
    });
  }, () => {
    frame.remove();
    location.assign(`/fullscreen?to=${encodeURIComponent(here)}`);
  });
}
if (inFullscreenShell || document.fullscreenEnabled) {
  $("fullscreen-setting").hidden = false;
  $("settings-fullscreen").checked = inFullscreenShell;
  $("settings-fullscreen").addEventListener("change", () => {
    const here = location.pathname + location.search;
    if (inFullscreenShell) window.top.location.assign(here);
    else enterFullscreen(here);
  });
}
if (inFullscreenShell) {
  // The frame allows only this origin, so links that leave the app replace the full-screen page.
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (link && link.origin !== location.origin) link.target = "_top";
  }, { capture: true });
}

const drawer = matchMedia("(max-width: 959px)");
const railTooltip = $("rail-tooltip");
for (const control of document.querySelectorAll(".rail-action")) {
  const show = () => {
    if (drawer.matches) return;
    railTooltip.textContent = control.dataset.tooltip;
    const box = control.getBoundingClientRect();
    railTooltip.style.top = `${box.top + box.height / 2}px`;
    // With Settings or Help open, sit left of the panel instead of over its header and Close button.
    const panel = document.querySelector(".aside-panel:not([hidden])");
    railTooltip.style.right = panel ? `${innerWidth - panel.getBoundingClientRect().left + 8}px` : "";
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
function syncContextHelp() {
  const view = document.body.dataset.view === "deck" ? $("deck-view").dataset.mode === "simple" ? "launcher" : "dashboard" : "inbox";
  for (const section of document.querySelectorAll("[data-help-view]")) section.hidden = section.dataset.helpView !== view;
}
function showAside(name, restoreFocus = true) {
  const current = document.body.dataset.aside || "";
  for (const button of document.querySelectorAll("[data-aside]")) button.setAttribute("aria-expanded", String(button.dataset.aside === name));
  for (const panel of document.querySelectorAll(".aside-panel")) panel.hidden = panel.id !== name;
  if (name) document.body.dataset.aside = name;
  else delete document.body.dataset.aside;
  if (name === "help") syncContextHelp();
  if (name === "settings") {
    if (document.body.dataset.view === "deck") $("settings").insertBefore($("deck-form"), $("appearance-form"));
    else $("settings").append($("deck-form"));
  }
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
  if (deckData) renderDeck(deckData);
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
  // Scoped to the last turn, so it never reads as a second, different count beside More's "every turn" total. An
  // edit no check has covered is the one exception worth flagging here, beside the files it concerns.
  const unchecked = files.length && !checks.length ? "Unchecked" : checks.length && turn.edited_after_check ? "Edited after last check" : "";
  rowLabel("files-summary", `${files.length} ${files.length === 1 ? "file" : "files"} changed in the last turn`, unchecked);
  $("files-summary").dataset.tone = unchecked ? "warning" : "";
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
    // The turn places a decision in the chat; the exact time is only a hover away.
    const stamp = Number.isNaN(at.getTime()) ? "" : at.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const when = decision.turn ? `Turn ${decision.turn}` : stamp;
    const answer = (decision.chosen || "").replace(/^#+\s*/, "");
    // Without answer text the question is the only information, so it leads instead of a placeholder.
    const longAnswer = answer.length > DECISION_ANSWER_PREVIEW_LIMIT;
    const lead = el("p", "decision-answer-text", longAnswer ? decisionPreview(answer) : answer || decision.question);
    const context = el("p", "decision-question", answer ? decision.question : `Answered in ${appName(thread)}; the answer was not recorded.`);
    if (answer) context.title = decision.question;
    // Most decisions are the agent's, so only the exception (yours) is named.
    const meta = el("p", "decision-meta", [decision.source === "agent" ? "" : "You", when].filter(Boolean).join(" · "));
    if (stamp) meta.title = stamp;
    const alternatives = answer ? decision.options.filter((option) => option !== decision.chosen) : decision.options;
    // A single rejected option is the comparison that gives the choice its meaning, so it shows inline.
    const inlineAlternative = answer && alternatives.length === 1;
    const over = inlineAlternative ? el("span", "decision-over", `instead of ${alternatives[0]}`) : null;
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
    if (alternatives.length && !inlineAlternative) {
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
    footer.append(actions);
    const choice = over ? el("div", "decision-choice") : lead;
    if (over) choice.append(lead, over);
    // Question with its turn set apart on the right, then the choice and what it beat, then why; without an answer the
    // question leads and the note follows.
    const head = el("div", "decision-head");
    head.append(answer ? context : choice, ...(meta.textContent ? [el("span", "decision-turn", meta.textContent)] : []));
    item.replaceChildren(head, answer ? choice : context, ...(decision.reason ? [el("p", "reason", decision.reason)] : []), ...(actions.childElementCount ? [footer] : []));
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
  rowLabel("tools-summary", "Tools", `${calls} ${calls === 1 ? "call" : "calls"}`);
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
    const pill = harnessPill(thread.harness, appName(thread));
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
  const project = item(projectName(thread), thread.cwd, "i-workspace", true);
  project.classList.add("meta-item--project");
  items.push(project);
  if (thread.git_branch) {
    // The branch is the first to shorten on a narrow screen, so the meta row stays one line; its tooltip keeps it whole.
    const branch = item(thread.git_branch, `Recorded Git branch: ${thread.git_branch}`, "i-branch", true);
    branch.classList.add("meta-item--branch");
    items.push(branch);
  }
  items.push(item(ago(thread.updated_at), "Last recorded event"));
  // How full the context window is, as a short bar with its percent: muted while normal, amber past 75% and
  // red past 90%, the same thresholds as the inbox tag and the Deck gauge.
  const fill = contextFill(thread.context_used, contextSize(thread));
  if (fill) {
    const context = item(`${fill.percent}%`, `Context window: ${tokenCount(thread.context_used, true)} of ${tokenCount(contextSize(thread), true)} tokens used`);
    context.classList.add("meta-item--context");
    if (fill.percent >= 75) context.dataset.tone = fill.percent >= 90 ? "red" : "amber";
    const bar = el("span", "context-bar");
    bar.setAttribute("aria-hidden", "true");
    bar.style.setProperty("--fill", `${fill.percent}%`);
    context.prepend(el("span", "context-label", "CTX"), bar);
    context.setAttribute("aria-label", `Context ${fill.percent}% used`);
    items.push(context);
  }
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
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  // Each chip says its scope: checks and files are the latest turn's, context the whole chat's
  // (the More section's "Files changed" counts every turn, so an unscoped "14" next to its "17" read as a mismatch).
  const turnChips = [
    failed && [`${failed} failed`, "#checks-wrap", "danger"],
    passed && [`${passed} passed`, "#checks-wrap", "passed"],
    unknown && [`${unknown} ${exitCodes ? "without exit code" : "not recorded"}`, "#checks-wrap", "muted"],
    // Same words as the inbox tag, and short enough to keep the chip strip on one line in portrait.
    files.length && !checks.length && ["Edits unchecked", "#checks-wrap", "warning"],
    checks.length && turn.edited_after_check && ["Edited after last check", "#checks-wrap", "warning"],
    files.length && [plural(files.length, "file"), "#outcome-wrap", ""],
  ].filter(Boolean);
  // Only the Deck's chat HUD shows this strip. Elsewhere it repeated the files row, the Checks section and the
  // status card for a whole extra row; the files row carries the unchecked-edit warning instead.
  const header = threadId ? $("thread-heading") : document.querySelector(".panel-heading");
  header.append($("evidence"));
  $("evidence").hidden = turnChips.length === 0 || document.body.dataset.origin !== "deck";
  // The scope is in each chip's tooltip and accessible name, not a visible label: the chips read on their own.
  const chip = (scopeLabel) => ([text, target, tone]) => {
    const link = el("a", "evidence-chip", text);
    link.href = target;
    link.title = `${scopeLabel}: ${text}`;
    link.setAttribute("aria-label", `${text}, ${scopeLabel.toLowerCase()}`);
    if (tone) link.dataset.tone = tone;
    const item = el("li");
    item.append(link);
    return item;
  };
  $("evidence-list").replaceChildren(...turnChips.map(chip("Last turn")));
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

// The no-scroll HUD layouts: wide and driven by a mouse or trackpad (see app.css).
const HUD_WIDE = matchMedia("(min-width: 1200px) and (pointer: fine)");

function deckHudWide() {
  return document.body.dataset.origin === "deck" && HUD_WIDE.matches;
}

// Crossing 1200px (or plugging in a mouse) re-renders the chat so its layout (data-hud) matches the window.
HUD_WIDE.addEventListener("change", () => { if (threadData) renderThread(threadData); });

// A subtask's state in the order a parent sorts them; see SUBTASK_ORDER.
function subtaskKind(chat) {
  if (needsAttention(chat)) return "waiting";
  if (chat.check_state === "failed") return "failed";
  if (chat.status === "interrupted") return "stopped";
  if (chat.status === "working") return chat.quiet ? "quiet" : "working";
  return "done";
}

const SUBTASK_LABEL = { waiting: "Needs you", failed: "Check failed", stopped: "Stopped", quiet: "Quiet", working: "Working", done: "Done" };

// Every chat this page knows: the inbox beside a panel, or the attention stream on a full chat page.
function chatRelations() {
  return deckDelegates(inboxData || attentionData || []);
}

function subtaskRow(chat, kind, parent) {
  const state = attentionState(chat);
  const link = el("a", "list-row subtask");
  link.href = `/?thread=${encodeURIComponent(chatKey(chat))}${inboxReturn}`;
  link.dataset.kind = kind;
  link.dataset.status = state;
  const glyph = el("span", "glyph");
  glyph.append(icon((STATUS[state] || STATUS.idle).icon));
  if (state === "working") syncSpin(glyph.querySelector("use"));
  // The age says what it measures: a quiet run since its last activity, a running one since it started.
  const when = kind === "quiet" ? `last activity ${ago(chat.updated_at)}` : kind === "working" ? workingFor(chat.working_since) : ago(chat.updated_at);
  // A worker's slug names it at a glance; its brief's first line (often a raw "Task: …" heading) stays in the tooltip.
  const slug = workerSlug(chat);
  const head = el("span", "subtask-head");
  const title = el("span", `subtask-title${slug ? " subtask-title--slug" : ""}`, slug || chatName(chat));
  // The parent already names its agent; a subtask names its own only when it differs.
  const pill = HARNESS_LABEL[chat.harness] && chat.harness !== parent?.harness ? [harnessPill(chat.harness, HARNESS_LABEL[chat.harness])] : [];
  const status = el("span", "subtask-state", [SUBTASK_LABEL[kind], subtaskMetrics([chat]), when].filter(Boolean).join(" · "));
  // A failed check already is the row's state; an unchecked one is shown unless its orchestrator verified it.
  // A Run step already says the check is still to do, as on the inbox row.
  const checkState = effectiveCheckState(chat, parent);
  const check = kind === "failed" || kind === "working" || (checkState === "unchecked" && chat.next_kind === "run") ? null
    : checkTag(checkState, chat.check_reason);
  head.append(title, ...pill, ...(check ? [check] : []), status);
  const summary = chatSummary(chat);
  link.append(glyph, head, ...(summary ? [el("span", "subtask-summary", summary)] : []));
  link.title = [chatName(chat), summary].filter(Boolean).join("\n");
  // Beside the inbox, a subtask opens in the same pane, like a row click.
  link.addEventListener("click", (event) => {
    if (threadId || !wideDetail.matches || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    showPanel(chatKey(chat));
  });
  const item = el("li");
  item.append(link);
  return item;
}

const parentLine = el("p", "parent-link");

// An orchestrator lists its subtasks by urgency under its status; a subtask links back to its orchestrator.
function renderSubtasks(thread) {
  const { children, parents, inferred } = chatRelations();
  const key = thread ? chatKey(thread) : "";
  const kids = children.get(key) || [];
  $("subtasks-wrap").hidden = kids.length === 0;
  if (kids.length) {
    const rows = kids.map((chat) => ({ chat, kind: subtaskKind(chat) }))
      .sort((a, b) => SUBTASK_ORDER.indexOf(a.kind) - SUBTASK_ORDER.indexOf(b.kind));
    const rollup = subtaskRollup(rows.map(({ kind }) => kind));
    $("subtasks-count").textContent = [rollup.text, subtaskMetrics(kids)].filter(Boolean).join(" · ");
    $("subtasks-count").dataset.tone = rollup.tone;
    // The inbox's own row for this chat, which carries the check fields the thread view lacks.
    const parent = parents.get(chatKey(kids[0])) || thread;
    $("subtasks").replaceChildren(...rows.map(({ chat, kind }) => subtaskRow(chat, kind, parent)));
  }
  const parent = parents.get(key);
  (threadId ? $("subtitle") : $("panel-subtitle")).after(parentLine);
  parentLine.hidden = !parent;
  if (!parent) return;
  const link = el("a", "", chatName(parent));
  link.href = `/?thread=${encodeURIComponent(chatKey(parent))}${inboxReturn}`;
  link.addEventListener("click", (event) => {
    if (threadId || !wideDetail.matches || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    showPanel(chatKey(parent));
  });
  // A parent guessed from the worker folder says so, since it is not recorded by the agent.
  const guessed = inferred.has(key);
  parentLine.replaceChildren(guessed ? "Likely subtask of " : "Subtask of ", link);
  parentLine.title = guessed ? `Inferred from the ${workerFolder(thread)} folder this chat runs in` : "";
}

function inboxRow(thread) {
  const key = chatKey(thread);
  return (inboxData || attentionData || []).find((chat) => chatKey(chat) === key);
}

// After an inbox update, an open chat whose superseded state flipped renders again; otherwise only its subtasks do.
function syncOpenThread() {
  if (!threadData) return;
  if (Boolean(inboxRow(threadData)?.superseded) !== Boolean(threadData.superseded)) renderThread(threadData);
  else renderSubtasks(threadData);
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
  $("status-card").dataset.settled = "false";
    $("status-icon").setAttribute("href", "#i-alert");
    $("status-title").textContent = "No rollout file for this chat";
    $("status-body").hidden = false;
    $("status-body").dataset.kind = "none";
    $("next-kind").hidden = true;
    setStatusText("It may have been archived. Go back to the inbox.");
    for (const id of ["open-codex", "next-options", "reminder-toggle", "quiet-note", "pending-step", "failed-check", "evidence", "outcome-wrap", "checks-wrap", "decisions-wrap", "subtasks-wrap", "more"]) $(id).hidden = true;
    parentLine.hidden = true;
    if (openingPanel) title.focus({ preventScroll: true });
    return;
  }
  threadData = thread;
  // The thread stream carries no relations: a superseded worker reads as settled here too, its handoff kept as history.
  thread.superseded = Boolean(inboxRow(thread)?.superseded);
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
  renderSubtasks(thread);
  renderEarlier(thread.turns);
  renderSessionFiles(thread, turn);
  renderTimeline(thread);
  renderToolUsage(thread);
  renderSessionInfo(thread, turn);
  // Opened from Deck on a wide screen, the chat is a no-scroll, three-column HUD. Its sections still fold:
  // someone who opened the chat has time to go through them.
  $("thread-view").dataset.hud = String(deckHudWide());
  if (deckHudWide()) {
    // Compact live facts lead the More column and long histories close it. Moving the nodes, not
    // CSS `order`, keeps keyboard and reading order equal to what is on screen.
    $("more").querySelector(".list").append(...["hero-meta", "tools-wrap", "activity-wrap", "session-files-wrap", "earlier-wrap"].map($));
  }
  markThreadSeen();
  if (openingPanel) title.focus({ preventScroll: true });
}

// A turn that ends while its chat sits open in a page you are not using (another window, a background tab)
// stays a new result; it is marked seen once this page has focus again.
function markThreadSeen() {
  const turn = threadData?.turns[threadData.turns.length - 1];
  if (!turn?.ended_at || seen.get(chatKey(threadData)) >= turn.ended_at || !document.hasFocus()) return;
  seen.set(chatKey(threadData), turn.ended_at);
  if (inboxData) renderInbox(inboxData);
  else if (attentionData) syncNavigation(attentionData);
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
  $("status-card").dataset.settled = "false";
  $("status-icon").setAttribute("href", "#i-turn");
  $("status-title").textContent = "Loading…";
  for (const id of ["status-body", "open-codex", "evidence", "outcome-wrap", "checks-wrap", "decisions-wrap", "subtasks-wrap", "more"]) $(id).hidden = true;
  parentLine.hidden = true;
  for (const details of $("thread-view").querySelectorAll("details")) details.open = false;
  $("thread-view").scrollTop = 0;
}

function showPanel(id) {
  if (id === openId) return Promise.resolve();
  threadSource?.close();
  streams.delete(threadSource);
  threadSource = null;
  threadData = null;
  openId = id;
  if (id) $("panel-focus").href = focusedChatUrl(id);
  return transition(() => {
    document.body.dataset.panel = id ? "open" : "closed";
    $("thread-view").hidden = !id;
    // Beside an open chat the footer rides at the end of the chat pane, scrolling away on its gray instead of
    // holding a pinned row under both columns; closing the chat puts it back.
    if (id) $("thread-view").append(pageFooter);
    else footerHome.parentNode.insertBefore(pageFooter, footerHome.nextSibling);
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

// Deck: selected handoff and telemetry above compact, selectable status rows.
let deckData = null;
let deckChildren = new Map(); // orchestrator key -> delegated chats, from deckGroups

// The orchestrator's delegated chats, each with its state and handoff line; each opens its own thread.
function deckDelegateList(chat) {
  const children = deckChildren.get(chatKey(chat));
  if (!children?.length) return null;
  const section = el("section", "deck-delegates");
  section.setAttribute("aria-label", "Delegated chats");
  section.append(el("h3", "deck-supporting-label", `DELEGATED · ${children.length}`));
  const list = el("ol");
  for (const child of children) {
    const kind = sectionOf(child);
    const link = el("a", "deck-delegate");
    link.href = `/?thread=${encodeURIComponent(chatKey(child))}&view=deck`;
    link.dataset.kind = kind;
    link.append(icon(SECTION_ICONS[kind]), deckAgent(child), el("span", "deck-delegate-title", chatName(child)));
    const line = chatSummary(child);
    if (line) link.append(el("span", "deck-delegate-line", line));
    link.title = [chatName(child), line].filter(Boolean).join(" · ");
    const item = el("li");
    item.append(link);
    list.append(item);
  }
  section.append(list);
  return section;
}
let deckSelected = "";
// The hero follows urgency (Needs you first) until the user picks a chat; a status filter resets it.
let deckPinned = false;
let deckFilter = "";
let deckDirection = 0;
let deckMomentum = 0;
let deckEarlierLimit = SECTION_LIMIT;
let deckLayout = readPreference("your-turn.deck.layout") === "focus" ? "focus" : "multi";
let deckMode = readPreference("your-turn.deck.mode") === "simple" ? "simple" : "dashboard";
const deckDismissals = new Map();
const deckGroupOpen = new Map();
// Narrow portrait (phone, split pane) starts queues collapsed; a tap or fleet filter opens one.
const deckNarrow = matchMedia("(max-width: 599px) and (orientation: portrait)");
// With the queue dock showing, the full lists below are a secondary tray and start collapsed too.
const deckWide = matchMedia("(min-width: 1200px)");
const deckDocked = () => deckLayout === "multi" && deckWide.matches && !$("deck-matrix").hidden;
deckWide.addEventListener("change", () => { if (deckData) renderDeck(deckData); });
let deckGesture = null;
// While the browser scrolls a touch drag (and its fling), live renders wait: replacing the card would end the scroll.
let deckScrolling = false;
function deckScrollTakeover() {
  deckGesture = null;
  if (deckScrolling) return;
  deckScrolling = true;
  const done = () => {
    if (!deckScrolling) return;
    deckScrolling = false;
    renderDeck(deckData);
  };
  document.addEventListener("scrollend", done, { capture: true, once: true });
  setTimeout(done, 3000);  // No scroll after all (a tap that drifted), or no scrollend support.
}
let deckSwipeUntil = 0;
const DECK_NAMES = { waiting: "NEEDS YOU", working: "WORKING", new: "READY" };
const DECK_AGENTS = { claude: "Claude", codex: "Codex", cursor: "Cursor" };
const deckSlots = [readPreference("your-turn.deck.slot1") || "claude", readPreference("your-turn.deck.slot2") || "codex"];
const DECK_REVIEW_KEY = "your-turn.deck.reviewed";
let deckReviewed = deckView && !threadId ? readDeckReviews() : new Map();

function readDeckReviews() {
  try {
    const entries = JSON.parse(readPreference(DECK_REVIEW_KEY) || "[]");
    return new Map(Array.isArray(entries) ? entries.filter((entry) => Array.isArray(entry) && entry.length === 2 && typeof entry[0] === "string" && (typeof entry[1] === "string" || entry[1] === null)) : []);
  } catch { return new Map(); }
}

function deckReviewStamp(chat) {
  const key = chatKey(chat);
  if (deckReviewed.has(key)) return deckReviewed.get(key);
  // Older Deck versions used the reminder map; only Deck interprets those markers.
  const legacy = shared.dismissed[key];
  return typeof legacy === "string" && legacy.startsWith("reviewed:") ? legacy.slice(9) : null;
}

function setDeckReview(key, value) {
  deckReviewed = new Map([...deckReviewed, ...readDeckReviews()]);
  deckReviewed.set(key, value);
  try { localStorage.setItem(DECK_REVIEW_KEY, JSON.stringify([...deckReviewed])); } catch { /* Keep this page's review state. */ }
}

// What a Deck review remembers: the result it saw, or for a quiet chat the silence it set aside.
function deckReviewMark(chat, kind) {
  return kind === "working" ? `quiet:${chat.updated_at}` : chat.turn_ended_at;
}

function deckSectionOf(chat) {
  const kind = sectionOf(chat);
  return ["new", "working"].includes(kind) && deckReviewStamp(chat) === deckReviewMark(chat, kind) ? "earlier" : kind;
}

function deckGroups(chats) {
  const delegates = deckDelegates(chats, (parent) => deckSectionOf(parent) !== "earlier");
  deckChildren = delegates.children;
  const groups = deckOrder(groupChats(delegates.top));
  for (const kind of ["new", "working"]) {
    const reviewed = groups.get(kind).filter((chat) => deckReviewStamp(chat) === deckReviewMark(chat, kind));
    if (!reviewed.length) continue;
    const keys = new Set(reviewed.map(chatKey));
    groups.set(kind, groups.get(kind).filter((chat) => !keys.has(chatKey(chat))));
    groups.set("earlier", [...groups.get("earlier"), ...reviewed].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
  }
  return groups;
}

if (deckView && !threadId) window.addEventListener("storage", (event) => {
  if (event.key !== DECK_REVIEW_KEY && event.key !== null) return;
  deckReviewed = readDeckReviews();
  if (deckData) renderDeck(deckData);
});

function deckEntries(groups) {
  return ["waiting", "working", "new"].filter((kind) => !deckFilter || kind === deckFilter)
    .flatMap((kind) => groups.get(kind).map((chat) => ({ chat, kind })));
}

function deckCarouselQueue(groups) {
  const kind = deckFilter || ["waiting", "working", "new"].find((key) => groups.get(key).some((chat) => chatKey(chat) === deckSelected)) || "waiting";
  return groups.get(kind);
}

function selectDeckChat(key, direction = 0) {
  deckSelected = key;
  deckPinned = true;
  deckDirection = direction;
  if (deckData) renderDeck(deckData);
}

function cycleDeckChat(step, velocity = 0) {
  if (!deckData) return;
  const queue = deckCarouselQueue(deckGroups(deckData));
  if (queue.length < 2) { renderDeck(deckData); return; }
  const index = queue.findIndex((chat) => chatKey(chat) === deckSelected);
  deckMomentum = Math.min(2, Math.abs(velocity));
  selectDeckChat(chatKey(queue[(index + step + queue.length) % queue.length]), step);
}

function focusDeckKind(kind) {
  deckFilter = deckFilter === kind ? "" : kind;
  const groups = deckGroups(deckData);
  if (deckFilter) deckGroupOpen.set(deckFilter, true);
  deckPinned = false;
  deckSelected = deckEntries(groups)[0] ? chatKey(deckEntries(groups)[0].chat) : "";
  renderDeck(deckData);
}

function renderDeckFleet(groups) {
  const fleet = $("deck-fleet");
  if (!fleet.children.length) {
    const all = el("button", "deck-fleet-all");
    all.type = "button";
    all.dataset.clearFilter = "";
    all.title = "All chats · Clear status filter";
    all.setAttribute("aria-label", "Show all chats and clear status filter");
    all.append(icon("i-fleet"));
    const lights = el("span", "deck-lights");
    lights.setAttribute("aria-hidden", "true");
    lights.append(...Array.from({ length: 6 }, (_, index) => {
      const light = el("span");
      light.dataset.kind = "";
      light.style.setProperty("--index", String(index));
      return light;
    }));
    fleet.append(all, lights, ...Object.keys(DECK_NAMES).map((kind) => {
      const button = el("button", "deck-fleet-readout");
      button.type = "button";
      button.dataset.kind = kind;
      button.append(el("strong"), el("span", "", DECK_NAMES[kind]));
      return button;
    }));
  }
  const counts = Object.fromEntries(Object.keys(DECK_NAMES).map((kind) => [kind, groups.get(kind).length]));
  const cells = deckMagazine(counts, deckFilter);
  const lights = fleet.querySelector(".deck-lights");
  const revUp = fleet.dataset.filter !== deckFilter && !calm.matches;
  if (revUp) {
    lights.classList.remove("deck-lights-rev");
    // Restart the keyframe sweep even when the new filter uses the same cell colors.
    void lights.offsetWidth;
  }
  [...lights.children].forEach((light, index) => {
    light.dataset.kind = cells[index];
  });
  if (revUp) lights.classList.add("deck-lights-rev");
  fleet.querySelector(".deck-fleet-all").setAttribute("aria-pressed", String(!deckFilter));
  for (const button of fleet.querySelectorAll("button[data-kind]")) {
    const kind = button.dataset.kind;
    button.firstChild.textContent = counts[kind];
    button.dataset.empty = String(counts[kind] === 0);
    // Working counts every open turn; the quiet ones (maybe stuck) are named beside it.
    const quiet = kind === "working" ? groups.get(kind).filter((chat) => chat.quiet).length : 0;
    button.lastChild.textContent = quiet ? `${DECK_NAMES[kind]} · ${quiet} QUIET` : DECK_NAMES[kind];
    button.setAttribute("aria-pressed", String(deckFilter === kind));
    button.setAttribute("aria-label", `${DECK_NAMES[kind]}: ${counts[kind]}${quiet ? `, ${quiet} quiet` : ""}. ${deckFilter === kind ? "Show all chats" : "Focus this group"}.`);
  }
  fleet.dataset.filter = deckFilter;
}

$("deck-fleet").addEventListener("click", (event) => {
  if (event.target.closest("[data-clear-filter]") && deckData) {
    deckFilter = "";
    renderDeck(deckData);
    return;
  }
  const button = event.target.closest("button[data-kind]");
  if (button && deckData) focusDeckKind(button.dataset.kind);
});
$("deck-reload").addEventListener("click", (event) => {
  event.currentTarget.setAttribute("aria-busy", "true");
  location.reload();
});
$("deck-layout").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-layout]");
  if (!button) return;
  deckLayout = button.dataset.layout;
  try { localStorage.setItem("your-turn.deck.layout", deckLayout); } catch { /* Page-local layout still works. */ }
  if (deckData) renderDeck(deckData);
});
function setDeckMode(mode, persist = true) {
  deckMode = mode === "simple" ? "simple" : "dashboard";
  $("deck-mode-switch").hidden = !deckView || Boolean(threadId);
  $("deck-view").dataset.mode = deckMode;
  $("deck-launcher").hidden = deckMode !== "simple";
  if (document.body.dataset.aside === "help") syncContextHelp();
  for (const button of $("deck-mode-switch").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.deckMode === deckMode));
  }
  if (persist) try { localStorage.setItem("your-turn.deck.mode", deckMode); } catch { /* Keep this page's selection. */ }
}
setDeckMode(deckMode, false);
$("deck-mode-switch").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-deck-mode]");
  if (!button) return;
  setDeckMode(button.dataset.deckMode);
  if (drawer.matches) closeNavigation();
});

const deckLaunchApps = $("deck-launch-apps");
const deckAppsAvailable = deckLaunchApps.dataset.available === "true";
$("deck-launch-unavailable").hidden = deckAppsAvailable;
if (!deckAppsAvailable) for (const button of deckLaunchApps.querySelectorAll("[data-open-app]")) {
  button.disabled = true;
  button.setAttribute("aria-describedby", "deck-launch-unavailable");
}
const deckLaunchPages = [...deckLaunchApps.querySelectorAll(".deck-launch-page")];
const deckLaunchPagination = $("deck-launch-pagination");
let deckLaunchPage = 0;
function syncDeckLaunchPage(index) {
  deckLaunchPage = Math.max(0, Math.min(index, deckLaunchPages.length - 1));
  deckLaunchPages.forEach((page, i) => { page.inert = i !== deckLaunchPage; });
  for (const button of deckLaunchPagination.querySelectorAll("[data-launch-page]")) {
    if (Number(button.dataset.launchPage) === deckLaunchPage) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  $("deck-launch-position").textContent = `Shortcuts page ${deckLaunchPage + 1} of ${deckLaunchPages.length}`;
}
function showDeckLaunchPage(index, behavior = calm.matches ? "instant" : "smooth") {
  syncDeckLaunchPage(index);
  const left = deckLaunchPages[deckLaunchPage].offsetLeft - deckLaunchPages[0].offsetLeft;
  deckLaunchApps.scrollTo({ left, behavior });
}
syncDeckLaunchPage(0);
deckLaunchPagination.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-launch-page]");
  if (!button) return;
  showDeckLaunchPage(Number(button.dataset.launchPage));
});
deckLaunchApps.addEventListener("keydown", (event) => {
  const index = { ArrowLeft: deckLaunchPage - 1, ArrowRight: deckLaunchPage + 1, Home: 0, End: deckLaunchPages.length - 1 }[event.key];
  if (index === undefined || event.altKey || event.ctrlKey || event.metaKey) return;
  event.preventDefault();
  showDeckLaunchPage(index);
  deckLaunchApps.focus({ preventScroll: true });
});
let deckLaunchScrollTimer;
deckLaunchApps.addEventListener("scroll", () => {
  clearTimeout(deckLaunchScrollTimer);
  deckLaunchScrollTimer = setTimeout(() => {
    const width = deckLaunchPages[1].offsetLeft - deckLaunchPages[0].offsetLeft;
    if (width) syncDeckLaunchPage(Math.round(deckLaunchApps.scrollLeft / width));
  }, 100);
}, { passive: true });
new ResizeObserver(() => {
  if (deckLaunchApps.clientWidth) showDeckLaunchPage(deckLaunchPage, "instant");
}).observe(deckLaunchApps);
$("deck-launcher").addEventListener("click", async (event) => {
  if (event.target.closest("[data-open-settings]")) { showAside("settings"); return; }
  const button = event.target.closest("button[data-open-app]");
  if (!button || button.disabled) return;
  const app = button.dataset.openApp;
  const name = button.querySelector("span").textContent;
  const status = $("deck-launch-status");
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  status.textContent = `Opening ${name} on this Mac…`;
  try {
    const response = await fetch(`/api/open-app/${encodeURIComponent(app)}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    status.textContent = response.ok ? `Opened ${name} on this Mac.`
      : response.status === 501 ? "App shortcuts are available when Your Turn runs on macOS."
        : `Could not open ${name} on this Mac. Check its app or command in launcher.toml, then try again.`;
  } catch {
    status.textContent = `Could not reach the Mac to open ${name}. Try again when it is online.`;
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
  }
});
$("deck-carousel").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-step]");
  if (button) cycleDeckChat(Number(button.dataset.step));
});

function deckReviewButton(chat, kind, className) {
  if (!deckCanReview(chat, kind)) return null;
  const button = el("button", className, kind === "new" ? "Mark reviewed" : "Dismiss");
  button.type = "button";
  button.dataset.review = chatKey(chat);
  button.setAttribute("aria-label", `${kind === "new" ? "Mark reviewed" : kind === "working" ? "Set aside quiet chat" : "Dismiss reminder for"} ${chatName(chat)}`);
  button.title = kind === "new" ? "Move this result to Earlier"
    : kind === "working" ? "Move this quiet chat to Earlier; it comes back if the agent writes again"
    : "Hide this reminder; the request stays open in its agent";
  return button;
}

function reviewDeckChat(key) {
  if (!deckView || threadId) return;
  const chat = deckData?.find((item) => chatKey(item) === key);
  if (!chat || deckDismissals.has(key)) return;
  const kind = deckSectionOf(chat);
  if (!deckCanReview(chat, kind)) { renderDeck(deckData); return; }
  const local = kind !== "waiting";
  const previous = local ? deckReviewStamp(chat) : shared.dismissed[key] || null;
  if (local) setDeckReview(key, deckReviewMark(chat, kind));
  else saveShared({ dismissed: { [key]: chat.attention_key } });
  const row = [...$("deck-groups").querySelectorAll("[data-select]")].find((node) => node.dataset.select === key);
  const focused = row?.parentElement.contains(document.activeElement) || [...$("deck-feature").children].some((card) => card.dataset.key === key && card.contains(document.activeElement));
  let undone = false;
  const finish = () => {
    if (undone) return;
    deckDismissals.delete(key);
    renderShared();
    if (focused) ([...$("deck-groups").querySelectorAll(".deck-row")].find((node) => node.getClientRects().length) || $("deck-fleet").querySelector("button"))?.focus({ preventScroll: true });
  };
  if (row && !calm.matches) {
    const item = row.parentElement;
    const animation = item.animate([{ height: `${item.offsetHeight}px`, opacity: 1 }, { height: "0px", opacity: 0 }], { duration: 180, easing: "ease-out" });
    deckDismissals.set(key, animation);
    animation.finished.then(finish, finish);
  } else finish();
  const undo = el("button", "button", "Undo");
  undo.type = "button";
  undo.addEventListener("click", () => {
    hideUndo();
    undone = true;
    deckDismissals.get(key)?.cancel();
    deckDismissals.delete(key);
    if (local) setDeckReview(key, previous);
    else saveShared({ dismissed: { [key]: previous } });
    deckSelected = key;
    deckPinned = true;
    deckFilter = "";
    renderShared();
    $("deck-groups").querySelector(`[data-select="${CSS.escape(key)}"]`)?.focus({ preventScroll: true });
  });
  const toast = el("div", "undo-toast-body");
  toast.append(el("span", "", `${kind === "new" ? "Reviewed" : kind === "working" ? "Set aside" : "Reminder dismissed"}: ${chatName(chat)}`), undo);
  $("undo-toast").replaceChildren(toast);
  restartUndoTimer();
}

function renderDeckTelemetry() {
  if (!deckData) return;
  const groups = deckGroups(deckData);
  document.body.dataset.deckUrgent = String(deckUrgent(groups.get("waiting").map(waitingSince)));
  const metrics = deckTelemetry(deckData, deckData.filter((chat) => chat.status === "working"), groups.get("waiting").map(waitingSince));
  for (const button of $("deck-slots").children) {
    const metric = metrics.find((item) => item.id === deckSlots[Number(button.dataset.slot) - 1]) || metrics[Number(button.dataset.slot) - 1];
    button.dataset.metric = metric.id;
    button.dataset.tone = metric.tone;
    button.title = `${metric.note} Click to switch metric.`;
    button.setAttribute("aria-label", `${metric.label} ${metric.value}. Switch telemetry metric.`);
    const reading = el("span", "deck-telemetry-reading");
    const cycle = el("span", "deck-cycle", "↻");
    cycle.setAttribute("aria-hidden", "true");
    reading.append(el("strong", "", metric.value), cycle);
    button.replaceChildren(el("span", "", metric.label), reading);
  }
}

$("deck-slots").addEventListener("click", (event) => {
  const button = event.target.closest("[data-slot]");
  if (!button || !deckData) return;
  const modes = ["claude", "codex", "burn", "peak", "wait", "today"];
  const slot = Number(button.dataset.slot);
  deckSlots[slot - 1] = modes[(modes.indexOf(button.dataset.metric) + 1) % modes.length];
  try { localStorage.setItem(`your-turn.deck.slot${slot}`, deckSlots[slot - 1]); } catch { /* Keep this page's selection. */ }
  renderDeckTelemetry();
});

function deckSince(chat, kind) {
  return kind === "working" ? chat.working_since : kind === "waiting" ? waitingSince(chat)
    : chat.turn_ended_at || chat.updated_at;
}

function deckAgent(chat) {
  return el("span", "deck-agent", DECK_AGENTS[chat.harness] || appName(chat));
}

function deckRepo(chat) {
  const repo = el("span", "deck-repo");
  repo.title = chat.cwd || projectName(chat);
  repo.append(icon("i-workspace"), el("span", "", projectName(chat)));
  return repo;
}

function updateDeckTimer(node) {
  const duration = deckElapsed(node.dataset.lcd) || "—";
  node.setAttribute("aria-label", `Elapsed time: ${duration}`);
  node.replaceChildren(...duration.split(" ").map((part) => {
    const unit = el("span", "", part);
    unit.setAttribute("aria-hidden", "true");
    return unit;
  }));
}

function deckTimer(since, className = "deck-timer") {
  const timer = el("span", className);
  timer.setAttribute("role", "timer");
  timer.setAttribute("aria-live", "off");
  if (since) timer.dataset.lcd = since;
  updateDeckTimer(timer);
  return timer;
}

// "Quiet 18h", refreshed in place by the 30-second ticker like the Inbox's quiet tag.
function deckQuietAge(chat, className) {
  const age = el("span", className, `Quiet ${quietFor(chat)}`);
  age.dataset.quietAt = chat.updated_at;
  return age;
}

function deckMini(chat, kind) {
  const item = el("li");
  const button = el("button", "deck-mini");
  button.type = "button";
  button.dataset.select = chatKey(chat);
  button.dataset.kind = kind;
  const quiet = deckQuiet(chat, kind);
  button.dataset.quiet = String(quiet);
  button.setAttribute("aria-label", `Focus ${chatName(chat)}, ${quiet ? "quiet, " : ""}${appName(chat)}, ${projectName(chat)}`);
  const head = el("span", "deck-mini-head");
  const title = el("span", "deck-mini-title", chatName(chat));
  title.title = chatName(chat);
  head.append(icon(SECTION_ICONS[kind]), title);
  const meta = el("span", "deck-mini-meta");
  const delegated = deckChildren.get(chatKey(chat))?.length;
  meta.append(deckAgent(chat), deckRepo(chat), ...(delegated ? [el("span", "deck-mini-delegates", `+${delegated}`)] : []), quiet ? deckQuietAge(chat, "deck-mini-time") : deckTimer(deckSince(chat, kind), "deck-mini-time"));
  const fill = contextFill(chat.context_used, contextSize(chat));
  const readout = el("span", "deck-mini-readout");
  // The bar is the reading; the percent stays for screen readers and the figures for hover.
  const context = el("span", "deck-mini-context sr-only", fill ? `CTX ${fill.percent}%` : "CTX unknown");
  readout.title = fill ? `CTX ${fill.percent}% · ${tokenCount(chat.context_used, true)} / ${tokenCount(contextSize(chat), true)}` : "Context window not reported";
  const gauge = el("span", `deck-mini-gauge${fill ? "" : " deck-mini-standby"}`);
  gauge.setAttribute("aria-hidden", "true");
  gauge.dataset.tone = fillTone(fill?.percent, "green");
  for (let i = 0; i < 10; i++) {
    const block = el("span");
    block.style.setProperty("--fill", `${fill ? Math.max(0, Math.min(100, (fill.percent - i * 10) * 10)) : 0}%`);
    gauge.append(block);
  }
  readout.append(gauge, context);
  button.append(head, meta, readout);
  item.append(button);
  const review = deckReviewButton(chat, kind, "deck-mini-review");
  if (review) item.append(review);
  return item;
}

function renderDeckMatrix(groups, selected) {
  const matrix = $("deck-matrix");
  const grid = $("deck-mini-grid");
  // The dock lists every other queued chat, Needs you first, so the hero never has to scroll for them.
  const entries = deckEntries(groups).filter(({ chat }) => chatKey(chat) !== deckSelected);
  const usage = deckUsage(deckData);
  const slot = $("deck-usage");
  slot.hidden = !usage;
  if (usage && slot.dataset.sig !== usage.outerHTML) { slot.dataset.sig = usage.outerHTML; slot.replaceChildren(...usage.children); }
  // Plan usage keeps the dock visible even when no other chat is queued.
  matrix.hidden = !selected || (!entries.length && !usage);
  grid.hidden = $("deck-matrix-title").hidden = !entries.length;
  $("deck-stage").dataset.queueEmpty = String(matrix.hidden);
  $("deck-matrix-title").textContent = deckFilter ? `${DECK_NAMES[deckFilter]} QUEUE` : "QUEUE";
  const focused = grid.contains(document.activeElement) && document.activeElement.dataset.select;
  // Category separators: each status run opens with its name and count, so the list reads as groups, not a stream.
  // A filtered queue is one category and its title already names it.
  // Counts include the chat open in the hero, so they match the fleet strip's totals.
  const counts = {};
  for (const { kind } of deckEntries(groups)) counts[kind] = (counts[kind] || 0) + 1;
  const cards = entries.flatMap(({ chat, kind }, i) => {
    const card = deckMini(chat, kind);
    if (deckFilter || entries[i - 1]?.kind === kind) return [card];
    const separator = el("li", "deck-mini-group");
    separator.dataset.kind = kind;
    const heading = el("h3", "", DECK_NAMES[kind]);
    heading.append(el("span", "", String(counts[kind])));
    separator.append(heading);
    return [separator, card];
  });
  const signature = cards.map((card) => card.outerHTML).join("");
  if (grid.dataset.sig !== signature) {
    const scroll = grid.scrollTop;
    grid.dataset.sig = signature;
    grid.replaceChildren(...cards);
    grid.scrollTop = scroll;
    if (focused) (grid.querySelector(`[data-select="${CSS.escape(focused)}"]`) || $("deck-feature").querySelector("a"))?.focus({ preventScroll: true });
  }
}

// A queue with more below its fold fades out at the bottom, so a half-visible row reads as "scroll for more".
function markDeckQueueMore() {
  const grid = $("deck-mini-grid");
  grid.dataset.more = String(grid.scrollTop + grid.clientHeight < grid.scrollHeight - 1);
}
$("deck-mini-grid").addEventListener("scroll", markDeckQueueMore, { passive: true });

$("deck-feature").addEventListener("keydown", (event) => {
  const supporting = event.target.closest?.(".deck-supporting[open]");
  if (event.key !== "Escape" || !supporting) return;
  event.preventDefault();
  supporting.open = false;
  supporting.querySelector("summary").focus();
});

$("deck-mini-grid").addEventListener("click", (event) => {
  const review = event.target.closest("[data-review]");
  if (review) { reviewDeckChat(review.dataset.review); return; }
  const button = event.target.closest("[data-select]");
  if (!button) return;
  selectDeckChat(button.dataset.select);
  $("deck-feature").querySelector("a")?.focus({ preventScroll: true });
});

function deckTerminal(chat, { allEvents = false } = {}) {
  const state = deckTerminalState(chat, $("connection").dataset.state === "live");
  const events = deckTerminalRows(state.events, allEvents ? null : undefined);
  const terminal = el("div", "deck-terminal");
  terminal.dataset.live = String(state.live);
  terminal.dataset.stream = JSON.stringify(state.events.length ? state.events : [state.fallback]);
  const header = el("div", "deck-terminal-header");
  const status = el("span", "deck-terminal-state");
  const dot = el("span", "deck-terminal-dot");
  dot.setAttribute("aria-hidden", "true");
  status.append(dot, document.createTextNode(state.label));
  header.append(status, el("span", "deck-terminal-source", "RECORDED LOG"));
  terminal.append(header);
  const body = el("div", "deck-terminal-body");
  terminal.append(body);
  if (events.length) {
    const log = el("ol", "deck-terminal-log");
    log.setAttribute("aria-label", "Latest recorded activity");
    events.forEach((event, index) => {
      const row = el("li");
      row.title = event.title;
      const time = el("span", "deck-terminal-time", event.pending ? "PENDING" : clock(event.at) || "LOG");
      const text = el("code", "deck-terminal-text", `${event.kind === "command" ? "$" : "›"} ${event.title}`);
      if (index === events.length - 1) {
        const cursor = el("span", "deck-terminal-cursor", "_");
        cursor.setAttribute("aria-hidden", "true");
        text.append(cursor);
      }
      row.append(time, text);
      log.append(row);
    });
    body.append(log);
  } else {
    body.append(el("p", "deck-terminal-idle", state.fallback));
  }
  return terminal;
}

function deckGoal(recap) {
  return (recap || "").match(/(?:^|\s)Goal:\s*(.+?)(?=\s+(?:Settled|Open|Done|Next|Status):|$)/s)?.[1].trim() || "";
}

function updateDeckPulse(node) {
  const age = Date.now() - Date.parse(node.dataset.pulseLast);
  const pulse = node.closest(".deck-pulse");
  const stalled = pulse.dataset.quiet === "true" || age > DECK_STALL_MS;
  pulse.dataset.stalled = String(stalled);
  const since = deckElapsed(node.dataset.pulseLast) || "—";
  node.textContent = stalled ? `NO ACTIVITY ${since}` : `LAST STEP ${since}`;
}

// Goal, 30 minutes of token activity, and changed files fill the readout beside a working terminal.
function deckVitals(chat) {
  const vitals = el("div", "deck-vitals");
  const goal = deckGoal(chat.recap);
  if (goal) {
    const row = el("p", "deck-goal");
    row.title = goal;
    row.append(el("span", "deck-vital-label", "GOAL"), document.createTextNode(goal));
    vitals.append(row);
  }
  const minutes = minuteBuckets(chat.usage_minutes, 30);
  const peak = Math.max(...minutes);
  const pulse = el("div", "deck-pulse");
  pulse.dataset.quiet = String(Boolean(chat.quiet));
  const head = el("p", "deck-pulse-head");
  const last = el("span", "deck-pulse-last");
  last.dataset.pulseLast = chat.activity_log?.at(-1)?.at || chat.updated_at;
  head.append(el("span", "deck-vital-label", "PULSE · 30M"), last);
  const chart = el("div", "deck-pulse-chart");
  chart.setAttribute("aria-hidden", "true");
  for (const tokens of minutes) {
    const bar = el("span", "deck-pulse-bar");
    if (tokens) bar.style.setProperty("--h", `${Math.max(12, Math.round(Math.sqrt(tokens / peak) * 100))}%`);
    chart.append(bar);
  }
  pulse.append(head, chart);
  vitals.append(pulse);
  updateDeckPulse(last);
  const files = [...new Set(chat.changed_files || [])];
  if (files.length) {
    const row = el("p", "deck-files");
    row.title = files.join("\n");
    row.append(el("span", "deck-vital-label", `${files.length} ${files.length === 1 ? "FILE" : "FILES"}`),
      el("code", "", files.slice(-2).map((path) => path.split("/").pop()).join(" · ")));
    vitals.append(row);
  }
  return vitals;
}

// Tokens per minute over the last `count` minutes, oldest first; the last slot is the current minute.
function minuteBuckets(samples, count, now = Date.now()) {
  const minutes = Array(count).fill(0);
  const current = Math.floor(now / 60_000);
  for (const [at, tokens] of samples || []) {
    const slot = count - 1 - (current - Math.floor(Date.parse(at) / 60_000));
    if (slot >= 0 && slot < count) minutes[slot] += tokens;
  }
  return minutes;
}

// One instrument for every trace: bars scaled to the peak (or `max`), newest on the right.
// The head carries the reading in text, so the chart itself stays decorative for screen readers.
function deckTrace(label, values, { reading = "", max, tone = () => "", title = () => "", live = false } = {}) {
  const block = el("div", "deck-trace");
  const head = el("p", "deck-trace-head");
  head.append(el("span", "deck-vital-label", label), el("span", "deck-trace-reading", reading));
  const chart = el("div", "deck-trace-chart");
  chart.setAttribute("aria-hidden", "true");
  chart.dataset.live = String(live);
  const peak = max ?? Math.max(1, ...values);
  values.forEach((value, index) => {
    const bar = el("span", "deck-trace-bar");
    bar.style.setProperty("--h", `${value > 0 ? Math.max(4, Math.min(100, Math.round(value / peak * 100))) : 0}%`);
    if (tone(value, index)) bar.dataset.tone = tone(value, index);
    if (title(value, index)) bar.title = title(value, index);
    chart.append(bar);
  });
  block.append(head, chart);
  return block;
}

// Real telemetry for Supporting evidence: lap times (purple best, live lap animated),
// context at each lap's end, and the chat's token flow.
function deckTraces(chat, kind, { supporting = false } = {}) {
  const traces = [];
  // A trace needs two samples everywhere: a single lap's "best" and "avg" are the same number over one full bar,
  // which compares nothing (and contradicted the "does not record per-step times" note beside it).
  const minimumSamples = 2;
  const laps = (chat.laps || []).filter((lap) => lapSeconds(lap) > 0);
  const live = laps.length > 0 && !laps.at(-1).ended_at;
  if (laps.length >= minimumSamples) {
    const seconds = laps.map(lapSeconds);
    const finished = seconds.filter((_, i) => laps[i].ended_at);
    const best = finished.length ? Math.min(...finished) : 0;
    traces.push(deckTrace(`LAPS · ${laps.length}`, seconds, {
      reading: finished.length ? `Best ${lapClock(best)} · avg ${lapClock(mean(finished))}` : "",
      tone: (value, i) => !laps[i].ended_at ? "live" : value === best ? "best" : "",
      title: (value, i) => `Turn ${laps[i].turn}: ${lapClock(value)}${laps[i].ended_at ? "" : " so far"}`,
      live,
    }));
  }
  const size = contextSize(chat);
  const filled = (chat.laps || []).filter((lap) => lap.context > 0);
  if (size && filled.length >= minimumSamples) {
    const percents = filled.map((lap) => Math.min(100, lap.context / size * 100));
    const growth = percents.slice(1).map((value, i) => value - percents[i]).filter((value) => value > 0);
    traces.push(deckTrace("CTX / LAP", percents, {
      max: 100,
      reading: growth.length ? `+${mean(growth).toFixed(1)}% per lap` : "",
      tone: (value) => fillTone(value),
      title: (value, i) => `Turn ${filled[i].turn}: ${Math.round(value)}% of the context window`,
    }));
  }
  if (kind !== "working" || supporting) {
    const minutes = minuteBuckets(chat.usage_minutes, 60);
    const total = minutes.reduce((sum, value) => sum + value, 0);
    if (total) traces.push(deckTrace("TOKENS · 60M", minutes, { reading: `${tokenCount(total, true)} tokens` }));
  }
  if (!traces.length) return null;
  const band = el("div", "deck-traces");
  band.append(...traces);
  return band;
}

const DECK_SECTORS = [["think", "THINK"], ["run", "RUN"], ["edit", "EDIT"]];
// 5% segments: the 75% and 90% marks land on segment edges.
const DECK_CTX_SEGMENTS = 20;

function lapSeconds(lap) {
  const start = Date.parse(lap.started_at);
  const end = lap.ended_at ? Date.parse(lap.ended_at) : Date.now();
  return start && end > start ? (end - start) / 1000 : 0;
}

function lapClock(seconds) {
  const s = Math.round(Math.abs(seconds));
  const mm = String(Math.floor((s % 3600) / 60)), ss = String(s % 60).padStart(2, "0");
  return s >= 3600 ? `${Math.floor(s / 3600)}:${mm.padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

const mean = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;

// What the chat changed, newest first: the files to review before acting on its handoff.
const DECK_FILES_SHOWN = 12;
function deckChangedFiles(chat) {
  const files = [...new Set(chat.changed_files || [])].reverse();
  if (!files.length) return null;
  const root = chat.cwd ? `${chat.cwd.replace(/\/$/, "")}/` : "";
  const block = el("section", "deck-files-panel");
  block.setAttribute("aria-label", "Changed files");
  const head = el("p", "deck-trace-head");
  head.append(el("span", "deck-vital-label", "CHANGED FILES"), el("span", "deck-trace-reading", String(files.length)));
  const list = el("ol", "deck-files-list");
  for (const path of files.slice(0, DECK_FILES_SHOWN)) {
    const relative = root && path.startsWith(root) ? path.slice(root.length) : path;
    const slash = relative.lastIndexOf("/");
    const item = el("li");
    item.title = relative;
    // The directory shortens from its start ("…/ingestion/"), so the part next to the file name stays readable;
    // the inner left-to-right span keeps the path's own order inside the right-to-left box that does it.
    if (slash > 0) {
      const dir = el("span", "deck-files-dir");
      const text = el("span", "", relative.slice(0, slash + 1));
      text.dir = "ltr";
      dir.append(text);
      item.append(dir);
    }
    item.append(el("span", "deck-files-name", relative.slice(slash + 1)));
    list.append(item);
  }
  if (files.length > DECK_FILES_SHOWN) list.append(el("li", "deck-files-more", `+${files.length - DECK_FILES_SHOWN} more in the chat`));
  block.append(head, list);
  return block;
}

// Plan usage per agent account: the 5-hour session and the weekly window, from the newest report each
// agent made (Codex in its transcripts, Claude through the opt-in status line capture).
const USAGE_WINDOWS = [[300, "SESSION 5H"], [10_080, "WEEKLY 7D"]];
const USAGE_STALE_MS = 15 * 60_000;
function deckUsage(chats, now = Date.now()) {
  const providers = ["claude", "codex"].map((harness) => {
    const own = (chats || []).filter((chat) => chat.harness === harness);
    return { harness, at: own.map((chat) => chat.rate_limits_at || "").sort().at(-1) || "", windows: latestQuota(own, now) };
  }).filter(({ windows }) => windows.length);
  const cards = USAGE_WINDOWS.map(([minutes, label]) => {
    const rows = providers.map((provider) => [provider, provider.windows.find((window) => window.window_minutes === minutes)])
      .filter(([, window]) => window);
    if (!rows.length) return null;
    const card = el("div", "deck-usage-card");
    const head = el("p", "deck-trace-head");
    head.append(el("span", "deck-vital-label", label));
    card.append(head);
    for (const [{ harness, at }, window] of rows) {
      const percent = Math.round(window.used_percent);
      const row = el("div", "deck-usage-row");
      row.dataset.tone = fillTone(percent);
      const gauge = el("span", "deck-mini-gauge");
      gauge.dataset.tone = row.dataset.tone;
      gauge.setAttribute("aria-hidden", "true");
      for (let i = 0; i < 10; i++) {
        const block = el("span");
        block.style.setProperty("--fill", `${Math.max(0, Math.min(100, (percent - i * 10) * 10))}%`);
        gauge.append(block);
      }
      const notes = [window.resets_at ? `Resets in ${untilShort(window.resets_at, now)}` : ""];
      const age = now - Date.parse(at);
      // Claude's capture only updates while a session runs: say when a reading is old.
      if (age > USAGE_STALE_MS) notes.push(`As of ${ago(at)}`);
      row.append(el("span", "deck-usage-name", DECK_AGENTS[harness] || appName({ harness })), el("strong", "deck-usage-percent", `${percent}%`), gauge,
        el("span", "deck-usage-note", notes.filter(Boolean).join(" · ")));
      row.setAttribute("aria-label", `${appName({ harness })} ${label.toLowerCase()}: ${percent}% used${notes.filter(Boolean).length ? `, ${notes.filter(Boolean).join(", ").toLowerCase()}` : ""}`);
      card.append(row);
    }
    return card;
  }).filter(Boolean);
  if (!cards.length) return null;
  const block = el("section");
  block.append(...cards);
  return block;
}

// The run's setup, like a car's: model, reasoning effort and how much input the prompt cache served.
function deckSetup(chat) {
  const parts = [chat.model?.replace(/^claude-/, ""), chat.reasoning_effort?.toLowerCase(),
    Number.isFinite(chat.cache_hit) ? `cache ${chat.cache_hit}%` : ""].filter(Boolean);
  if (!parts.length) return null;
  const row = el("span", "deck-setup", parts.join(" · "));
  row.title = "Model and reasoning effort of the latest turn; cache is the cached share of this session's input tokens.";
  return row;
}

// Tool use (built-in and MCP): calls per tool as ranked bars; a tool called in the last minute of a live run flows.
function deckTools(chat) {
  const tools = chat.tool_calls || [];
  if (!tools.length) return null;
  const peak = Math.max(...tools.map((tool) => tool.count));
  const block = el("div", "deck-tools");
  const head = el("p", "deck-trace-head");
  const total = tools.reduce((sum, tool) => sum + tool.count, 0);
  head.append(el("span", "deck-vital-label", "TOOLS"), el("span", "deck-trace-reading", `${total} ${total === 1 ? "call" : "calls"}`));
  const list = el("ol", "deck-tools-list");
  list.setAttribute("aria-label", "Tool calls by tool");
  for (const tool of tools) {
    const [server, name] = tool.name.includes(" · ") ? tool.name.split(" · ") : ["", tool.name];
    const item = el("li");
    item.title = `${tool.name}: ${tool.count} ${tool.count === 1 ? "call" : "calls"}`;
    if (chat.status === "working" && !chat.quiet && Date.now() - Date.parse(tool.last_at) < 60_000) item.dataset.live = "true";
    const label = el("span", "deck-tools-name", name);
    if (server) label.append(el("span", "deck-tools-server", server));
    const bar = el("span", "deck-tools-bar");
    bar.setAttribute("aria-hidden", "true");
    bar.style.setProperty("--w", `${Math.round(tool.count / peak * 100)}%`);
    item.append(label, bar, el("span", "deck-tools-count", String(tool.count)));
    list.append(item);
  }
  block.append(head, list);
  return block;
}

// Turns left before the context fills: context left over this chat's average growth per finished turn.
function deckRunway(chat) {
  const laps = chat.laps || [];
  const done = laps.filter((lap) => lap !== laps.at(-1) && ["done", "waiting"].includes(lap.status) && lapSeconds(lap) > 0);
  const growth = done.slice(1).map((lap, i) => lap.context - done[i].context).filter((value, i) => value > 0 && done[i].context > 0).slice(-6);
  const left = contextSize(chat) - chat.context_used;
  return growth.length >= 2 && left > 0 ? Math.floor(left / mean(growth)) : null;
}

// The latest turn against this chat's finished turns' average; null when there is no fair comparison.
function deckLapDelta(chat) {
  const laps = chat.laps || [];
  const current = laps.at(-1);
  // Same bar as deckLap: without per-step times (Cursor's minute stamps) lap times are not meaningful.
  if (!current?.started_at || !laps.some((lap) => Object.keys(lap.sectors || {}).length)) return null;
  const live = !current.ended_at;
  const done = laps.filter((lap) => lap !== current && ["done", "waiting"].includes(lap.status) && lapSeconds(lap) > 0);
  // A quiet lap is not a slow lap: its running delta would only measure the silence.
  if (!done.length || (live && chat.quiet)) return null;
  const average = mean(done.map(lapSeconds));
  return { delta: lapSeconds(current) - average, average, count: done.length, live };
}

// F1 delta block: the sign and size against this chat's own average. Only a clearly slower turn takes colour.
function deckDeltaMark(lap, className) {
  const mark = el("span", className, `${lap.delta >= 0 ? "+" : "−"}${lapClock(lap.delta)}`);
  const ratio = lap.average > 0 ? lap.delta / lap.average : 0;
  mark.dataset.tone = ratio > .5 ? "red" : ratio > .2 ? "amber" : lap.delta > 0 ? "slower" : "faster";
  mark.title = `${lap.live ? "So far, compared" : "Compared"} with this chat's average turn: ${lapClock(lap.average)} over ${lap.count}`;
  return mark;
}

// One dominant phase code per card, like a gear indicator. FAIL and IDLE are the exceptions that outrank the group.
const DECK_PHASES = { ack: "Needs you", run: "Working", done: "Ready", idle: "Quiet", fail: "Checks failed" };
function deckPhase(chat, kind) {
  if (chat.check_state === "failed") return "fail";
  if (deckQuiet(chat, kind)) return "idle";
  return { waiting: "ack", working: "run", new: "done" }[kind];
}

// The latest turn against this chat's finished turns: lap time and delta, and where the time went.
function deckLap(chat) {
  const laps = chat.laps || [];
  const current = laps.at(-1);
  // Sectors need per-step times; a source without them (Cursor's minute stamps) has no meaningful laps either.
  if (!current?.started_at || !laps.some((lap) => Object.keys(lap.sectors || {}).length)) return null;
  const live = !current.ended_at;
  const done = laps.filter((lap) => lap !== current && ["done", "waiting"].includes(lap.status) && lapSeconds(lap) > 0);
  const block = el("div", "deck-lap");
  const head = el("p", "deck-lap-head");
  head.append(el("span", "deck-vital-label", `LAP ${current.turn}`));
  if (!live) head.append(el("span", "deck-lap-time", lapClock(lapSeconds(current))));
  const lapDelta = deckLapDelta(chat);
  if (lapDelta) head.append(deckDeltaMark(lapDelta, "deck-lap-delta"));
  block.append(head);
  if (DECK_SECTORS.some(([name]) => current.sectors?.[name])) {
    const sectors = el("div", "deck-sectors");
    sectors.setAttribute("aria-label", "Where this turn's time went");
    for (const [name, label] of DECK_SECTORS) {
      const value = current.sectors?.[name] || 0;
      const history = done.map((lap) => lap.sectors?.[name] || 0);
      const cell = el("span", "deck-sector");
      cell.append(el("span", "", label), el("strong", "", lapClock(value)));
      // Like F1 sectors: colored once the lap is complete, purple for this chat's best.
      if (!live && history.length >= 2) {
        cell.dataset.tone = value <= Math.min(...history) ? "best" : value <= mean(history) ? "good" : "slow";
        cell.title = `${label}: ${lapClock(value)}; this chat's average ${lapClock(mean(history))}`;
      }
      sectors.append(cell);
    }
    block.append(sectors);
  }
  return block;
}

function deckHero(chat, kind) {
  const hero = el("a", "deck-hero");
  hero.href = `/?thread=${encodeURIComponent(chatKey(chat))}&view=deck`;
  hero.setAttribute("aria-label", `Open ${chatName(chat)}`);
  hero.dataset.key = chatKey(chat);
  hero.dataset.kind = kind;
  const left = el("div", "deck-hero-left");
  const identity = el("div", "deck-identity");
  const badge = el("span", "deck-icon");
  badge.append(icon(SECTION_ICONS[kind]));
  const heading = el("div", "deck-heading");
  const title = el("h2", "deck-title", chatName(chat));
  title.title = chatName(chat);
  heading.append(title);
  const meta = el("div", "deck-meta");
  // Model, effort and cache sit with the agent: a quick read of what is driving this run.
  meta.append(...[deckAgent(chat), deckSetup(chat)].filter(Boolean));
  heading.append(meta);
  identity.append(badge, heading);
  const cardHeader = el("div", "deck-card-header");
  cardHeader.append(identity);
  left.append(cardHeader);
  const telemetry = el("div", "deck-evidence");
  telemetry.setAttribute("aria-label", "Recorded chat telemetry");
  // The same check reading as the inbox and Subtasks: a worker its orchestrator verified later is not unchecked.
  const checkState = effectiveCheckState(chat, deckParents.get(chatKey(chat)));
  const check = el("span", "", `CHECKS ${checkState || "—"}`);
  check.dataset.state = checkState || "unknown";
  if (!checkState) check.title = "Checks not reported";
  const count = (label, n) => {
    const item = el("span", "", `${label} ${n}`);
    if (!n) item.dataset.zero = "true";
    return item;
  };
  telemetry.append(check, count("FILES", chat.changed_files?.length || 0),
    count("DECISIONS", chat.decisions?.filter((d) => d.chosen !== null).length || 0));
  const handoff = el("div", "deck-handoff");
  // The next line is labelled with its step type (APPROVE, ANSWER, RUN), so the verb is read before the sentence.
  const nextLabel = chat.question ? "Answer" : NEXT_LABEL[chat.next_kind] || "Next";
  const line = (label, value, key = label.toLowerCase()) => {
    const row = el("p");
    row.dataset.label = key;
    row.title = `${label}: ${value}`;
    row.append(el("strong", "", `${label}: `), document.createTextNode(value));
    return row;
  };
  if (kind === "working") {
    handoff.append(deckTerminal(chat));
  } else {
    const text = deckHandoffText(chat, kind);
    if (kind === "waiting") handoff.append(...[line(nextLabel, text.next, "next"), text.outcome && line("Outcome", text.outcome)].filter(Boolean));
    // "No further action requested" restates the DONE code, so a finished chat with no step shows only its outcome.
    else handoff.append(...[line("Outcome", text.outcome), chat.next_kind !== "none" && line(nextLabel, text.next, "next")].filter(Boolean));
  }
  left.append(handoff, telemetry);
  // Detailed telemetry is moved into Supporting evidence below.
  const traces = deckTraces(chat, kind);
  if (kind !== "working") {
    const files = deckChangedFiles(chat);
    if (files) left.append(files);
    // Say what this source does not record instead of leaving a silent gap, but only when it truly records
    // neither: a source with step times or token usage may simply not have enough laps yet.
    if (!traces && !(chat.laps || []).some((lap) => Object.keys(lap.sectors || {}).length) && !(chat.usage_minutes || []).length) {
      left.append(el("p", "deck-unreported", `${appName(chat)} does not record per-step times or token usage, so laps and token flow are not shown.`));
    }
  }
  const right = el("div", "deck-readout");
  const quiet = deckQuiet(chat, kind);
  // Quiet, the running clock stops meaning progress: show how long nothing was recorded instead.
  const timer = deckTimer(quiet ? chat.updated_at : deckSince(chat, kind));
  // The phase code is the card's dominant reading (gear indicator); the full name is there for screen readers and hover.
  const phase = deckPhase(chat, kind);
  const status = el("span", "deck-status", phase.toUpperCase());
  status.append(el("span", "sr-only", ` · ${DECK_PHASES[phase]}`));
  status.title = DECK_PHASES[phase];
  status.dataset.kind = kind;
  status.dataset.phase = phase;
  if (quiet) status.dataset.quiet = "true";
  // The repo follows the status so the line reads as one phrase: "RUN your-turn".
  heading.prepend(status, deckRepo(chat));
  const time = el("div", "deck-header-time");
  time.append(el("span", "deck-time-label", kind === "waiting" ? "WAITING" : kind === "working" ? quiet ? "NO ACTIVITY FOR" : "ELAPSED" : "SINCE RESULT"), timer);
  const lapDelta = deckLapDelta(chat);
  // The delta is a call to act on a run that is going long; on a finished or waiting chat it is history, so it stays
  // with the laps in Supporting evidence.
  if (lapDelta && kind === "working") time.append(deckDeltaMark(lapDelta, "deck-header-delta"));
  cardHeader.append(time);
  const size = contextSize(chat);
  const fill = contextFill(chat.context_used, size);
  const context = el("div", "deck-context");
  const header = el("p", "deck-context-header");
  if (fill) {
    context.dataset.tone = fillTone(fill.percent, "green");
    // The figures sit in their own span: the card face shows percent + bar, Supporting evidence the exact tokens.
    const tokens = el("span", "deck-context-tokens", "CTX ");
    tokens.append(el("span", "deck-context-detail", `${tokenCount(chat.context_used, true)} / ${tokenCount(size, true)}`));
    header.append(el("span", "deck-percent", `${fill.percent}%`), tokens);
    context.title = `${tokenCount(chat.context_used, true)} / ${tokenCount(size, true)} tokens`;
    const gauge = el("div", "deck-gauge");
    gauge.setAttribute("role", "meter");
    gauge.setAttribute("aria-label", "Context window");
    gauge.setAttribute("aria-valuemin", "0");
    gauge.setAttribute("aria-valuemax", "100");
    gauge.setAttribute("aria-valuenow", String(fill.percent));
    const left = Math.max(0, size - chat.context_used);
    const runway = deckRunway(chat);
    gauge.setAttribute("aria-valuetext", `${fill.percent}% used, ${tokenCount(left, true)} tokens left${runway === null ? "" : `, about ${runway} turns`}`);
    // Bullet-graph style: 75% and 90% fall on segment edges, so the warning zones tint the track
    // and only the part of the bar inside a zone takes its color; no tick marks are needed.
    const step = 100 / DECK_CTX_SEGMENTS;
    for (let i = 0; i < DECK_CTX_SEGMENTS; i++) {
      const block = el("span", "deck-gauge-block");
      block.style.setProperty("--fill", `${Math.max(0, Math.min(100, (fill.percent - i * step) / step * 100))}%`);
      const zone = fillTone(i * step);
      if (zone) block.dataset.zone = zone;
      block.append(el("span", "deck-gauge-fill"));
      gauge.append(block);
    }
    const remaining = el("p", "deck-context-left");
    remaining.append(el("span", "deck-context-tokens-left", `${tokenCount(left, true)} left`));
    if (runway !== null) {
      const turns = el("span", "deck-runway", runway < 1 ? "<1 turn" : `≈${runway > 99 ? "99+" : runway} ${runway === 1 ? "turn" : "turns"}`);
      turns.dataset.low = String(runway <= 3);
      turns.title = "Context left divided by this chat's average growth per turn; the agent may compact sooner.";
      remaining.append(turns);
    }
    context.append(header, gauge, remaining);
  } else {
    header.textContent = chat.context_used > 0 ? `CTX ${tokenCount(chat.context_used, true)} · window unknown` : "CTX not reported";
    header.title = "Context window not reported";
    const gauge = el("div", "deck-gauge deck-gauge-standby");
    gauge.setAttribute("aria-hidden", "true");
    gauge.append(...Array.from({ length: DECK_CTX_SEGMENTS }, () => el("span", "deck-gauge-block")));
    context.append(header, gauge, el("span", "deck-context-standby", "STANDBY · awaiting context telemetry"));
  }
  const lap = deckLap(chat);
  if (lap) right.append(lap);
  if (kind === "working") right.append(deckVitals(chat));
  const tools = deckTools(chat);
  if (tools) right.append(tools);
  // The context barometer spans the card's full width along its bottom edge.
  hero.append(left, right, context);
  return hero;
}

function deckRow(chat, kind) {
  const item = el("li");
  item.dataset.kind = kind;
  const historical = kind === "earlier";
  const row = el(historical ? "a" : "button", "deck-row");
  if (historical) {
    row.href = `/?thread=${encodeURIComponent(chatKey(chat))}&view=deck`;
    row.dataset.history = chatKey(chat);
  } else {
    row.type = "button";
    row.dataset.select = chatKey(chat);
    row.setAttribute("aria-pressed", String(chatKey(chat) === deckSelected));
  }
  row.dataset.kind = kind;
  const quiet = deckQuiet(chat, kind);
  row.dataset.quiet = String(quiet);
  row.setAttribute("aria-label", `${historical ? "Open historical chat" : "Select"} ${chatName(chat)}, ${quiet ? "quiet, " : ""}${DECK_AGENTS[chat.harness] || appName(chat)}, ${projectName(chat)}`);
  const marker = el("span", "deck-row-marker", historical ? "" : kind === "new" ? "✓" : "●");
  if (historical) marker.append(icon("i-turn"));
  marker.setAttribute("aria-hidden", "true");
  const title = el("span", "deck-row-title", chatName(chat));
  title.title = chatName(chat);
  const meta = el("span", "deck-row-meta");
  const since = deckSince(chat, kind);
  const age = el("span", "deck-age", since ? ago(since, "") : "—");
  if (since) { age.dataset.ago = since; age.dataset.short = ""; }
  const chevron = icon("i-chevron");
  chevron.classList.add("deck-row-chevron");
  const delegated = deckChildren.get(chatKey(chat))?.length;
  meta.append(deckAgent(chat), deckRepo(chat), ...(delegated ? [el("span", "deck-mini-delegates", `+${delegated}`)] : []), quiet ? deckQuietAge(chat, "deck-age") : age, chevron);
  row.append(marker, title, meta);
  item.append(row);
  const review = deckReviewButton(chat, kind, "deck-row-review");
  if (review) item.append(review);
  return item;
}

function renderDeck(chats) {
  deckData = chats;
  if (deckGesture || deckScrolling || deckDismissals.size) return;
  const groups = deckGroups(chats);
  const kinds = ["waiting", "working", "new"];
  const fallback = deckFallback(Object.fromEntries([...groups].map(([kind, list]) => [kind, list.length])));
  renderDeckFleet(groups);
  $("deck-view").dataset.layout = deckLayout;
  for (const button of $("deck-layout").children) button.setAttribute("aria-pressed", String(button.dataset.layout === deckLayout));
  renderDeckTelemetry();
  const active = deckEntries(groups);
  const selected = (deckPinned && active.find(({ chat }) => chatKey(chat) === deckSelected)) || active[0];
  const feature = $("deck-feature");
  const carousel = $("deck-carousel");
  const focusedCarouselStep = carousel.contains(document.activeElement) ? document.activeElement.dataset.step : null;
  if (selected) {
    const selectionChanged = feature.dataset.selected !== chatKey(selected.chat);
    const presentationChanged = selectionChanged || feature.firstElementChild?.dataset.kind !== selected.kind;
    const previousBlocks = new Map([...feature.querySelectorAll(".deck-hero")].map((hero) => [hero.dataset.key, [...hero.querySelectorAll(".deck-gauge-block")]]));
    const previousTerminals = new Map([...feature.querySelectorAll(".deck-hero")].map((hero) => [hero.dataset.key, hero.querySelector(".deck-terminal")]));
    const previousCharts = new Map([...feature.querySelectorAll(".deck-hero")].map((hero) => [hero.dataset.key, hero.querySelector(".deck-pulse-chart")]));
    const focusedKey = document.activeElement.closest(".deck-card")?.dataset.key;
    const focusedReview = document.activeElement.hasAttribute("data-review");
    const focusedSupporting = document.activeElement.matches(".deck-supporting > summary");
    const focusedLog = document.activeElement.matches(".deck-supporting .deck-terminal-body");
    // Wide docked cards have room for the evidence, so it starts open there instead of leaving the card
    // half empty; elsewhere it starts closed. A user's open or closed choice holds for the selected chat.
    // Every card starts with its evidence closed and opens it on request; the choice holds for the selected chat.
    const supportingOpen = !selectionChanged && Boolean(feature.querySelector(".deck-supporting")?.open);
    deckSelected = chatKey(selected.chat);
    const cards = [selected].map(({ chat, kind }) => {
      const card = el("article", "deck-card");
      card.dataset.key = chatKey(chat);
      card.dataset.kind = kind;
      card.dataset.selected = String(chatKey(chat) === deckSelected);
      card.dataset.checkpoint = String(kind === "working" || !chat.outcome?.trim());
      card.dataset.quiet = String(deckQuiet(chat, kind));
      card.dataset.phase = deckPhase(chat, kind);
      // Hero and evidence share one body: on a touch tablet it is the card's single scrolling area (see app.css).
      const body = el("div", "deck-card-body");
      card.append(body);
      body.append(deckHero(chat, kind));
      const delegates = deckDelegateList(chat);
      if (delegates) body.append(delegates);
      const supporting = el("details", "deck-supporting");
      supporting.open = supportingOpen;
      const summary = el("summary");
      const collapse = el("span", "deck-supporting-collapse", "Collapse");
      collapse.setAttribute("aria-hidden", "true");
      summary.append(el("span", "", "Supporting evidence · logs, files & history"), collapse);
      supporting.append(summary);
      const context = card.querySelector(".deck-context");
      if (context) {
        const contextPanel = el("section", "deck-supporting-context");
        contextPanel.append(el("h3", "deck-supporting-label", "CURRENT CONTEXT"), context.cloneNode(true));
        supporting.append(contextPanel);
      }
      const traces = deckTraces(chat, kind, { supporting: true });
      if (traces) supporting.append(traces);
      supporting.append(...card.querySelectorAll(".deck-lap, .deck-vitals, .deck-files-panel, .deck-tools, .deck-unreported"));
      card.querySelector(".deck-readout").remove();
      const terminal = card.querySelector(".deck-terminal");
      if (terminal) {
        const history = deckTerminal(chat, { allEvents: true });
        const log = history.querySelector(".deck-terminal-body");
        log.tabIndex = 0;
        log.setAttribute("role", "region");
        log.setAttribute("aria-label", "Recorded activity log");
        supporting.append(history);
      }
      if (kind === "working") {
        const setup = card.querySelector(".deck-setup");
        if (setup) supporting.append(setup.cloneNode(true));
      }
      const decisions = (chat.decisions || []).filter((d) => d.chosen !== null);
      // Historical decisions support the current handoff without competing with its next action.
      if (decisions.length) {
        const history = el("section", "deck-history");
        history.setAttribute("aria-label", "Latest recorded decisions");
        const list = el("ol");
        for (const decision of decisions.slice(-3).reverse()) {
          const item = el("li", "", `${decision.question || "Decision"} → ${decision.chosen}`);
          item.title = item.textContent;
          list.append(item);
        }
        if (decisions.length > 3) list.append(el("li", "deck-history-earlier", `+${decisions.length - 3} earlier in the chat`));
        history.append(list);
        supporting.append(history);
      }
      if (supporting.children.length > 1) {
        const panel = el("div", "deck-supporting-body");
        panel.append(...[...supporting.children].slice(1));
        supporting.append(panel);
        body.append(supporting);
      }
      const footer = el("div", "deck-card-footer");
      const waiting = groups.get("waiting").length;
      if (kind !== "waiting" && waiting && !deckFilter) {
        const jump = el("button", "deck-card-jump", `${waiting} waiting →`);
        jump.type = "button";
        jump.dataset.jumpWaiting = "";
        jump.setAttribute("aria-label", `Show the first of ${waiting} Needs you chats`);
        footer.append(jump);
      }
      const review = deckReviewButton(chat, kind, "deck-card-review");
      if (review) footer.append(review);
      // Claude chats resume from a terminal command, which the thread view offers to copy.
      const agentLink = chat.harness === "cursor" ? chat.handoff?.open_uri || ""
        : chat.harness === "claude" ? "" : `codex://threads/${encodeURIComponent(chat.id)}`;
      // The thread view only shows the chat, so the verb applies only where the agent itself opens.
      const open = el("a", "deck-card-open", agentLink ? `${stepVerb(chat, kind === "waiting")} in ${appName(chat)}` : "Open chat");
      open.href = agentLink || `/?thread=${encodeURIComponent(chatKey(chat))}&view=deck`;
      open.append(icon(agentLink ? "i-external" : "i-chevron"));
      if (agentLink) open.dataset.openKey = chatKey(chat);
      footer.append(open);
      card.append(footer);
      return card;
    });
    const signature = cards.map((card) => card.outerHTML).join("");
    if (feature.dataset.sig !== signature) {
      feature.dataset.sig = signature;
      // A live update must not scroll the card being read back to its top. Read before the reuse below moves
      // the log and charts out of the old card, which shrinks it and resets its scroll.
      const scrolled = new Map([...feature.querySelectorAll(".deck-card")].map((card) => [card.dataset.key, card.querySelector(".deck-card-body")?.scrollTop || 0]));
      // Keep ongoing cell reveals alive when live updates replace the surrounding card.
      for (const card of cards) {
        const previous = previousBlocks.get(card.dataset.key);
        const terminal = card.querySelector(".deck-terminal");
        const previousTerminal = previousTerminals.get(card.dataset.key);
        if (terminal && terminal.outerHTML === previousTerminal?.outerHTML) terminal.replaceWith(previousTerminal);
        const chart = card.querySelector(".deck-pulse-chart");
        const previousChart = previousCharts.get(card.dataset.key);
        if (chart && chart.outerHTML === previousChart?.outerHTML) chart.replaceWith(previousChart);
        card.querySelectorAll(".deck-gauge-block").forEach((block, index) => {
          if (!calm.matches && previous?.[index]?.outerHTML === block.outerHTML) block.replaceWith(previous[index]);
        });
      }
      if (feature.contains(carousel)) $("deck-stage").append(carousel);
      feature.replaceChildren(...cards);
      for (const card of cards) if (scrolled.get(card.dataset.key)) card.querySelector(".deck-card-body").scrollTop = scrolled.get(card.dataset.key);
      feature.dataset.selected = deckSelected;
      if (!calm.matches) {
        for (const hero of feature.querySelectorAll(".deck-hero")) {
          if (presentationChanged) hero.animate([{ opacity: .25, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 220, easing: "cubic-bezier(.22,1,.36,1)" });
          const terminal = hero.querySelector(".deck-terminal");
          if (terminal && terminal.dataset.live === "true" && terminal.dataset.stream !== previousTerminals.get(hero.dataset.key)?.dataset.stream) {
            terminal.querySelector("li:last-child, .deck-terminal-idle")?.animate([{ opacity: .2, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 180, easing: "cubic-bezier(.22,1,.36,1)" });
          }
          const previous = previousBlocks.get(hero.dataset.key);
          hero.querySelectorAll(".deck-gauge:not(.deck-gauge-standby) .deck-gauge-block").forEach((block, index, blocks) => {
            const from = selectionChanged ? "0%" : previous?.[index]?.style.getPropertyValue("--fill") || "0%";
            const to = block.style.getPropertyValue("--fill");
            if (from !== to && to !== "0%") block.querySelector(".deck-gauge-fill").animate([{ opacity: 0 }, { opacity: 1 }], { duration: 350, delay: index * (1400 / blocks.length), easing: "ease", fill: "backwards" });
          });
        }
        if (deckDirection) cards[0].animate([{ transform: `translateX(${deckDirection * (24 + deckMomentum * 8)}px)`, opacity: .5 }, { transform: "translateX(0)", opacity: 1 }], { duration: 280 - deckMomentum * 40, easing: "cubic-bezier(.22,1,.36,1)" });
      }
      if (focusedKey && focusedCarouselStep === null) {
        const card = cards.find((item) => item.dataset.key === focusedKey);
        (card?.querySelector(focusedLog ? ".deck-supporting .deck-terminal-body" : focusedSupporting ? ".deck-supporting > summary" : focusedReview ? "button" : "a") || cards[0].querySelector("a")).focus({ preventScroll: true });
      }
    }
  } else {
    if (feature.contains(carousel)) $("deck-stage").append(carousel);
    feature.replaceChildren();
    delete feature.dataset.sig;
    delete feature.dataset.selected;
  }
  deckDirection = 0;
  deckMomentum = 0;
  feature.hidden = !selected;
  if (selected) {
    const footer = feature.querySelector(".deck-card-footer");
    if (carousel.parentElement !== footer) footer.prepend(carousel);
    if (focusedCarouselStep !== null) carousel.querySelector(`[data-step="${focusedCarouselStep}"]`)?.focus({ preventScroll: true });
  } else if (focusedCarouselStep !== null) $("deck-fleet").querySelector(".deck-fleet-all")?.focus({ preventScroll: true });
  $("deck-stage").hidden = !selected;
  renderDeckMatrix(groups, selected);
  markDeckQueueMore();
  const queue = deckCarouselQueue(groups);
  // One chat has nowhere to step to; the status pill already names the kind.
  $("deck-carousel").hidden = !selected || queue.length < 2;
  const position = `${Math.max(0, queue.findIndex((chat) => chatKey(chat) === deckSelected)) + 1} / ${queue.length}`;
  if ($("deck-position").textContent !== position) $("deck-position").textContent = position;
  $("deck-carousel").setAttribute("aria-label", `${selected ? DECK_NAMES[selected.kind] : "Chat"} carousel`);
  for (const button of $("deck-carousel").querySelectorAll("button")) button.disabled = queue.length < 2;
  if (focusedCarouselStep !== null && selected && queue.length < 2) feature.querySelector("a")?.focus({ preventScroll: true });
  const root = $("deck-groups");
  const focused = root.contains(document.activeElement) && document.activeElement?.dataset.select;
  const focusedHistory = root.contains(document.activeElement) && document.activeElement?.dataset.history;
  const focusedReview = root.contains(document.activeElement) && document.activeElement?.dataset.review;
  const focusedMore = root.contains(document.activeElement) && document.activeElement?.hasAttribute("data-more-earlier");
  const focusedGroup = document.activeElement?.closest("details")?.dataset.kind;
  const swiped = root.querySelector("li[data-swiped] .deck-row")?.dataset.select;
  // Docked, the dock is the permanent queue and the page is a three-zone, no-scroll grid: no lists below.
  $("deck-view").dataset.docked = String(deckDocked());
  root.hidden = fallback === "standby" || deckDocked();
  root.replaceChildren(...(fallback === "earlier" ? [...kinds, "earlier"] : kinds).map((kind) => {
    const group = el("details", "deck-group");
    group.dataset.kind = kind;
    group.open = groups.get(kind).length > 0 && (kind === "earlier" || !deckFilter || kind === deckFilter) && (deckGroupOpen.get(kind) ?? !deckNarrow.matches);
    group.dataset.muted = String(Boolean(deckFilter) && kind !== deckFilter && kind !== "earlier");
    const summary = el("summary", "deck-group-heading");
    const badge = el("span", "deck-icon");
    badge.append(icon(SECTION_ICONS[kind]));
    const chevron = icon("i-chevron");
    chevron.classList.add("deck-collapse");
    summary.append(badge, el("span", "deck-group-name", DECK_NAMES[kind] || "EARLIER"),
      el("span", "deck-group-count", String(groups.get(kind).length)), chevron);
    summary.addEventListener("click", (event) => {
      if (kind !== "earlier" && deckFilter && deckFilter !== kind) { event.preventDefault(); focusDeckKind(kind); }
      else deckGroupOpen.set(kind, !group.open);
    });
    const list = el("ol", "deck-rows");
    const rows = kind === "earlier" ? groups.get(kind).slice(0, deckEarlierLimit) : groups.get(kind);
    list.append(...rows.map((chat) => deckRow(chat, kind)));
    if (deckFilter === kind && !groups.get(kind).length) {
      group.open = true;
      list.append(el("li", "deck-filter-empty", `No ${DECK_NAMES[kind].toLowerCase()} chats. Select this fleet filter again to show all.`));
    }
    group.append(summary, list);
    if (kind === "earlier" && rows.length < groups.get(kind).length) {
      const more = el("button", "deck-history-more", "Load more earlier chats");
      more.type = "button";
      more.dataset.moreEarlier = "";
      group.append(more);
    }
    return group;
  }));
  let restoreTarget;
  if (focused) restoreTarget = root.querySelector(`[data-select="${CSS.escape(focused)}"], [data-history="${CSS.escape(focused)}"]`);
  else if (focusedHistory) restoreTarget = root.querySelector(`[data-history="${CSS.escape(focusedHistory)}"], [data-select="${CSS.escape(focusedHistory)}"]`);
  else if (focusedReview) restoreTarget = root.querySelector(`[data-review="${CSS.escape(focusedReview)}"]`);
  else if (focusedMore) restoreTarget = root.querySelector("[data-more-earlier]");
  else if (focusedGroup) restoreTarget = root.querySelector(`[data-kind="${focusedGroup}"] > summary`);
  if (focused || focusedHistory || focusedReview || focusedMore || focusedGroup) {
    (restoreTarget?.getClientRects().length ? restoreTarget : $("deck-fleet").querySelector(".deck-fleet-all"))?.focus({ preventScroll: true });
  }
  if (swiped) root.querySelector(`[data-select="${CSS.escape(swiped)}"]`)?.parentElement.setAttribute("data-swiped", "");
  const standby = $("deck-empty");
  standby.hidden = fallback !== "standby";
  const connected = $("connection").dataset.state === "live";
  standby.dataset.connected = String(connected);
  const headline = connected ? "No active chats in this view" : "Waiting for connection";
  const description = connected ? "Open Inbox to see other chats and earlier results." : "Local telemetry is reconnecting. The last recorded view has no active chats.";
  if ($("deck-standby-title").textContent !== headline) $("deck-standby-title").textContent = headline;
  if ($("deck-standby-description").textContent !== description) $("deck-standby-description").textContent = description;
  const earlier = groups.get("earlier").length;
  $("deck-earlier-link").hidden = earlier === 0 || fallback === "earlier";
  $("deck-earlier-link").textContent = `${earlier} earlier ${earlier === 1 ? "chat" : "chats"} in the inbox`;
  const needs = groups.get("waiting").length;
  document.title = needs ? `(${needs}) Your Turn` : "Your Turn";
  setFavicon(needs > 0);
}

$("deck-groups").addEventListener("click", (event) => {
  if (event.target.closest("[data-more-earlier]")) {
    const next = deckEarlierLimit;
    deckEarlierLimit += SECTION_LIMIT;
    renderDeck(deckData);
    document.querySelectorAll('.deck-group[data-kind="earlier"] [data-history]')[next]?.focus();
    return;
  }
  const review = event.target.closest("[data-review]");
  if (review) { reviewDeckChat(review.dataset.review); return; }
  const row = event.target.closest(".deck-row");
  if (!row || !deckData || row.dataset.history) return;
  selectDeckChat(row.dataset.select);
  $("deck-feature").scrollIntoView({ block: "nearest", behavior: "instant" });
});

$("deck-feature").addEventListener("click", (event) => {
  const review = event.target.closest("[data-review]");
  if (review) reviewDeckChat(review.dataset.review);
  if (event.target.closest("[data-jump-waiting]")) {
    deckPinned = false;
    renderDeck(deckData);
    $("deck-feature").querySelector("a")?.focus({ preventScroll: true });
  }
});

// Hero swipes navigate; queue swipes act. Vertical drags keep native page scrolling.
for (const root of [$("deck-feature"), $("deck-groups")]) {
  root.addEventListener("pointerdown", (event) => {
    deckSwipeUntil = 0;
    const node = event.target.closest(".deck-row, .deck-hero");
    if (!node || node.dataset.history || !["touch", "pen"].includes(event.pointerType) || event.isPrimary === false) return;
    deckGesture = { node, key: node.dataset.select || node.dataset.key, id: event.pointerId, x: event.clientX, y: event.clientY, dx: 0, dy: 0, moved: false, hero: node.classList.contains("deck-hero"), lastX: event.clientX, lastAt: performance.now(), velocity: 0 };
  });
  root.addEventListener("pointermove", (event) => {
    const swipe = deckGesture;
    if (!swipe || swipe.id !== event.pointerId) return;
    const now = performance.now();
    swipe.velocity = (event.clientX - swipe.lastX) / Math.max(1, now - swipe.lastAt);
    swipe.lastX = event.clientX;
    swipe.lastAt = now;
    swipe.dx = event.clientX - swipe.x;
    swipe.dy = event.clientY - swipe.y;
    if (!swipe.moved && Math.abs(swipe.dy) > Math.abs(swipe.dx) && Math.abs(swipe.dy) > 8) { deckScrollTakeover(); return; }
    if (Math.abs(swipe.dx) < 8 && !swipe.moved) return;
    swipe.moved = true;
    swipe.node.setPointerCapture(event.pointerId);
    const protectedRow = !swipe.hero && swipe.dx < 0 && !swipe.node.parentElement.querySelector("[data-review]");
    swipe.node.style.translate = `${protectedRow ? Math.max(-8, swipe.dx * .1) : Math.max(-120, Math.min(60, swipe.dx * (swipe.hero ? .25 : 1)))}px 0`;
    swipe.node.dataset.dragging = "true";
  });
  const end = (event) => {
    const swipe = deckGesture;
    if (!swipe || swipe.id !== event.pointerId) return;
    deckGesture = null;
    swipe.node.style.translate = "";
    delete swipe.node.dataset.dragging;
    if (swipe.node.hasPointerCapture(event.pointerId)) swipe.node.releasePointerCapture(event.pointerId);
    // Keep the tapped DOM node alive until its click selects/opens the chat.
    if (!swipe.moved) { if (event.type === "pointercancel") { deckGesture = swipe; deckScrollTakeover(); } return; }
    if (swipe.moved) deckSwipeUntil = performance.now() + 450;
    const velocity = performance.now() - swipe.lastAt < 100 ? swipe.velocity : 0;
    const action = event.type === "pointercancel" ? "" : deckSwipe(swipe.dx, swipe.dy, swipe.node.offsetWidth, swipe.hero, velocity);
    if (action === "next" || action === "previous") { deckSelected = swipe.key; cycleDeckChat(action === "next" ? 1 : -1, velocity); }
    else if (action === "focus") { selectDeckChat(swipe.key); $("deck-feature").scrollIntoView({ block: "nearest", behavior: "instant" }); }
    else if (action === "review" && swipe.node.parentElement.querySelector("[data-review]")) {
      if (-swipe.dx > swipe.node.offsetWidth / 2) reviewDeckChat(swipe.key);
      else { swipe.node.parentElement.dataset.swiped = ""; renderDeck(deckData); }
    } else { delete swipe.node.parentElement.dataset.swiped; renderDeck(deckData); }
  };
  root.addEventListener("pointerup", end);
  root.addEventListener("pointercancel", end);
  root.addEventListener("click", (event) => {
    if (performance.now() < deckSwipeUntil) { event.preventDefault(); event.stopImmediatePropagation(); return; }
    const row = event.target.closest(".deck-row");
    if (row && "swiped" in row.parentElement.dataset) {
      event.preventDefault(); event.stopImmediatePropagation(); delete row.parentElement.dataset.swiped;
    }
  }, true);
}

if (deckView && !threadId) document.addEventListener("keydown", (event) => {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey || event.shiftKey ||
      shortcutBlocked(event.target, Boolean(document.body.dataset.aside)) || document.body.dataset.navigation === "open") return;
  const step = ["j", "J", "ArrowRight"].includes(event.key) ? 1 : ["k", "K", "ArrowLeft"].includes(event.key) ? -1 : 0;
  if (step) { event.preventDefault(); cycleDeckChat(step); }
  if (event.key === "e") {
    const key = document.activeElement.closest(".deck-card")?.dataset.key || document.activeElement.dataset.select;
    if (key) { event.preventDefault(); reviewDeckChat(key); }
  }
});

let deckParents = new Map(); // child key -> orchestrator, for the Deck's check reading
function liveDeck(chats) {
  deckParents = deckDelegates(chats).parents;
  stateSync.retain(chats.map(chatKey));
  migrateLocalMarks(chats);
  notifyChanges(chats);
  renderDeck(chats);
}

if (!threadId && !deckView) {
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
    const saved = readPreference("compact-header");
    document.documentElement.dataset.header = saved === "true" || (saved === null && innerHeight < 1100) ? "compact" : "full";
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
    markThreadSeen();
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
    if (event.key === "e") {
      const id = document.activeElement.closest("#sections li")?.querySelector(".row")?.dataset.id;
      const chat = id && inboxData?.find((item) => chatKey(item) === id);
      if (!chat || !inboxDismissal(chat)) return;
      event.preventDefault();
      dismissFromInbox(chat, inboxDismissal(chat));
      return;
    }
    const direction = ["j", "ArrowDown"].includes(event.key) ? 1 : ["k", "ArrowUp"].includes(event.key) ? -1 : 0;
    if (!direction) return;
    const rows = [...document.querySelectorAll("#sections .row")].filter((row) => row.getClientRects().length);
    const key = queueTarget(rows.map((row) => row.dataset.id), document.activeElement.dataset.id, direction);
    const row = rows.find((row) => row.dataset.id === key);
    if (row) { event.preventDefault(); row.focus(); row.scrollIntoView({ block: "nearest" }); }
  });
  // Touch has no hover: swiping a dismissible row left reveals Dismiss; past half the row it dismisses.
  // Vertical drags stay with the browser (touch-action: pan-y), which cancels the swipe.
  let swipe = null;
  let swipeEnded = -Infinity;
  const closeSwipes = (except) => {
    for (const item of $("sections").querySelectorAll("li[data-swiped]")) if (item !== except) delete item.dataset.swiped;
  };
  const endSwipe = () => {
    if (!swipe) return;
    delete swipe.item.dataset.swiping;
    swipe.row.style.translate = "";
    swipe = null;
  };
  $("sections").addEventListener("pointerdown", (event) => {
    swipeEnded = -Infinity;
    const row = event.target.closest(".row");
    const button = row?.parentElement.querySelector(":scope > .row-dismiss");
    if (event.pointerType !== "touch" || !button) return;
    closeSwipes(row.parentElement);
    const open = "swiped" in row.parentElement.dataset ? button.offsetWidth : 0;
    swipe = { item: row.parentElement, row, button, x: event.clientX, open, dx: -open, moved: false };
  });
  $("sections").addEventListener("pointermove", (event) => {
    if (!swipe) return;
    const delta = event.clientX - swipe.x;
    if (!swipe.moved && Math.abs(delta) < 8) return;
    swipe.moved = true;
    swipe.dx = Math.min(0, delta - swipe.open);
    swipe.item.dataset.swiping = "";
    swipe.row.style.translate = `${swipe.dx}px 0`;
  });
  $("sections").addEventListener("pointerup", () => {
    if (!swipe) return;
    const { item, row, button, dx, moved } = swipe;
    endSwipe();
    if (!moved) return;
    swipeEnded = performance.now();
    if (-dx > row.offsetWidth / 2) button.click();
    else if (-dx > button.offsetWidth / 2) item.dataset.swiped = "";
    else delete item.dataset.swiped;
  });
  $("sections").addEventListener("pointercancel", endSwipe);
  // A swipe is not a tap, and a tap on an open row closes it instead of opening the chat.
  $("sections").addEventListener("click", (event) => {
    if (event.target.closest(".row-dismiss")) return;
    const item = event.target.closest(".row")?.parentElement;
    const justSwiped = performance.now() - swipeEnded < 400;
    if (!justSwiped && !(item && "swiped" in item.dataset)) {
      closeSwipes();
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    if (!justSwiped) delete item.dataset.swiped;
  }, true);
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
  const chats = inboxData || attentionData || deckData;
  if (chats) notifyChanges(chats);
  if (document.hidden) return;
  // Passing the stall threshold writes nothing, so redraw once to offer Dismiss on a now-stuck chat.
  if (deckView && !threadId && deckData?.some((chat) => {
    const age = Date.now() - Date.parse(chat.updated_at);
    return chat.quiet && age > DECK_STALL_MS && age <= DECK_STALL_MS + 30_000;
  })) renderDeck(deckData);
  for (const node of document.querySelectorAll("[data-ago]")) node.textContent = ago(node.dataset.ago, "short" in node.dataset ? "" : " ago");
  for (const node of document.querySelectorAll("[data-quiet-at]")) node.textContent = `Quiet ${ago(node.dataset.quietAt).replace(/ ago$/, "")}`;
  for (const node of document.querySelectorAll("[data-working-since]")) node.textContent = `${STATUS.working.label} ${workingFor(node.dataset.workingSince)}`;
  if (threadData) renderStatus(threadData, threadData.turns[threadData.turns.length - 1]);
}, 30_000);
setInterval(() => {
  if (document.hidden || !deckView) return;
  renderDeckTelemetry();
  for (const node of document.querySelectorAll("[data-lcd]")) updateDeckTimer(node);
  for (const node of document.querySelectorAll("[data-pulse-last]")) updateDeckPulse(node);
}, 1_000);


// The page this tab showed before this one, so Back can step back in history (restored instantly) when it is the
// page the back link names, instead of loading it again as a new entry.
const previousView = (() => { try { return sessionStorage.getItem("your-turn.view") || ""; } catch { return ""; } })();
function rememberPage() {
  try { sessionStorage.setItem("your-turn.view", `${document.body.dataset.view}:${threadId || deckView ? "" : inboxStatus}`); } catch { /* Back loads the page. */ }
}
rememberPage();

function goBack() {
  if (history.length > 1 && previousView === (deckView ? "deck:" : `inbox:${inboxStatus}`) && !returnOpenId) history.back();
  else location.assign($("back").href);
}

// A home-screen app has no browser Back gesture: a swipe from the left edge goes back, as in Safari.
function edgeSwipeBack() {
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (!standalone) return;
  const view = $("thread-view");
  let start = null;
  addEventListener("touchstart", (event) => {
    const touch = event.touches[0];
    start = event.touches.length === 1 && touch.clientX < 24 ? { x: touch.clientX, y: touch.clientY, dx: 0 } : null;
  }, { passive: true });
  addEventListener("touchmove", (event) => {
    if (!start) return;
    const touch = event.touches[0];
    start.dx = touch.clientX - start.x;
    if (Math.abs(touch.clientY - start.y) > Math.max(30, start.dx)) { start = null; view.style.translate = ""; return; }
    if (!calm.matches) view.style.translate = `${Math.max(0, start.dx * .6)}px 0`;
  }, { passive: true });
  const end = (event) => {
    if (!start) return;
    const back = event.type === "touchend" && start.dx > Math.min(100, innerWidth / 4);
    start = null;
    view.style.translate = "";
    if (back) goBack();
  };
  addEventListener("touchend", end);
  addEventListener("touchcancel", end);
}

if (threadId) {
  $("thread-view").hidden = false;
  $("back").hidden = false;
  $("back").href = inboxUrl(inboxStatus, returnOpenId);
  $("back-label").textContent = inboxStatus ? INBOX_FILTERS[inboxStatus].label : "Inbox";
  if (deckView) { $("back").href = "/deck"; $("back-label").textContent = "Deck"; }
  $("inbox-title").hidden = true;
  $("thread-heading").hidden = false;
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || document.querySelector("dialog[open]") ||
        document.body.dataset.navigation === "open" || document.body.dataset.aside) return;
    // Escape's default action stops loading, which cancels this navigation and closes the live streams.
    event.preventDefault();
    goBack();
  });
  $("back").addEventListener("click", (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    goBack();
  });
  edgeSwipeBack();
  connect(`/api/stream?thread=${encodeURIComponent(threadId)}`, "thread", renderThread);
  // The favicon and notifications cover every chat, not just this one; the live label follows this chat's stream.
  stream("/api/stream", (source) => source.addEventListener("inbox", (message) => {
    attentionData = markSuperseded(JSON.parse(message.data));
    stateSync.retain(attentionData.map(chatKey));
    syncOpenThread();
    syncNavigation(attentionData);
    notifyChanges(attentionData);
    setFavicon(attentionData.some(needsAttention));
  }));
} else if (deckView) {
  $("deck-view").hidden = false;
  document.querySelector(".deck-brand-row").append(document.querySelector(".bar"));
  $("nav-inbox").removeAttribute("aria-current");
  // The rail icon toggles the layout: on the deck it turns the deck off.
  $("nav-deck").setAttribute("aria-current", "page");
  $("nav-deck").href = "/";
  $("nav-deck").dataset.tooltip = "Turn off deck";
  $("nav-deck").setAttribute("aria-label", "Turn off deck");
  connect("/api/stream", "inbox", liveDeck);
} else {
  $("inbox-view").hidden = false;
  $("panel-head").hidden = false;
  if (inboxStatus) $("inbox-title").textContent = INBOX_FILTERS[inboxStatus].label;
  connect("/api/stream", "inbox", liveInbox);
  const open = params.get("open");
  if (open && wideDetail.matches) showPanel(open);
  else if (open) location.replace(`/?thread=${encodeURIComponent(open)}${inboxReturn}`);
}
