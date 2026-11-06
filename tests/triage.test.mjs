import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('const AWAY_DIGEST_MS'), source.indexOf('// End pure triage helpers.')) +
  '\nObject.assign(this, { AWAY_DIGEST_MS, filterInbox, awayDelta, queueTarget, focusAfterRemoval, shortcutBlocked, contextFill, contextSize, deckOrder, latestQuota, windowLabel, untilShort, deckTelemetry, deckMagazine, deckSwipe, deckUrgent, deckTerminalState, deckHandoffText, deckCanReview, deckFallback });', context);

test('working sessions cannot be dismissed even when categorized as a pending request', () => {
  const working = {status:'working',attention_key:'pending'};
  for (const kind of ['working','waiting','new','earlier']) assert.equal(context.deckCanReview(working,kind),false);
  assert.equal(context.deckCanReview({status:'done',attention_key:'pending'},'waiting'),true);
  assert.equal(context.deckCanReview({status:'done'},'new'),true);
  assert.equal(context.deckCanReview({status:'done'},'earlier'),false);
  assert.equal(context.deckCanReview({status:'done'},'waiting'),false);
});

test('Earlier fallback depends on the entire fleet, not an empty selected filter', () => {
  assert.equal(context.deckFallback({waiting:1,working:0,new:0,earlier:20}),'active');
  assert.equal(context.deckFallback({waiting:0,working:1,new:0,earlier:20}),'active');
  assert.equal(context.deckFallback({waiting:0,working:0,new:1,earlier:20}),'active');
  assert.equal(context.deckFallback({waiting:0,working:0,new:0,earlier:20}),'earlier');
  assert.equal(context.deckFallback({waiting:0,working:0,new:0,earlier:0}),'standby');
});

test('terminal shows recorded commands and pending calls without pretending unsupported or quiet sources are live', () => {
  const chat = { capabilities:{live_activity:true}, activity_summary:'Previous caption', pending_tool:'Bash: sed -n 1,20p src/app.py',
    activity_log:[{kind:'command',title:'git diff --check',at:'2026-11-04T12:00:00Z'}] };
  const state = context.deckTerminalState(chat);
  assert.equal(state.label,'CALL PENDING');
  assert.equal(state.live,true);
  assert.equal(state.events.at(-1).title,'sed -n 1,20p src/app.py');
  assert.equal(state.events.at(-1).pending,true);
  assert.equal(context.deckTerminalState({...chat,quiet:true}).live,false);
  assert.equal(context.deckTerminalState(chat,false).label,'OFFLINE');
  const unsupported = context.deckTerminalState({...chat,capabilities:{live_activity:false}});
  assert.equal(unsupported.label,'LAST KNOWN STATE');
  assert.equal(unsupported.events.length,0);
  assert.equal(unsupported.fallback,'Awaiting agent completion checkpoint…');
});

test('missing handoffs use honest checkpoint copy, ignore old recaps and never invent a next action', () => {
  const chat = { outcome:' ',recap:'A stale previous outcome',next_kind:'unknown',next_text:' ',question:' ' };
  const waiting = context.deckHandoffText(chat,'waiting');
  assert.equal(waiting.outcome,'');  // No outcome line: the chat is waiting on you, not still running.
  assert.equal(waiting.pending,true);
  assert.equal(waiting.next,'Open this chat to review the handoff.');
  assert.equal(context.deckHandoffText(chat,'new').outcome,'Completion checkpoint not recorded yet.');
  assert.equal(context.deckHandoffText({...chat,next_kind:'none'},'new').next,'No further action requested.');
  assert.equal(context.deckHandoffText({...chat,outcome:'Fixed the test',question:'Approve the change?'},'waiting').next,'Approve the change?');
});

test('urgency starts strictly after fifteen minutes and ignores unknown or future waits', () => {
  const now = Date.parse('2026-11-04T12:00:00Z');
  assert.equal(context.deckUrgent(['2026-11-04T11:45:00Z'], now), false);
  assert.equal(context.deckUrgent(['2026-11-04T11:44:59Z'], now), true);
  assert.equal(context.deckUrgent(['unknown', '2026-11-04T12:01:00Z'], now), false);
  assert.equal(context.deckUrgent([], now), false);
});

