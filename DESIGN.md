# Design

## Authority and product

Active design contract, revised 2026-10-30. The approved architectural light/dark
references replace the earlier iOS grouped-list and automatic kanban presentation.

Your Turn helps an engineer who runs several coding-agent chats (Codex, Claude Code, Cursor) see
which chats need them, what each one produced, and what to do next, then act on that chat in its
own app. It is a read-only local web page, usually open in a narrow browser window beside the
agent's app. It is not a native app and has no agent controls.

Agents are no longer the slow part of the loop; the person running them is. The inbox and chat page
answer four questions in this order:

| Step | Question | Answered by |
| --- | --- | --- |
| Notice | Does it need me? | Status, Needs you count, alerts |
| Understand | What happened? | Recap, outcome, changed files |
| Judge | Can I trust it? | Checks, Check failed, Edits unchecked |
| Act | What do I do next? | Next step, the chat's action (Open in Codex, Copy resume command, Open in Cursor) |

A feature belongs only if it shortens one of these steps. Controlling agents, and dashboards read
for their own sake, are out of scope.

## Environment

- Responsive from 320px to desktop. An 80px icon rail provides Inbox, Settings and Help. The leaf mark is the
  Inbox link (tooltip "Inbox"); there is no separate Inbox icon, so the rail has one way home.
  Below 960px it becomes a keyboard-accessible drawer with visible labels.
- The inbox remains one grouped list at every width. At 1280px and above, selecting a chat
  can open a detail pane without changing the default inbox into columns.
- Theme follows the system until an explicit browser-local override is chosen. The root theme
  resolves before first paint and controls both UI tokens and day/night artwork.
- Pointer, keyboard and touch work. No interaction requires hover. Chat prose keeps its reading measure.

## Inbox

- The icon rail separates application navigation from status filtering. Icons have accessible names
  and hover/keyboard-focus labels. The header shows the active view title, with no tagline, beside
  a shallow architectural niche with the original round metal-and-glass gachapon, plant and two capsules.
- Each theme uses ONE complete text-free scene exported from the selected header master. Separate
  room and object layers were rejected after misalignment produced a doubled niche. Keep machine,
  plant, capsules and their lighting together. Only live HTML controls are layered over the image.
  No whole UI mockup is shipped as a background.
- Status filters have one owner: the full inbox uses the glass tab bar; the compact detail list
  uses one labeled native selector with the same counts and URL semantics. The outer rail has no
  status filters. The selector uses appearance:auto with explicit indicator clearance.
  Glass has an opaque fallback. Controls never become rasterized text.
- Live connection and quick-theme controls remain accessible in a top-right utility row; the chat back link stays on the left.
- The tab title carries the Needs you count, as "(2) Your Turn", and the favicon gains an orange
  badge while any chat needs the user. Chat pages also follow the inbox stream, so the badge and
  notifications cover every chat, not only the open one.
