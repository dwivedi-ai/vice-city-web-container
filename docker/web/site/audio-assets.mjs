import { download, openCache } from './download.mjs';

// Native audio uses temporary filenames, so two voices can request the same
// recording concurrently. Share the transfer, but give each consumer its own
// bytes. This cache never contains saves and audio never occupies pack slots.
export function createAudioStore(files, urlFor, { memoryLimit = 32 << 20 } = {}) {
  const allowed = new Set(files), resident = new Map(), jobs = new Map();
  let memory = 0, closed = false;
  const stats = { loads: 0, hits: 0, shared: 0, residentBytes: 0, active: 0 };
  const cachePromise = openCache('vc-audio').then(async cache => {
    try {
      const keep = new Set(files.map(urlFor));
      for (const request of await cache?.keys() || []) if (!keep.has(request.url)) await cache.delete(request);
    } catch {}
    return cache;
  });
  return {
    stats,
    has: file => allowed.has(file),
    async read(file) {
      if (closed) throw new Error('Audio store closed');
      if (!allowed.has(file)) throw new Error('Unknown audio asset');
      if (resident.has(file)) {
        const bytes = resident.get(file); resident.delete(file); resident.set(file, bytes);
        stats.hits++; return bytes.slice();
      }
      let job = jobs.get(file);
      if (!job) {
        job = { controller: new AbortController() };
        jobs.set(file, job); stats.active = jobs.size;
        job.promise = (async () => {
          const cache = await cachePromise;
          // A radio recording can take several minutes on a slow connection.
          const bytes = await download(urlFor(file), {}, {
            cache, signal: job.controller.signal, priority: 'low', timeoutMs: 900000, attempts: 2,
          });
          stats.loads++;
          if (bytes.length <= memoryLimit) {
            while (memory + bytes.length > memoryLimit && resident.size) {
              const oldest = resident.keys().next().value;
              memory -= resident.get(oldest).length; resident.delete(oldest);
            }
            resident.set(file, bytes); memory += bytes.length; stats.residentBytes = memory;
          }
          return bytes;
        })().finally(() => { jobs.delete(file); stats.active = jobs.size; });
      } else stats.shared++;
      return (await job.promise).slice();
    },
    close() {
      closed = true;
      for (const job of jobs.values()) job.controller.abort();
      resident.clear(); memory = 0; stats.residentBytes = 0;
    },
  };
}
