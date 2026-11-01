import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext(source.slice(source.indexOf('const AWAY_DIGEST_MS'), source.indexOf('// End pure triage helpers.')) +
  '\nObject.assign(this, { AWAY_DIGEST_MS, filterInbox, awayDelta, queueTarget, shortcutBlocked });', context);

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
