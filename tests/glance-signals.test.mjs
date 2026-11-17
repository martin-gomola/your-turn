// The at-a-glance signals: the action verb, the Deck phase code, the lap delta block and failed-first ordering.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');

// A top-level function or const from app.js, cut at its matching closing brace (or line end for a one-liner).
function extract(start) {
  const from = source.indexOf(start);
  assert.notEqual(from, -1, `${start} not found in app.js`);
  const open = source.indexOf('{', from);
  const lineEnd = source.indexOf('\n', from);
  if (open === -1 || open > lineEnd && !start.startsWith('function')) return source.slice(from, lineEnd);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source[i] === '{') depth++;
    if (source[i] === '}' && --depth === 0) return source.slice(from, i + 1);
  }
  throw new Error(`${start} is unbalanced`);
}

function signals(context = {}) {
  const ctx = vm.createContext({
    deckQuiet: (chat) => Boolean(chat.quiet),
    el: (tag, className, text) => ({ tag, className, textContent: text, dataset: {} }),
    ...context,
  });
  vm.runInContext([
    extract('function stepVerb('), extract('const DECK_PHASES'), extract('function deckPhase('),
    extract('function lapSeconds('), extract('function lapClock('), extract('const mean ='),
    extract('function deckLapDelta('), extract('function deckDeltaMark('),
    'Object.assign(this, { stepVerb, deckPhase, deckLapDelta, deckDeltaMark });',
  ].join('\n'), ctx);
  return ctx;
}

const at = (minutesAgo) => new Date(Date.now() - minutesAgo * 60_000).toISOString();
// Finished laps of `minutes` each, then a live lap running for `current` minutes; sectors mark per-step times.
function laps(minutes, current, { quiet = false } = {}) {
  const done = minutes.map((m, i) => ({ status: 'done', started_at: at(200 - i * 20), ended_at: at(200 - i * 20 - m), sectors: { think: 1 } }));
  return { quiet, laps: [...done, { status: 'working', started_at: at(current), sectors: {} }] };
}

test('the primary action names the step it completes, and only for a waiting chat', () => {
  const { stepVerb } = signals();
  assert.equal(stepVerb({ next_kind: 'approve' }, true), 'Approve');
  assert.equal(stepVerb({ next_kind: 'answer' }, true), 'Answer');
  assert.equal(stepVerb({ question: 'Which one?', next_kind: 'unknown' }, true), 'Answer');
  assert.equal(stepVerb({ next_kind: 'run' }, true), 'Run');
  assert.equal(stepVerb({ next_kind: 'review' }, true), 'Open');
  assert.equal(stepVerb({ next_kind: 'approve' }, false), 'Open');
});

test('the Deck phase code: a failed check and a quiet run outrank the group', () => {
  const { deckPhase } = signals();
  assert.equal(deckPhase({}, 'waiting'), 'ack');
  assert.equal(deckPhase({}, 'working'), 'run');
  assert.equal(deckPhase({}, 'new'), 'done');
  assert.equal(deckPhase({ quiet: true }, 'working'), 'idle');
  assert.equal(deckPhase({ check_state: 'failed' }, 'new'), 'fail');
  assert.equal(deckPhase({ check_state: 'failed', quiet: true }, 'working'), 'fail');
});

test('the delta block is muted within 20% of the average, amber above it and red past 50%', () => {
  const { deckLapDelta, deckDeltaMark } = signals();
  const tone = (current) => deckDeltaMark(deckLapDelta(laps([10, 10], current)), 'x').dataset.tone;
  assert.equal(tone(11), 'slower');
  assert.equal(tone(13), 'amber');
  assert.equal(tone(16), 'red');
  assert.equal(tone(8), 'faster');
  assert.match(deckDeltaMark(deckLapDelta(laps([10, 10], 13)), 'x').textContent, /^\+3:00$/);
});

test('no delta without per-step times, without finished laps, or for a quiet live turn', () => {
  const { deckLapDelta } = signals();
  const minuteStamps = laps([10, 10], 13);
  for (const lap of minuteStamps.laps) lap.sectors = {};
  assert.equal(deckLapDelta(minuteStamps), null);
  assert.equal(deckLapDelta(laps([], 13)), null);
  assert.equal(deckLapDelta(laps([10, 10], 30, { quiet: true })), null);
});

test('Needs you lists a failed check first, then the longest wait', () => {
  const context = vm.createContext({
    NEW_WINDOW_MS: 86400000, shared: { dismissed: {} }, seen: { get: () => '' },
    chatKey: (chat) => chat.key, SECTIONS: ['waiting', 'working', 'new', 'earlier'].map((key) => ({ key })),
    waitingSince: (chat) => chat.turn_ended_at || chat.updated_at,
  });
  vm.runInContext(source.slice(source.indexOf('function needsAttention('), source.indexOf('function chatSummary(')) +
    source.slice(source.indexOf('function groupChats('), source.indexOf('function quietFor(')) +
    '\nObject.assign(this, { groupChats });', context);
  const waiting = (key, minutesAgo, check_state = '') => ({ key, status: 'waiting', needs_you: true, attention_key: key,
    turn_ended_at: at(minutesAgo), updated_at: at(minutesAgo), check_state });
  // Array.from: the list comes from the VM's realm, whose Array prototype deepStrictEqual would reject.
  const order = Array.from(context.groupChats([waiting('old', 90), waiting('failed', 5, 'failed'), waiting('older', 120)])
    .get('waiting'), (chat) => chat.key);
  assert.deepEqual(order, ['failed', 'older', 'old']);
});
