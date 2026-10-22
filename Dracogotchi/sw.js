// Service worker de Dracogotchi: guarda la app en el dispositivo para usarla sin conexión.
// Si cambias algún archivo de la app, cambia también este número de versión.
const VERSION = 'dracogotchi-v2';
const ARCHIVOS = [
  './',
  'index.html',
  'acceso.js',
  'manifest.webmanifest',
  'icons/icon-180.png',
  'icons/icon-192.png',
  'icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(VERSION).then((c) => c.addAll(ARCHIVOS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Primero lo guardado (rápido y sin conexión); en segundo plano se refresca para la próxima vez.
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  e.respondWith(
    caches.match(req, { ignoreSearch: true }).then((guardado) => {
      const red = fetch(req)
        .then((r) => {
          if (r && r.ok) {
            const copia = r.clone();
            caches.open(VERSION).then((c) => c.put(req, copia));
          }
          return r;
        })
        .catch(() => guardado || (req.mode === 'navigate' ? caches.match('index.html') : undefined));
      return guardado || red;
    })
  );
});