test('a fast horizontal flick advances only the hero, while vertical intent wins', () => {
  assert.equal(context.deckSwipe(-22, 2, 390, true, -1), 'next');
  assert.equal(context.deckSwipe(-22, 2, 390, true, 0), '');
  assert.equal(context.deckSwipe(-22, 2, 390, false, -1), '');
  assert.equal(context.deckSwipe(-22, 80, 390, true, -1), '');
  assert.equal(context.deckSwipe(-22, 2, 390, true, 1), '');
});

test('legacy working clear markers never hide a running session', () => {
  const dismissed = { task: 'cleared:turn-1' };
  const helpers = vm.createContext({ needsAttention: c => c.needs_you, isNewResult: c => c.status === 'done',
    chatKey: c => c.id, shared: { dismissed } });
  vm.runInContext(source.slice(source.indexOf('function sectionOf('), source.indexOf('function chatSummary(')) + '\nthis.sectionOf = sectionOf;', helpers);
  const chat = { id:'task', status:'working', working_since:'turn-1' };
  assert.equal(helpers.sectionOf(chat), 'working');
  assert.equal(chat.status, 'working');
  assert.equal(helpers.sectionOf({ ...chat, working_since:'turn-2' }), 'working');
  assert.equal(helpers.sectionOf({ ...chat, needs_you:true }), 'waiting');
  assert.equal(helpers.sectionOf({ ...chat, status:'done' }), 'new');
  dismissed.task = null;
  assert.equal(helpers.sectionOf(chat), 'working');
});

test('six-cell magazine apportions fleet counts and handles focused and empty states', () => {
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 7, working: 1, new: 4 })), ['waiting', 'waiting', 'waiting', 'working', 'new', 'new']);
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 1, working: 1, new: 1 })), ['waiting', 'working', 'new', '', '', '']);
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 2, working: 0, new: 1 })), ['waiting', 'waiting', 'new', '', '', '']);
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 7, working: 1, new: 4 }, 'working')), ['working', '', '', '', '', '']);
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 7, working: 1, new: 3 }, 'new')), ['new', 'new', 'new', '', '', '']);
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 7, working: 1, new: 4 }, 'waiting')), Array(6).fill('waiting'));
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 0, working: 6, new: 0 }, 'working')), Array(6).fill('working'));
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 7, working: 0, new: 4 }, 'working')), Array(6).fill(''));
  assert.deepEqual(Array.from(context.deckMagazine({ waiting: 0, working: 0, new: 0 })), Array(6).fill(''));
});

test('Inbox ignores Deck review markers and uses its original seen-state rule', () => {
  const key = 'codex:chat';
  const at = new Date().toISOString();
  const dismissed = { [key]: `reviewed:${at}` };
  const helpers = vm.createContext({ hasAttention: () => false, hasResult: () => true, chatKey: () => key,
    NEW_WINDOW_MS: 86400000, seen: { get: () => '' }, shared: { dismissed } });
  vm.runInContext(source.slice(source.indexOf('function isNewResult('), source.indexOf('function sectionOf(')) + '\nthis.isNewResult = isNewResult;', helpers);
  assert.equal(helpers.isNewResult({ turn_ended_at: at }), true);
  assert.equal(helpers.isNewResult({ turn_ended_at: new Date(Date.now() + 1000).toISOString() }), true);
  dismissed[key] = null;
  assert.equal(helpers.isNewResult({ turn_ended_at: at }), true);
});

test('hero swipes navigate, row swipes act, and vertical or small drags do neither', () => {
  assert.equal(context.deckSwipe(-70, 5, 390, true), 'next');
  assert.equal(context.deckSwipe(70, 5, 390, true), 'previous');
  assert.equal(context.deckSwipe(-90, 10, 800), 'review');
  assert.equal(context.deckSwipe(90, 10, 800), 'focus');
  assert.equal(context.deckSwipe(-20, 0, 390), '');
  assert.equal(context.deckSwipe(90, 120, 390), '');
});