- Notifications are opt-in through the bell and stored in this browser. The bell always shows a
  plain bell (the struck-through bell is the status card's dismiss action); on is shown by an
  accent-tinted pressed state, and its accessible name stays "Desktop notifications". While the
  page is hidden or unfocused, a chat that newly needs the user, or has been quiet for five minutes,
  raises one system notification, tagged by chat so repeats replace each other; clicking it opens
  that chat. Chats that already needed the user when the page loaded do not notify.
- Ages, quiet durations, and the quiet note refresh every 30 seconds in place, because a quiet chat
  writes nothing that would push an update.
- Header filters are All, Needs you, Working, New results and Earlier, with a selected underline.
- Each section initially shows10 chats at every width and filter. Load more adds10, retaining the expanded count through live updates. Counts always cover the full matching set.
- One history_days setting in config.toml defines the inbox window for every status (default14 days, positive integer, read at server start). Older chats remain accessible by direct link; no hidden latest30 exception.
- Empty sections are not drawn. Needs you therefore only appears with chats, inside a soft orange
  tint and edge, so the color itself means "something is waiting".
- In All, with more than one section, each section heading is a disclosure button: a chevron on
  the right, and the chat count only while folded. Folding lasts through live updates.
- Earlier is history, so it starts folded. It is open when it is the only section, when Earlier
  is the filter, or when the open chat is in it. Once open it stays open, so a new chat never
  folds the list under the reader. A folded section opens when the open chat moves into it.
- Needs you retains longest-wait-first ordering. Other sections sort by latest change. Existing status, seen and quiet semantics remain unchanged.
- Each status cue appears once. A desktop row has a pale outline-glyph chip, title/preview/action or
  check tags, project name (no icon), age and navigation chevron. Section headings carry no counts;
  the filters own them. Rows in New results carry no New tag. Titles and secondary text are neutral
  rather than blue.
- A Needs you row shows the request in full-strength text, and a pending question adds its recorded
  options as one muted read-only line, so the choice is visible without opening the chat.
  Normal rows are 72px minimum. Desktop previews use one line; narrow attention previews use two,
  and the full request remains available in the chat. Small screens move project/age below the title.
- Preserve Answer/Run/Review, quiet, new, failure and unchecked tags; no data is inferred from titles
  just to imitate a gear/flask/bug glyph in a generated mockup. Semantic status/action icons are honest.
- Opening a finished result updates seen state and all filter counts immediately, including cross-tab
  storage updates. It does not complete a recorded user action.
- Filtered chat links keep their return scope; the chat page's back link returns to it.

## Wide detail pane

- At 1280px and above, an ordinary row click opens a bookmarkable `/?open=<id>` detail pane;
  the inbox becomes a compact list beside it. The sidebar remains available.
- Selecting another filter keeps the detail open. Modified clicks use the real full-chat link.
- Escape/Close returns focus to the originating row, or the current filter if the seen result moved.
  Browser Back/Forward restores pane state. Narrowing the viewport redirects an open pane to the
  full chat page with its filter return scope preserved.
- Detail content scrolls independently and stays top-aligned. Native dialogs take precedence over
  pane Escape handling. Gachapon animation and parallax remain deferred; scene composition stays steady.
- The status card sizes to its complete content; the primary chat action must never be
  clipped by a grid track. Compact-list filters stay pinned, and row scroll margins account for them.
- Working rows use their status or quiet label without generic per-item coaching text. Actual
  activity belongs in the opened chat; do not add invented progress just to fill a preview line.

## Settings and Help

- Settings exposes System/Light/Dark and the existing notification permission/preference behavior.
  Appearance controls and quick toggle share one resolver. Storage failure applies a page-local choice
  without claiming it was saved. Notification permission is requested only through an explicit action.
- Help explains the current read-only workflow, four status groups, recent-window limits, quiet hints,
  reminder dismissal, local privacy and connection troubleshooting. There are no new account/sync features.
- Native modal dialogs support Escape and focus return. The mobile drawer traps focus, makes main
  content inert and returns focus to its menu button. Footer actions remain reachable in short windows.

## Chat page

- A sticky row with the back link on the left and the same live-state and theme group on the
  right. Below it, a large title (the chat name) and a meta row with fixed slots in a fixed order,
  each shown only when known: the agent pill (Codex, Claude Code, Cursor; the same pill as inbox
  rows, full app name here), project (full path on hover), recorded Git branch, and the time of the
  last recorded event. Items align on the text baseline (not box center), so the smaller pill
  text sits on the same line. Text slots are dot-separated with the dot trailing its item, so a wrapped
  line never starts with a separator. New metadata joins this row as another slot. The wide-screen
  pane header uses the same row.
- The status card comes first. Its header shows the status glyph and label and the chat's action:
  "Open in Codex" (deep link), "Copy resume command" for Claude Code (copies `claude --resume <id>`
  and briefly confirms), or "Open in Cursor" (opens the project folder). It is the only filled accent button on the page, and it is filled only when the chat
  needs the user or a check failed; otherwise it is an outlined secondary link. Its body depends on state:
  - Needs you: the title adds how long the request has waited ("Needs you · 12d ago"), so fresh and
    stale requests read differently. Then the action label and the request, with recorded options as
    a plain read-only list, then the reminder control and its note ("Only affects this browser's
    inbox"). The action label is omitted when the request already starts with it, so one fact is
    never stated twice ("Approve pending action in Cursor" needs no Approve label above it).
  - Working: this turn's latest recorded step, as its kind (Ran a command, Edited files, ...) and
    its source title, with commands in mono. The glyph rotates. A recorded command does not mean
    it is still running, and a new turn never shows the previous turn's step. When the chat is
    quiet, the title reads "Working · quiet", the label reads Quiet (in the needs-you color), and a
    note under the step gives the clock time and age of the last activity and says the chat may be
    waiting for approval in the chat's app (Codex, Claude Code, or Cursor) or running a long command.
  - Approval (Cursor only, which reports it): the chat is in Needs you with the action label
    Approve and "Approve pending action in Cursor"; it leaves Needs you when Cursor clears the flag.
  - Done: "No further action was requested", or "No next action was recorded" when the answer
    skipped the handoff format. When a check in the latest turn failed, either line adds ", but a
    check failed" in the danger color.
  - Loading and missing chats hide the handoff.
- What happened: the latest turn's outcome, when there is one, and a files row that expands to the
  latest turn's changed paths relative to the working directory.
- Checks, as grouped rows: a warning row when files changed after the last check, when edits had no
  check, or when a check has no exit code; and one row per check with its command and Passed,
  Failed (exit N), or Exit not reported. A missing exit code is never shown as passed, failed, or
  running. Labels follow what the chat's app records (`capabilities` in the thread JSON): Claude
  Code reports only success or failure, so its failures read Failed with no invented exit code;
  Cursor records no results, so its checks read Not recorded under one note saying Cursor doesn't
  record command results.
- Commands and paths use mono and wrap. Command highlighting (executable, path, flag, string,
  operator) is a presentation hint, not shell parsing; every character stays selectable inert text.
- Decisions, as grouped rows: the question, the recorded answer labelled Agent decision or Your
  answer, the optional reason, the recorded turn and local time when available, and a collapsed
  Other options disclosure that must not resemble choice buttons. When the app recorded that a
  question was answered but not the answer (Cursor), the question leads, the context line reads
  "Answered in Cursor; the answer was not recorded.", and the disclosure lists all Options (n). Three recent decisions show
  directly; older ones sit behind a counted disclosure row. A pending question appears in the status
  card, not here.
- What happened shows the latest `Recap:` (Chat so far) above the latest turn's outcome (Latest
  turn), each with a small label; with no recap it is the outcome alone, and while a turn runs it
  keeps showing the last recap.
- More, as disclosure rows: Earlier turns, Files changed, Activity (with Key steps and Everything
  filters), and Session details. Files changed is the session's final set of edited files, most
  recently changed first, without per-turn history (long chats made turn lists noise); it appears
  only when earlier turns edited files, because What happened already lists the latest turn's
  files. Session details groups usage, runtime, workspace, and turn facts, with one muted pictogram
  per group. The disclosure summary keeps the session token total and last-request context in view.
  Details include the latest reported token totals and last-request usage, model and effort from the
  latest turn, provider, branch, client, working directory, and report time. Counts come from the
  latest token_count snapshot, never a sum; cached input and reasoning
  are included in their parent counts; context is the last request total relative to the model
  window. Unknowns stay "Not reported" and a reported zero stays zero. Usage is telemetry, not a
  bill or an account quota; rate-limit snapshots are not shown as current account limits.
- Disclosure open state, selected text, and keyboard focus survive live updates. Decision records
  are keyed by source identity and position and keep their DOM nodes while unchanged; a focused
  decision that moves into history keeps that history open.

## Visual system

`tokens.css` owns the shared palette, type, spacing and motion values. `app.css` supplies structural
layout, responsive adaptation and small optical adjustments. No UI framework or remote font dependency.

- Neutral warm-white / charcoal surfaces and neutral charcoal/grey or off-white/grey text. Green is
  navigation emphasis; orange waiting, purple working, teal new/passed, grey history, red failure.
  Selected green ink is darker in light mode to meet contrast over its tinted surface.
- Native system typography. Desktop display title 76px, row title20px/regular,
  preview/project/age18px, section heading24px. Narrow panes use smaller display sizes and 16px prose.
- Insets come from named tokens, not one-off values. `--page-inset` / `--page-inset-end` place
  content (40/32px desktop, 24px medium, 20px phone). Inside a control, text starts at
  `--inset-control` (16px) and a trailing indicator (chevron, divider) sits `--inset-indicator`
  (12px) from the end. An icon-only control at a content edge bleeds by `--icon-bleed` so its glyph,
  not its invisible 44px hit area, lines up with that edge (theme toggle on desktop, menu button on
  phones). Styled selects use `appearance: none` with a `.select-chevron` at `--inset-indicator`;
  Load more is centered under its list; the sticky chat pane header has a hairline bottom edge so
  content scrolls under a boundary.
- Fine 1.5–1.8px outline icons on very pale role chips, thin separators, open inbox sections.
  Existing chat-detail cards/disclosures retain their readable grouping. No colored side stripes.
- A theme-specific local WebP header scene maintains its original green/ivory/brass/glass
  material identity. All UI text stays HTML. Art is decorative and hidden on small phone layouts.
  Art files are served as binary resources with correct MIME types and packaged with the app.
- CSS masks only blend the edge of real scene assets; they do not draw substitute illustration.
  Glass filters retain contrast and have a solid-surface fallback when blur is unsupported.
- Existing row/page/detail transitions remain; press feedback and dialogs use short opacity/transform
  motion. Working is the only continuous progress glyph. Reduced motion disables all transitions
  and animations. No moving capsule, toy drift or parallax changes the approved composition.
- Command/path highlighting remains inert selectable text; telemetry is not a billing or quota meter.

## Accessibility

- Normal text at least 4.5:1, large text and essential glyphs at least 3:1.
- Every control at least 44px tall; links navigate and buttons act. Native details provide
  disclosure with visible focus. Decorative glyphs are hidden from assistive technology; status is
  always also text.
- Text scales to 200% without clipping or horizontal scrolling at 320px. Below 480px, explanatory
  text (requests, outcomes, reasons, commands) uses 16px; short labels and times stay compact.
- In the list and chat page layouts the page owns scrolling: no fixed overlays or nested scroll
  regions besides the sticky chat header. Only the wide compact list and detail pane scroll independently.
- Reachable states: loading, live and reconnecting, empty inbox, empty filter, long titles,
  waiting, working, done, stopped, dismissed, missing chat, known and unknown next steps, passed,
  failed, unreported, and stale checks.

## Delivery checks

Run the repository tests and the JavaScript syntax check. Render the inbox and representative
waiting, working, and done chats in both appearances at 320, 390, 430, and 768px, plus 200% text.
Inspect contrast, overflow, focus, disclosure retention, reduced motion, long content, empty states,
and offline feedback.

Current verification evidence and any gaps are reported with the implementation delivery. Browser
checks provide evidence for the tested Chromium engine, not Safari certification.

Dated verification records live in [docs/verification.md](./docs/verification.md).

Help uses a two-column semantic status table and three native disclosures for reminders/quiet, inclusion limits, and connection/privacy. Keep the introduction brief; technical details stay available on demand. The dialog owns scrolling at narrow widths.

Desktop notifications are controlled only in Settings. Appearance and Desktop notifications headings pair lightweight decorative pictograms with persistent text labels.

The full inbox header collapses like a large top app bar: the scene and title fade and scroll away, and only the status tabs stay pinned. Browsers without scroll-linked animation keep the static header rather than pin a slice of the scene. At split-view sizes of at least 1600×800px, only the status tabs sit above both scrollable panes, with no scene, because permanent art would take space from the chat being read. Use those tabs as the sole filter; hide the compact selector. Smaller split views retain the compact header to preserve reading space.

Scrollbars are thin with no track. The page shows a faint thumb; inner panes (the split view's list and chat, the menu, Settings) show it only while pointed at or focused from the keyboard.

On mobile, group the navigation trigger, Live state and quick theme control at the top right. Move the inbox title to the top-left and keep the phone header compact. Full chat pages retain the Back link on the left.

The footer shows only the application version from package metadata. In split views it sits under the detail pane; the chat list extends to the bottom. Local-session and read-only explanations belong in Help.

Chat sections keep intrinsic row heights and align to the top of their scroll container. Sparse filtered lists must not stretch headings or distribute empty space between heading and rows. Split-view sections have no extra top inset.

Navigation is right-sided at every size: the desktop icon rail sits at the right edge; mobile opens a right-hand drawer with backdrop on its left. Mobile top-row order is Live, theme, then hamburger at the far right, matching DOM/keyboard order. Rail tooltips open toward the content on the left.

Shared content inset is owned by --content-inset:24px desktop and16px below960px. Cards, status panels, dialogs and detail-pane horizontal insets consume it. Split list and sticky detail header share the same top inset. Preserve distinct outer-page gutters and compact control gaps rather than assigning one spacing value to every role.

Session details starts with the complete selectable Thread ID and a labeled copy-icon button. Clipboard success/failure is announced inline; live refresh preserves focus on this static control. A blocked clipboard leaves the ID available for manual copying.
