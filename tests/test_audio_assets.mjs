import { test, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createAudioStore } from '../docker/web/site/audio-assets.mjs';
const savedFetch = globalThis.fetch, savedCaches = globalThis.caches, stores = [];
afterEach(() => { for (const s of stores.splice(0)) s.close(); globalThis.fetch = savedFetch; globalThis.caches = savedCaches; });
const tick = () => new Promise(r => setImmediate(r));
function store(limit = 32) {
  globalThis.caches = { open: async () => { throw Error('Storage unavailable'); } };
  const s = createAudioStore(['water.mp3', 'city.mp3'], f => 'http://test/' + f, { memoryLimit: limit }); stores.push(s); return s;
}
test('concurrent audio consumers share a transfer and cannot mutate one another', async () => {
  let calls = 0;
  globalThis.fetch = async () => { calls++; await tick(); return new Response(Uint8Array.of(1, 2, 3)); };
  const s = store(); const [a, b] = await Promise.all([s.read('water.mp3'), s.read('water.mp3')]);
  a[0] = 99; assert.equal(b[0], 1); assert.equal((await s.read('water.mp3'))[0], 1);
  assert.equal(calls, 1); assert.equal(s.stats.shared, 1); assert.equal(s.stats.hits, 1);
});
test('audio memory is bounded and evicted recordings remain fetchable', async () => {
  let calls = 0; globalThis.fetch = async () => { calls++; return new Response(Uint8Array.of(1, 2, 3)); };
  const s = store(3); await s.read('water.mp3'); await s.read('city.mp3'); await s.read('water.mp3');
  assert.equal(calls, 3); assert.equal(s.stats.residentBytes, 3);
});
test('failed audio jobs are removed so the next request can recover', async () => {
  let fail = true; globalThis.fetch = async () => fail ? new Response('', { status: 404 }) : new Response('ok');
  const s = store(); await assert.rejects(s.read('water.mp3'), /404/); await tick(); fail = false;
  assert.equal(new TextDecoder().decode(await s.read('water.mp3')), 'ok');
});
test('closing aborts active recordings and disallows later reads', async () => {
  globalThis.fetch = async (_, { signal }) => new Response(new ReadableStream({ start(c) { signal.addEventListener('abort', () => c.error(signal.reason), { once: true }); } }));
  const s = store(); const pending = s.read('water.mp3'); await tick(); s.close();
  await assert.rejects(pending); await assert.rejects(s.read('water.mp3'), /closed/); assert.equal(s.stats.residentBytes, 0);
});

test('cached audio can be reused without contacting the server', async () => {
  const kept = 'http://test/water.mp3', removed = [];
  globalThis.caches = { open: async name => {
    assert.equal(name, 'vc-audio');
    return { keys: async () => [{ url: kept }, { url: 'http://test/obsolete' }], delete: async url => removed.push(url.url), match: async () => new Response(Uint8Array.of(4, 5, 6)) };
  } };
  globalThis.fetch = async () => { throw Error('Must use cached recording'); };
  const s = createAudioStore(['water.mp3'], () => kept); stores.push(s);
  assert.deepEqual([...await s.read('water.mp3')], [4, 5, 6]);
  assert.deepEqual(removed, ['http://test/obsolete']);
});
