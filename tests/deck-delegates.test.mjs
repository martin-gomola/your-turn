import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext('function chatKey(chat) { return chat.key || chat.id; }\n' +
  source.slice(source.indexOf('const AWAY_DIGEST_MS'), source.indexOf('// End pure triage helpers.')) +
  '\nObject.assign(this, { deckDelegates, subtaskRollup, SUBTASK_ORDER, workerSlug, isSupersededSubtask, markSuperseded,' +
  ' effectiveCheckState, subtaskMetrics, formatCompactTokens });', context);

const ids = (chats) => Array.from(chats, (chat) => chat.id);

test('relay workers and Codex subagents ride under their orchestrator', () => {
  const chats = [
    { id: 'old', cwd: '/r', started_at: '1' },
    { id: 'boss', cwd: '/r', started_at: '2' },
    { id: 'relay', cwd: '/r/.relay/fix-csv', started_at: '3' },
    { id: 'sub', cwd: '/elsewhere', parent_id: 'boss', started_at: '4' },
    { id: 'stray', cwd: '/other/.relay/x', started_at: '5' },
  ];
  const { top, children } = context.deckDelegates(chats);
  assert.deepEqual(ids(top), ['old', 'boss', 'stray']);
  assert.deepEqual(ids(children.get('boss')), ['relay', 'sub']);
});

test('a delegate-code worker rides under the latest chat that started before it in its repo', () => {
  const chats = [
    { id: 'old', cwd: '/r', started_at: '1' },
    { id: 'boss', cwd: '/r', started_at: '2' },
    { id: 'worker', cwd: '/r/.delegate-code/loop-gaps', started_at: '3' },
    { id: 'later', cwd: '/r', started_at: '4' },
  ];
  const { top, children, inferred } = context.deckDelegates(chats);
  assert.deepEqual(ids(top), ['old', 'boss', 'later']);
  assert.deepEqual(ids(children.get('boss')), ['worker']);
  assert.deepEqual([...inferred], ['worker']);
});

test('a worker prefers the orchestrator still running over a newer idle chat in the repo', () => {
  const chats = [
    { id: 'boss', cwd: '/r', started_at: '2', status: 'working', updated_at: '2' },
    { id: 'idle', cwd: '/r', started_at: '3', status: 'done', updated_at: '3' },
    { id: 'worker', cwd: '/r/.delegate-code/a', started_at: '5', status: 'working', updated_at: '6' },
  ];
  assert.equal(context.deckDelegates(chats).parents.get('worker').id, 'boss');
});

test('a parent the Deck hides leaves its children in the queue', () => {
  const chats = [{ id: 'boss', cwd: '/r', started_at: '1' }, { id: 'relay', cwd: '/r/.relay/a', started_at: '2' }];
  const { top, children } = context.deckDelegates(chats, (parent) => parent.id !== 'boss');
  assert.deepEqual(ids(top), ['boss', 'relay']);
  assert.equal(children.size, 0);
});

test('a relay child records its inferred parent; a named parent is not inferred', () => {
  const chats = [
    { id: 'boss', cwd: '/r', started_at: '1' },
    { id: 'relay', cwd: '/r/.relay/a', started_at: '2' },
    { id: 'sub', cwd: '/x', parent_id: 'boss', started_at: '3' },
  ];
  const { parents, inferred } = context.deckDelegates(chats);
  assert.equal(parents.get('relay').id, 'boss');
  assert.equal(parents.get('sub').id, 'boss');
  assert.deepEqual([...inferred], ['relay']);
});

test('the subtask roll-up counts done work and names exceptions, most urgent first', () => {
  assert.deepEqual({ ...context.subtaskRollup(['quiet', 'done']) }, { text: '1 of 2 done · 1 quiet', tone: 'quiet' });
  assert.deepEqual({ ...context.subtaskRollup(['done', 'quiet', 'waiting', 'quiet', 'working']) },
    { text: '1 of 5 done · 1 needs you · 2 quiet', tone: 'waiting' });
  assert.deepEqual({ ...context.subtaskRollup(['working', 'done']) }, { text: '1 of 2 done', tone: '' });
  assert.equal(context.SUBTASK_ORDER.indexOf('failed') < context.SUBTASK_ORDER.indexOf('quiet'), true);
});

