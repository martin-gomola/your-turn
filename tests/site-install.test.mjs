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
    'uv tool install your-turn\nyour-turn doctor\nyour-turn autostart enable\nyour-turn install');
});

test('nix ignores uv and refuses autostart', () => {
  assert.equal(installation({method: 'nix', uv: 'brew'}),
    'nix run github:martin-gomola/your-turn -- doctor\nnix run github:martin-gomola/your-turn -- install');
  assert.throws(() => installation({method: 'nix', autostart: true}));
});

test('unknown choices are rejected', () => {
  assert.throws(() => installation({method: 'pip'}));
  assert.throws(() => installation({uv: 'toString'}));
  assert.throws(() => installation({doctor: 'yes'}));
});
