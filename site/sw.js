// Joinville Meteo — service worker: offline shell + Web Push (ready for the alert channel).
const CACHE = 'joinville-meteo-v1';
const SHELL = ['index.html', 'assets/css/app.css', 'manifest.json',
               'assets/icons/icon-192.png', 'assets/icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});
// network-first for GET: a live data dashboard stays fresh online, falls back to cache offline
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(r => {
      if (r && r.ok) { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); }
      return r;
    }).catch(() => caches.match(e.request).then(m => m || caches.match('index.html')))
  );
});
// --- Web Push (no-op until push subscriptions + a sender exist) ---
self.addEventListener('push', e => {
  let d = { title: 'Joinville · Alerta', body: 'Novo alerta meteorológico.', url: 'index.html' };
  try { if (e.data) d = Object.assign(d, e.data.json()); } catch (_) { if (e.data) d.body = e.data.text(); }
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body, icon: 'assets/icons/icon-192.png', badge: 'assets/icons/icon-192.png',
    tag: d.tag || 'joinville-alert', renotify: true, data: d.url || 'index.html'
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: 'window' }).then(ws => {
    const u = e.notification.data || 'index.html';
    for (const w of ws) { if ('focus' in w) { if (w.navigate) w.navigate(u); return w.focus(); } }
    return clients.openWindow(u);
  }));
});
