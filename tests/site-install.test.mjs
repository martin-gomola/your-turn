import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installation} from '../site/install.mjs';

test('default is a one-line uvx install with no dry run or Codex autostart', () => {
  assert.equal(installation(), 'uvx your-turn@latest install');
});

test('dry run prefixes uvx doctor before install', () => {
  assert.equal(installation({doctor: true}), 'uvx your-turn@latest doctor\nuvx your-turn@latest install');
});

test('missing uv is installed first', () => {
  assert.ok(installation({uv: 'brew'}).startsWith('brew install uv\n'));
  assert.ok(installation({uv: 'script'}).startsWith('curl -LsSf https://astral.sh/uv/install.sh | sh\n'));
});

test('Codex autostart uses a persistent install and ends with install', () => {
  assert.equal(
    installation({autostart: true}),
    'uv tool install your-turn@latest\nyour-turn autostart enable\nyour-turn install',
  );
  assert.equal(
    installation({doctor: true, autostart: true}),
    'uv tool install your-turn@latest\nyour-turn doctor\nyour-turn autostart enable\nyour-turn install',
  );
});

test('unknown choices are rejected', () => {
  assert.throws(() => installation({uv: 'toString'}));
  assert.throws(() => installation({doctor: 'yes'}));
});
