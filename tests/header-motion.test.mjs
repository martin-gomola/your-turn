import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const controls = source.slice(source.indexOf('  const headerToggle ='), source.indexOf('  const search = $("inbox-search")'));
function setup({ reduced = false, supported = true, open = '' } = {}) {
  const root = { dataset: { header: 'full' } }, events = {}, motions = [], storage = new Map();
  const button = { setAttribute() {}, addEventListener: (name, fn) => { events[name] = fn; } };
  const document = { documentElement: root };
  if (supported) document.startViewTransition = (update) => {
    let resolve;
    const motion = { update, types: new Set(), finished: new Promise((done) => { resolve = done; }),
      finish: () => resolve(), skipTransition() { this.skipped = true; resolve(); } };
    motions.push(motion);
    return motion;
  };
  vm.runInNewContext(controls, {
    $, document, calm: { matches: reduced }, openId: open,
    localStorage: { setItem: (key, value) => storage.set(key, value) },
    readPreference: (key) => storage.get(key), window: { addEventListener() {} },
  });
  function $(id) { assert.equal(id, 'header-toggle'); return button; }
  return { click: () => events.click(), root, motions, storage };
}

test('rapid focus toggles cancel the prior transition and only the latest cleans up', async () => {
  const b = setup();
  b.click();
  b.click();
  assert.equal(b.motions[0].skipped, true);
  b.motions.forEach((motion) => motion.update());
  await Promise.resolve();
  assert.equal(b.root.dataset.header, 'full');
  assert.equal(b.root.dataset.headerMotion, 'true');
  b.motions[1].finish();
  await Promise.resolve();
  assert.equal(b.root.dataset.headerMotion, undefined);
  assert.equal(b.storage.get('compact-header'), 'false');
});

for (const options of [{ reduced: true }, { supported: false }, { open: 'codex:chat' }]) {
  test(`focus preference applies immediately with ${JSON.stringify(options)}`, () => {
    const b = setup(options);
    b.click();
    assert.equal(b.root.dataset.header, 'compact');
    assert.equal(b.motions.length, 0);
    assert.equal(b.storage.get('compact-header'), 'true');
  });
}
