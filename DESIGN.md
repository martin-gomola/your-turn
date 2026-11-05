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

## Handoff contract

Agents report through plain text in their final answer, written by the `your-turn` skill (Codex
plugin, Claude Code and Cursor global skills, and a `CLAUDE.md` block). No MCP server or other
process runs, so no app asks for a permission and nothing breaks when a tool is unavailable.

| Line | Answers | Parsed into |
| --- | --- | --- |
| `**Outcome:** <sentence>` | What happened? | The turn's outcome |
| `**Next step:** none \| answer: … \| review: … \| approve: … \| run: …` | What do I do next? | Next kind and text; an action puts the chat in Needs you |
| `**Recap:** <sentences>` (second turn on) | What is this chat about? | The chat recap |
| `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` | Why this way? | One agent decision per line (`→` accepted, `(over …)` optional) |

Questions that block the agent go through the app's own question tool (`AskUserQuestion`,
`AskQuestion`, Codex questions), so they show as pending with their options. `log_decision` tool
calls in older transcripts still read as decisions.

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

- The main bar offers a focus icon to toggle compact header density. Compact mode removes the
  decorative artwork and large title from view, keeps an accessible heading, and preserves status
  filters and utilities: one strip on desktop, utilities above filters in narrow windows. The choice
  persists in browser-local storage, resolves before first paint, and can be reversed with the same
  toggle. A blocked storage write changes only the current page. Chat-only pages omit this control.
- Focus density animates in both directions using the existing motion tokens: artwork and title
  fade upward while filters and the inbox move into place. Reduced motion, unsupported browsers,
  and an already compact split view apply the preference immediately; rapid toggles cancel the
  previous transition without leaving temporary styles behind.

- The icon rail separates application navigation from status filtering. Icons have accessible names
  and hover/keyboard-focus labels. The header shows the active view title, with no tagline, beside
  a shallow architectural niche with the original round metal-and-glass gachapon, plant and two capsules.
- Each theme uses ONE complete text-free scene exported from the selected header master. Separate
  room and object layers were rejected after misalignment produced a doubled niche. Keep machine,
  plant, capsules and their lighting together. Only live HTML controls are layered over the image.
  No whole UI mockup is shipped as a background.
- When the header artwork is visible at intermediate widths, keep the title at the desktop lower
  inset. On phone widths the artwork is hidden and the title returns to the top.
- Status filters have one owner: the full inbox uses the glass tab bar; the compact detail list
  uses one labeled native selector with the same counts and URL semantics. The outer rail has no
  status filters. The selector uses appearance:auto with explicit indicator clearance.
  Desktop tabs pair category icons with their full labels. At phone widths, they use icons and counts
  to fit without horizontal scrolling; accessible names retain the full labels. Glass has an opaque
  fallback. Controls never become rasterized text.
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
- Header filters are All, Needs you, Working, New results and Earlier, with a selected underline and
  compact status-colored count badges. A rising New results count briefly turns red and pulses; the
  initial count does not animate, and reduced-motion users receive no pulse.
- Each section initially shows10 chats at every width and filter. Load more adds10, retaining the expanded count through live updates. Counts always cover the full matching set.
- One history_days setting in config.toml defines the inbox window for every status (default14 days, positive integer, read at server start). Older chats remain accessible by direct link; no hidden latest30 exception.
- Empty sections are not drawn. Needs you therefore only appears with chats, inside a soft orange
  tint and edge, so the color itself means "something is waiting".
- In All, with more than one section, each section heading is a disclosure button: a chevron on
  the right, and the chat count only while folded. Hover and keyboard focus highlight the control;
  rows sit slightly inset beneath the heading. Folding lasts through live updates.
- Earlier is history, so it starts folded. It is open when it is the only section, when Earlier
  is the filter, or when the open chat is in it. Once open it stays open, so a new chat never
  folds the list under the reader. A folded section opens when the open chat moves into it.
