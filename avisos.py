"""
La Pizarra · Avisos al teléfono (29 oct 2026)

Corre cada 10 minutos en GitHub (.github/workflows/avisos.yml). Lee quién activó los avisos (avisos_tk/{uid}),
sus equipos favoritos (usuarios/{uid}.fav) y lo nuevo en Firebase, y manda notificaciones con Firebase Cloud Messaging:

  · Partidos de tus equipos (p.eq): "en un rato juega…" y el resultado final. Fútbol (API-Football), NFL y NBA (marcadores públicos de ESPN).
  · Goles (p.gol): cada gol de un partido de tus equipos de fútbol.
  · Amigos (p.soc): solicitudes de amistad, solicitudes aceptadas y comentarios en tus posts.
  · Retos (p.ret): cuando un amigo te reta a un duelo.
  · Recordatorios de cierre (p.cie): la quiniela de Liga MX, el Survivor o el reto del día cierran pronto y no has jugado.
  · Sufrimiento ajeno (p.riv): cuando pierde el rival de toda la vida de tu equipo (América-Pumas, Real Madrid-Barça…).
Los textos cambian según cómo va el partido (remontadas, goles al final, goleadas, penales).

Si hay un partido de tus equipos en juego, se queda revisando ~9 minutos (cada minuto) para que los goles lleguen rápido.
Lo que ya se mandó se anota en sistema/avisos (solo GitHub lo lee) para no repetir.
Variables: FIREBASE_SA (llave de servicio, secreto), API_FOOTBALL_KEY (secreto). PRUEBA=1: no manda nada, solo imprime.
"""
import os, json, time, hashlib, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

