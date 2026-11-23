import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installation} from '../site/install.mjs';

test('default is a uv dry run, then install', () => {
  assert.equal(installation(), 'uvx your-turn@latest doctor\nuvx your-turn@latest install');
  assert.equal(installation({doctor: false}), 'uvx your-turn@latest install');
});

test('missing uv is installed first', () => {
  assert.ok(installation({uv: 'brew'}).startsWith('brew install uv\n'));
  assert.ok(installation({uv: 'script'}).startsWith('curl -LsSf https://astral.sh/uv/install.sh | sh\n'));
});

test('autostart uses a persistent install and ends with install', () => {
  assert.equal(installation({autostart: true}),
    'uv tool install your-turn@latest\nyour-turn doctor\nyour-turn autostart enable\nyour-turn install');
});

test('unknown choices are rejected', () => {
  assert.throws(() => installation({uv: 'toString'}));
  assert.throws(() => installation({doctor: 'yes'}));
});
