import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const help = source.slice(source.indexOf('function syncContextHelp('), source.indexOf('function showAside('));

for (const [view, mode, expected] of [
  ['inbox', 'dashboard', 'inbox'], ['thread', 'simple', 'inbox'],
  ['deck', 'dashboard', 'dashboard'], ['deck', 'simple', 'launcher'],
]) test(`Help leads with ${expected} in ${view}/${mode}`, () => {
  const sections = ['inbox', 'dashboard', 'launcher'].map(view => ({ dataset: { helpView: view } }));
  vm.runInNewContext(help + '\nsyncContextHelp();', {
    document: { body: { dataset: { view } }, querySelectorAll: () => sections },
    $: () => ({ dataset: { mode } }),
  });
  assert.deepEqual(sections.filter(section => !section.hidden).map(section => section.dataset.helpView), [expected]);
});