- Needs you retains longest-wait-first ordering. Other sections sort by latest change. Existing status, seen and quiet semantics remain unchanged.
- Each status cue appears once. A desktop row has a pale outline-glyph chip, title/preview/action or
  check tags, a folder glyph and monospaced project name, age and navigation chevron. Section headings carry no counts;
  the filters own them. Rows in New results carry no New tag. Titles and secondary text are neutral
  rather than blue.
- A Needs you row shows the request in full-strength text, and a pending question adds its recorded
  options as one muted read-only line, so the choice is visible without opening the chat.
  Normal rows are 72px minimum. Desktop previews use one line; narrow attention previews use two,
  and the full request remains available in the chat. Small screens move project and age below the
  title together in one row; long project names truncate in the available space.
- Preserve Answer/Run/Review, quiet, new, failure and unchecked tags; no data is inferred from titles
  just to imitate a gear/flask/bug glyph in a generated mockup. Semantic status/action icons are honest.
- Opening a finished result updates seen state and all filter counts immediately, including cross-tab
  storage updates. It does not complete a recorded user action.
- A Needs you row can dismiss its reminder in place, for a request already handled in the agent app:
  the struck-through bell, the status card's dismiss action, takes the place of the age and chevron
  on hover or keyboard focus; `e` dismisses the focused row. Touch screens have no hover, so the row
  covers a labeled Dismiss action until it is swiped left; a swipe past half the row dismisses at
  once, a tap on an open row closes it, and vertical drags keep scrolling. The chat moves to Earlier as Reminder dismissed, with the same row transition as live
  updates, focus moves to the next row, and an Undo toast rises in and stays for 8 seconds, or while
  it is pointed at or focused. A new request brings the chat back.
- Filtered chat links keep their return scope; the chat page's back link returns to it.

## Deck

The supplied selected-card and compact-list reference is the Deck layout authority.
Deck is a dark read-only monitoring surface at `/deck` (also `/?view=deck`), centered
at a maximum width of 1440px, with 32px desktop gutters and available width on
phones and tablets. The one-card focus layout is capped at 820px.

Deck's canonical spacing owner is `body[data-view="deck"]` in `app.css`:
`--space-1:4px`, `--space-2:8px`, `--space-3:12px`, `--space-4:16px`,
`--space-5:24px`, `--space-6:32px`. All Deck padding, margins and gaps consume these
tokens (or token calculations); zero and automatic layout values remain valid.
The deterministic spacing test rejects raw spacing dimensions in Deck rules.
Border strokes, typography, control/glyph dimensions and animation timing keep their
own roles. These six values are scoped to Deck rather than replacing the shared
Inbox/chat scale in `tokens.css`.

- A proportional six-cell magazine represents Needs you, Working and Ready, reserving
  at least one cell for each nonempty status so rare Working sessions remain visible.
  Fleet count buttons toggle a status focus, expand its group, select its first card,
  and switch the magazine to that status, lighting exactly its count up to six cells
  and leaving unused cells dark gray. All/Fleet mode retains proportional category shares.
  Startup and filter changes run the CSS `revUp` keyframe with 350ms illumination
  and `calc(var(--index) * 45ms)` delays, plus a subtle core glow. Routine updates
  do not restart the sweep. Reduced motion
  applies the final state immediately. Clicking the active button returns to All;
  an icon-only fleet button at the start of the bar clears filters, using the same
  chamfered honeycomb silhouette as the LEDs and a three-cell honeycomb glyph,
  while retaining the selected chat. It has a neutral selected state, an accessible
  name and tooltip without a visible All label; phones have a 44px target.
  zero-count focus shows an empty message and unlit cells, never an unrelated hero.
  All three group headings remain visible, with other groups folded during focus.
  The brand row below
  holds two keyboard-accessible telemetry cycle buttons; each metric choice persists locally.
  Modes are estimated Claude reset, Codex activity/quota remaining, recorded token velocity,
  peak known context, longest wait and recorded tokens today (browser-local midnight).
  Tooltips explain source limitations: Claude reset estimates the earliest message in the
  last five hours, not the account quota; token readings cover retained local logs only.
  Both header tiers use the same full-width container edges as the cockpit grid.
  Live/navigation sit inside Tier 1's reserved trailing inset, rather than shortening
  that tier with an external margin. This alignment holds in Focus and Bento layouts.
