import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {readApiErrorMessage} from '../src/apiResponse.ts';

test('structured validation errors consume the body once', async () => {
  const response = new Response(JSON.stringify({detail: [{loc: ['body', 'name'], msg: 'required'}]}), {status: 422});
  assert.equal(await readApiErrorMessage(response), '[{"loc":["body","name"],"msg":"required"}]');
  assert.equal(response.bodyUsed, true);
});

for (const [label, raw, status, expected] of [
  ['plain text', 'upstream gateway unavailable', 502, 'upstream gateway unavailable'],
  ['HTML', '<html>Gateway timeout</html>', 504, '<html>Gateway timeout</html>'],
  ['empty', null, 503, 'API 请求失败（HTTP 503）'],
  ['whitespace', '  \n', 503, 'API 请求失败（HTTP 503）'],
  ['permission', '{"detail":"无权编辑"}', 403, '无权编辑'],
  ['conflict', '{"detail":"版本已变化"}', 409, '版本已变化'],
  ['non-detail JSON', '{"error":"denied"}', 400, '{"error":"denied"}'],
]) {
  test(`API error preserves ${label} response`, async () => {
    assert.equal(await readApiErrorMessage(new Response(raw, {status})), expected);
  });
}

// Exercise the actual API wrapper, not a parallel reimplementation. No app or
// network is started: the wrapper's fetch and document dependencies are local.
function apiWrapper(fetch) {
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  const start = source.indexOf('const api = async');
  const end = source.indexOf('const send = ', start);
  assert.ok(start >= 0 && end > start, 'API wrapper source boundary must remain explicit');
  const wrapper = stripTypeScriptTypes(source.slice(start, end));
  return new Function('fetch', 'document', 'debugUrl', 'readApiErrorMessage',
    wrapper + '\nreturn api;')(
      fetch, {cookie: 'ovc_csrf=synthetic-csrf'}, value => value, readApiErrorMessage,
    );
}

test('actual API wrapper keeps status, URL, and CSRF for text and conflict errors', async () => {
  for (const [status, raw, expected] of [
    [502, 'upstream gateway unavailable', 'upstream gateway unavailable'],
    [409, '{"detail":"版本已变化"}', '版本已变化'],
    [403, '{"detail":"无权编辑"}', '无权编辑'],
  ]) {
    const api = apiWrapper(async (url, options) => {
      assert.equal(url, '/api/test');
      assert.equal(options.headers['X-CSRF-Token'], 'synthetic-csrf');
      return new Response(raw, {status});
    });
    await assert.rejects(api('/test', {method: 'POST'}), error => {
      assert.equal(error.message, expected);
      assert.equal(error.status, status);
      assert.equal(error.kind, 'api');
      assert.equal(error.url, '/api/test');
      return true;
    });
  }
});

test('actual API wrapper still returns successful JSON', async () => {
  const api = apiWrapper(async () => new Response('{"revision":3}', {status: 200}));
  assert.deepEqual(await api('/test'), {revision: 3});
});
