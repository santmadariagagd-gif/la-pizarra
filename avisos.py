"""
La Pizarra · Avisos al teléfono (29 oct 2026)

Corre cada 10 minutos en GitHub (.github/workflows/avisos.yml). Lee quién activó los avisos (avisos_tk/{uid}),
sus equipos favoritos (usuarios/{uid}.fav) y lo nuevo en Firebase, y manda notificaciones con Firebase Cloud Messaging:

  · Partidos de tus equipos (p.eq): "en un rato juega…" y el resultado final. Fútbol (API-Football), NFL y NBA (marcadores públicos de ESPN).
  · Goles (p.gol): cada gol de un partido de tus equipos de fútbol.
  · Amigos (p.soc): solicitudes de amistad, solicitudes aceptadas y comentarios en tus posts.
  · Retos (p.ret): cuando un amigo te reta a un duelo.

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
                self.manda(otro, "soc", "Solicitud de amistad", f"{n.get(de) or 'Alguien'} quiere ser tu amigo en La Pizarra", "/?av=1", f"am-{a['_id']}")
            elif a.get("est") == "ok":
                self.manda(de, "soc", "Ya son amigos", f"{n.get(otro) or 'Tu amigo'} aceptó tu solicitud", "/#amigos", f"amok-{a['_id']}")
        for d in self.db.nuevos("duelos", "t", desde):
            if d.get("est") != "pend": continue
            de, n = d.get("de"), d.get("n") or {}
            otro = next((x for x in d.get("u") or [] if x != de), None)
            if otro:
                self.manda(otro, "ret", "Te retaron a un duelo ⚔️", f"{n.get(de) or 'Un amigo'} te retó: {DU_T.get(d.get('tipo'), 'duelo')} · {d.get('e') or ''}".strip(" ·"), "/?av=1", f"du-{d['_id']}")
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
                self.manda(p["uid"], "soc", f"{cm.get('n') or 'Un amigo'} comentó tu post", f"“{corta(cm.get('tx'), 90)}”", "/#amigos", f"co-{pid}-{cm['_id']}")
        for k in list(nc):
            if k not in vivos: del nc[k]
        self.E["soc_t"] = hasta

    # ---------- partidos ----------
    def favoritos(self):
        """{"f2283": {uid: "Pumas"}, "nKC": {...}, "bNYK": {...}} de quienes quieren avisos de partidos o goles"""
        F = {}
        for uid, S in self.subs.items():
            p = S.get("p", {})
            if not (p.get("eq", 1) or p.get("gol", 1)): continue
            for k, x in (self.db.favoritos(uid) or {}).items():
                if k[:1] in "fnb": F.setdefault(k, {})[uid] = (x or {}).get("n") or k[1:]
        return F

    def futbol(self, F, vivo_check):
        ids = {int(k[1:]) for k in F if k[0] == "f" and k[1:].isdigit()}
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
                        riv = x["an"] if lado == "h" else x["hn"]
                        self.manda(uid, "eq", f"En un rato juega {nom}", f"{nom} {'vs' if lado == 'h' else 'en casa de'} {riv} · {hora(x['ts'])} · {x['lg']}", "/#favs", f"pre-f{x['id']}-{uid[:8]}")
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
            mk = self.E["mk"].get(f"f{fid}") or [0, 0]
            m = r["fixture"]["status"].get("elapsed")
            if [gh, ga] != mk and (gh + ga) > sum(mk):
                goles = [e for e in r.get("events") or [] if e.get("type") == "Goal" and e.get("detail") != "Missed Penalty"]
                ult = goles[-1] if goles else None
                quien = None
                if ult: quien = H if ult["team"]["id"] == H["id"] else A
                elif gh > mk[0]: quien = H
                else: quien = A
                autor = f" · {ult['player']['name']}" + (" (autogol)" if ult and ult.get("detail") == "Own Goal" else "") if ult and ult.get("player", {}).get("name") else ""
                mins = f" ({m}')" if m else ""
                for lado, T in (("h", H), ("a", A)):
                    for uid, nom in F.get(f"f{T['id']}", {}).items():
                        nuestro = quien["id"] == T["id"]
                        tit = f"⚽ ¡GOL DE {nom.upper()}!" if nuestro else f"Gol de {quien['name']} 😬"
                        hn, an = (nom, A["name"]) if lado == "h" else (H["name"], nom)
                        self.manda(uid, "gol", tit, f"{hn} {gh}-{ga} {an}{mins}{autor}", "/#favs", f"gol-f{fid}-{gh}-{ga}-{uid[:8]}")
            self.E["mk"][f"f{fid}"] = [gh, ga]
            if st in AF_FIN:
                if not visto: self.E["env"][f"fin-f{fid}"] = int(self.now); self.E["mk"].pop(f"f{fid}", None); continue   # no lo vimos en juego: no se avisa tarde
                for lado, T, gy, gr, R2 in (("h", H, gh, ga, A), ("a", A, ga, gh, H)):
                    for uid, nom in F.get(f"f{T['id']}", {}).items():
                        v = "ganó" if gy > gr else "perdió" if gy < gr else "empató"
                        hn, an = (nom, A["name"]) if lado == "h" else (H["name"], nom)
                        self.manda(uid, "eq", f"Final: {nom} {v}", f"{hn} {gh}-{ga} {an}", "/#favs", f"fin-f{fid}-{uid[:8]}")
                self.E["env"][f"fin-f{fid}"] = int(self.now)
                self.E["mk"].pop(f"f{fid}", None)
            else:
                hay = True
        return hay

    def espn(self, F, liga, pre, ruta, mapa):
        keys = {k[1:] for k in F if k[0] == pre}
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
                for uid, nom in F.get(pre + k, {}).items():
                    riv = o["team"].get("shortDisplayName") or o["team"].get("displayName") or ab(o)
                    if st == "pre" and 0 < ts - self.now <= 35 * 60:
                        self.manda(uid, "eq", f"En un rato juegan los {nom}", f"{nom} {'vs' if c.get('homeAway') == 'home' else 'en casa de'} {riv} · {hora(ts)} · {liga}", "/#favs", f"pre-{pre}{ev['id']}-{uid[:8]}")
                    if st == "post" and f"{pre}{ev['id']}" in self.E.get("vis", {}):
                        gy, gr = int(float(c.get("score") or 0)), int(float(o.get("score") or 0))
                        v = "ganaron" if gy > gr else "perdieron" if gy < gr else "empataron"
                        self.manda(uid, "eq", f"Final: los {nom} {v}", f"{nom} {gy}-{gr} {riv} · {liga}", "/#favs", f"fin-{pre}{ev['id']}-{uid[:8]}")
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