- Desktop (>=1200px) defaults to a 60/40 Bento Cockpit: the selected full hero on
  the left, a bounded scrollable two-column matrix of mini-telemetry cards on the right.
  The matrix shows the remaining Needs you queue, excluding the selected chat. A
  status filter scopes it to that category; if no chats need the user it follows
  the selected category. Each compact three-row mini-card shows title; agent, repo and
  elapsed time; then the known/standby context gauge. The repo hides on cards narrower
  than 210px. Cards keep their compact content height (two rows fit the shortest hero)
  and never stretch to a taller hero; scrolling snaps by whole row. Selecting one swaps it into the hero and moves keyboard
  focus there. Matrix scroll and focus survive live updates. An empty matrix yields
  its space to the hero. A saved toggle offers Bento Cockpit or 1-Card Focus.
  Smaller views show one carousel card. No extra selected-chat label is needed.
  The footer's open action goes to the agent: "Open in Codex" opens that thread,
  "Open in Cursor" opens its project; Claude chats keep "Open chat" to the thread view,
  which offers the resume command. The hero body still opens the thread view.
  Carousel controls sit in the card's integrated footer beside its review action,
  wrapping as a control group on the narrowest phones. The same controls and keyboard
  focus survive live replacements and empty-to-populated transitions. Major container
  gaps are 32px, hero perimeter padding is uniformly 24px, and each status section
  starts with 24px of top margin, including the first and collapsed sections.
- Fleet buttons scale subtly on hover and press, with category-colored active borders.
  A decorative, noninteractive ambient top-edge glow appears whenever a Needs you
  wait exceeds 15 minutes. It follows the entire attention queue, independent of
  the active filter, and refreshes as time passes without requiring a new log event.
- Hero: selected border, icon tile, handoff labels, action and focus accents share the
  chat's category: amber Needs you/question icon, purple Working/rotating progress icon,
  emerald Ready/check icon. The shared `--deck-tone` role also owns section accents.
  Context utilization keeps its independent green/amber/red thresholds.
  Rounded 2px selected border, 24px perimeter padding, 55/45 columns with an exact
  32px gap and a 1px divider centered in that gutter. Stacked narrow views use the
  same gap with a horizontal divider. Left: 48px rounded category icon, one-line 24px title, full agent-name pill
  (Claude, Codex, Cursor), folder and repository, then explicit Outcome and Next lines.
  Outcome and Next are one-line 16px summaries with ellipsis and full text on hover or
  in the linked chat. Missing outcomes use a completion-checkpoint status, never a
  previous turn's recap. Next distinguishes an explicitly empty action from an unknown handoff.
  Outcome labels use the category accent; Next uses neutral high-contrast text.
  Right: 36px tabular elapsed timer
  in the normal sans font with separate time units, a .22em flex gap and an accessible
  single-space duration label, avoiding doubled monospace spacing,
  uppercase status pill (red BLOCKED for Needs you, purple WORKING, green READY), and CTX.
  Working cards replace handoff prose with a purple monospace terminal (#080A0F,
  8px radius, standard 16px internal padding) containing up to three recorded current-turn steps
  and any outstanding call. Shell rows show the recorded display command unchanged,
  never a shortened check caption or invented output. Long commands wrap; phones show
  the latest two events. Historical commands are explicitly headed RECORDED LOG;
  a pending call is not proof of process execution or approval.
  RUNNING refers to the reported open agent turn. Quiet, offline and unsupported-live
  sources display QUIET, OFFLINE or LAST KNOWN STATE without streaming motion.
  Missing activity shows “Awaiting agent completion checkpoint…”; new turns clear
  old activity captions and exclude earlier-turn events.
  Live terminals have a soft CRT scanline, purple status pulse, blinking underscore,
  and a short fade for new source events. Unchanged terminal nodes retain their
  animation phase through live card replacements; routine timer updates do not replay text.
  Working-to-Needs you/Ready transitions fade into Outcome/Next even for the same chat ID.
  Working/missing-outcome cards show a subtle indeterminate checkpoint line along
  the bottom edge. Offline, quiet, unsupported-live and reduced-motion views keep it static.
  Category transitions update all of these roles even when the selected chat key stays the same.
