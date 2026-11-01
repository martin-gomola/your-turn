import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/navigation.js', import.meta.url), 'utf8');
function browser(from, to, reduced = false) {
  const events = new Map(), types = new Set(['page']), root = { dataset: {} };
  vm.runInNewContext(source, {
    URL, location: { href: to }, document: { documentElement: root },
    navigation: { activation: { from: { url: from } } },
    matchMedia: () => ({ matches: reduced }),
    addEventListener: (name, fn) => events.set(name, fn),
  });
  return { events, root, types, transition: { types } };
}

test('same-chat collapse replaces upward page motion with horizontal panel motion', () => {
  const b = browser('http://localhost/?open=codex%3Aa', 'http://localhost/?thread=codex%3Aa');
  b.events.get('pagereveal')({ viewTransition: b.transition });
  assert.deepEqual([...b.types], ['hide-inbox']);
  assert.equal(b.root.dataset.sidebarNavigation, 'hide');
});

test('outgoing document receives the same transition type', () => {
  const b = browser('', 'http://localhost/?open=a');
  b.events.get('pageswap')({ activation: { entry: { url: 'http://localhost/?thread=a' } }, viewTransition: b.transition });
  assert.equal(b.types.has('hide-inbox'), true);
});

test('the explicit return route identifies collapse when activation.from is unavailable', () => {
  const b = browser(undefined, 'http://localhost/?thread=a&returnOpen=a');
  b.events.get('pagereveal')({ viewTransition: b.transition });
  assert.deepEqual([...b.types], ['hide-inbox']);
});

for (const [from, to] of [
  ['http://localhost/', 'http://localhost/?thread=a'],
  ['http://localhost/?open=a', 'http://localhost/?thread=b'],
  ['http://localhost/?thread=a', 'http://localhost/?open=a'],
  ['http://localhost/?open=a', 'http://other/?thread=a'],
]) test(`other navigations retain page motion: ${from} → ${to}`, () => {
  const b = browser(from, to);
  b.events.get('pagereveal')({ viewTransition: b.transition });
  assert.deepEqual([...b.types], ['page']);
});

test('reduced motion and absent transition support need no animation', () => {
  const b = browser('http://localhost/?open=a', 'http://localhost/?thread=a', true);
  b.events.get('pagereveal')({ viewTransition: b.transition });
  assert.equal(b.types.has('hide-inbox'), false);
  b.events.get('pagereveal')({});
  assert.equal(b.root.dataset.sidebarNavigation, undefined);
});
