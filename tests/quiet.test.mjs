import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const helpers = source.slice(source.indexOf('const APP_NAME'), source.indexOf('const QUIET_NOTIFY_MS'));
const context = vm.createContext({});
vm.runInContext(`${helpers}\nObject.assign(this, { quietHint, unavailableNote, unverifiedNote, liveUnverified, summaryText });`, context);

test('quiet chat that never asks for approval is not said to wait for it', () => {
  const hint = context.quietHint({ harness: 'codex', approval_policy: 'never' });
  assert.equal(hint, 'No activity recorded. It may still be running, or it may be stuck.');
  assert.doesNotMatch(context.quietHint({ harness: 'codex', approval_policy: 'never', pending_tool: 'make test' }), /approval/);
});

for (const policy of ['on-request', '', undefined]) {
  test(`quiet chat with approval policy ${JSON.stringify(policy)} may be waiting for approval`, () => {
    const hint = context.quietHint({ harness: 'codex', approval_policy: policy });
    assert.match(hint, /^No activity recorded\. It may be waiting for your approval in Codex, or running a long command\.$/);
  });
}

test('a chat without content says its state is unknown and labels the app summary as the app’s', () => {
  const chat = { harness: 'cursor', status: 'unknown', content_available: false, summary: 'Edited README.md' };
  assert.equal(context.summaryText(chat), 'Cursor summary: Edited README.md');
  assert.equal(context.summaryText({ ...chat, summary: '' }), '');
  assert.match(context.unavailableNote(chat), /^Cursor keeps no local record of this chat’s messages, so whether it is working or finished is unknown\.$/);
});

test('only a working chat whose app may not write while working is unverifiable live', () => {
  const cursor = { harness: 'cursor', status: 'working', capabilities: { live_activity: false } };
  assert.equal(context.liveUnverified(cursor), true);
  assert.equal(context.liveUnverified({ ...cursor, status: 'done' }), false);
  assert.equal(context.liveUnverified({ harness: 'claude', status: 'working', capabilities: { live_activity: true } }), false);
  // Older payloads without capabilities keep the quiet detection.
  assert.equal(context.liveUnverified({ harness: 'codex', status: 'working' }), false);
  assert.match(context.unverifiedNote(cursor), /^This is the last recorded state\. Cursor may not record activity while a turn runs/);
});

test('quiet Claude Code chat keeps its pending call in the hint', () => {
  const hint = context.quietHint({ harness: 'claude', pending_tool: 'Bash: make test' });
  assert.match(hint, /Its last call has no result yet \(Bash: make test\): it may be waiting for your approval in Claude Code/);
});