- Known context shows used/window and percentage, exactly ten rounded 14px segments
  separated by the 4px spacing token, with prominent amber 75% and red 90% ticks and labels.
  Context colors use green below 75%, amber from 75%, red from 90%.
  Unknown windows show the reported usage plus ten muted hatched standby segments;
  standby is not a meter and never implies a known utilization.
- Needs you, Working and Ready are collapsible groups with a rounded status icon,
  uppercase title, circular count and trailing chevron. Ready displays the existing
  New results group; underlying seen and attention semantics are preserved.
  All three headers remain visible; empty groups start collapsed.
- Each desktop row is a uniform 52px horizontal line with a 52px minimum and
  `padding:0 var(--space-4)`: status dot (or Ready check), bold task title,
  full agent-name pill, aligned repository, compact relative age and right chevron.
  Long titles and repositories truncate within their columns. Review/dismiss is a
  separate accessible action, revealed on hover/focus or a left swipe. Needs you
  dismisses a reminder and Ready marks a result reviewed. Raw source status Working
  prohibits review/dismiss entirely, even if a pending question puts it in Needs you.
  Buttons are absent and the route-scoped Deck action handler rejects shortcuts,
  swipes, direct calls and stale-button races. This is exclusively a Deck UI policy:
  shared Inbox classifiers, backend state rules and Inbox dismiss handlers retain
  their original behaviour. Legacy `cleared:` markers have no classifier semantics.
  Other row metadata stays limited to agent, repo and age.
- A row selects the hero; the hero opens the chat. Selection is visibly marked and
  keyboard accessible, using an 8% status tint and an amber ring instead of a double
  dot/left-rail collision. Row markers and 32px section icons share the same center axis.
  Every section has 24px top separation in both collapsed and open states;
  rows start 8px below their heading. Collapse state and focused controls survive
  live refreshes. Below 1024px the entire Deck is strictly one column in portrait and
  landscape, the secondary matrix is hidden, the hero's telemetry stacks below its
  identity/handoff, and row metadata moves below its title. Compact headers combine
  fleet and telemetry. Narrow rows keep the same 52px minimum and 16px horizontal
  padding, using a uniform 80px two-line layout with 12px gaps. Desktop metadata and
  its children share a centered flex axis. Page scrolling stays native; there is no short-landscape split.
- Swiping a hero horizontally or using Previous/Next, J/K or Left/Right cycles its
  current status queue (Needs you by default). A right row swipe focuses that card;
  a left row swipe reveals Dismiss/Mark reviewed, and a full swipe applies it. Visible
  buttons supply keyboard and pointer equivalents. Dismiss uses the existing reminder
  attention key. Completed-card review uses the browser-local `your-turn.deck.reviewed`
  overlay so its Undo never regresses shared seen state or overwrites Inbox reminder
  state. Deck tabs sync that overlay through storage events. Legacy `reviewed:` values
  are interpreted only by Deck and never by shared Inbox classification; existing
  shared markers are preserved. Opening a chat still uses normal shared seen state.
  These Deck actions move the chat to Earlier within Deck,
  provide Undo and never complete a request in its agent. New requests reappear.
- The selected hero fades/slides 4px using cubic-bezier(.22,1,.36,1); carousel swipes
  project recent horizontal velocity to recognize quick flicks and adjust settling motion.
  Vertical intent and cancelled gestures never act. Known CTX
  context fills retain their slower 140ms segment stagger and 350ms fade.
  Each colored cell appears as a whole at its final width rather than wiping across
  the cell. Unchanged cells retain their reveal animation through live card updates.
  Working indicators and Live breathe subtly.
  Reduced motion removes these effects, and routine updates do not replay selection motion.
- Needs you keeps longest-wait-first order. Working and Ready preserve stable deck
  ordering. Earlier remains available through the footer's counted inbox link.
