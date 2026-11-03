// Bounded, verified downloads. Optional disk caching must never prevent play.
export async function openCache(name) {
  try { return await globalThis.caches?.open(name); } catch { return null; }
}

async function discard(cache, url) {
  try { await cache?.delete(url); } catch {}
}

export async function verify(bytes, expected) {
  if (expected.size !== undefined && bytes.length !== expected.size) {
    throw new Error(`Incomplete download (${bytes.length}/${expected.size} bytes)`);
  }
  // Web Crypto is available over HTTPS/localhost. Plain HTTP LAN deployments
  // still get strict decoded-length checks and independently addressed chunks.
  if (expected.sha256 && globalThis.crypto?.subtle) {
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hex = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, "0")).join("");
    if (hex !== expected.sha256) throw new Error("Download checksum mismatch");
  }
}

export async function download(url, expected = {}, {
  cache = null, signal, priority = "auto", onResponse = () => {}, onProgress = () => {}, onRetry = () => {},
  attempts = 3, stallMs = 30000, timeoutMs = 120000, retryDelayMs = 600,
} = {}) {
  signal?.throwIfAborted();
  try {
    const cached = await cache?.match(url);
    if (cached) {
      const bytes = new Uint8Array(await cached.arrayBuffer());
      await verify(bytes, expected);
      onProgress(bytes.length);
      return bytes;
    }
  } catch {
    await discard(cache, url);
  }

  for (let attempt = 0; attempt < attempts; attempt++) {
    signal?.throwIfAborted();
    const controller = new AbortController();
    const abort = () => controller.abort(signal.reason);
    signal?.addEventListener("abort", abort, { once: true });
    let idleTimer;
    const resetIdle = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => controller.abort(new Error("Download stalled")), stallMs);
    };
    const totalTimer = setTimeout(() => controller.abort(new Error("Download timed out")), timeoutMs);
    let reader;
    let permanent = false;
    try {
      resetIdle();
      const response = await fetch(url, { priority, signal: controller.signal, cache: attempt ? "reload" : "default" });
      onResponse(response);
      if (!response.ok) {
        permanent = response.status >= 400 && response.status < 500 && ![408, 429].includes(response.status);
        throw new Error(`Download failed (HTTP ${response.status})`);
      }
      reader = response.body.getReader();
      // Never clone/tee the response: an unread branch buffers the entire body.
      const out = expected.size === undefined ? null : new Uint8Array(expected.size);
      const chunks = [];
      let offset = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        resetIdle();
        if (out) {
          if (offset + value.length > out.length) throw new Error("Download exceeds expected size");
          out.set(value, offset);
        } else chunks.push(value);
        offset += value.length;
        onProgress(offset);
      }
      const bytes = out || new Uint8Array(offset);
      if (!out) {
        let at = 0;
        for (const chunk of chunks) { bytes.set(chunk, at); at += chunk.length; }
      }
      // Check actual received length, not the allocated output's length.
      if (expected.size !== undefined && offset !== expected.size) throw new Error("Incomplete download");
      await verify(bytes, expected);
      signal?.throwIfAborted();
      // A failed/quota-limited cache write cannot reject a successful download.
      // Response copies this small chunk; do not retain a full second boot bundle.
      if (cache) {
        try { void cache.put(url, new Response(bytes)).catch(() => {}); } catch {}
      }
      return bytes;
    } catch (error) {
      onProgress(0);
      signal?.throwIfAborted();
      if (permanent || attempt === attempts - 1) throw error;
      onRetry(attempt + 1);
    } finally {
      clearTimeout(idleTimer);
      clearTimeout(totalTimer);
      signal?.removeEventListener("abort", abort);
      controller.abort();
      try { await reader?.cancel(); } catch {}
    }
    await new Promise(resolve => setTimeout(resolve, retryDelayMs * 2 ** attempt));
  }
}

export async function loadChunks(preload, baseUrl, { onProgress = () => {}, onRetry = () => {}, concurrency = 4, signal } = {}) {
  const cache = await openCache("vc-preload");
  const urls = preload.parts.map(part => new URL(part.url, baseUrl).href);
  // Retain unchanged content-addressed chunks across releases, not just one
  // manifest version. This cache contains game downloads, never save data.
  try {
    const keep = new Set(urls);
    for (const request of await cache?.keys() || []) {
      if (!keep.has(request.url)) await cache.delete(request);
    }
  } catch {}
  const controller = new AbortController();
  const abort = () => controller.abort(signal.reason);
  signal?.throwIfAborted();
  signal?.addEventListener("abort", abort, { once: true });
  const all = new Uint8Array(preload.size);
  const offsets = [];
  let sum = 0;
  for (const part of preload.parts) { offsets.push(sum); sum += part.size; }
  if (sum !== preload.size) throw new Error("Invalid game manifest");
  const progress = new Array(preload.parts.length).fill(0);
  let next = 0;
  const worker = async () => {
    while (next < preload.parts.length) {
      controller.signal.throwIfAborted();
      const index = next++;
      const bytes = await download(urls[index], preload.parts[index], {
        cache, signal: controller.signal, onRetry,
        onProgress: count => {
          progress[index] = count;
          onProgress(progress.reduce((a, b) => a + b, 0), preload.size);
        },
      });
      all.set(bytes, offsets[index]);
    }
  };
  const workers = Array.from({ length: Math.min(concurrency, preload.parts.length) }, worker);
  try {
    await Promise.all(workers);
    return all;
  } catch (error) {
    controller.abort(error);
    await Promise.allSettled(workers);
    throw error;
  } finally {
    signal?.removeEventListener("abort", abort);
  }
}
