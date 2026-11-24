// Koch-I-Doo Service Worker: App-Shell offline, API/Bilder network-first.
// Cache-Name enthält die App-Version → neue Deploys räumen alte Caches auf.
const CACHE = "kochido-v1.21.0";
const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;

  // API & Bilder: network-first, Cache als Offline-Fallback
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/images/")) {
    e.respondWith(
      fetch(e.request)
        .then((resp) => {
          if (resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(e.request, copy));
          }
          return resp;
        })
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // Statische Assets (gehashed): cache-first, sonst Netz; SPA-Fallback auf index.html
  e.respondWith(
    caches.match(e.request).then(
      (hit) =>
        hit ||
        fetch(e.request)
          .then((resp) => {
            if (resp.ok && url.origin === self.location.origin) {
              const copy = resp.clone();
              caches.open(CACHE).then((c) => c.put(e.request, copy));
            }
            return resp;
          })
          .catch(() => caches.match("/index.html"))
    )
  );
});