- When all three active groups are empty, a matching collapsible Earlier section
  replaces the bare calm message and shows recent history already supplied by the
  server's configured local-log history window. It starts expanded, shows ten rows,
  and loads ten more at a time. Three empty active headers remain folded above it.
  History rows link directly to their chat with Deck return context and have no
  dismiss/review/swipe actions. Collapse and expansion survive live updates; active
  work returning replaces the fallback with the normal active queue.
- When the entire recent inbox is empty, hide the grouped list and show Fleet Standby:
  a soft green pulse glyph, “FLEET STANDBY · ALL SYSTEMS CLEAR”, and the monospace
  subtext “No blocking tasks. All parallel agent streams are synchronized.”
  The connected feed owns that copy; disconnected state instead says it is waiting
  for connection and uses a neutral static glyph. Reduced motion removes the pulse.
- There is no Open chat label or Files block in the hero. App navigation and Live
  remain outside the deck content. Pointer, touch and keyboard share this flow.
- A chat opened from Deck (`/?thread=<key>&view=deck`, marked `body[data-origin="deck"]`)
  is the Deck HUD: the same chat page and content in Deck's flat palette (#0d0f12 surface,
  #ffffff text, #b4b8bf secondary, #41464d 1px strokes, 2px corners, no shadows or gradients).
  It resolves dark before first paint whatever the saved appearance, and hides the theme toggle.
  The evidence strip becomes the ticker under the title: status chips first (white label after a
  role-colored dot), then monospaced tabular counters (files, decisions), then the metadata;
  it wraps rather than scrolls on narrow widths. The status card leads with a 28px title and a
  1px status-colored frame; the chat's main action is filled white with dark text. Section
  titles become uppercase labels and history stays in the existing folded disclosure rows.
  Spacing uses only the shared 4px-step tokens; the plain chat page and Deck are unchanged.

## Wide detail pane

- At 1280px and above, an ordinary row click opens a bookmarkable `/?open=<id>` detail pane;
  the inbox becomes a compact list beside it. The sidebar remains available.
- The Hide inbox icon sits at the top-right of the left chat list and opens the selected chat as a full page without that list; Inbox returns to the same
  filter with that chat reopened.
- Hiding the inbox slides its left column horizontally off the left edge while the chat expands.
  Supported browsers use the cross-page view transition; reduced motion and unsupported browsers
  navigate directly. This navigation does not use the generic upward page entrance.
- Compact row titles wrap to two lines before truncation. Row height grows with the title; the age
  stays at the top-right ("2d", 12px, tabular). The request or preview follows the title, then one
  quiet "Codex · project" line at 11px. The status glyph aligns with the title, and the open row needs
  no chevron.
- Selecting another filter keeps the detail open. Modified clicks use the real full-chat link.
- Escape or the Inbox button returns focus to the originating row, or the current filter if the seen result moved.
  Browser Back/Forward restores pane state. Narrowing the viewport redirects an open pane to the
  full chat page with its filter return scope preserved.
- Detail content scrolls independently and stays top-aligned. Escape inside the Settings/Help panel
  closes only that panel; elsewhere it closes the detail pane. Gachapon animation and parallax remain deferred; scene composition stays steady.
- The status card sizes to its complete content; the primary chat action must never be
  clipped by a grid track. Compact-list filters stay pinned, and row scroll margins account for them.
- Working rows show a compact caption from recorded live activity. Shell chains prefer at most two
  check tool names (for example `pytest && node --test`), omitting setup, redirects and log-printing
  commands. Details retain the recorded activity and check evidence. No activity is invented for sources
  that cannot report it live.
- Main-list project metadata gets a 280px column on desktop and 220px at intermediate desktop widths,
  so common repository names remain visible alongside the app badge and folder icon.

## Settings and Help

- Settings exposes System/Light/Dark and the existing notification permission/preference behavior.
  Appearance controls and quick toggle share one resolver. Storage failure applies a page-local choice
  without claiming it was saved. Notification permission is requested only through an explicit action.
- Help explains the current read-only workflow, four status groups, recent-window limits, quiet hints,
  reminder dismissal, local privacy and connection troubleshooting. There are no new account/sync features.
