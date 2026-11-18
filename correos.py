"""
correos.py — recordatorios por correo (13 nov 2026). Los llama avisos.py en cada corrida (cada 5 min con cron-job.org).

Por qué: casi nadie prende los avisos al teléfono (1 de 18 cuentas). El correo le llega a todos los que tienen cuenta.
Se mandan con Resend (secreto RESEND_API_KEY, dominio lapizarra.mx verificado) desde avisos@lapizarra.mx.

Dos correos, nada más:
  1. Cierre de la Quiniela Liga MX (jornada, Liguilla o Llave): entre 2 y 8 horas antes del cierre, a quien jugó la anterior
     y todavía no hace sus picks. Si ya le llega el aviso al teléfono de "Recordatorios", no se le manda correo.
  2. Tu semana (lunes de 9 a 12): cómo te fue (aciertos, lugar, reto, survivor, fantasy) y lo que viene.
Cada correo trae link para dejar de recibirlos (lapizarra.mx/?correos=0 → Firestore correos/{uid}.no = true).
Lo enviado se anota en sistema/avisos (E["mail"]) para no repetir. Máx. 90 correos por corrida (Resend gratis: 100 al día).
"""
import hashlib, html, json, os, re, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MX = ZoneInfo("America/Mexico_City")
KEY = os.environ.get("RESEND_API_KEY", "")
DE = "La Pizarra <avisos@lapizarra.mx>"
WEB = "https://lapizarra.mx"
BAJA = WEB + "/?correos=0"
TOPE = 90
NJ = {18: "los cuartos de final", 19: "las semifinales", 20: "la final", "llave": "la Llave de la Liguilla"}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def cuando(ts):
    d = datetime.fromtimestamp(ts, MX); hoy = datetime.now(MX).date()
    h = d.strftime("%I:%M").lstrip("0") + (" am" if d.hour < 12 else " pm")
    dia = "hoy" if d.date() == hoy else "mañana" if (d.date() - hoy).days == 1 else f"el {DIAS[d.weekday()]}"
    return f"{dia} a las {h}"


# ---------- diseño (13 nov 2026, v2) ----------
# Pizarrón verde con dibujos de gis (imágenes en lapizarra.mx/correo/: semana, cierre, liga; las hace un script con PIL,
# reto, vuelve, llave; 1200×440). Todo con tablas y estilos en línea para que se vea igual en Gmail, Outlook y Apple Mail. Si el correo no
# carga imágenes, queda el texto alternativo y el fondo verde.
C = dict(fondo="#0F1C18", hoja="#1F332D", caja="#26403A", borde="#3A554C", gis="#ECEFE7", gris="#A8B8AF", ama="#F2D466", tinta="#15241F")
FUENTE = "'Barlow Condensed','Arial Narrow',Helvetica,Arial,sans-serif"
TXT = "Helvetica,Arial,sans-serif"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIA3 = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]
e = html.escape


def tarjetas(items):
    """Cuadritos de dos en dos: (ícono, qué, número grande, detalle)."""
    celdas = []
    for ic, que, big, det in items:
        celdas.append(f"""<td width="50%" valign="top" style="padding:6px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['caja']};border:1px solid {C['borde']};border-radius:14px">
<tr><td style="padding:14px 14px 4px"><span style="display:inline-block;width:36px;height:36px;line-height:36px;text-align:center;border-radius:18px;background:{C['ama']};font-size:19px">{ic}</span></td></tr>
<tr><td style="padding:6px 14px 0;font:700 12px/1.2 {TXT};letter-spacing:.06em;text-transform:uppercase;color:{C['gris']}">{e(que)}</td></tr>
<tr><td style="padding:4px 14px 0;font:800 24px/1.1 {FUENTE};color:{C['gis']}">{e(big)}</td></tr>
<tr><td style="padding:3px 14px 14px;font:400 13px/1.35 {TXT};color:{C['gris']}">{e(det)}</td></tr></table></td>""")
    if len(celdas) % 2: celdas.append('<td width="50%" style="padding:6px"></td>')
    filas = "".join("<tr>" + celdas[k] + celdas[k + 1] + "</tr>" for k in range(0, len(celdas), 2))
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 14px">{filas}</table>'


