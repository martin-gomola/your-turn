import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/state-sync.js', import.meta.url), 'utf8');
const A = 'codex:00000000-0000-4000-8000-000000000001';
const B = 'claude:00000000-0000-4000-8000-000000000002';
const empty = () => ({ seen: {}, dismissed: {}, dismissed_at: {} });
function setup({ backup, blocked = false, storage = new Map() } = {}) {
  const window = {}, calls = [];
  let fail = false, httpOk = true;
  if (backup) storage.set('your-turn:inbox-state:v2', typeof backup === 'string' ? backup : JSON.stringify(backup));
  vm.runInNewContext(source, {
    window, AbortSignal, Date: { now: () => 1000 },
    localStorage: {
      getItem(key) { if (blocked) throw Error('blocked'); return storage.get(key) || null; },
      setItem(key, value) { if (blocked) throw Error('blocked'); storage.set(key, value); },
    },
    fetch: async (_, options) => {
      calls.push(JSON.parse(options.body));
      if (fail) throw Error('offline');
      return { ok: httpOk };
    },
  });
  const state = new window.YourTurnState();
  state.retain([A, B]);
  return { state, storage, calls, setOffline: (value) => { fail = value; }, setHttpOk: (value) => { httpOk = value; }, Class: window.YourTurnState };
}

test('browser backup restores an empty server and survives a browser reload', async () => {
  const b = setup();
  await b.state.receive(empty());
  await b.state.save({ dismissed: { [A]: 'request' }, seen: { [A]: '2026-11-01T10:00:00Z' } });
  const reloaded = new b.Class();
  reloaded.retain([A, B]);
  b.calls.length = 0;
  await reloaded.receive(empty());
  assert.equal(b.calls.length, 1);
  assert.equal(b.calls[0].dismissed[A], 'request');
  assert.equal(b.calls[0].seen[A], '2026-11-01T10:00:00Z');
});

test('a newer explicit restore beats an older backup', async () => {
  const b = setup({ backup: { ...empty(), dismissed: { [A]: 'old' }, dismissed_at: { [A]: 10 } } });
  await b.state.receive({ ...empty(), dismissed: { [A]: null }, dismissed_at: { [A]: 20 } });
  assert.equal(b.state.data.dismissed[A], null);
  assert.equal(b.calls.length, 0);
  assert.equal(JSON.parse(b.storage.get(b.Class.storageKey)).dismissed[A], null);
});

test('offline restores persist and retry after reconnect without resurrecting the reminder', async () => {
  const b = setup();
  await b.state.receive({ ...empty(), dismissed: { [A]: 'old' }, dismissed_at: { [A]: 10 } });
  b.setOffline(true);
  await b.state.save({ dismissed: { [A]: null } });
  assert.equal(JSON.parse(b.storage.get(b.Class.storageKey)).dismissed[A], null);
  b.setOffline(false);
  await b.state.receive({ ...empty(), dismissed: { [A]: 'old' }, dismissed_at: { [A]: 10 } });
  assert.equal(b.calls.at(-1).dismissed[A], null);
  assert.equal(b.state.data.dismissed[A], null);
});

test('a failed HTTP response retains the local write for retry', async () => {
  const b = setup();
  await b.state.receive(empty());
  b.setHttpOk(false);
  await b.state.save({ dismissed: { [A]: 'request' } });
  b.setHttpOk(true);
  await b.state.flush();
  assert.equal(b.calls.length, 2);
  assert.equal(b.calls[1].dismissed[A], 'request');
});

test('concurrent tabs merge distinct actions into the local backup', async () => {
  const storage = new Map();
  const a = setup({ storage }), b = setup({ storage });
  await a.state.save({ dismissed: { [A]: 'one' } });
  await b.state.save({ dismissed: { [B]: 'two' } });
  a.state.readBackup();
  assert.equal(a.state.data.dismissed[A], 'one');
  assert.equal(a.state.data.dismissed[B], 'two');
  const backup = JSON.parse(storage.get(a.Class.storageKey));
  assert.equal(backup.dismissed[A], 'one');
  assert.equal(backup.dismissed[B], 'two');
});

test('expired chat backups are pruned and never sent back to the server', async () => {
  const b = setup({ backup: { ...empty(), dismissed: { [A]: 'keep', [B]: 'old' } } });
  b.state.retain([A]);
  await b.state.receive(empty());
  assert.equal(b.state.data.dismissed[B], undefined);
  assert.equal(b.calls[0].dismissed[B], undefined);
});

test('blocked or malformed storage still allows server sharing', async () => {
  for (const options of [{ blocked: true }, { backup: '{broken' }]) {
    const b = setup(options);
    await b.state.receive(empty());
    await b.state.save({ dismissed: { [A]: 'request' } });
    assert.equal(b.calls[0].dismissed[A], 'request');
  }
});

test('older server protocol waits for a restart without a write loop', async () => {
  const b = setup();
  await b.state.receive({ seen: {}, dismissed: {} });
  await b.state.save({ dismissed: { [A]: 'request' } });
  assert.equal(b.calls.length, 0);
  await b.state.receive(empty());
  assert.equal(b.calls.length, 1);
});
