import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/theme.js', import.meta.url), 'utf8');

function browser({ stored = null, dark = false, blocked = false, compact = false, search = '', height = 1200, header = null } = {}) {
  const storage = new Map(stored ? [['theme', stored]] : []);
  if (compact) storage.set('compact-header', 'true');
  if (header !== null) storage.set('compact-header', header);
  const events = new Map();
  const system = { matches: dark, addEventListener: (_, callback) => events.set('system', callback) };
  const root = { dataset: {} };
  let changes = 0;
  const window = {};
  vm.runInNewContext(source, {
    window, Event, URLSearchParams, innerHeight: height,
    location: { search },
    matchMedia: () => system,
    localStorage: {
      getItem(key) { if (blocked) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem(key, value) { if (blocked) throw Error('blocked'); storage.set(key, value); },
      removeItem(key) { if (blocked) throw Error('blocked'); storage.delete(key); },
    },
    document: { documentElement: root, querySelector: () => ({ setAttribute() {} }), dispatchEvent: () => changes++ },
    addEventListener: (name, callback) => events.set(name, callback),
  });
  return { root, storage, events, system, api: window.YourTurnTheme, changes: () => changes };
}

test('system appearance resolves before first paint and follows changes', () => {
  const b = browser({ dark: true });
  assert.equal(b.root.dataset.theme, 'dark');
  b.system.matches = false; b.events.get('system')();
  assert.equal(b.root.dataset.theme, 'light');
  assert.equal(b.api.preference(), 'system');
});

test('header density resolves before first paint and safely defaults when storage is unavailable', () => {
  assert.equal(browser({ compact: true }).root.dataset.header, 'compact');
  assert.equal(browser().root.dataset.header, 'full');
  assert.equal(browser({ compact: true, blocked: true }).root.dataset.header, 'full');
});

test('saved override wins over system until System is selected', () => {
  const b = browser({ stored: 'light', dark: true });
  assert.equal(b.root.dataset.theme, 'light');
  assert.equal(b.api.set('system'), true);
  assert.equal(b.root.dataset.theme, 'dark');
  assert.equal(b.storage.has('theme'), false);
});

test('explicit toggles publish a shared themechange and persist', () => {
  const b = browser();
  b.api.set('dark');
  assert.equal(b.storage.get('theme'), 'dark');
  assert.equal(b.root.dataset.theme, 'dark');
  assert.equal(b.changes(), 2);
});

test('cross-tab updates and cleared storage re-resolve the theme', () => {
  const b = browser({ stored: 'light', dark: true });
  b.storage.set('theme', 'dark'); b.events.get('storage')({ key: 'theme' });
  assert.equal(b.root.dataset.theme, 'dark');
  b.storage.clear(); b.events.get('storage')({ key: null });
  assert.equal(b.api.preference(), 'system');
  assert.equal(b.root.dataset.theme, 'dark');
});

test('a chat opened from Deck resolves dark over a saved light appearance', () => {
  assert.equal(browser({ stored: 'light', search: '?thread=codex%3Aabc&view=deck' }).root.dataset.theme, 'dark');
  assert.equal(browser({ stored: 'light', search: '?view=deck' }).root.dataset.theme, 'light');
  assert.equal(browser({ stored: 'light', search: '?thread=codex%3Aabc' }).root.dataset.theme, 'light');
});

test('unavailable storage still permits a page-local theme choice', () => {
  const b = browser({ blocked: true });
  assert.equal(b.api.set('dark'), false);
  assert.equal(b.root.dataset.theme, 'dark');
  assert.equal(b.api.preference(), 'dark');
  assert.equal(b.storage.size, 0);
});

test('without a saved choice, short windows start with the compact header; a saved choice always wins', () => {
  assert.equal(browser({ height: 1000 }).root.dataset.header, 'compact');
  assert.equal(browser({ height: 1200 }).root.dataset.header, 'full');
  assert.equal(browser({ height: 800, header: 'false' }).root.dataset.header, 'full');
  assert.equal(browser({ height: 1400, header: 'true' }).root.dataset.header, 'compact');
});
