import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {loadConfigFromFile} from 'vite';

test('collaboration launcher and development API proxy use 7878', async () => {
  const script = readFileSync(new URL('../Start-Studio.ps1', import.meta.url), 'utf8');
  assert.match(script, /\[int\]\$Port\s*=\s*7878\b/);
  const loaded = await loadConfigFromFile({command: 'serve', mode: 'development'});
  assert.equal(loaded.config.server.proxy['/api'], 'http://127.0.0.1:7878');
});
