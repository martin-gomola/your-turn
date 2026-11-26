import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext('function chatKey(chat) { return chat.key || chat.id; }\n' +
  source.slice(source.indexOf('const AWAY_DIGEST_MS'), source.indexOf('// End pure triage helpers.')) +
  '\nObject.assign(this, { deckDelegates, subtaskRollup, SUBTASK_ORDER });', context);

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
