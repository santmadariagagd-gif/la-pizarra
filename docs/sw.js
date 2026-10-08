/* La Pizarra · service worker (8 oct 2026)
   Sirve para que la página se pueda instalar como app y abra aunque no haya internet.
   Regla: SIEMPRE se pide primero a internet (la página se actualiza cada mañana y no queremos mostrar datos viejos);
   solo si no hay conexión se usa la última copia guardada. Lo de otros sitios (API-Football, Firebase, fuentes) no se toca. */
const CACHE = "pizarra-v1";
const BASICOS = ["/", "/manifest.webmanifest", "/iconos/icono-192.png", "/iconos/icono-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(BASICOS)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;   // solo lo de lapizarra.mx
  const pagina = req.mode === "navigate";
  if (!pagina && !url.pathname.startsWith("/datos/") && !url.pathname.startsWith("/iconos/")) return;
  const llave = pagina ? "/" : url.pathname;   // sin "?v=…": una sola copia por archivo (no se acumulan versiones)
  e.respondWith(
    fetch(req).then(r => {
      if (r.ok && r.type === "basic") { const copia = r.clone(); caches.open(CACHE).then(c => c.put(llave, copia)).catch(() => {}); }
      return r;
    }).catch(() => caches.match(llave).then(c => c || Response.error()))
  );
});