MX = ZoneInfo("America/Mexico_City")
PRUEBA = os.environ.get("PRUEBA") == "1"
AFK = os.environ.get("API_FOOTBALL_KEY", "").strip()
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
NFL_AB = {"WSH": "WAS", "LAR": "LA"}
NBA_AB = {"NY": "NYK", "SA": "SAS", "GS": "GSW", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS", "PHO": "PHX", "BRK": "BKN", "CHO": "CHA"}
DU_T = {"mx": "Quiniela Liga MX", "fan": "Fantasy Champions", "rd": "Reto del día"}
AF_FIN, AF_NO = {"FT", "AET", "PEN"}, {"PST", "CANC", "ABD", "AWD", "WO", "TBD"}
DUR = 9 * 60          # cuánto se queda revisando si hay partido en juego
CADA = 60             # cada cuánto revisa en ese rato (1 llamada a API-Football por vuelta, solo con partido en juego)

def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "LaPizarra/1.0 (+https://lapizarra.mx)", "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

AF_N = 0
def af(ruta, **q):
    global AF_N
    if not AFK: return []
    AF_N += 1
    try:
        j = get_json("https://v3.football.api-sports.io/" + ruta + "?" + urllib.parse.urlencode(q), {"x-apisports-key": AFK})
    except Exception as e:
        print("API-Football:", ruta, e); return []
    if j.get("errors"): print("API-Football:", ruta, j.get("errors")); return []
    return j.get("response") or []

def hora(ts):
    return datetime.fromtimestamp(ts, MX).strftime("%-I:%M %p").replace("AM", "am").replace("PM", "pm")

def corta(s, n=70):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


# ---------- Textos con personalidad (29 oct 2026) ----------
# Cada aviso elige entre varias frases (siempre la misma para el mismo partido/persona, para no repetir al reintentar).
def elige(semilla, opciones):
    return opciones[int(hashlib.sha1(str(semilla).encode()).hexdigest(), 16) % len(opciones)]

# Nombres cortos en español (API-Football los trae en inglés o largos)
NOMBRES = {2287: "el América", 2286: "Pumas", 2278: "Chivas", 2283: "Atlas", 2295: "Cruz Azul", 2279: "Tigres", 2282: "Rayados",
           2281: "Toluca", 2292: "Pachuca", 2289: "León", 2291: "Puebla", 2285: "Santos", 2288: "Necaxa", 2280: "Xolos",
           541: "el Real Madrid", 529: "el Barça", 530: "el Atlético", 536: "el Sevilla", 543: "el Betis",
           33: "el Manchester United", 40: "el Liverpool", 50: "el Manchester City", 42: "el Arsenal", 47: "el Tottenham", 45: "el Everton", 49: "el Chelsea",
           505: "el Inter", 489: "el Milan", 496: "la Juventus", 497: "la Roma", 487: "la Lazio", 157: "el Bayern", 165: "el Dortmund", 85: "el PSG", 81: "el Marsella"}
def nombre(i, defecto):
    n = NOMBRES.get(i)
    return n[3:] if n and n.startswith("el ") else n[3:] if n and n.startswith("la ") else (n or defecto)
def nombre_art(i, defecto):   # "el América", "la Juventus"
    return NOMBRES.get(i) or defecto

# Rivales de toda la vida (en los dos sentidos). f = fútbol (id de API-Football), n = NFL, b = NBA
_PARES = [("f2287", "f2278"), ("f2287", "f2286"), ("f2287", "f2295"), ("f2278", "f2283"), ("f2279", "f2282"), ("f2286", "f2295"),
          ("f541", "f529"), ("f541", "f530"), ("f536", "f543"), ("f33", "f40"), ("f33", "f50"), ("f42", "f47"), ("f40", "f45"),
          ("f505", "f489"), ("f505", "f496"), ("f497", "f487"), ("f157", "f165"), ("f85", "f81"),
          ("nKC", "nLV"), ("nDAL", "nPHI"), ("nDAL", "nWAS"), ("nGB", "nCHI"), ("nPIT", "nBAL"), ("nNE", "nNYJ"), ("nSF", "nSEA"),
          ("bLAL", "bBOS"), ("bNYK", "bBOS"), ("bLAL", "bLAC"), ("bGSW", "bCLE")]
RIVALES = {}
for a, b in _PARES:
    RIVALES.setdefault(a, set()).add(b); RIVALES.setdefault(b, set()).add(a)

def titulo_gol(nuestro, nom, riv, yo, el, antes, peor, m, autogol, sem):
    """yo/el: marcador ya con el gol; antes: diferencia antes del gol; peor: la peor diferencia que tuvimos."""
    m = m or 0
    N = nom.upper()
    if nuestro:
        if yo - el == 0: return elige(sem, [f"⚽ ¡EMPATA {N}! Aquí hay partido", f"⚽ ¡Gol de {nom}! Se empareja todo", f"⚽ ¡{N} lo empata! No estaba muerto"])
        if yo > el and antes <= 0 and peor < 0: return elige(sem, [f"🔥 ¡LA REMONTADA! {nom} le da la vuelta", f"🔥 ¡{N} LO VOLTEÓ!", f"🔥 ¡De atrás para adelante! {nom} ya gana"])
        if yo > el and antes == 0 and m >= 80: return elige(sem, [f"⚽ ¡GOL DE {N} AL {m}'! Que alguien detenga el reloj", f"⚽ ¡{N} lo gana al final! ¡Gol al {m}'!", f"⚽ ¡En el último suspiro! Gol de {nom}"])
        if yo - el >= 3: return elige(sem, [f"⚽ ¡Otro de {nom}! Esto ya es goleada", f"⚽ ¡Y van {yo}! {nom} no tiene piedad", f"⚽ ¡Baile! Gol de {nom}"])
        if m and m <= 5: return elige(sem, [f"⚽ ¡Tempranero! Gol de {nom} al {m}'", f"⚽ ¡Ni se habían acomodado! Gol de {nom}"])
        return elige(sem, [f"⚽ ¡GOOOL DE {N}!", f"⚽ ¡Gol de {nom}! Grítalo", f"⚽ ¡GOL! {nom} pega primero" if yo == 1 and el == 0 else f"⚽ ¡GOL DE {N}!", f"⚽ ¡Gooool! Anota {nom}"])
    if autogol: return elige(sem, [f"🤦 Autogol de {nom}…", f"🤦 Nos la metimos solos: autogol de {nom}"])
    if yo - el == 0 and m >= 80: return elige(sem, [f"💔 {riv} lo empata al {m}'…", f"💔 Se nos escapó al final: empata {riv}"])
    if yo < el and antes > 0: return elige(sem, [f"😱 {riv} le da la vuelta a {nom}", f"😱 Se voltea el partido: gana {riv}"])
    if el - yo >= 3: return elige(sem, [f"🙈 Otro de {riv}. Mejor ni veas", f"🙈 {riv} ya va {el}-{yo}. Paciencia…"])
    if m >= 85 and yo < el: return elige(sem, [f"💔 Gol de {riv} al {m}'. Duele", f"💔 {riv} anota al final. Ni modo"])
    return elige(sem, [f"😬 Gol de {riv}", f"😬 Nos anotó {riv}. Respira", f"😬 Gol de {riv}. Todavía hay tiempo" if (m or 0) < 75 else f"😬 Gol de {riv}"])

def titulo_final(nom, riv, yo, el, peor, mejor, py, pe, sem):
    if py is not None and pe is not None and yo == el:
        return f"😮‍💨 ¡{nom} gana en penales!" if py > pe else f"💔 Se fue en penales: {nom} cae {py}-{pe}"
    if yo > el:
        if yo - el >= 3: return elige(sem, [f"🔥 ¡Goleada de {nom}!", f"🔥 ¡{nom} dio cátedra! Ganó {yo}-{el}", f"🔥 ¡Bailó {nom}! Ganó {yo}-{el}"])
        if peor < 0: return elige(sem, [f"🔥 ¡{nom} lo remontó y ganó!", f"🔥 ¡Remontada completa! Ganó {nom}"])
        if yo - el == 1: return elige(sem, [f"😮‍💨 ¡Sufrido, pero ganó {nom}!", f"✅ Ganó {nom}. Con el corazón en la mano", f"✅ ¡Tres puntos para {nom}!"])
        return elige(sem, [f"✅ ¡Ganó {nom}!", f"✅ {nom} cumplió y ganó", f"✅ ¡Victoria de {nom}!"])
    if yo < el:
        if el - yo >= 3: return elige(sem, [f"📈 Goleada en contra. Tu Sufrómetro va a subir", f"🙈 Mejor ni preguntes: {nom} perdió {yo}-{el}", f"💀 Noche para olvidar: {nom} perdió {yo}-{el}"])
        if mejor > 0: return elige(sem, [f"💔 {nom} lo tenía y lo dejó ir", f"💔 Iba ganando… y perdió {nom}"])
        return elige(sem, [f"❌ Perdió {nom}", f"❌ Hoy no se pudo: perdió {nom}", f"❌ Derrota de {nom}. Ya vendrán tiempos mejores"])
    if yo == 0: return elige(sem, [f"😴 {nom} empató 0-0. Ni modo", f"😴 Cero a cero. {nom} no pudo", f"🥱 Empate sin goles de {nom}"])
    if mejor > 0: return elige(sem, [f"😩 {nom} lo tenía y se lo empataron", f"😩 Se escapó la victoria: empató {nom}"])
    if peor < 0: return elige(sem, [f"😮‍💨 ¡{nom} rescató el empate!", f"👊 {nom} no se rindió y empató"])
    return elige(sem, [f"🤝 Empató {nom}", f"🤝 Reparten puntos: empató {nom}"])

def titulo_final_us(nom, gy, gr, pre, sem):
    paliza = 21 if pre == "n" else 20
    if gy > gr:
        if gy - gr >= paliza: return elige(sem, [f"🔥 ¡Paliza de los {nom}!", f"🔥 ¡Los {nom} pasaron por encima!"])
        if gy - gr <= 3: return elige(sem, [f"😮‍💨 ¡Sufrido! Ganaron los {nom}", f"😮‍💨 ¡De infarto! Ganaron los {nom}"])
        return elige(sem, [f"✅ ¡Ganaron los {nom}!", f"✅ Victoria de los {nom}"])
    if gy < gr:
        if gr - gy >= paliza: return elige(sem, [f"🙈 Mejor ni preguntes: perdieron los {nom}", f"💀 Noche para olvidar de los {nom}"])
        if gr - gy <= 3: return elige(sem, [f"💔 Por poquito… perdieron los {nom}", f"💔 Se les fue por nada: perdieron los {nom}"])
        return elige(sem, [f"❌ Perdieron los {nom}", f"❌ Hoy no se pudo: perdieron los {nom}"])
    return f"🤝 Empataron los {nom}"


class Avisos:
    def __init__(self, db, enviar):
        self.db, self.enviar_fcm = db, enviar
        self.now = time.time()
        self.E = db.lee_estado()
        self.E.setdefault("env", {}); self.E.setdefault("mk", {}); self.E.setdefault("conoc", {})
        self.subs = db.suscriptores()      # uid → {tk:[…], p:{…}}
        self.nuevos = 0

    # ---------- envío ----------
    def manda(self, uid, cat, titulo, cuerpo, url="/", clave=None):
        S = self.subs.get(uid)
        if not S or not S.get("tk"): return
        if cat and not S.get("p", {}).get(cat, 1): return
        if clave:
            if clave in self.E["env"]: return
            self.E["env"][clave] = int(self.now)
        self.nuevos += 1
        print(f"→ {uid[:6]}… [{cat}] {titulo} · {cuerpo}")
        if PRUEBA: return
        malos = self.enviar_fcm(S["tk"], {"t": titulo, "b": cuerpo, "u": url, "g": (clave or "")[:60]})
        if malos:
            S["tk"] = [t for t in S["tk"] if t not in malos]
            self.db.quita_tokens(uid, malos)

    def bienvenida(self):
        for uid, S in self.subs.items():
            for t in S.get("tk", []):
                h = hashlib.sha1(t.encode()).hexdigest()[:12]
                if h in self.E["conoc"]: continue
                self.E["conoc"][h] = int(self.now)
                print(f"→ {uid[:6]}… bienvenida")
                if not PRUEBA:
                    malos = self.enviar_fcm([t], {"t": "¡Listo! Avisos activados", "b": "Así te van a llegar los avisos de La Pizarra: goles de tus equipos, retos y lo que dicen tus amigos.", "u": "/?av=1", "g": "bienvenida"})
                    if malos: S["tk"] = [x for x in S["tk"] if x not in malos]; self.db.quita_tokens(uid, malos)

    # ---------- amigos y retos ----------
    def social(self):
        desde = self.E.get("soc_t") or (self.now - 15 * 60)
        hasta = self.now
        for a in self.db.nuevos("amistades", "t", desde):
            u, de, n = a.get("u") or [], a.get("de"), a.get("n") or {}
            otro = next((x for x in u if x != de), None)
            if not otro: continue
            if a.get("est") == "pend":
                N = n.get(de) or "Alguien"
                t, b = elige(a["_id"], [("👋 Nueva solicitud", f"{N} quiere ser tu amigo en La Pizarra"),
                                        ("👋 ¿Lo dejas entrar a tu banca?", f"{N} te mandó solicitud de amistad"),
                                        ("👋 Alguien te quiere en su grupo", f"{N} quiere ser tu amigo. Ya tendrás a quién retar")])
                self.manda(otro, "soc", t, b, "/?av=1", f"am-{a['_id']}")
            elif a.get("est") == "ok":
                N = n.get(otro) or "Tu amigo"
                t, b = elige(a["_id"], [("🤝 Ya son amigos", f"{N} aceptó tu solicitud. Ya pueden retarse"),
                                        ("🤝 Solicitud aceptada", f"{N} ya está en tu banca. Que empiece la rivalidad")])
                self.manda(de, "soc", t, b, "/#amigos", f"amok-{a['_id']}")
        for d in self.db.nuevos("duelos", "t", desde):
            if d.get("est") != "pend": continue
            de, n = d.get("de"), d.get("n") or {}
            otro = next((x for x in d.get("u") or [] if x != de), None)
            if otro:
                N, T, e = n.get(de) or "Un amigo", DU_T.get(d.get("tipo"), "duelo"), d.get("e") or ""
                t, b = elige(d["_id"], [(f"⚔️ {N} te retó", f"{T}{' · ' + e if e else ''}. ¿Aceptas o le sacas?"),
                                        (f"⚔️ {N} te está buscando", f"Te retó a un duelo de {T}{' · ' + e if e else ''}. No te rajes"),
                                        (f"⚔️ Te tiraron el guante", f"{N} te retó: {T}{' · ' + e if e else ''}")])
                self.manda(otro, "ret", t, b, "/?av=1", f"du-{d['_id']}")
        # comentarios: posts de las últimas 2 semanas cuyo contador de comentarios subió
        nc = self.E.setdefault("nc", {})
        vivos = set()
        for p in self.db.nuevos("posts", "t", self.now - 14 * 86400):
            pid, c = p["_id"], int(p.get("nc") or 0); vivos.add(pid)
            antes = nc.get(pid)
            nc[pid] = c
            if antes is None or c <= antes or p.get("uid") not in self.subs: continue
            for cm in self.db.comentarios(pid, min(5, c - antes)):
                if cm.get("uid") == p.get("uid"): continue
                N = cm.get("n") or "Un amigo"
                t = elige(cm["_id"], [f"💬 {N} comentó tu post", f"💬 {N} te contestó", f"💬 {N} tiene algo que decir"])
                self.manda(p["uid"], "soc", t, f"“{corta(cm.get('tx'), 90)}”", "/#amigos", f"co-{pid}-{cm['_id']}")
        for k in list(nc):
            if k not in vivos: del nc[k]
        self.E["soc_t"] = hasta

    # ---------- recordatorios de cierre (29 oct 2026) ----------
    # Si algo cierra en la próxima hora y media y no has hecho tus picks, te avisa una vez. Solo a quien ya juega:
    # quiniela Liga MX (hizo picks la jornada anterior), Survivor (sigue vivo) y reto del día (contestó ayer: cuida su racha).
    def cierres(self):
        lo, hi = self.now, self.now + 90 * 60
        sha = lambda u: hashlib.sha256(u.encode()).hexdigest()[:12]
        lee = lambda n: json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", n), encoding="utf-8"))
        def falta(ts):
            m = max(5, int(round((ts - self.now) / 300.0)) * 5)
            return f"{m} min" if m < 60 else "una hora" if m <= 65 else f"{m // 60} h {m % 60} min"
        for jd in self.db.rango("qmx_jornadas", "primero", lo, hi):
            jid, sl, j, ts = jd["_id"], jd.get("s"), jd.get("j"), jd["_ts"]
            if not isinstance(j, int): continue
            prev = f"{sl}-{j - 1}"
            Q = self.db.donde("qmx_picks", "jid", "in", [jid, prev])
            jug = {d.get("uid") for d in Q if d.get("jid") == prev}
            hechos = {d.get("uid") for d in Q if d.get("jid") == jid and (d.get("p") or {})}
            for uid in (jug - hechos) & set(self.subs):
                t = elige(f"{jid}{uid}", [f"⏰ La jornada {j} cierra en {falta(ts)}", f"⏰ ¡Ojo! Quedan {falta(ts)} para tus picks", f"⏰ Se te va la jornada {j}"])
                self.manda(uid, "cie", t, "Todavía no haces tus picks de la Quiniela Liga MX.", "/#quinielamx", f"cie-q-{jid}-{uid[:8]}")
            S = self.db.donde("smx_picks", "jid", "in", [jid, prev])
            try: TS = lee("smx_tabla.json"); TS = TS.get("t") if TS.get("s") == sl else {}
            except Exception: TS = {}
            jug = {d.get("uid") for d in S if d.get("jid") == prev}
            hechos = {d.get("uid") for d in S if d.get("jid") == jid}
            for uid in (jug - hechos) & set(self.subs):
                if (TS.get(sha(uid)) or {}).get("c") is not None: continue   # ya está fuera
                self.manda(uid, "cie", "🛡️ Te puedes quedar fuera del Survivor", f"La jornada {j} cierra en {falta(ts)} y no has escogido equipo. Si no escoges, quedas eliminado.", "/#quinielamx", f"cie-s-{jid}-{uid[:8]}")
        for rd in self.db.rango("retos_dia", "cierre", lo, hi):
            f, ts = rd["_id"], rd["_ts"]
            ayer = (datetime.fromisoformat(f) - timedelta(days=1)).date().isoformat()
            R = self.db.donde("rd_resp", "f", "in", [ayer, f])
            jug = {d.get("uid") for d in R if d.get("f") == ayer}
            hechos = {d.get("uid") for d in R if d.get("f") == f}
            try: RT = lee("rd_tabla.json").get("t") or {}
            except Exception: RT = {}
            try:
                x = (lee("reto_dia.json").get("d") or {}).get(f) or {}
                q = f"Hoy: {x.get('hn') or x.get('h')} vs {x.get('an') or x.get('a')}. Contesta antes de que empiece." if (x.get("hn") or x.get("h")) else ""
            except Exception: q = ""
            for uid in (jug - hechos) & set(self.subs):
                r = int((RT.get(sha(uid)) or {}).get("r") or 0)   # racha de aciertos según la última tabla
                t = f"🔥 Cuida tu racha de {r}: el reto cierra en {falta(ts)}" if r >= 2 else f"⏰ El reto del día cierra en {falta(ts)}"
                self.manda(uid, "cie", t, corta(q, 110) or "Contesta antes de que empiece el partido.", "/#hoy", f"cie-rd-{f}-{uid[:8]}")

    # ---------- partidos ----------
    def favoritos(self):
        """F: {"f2286": {uid: "Pumas"}, "nKC": {...}} de quienes quieren avisos de partidos o goles.
        RV: {"f2287": {uid: "Pumas"}} rivales de toda la vida de sus equipos (para el sufrimiento ajeno)."""
        F, RV = {}, {}
        for uid, S in self.subs.items():
            p = S.get("p", {})
            for k, x in (self.db.favoritos(uid) or {}).items():
                if k[:1] not in "fnb": continue
                nom = (x or {}).get("n") or k[1:]
                if p.get("eq", 1) or p.get("gol", 1): F.setdefault(k, {})[uid] = nom
                if p.get("riv", 1):
                    for r in RIVALES.get(k, ()): RV.setdefault(r, {})[uid] = nom
        for r in list(RV):   # si también le va a ese equipo, no es su rival
            for uid in list(RV[r]):
                if uid in F.get(r, {}): del RV[r][uid]
        self.RV = RV
        return F

    def futbol(self, F, vivo_check):
        RV = getattr(self, "RV", {})
        ids = {int(k[1:]) for k in list(F) + list(RV) if k[0] == "f" and k[1:].isdigit()}
        if not ids or not AFK: return False
        hoy = datetime.now(MX).date().isoformat()
        dia = self.E.get("dia") or {}
        hid = hashlib.sha1(",".join(map(str, sorted(ids))).encode()).hexdigest()[:10]   # si cambian los favoritos, se vuelve a pedir
        if dia.get("f") != hoy or dia.get("ids") != hid or self.now - dia.get("t", 0) > 3 * 3600:
            L = af("fixtures", date=hoy, timezone="America/Mexico_City")
            if L or dia.get("f") != hoy:
                viejos = [x for x in dia.get("fx", []) if x["ts"] > self.now - 4 * 3600 and x.get("f") != hoy]
                fx = [{"id": x["fixture"]["id"], "ts": x["fixture"]["timestamp"], "h": x["teams"]["home"]["id"], "a": x["teams"]["away"]["id"],
                       "hn": x["teams"]["home"]["name"], "an": x["teams"]["away"]["name"], "lg": x["league"]["name"], "f": hoy} for x in L
                      if x["teams"]["home"]["id"] in ids or x["teams"]["away"]["id"] in ids]
                dia = {"f": hoy, "ids": hid, "t": int(self.now), "fx": viejos + fx}
                self.E["dia"] = dia
        mios = [x for x in dia.get("fx", []) if x["h"] in ids or x["a"] in ids]
        # empieza en un rato
        for x in mios:
            falta = x["ts"] - self.now
            if 0 < falta <= 35 * 60:
                for lado in ("h", "a"):
                    for uid, nom in F.get(f"f{x[lado]}", {}).items():
                        rid = x["a"] if lado == "h" else x["h"]
                        riv = nombre(rid, x["an"] if lado == "h" else x["hn"])
                        clasico = rid in {int(r[1:]) for r in RIVALES.get(f"f{x[lado]}", ())}
                        t = (elige(x["id"], [f"🔥 ¡Hoy es clásico! {nom} vs {riv}", f"🔥 Se juega el clásico: {nom} vs {riv}", f"🔥 Partido de rivalidad: {nom} vs {riv}"]) if clasico
                             else elige(f"{x['id']}{uid}", [f"⏰ En media hora juega {nom}", f"🍿 Prepara la botana: juega {nom}", f"⏰ Ya casi: {nom} sale a la cancha", f"📺 Prende la tele: juega {nom}"]))
                        self.manda(uid, "eq", t, f"{nom} {'vs' if lado == 'h' else 'en casa de'} {riv} · {hora(x['ts'])} · {x['lg']}", "/#favs", f"pre-f{x['id']}-{uid[:8]}")
        # en juego: marcador y final
        enj = [x for x in mios if x["ts"] - 10 * 60 < self.now < x["ts"] + 3.5 * 3600 and f"fin-f{x['id']}" not in self.E["env"]]
        if not enj or not vivo_check: return bool(enj)
        R = af("fixtures", ids="-".join(str(x["id"]) for x in enj[:20]))
        hay = False
        for r in R:
            fid, st = r["fixture"]["id"], r["fixture"]["status"]["short"]
            H, A, gh, ga = r["teams"]["home"], r["teams"]["away"], r["goals"]["home"], r["goals"]["away"]
            if st in AF_NO: self.E["env"][f"fin-f{fid}"] = int(self.now); continue
            if st == "NS": hay = True; continue
            gh, ga = int(gh or 0), int(ga or 0)
            visto = f"f{fid}" in self.E["mk"]
            mk = (self.E["mk"].get(f"f{fid}") or [0, 0, 0, 0]) + [0, 0]
            dmin, dmax = min(mk[2], gh - ga), max(mk[3], gh - ga)   # peor y mejor diferencia para el local en todo el partido
            m = r["fixture"]["status"].get("elapsed")
            if [gh, ga] != mk[:2] and (gh + ga) > mk[0] + mk[1]:
                goles = [e for e in r.get("events") or [] if e.get("type") == "Goal" and e.get("detail") != "Missed Penalty"]
                ult = goles[-1] if goles else None
                quien = (H if ult["team"]["id"] == H["id"] else A) if ult else (H if gh > mk[0] else A)
                autogol = bool(ult and ult.get("detail") == "Own Goal")
                autor = f" · {ult['player']['name']}" + (" (autogol)" if autogol else "") if ult and (ult.get("player") or {}).get("name") else ""
                mins = f" ({m}')" if m else ""
                for lado, T in (("h", H), ("a", A)):
                    for uid, nom in F.get(f"f{T['id']}", {}).items():
                        yo, el = (gh, ga) if lado == "h" else (ga, gh)
                        antes = (mk[0] - mk[1]) if lado == "h" else (mk[1] - mk[0])
                        peor = dmin if lado == "h" else -dmax
                        riv = nombre((A if lado == "h" else H)["id"], (A if lado == "h" else H)["name"])
                        t = titulo_gol(quien["id"] == T["id"], nom, riv, yo, el, antes, peor, m, autogol, f"{fid}{gh}{ga}")
                        hn, an = (nom, riv) if lado == "h" else (riv, nom)
                        self.manda(uid, "gol", t, f"{hn} {gh}-{ga} {an}{mins}{autor}", "/#favs", f"gol-f{fid}-{gh}-{ga}-{uid[:8]}")
            self.E["mk"][f"f{fid}"] = [gh, ga, dmin, dmax]
            if st in AF_FIN:
                if not visto: self.E["env"][f"fin-f{fid}"] = int(self.now); self.E["mk"].pop(f"f{fid}", None); continue   # no lo vimos en juego: no se avisa tarde
                pen = (r.get("score") or {}).get("penalty") or {}
                ph, pa = pen.get("home"), pen.get("away")
                for lado, T, O in (("h", H, A), ("a", A, H)):
                    yo, el = (gh, ga) if lado == "h" else (ga, gh)
                    py, pe = (ph, pa) if lado == "h" else (pa, ph)
                    peor, mejor = (dmin, dmax) if lado == "h" else (-dmax, -dmin)
                    riv = nombre(O["id"], O["name"])
                    for uid, nom in F.get(f"f{T['id']}", {}).items():
                        t = titulo_final(nom, riv, yo, el, peor, mejor, py, pe, f"{fid}{uid}")
                        hn, an = (nom, riv) if lado == "h" else (riv, nom)
                        self.manda(uid, "eq", t, f"{hn} {gh}-{ga} {an}" + (f" ({ph}-{pa} en penales)" if st == "PEN" and ph is not None else ""), "/#favs", f"fin-f{fid}-{uid[:8]}")
                    # sufrimiento ajeno: perdió el rival de toda la vida de tu equipo
                    if yo < el or (st == "PEN" and py is not None and pe is not None and py < pe):
                        for uid, mio in RV.get(f"f{T['id']}", {}).items():
                            if uid in F.get(f"f{O['id']}", {}): continue   # ya le llegó el final de su propio partido
                            yon = nombre_art(T["id"], T["name"])
                            t = elige(f"{fid}{uid}", [f"😏 Perdió {yon}", f"😏 Sufrimiento ajeno: perdió {yon}", f"😏 ¿Ya viste? Perdió {yon}", f"🍿 Perdió {yon}. Disfrútalo"])
                            b = elige(f"{fid}{uid}b", ["Hoy duermes tranquilo.", f"La afición de {mio} lo agradece.", "Mándale captura a tu amigo que le va.", "No es lo mismo que ganar, pero se le parece."])
                            self.manda(uid, "riv", t, f"{nombre(H['id'], H['name'])} {gh}-{ga} {nombre(A['id'], A['name'])}. {b}", "/#favs", f"riv-f{fid}-{uid[:8]}")
                self.E["env"][f"fin-f{fid}"] = int(self.now)
                self.E["mk"].pop(f"f{fid}", None)
            else:
                hay = True
        return hay

    def espn(self, F, liga, pre, ruta, mapa):
        RV = {k: v for k, v in getattr(self, "RV", {}).items() if k[0] == pre}
        keys = {k[1:] for k in list(F) + list(RV) if k[0] == pre}
        if not keys: return False
        try: j = get_json(f"{ESPN}/{ruta}/scoreboard")
        except Exception as e: print("ESPN", liga, e); return False
        hay = False
        for ev in j.get("events") or []:
            C = (ev.get("competitions") or [{}])[0]; cs = C.get("competitors") or []
            st = (C.get("status") or ev.get("status") or {}).get("type", {}).get("state")
            ab = lambda c: mapa.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
            ts = datetime.fromisoformat(ev["date"].replace("Z", "+00:00")).timestamp()
            for c in cs:
                k = ab(c)
                if k not in keys: continue
                o = next((x for x in cs if x is not c), None)
                if not o: continue
                visto = f"{pre}{ev['id']}" in self.E.get("vis", {})
                gy, gr = int(float(c.get("score") or 0)), int(float(o.get("score") or 0))
                riv = o["team"].get("shortDisplayName") or o["team"].get("displayName") or ab(o)
                for uid, nom in F.get(pre + k, {}).items():
                    if st == "pre" and 0 < ts - self.now <= 35 * 60:
                        clasico = pre + ab(o) in RIVALES.get(pre + k, ())
                        t = (f"🔥 Partido de rivalidad: {nom} vs {riv}" if clasico else
                             elige(f"{ev['id']}{uid}", [f"⏰ En media hora juegan los {nom}", f"🍿 Prepara la botana: juegan los {nom}", f"📺 Prende la tele: juegan los {nom}"]))
                        self.manda(uid, "eq", t, f"{nom} {'vs' if c.get('homeAway') == 'home' else 'en casa de'} {riv} · {hora(ts)} · {liga}", "/#favs", f"pre-{pre}{ev['id']}-{uid[:8]}")
                    if st == "post" and visto:
                        self.manda(uid, "eq", titulo_final_us(nom, gy, gr, pre, f"{ev['id']}{uid}"), f"{nom} {gy}-{gr} {riv} · {liga}", "/#favs", f"fin-{pre}{ev['id']}-{uid[:8]}")
                if st == "post" and visto and gy < gr:   # sufrimiento ajeno
                    for uid, mio in RV.get(pre + k, {}).items():
                        if uid in F.get(pre + ab(o), {}): continue
                        yon = c["team"].get("shortDisplayName") or k
                        t = elige(f"{ev['id']}{uid}", [f"😏 Perdieron los {yon}", f"😏 Sufrimiento ajeno: perdieron los {yon}", f"🍿 ¿Ya viste? Perdieron los {yon}"])
                        self.manda(uid, "riv", t, f"{yon} {gy}-{gr} {riv} · {liga}. Hoy duermes tranquilo.", "/#favs", f"riv-{pre}{ev['id']}-{uid[:8]}")
                if st == "in" or (st == "pre" and 0 < ts - self.now <= 40 * 60): hay = True
                if st in ("pre", "in") and ts - self.now < 3600: self.E.setdefault("vis", {})[f"{pre}{ev['id']}"] = int(self.now)
        return hay

    def limpia(self):
        lim = self.now - 4 * 86400
        self.E["env"] = {k: v for k, v in self.E["env"].items() if v > lim}
        self.E["vis"] = {k: v for k, v in self.E.get("vis", {}).items() if v > self.now - 86400}
        self.E["conoc"] = {k: v for k, v in self.E["conoc"].items() if v > self.now - 120 * 86400}

    def corre(self):
        if not self.subs:
            print("Nadie ha activado los avisos todavía."); return
        print(f"{len(self.subs)} personas con avisos activados")
        self.bienvenida()
        try: self.social()
        except Exception as e: print("Amigos/retos:", e)
        try: self.cierres()
        except Exception as e: print("Cierres:", e)
        F = self.favoritos()
        inicio = time.time()
        while True:
            self.now = time.time()
            hay = False
            try: hay |= self.futbol(F, True)
            except Exception as e: print("Fútbol:", e)
            hay |= self.espn(F, "NFL", "n", "football/nfl", NFL_AB)
            hay |= self.espn(F, "NBA", "b", "basketball/nba", NBA_AB)
            self.limpia(); self.db.guarda_estado(self.E)
            if not hay or time.time() - inicio + CADA > DUR: break
            time.sleep(CADA)
        print(f"Avisos mandados: {self.nuevos} · llamadas a API-Football: {AF_N}")


# ---------- Firebase de verdad ----------
class DBFirebase:
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore
        firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SA"])))
        self.fs, self.c = firestore, firestore.client()
    def lee_estado(self):
        return self.c.document("sistema/avisos").get().to_dict() or {}
    def guarda_estado(self, E):
        self.c.document("sistema/avisos").set(E)
    def suscriptores(self):
        R = {}
        for d in self.c.collection("avisos_tk").stream():
            x = d.to_dict() or {}
            tk = [t for t in x.get("tk") or [] if isinstance(t, str) and t]
            if tk: R[d.id] = {"tk": tk, "p": x.get("p") or {}}
        return R
    def favoritos(self, uid):
        d = self.c.document(f"usuarios/{uid}").get().to_dict() or {}
        return (d.get("fav") or {}).get("eq") or {}
    def nuevos(self, col, campo, desde):
        dt = datetime.fromtimestamp(desde, timezone.utc)
        return [{"_id": d.id, **(d.to_dict() or {})} for d in self.c.collection(col).where(campo, ">", dt).stream()]
    def rango(self, col, campo, lo, hi):
        a, b = datetime.fromtimestamp(lo, timezone.utc), datetime.fromtimestamp(hi, timezone.utc)
        R = []
        for d in self.c.collection(col).where(campo, ">", a).where(campo, "<=", b).stream():
            x = d.to_dict() or {}; v = x.get(campo)
            R.append({"_id": d.id, "_ts": v.timestamp() if hasattr(v, "timestamp") else 0, **x})
        return R
    def donde(self, col, campo, op, valor):
        return [{"_id": d.id, **(d.to_dict() or {})} for d in self.c.collection(col).where(campo, op, valor).stream()]
    def comentarios(self, pid, n):
        q = self.c.collection(f"posts/{pid}/com").order_by("ts", direction=self.fs.Query.DESCENDING).limit(n)
        return [{"_id": d.id, **(d.to_dict() or {})} for d in q.stream()]
    def quita_tokens(self, uid, malos):
        self.c.document(f"avisos_tk/{uid}").update({"tk": self.fs.ArrayRemove(list(malos))})

def enviar_fcm(tokens, data):
    """Manda el aviso a cada aparato. Regresa las claves que ya no sirven (app borrada, permiso quitado) para limpiarlas."""
    from firebase_admin import messaging
    M = [messaging.Message(token=t, data={k: str(v) for k, v in data.items()},
                           webpush=messaging.WebpushConfig(headers={"Urgency": "high", "TTL": "21600"})) for t in tokens]
    malos = []
    try:
        r = messaging.send_each(M)
        for t, x in zip(tokens, r.responses):
            if not x.success:
                print("  FCM:", type(x.exception).__name__, str(x.exception)[:120])
                if isinstance(x.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError)) or "not a valid FCM registration token" in str(x.exception):
                    malos.append(t)
    except Exception as e:
        print("FCM:", e)
    return malos


if __name__ == "__main__":
    if not os.environ.get("FIREBASE_SA", "").strip():
        print("No hay FIREBASE_SA; no se mandan avisos"); raise SystemExit(0)
    Avisos(DBFirebase(), enviar_fcm).corre()
