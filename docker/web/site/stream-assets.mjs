import { download, openCache } from './download.mjs';

// Packs amortize request latency while preserving the engine's async-file API.
// Memory is bounded; disk cache failures and unsupported Cache Storage are OK.
export function createAssetStore(manifest, baseUrl, { memoryLimit = 64 << 20, injectionLimit = 48 << 20, concurrency = 2 } = {}) {
  const descriptors = manifest.stream?.packs || [];
  const entries = manifest.stream?.files || {};
  const members = new Map();
  for (const [file, entry] of Object.entries(entries)) {
    if (!members.has(entry[0])) members.set(entry[0], []);
    members.get(entry[0]).push([file, entry[1], entry[2]]);
  }
  let filesystem = null, injectedBytes = 0;
  const injected = new Set(), demanded = new Set();
  const warm = new Set(manifest.stream?.warmup || []);
  const resident = new Map();
  const jobs = new Map();
  const queue = [];
  let memory = 0, active = 0, closed = false, prefetchStopped = false;
  const stats = { downloads: 0, hits: 0, preemptions: 0, residentBytes: 0, active: 0 };
  const cachePromise = openCache('vc-stream').then(async cache => {
    try {
      const keep = new Set(descriptors.map(p => new URL(p.url, baseUrl).href));
      for (const request of await cache?.keys() || []) {
        if (!keep.has(request.url)) await cache.delete(request);
      }
    } catch {}
    return cache;
  });
  const install = (id, bytes) => {
    if (!filesystem) return;
    for (const [file, offset, size] of members.get(id) || []) {
      if (injected.has(file) || demanded.has(file) || injectedBytes + size > injectionLimit) continue;
      if (offset < 0 || size < 0 || offset + size > bytes.length) throw new Error("Invalid asset pack index");
      const path = "/" + file;
      try {
        if (filesystem.analyzePath(path).exists) continue;
        const slash = path.lastIndexOf("/");
        filesystem.mkdirTree(path.slice(0, slash));
        filesystem.createDataFile(path.slice(0, slash), path.slice(slash + 1), bytes.slice(offset, offset + size), true, true, true);
      } catch {
        // Prefill is optional; a valid demanded file must still be delivered.
        filesystem = null;
        return;
      }
      injected.add(file); injectedBytes += size;
      stats.injectedBytes = injectedBytes;
      stats.injectedFiles = injected.size;
    }
  };
  const remember = (id, bytes) => {
    install(id, bytes);
    if (bytes.length > memoryLimit) return;
    if (resident.has(id)) { memory -= resident.get(id).length; resident.delete(id); }
    while (memory + bytes.length > memoryLimit && resident.size) {
      const oldest = resident.keys().next().value;
      memory -= resident.get(oldest).length;
      resident.delete(oldest);
    }
    resident.set(id, bytes); memory += bytes.length; stats.residentBytes = memory;
  };
  const pump = () => {
    queue.sort((a, b) => a.priority - b.priority);
    while (!closed && active < concurrency && queue.length) {
      const job = queue.shift();
      active++; stats.active = active; job.started = true;
      (async () => {
        const cache = await cachePromise;
        job.controller.signal.throwIfAborted();
        const bytes = await download(new URL(descriptors[job.id].url, baseUrl).href, descriptors[job.id], {
          cache, signal: job.controller.signal, priority: job.priority ? 'low' : 'high',
        });
        stats.downloads++;
        remember(job.id, bytes);
        return bytes;
      })().then(job.resolve, job.reject).finally(() => {
        active--; stats.active = active;
        if (jobs.get(job.id) === job) jobs.delete(job.id);
        pump();
      });
    }
  };
  const stopPrefetch = () => {
    prefetchStopped = true;
    for (let i = queue.length - 1; i >= 0; i--) {
      if (queue[i].priority) {
        const job = queue.splice(i, 1)[0];
        jobs.delete(job.id); job.reject(new DOMException('Prefetch canceled', 'AbortError'));
      }
    }
    for (const job of jobs.values()) if (job.priority && job.started) job.controller.abort();
  };
  const get = (id, priority = 0) => {
    if (closed) return Promise.reject(new Error('Asset store closed'));
    if (resident.has(id)) {
      const bytes = resident.get(id); resident.delete(id); resident.set(id, bytes);
      stats.hits++; return Promise.resolve(bytes);
    }
    const existing = jobs.get(id);
    if (existing && !existing.controller.signal.aborted) {
      existing.priority = Math.min(priority, existing.priority);
      pump(); return existing.promise;
    }
    if (!descriptors[id]) return Promise.reject(new Error('Unknown asset pack'));
    const job = { id, priority, controller: new AbortController(), started: false };
    job.promise = new Promise((resolve, reject) => { job.resolve = resolve; job.reject = reject; });
    jobs.set(id, job); queue.push(job);
    if (!priority && active >= concurrency) {
      const speculative = [...jobs.values()].find(j => j.started && j.priority);
      if (speculative) { stats.preemptions++; speculative.controller.abort(); }
    }
    pump(); return job.promise;
  };
  return {
    stats,
    has: file => Object.hasOwn(entries, file),
    attachFS(fs) {
      filesystem = fs;
      for (const [id, bytes] of resident) install(id, bytes);
    },
    async read(file) {
      const entry = entries[file];
      if (!entry) throw new Error(`Unknown packed asset: ${file}`);
      const [id, offset, size] = entry;
      demanded.add(file);
      let bytes;
      try { bytes = await get(id); } finally { demanded.delete(file); }
      if (offset < 0 || size < 0 || offset + size > bytes.length) throw new Error('Invalid asset pack index');
      // Copy only the requested file, never retain a whole pack through a view.
      return bytes.slice(offset, offset + size);
    },
    prefetch() {
      if (prefetchStopped || closed) return;
      for (const id of warm) void get(id, 1).catch(() => {});
    },
    close() {
      closed = true; stopPrefetch();
      for (const job of jobs.values()) job.controller.abort();
      for (const job of queue.splice(0)) job.reject(new DOMException('Closed', 'AbortError'));
      jobs.clear(); resident.clear(); memory = 0; stats.residentBytes = 0;
    },
  };
}

export function installBlobDelivery(win, store) {
  const owned = new Map();
  const revoke = url => {
    const timer = owned.get(url);
    if (timer === undefined) return;
    clearTimeout(timer); owned.delete(url); win.URL.revokeObjectURL(url);
    store.stats.objectUrls = owned.size;
  };
  const originalOpen = win.XMLHttpRequest.prototype.open;
  win.XMLHttpRequest.prototype.open = function(method, url, ...args) {
    if (owned.has(String(url))) this.addEventListener('loadend', () => revoke(String(url)), { once: true });
    return originalOpen.call(this, method, url, ...args);
  };
  const originalFetch = win.fetch.bind(win);
  win.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!owned.has(url)) return originalFetch(input, init);
    try {
      const response = await originalFetch(input, init);
      return new win.Response(await response.arrayBuffer(), { status: response.status, headers: response.headers });
    } finally { revoke(url); }
  };
  win.addEventListener('pagehide', () => { for (const url of owned.keys()) revoke(url); }, { once: true });
  return async file => {
    const bytes = await store.read(file);
    const url = win.URL.createObjectURL(new win.Blob([bytes], { type: 'application/octet-stream' }));
    // Normally released at XHR loadend/fetch consumption. The timeout also
    // bounds abandoned URLs when the engine cancels before opening a request.
    owned.set(url, setTimeout(() => revoke(url), 120000));
    store.stats.objectUrls = owned.size;
    return url;
  };
}
