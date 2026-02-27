// ==========================================
// 🔧 iFix Pro Service Worker v4
// Offline support + Cache CDN libraries
// ==========================================

const CACHE_NAME = 'ifix-pro-v4';
const CDN_CACHE = 'ifix-cdn-libs-v4';

// PocketBase API paths - SELALU dari network (realtime data)
const API_PATHS = ['/api/', '/_/', '/pb_'];

// File app yang wajib di-cache untuk offline
const APP_SHELL = [
  '/index.html',
  '/manifest.json',
  '/sw.js',
  '/logo-ifix.png',
];

// Domain CDN yang pakai cache-first
const CDN_DOMAINS = [
  'cdn.tailwindcss.com',
  'cdnjs.cloudflare.com',
  'unpkg.com',
  'esm.sh',
  'fonts.googleapis.com',
  'fonts.gstatic.com',
];

// Install: cache semua file app shell
self.addEventListener('install', (event) => {
  console.log('[SW] Installing v4...');
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.all(
        APP_SHELL.map((url) =>
          cache.add(url).catch((err) => console.warn('[SW] Gagal cache:', url, err))
        )
      );
    })
  );
});

// Activate: bersihkan cache lama
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating v4...');
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((k) => k !== CACHE_NAME && k !== CDN_CACHE)
          .map((k) => { console.log('[SW] Hapus cache lama:', k); return caches.delete(k); })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch: strategi berdasarkan jenis request
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Skip: non-GET, chrome-extension
  if (event.request.method !== 'GET') return;
  if (url.protocol === 'chrome-extension:') return;

  // PocketBase API calls → SELALU network (data realtime, jangan cache)
  if (API_PATHS.some((path) => url.pathname.startsWith(path))) return;

  // CDN libraries → Cache First
  if (CDN_DOMAINS.some((d) => url.hostname.includes(d))) {
    event.respondWith(
      caches.open(CDN_CACHE).then(async (cache) => {
        const cached = await cache.match(event.request);
        if (cached) {
          return cached; // ✅ Dari cache = instan
        }
        try {
          const response = await fetch(event.request);
          if (response.ok) {
            cache.put(event.request, response.clone());
          }
          return response;
        } catch {
          return new Response('// CDN offline', { headers: { 'Content-Type': 'text/javascript' } });
        }
      })
    );
    return;
  }

  // index.html → Network First dengan fallback cache (agar selalu update)
  if (url.pathname === '/' || url.pathname === '/index.html') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => {
          console.log('[SW] Offline: serve index.html dari cache');
          return caches.match('/index.html');
        })
    );
    return;
  }

  // Asset lain (logo, manifest, dsb) → Cache First
  event.respondWith(
    caches.match(event.request).then((cached) => {
      return cached || fetch(event.request).then((response) => {
        if (response.ok) {
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, response.clone()));
        }
        return response;
      });
    })
  );
});
