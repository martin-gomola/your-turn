import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const context = vm.createContext({});
vm.runInContext('function chatKey(chat) { return chat.key || chat.id; }\n' +
  source.slice(source.indexOf('const AWAY_DIGEST_MS'), source.indexOf('// End pure triage helpers.')) +
  '\nObject.assign(this, { deckDelegates });', context);

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

test('a parent the Deck hides leaves its children in the queue', () => {
  const chats = [{ id: 'boss', cwd: '/r', started_at: '1' }, { id: 'relay', cwd: '/r/.relay/a', started_at: '2' }];
  const { top, children } = context.deckDelegates(chats, (parent) => parent.id !== 'boss');
  assert.deepEqual(ids(top), ['boss', 'relay']);
  assert.equal(children.size, 0);
});
