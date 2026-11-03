import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { download, loadChunks } from '../docker/web/site/download.mjs';

const originalFetch = globalThis.fetch;
const originalCaches = globalThis.caches;
afterEach(() => { globalThis.fetch = originalFetch; globalThis.caches = originalCaches; });
const payload = Uint8Array.from([1, 2, 3, 4]);
const expected = { size: 4, sha256: createHash('sha256').update(payload).digest('hex') };
const options = { retryDelayMs: 0 };

test('truncated and same-size corrupt responses retry; only verified data is cached', async () => {
  let calls = 0;
  const writes = [];
  const progress = [];
  globalThis.fetch = async () => new Response([payload.slice(0, 2), new Uint8Array(4), payload][calls++]);
  const cache = { match: async () => undefined, put: async (url, response) => writes.push(new Uint8Array(await response.arrayBuffer())) };
  assert.deepEqual(await download('http://test/chunk', expected, { ...options, cache, onProgress: n => progress.push(n) }), payload);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls, 3);
  assert.deepEqual(writes, [payload]);
  assert.equal(progress.filter(n => n === 0).length, 2);
});

test('corrupt cached data is evicted and fetched again', async () => {
  let deleted = false;
  globalThis.fetch = async () => new Response(payload);
  const cache = { match: async () => new Response(new Uint8Array(4)), delete: async () => { deleted = true; }, put: async () => {} };
  assert.deepEqual(await download('http://test/chunk', expected, { ...options, cache }), payload);
  assert.equal(deleted, true);
});

test('cache read/delete/write failures do not block a successful download', async () => {
  const failure = async () => { throw new Error('storage unavailable'); };
  globalThis.fetch = async () => new Response(payload);
  const cache = { match: failure, delete: failure, put: failure };
  assert.deepEqual(await download('http://test/chunk', expected, { ...options, cache }), payload);
});

test('a valid cached chunk needs no network', async () => {
  globalThis.fetch = async () => { throw new Error('must not fetch'); };
  assert.deepEqual(await download('http://test/chunk', expected, { cache: { match: async () => new Response(payload) } }), payload);
});

test('permanent HTTP errors fail once; transient errors retry within the limit', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('', { status: 404 }); };
  await assert.rejects(download('http://test/chunk', expected, options), /404/);
  assert.equal(calls, 1);
  calls = 0;
  globalThis.fetch = async () => { calls++; return new Response('', { status: 503 }); };
  await assert.rejects(download('http://test/chunk', expected, options), /503/);
  assert.equal(calls, 3);
});

test('an oversized response is rejected, never cached', async () => {
  globalThis.fetch = async () => new Response(new Uint8Array(5));
  await assert.rejects(download('http://test/chunk', expected, { ...options, attempts: 1 }), /exceeds/);
});

test('stalled response body times out and recovers on retry', async () => {
  let calls = 0;
  globalThis.fetch = async (_, { signal }) => {
    if (calls++) return new Response(payload);
    return new Response(new ReadableStream({ start(controller) {
      signal.addEventListener('abort', () => controller.error(signal.reason), { once: true });
    } }));
  };
  assert.deepEqual(await download('http://test/chunk', expected, { ...options, stallMs: 10 }), payload);
  assert.equal(calls, 2);
});

test('an aborted startup does not retry', async () => {
  let calls = 0;
  const controller = new AbortController();
  globalThis.fetch = async (_, { signal }) => {
    calls++;
    controller.abort(new Error('startup canceled'));
    throw signal.reason;
  };
  await assert.rejects(download('http://test/chunk', expected, { ...options, signal: controller.signal }), /startup canceled/);
  assert.equal(calls, 1);
});

test('chunks are assembled in manifest order with bounded concurrency and unavailable storage', async () => {
  let active = 0, peak = 0;
  globalThis.caches = { open: async () => { throw new Error('disabled'); } };
  globalThis.fetch = async url => {
    peak = Math.max(peak, ++active);
    await new Promise(resolve => setTimeout(resolve, 5));
    active--;
    return new Response(Uint8Array.of(Number(url.split('/').at(-1))));
  };
  const parts = Array.from({ length: 9 }, (_, n) => ({ url: String(n), size: 1 }));
  const result = await loadChunks({ parts, size: 9 }, 'http://test/', { concurrency: 3 });
  assert.deepEqual([...result], [0, 1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal(peak, 3);
});

test('a failed chunk aborts sibling transfers and stops scheduling new ones', async () => {
  const requests = [];
  let aborted = false;
  globalThis.fetch = async (url, { signal }) => {
    requests.push(url);
    if (url.endsWith('/0')) return new Response('', { status: 404 });
    return new Response(new ReadableStream({ start(controller) {
      signal.addEventListener('abort', () => { aborted = true; controller.error(signal.reason); }, { once: true });
    } }));
  };
  const parts = Array.from({ length: 6 }, (_, n) => ({ url: String(n), size: 1 }));
  await assert.rejects(loadChunks({ parts, size: 6 }, 'http://test/', { concurrency: 2 }), /404/);
  assert.equal(requests.length, 2);
  assert.equal(aborted, true);
});
