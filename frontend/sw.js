/* eslint-disable no-restricted-globals */
const CACHE = "whoop-pwa-v2";
const ASSETS = ["/", "/css/style.css", "/js/app.js", "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS).catch(() => cache.add("/")))
  );
  self.skipWaiting(); // Сразу активируем новую версию Service Worker
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim(); // Сразу берем контроль над текущими клиентами
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/auth")) return;

  // Стратегия: Network First (Сначала сеть, затем кэш)
  // Гарантирует, что PWA всегда показывает свежую версию, если есть интернет
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => {
        // При ошибке сети (оффлайн) отдаем из кэша
        return caches.match(req);
      })
  );
});