test('a worker slug is the first folder under .delegate-code or .relay', () => {
  assert.equal(context.workerSlug({ cwd: '/r/.delegate-code/loop-gaps' }), 'loop-gaps');
  assert.equal(context.workerSlug({ cwd: '/r/.relay/fix-csv/src/app' }), 'fix-csv');
  assert.equal(context.workerSlug({ cwd: '/r/src' }), '');
  assert.equal(context.workerSlug({}), '');
});

const settledBoss = { id: 'boss', cwd: '/r', status: 'done', needs_you: false, turn_ended_at: '2026-11-27T12:00:00Z' };
const staleWorker = (extra = {}) => ({ id: 'w', cwd: '/r/.delegate-code/a', status: 'done', needs_you: true, next_kind: 'review',
  next_basis: 'handoff', turn_ended_at: '2026-11-27T11:00:00Z', ...extra });

test('a worker handoff is superseded once its orchestrator settles a later turn or its worktree is gone', () => {
  assert.equal(context.isSupersededSubtask(staleWorker(), settledBoss), true);
  assert.equal(context.isSupersededSubtask(staleWorker(), null), false);
  // The orchestrator still working, waiting, needing you, not yet past the worker, or with no recorded turn end
  // (a newer file mtime is not one) keeps the handoff live.
  for (const boss of [{ status: 'working' }, { status: 'waiting' }, { needs_you: true }, { turn_ended_at: '2026-11-27T10:00:00Z' },
    { turn_ended_at: '', updated_at: '2026-11-27T13:00:00Z' }]) {
    assert.equal(context.isSupersededSubtask(staleWorker(), { ...settledBoss, ...boss }), false, JSON.stringify(boss));
  }
  // A removed worktree supersedes even when the orchestrator is still running or out of view.
  assert.equal(context.isSupersededSubtask(staleWorker({ worktree_removed: true }), { ...settledBoss, status: 'working' }), true);
  assert.equal(context.isSupersededSubtask(staleWorker({ worktree_removed: true }), null), true);
  assert.equal(context.isSupersededSubtask(staleWorker({ worktree_removed: true, status: 'working' }), null), false);
  // Never: a live run, a live wait, a source-level approval or question, a failed check.
  for (const extra of [{ status: 'working' }, { status: 'waiting' }, { next_basis: 'source' }, { check_state: 'failed' }]) {
    assert.equal(context.isSupersededSubtask(staleWorker({ worktree_removed: true, ...extra }), settledBoss), false, JSON.stringify(extra));
  }
});

test('markSuperseded flags only subtasks under a settled orchestrator', () => {
  const chats = context.markSuperseded([{ ...settledBoss, started_at: '1' }, staleWorker({ started_at: '2' }),
    { id: 'solo', cwd: '/x', status: 'done', needs_you: true, turn_ended_at: '2026-11-27T09:00:00Z' }]);
  assert.deepEqual(chats.map((chat) => chat.superseded), [false, true, false]);
});

test('an orchestrator that passed a check later clears a superseded worker\'s unchecked edits, never a failure', () => {
  const passed = { ...settledBoss, check_passed_at: '2026-11-27T11:30:00Z' };
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'unchecked' }), passed), '');
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'unchecked' }), settledBoss), 'unchecked');
  // A parent check from before the worker ended (10:00 vs 11:00) clears nothing, even with the worktree gone.
  const earlier = { ...settledBoss, check_passed_at: '2026-11-27T10:00:00Z' };
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'unchecked', worktree_removed: true }), earlier), 'unchecked');
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'unchecked', turn_ended_at: '' }), passed), 'unchecked');
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'unchecked', status: 'working' }), passed), 'unchecked');
  assert.equal(context.effectiveCheckState(staleWorker({ check_state: 'failed' }), passed), 'failed');
  assert.equal(context.effectiveCheckState({ check_state: '' }, null), '');
});

test('subtask metrics sum time and output tokens compactly and say nothing when none were recorded', () => {
  assert.equal(context.subtaskMetrics([{ active_seconds: 334, output_tokens: 24157, total_tokens: 4e6 },
    { active_seconds: 222, output_tokens: 17122 }]), '9m 16s · 41.3K out');
  assert.equal(context.subtaskMetrics([{ active_seconds: 45, output_tokens: 0 }]), '45s');
  assert.equal(context.subtaskMetrics([{ active_seconds: 3900 }]), '1h 5m');
  assert.equal(context.subtaskMetrics([{ turn_count: 3, total_tokens: 9000 }]), '');
  assert.equal(context.subtaskMetrics([{}]), '');
  assert.equal(context.formatCompactTokens(520000), '520K');
});