def agenda(items):
    """Lo que viene: (timestamp o None, texto). Con fecha → cuadrito de calendario; sin fecha → ✏️."""
    filas = []
    for ts, txt in items:
        if ts:
            d = datetime.fromtimestamp(ts, MX)
            chip = f"""<td width="52" valign="top"><table role="presentation" cellpadding="0" cellspacing="0" style="width:46px;border-radius:10px;overflow:hidden;border:1px solid {C['borde']}">
<tr><td align="center" style="background:{C['ama']};font:800 11px/1 {TXT};color:{C['tinta']};padding:4px 0">{DIA3[d.weekday()]}</td></tr>
<tr><td align="center" style="background:{C['gis']};font:800 20px/1 {FUENTE};color:{C['tinta']};padding:5px 0 4px">{d.day}</td></tr></table></td>"""
            sub = cuando(ts)
        else:
            chip = f'<td width="52" valign="top" align="center" style="font-size:24px;line-height:40px">✏️</td>'; sub = "todos los días"
        filas.append(f"""<tr>{chip}<td valign="middle" style="padding:2px 0 14px 10px"><div style="font:700 15px/1.3 {TXT};color:{C['gis']}">{e(txt)}</div>
<div style="font:400 13px/1.3 {TXT};color:{C['gris']}">{e(sub)}</div></td></tr>""")
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(filas)}</table>'


def titulo2(t):
    return f'<div style="margin:18px 0 10px;padding-top:16px;border-top:2px dashed {C["borde"]};font:800 13px/1 {TXT};letter-spacing:.12em;text-transform:uppercase;color:{C["ama"]}">{e(t)}</div>'


def parrafo(t):   # t ya viene escapado
    return f'<p style="margin:0 0 14px;font:400 16px/1.5 {TXT};color:{C["gis"]}">{t}</p>'


def cuenta_atras(ts):
    h = max(1, round((ts - time.time()) / 3600))
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 16px;background:{C['tinta']};border:2px solid {C['ama']};border-radius:16px">
<tr><td width="120" align="center" style="padding:16px 8px;border-right:2px dashed {C['borde']}"><div style="font:800 54px/1 {FUENTE};color:{C['ama']}">{h}</div>
<div style="font:700 12px/1.2 {TXT};letter-spacing:.08em;text-transform:uppercase;color:{C['gris']}">{"hora" if h == 1 else "horas"}</div></td>
<td style="padding:16px 18px"><div style="font:800 20px/1.2 {FUENTE};color:{C['gis']}">Cierra {e(cuando(ts))}</div>
<div style="font:400 14px/1.4 {TXT};color:{C['gris']};margin-top:4px">Lo que no escojas antes vale cero en la tabla.</div></td></tr></table>"""


def pasos(items):
    filas = "".join(f"""<tr><td width="40" valign="top"><span style="display:inline-block;width:24px;height:24px;line-height:24px;text-align:center;border-radius:14px;border:2px solid {C['ama']};font:800 15px {FUENTE};color:{C['ama']}">{k}</span></td>
