import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const handler = source.slice(source.indexOf('async function copyThreadId()'), source.indexOf('$("copy-thread-id").addEventListener'));

for (const denied of [false, true]) {
  test(`copy Thread ID: ${denied ? 'denied' : 'success'}`, async () => {
    const id = '0d3e0067-0000-7000-8000-000000000067';
    const nodes = { 'session-thread-id': { textContent: id }, 'copy-thread-id': { disabled: false }, 'copy-thread-status': { textContent: '' } };
    let copied;
    const context = vm.createContext({ $: key => nodes[key], navigator: { clipboard: { writeText: async value => {
      if (denied) throw new Error('Clipboard denied');
      copied = value;
    } } } });
    vm.runInContext(handler, context);
    await context.copyThreadId();
    assert.equal(nodes['session-thread-id'].textContent, id);
    assert.match(nodes['copy-thread-status'].textContent, denied ? /copy it manually/ : /copied/);
    assert.equal(copied, denied ? undefined : id);
  });

  test(`copy file path: ${denied ? 'denied' : 'success'}`, async () => {
    const path = 'src/yourturn/static/app.js';
    const status = { textContent: '' };
    let copied;
    const context = vm.createContext({ navigator: { clipboard: { writeText: async value => {
      if (denied) throw new Error('Clipboard denied');
      copied = value;
    } } } });
    const handler = source.slice(source.indexOf('async function copyFilePath('), source.indexOf('$("open-codex").addEventListener'));
    vm.runInContext(`${handler}\nthis.copyFilePath = copyFilePath;`, context);
    await context.copyFilePath(path, status);
    assert.equal(copied, denied ? undefined : path);
    assert.match(status.textContent, denied ? /Clipboard access was denied/ : new RegExp(`copied: ${path.replaceAll('/', '\\/')}`));
  });
}
