import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/yourturn/static/app.js', import.meta.url), 'utf8');
const helpers = source.slice(source.indexOf('const APP_NAME'), source.indexOf('const QUIET_NOTIFY_MS'));
const context = vm.createContext({});
vm.runInContext(`${helpers}\nObject.assign(this, { basisOf });`, context);

test('only a next step the source or handoff did not name is marked', () => {
  assert.equal(context.basisOf({ next_basis: 'inferred' }).label, 'Inferred');
  assert.equal(context.basisOf({ next_basis: 'no_handoff' }).label, 'No handoff');
  assert.equal(context.basisOf({ next_basis: 'no_next_step' }).label, 'No next step');
  for (const basis of ['source', 'handoff', '', undefined]) assert.equal(context.basisOf({ next_basis: basis }), null);
});