<td style="padding:3px 0 12px;font:400 15px/1.45 {TXT};color:{C['gis']}">{t}</td></tr>""" for k, t in enumerate(items, 1))
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:4px 0 8px">{filas}</table>'


def plantilla(cabeza, kicker, titulo, cuerpo, boton, url, pre=""):
    """cabeza: semana | cierre | liga (la imagen de arriba). cuerpo: HTML ya armado con los bloques de arriba."""
    img = f"{WEB}/correo/{cabeza}.png"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light"><meta name="supported-color-schemes" content="dark light"><title>{e(titulo)}</title></head>
<body style="margin:0;padding:0;background:{C['fondo']}">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{C['fondo']}">{e(pre)}&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;&#8199;&#847;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{C['fondo']}"><tr><td align="center" style="padding:20px 10px 28px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:{C['hoja']};border-radius:18px;border:1px solid {C['borde']}">
<tr><td style="padding:0;line-height:0"><a href="{url}"><img src="{img}" width="560" alt="La Pizarra" style="display:block;width:100%;max-width:560px;height:auto;border:0;border-radius:18px 18px 0 0;background:{C['hoja']};color:{C['ama']};font:800 28px {FUENTE}"></a></td></tr>
<tr><td style="padding:22px 26px 8px">
<div style="font:800 12px/1 {TXT};letter-spacing:.14em;text-transform:uppercase;color:{C['ama']};margin-bottom:10px">{e(kicker)}</div>
<h1 style="margin:0 0 14px;font:800 32px/1.08 {FUENTE};color:{C['gis']}">{e(titulo)}</h1>
{cuerpo}
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:10px 0 22px"><tr><td style="border-radius:12px;background:{C['ama']};box-shadow:0 4px 0 #B89A2E">
<a href="{url}" style="display:inline-block;padding:15px 26px;font:800 18px/1 {FUENTE};letter-spacing:.02em;color:{C['tinta']};text-decoration:none;border-radius:12px">{e(boton)} →</a></td></tr></table>
</td></tr>
<tr><td style="padding:16px 26px 22px;border-top:1px solid {C['borde']};font:400 12px/1.55 {TXT};color:{C['gris']}">
<b style="color:{C['gis']}">La Pizarra</b> · quinielas, retos y la carrilla de tu grupo · <a href="{WEB}" style="color:{C['gris']}">lapizarra.mx</a><br>
Te llega porque tienes cuenta en La Pizarra. <a href="{BAJA}" style="color:{C['gris']}">Ya no quiero estos correos</a>.</td></tr>
</table></td></tr></table></body></html>"""


def texto_plano(titulo, lineas, boton, url):
    return f"{titulo}\n\n" + "\n".join(lineas) + f"\n\n{boton}: {url}\n\n—\nLa Pizarra · Ya no quiero estos correos: {BAJA}\n"