test('deck telemetry uses windowed logs, account quota, active chats and known context', () => {
  const now = Date.parse('2026-11-04T12:00:00Z');
  const working = { harness: 'codex', context_used: 900, context_window: 1000,
    usage_minutes: [['2026-11-04T11:50:00Z', 30000], ['2026-11-04T11:00:00Z', 5000]],
    rate_limits_at: '2026-11-04T11:59:00Z', rate_limits: [{ window_minutes: 300, used_percent: 16 }] };
  const chats = [working, { harness: 'claude', message_minutes: ['2026-11-04T06:59:00Z', '2026-11-04T08:00:00Z', '2026-11-04T13:00:00Z'] }];
  const metrics = context.deckTelemetry(chats, [working], ['2026-11-04T10:11:00Z'], now);
  assert.deepEqual(Array.from(metrics, (m) => m.value), ['1h', '1 ACTIVE / 84%', '2.0k/min', '90%', '1h 49m', '0.0M TOK']);
  assert.equal(metrics[0].label, 'CLAUDE RESET EST.');
  // A captured 5-hour window replaces the estimate, so the strip and the usage card agree.
  const captured = { harness: 'claude', rate_limits_at: '2026-11-04T11:58:00Z',
    rate_limits: [{ window_minutes: 300, used_percent: 18, resets_at: '2026-11-04T15:00:00Z' }] };
  const reported = context.deckTelemetry([...chats, captured], [working], [], now)[0];
  assert.deepEqual([reported.label, reported.value], ['CLAUDE RESET', '3h']);
  assert.equal(metrics[3].tone, 'red');
  const empty = context.deckTelemetry([], [], [], now);
  assert.deepEqual(Array.from(empty, (m) => m.value), ['—', '0 ACTIVE', '—', '—', '—', '—']);
  assert.equal(context.deckTelemetry([{ harness: 'claude' }], [], [], now)[0].value, 'READY');
});

test('deck order ignores latest writes: working by start, new by arrival, others untouched', () => {
  const working = [{ id: 'b', working_since: '2026-11-03T10:05:00Z' }, { id: 'a', working_since: '2026-11-03T10:00:00Z' }];
  const fresh = [{ id: 'y', turn_ended_at: '2026-11-03T11:00:00Z' }, { id: 'x', turn_ended_at: '2026-11-03T09:00:00Z' }];
  const waiting = [{ id: 'w2' }, { id: 'w1' }];
  const order = context.deckOrder(new Map([['waiting', waiting], ['working', working], ['new', fresh], ['earlier', []]]));
  const ids = (key) => [...order.get(key)].map((c) => c.id);
  assert.deepEqual(ids('working'), ['a', 'b']);
  assert.deepEqual(ids('new'), ['x', 'y']);
  assert.deepEqual(ids('waiting'), ['w2', 'w1']);
  assert.deepEqual(working.map((c) => c.id), ['b', 'a'], 'input lists are not mutated');
});

test('context size uses the reported window, infers 1M for Claude past 200K, else unknown', () => {
  assert.equal(context.contextSize({ harness: 'codex', context_window: 272000, context_used: 5 }), 272000);
  assert.equal(context.contextSize({ harness: 'claude', context_window: 0, context_used: 254800 }), 1000000);
  assert.equal(context.contextSize({ harness: 'claude', context_window: 0, context_used: 150000 }), 0);
  assert.equal(context.contextSize({ harness: 'cursor', context_window: 0, context_used: 300000 }), 0);
});

test('quota comes from the newest report and drops windows that already reset', () => {
  const now = Date.parse('2026-11-03T12:00:00Z');
  const five = { used_percent: 18, window_minutes: 300, resets_at: '2026-11-03T15:00:00Z' };
  const ended = { used_percent: 90, window_minutes: 10080, resets_at: '2026-11-03T11:00:00Z' };
  const chats = [{ rate_limits_at: '2026-11-03T10:00:00Z', rate_limits: [ended] },
    { rate_limits_at: '2026-11-03T11:30:00Z', rate_limits: [five, ended] }, { rate_limits_at: '', rate_limits: [] }];
  assert.deepEqual(context.latestQuota(chats, now).map((w) => w.window_minutes), [300]);
  assert.deepEqual([...context.latestQuota([{ rate_limits_at: '' }], now)], []);
  assert.deepEqual([300, 10080, 1440, 90].map(context.windowLabel), ['5h', 'Week', '1d', '90m']);
  assert.deepEqual(['2026-11-03T12:00:20Z', '2026-11-03T12:12:00Z', '2026-11-03T16:00:00Z', '2026-11-09T12:00:00Z', '2026-11-03T11:00:00Z']
    .map((iso) => context.untilShort(iso, now)), ['<1m', '12m', '4h', '6d', '']);
});