- Settings and Help open as one non-modal panel docked beside the rail, never a modal popup. The rail
  button toggles it (`aria-expanded`, selected style) and swaps between the two; Close, Escape from inside
  and a second click return focus to the rail button. From 1280px the page reflows beside the 380px panel
  so Appearance previews on live content, including the split view; 960–1279px overlays the page edge;
  below 960px the panel covers the page, makes it inert and returns focus to the menu button. The mobile drawer traps focus, makes main
  content inert and returns focus to its menu button. Footer actions remain reachable in short windows.

## Chat page

- A sticky row with the back link on the left and the same live-state and theme group on the
  right. Below it, a large title (the chat name) and a meta row with fixed slots in a fixed order,
  each shown only when known: the agent pill (Codex, Claude Code, Cursor; the same pill as inbox
  rows, full app name here), project (full path on hover), recorded Git branch, and the time of the
  last recorded event. Project and branch values use monospaced text with decorative folder and
  branch glyphs; text values remain the accessible names. Items align on the text baseline (not box center), so the smaller pill
  text sits on the same line. Text slots are dot-separated with the dot trailing its item, so a wrapped
  line never starts with a separator. New metadata joins this row as another slot. The wide-screen
  pane header uses the same row.
- The status card comes first. Its header shows the status glyph and label and the chat's action:
  "Open in Codex" (deep link), "Copy resume command" for Claude Code (copies `claude --resume <id>`
  and briefly confirms), or "Open in Cursor" (opens the project folder). Each action uses an outlined
  surface with accent text and an icon matching its behavior; placement keeps it easy to find without
  a filled color block. When the status card
  is at most 64rem wide, the action moves below the title and spans the card width so the title keeps
  room on its row. A phone-width fallback covers browsers without container queries.
  Its body depends on state:
  - Needs you: the title adds how long the request has waited ("Needs you · 12d ago"), so fresh and
    stale requests read differently. Then the action label and the request, with recorded options as
    a plain read-only list, then the reminder control and its note ("Hidden in every Your Turn
    tab"). Numbered "Next steps for you" text appears as an ordered list; other request text stays
    as written. The action label is omitted when the request already starts with it, so one fact is
    never stated twice ("Approve pending action in Cursor" needs no Approve label above it).
  - Working: this turn's latest recorded step, as its kind (Ran a command, Edited files, ...) and
    its source title, with commands in mono. The glyph rotates. A recorded command does not mean
    it is still running, and a new turn never shows the previous turn's step. When the chat is
    quiet, the title reads "Working · quiet", the label reads Quiet (in the needs-you color), and a
    note under the step gives the clock time and age of the last activity and says the chat may be
    waiting for approval in the chat's app (Codex, Claude Code, or Cursor) or running a long command.
  - Approval (Cursor only, which reports it): the chat is in Needs you with the action label
    Approve and "Approve pending action in Cursor"; it leaves Needs you when Cursor clears the flag.
    While the latest turn is still open, a "Last recorded step" line shows that turn's last command,
    tool call, or edit (commands in mono). It never claims to be the pending action, and it is hidden
    once the turn has ended, since nothing in an ended turn can still be awaiting approval.
  - Done: "No further action was requested", or "No next action was recorded" when the answer
    skipped the handoff format. When a check in the latest turn failed, either line adds ", but a
    check failed" in the danger color.
  - Loading and missing chats hide the handoff.
- Evidence strip, in the chat header under its title and metadata: chips answering "can I trust it?"
  before the details. Latest turn: N failed, N passed, N without exit code / not recorded
  (per the app's capabilities), No checks after edits, Edited after last check, N files changed;
  session: N decisions. Chips use the check rows' role colors, each jumps to its section (Files opens
  its disclosure), jumps land below the sticky header, and the strip is hidden when there is no
  evidence at all. Missing evidence is a chip of its own rather than an absence.
- What happened: the latest turn's outcome, when there is one, and a files row that expands to the
  latest turn's changed paths relative to the working directory.
- Decisions appear above Checks; More follows both sections.
- Checks, as grouped rows: a warning row when files changed after the last check, when edits had no
  check, or when a check has no exit code; and one row per check with its command and Passed,
  Failed (exit N), or Exit not reported. A missing exit code is never shown as passed, failed, or
  running. Labels follow what the chat's app records (`capabilities` in the thread JSON): Claude
  Code reports only success or failure, so its failures read Failed with no invented exit code;
  Cursor records no results, so its checks read Not recorded under one note saying Cursor doesn't
  record command results.
- Commands and paths use mono and wrap. Command highlighting (executable, path, flag, string,
  operator) is a presentation hint, not shell parsing; every character stays selectable inert text.
- Decisions, as grouped rows: the chosen answer leads, followed by the question and optional reason.
  A long answer has a short preview and a Show full decision action; recorded alternatives have a
  View options action. Put both controls together in the footer, with agent/turn/time metadata
  aligned at the end. View options opens an anchored popover so the list does not change card height;
  Show full decision opens a modal with the complete question, answer, optional reason and
  alternatives. The popover dismisses on Escape or an outside click and returns focus to its
  trigger. Closing the modal with its button or Escape returns to the same card. When the app
  recorded that a question was answered but
  not the answer (Cursor), the question leads, the context line reads "Answered in Cursor; the answer
  was not recorded.", and View options lists all Options (n) in the popover. Three recent decisions
  show directly; older ones sit behind a counted disclosure row. A pending question appears in the
  status card, not here.
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
  motion. Working is the only continuous progress glyph; its folded section heading and row glyphs
  share one rotation phase. Reduced motion disables all transitions and animations. No moving
  capsule, toy drift or parallax changes the approved composition.
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

Help uses a two-column semantic status table and three native disclosures for reminders/quiet, inclusion limits, and connection/privacy. Keep the introduction brief; technical details stay available on demand. The panel owns its scrolling.

Desktop notifications are controlled only in Settings. Appearance and Desktop notifications headings pair lightweight decorative pictograms with persistent text labels.

The full inbox header collapses like a large top app bar: the scene and title fade and scroll away, and only the status tabs stay pinned. Browsers without scroll-linked animation keep the static header rather than pin a slice of the scene. At split-view sizes of at least 1600×800px, only the status tabs sit above both scrollable panes, with no scene, because permanent art would take space from the chat being read. Use those tabs as the sole filter; hide the compact selector. Smaller split views retain the compact header to preserve reading space.

Scrollbars are thin with no track. The page shows a faint thumb; inner panes (the split view's list and chat, the menu, Settings) show it only while pointed at or focused from the keyboard.
The left split pane's scroll edge meets the vertical divider, with the existing column gap retained
as internal end padding so text stays clear of the scrollbar.

Inbox marks are shared through the server and backed up in browser-local storage. Local changes
survive failed saves and are retried. Versioned dismissals and explicit restore markers merge by
timestamp, so an old backup cannot undo a newer restore. Both layers prune marks outside the current
inbox, and blocked local storage leaves server sharing available.

On mobile, group the navigation trigger, Live state and quick theme control at the top right. Move the inbox title to the top-left and keep the phone header compact. Full chat pages retain the Back link on the left.

The footer shows the application version from package metadata and an icon link to the GitHub repository. In split views it sits under the detail pane; the chat list extends to the bottom. Local-session and read-only explanations belong in Help.

Chat sections keep intrinsic row heights and align to the top of their scroll container. Sparse filtered lists must not stretch headings or distribute empty space between heading and rows. Split-view sections have no extra top inset.

Navigation is right-sided at every size: the desktop icon rail sits at the right edge; mobile opens a right-hand drawer with backdrop on its left. Mobile top-row order is Live, theme, then hamburger at the far right, matching DOM/keyboard order. Rail tooltips open toward the content on the left.

Shared content inset is owned by --content-inset:24px desktop and16px below960px. Cards, status panels, dialogs and detail-pane horizontal insets consume it. Split list and sticky detail header share the same top inset. Preserve distinct outer-page gutters and compact control gaps rather than assigning one spacing value to every role.

Session details starts with the complete selectable Thread ID and a labeled copy-icon button. Clipboard success/failure is announced inline; live refresh preserves focus on this static control. A blocked clipboard leaves the ID available for manual copying.