class Correos:
    def __init__(self, av):
        self.av, self.db, self.E = av, av.db, av.E
        self.E.setdefault("mail", {})
        self.n = 0; self._quien = None

    # ---- quién puede recibir: cuentas con correo confirmado que no los apagaron ----
    def quien(self):
        if self._quien is None:
            from firebase_admin import auth
            no = {d.id for d in self.db.c.collection("correos").stream() if (d.to_dict() or {}).get("no")}
            self._quien = {}; self.meta = {}
            for u in auth.list_users().iterate_all():
                if not (u.email and u.email_verified and not u.disabled and u.uid not in no): continue
                self._quien[u.uid] = (u.email, (u.display_name or "").split(" ")[0])
                m = u.user_metadata
                self.meta[u.uid] = ((m.creation_timestamp or 0) / 1000, max(m.last_sign_in_timestamp or 0, getattr(m, "last_refresh_timestamp", 0) or 0) / 1000)
        return self._quien

    def manda(self, uid, clave, asunto, html_, texto):
        if clave in self.E["mail"] or self.n >= TOPE: return
        q = self.quien().get(uid)
        if not q: return
        email, nom = q
        if not KEY: print(f"✉ (sin RESEND_API_KEY) {uid[:6]}… {asunto}"); return
        cuerpo = dict(**{"from": DE}, to=[email], subject=asunto, html=html_, text=texto,
                      headers={"List-Unsubscribe": f"<{BAJA}>"}, tags=[{"name": "tipo", "value": clave.split("-")[0]}])
        try:
            r = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(cuerpo).encode(), method="POST",
                                       headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "la-pizarra-correos/1.0"})
            with urllib.request.urlopen(r, timeout=20) as x: x.read()
            self.E["mail"][clave] = int(time.time()); self.n += 1
            print(f"✉ {clave.split('-')[0]}")   # sin asunto: puede traer apodos y el log es público
        except Exception as e:
            print("Correo:", getattr(e, "code", ""), str(getattr(e, "read", lambda: b"")() or e)[:200])

    # ---- 1. cierre de la Quiniela Liga MX ----
    def cierres(self):
        now = time.time()
        for jd in self.db.rango("qmx_jornadas", "primero", now + 2 * 3600, now + 8 * 3600):
            jid, sl, j, ts = jd["_id"], jd.get("s"), jd.get("j"), jd["_ts"]
            if j == "llave": prev = f"{sl}-17"
            elif isinstance(j, int): prev = f"{sl}-{j - 1}"
            else: continue
            nj = NJ.get(j, f"la jornada {j}")
            Q = self.db.donde("qmx_picks", "jid", "in", [jid, prev])
            jug = {d.get("uid") for d in Q if d.get("jid") == prev}
            if j == "llave": jug = set(self.quien())      # la Llave es para todos (18 nov 2026), no solo para quien jugó la 17
            hechos = {d.get("uid") for d in Q if d.get("jid") == jid and (d.get("p") or {})}
            for uid in jug - hechos:
                S = self.av.subs.get(uid)
                if S and S.get("tk") and S.get("p", {}).get("cie", 1): continue   # ya le llega al teléfono
                nom = self.quien().get(uid, ("", ""))[1]
                h_, t_ = self.correo_cierre(nom, nj, ts)
                cv = "cierran" if nj.startswith(("los ", "las ")) else "cierra"
                self.manda(uid, f"cie-{jid}-{uid[:10]}", f"⏰ Te faltan tus picks: {nj} {cv} {cuando(ts)}", h_, t_)

    def correo_cierre(self, nom, nj, ts):
        q = (f"{e(nom)}, todavía" if nom else "Todavía") + f" no haces tus picks de <b>{e(nj)}</b> en la Quiniela Liga MX."
        cuerpo = parrafo(q) + cuenta_atras(ts) + titulo2("Son dos minutos") + pasos([
            "Abre la Quiniela Liga MX en La Pizarra.", "En cada partido escoge <b>local, empate o visita</b>.",
            "Listo: tus picks se guardan solos y tu grupo los ve cuando arranca el partido."])
        url = WEB + "/#quinielamx"
        return (plantilla("cierre", "Quiniela Liga MX", f"Te faltan tus picks de {nj}", cuerpo, "Hacer mis picks", url,
                          pre=f"Te faltan tus picks de {nj}. Cierra {cuando(ts)}."),
                texto_plano(f"Te faltan tus picks de {nj} (cierra {cuando(ts)})", [re.sub(r"<[^>]+>", "", q), "Escoge local, empate o visita en cada partido. Lo que no escojas vale cero."], "Hacer mis picks", url))

    # ---- 2. tu semana (lunes) ----
    def semanal(self, solo=None):
        ahora = datetime.now(MX)
        if solo is None and (ahora.weekday() != 0 or not (9 <= ahora.hour < 12)): return
        sem = ahora.date().isoformat() if solo is None else f"prueba{int(time.time())}"
        L = self.av.lineas_semana(list(self.quien()))
        self.av.lo_que_viene()
        for uid in (solo or list(self.quien())):
            nom = self.quien()[uid][1]
            h_, t_ = self.correo_semana(nom, getattr(self.av, "est", {}).get(uid) or [], getattr(self.av, "prox", []), L.get(uid) or [])
            self.manda(uid, f"sem-{sem}-{uid[:10]}", "📊 Tu semana en La Pizarra", h_, t_)

    def correo_semana(self, nom, T, prox, lineas):
        hoy = datetime.now(MX).date()
        kick = f"Semana del {hoy.day} de {MESES[hoy.month - 1]}"
        if T:
            tit = f"{nom}, así te fue" if nom else "Así te fue"
            cuerpo = parrafo("Tu semana pasada en La Pizarra, en corto:") + tarjetas(T[:4])
        else:
            tit = f"{nom}, esta semana se juega" if nom else "Esta semana se juega"
            cuerpo = parrafo("La semana pasada no jugaste nada en La Pizarra. Ésta puedes empezar con cualquiera de estos:") + tarjetas([
                ("🎯", "Quiniela Liga MX", "Local, empate o visita", "contra tu grupo, jornada por jornada"),
                ("🧠", "Reto del día", "1 pregunta", "nueva cada mañana en la portada")])
        ag = [(ts, t) for ts, t in prox[:3]] + [(None, "Reto del día: una pregunta nueva en la portada")]
        cuerpo += titulo2("Lo que viene") + agenda(ag)
        cuerpo += titulo2("Para el grupo") + parrafo("Reta a un amigo, haz tus picks y presume tu semana en el grupo. 🗣️")
        url = WEB + "/?sem=1"
        pre = (" · ".join(lineas[:2]) or "Lo que viene esta semana en La Pizarra")
        return (plantilla("semana", kick, tit, cuerpo, "Ver mi semana", url, pre=pre[:1].upper() + pre[1:]),
                texto_plano(tit, [f"• {x}" for x in lineas[:5]] + ["", "Lo que viene:"] + [f"• {t} ({cuando(ts)})" for ts, t in prox[:3]] + ["• Reto del día: una pregunta nueva en la portada"], "Ver mi semana", url))

    # ---- 3. racha en peligro (18 nov 2026) ----
    def racha(self, solo=None, forzar=False):
        """Quien lleva 2+ días seguidos contestando el reto del día y hoy no ha contestado: correo entre 1 y 5 h antes del cierre.
        A quien tiene avisos al teléfono ya le llega el push de 90 min antes; a esos no se les manda correo."""
        ahora = datetime.now(MX)
        if not forzar and not (8 <= ahora.hour < 22): return
        now = time.time()
        retos = self.db.rango("retos_dia", "cierre", now + 3600, now + 5 * 3600)
        if forzar and not retos:
            retos = [{"_id": ahora.date().isoformat(), "_ts": now + 4 * 3600 + 60}]
        for rd in retos:
            f, ts = rd["_id"], rd["_ts"]
            d0 = datetime.fromisoformat(f).date()
            dias = [(d0 - timedelta(days=k)).isoformat() for k in range(0, 15)]
            R = self.db.donde("rd_resp", "f", "in", dias)
            hechos = {}
            for x in R: hechos.setdefault(x.get("uid"), set()).add(x.get("f"))
            pregunta = self.pregunta(f)
            for uid in (solo or list(self.quien())):
                F = hechos.get(uid, set())
                if f in F and not forzar: continue
                n = 0
                while dias[n + 1] in F if n + 1 < len(dias) else False: n += 1
                if forzar: n = max(n, 3)
                if n < 2: continue
                S = self.av.subs.get(uid)
                if not forzar and S and S.get("tk"): continue
                nom = self.quien()[uid][1]
                h_, t_ = self.correo_racha(nom, n, ts, pregunta)
                self.manda(uid, f"rac-{f}{'p' + str(int(now)) if forzar else ''}-{uid[:10]}", f"🔥 {nom + ', tu' if nom else 'Tu'} racha de {n} días está en peligro", h_, t_)

    def pregunta(self, f):
        try:
            x = (json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "reto_dia.json"), encoding="utf-8")).get("d") or {}).get(f) or {}
        except Exception: x = {}
        h, a = x.get("hn") or x.get("h"), x.get("an") or x.get("a")
        if not h or not isinstance(h, str): return ""
        q = x.get("q")
        return {"gana": f"¿Quién gana: {h} o {a}?", "goles": f"¿Cuántos goles hay en {h} vs {a}?", "ambos": f"¿Anotan los dos en {h} vs {a}?",
                "spread": f"¿Quién cubre la línea en {a} @ {h}?", "total": f"¿Más o menos puntos en {a} @ {h}?"}.get(q, f"Hoy: {h} vs {a}.")

    def correo_racha(self, nom, n, ts, pregunta):
        fuegos = "🔥" * min(n, 7)
        cuerpo = parrafo((f"{e(nom)}, llevas" if nom else "Llevas") + f" <b>{n} días seguidos</b> contestando el reto del día. Hoy todavía no contestas, y si se cierra sin tu respuesta la racha vuelve a cero.")
        cuerpo += f'<div style="margin:4px 0 14px;font-size:30px;letter-spacing:2px">{fuegos}</div>'
        if pregunta: cuerpo += titulo2("La pregunta de hoy") + parrafo(f"<b>{e(pregunta)}</b>")
        cuerpo += cuenta_atras(ts).replace("Lo que no escojas antes vale cero en la tabla.", "Una pregunta, diez segundos.")
        url = WEB + "/#hoy"
        return (plantilla("reto", "Reto del día", f"Tu racha de {n} días está en peligro", cuerpo, "Contestar el reto", url, pre=pregunta or "Contesta el reto de hoy antes de que cierre."),
                texto_plano(f"Tu racha de {n} días está en peligro", [f"Llevas {n} días seguidos contestando el reto del día. Hoy todavía no contestas.", pregunta, f"Cierra {cuando(ts)}."], "Contestar el reto", url))

    # ---- 4. te extrañamos (18 nov 2026) ----
    def extranamos(self, solo=None, forzar=False):
        """A quien no ha usado La Pizarra en 7+ días (y tiene cuenta de hace 3+ días): qué hicieron sus amigos y lo que viene.
        Máximo uno cada 14 días; nunca en lunes (ese día va "Tu semana"); de 6 a 8 pm."""
        ahora = datetime.now(MX)
        if not forzar and (ahora.weekday() == 0 or not (18 <= ahora.hour < 20)): return
        now = time.time(); hoy = ahora.date()
        dias30 = [(hoy - timedelta(days=k)).isoformat() for k in range(30)]
        R = self.db.donde("rd_resp", "f", "in", dias30)
        rd_ult, rd7 = {}, {}
        for x in R:
            u, f = x.get("uid"), x.get("f") or ""
            rd_ult[u] = max(rd_ult.get(u, ""), f)
            if f >= (hoy - timedelta(days=7)).isoformat(): rd7[u] = rd7.get(u, 0) + 1
        P = self.db.nuevos("posts", "t", now - 30 * 86400)
        po_ult, po7 = {}, {}
        for x in P:
            u = x.get("uid"); t = x.get("t"); t = t.timestamp() if hasattr(t, "timestamp") else 0
            po_ult[u] = max(po_ult.get(u, 0), t)
            if t > now - 7 * 86400: po7[u] = po7.get(u, 0) + 1
        sync = {}
        for d in self.db.c.collection("usuarios").select(["t"]).stream():
            t = (d.to_dict() or {}).get("t"); sync[d.id] = t.timestamp() if hasattr(t, "timestamp") else 0
        amigos = {}
        for d in self.db.c.collection("amistades").stream():
            x = d.to_dict() or {}
            if x.get("est") != "ok": continue
            u = x.get("u") or []
            for a in u:
                for b in u:
                    if a != b: amigos.setdefault(a, set()).add(b)
        apodo = {d.id: (d.to_dict() or {}).get("a") or "" for d in self.db.c.collection("perfiles").select(["a"]).stream()}
        jugaron7 = len([u for u in rd7])
        self.av.lo_que_viene(); prox = getattr(self.av, "prox", [])
        for uid in (solo or list(self.quien())):
            alta, acc = self.meta.get(uid, (0, 0))
            ult = max(acc, sync.get(uid, 0), po_ult.get(uid, 0),
                      datetime.fromisoformat(rd_ult[uid]).replace(tzinfo=MX).timestamp() if uid in rd_ult else 0)
            if not forzar and (now - ult < 7 * 86400 or now - alta < 3 * 86400): continue
            if not forzar and any(k.startswith("ext-") and k.endswith(uid[:10]) and v > now - 14 * 86400 for k, v in self.E["mail"].items()): continue
            T = []
            for a in sorted(amigos.get(uid, ()), key=lambda a: -(rd7.get(a, 0) * 2 + po7.get(a, 0))):
                if not apodo.get(a) or not (rd7.get(a) or po7.get(a)): continue
                if rd7.get(a): T.append(("🧠", apodo[a][:20], f"{rd7[a]} {'reto' if rd7[a] == 1 else 'retos'}", "contestó esta semana"))
                else: T.append(("💬", apodo[a][:20], f"{po7[a]} {'post' if po7[a] == 1 else 'posts'}", "publicó esta semana"))
                if len(T) == 4: break
            nom = self.quien()[uid][1]
            dias = max(7, int((now - ult) / 86400)) if ult else None
            h_, t_ = self.correo_extranamos(nom, T, jugaron7, prox, dias)
            asunto = f"👀 {T[0][1]} y tus amigos siguen jugando" if T else (f"👀 {nom}, esto pasó en La Pizarra" if nom else "👀 Esto pasó en La Pizarra")
            self.manda(uid, f"ext-{hoy.isoformat()}{'p' + str(int(now)) if forzar else ''}-{uid[:10]}", asunto, h_, t_)

    def correo_extranamos(self, nom, T, jugaron7, prox, dias):
        hace = f"Hace {dias} días que no te vemos" if dias and dias < 60 else "Hace rato que no te vemos"
        cuerpo = parrafo((f"{e(nom)}, h" if nom else "H") + hace[1:] + " en La Pizarra. Esto es lo que te perdiste:")
        if T:
            cuerpo += titulo2("Tus amigos esta semana") + tarjetas(T)
        else:
            cuerpo += tarjetas([("🧠", "Reto del día", f"{jugaron7} {'persona' if jugaron7 == 1 else 'personas'}", "lo jugaron esta semana"),
                                ("🤝", "Amigos", "Agrega a uno", "jugar contra alguien es lo divertido")])
        ag = [(ts, t) for ts, t in prox[:3]] + [(None, "Reto del día: una pregunta nueva cada día")]
        cuerpo += titulo2("Lo que viene") + agenda(ag)
        url = WEB + "/?vuelve=1"
        lineas = [f"• {t[1]} {t[3].replace(' esta semana', '')} {t[2]} esta semana" for t in T] or [f"• {jugaron7} personas jugaron el reto del día esta semana."]
        return (plantilla("vuelve", "Te extrañamos", "Esto pasó mientras no estabas", cuerpo, "Volver a La Pizarra", url,
                          pre=(f"{T[0][1]} {T[0][3]}: {T[0][2]}." if T else "Lo que pasó en La Pizarra y lo que viene.")),
                texto_plano("Esto pasó mientras no estabas", [hace + "."] + lineas + ["", "Lo que viene:"] + [f"• {t} ({cuando(ts)})" for ts, t in prox[:3]], "Volver a La Pizarra", url))

    # ---- 5. se abrió la Llave de la Liguilla (18 nov 2026) ----
    def llave(self, solo=None, forzar=False):
        """Cuando el build abre la Llave (qmx_jornadas con j="llave"): un correo a todas las cuentas que no la han llenado,
        si faltan más de 8 horas para el cierre (lo de 2-8 h antes lo cubre el recordatorio de cierres)."""
        ahora = datetime.now(MX); now = time.time()
        if not forzar and not (9 <= ahora.hour < 21): return
        L = [x for x in self.db.donde("qmx_jornadas", "j", "==", "llave") if x.get("primero")]
        for jd in L:
            pr = jd.get("primero"); ts = pr.timestamp() if hasattr(pr, "timestamp") else 0
            if not forzar and ts < now + 8 * 3600: continue
            if forzar and ts < now: ts = now + 3 * 86400
            jid = jd["_id"]
            hechos = {d.get("uid") for d in self.db.donde("qmx_picks", "jid", "==", jid) if (d.get("p") or {})}
            for uid in (solo or list(self.quien())):
                if uid in hechos and not forzar: continue
                nom = self.quien()[uid][1]
                h_, t_ = self.correo_llave(nom, ts)
                self.manda(uid, f"llave-{jid}{'p' + str(int(now)) if forzar else ''}-{uid[:10]}", "🏆 Ya se abrió la Llave de la Liguilla", h_, t_)
        if forzar and not L:
            for uid in (solo or []):
                h_, t_ = self.correo_llave(self.quien()[uid][1], now + 3 * 86400)
                self.manda(uid, f"llave-prueba{int(now)}-{uid[:10]}", "🏆 (Prueba) Ya se abrió la Llave de la Liguilla", h_, t_)

    def correo_llave(self, nom, ts):
        cuerpo = parrafo((f"{e(nom)}, ya" if nom else "Ya") + " están los 8 de la Liguilla. Llena tu Llave una sola vez y te acompaña hasta la final: quién pasa a semis, quién llega a la final y quién se corona.")
        cuerpo += tarjetas([("🎯", "Semifinalistas", "1 punto", "por cada uno que atines"), ("🥈", "Finalistas", "3 puntos", "por cada uno"),
                            ("🏆", "Campeón", "5 puntos", "si le atinas"), ("📊", "Tabla general", "Se suma", "a tus puntos de la quiniela")])
        cuerpo += titulo2("Cierra cuando arrancan los cuartos") + parrafo(f"Tienes hasta <b>{e(cuando(ts))}</b>. Son 2 minutos.")
        cuerpo += pasos(["Escoge quién pasa en cada serie de cuartos.", "Luego tus dos finalistas y tu campeón.", "Presume tu Llave en el grupo con el botón 📸 y reta a tus amigos."])
        url = WEB + "/?llave=1"
        return (plantilla("llave", "Quiniela Liga MX · Liguilla", "Llena tu Llave de la Liguilla", cuerpo, "Llenar mi Llave", url,
                          pre=f"Semifinalistas, finalistas y campeón: hasta 5 puntos. Cierra {cuando(ts)}."),
                texto_plano("Llena tu Llave de la Liguilla", ["Ya están los 8 de la Liguilla.", "Semifinalistas: 1 punto cada uno · Finalistas: 3 · Campeón: 5.", f"Cierra {cuando(ts)}."], "Llenar mi Llave", url))

    def prueba(self):
        """Workflow "Avisos" a mano con prueba_correo=1: manda el correo del lunes solo al dueño (huella del correo)."""
        duenos = [u for u, (e, _) in self.quien().items() if hashlib.sha256(e.strip().lower().encode()).hexdigest()[:16] == "bbd57af465240ba7"]
        print(f"Correo de prueba al dueño: {len(duenos)} cuenta(s)")
        self.semanal(solo=duenos)
        for uid in duenos:      # y el de cierre, con unos cuartos de final de mentiritas a 5 horas
            h_, t_ = self.correo_cierre(self.quien()[uid][1], "los cuartos de final", time.time() + 5 * 3600 + 120)
            self.manda(uid, f"cie-prueba{int(time.time())}-{uid[:10]}", "⏰ (Prueba) Te faltan tus picks: los cuartos de final cierran hoy", h_, t_)
        if os.environ.get("CORREO_PRUEBA") == "2":   # 2 = además racha, te extrañamos y Llave
            self.racha(solo=duenos, forzar=True); self.extranamos(solo=duenos, forzar=True); self.llave(solo=duenos, forzar=True)

    def corre(self):
        if os.environ.get("CORREO_PRUEBA") in ("1", "2"):
            try: self.prueba()
            except Exception as e: print("Correos (prueba):", repr(e))
        try: self.cierres()
        except Exception as e: print("Correos (cierres):", repr(e))
        try: self.semanal()
        except Exception as e: print("Correos (semana):", repr(e))
        for f_ in (self.racha, self.extranamos, self.llave):
            try: f_()
            except Exception as e: print(f"Correos ({f_.__name__}):", repr(e))
        if self.n: print(f"Correos mandados: {self.n}")
