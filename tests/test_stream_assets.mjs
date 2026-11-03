import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createAssetStore } from '../docker/web/site/stream-assets.mjs';
const originalFetch = globalThis.fetch, originalCaches = globalThis.caches;
const stores = [];
afterEach(() => { for (const s of stores.splice(0)) s.close(); globalThis.fetch = originalFetch; globalThis.caches = originalCaches; });
const tick = () => new Promise(r => setImmediate(r));
function store({ packs = [{ url: '0', size: 4 }], files = { 'a': [0, 0, 2], 'b': [0, 2, 2] }, warmup = [] } = {}, options) {
  globalThis.caches = { open: async () => { throw Error('Storage disabled'); } };
  const s = createAssetStore({ stream: { packs, files, warmup } }, 'http://test/', options); stores.push(s); return s;
}

test('concurrent asset reads share one pack and return independent file bytes without Cache Storage', async () => {
  let count = 0;
  globalThis.fetch = async () => { count++; await tick(); return new Response(Uint8Array.of(1, 2, 3, 4)); };
  const s = store();
  const [a, b] = await Promise.all([s.read('a'), s.read('b')]);
  assert.deepEqual([...a], [1, 2]); assert.deepEqual([...b], [3, 4]);
  a[0] = 99;
  assert.deepEqual([...await s.read('a')], [1, 2]); assert.equal(count, 1);
});

test('native filesystem prefill skips demanded and existing files; attaches after downloads too', async () => {
  globalThis.fetch = async () => new Response(Uint8Array.of(1, 2, 3, 4));
  const written = new Map([['/existing', Uint8Array.of(9)]]);
  const fs = { analyzePath: p => ({ exists: written.has(p) }), mkdirTree: () => {}, createDataFile: (dir, file, bytes) => written.set(dir + '/' + file, bytes) };
  const s = store({ files: { a: [0, 0, 2], b: [0, 2, 2], existing: [0, 0, 2] } });
  s.attachFS(fs); await s.read('a');
  assert.equal(written.has('/a'), false); assert.deepEqual([...written.get('/b')], [3, 4]);
  assert.deepEqual([...written.get('/existing')], [9]); assert.equal(s.stats.injectedFiles, 1);
  const delayed = store(); await delayed.read('a'); delayed.attachFS(fs);
  assert.deepEqual([...written.get('/a')], [1, 2]);
});

test('decoded pack LRU is bounded and evicted packs can be fetched again', async () => {
  let count = 0; globalThis.fetch = async () => { count++; return new Response(Uint8Array.of(1, 2, 3, 4)); };
  const s = store({ packs: [{ url: '0', size: 4 }, { url: '1', size: 4 }], files: { a: [0, 0, 4], b: [1, 0, 4] } }, { memoryLimit: 4 });
  await s.read('a'); await s.read('b'); await s.read('a');
  assert.equal(count, 3); assert.equal(s.stats.residentBytes, 4);
});

test('demand preempts speculative traffic; aborted pack can subsequently be requested', async () => {
  let first = true; const seen = [];
  globalThis.fetch = async (url, { signal }) => {
    seen.push(url);
    if (url.endsWith('/0') && first) {
      first = false;
      return new Response(new ReadableStream({ start(c) { signal.addEventListener('abort', () => c.error(signal.reason), { once: true }); } }));
    }
    return new Response(Uint8Array.of(7));
  };
  const s = store({ packs: [{ url: '0', size: 1 }, { url: '1', size: 1 }], files: { a: [0, 0, 1], b: [1, 0, 1] }, warmup: [0] }, { concurrency: 1 });
  s.prefetch(); await tick();
  assert.deepEqual([...await s.read('b')], [7]);
  assert.deepEqual([...await s.read('a')], [7]);
  assert.equal(s.stats.preemptions, 1); assert.equal(seen.length, 3);
});

test('invalid indexes reject and a closed store cannot download new assets', async () => {
  globalThis.fetch = async () => new Response(Uint8Array.of(1, 2, 3, 4));
  const s = store({ files: { bad: [0, 3, 9], good: [0, 0, 4] } });
  await assert.rejects(s.read('bad'), /Invalid asset pack/);
  s.close(); await assert.rejects(s.read('good'), /closed/);
});

test('filesystem prefill respects its separate budget and failures cannot reject a valid demand', async () => {
  globalThis.fetch = async () => new Response(Uint8Array.of(1, 2, 3, 4));
  const written = [];
  const fs = { analyzePath: () => ({ exists: false }), mkdirTree: () => {}, createDataFile: (_, f) => written.push(f) };
  const s = store({ warmup: [0] }, { injectionLimit: 2 });
  s.attachFS(fs); s.prefetch(); await tick(); await tick();
  assert.deepEqual(written, ['a']); assert.equal(s.stats.injectedBytes, 2);
  const broken = store(); broken.attachFS({ ...fs, createDataFile: () => { throw Error('Cannot prefill'); } });
  assert.deepEqual([...await broken.read('a')], [1, 2]);
});

test('random traffic models do not cancel the finite first-scene warmup', async () => {
  const seen = [];
  globalThis.fetch = async url => { seen.push(url); await tick(); return new Response(Uint8Array.of(7)); };
  const s = store({ packs: [0, 1, 2].map(n => ({ url: String(n), size: 1 })), files: { 'vc-assets/local/models/gta3.img/random.dff': [0, 0, 1] }, warmup: [1, 2] });
  await s.read('vc-assets/local/models/gta3.img/random.dff');
  s.prefetch(); await tick(); await tick(); await tick();
  assert.ok(seen.includes('http://test/1')); assert.ok(seen.includes('http://test/2'));
});
