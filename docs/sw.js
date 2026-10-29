/* La Pizarra · service worker (8 oct 2026)
   Sirve para que la página se pueda instalar como app y abra aunque no haya internet.
   Regla: SIEMPRE se pide primero a internet (la página se actualiza cada mañana y no queremos mostrar datos viejos);
   solo si no hay conexión se usa la última copia guardada. Lo de otros sitios (API-Football, Firebase, fuentes) no se toca. */
const CACHE = "pizarra-v2";
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

/* Avisos al teléfono (29 oct 2026): el robot avisos.py manda {t: título, b: texto, u: a dónde lleva, g: etiqueta} por Firebase
   Cloud Messaging. Aquí se muestran (aunque la página esté cerrada) y al tocarlos se abre La Pizarra en esa sección. */
self.addEventListener("push", e => {
  let j = {};
  try { j = e.data ? e.data.json() : {}; } catch (_) { try { j = { data: { b: e.data.text() } }; } catch (__) {} }
  const d = j.data || j.notification || j || {};
  const titulo = d.t || d.title || "La Pizarra", cuerpo = d.b || d.body || "";
  e.waitUntil(self.registration.showNotification(titulo, {
    body: cuerpo, icon: "/iconos/icono-192.png", lang: "es-MX",
    tag: d.g || undefined, data: { u: d.u || "/" }
  }));
});
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.u) || "/", self.location.origin).href;
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(L => {
    const c = L.find(x => x.url.startsWith(self.location.origin));
    if (c) return c.navigate(url).then(x => (x || c).focus()).catch(() => c.focus());
    return self.clients.openWindow(url);
  }));
});