test('context fill bands at 50% and 80%, capped, and unknown without a window', () => {
  assert.deepEqual({ ...context.contextFill(400, 1000) }, { percent: 40, level: 'ok' });
  assert.deepEqual({ ...context.contextFill(500, 1000) }, { percent: 50, level: 'filling' });
  assert.deepEqual({ ...context.contextFill(800, 1000) }, { percent: 80, level: 'heavy' });
  assert.equal(context.contextFill(1200, 1000).percent, 100);
  assert.equal(context.contextFill(5000, 0), null);
  assert.equal(context.contextFill(0, 1000), null);
});

test('digest requires ten minutes and only counts newly actionable chats', () => {
  const before = new Set(['old', 'resolved']);
  const after = new Set(['old', 'new']);
  assert.deepEqual([...context.awayDelta(before, after, context.AWAY_DIGEST_MS - 1)], []);
  assert.deepEqual([...context.awayDelta(before, after, context.AWAY_DIGEST_MS)], ['new']);
  assert.deepEqual([...context.awayDelta(after, after, context.AWAY_DIGEST_MS)], []);
});

for (const field of ['title', 'project', 'outcome', 'next_step', 'next_text', 'recap', 'decisions', 'changed_files']) {
  test(`search includes ${field}, case insensitive and without mutating the inbox`, () => {
    const row = { id: 'a', [field]: field === 'decisions' ? [{ chosen: 'OAuth' }] : field === 'changed_files' ? ['src/OAuth.js'] : 'OAuth' };
    const rows = [row, { id: 'b' }];
    assert.deepEqual(context.filterInbox(rows, '  OAUTH ').map((r) => r.id), ['a']);
    assert.equal(context.filterInbox(rows, '').length, 2);
    assert.equal(context.filterInbox(rows, 'not found').length, 0);
    assert.equal(rows.length, 2);
  });
}

test('queue navigation follows visible order, clamps ends and starts on the first row', () => {
  const keys = ['waiting', 'working', 'finished'];
  assert.equal(context.queueTarget(keys, '', 1), 'waiting');
  assert.equal(context.queueTarget(keys, '', -1), 'waiting');
  assert.equal(context.queueTarget(keys, 'waiting', 1), 'working');
  assert.equal(context.queueTarget(keys, 'working', -1), 'waiting');
  assert.equal(context.queueTarget(keys, 'waiting', -1), 'waiting');
  assert.equal(context.queueTarget(keys, 'finished', 1), 'finished');
  assert.equal(context.queueTarget([], '', 1), '');
});

test('dismissing a row moves focus to the next row, or the previous one at the end', () => {
  const keys = ['a', 'b', 'c'];
  assert.equal(context.focusAfterRemoval(keys, 'a'), 'b');
  assert.equal(context.focusAfterRemoval(keys, 'b'), 'c');
  assert.equal(context.focusAfterRemoval(keys, 'c'), 'b');
  assert.equal(context.focusAfterRemoval(['a'], 'a'), '');
  assert.equal(context.focusAfterRemoval(keys, 'missing'), '');
});

test('shortcuts respect text entry and modal dialogs', () => {
  assert.equal(context.shortcutBlocked({ closest: () => ({}) }, false), true);
  assert.equal(context.shortcutBlocked({ closest: () => null }, true), true);
  assert.equal(context.shortcutBlocked({ closest: () => null }, false), false);
});

test('working captions use recorded live activity and never imply live Cursor activity', () => {
  const helpers = vm.createContext({ hasAttention: () => false, summaryText: () => '' });
  vm.runInContext(source.slice(source.indexOf('function chatSummary('), source.indexOf('function renderRow(')) +
    '\nthis.summary = chatSummary;', helpers);
  const chat = { status: 'working', activity_summary: 'make test', outcome: 'Previous result', capabilities: { live_activity: true } };
  assert.equal(helpers.summary(chat), 'make test');
  assert.equal(helpers.summary({ ...chat, capabilities: { live_activity: false } }), 'Previous result');
});

test('deck telemetry spends color only on a signal: neutral by default, amber for a wait, thresholds for context', () => {
  const now = Date.parse('2026-11-04T12:00:00Z');
  const tones = (waits, used) => Array.from(context.deckTelemetry([{ harness: 'codex', context_used: used, context_window: 1000 }], [], waits, now), (m) => m.tone);
  assert.deepEqual(tones([], 100), ['', '', '', '', '', '']);
  assert.deepEqual(tones(['2026-11-04T11:00:00Z'], 800), ['', '', '', 'amber', 'amber', '']);
});
