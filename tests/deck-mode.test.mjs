import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const controls = source.slice(source.indexOf('function setDeckMode('), source.indexOf('const deckLaunchApps ='));

function setup({ mode = 'dashboard', deckView = true, threadId = '', mobile = false, blocked = false } = {}) {
  const buttons = ['dashboard', 'simple'].map(mode => ({
    dataset: { deckMode: mode }, setAttribute(name, value) { this[name] = value; },
  }));
  const storage = new Map(), events = {};
  const nodes = {
    'deck-view': { dataset: {} }, 'deck-launcher': {},
    'deck-mode-switch': {
      querySelectorAll: () => buttons,
      addEventListener: (name, fn) => { events[name] = fn; },
    },
  };
  let closed = 0;
  vm.runInNewContext(controls, {
    $: id => nodes[id], deckMode: mode, deckView, threadId,
    document: { body: { dataset: {} } },
    drawer: { matches: mobile }, closeNavigation: () => { closed++; },
    localStorage: { setItem(key, value) { if (blocked) throw Error('blocked'); storage.set(key, value); } },
  });
  return { nodes, buttons, storage, closed: () => closed,
    click: mode => events.click({ target: { closest: () => buttons.find(b => b.dataset.deckMode === mode) } }),
  };
}

test('Dashboard starts selected without writing a preference; saved Launcher still works', () => {
  for (const mode of ['dashboard', 'simple']) {
    const b = setup({ mode });
    assert.equal(b.nodes['deck-view'].dataset.mode, mode);
    assert.equal(b.nodes['deck-launcher'].hidden, mode !== 'simple');
    assert.equal(b.buttons.filter(b => b['aria-pressed'] === 'true').length, 1);
    assert.equal(b.storage.size, 0);
  }
});

test('rail selection persists the existing preference and closes only the mobile drawer', () => {
  for (const mobile of [false, true]) {
    const b = setup({ mobile });
    b.click('simple');
    assert.equal(b.nodes['deck-launcher'].hidden, false);
    assert.equal(b.storage.get('your-turn.deck.mode'), 'simple');
    assert.equal(b.closed(), Number(mobile));
    b.click('dashboard');
    assert.equal(b.nodes['deck-launcher'].hidden, true);
    assert.equal(b.storage.get('your-turn.deck.mode'), 'dashboard');
  }
});

test('blocked storage keeps selection usable on this page', () => {
  const b = setup({ blocked: true });
  b.click('simple');
  assert.equal(b.nodes['deck-view'].dataset.mode, 'simple');
  assert.equal(b.buttons[1]['aria-pressed'], 'true');
});

test('mode controls are scoped to Deck, not Inbox or a chat opened from Deck', () => {
  for (const options of [{ deckView: false }, { threadId: 'codex:chat' }]) {
    assert.equal(setup(options).nodes['deck-mode-switch'].hidden, true);
  }
});
