# -*- coding: utf-8 -*-
"""
El periódico semanal de cada liga de fantasy (La Pizarra).
Lo corre GitHub cada martes temprano (.github/workflows/periodico.yml), después del Monday Night.

1. Lee la lista de ligas de periodico.json (por ahora se agregan a mano; "hasta" = fecha en que se acaba la prueba o el pago).
2. Baja de Sleeper (API documentada) matchups de todas las semanas, rosters, usuarios y movimientos.
3. CALCULA todo lo que es dato (marcadores, tabla, rachas, récords, puntos dejados en la banca, premios, cuadro de honor,
   castigados, previa con proyecciones). Las proyecciones son las de FantasyPros que build_site.py guarda cada día en
   Firebase (proyecciones/{temporada}-{semana}).
4. Le pasa esos datos a la API de Claude (secreto ANTHROPIC_API_KEY) para que escriba los textos con humor en español.
   La IA solo escribe: no puede cambiar números (el HTML usa los números calculados aquí, no los de la IA).
5. Publica docs/periodico/{liga}/{temporada}-{semana}.html, index.html (la última) y ultimo.json (para el link en Mi liga).

Variables: ANTHROPIC_API_KEY, FIREBASE_SA, SEMANA (opcional: forzar semana), SOLO_LIGA (opcional), SIN_IA=1 (prueba sin gastar).
"""
import json, os, re, sys, html, unicodedata, urllib.request, urllib.error
from datetime import datetime, timezone, date

AQUI = os.path.dirname(os.path.abspath(__file__))
SLEEPER = "https://api.sleeper.app/v1"
MODELO = "claude-sonnet-5-5"
PRECIO_IN, PRECIO_OUT = 2.0, 10.0          # USD por millón de tokens (Sonnet 5.5, sep 2026)
TFIX = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX"}  # Sleeper → nflverse (como en las proyecciones)
FLEX = {"FLEX": ["RB", "WR", "TE"], "WRRB_FLEX": ["WR", "RB"], "REC_FLEX": ["WR", "TE"],
        "SUPER_FLEX": ["QB", "RB", "WR", "TE"], "IDP_FLEX": ["DL", "LB", "DB"]}
NO_TITULAR = {"BN", "IR", "TAXI"}
esc = lambda s: html.escape(str(s if s is not None else ""))
r1 = lambda v: None if v is None else round(float(v) + 1e-9, 1)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "LaPizarra/1.0 (+https://lapizarra.mx)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b\.?", "", s)
    return re.sub(r"[^a-z]", "", s)


# ---------------------------------------------------------------- Firebase (proyecciones)
_db = None
def db():
    global _db
    if _db is not None: return _db or None
    sa = os.environ.get("FIREBASE_SA", "").strip()
    if not sa:
        print("Periódico: sin FIREBASE_SA, no hay proyecciones"); _db = False; return None
    import firebase_admin
    from firebase_admin import credentials, firestore
    if not firebase_admin._apps: firebase_admin.initialize_app(credentials.Certificate(json.loads(sa)))
    _db = firestore.client(); return _db

def proyecciones(season, w):
    d = db()
    if not d: return {}
    s = d.collection("proyecciones").document(f"{season}-{w}").get()
    return (s.to_dict() or {}).get("p", {}) if s.exists else {}


# ---------------------------------------------------------------- Semana a reportar
def semana_terminada(season):
    """Última semana de temporada regular con todos sus partidos terminados (nflverse)."""
    import nflreadpy as nfl
    s = nfl.load_schedules([season]).to_pandas()
    s = s[s.game_type == "REG"]
    done = [int(w) for w, g in s.groupby("week") if g.result.notna().all()]
    return max(done) if done else None


# ---------------------------------------------------------------- Datos de la liga (Sleeper)
class Liga:
    def __init__(self, lid, season, w, P):
        self.lid, self.season, self.w, self.P = lid, season, w, P
        self.league = get(f"{SLEEPER}/league/{lid}")
        self.users = {u["user_id"]: u for u in get(f"{SLEEPER}/league/{lid}/users")}
        self.rosters = {r["roster_id"]: r for r in get(f"{SLEEPER}/league/{lid}/rosters")}
        self.slots = [s for s in self.league.get("roster_positions", []) if s not in NO_TITULAR]
        self.mu = {}
        for k in range(1, w + 2):
            try: self.mu[k] = get(f"{SLEEPER}/league/{lid}/matchups/{k}") or []
            except Exception: self.mu[k] = []
        self.tx = []
        try: self.tx = [t for t in get(f"{SLEEPER}/league/{lid}/transactions/{w}") or [] if t.get("status") == "complete"]
        except Exception: pass

    def equipo(self, rid):
        r = self.rosters.get(rid) or {}
        u = self.users.get(r.get("owner_id")) or {}
        return (u.get("metadata") or {}).get("team_name") or u.get("display_name") or f"Equipo {rid}"

    def manager(self, rid):
        u = self.users.get((self.rosters.get(rid) or {}).get("owner_id")) or {}
        return u.get("display_name") or ""

    def jugador(self, pid):
        if pid in (None, "0", ""): return None
        if re.fullmatch(r"[A-Z]{2,3}", str(pid)):
            t = TFIX.get(pid, pid); return dict(id=pid, n=f"{t} D/ST", pos="DEF", tm=t, eleg=["DEF"], key=f"DEF:{t}")
        p = self.P.get(str(pid)) or {}
        tm = TFIX.get(p.get("team") or "", p.get("team") or "")
        n = p.get("full_name") or (f"{p.get('first_name','')} {p.get('last_name','')}".strip()) or f"Jugador {pid}"
        pos = p.get("position") or "?"
        return dict(id=str(pid), n=n, pos=pos, tm=tm, eleg=p.get("fantasy_positions") or [pos],
                    key=p.get("gsis_id") or f"n|{norm(n)}|{tm}", gsis=p.get("gsis_id"))


def mejor_alineacion(L, jug, pts):
    """Puntos de la mejor alineación posible con los jugadores del roster (para 'dejaste X en la banca')."""
    usados, total = set(), 0.0
    orden = sorted(range(len(L.slots)), key=lambda i: len(FLEX.get(L.slots[i], [L.slots[i]])))
    for i in orden:
        el = FLEX.get(L.slots[i], [L.slots[i]])
        c = [j for j in jug if j and j["id"] not in usados and any(e in el for e in j["eleg"])]
        if not c: continue
        b = max(c, key=lambda j: pts.get(j["id"], 0) or 0); usados.add(b["id"]); total += pts.get(b["id"], 0) or 0
    return total


def calcular(L, PROJ, PROJ_SIG):
    w, out = L.w, {}
    filas = L.mu.get(w) or []
    por_mid = {}
    for f in filas:
        if f.get("matchup_id") is not None: por_mid.setdefault(f["matchup_id"], []).append(f)
    # --- historial W/L por semana (rachas, tabla anterior, récords)
    hist = {}
    for k in range(1, w + 1):
        g = {}
        for f in L.mu.get(k) or []:
            if f.get("matchup_id") is not None: g.setdefault(f["matchup_id"], []).append(f)
        for par in g.values():
            if len(par) != 2: continue
            a, b = par; pa, pb = a.get("points") or 0, b.get("points") or 0
            for x, y, px, py in ((a, b, pa, pb), (b, a, pb, pa)):
                hist.setdefault(x["roster_id"], []).append(dict(w=k, pts=px, opp=y["roster_id"], opp_pts=py,
                                                              res="W" if px > py else "L" if px < py else "T"))
    def racha(rid, hasta):
        h = [x for x in hist.get(rid, []) if x["w"] <= hasta]
        if not h: return 0
        last, n = h[-1]["res"], 0
        for x in reversed(h):
            if x["res"] != last: break
            n += 1
        return n if last == "W" else -n if last == "L" else 0
    def tabla(hasta):
        T = []
        for rid in L.rosters:
            h = [x for x in hist.get(rid, []) if x["w"] <= hasta]
            T.append(dict(rid=rid, eq=L.equipo(rid), g=sum(x["res"] == "W" for x in h), p=sum(x["res"] == "L" for x in h),
                          e=sum(x["res"] == "T" for x in h), pf=round(sum(x["pts"] for x in h), 2), pc=round(sum(x["opp_pts"] for x in h), 2)))
        T.sort(key=lambda t: (-t["g"], -t["pf"]))
        return T
    T, T0 = tabla(w), tabla(w - 1)
    pos0 = {t["rid"]: i for i, t in enumerate(T0)}
    for i, t in enumerate(T):
        t["lugar"] = i + 1; t["mov"] = (pos0.get(t["rid"], i) - i) if w > 1 else 0
        t["racha"] = racha(t["rid"], w); t["sem"] = next((x["pts"] for x in hist.get(t["rid"], []) if x["w"] == w), 0)
    out["tabla"] = T
    # --- jugadores de la semana
    titulares, banca, por_equipo = [], [], {}
    for f in filas:
        rid, pp = f["roster_id"], f.get("players_points") or {}
        st = [s for s in (f.get("starters") or [])]
        jug = [L.jugador(p) for p in (f.get("players") or [])]
        jug = [j for j in jug if j]
        stset = set(s for s in st if s not in (None, "0"))
        for j in jug:
            pr = PROJ.get(j["key"]); x = dict(j, pts=r1(pp.get(j["id"], 0)), proj=r1(pr), eq=L.equipo(rid), rid=rid)
            (titulares if j["id"] in stset else banca).append(x)
        opt = mejor_alineacion(L, jug, pp)
        por_equipo[rid] = dict(pts=f.get("points") or 0, opt=round(opt, 2), banca=round(max(0, opt - (f.get("points") or 0)), 1),
                               vacios=sum(1 for s in st if s in (None, "0")))
    # mejor cambio que no se hizo (jugador de la banca que habría entrado por un titular)
    for rid, E in por_equipo.items():
        best = None
        for b in [x for x in banca if x["rid"] == rid]:
            for s in [x for x in titulares if x["rid"] == rid]:
                if not any(e in s["eleg"] for e in b["eleg"]) and not (s["pos"] in b["eleg"]): continue
                d = (b["pts"] or 0) - (s["pts"] or 0)
                if d > 0 and (best is None or d > best["dif"]): best = dict(banca=b["n"], banca_pts=b["pts"], titular=s["n"], titular_pts=s["pts"], dif=r1(d))
        E["cambio"] = best
    # --- matchups de la semana
    M = []
    for mid, par in por_mid.items():
        if len(par) != 2: continue
        a, b = sorted(par, key=lambda x: -(x.get("points") or 0))
        pa, pb = a.get("points") or 0, b.get("points") or 0
        def top(rid, n=3, rev=True):
            L2 = [x for x in titulares if x["rid"] == rid]
            return [dict(n=x["n"], pos=x["pos"], pts=x["pts"], proj=x["proj"]) for x in sorted(L2, key=lambda x: (x["pts"] or 0), reverse=rev)[:n]]
        rec = lambda rid: next(f"{t['g']}-{t['p']}" + (f"-{t['e']}" if t["e"] else "") for t in T if t["rid"] == rid)
        M.append(dict(id=mid, ganador=L.equipo(a["roster_id"]), perdedor=L.equipo(b["roster_id"]),
                      ganador_manager=L.manager(a["roster_id"]), perdedor_manager=L.manager(b["roster_id"]),
                      g_pts=r1(pa), p_pts=r1(pb), margen=r1(pa - pb), empate=pa == pb,
                      g_record=rec(a["roster_id"]), p_record=rec(b["roster_id"]),
                      g_mejores=top(a["roster_id"]), p_mejores=top(b["roster_id"]),
                      g_peores=top(a["roster_id"], 2, False), p_peores=top(b["roster_id"], 2, False),
                      g_banca=por_equipo[a["roster_id"]]["banca"], p_banca=por_equipo[b["roster_id"]]["banca"],
                      g_cambio=por_equipo[a["roster_id"]]["cambio"], p_cambio=por_equipo[b["roster_id"]]["cambio"],
                      g_racha=racha(a["roster_id"], w), p_racha=racha(b["roster_id"], w)))
    M.sort(key=lambda m: -m["margen"])
    out["matchups"] = M
    if not M: return out
    # --- números de la semana
    out["alta"] = max(M, key=lambda m: m["g_pts"]); out["baja"] = min(M, key=lambda m: m["p_pts"])
    out["cerrado"] = min(M, key=lambda m: m["margen"]); out["paliza"] = max(M, key=lambda m: m["margen"])
    out["promedio"] = r1(sum(m["g_pts"] + m["p_pts"] for m in M) / (2 * len(M)))
    tit = [x for x in titulares if x["pts"] is not None]
    hab = [x for x in tit if x["pos"] not in ("K", "DEF")]          # cuadro de honor y castigados: solo jugadores de posición
    out["honor"] = [dict(n=x["n"], pos=x["pos"], eq=x["eq"], pts=x["pts"], proj=x["proj"]) for x in sorted(hab, key=lambda x: -x["pts"])[:5]]
    conp = [x for x in hab if x["proj"] is not None and x["proj"] >= 8]
    out["castigados"] = [dict(n=x["n"], pos=x["pos"], eq=x["eq"], pts=x["pts"], proj=x["proj"], dif=r1(x["pts"] - x["proj"]))
                         for x in sorted(conp, key=lambda x: x["pts"] - x["proj"])[:5]] if conp else []
    noKD = [x for x in tit if x["pos"] not in ("K", "DEF")]
    sn = min(noKD, key=lambda x: x["pts"]) if noKD else None
    ban = [x for x in banca if x["pts"] is not None]
    fo = max(ban, key=lambda x: x["pts"]) if ban else None
    bu = max(M, key=lambda m: m["p_pts"])
    out["premios"] = dict(
        snell=dict(n=sn["n"], pos=sn["pos"], eq=sn["eq"], pts=sn["pts"], proj=sn["proj"]) if sn else None,
        pitts=out["castigados"][0] if out["castigados"] else None,
        foles=dict(n=fo["n"], pos=fo["pos"], eq=fo["eq"], pts=fo["pts"]) if fo else None,
        burrow=dict(eq=bu["perdedor"], pts=bu["p_pts"], margen=bu["margen"]))
    obit = sorted(conp, key=lambda x: x["pts"])[:3] if conp else sorted(noKD, key=lambda x: x["pts"])[:3]
    out["obituarios"] = [dict(n=x["n"], pos=x["pos"], tm=x["tm"], eq=x["eq"], pts=x["pts"], proj=x["proj"]) for x in obit]
    # ¿Bajo sospecha? el que más bajó contra la semana pasada
    caidas = []
    for rid in L.rosters:
        h = {x["w"]: x["pts"] for x in hist.get(rid, [])}
        if w in h and (w - 1) in h: caidas.append((h[w - 1] - h[w], rid, h[w - 1], h[w]))
    caidas.sort(reverse=True)
    out["sospecha"] = dict(eq=L.equipo(caidas[0][1]), antes=r1(caidas[0][2]), ahora=r1(caidas[0][3]), caida=r1(caidas[0][0])) if caidas and caidas[0][0] >= 25 else None
    out["banca_total"] = sorted([dict(eq=L.equipo(rid), pts=E["banca"], cambio=E["cambio"]) for rid, E in por_equipo.items()], key=lambda x: -x["pts"])
    # Power ranking: 60% puntos de la temporada (normalizados) + 40% % de victorias, y la semana como desempate
    mx = max(t["pf"] for t in T) or 1
    jug_t = lambda t: max(1, t["g"] + t["p"] + t["e"])
    out["power"] = [dict(eq=t["eq"], rid=t["rid"], g=t["g"], p=t["p"]) for t in
                    sorted(T, key=lambda t: -(0.6 * t["pf"] / mx + 0.4 * (t["g"] + 0.5 * t["e"]) / jug_t(t) + 0.0001 * t["sem"]))]
    for x in out["power"]:
        m = next((m for m in M if L.equipo(x["rid"]) in (m["ganador"], m["perdedor"])), None)
        if m:
            gano = m["ganador"] == x["eq"]; tops = m["g_mejores" if gano else "p_mejores"]
            x["linea"] = (f"{'Le ganó a' if gano else 'Perdió con'} {m['perdedor'] if gano else m['ganador']}, "
                          f"{m['g_pts'] if gano else m['p_pts']}-{m['p_pts'] if gano else m['g_pts']}." +
                          (f" {tops[0]['n'] if tops[0]['pos']=='DEF' else tops[0]['n'].split()[-1]} con {tops[0]['pts']}." if tops else ""))
    # --- récords de la temporada
    R, todos = {}, []
    for rid, h in hist.items():
        for x in h: todos.append(dict(x, rid=rid))
    if todos:
        a = max(todos, key=lambda x: x["pts"]); b = min(todos, key=lambda x: x["pts"])
        gan = [x for x in todos if x["res"] == "W"]
        bl = max(gan, key=lambda x: x["pts"] - x["opp_pts"]) if gan else None
        ce = min(gan, key=lambda x: x["pts"] - x["opp_pts"]) if gan else None
        per = [x for x in todos if x["res"] == "L"]
        ml = max(per, key=lambda x: x["pts"]) if per else None
        nom = lambda x: L.equipo(x["rid"]); rival = lambda x: L.equipo(x["opp"])
        R["alta"] = dict(eq=nom(a), vs=rival(a), w=a["w"], v=r1(a["pts"]))
        R["baja"] = dict(eq=nom(b), vs=rival(b), w=b["w"], v=r1(b["pts"]))
        if bl: R["paliza"] = dict(eq=nom(bl), vs=rival(bl), w=bl["w"], v=r1(bl["pts"] - bl["opp_pts"]))
        if ce: R["cerrado"] = dict(eq=nom(ce), vs=rival(ce), w=ce["w"], v=r1(ce["pts"] - ce["opp_pts"]))
        if ml: R["derrota"] = dict(eq=nom(ml), vs=rival(ml), w=ml["w"], v=r1(ml["pts"]))
        rs = [(racha(rid, w), rid) for rid in L.rosters]
        mw = max(rs); ml2 = min(rs)
        if mw[0] >= 2: R["racha_g"] = dict(eq=L.equipo(mw[1]), v=mw[0])
        if ml2[0] <= -2: R["racha_p"] = dict(eq=L.equipo(ml2[1]), v=-ml2[0])
        for k, v in R.items(): v["nuevo"] = v.get("w") == w
    out["records"] = R
    # --- movimientos de la semana
    tr, mv = [], []
    for t in sorted(L.tx, key=lambda t: t.get("status_updated") or t.get("created") or 0, reverse=True):
        nombre = lambda pid: (L.jugador(pid) or {}).get("n", "?")
        posequ = lambda pid: (lambda j: f"{j['pos']}/{j['tm']}" if j else "")(L.jugador(pid))
        if t.get("type") == "trade":
            lados = []
            for rid in t.get("roster_ids") or []:
                rec = [dict(n=nombre(p), pe=posequ(p)) for p, r in (t.get("adds") or {}).items() if r == rid]
                rec += [dict(n=f"Pick de {d['round']}ª ronda {d['season']}", pe="") for d in (t.get("draft_picks") or []) if d.get("owner_id") == rid]
                lados.append(dict(eq=L.equipo(rid), recibe=rec))
            tr.append(lados)
        else:
            rid = (t.get("roster_ids") or [None])[0]
            mv.append(dict(tipo={"waiver": "WAIVER", "free_agent": "AGENTE LIBRE", "commissioner": "COMISIONADO"}.get(t.get("type"), "MOVIMIENTO"),
                           eq=L.equipo(rid), agrega=[dict(n=nombre(p), pe=posequ(p)) for p in (t.get("adds") or {})],
                           suelta=[dict(n=nombre(p), pe=posequ(p)) for p in (t.get("drops") or {})],
                           faab=(t.get("settings") or {}).get("waiver_bid")))
    out["intercambios"], out["movimientos"] = tr, mv
    # --- previa de la semana que viene (con la mejor alineación proyectada de cada equipo)
    prev = []
    if PROJ_SIG:
        g = {}
        for f in L.mu.get(w + 1) or []:
            if f.get("matchup_id") is not None: g.setdefault(f["matchup_id"], []).append(f)
        for par in g.values():
            if len(par) != 2: continue
            pr = []
            for f in par:
                jug = [L.jugador(p) for p in (L.rosters[f["roster_id"]].get("players") or [])]
                jug = [j for j in jug if j]
                pp = {j["id"]: PROJ_SIG.get(j["key"], 0) for j in jug}
                pr.append((f["roster_id"], r1(mejor_alineacion(L, jug, pp))))
            (ra, pa), (rb, pb) = sorted(pr, key=lambda x: -x[1])
            prev.append(dict(fav=L.equipo(ra), fav_pts=pa, otro=L.equipo(rb), otro_pts=pb, linea=round((pa - pb) * 2) / 2, ou=round((pa + pb) * 2) / 2))
        prev.sort(key=lambda x: -x["linea"])
    out["previa"] = prev
    return out


# ---------------------------------------------------------------- IA (Claude)
REGLAS = """Eres el redactor de un periódico semanal de una liga de fantasy football entre amigos en México.
Escribe en español de México, con humor de cuates, sarcasmo y "carrilla" como en un grupo de WhatsApp de amigos:
burlas sobre decisiones de alineación, rachas, malas compras de waivers y jugadores que no rindieron.

Reglas firmes:
- Usa SOLO los datos que te doy. No inventes marcadores, puntos, lesiones, jugadas, noticias ni récords. Si un dato no está, no lo menciones.
- Los números que escribas deben coincidir exactamente con los datos.
- Nada de groserías fuertes, insultos personales, ni chistes sobre la vida privada, físico, familia, religión, orientación,
  nacionalidad o cualquier cosa fuera del fantasy. Las burlas son solo sobre fantasy. Puedes usar expresiones como
  "no manches", "qué oso", "se la jugó", "le dieron baile".
- Los nombres de equipos y de jugadores van tal cual. Puedes referirte a los managers por su nombre de usuario.
- Los nombres de los premios (Tony Snell, Kyle Pitts, Nick Foles, Joe Burrow) se quedan así.
- Respuesta: SOLO un objeto JSON válido, sin texto antes ni después y sin ```.
"""
FORMATO = """Devuelve exactamente este JSON:
{
 "titular": "titular principal de la edición (máx. 70 caracteres)",
 "subtitulo": "una línea con 2 o 3 datos de la semana",
 "resumen": "un párrafo de 4-6 frases que repase todos los matchups",
 "partidos": [ {"id": <id del matchup>, "etiqueta": "COMEDIA|DRAMA|ÚLTIMA HORA|CRÓNICA",
               "titular": "máx. 80 caracteres", "bajada": "una frase corta y graciosa",
               "historia": ["párrafo sobre el ganador", "párrafo sobre el perdedor (menciona puntos dejados en la banca si los hay)"],
               "cita": "una frase inventada del ganador después del partido (en tono de broma)"} ],
 "sospecha": "si hay dato de 'sospecha', un párrafo estilo expediente policiaco; si no, null",
 "premios": {"snell": "2-3 frases", "pitts": "2-3 frases", "foles": "2-3 frases", "burrow": "2-3 frases"},
 "obituarios": [ {"n": "nombre del jugador", "texto": "2-3 frases estilo esquela"} ],
 "avisos": [ {"titulo": "SE BUSCA / SE VENDE / SE PERDIÓ / etc.", "texto": "1-2 frases", "pie": "remate corto"} ]  (3 avisos)
}
Un objeto en "partidos" por cada matchup, en el mismo orden que te los doy."""

def escribir(datos, liga_nombre, w):
    if os.environ.get("SIN_IA") == "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        print("Periódico: sin IA (SIN_IA=1 o falta ANTHROPIC_API_KEY); se publica solo con datos"); return None, 0
    hechos = {k: datos.get(k) for k in ("matchups", "alta", "baja", "cerrado", "paliza", "promedio", "honor", "castigados",
                                         "premios", "obituarios", "sospecha", "banca_total", "intercambios")}
    hechos["tabla"] = [{k: t[k] for k in ("lugar", "eq", "g", "p", "racha", "mov")} for t in datos.get("tabla", [])]
    msg = f"Liga: {liga_nombre}. Semana {w}.\n\nDATOS:\n{json.dumps(hechos, ensure_ascii=False)}\n\n{FORMATO}"
    body = dict(model=MODELO, max_tokens=16000, system=REGLAS, messages=[dict(role="user", content=msg)])
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                          "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r: res = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("Periódico: la API de Claude respondió con error:", e.code, e.read().decode("utf-8")[:400]); return None, 0
    u = res.get("usage", {}); costo = u.get("input_tokens", 0) / 1e6 * PRECIO_IN + u.get("output_tokens", 0) / 1e6 * PRECIO_OUT
    print(f"Periódico: IA usó {u.get('input_tokens')} tokens de entrada y {u.get('output_tokens')} de salida ≈ ${costo:.3f} USD")
    txt = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text").strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt).strip()
    try: return json.loads(txt), costo
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        try: return json.loads(m.group(0)), costo
        except Exception: print("Periódico: la IA no regresó JSON válido; se publica solo con datos"); return None, costo


# ---------------------------------------------------------------- HTML
CSS = """
:root{--ink:#161616;--muted:#5b5b5b;--line:#d8d4c8;--paper:#fbfaf6;--red:#b8121b;--green:#1f6b3a}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:#ece9e0;color:var(--ink);font:17px/1.55 Georgia,"Times New Roman",serif}
.hoja{max-width:900px;margin:0 auto;background:var(--paper);padding:0 0 30px;box-shadow:0 0 30px rgba(0,0,0,.08)}
.cab{background:var(--red);color:#fff;text-align:center;padding:26px 16px 14px;border-bottom:6px solid var(--ink)}
.cab h1{margin:0;font:900 clamp(34px,8vw,64px)/1 Georgia,serif;letter-spacing:.02em;text-transform:uppercase;text-shadow:3px 3px 0 #000}
.cab p{margin:12px 0 0;font:700 12px/1.4 Georgia,serif;letter-spacing:.18em;text-transform:uppercase;border-top:1px solid rgba(255,255,255,.4);padding-top:10px}
.pad{padding:0 22px}
.tit{text-align:center;margin:26px 0 10px;font:900 clamp(28px,6vw,48px)/1.08 Georgia,serif;text-transform:uppercase}
.sub{text-align:center;font-style:italic;font-weight:700;border-top:2px solid var(--ink);border-bottom:1px solid var(--line);padding:10px 0;margin:0 0 18px}
h2.sec{font:700 13px/1 Georgia,serif;letter-spacing:.2em;text-transform:uppercase;color:var(--red);border-bottom:2px solid var(--red);padding-bottom:6px;margin:30px 0 12px}
h3.band{text-align:center;font:700 15px/1 Georgia,serif;letter-spacing:.2em;text-transform:uppercase;background:#f1ede2;border-top:3px solid var(--ink);border-bottom:2px solid var(--ink);padding:9px;margin:30px 0 12px}
.mu{border-bottom:1px solid var(--line);padding:12px 0}.mu b{text-transform:uppercase}.mu i{color:var(--red);display:block}.mu small{color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:15px}th,td{padding:8px 6px;border-bottom:1px solid var(--line);text-align:right}th{font-size:11px;letter-spacing:.12em;text-transform:uppercase}
td.l,th.l{text-align:left}.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}
.cajas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.caja{border:1.5px solid #bbb;background:#f6f4ee;text-align:center;padding:12px 8px}.caja .k{font:700 11px Georgia;letter-spacing:.15em;text-transform:uppercase;color:var(--muted)}
.caja .v{font:900 28px Georgia;margin:4px 0}.caja .s{font-size:13px;color:var(--muted)}
.fichas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.ficha{border:1px solid var(--line);text-align:center;padding:12px 8px;background:#fff}.ficha b{display:block}.ficha small{color:var(--muted);display:block}
.ficha .v{font:900 26px Georgia;color:#7a6400}.ficha.mal .v{color:var(--red)}
.cron{border-top:3px solid var(--ink);margin-top:24px;padding-top:10px}.cron .et{font:700 12px Georgia;letter-spacing:.18em;color:var(--red)}
.cron h4{margin:4px 0;font:900 clamp(20px,4vw,28px)/1.15 Georgia,serif;text-transform:uppercase}.cron .lin{font-style:italic;color:var(--muted)}
.marc{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--line);background:#fff;padding:10px 14px;margin:10px 0;gap:10px}
.marc b{font-size:18px}.marc .m{color:var(--red);font-weight:700}
blockquote{border-left:5px solid var(--red);margin:14px 0;padding:4px 16px;font:italic 700 clamp(18px,3.4vw,23px)/1.35 Georgia,serif}
blockquote small{display:block;font:400 14px Georgia;color:var(--muted);margin-top:4px}
.fraude{border:3px solid var(--ink);border-left:10px solid var(--red);padding:16px 20px;margin:26px 0;background:#f6f4ee;font-size:19px}
.fraude h3{text-align:center;color:var(--red);letter-spacing:.2em;margin:0 0 10px;font-size:16px}
.premios{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.premio{border:1.5px solid #bbb;padding:12px 14px;background:#fff}.premio h4{margin:0;color:var(--red);font:700 14px Georgia;letter-spacing:.12em;text-transform:uppercase}.premio i{color:var(--muted);font-size:14px}
.power{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.pw{border:1px solid var(--line);background:#fff;text-align:center;padding:10px}
.pw .n{font:900 30px Georgia;color:var(--red)}.pw.t1 .n{color:#b8930a}.pw.t2 .n{color:#7d7d7d}.pw.t3 .n{color:#9a5b22}.pw small{display:block;color:var(--muted);font-style:italic;font-size:13px}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:26px}@media(max-width:700px){.dos{grid-template-columns:1fr}}
.obit{border-bottom:2px solid var(--ink);padding:10px 0}.obit small{color:var(--muted);font-style:italic;display:block}
.prev{border-bottom:1px solid var(--line);padding:10px 0;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;text-align:center}
.prev .ln{font:900 28px Georgia;color:var(--red)}.prev small{display:block;color:var(--muted)}.prev .tag{grid-column:1/-1;font:700 11px Georgia;letter-spacing:.12em;border:1.5px solid var(--ink);padding:3px 8px;justify-self:start}
.rec{border-bottom:1px dotted #aaa;padding:8px 0;display:flex;justify-content:space-between;gap:10px}.rec .v{font:900 26px Georgia;color:var(--red)}.rec small{color:var(--muted)}.nuevo{font:700 10px Georgia;letter-spacing:.12em;color:#999;margin-left:6px}
.tx{display:grid;grid-template-columns:1fr auto 1fr;gap:10px;border-bottom:1px dotted #aaa;padding:10px 0}.tx ul{margin:4px 0;padding-left:18px}
.mv{display:grid;grid-template-columns:120px 1fr;gap:10px;border-bottom:1px dotted #aaa;padding:8px 0;font-size:15px}.mv span{font:700 11px Georgia;letter-spacing:.1em;color:var(--muted)}
.avisos{display:grid;grid-template-columns:1fr 1fr;gap:16px 26px;border-top:4px double var(--ink);border-bottom:4px double var(--ink);padding:16px 0;margin-top:26px}@media(max-width:700px){.avisos{grid-template-columns:1fr}}
.avisos b{display:block;text-transform:uppercase}.avisos i{color:var(--muted);font-size:14px}
.pie{text-align:center;color:var(--muted);font:14px Georgia;margin-top:26px}.pie a{color:var(--red)}
.compartir{display:block;text-align:center;margin:22px auto 0;background:#1f8f4e;color:#fff;text-decoration:none;font:700 16px system-ui,sans-serif;padding:12px 18px;border-radius:999px;max-width:320px}
"""

def render(liga_nombre, titulo, w, fecha, D, T, url):
    S = T or {}
    P = {p.get("id"): p for p in (S.get("partidos") or []) if isinstance(p, dict)}
    a, M = D.get("alta"), D.get("matchups") or []
    tit = S.get("titular") or (f"{a['ganador']} se lleva la semana con {a['g_pts']}" if a else f"Semana {w}")
    sub = S.get("subtitulo") or (f"{D['cerrado']['ganador']} sobrevivió por {D['cerrado']['margen']} · {D['paliza']['ganador']} ganó por {D['paliza']['margen']}" if M else "")
    h = [f"<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{esc(titulo)} · Semana {w}</title><meta property='og:title' content='{esc(titulo)} · Semana {w}'>",
         f"<meta property='og:description' content='{esc(tit)}'><style>{CSS}</style></head><body><div class='hoja'>",
         f"<header class='cab'><h1>{esc(titulo)}</h1><p>Edición de la semana {w} · {esc(liga_nombre)} · {esc(fecha)}</p></header><div class='pad'>",
         f"<div class='tit'>{esc(tit)}</div><p class='sub'>{esc(sub)}</p>"]
    if S.get("resumen"): h.append(f"<p>{esc(S['resumen'])}</p>")
    h.append("<h2 class='sec'>Esta semana</h2>")
    for m in M:
        x = P.get(m["id"], {}); baj = f"<i>{esc(x['bajada'])}</i>" if x.get("bajada") else ""
        h.append(f"<div class='mu'><b>{esc(m['ganador'])} {'empató con' if m['empate'] else 'le ganó a'} {esc(m['perdedor'])}</b>{baj}"
                 f"<small>{m['g_pts']} — {m['p_pts']} | margen: {m['margen']}</small></div>")
    # tabla
    h.append("<h2 class='sec'>Tabla</h2><table><thead><tr><th class='l'>#</th><th class='l'>Equipo</th><th>G-P</th><th>Pts sem.</th><th>Racha</th></tr></thead><tbody>")
    for t in D.get("tabla", []):
        r = t["racha"]; rc = f"<span class='up'>▲ {r}</span>" if r > 0 else f"<span class='dn'>▼ {-r}</span>" if r < 0 else "–"
        h.append(f"<tr><td class='l'>{t['lugar']}</td><td class='l'>{esc(t['eq'])}</td><td>{t['g']}-{t['p']}{'-'+str(t['e']) if t['e'] else ''}</td><td>{r1(t['sem'])}</td><td>{rc}</td></tr>")
    h.append("</tbody></table>")
    if M:
        b, c, p = D["baja"], D["cerrado"], D["paliza"]
        h.append("<div class='cajas'>" + "".join(f"<div class='caja'><div class='k'>{k}</div><div class='v'>{v}</div><div class='s'>{esc(s)}</div></div>" for k, v, s in [
            ("🏆 Más alta", a["g_pts"], a["ganador"]), ("🔥 Más baja", b["p_pts"], b["perdedor"]),
            ("⚔️ Más cerrado", f"{c['margen']} pts", f"{c['ganador']} sobrevivió"), ("😵 Paliza", f"{p['margen']} pts", f"{p['ganador']} arrasó"),
            ("📊 Promedio", D["promedio"], "de la liga")]) + "</div>")
    if D.get("honor"):
        h.append("<h3 class='band'>Cuadro de honor</h3><p style='text-align:center;font-style:italic;color:#5b5b5b'>Los titulares que más anotaron, de cualquier equipo</p><div class='fichas'>")
        h += [f"<div class='ficha'><b>{esc(x['n'])}</b><small>{x['pos']} · {esc(x['eq'])}</small><div class='v'>{x['pts']}</div><small>{'Proy: '+str(x['proj']) if x['proj'] is not None else ''}</small></div>" for x in D["honor"]]
        h.append("</div>")
    if D.get("castigados"):
        h.append("<h3 class='band'>Castigados</h3><p style='text-align:center;font-style:italic;color:#5b5b5b'>Los titulares que más le quedaron a deber a su proyección</p><div class='fichas'>")
        h += [f"<div class='ficha mal'><b>{esc(x['n'])}</b><small>{x['pos']} · {esc(x['eq'])}</small><div class='v'>{x['dif']}</div><small>Proy: {x['proj']} · Hizo {x['pts']}</small></div>" for x in D["castigados"]]
        h.append("</div>")
    # crónicas
    if S.get("partidos"):
        h.append("<h3 class='band'>Crónicas</h3>")
        for m in M:
            x = P.get(m["id"]);
            if not x: continue
            h.append(f"<div class='cron'><div class='et'>{esc(x.get('etiqueta') or 'CRÓNICA')}</div><h4>{esc(x.get('titular'))}</h4>"
                     f"<div class='lin'>{esc(m['ganador'])} {'empató con' if m['empate'] else 'le ganó a'} {esc(m['perdedor'])} | {m['g_pts']} - {m['p_pts']}</div>"
                     f"<div class='marc'><div><b>{esc(m['ganador'])}</b><br><small>{m['g_record']} · {m['g_pts']}</small></div><span class='m'>▶ {m['margen']}</span>"
                     f"<div style='text-align:right'><b>{esc(m['perdedor'])}</b><br><small>{m['p_record']} · {m['p_pts']}</small></div></div>")
            h += [f"<p>{esc(par)}</p>" for par in (x.get("historia") or []) if par]
            if x.get("cita"): h.append(f"<blockquote>“{esc(x['cita'])}”<small>— {esc(m['ganador'])}, después del partido</small></blockquote>")
            h.append("</div>")
    if S.get("sospecha") and D.get("sospecha"):
        h.append(f"<div class='fraude'><h3>🔎 BAJO SOSPECHA</h3>{esc(S['sospecha'])}</div>")
    # premios
    pr, PT = D.get("premios") or {}, S.get("premios") or {}
    cards = []
    for k, nom, desc in [("snell", "Premio Tony Snell", "El titular que no hizo absolutamente nada"), ("pitts", "Premio Kyle Pitts", "El titular que más le quedó a deber a su proyección"),
                         ("foles", "Premio Nick Foles", "La mejor actuación desde la banca"), ("burrow", "Premio Joe Burrow", "La mejor puntuación en una derrota")]:
        d = pr.get(k)
        if not d: continue
        dato = (f"{d['n']} ({d['eq']}): {d['pts']} pts" if "n" in d else f"{d['eq']}: {d['pts']} pts y perdió por {d['margen']}")
        cards.append(f"<div class='premio'><h4>{nom}</h4><i>{desc}</i><p><b>{esc(dato)}</b>{('<br>'+esc(PT[k])) if PT.get(k) else ''}</p></div>")
    if cards: h.append("<h3 class='band'>Premios de la semana</h3><div class='premios'>" + "".join(cards) + "</div>")
    if D.get("power"):
        h.append("<h3 class='band'>Power ranking</h3><div class='power'>")
        h += [f"<div class='pw t{i+1}'><div class='n'>#{i+1}</div><b>{esc(x['eq'])}</b><small>{esc(x.get('linea',''))}</small></div>" for i, x in enumerate(D["power"])]
        h.append("</div>")
    # obituarios + previa
    OT = {o.get("n"): o.get("texto") for o in (S.get("obituarios") or []) if isinstance(o, dict)}
    col1 = ["<h2 class='sec'>Obituarios</h2>"] + [f"<div class='obit'><b>{esc(o['n'])}</b><small>{'Proyectado '+str(o['proj'])+' – ' if o['proj'] is not None else ''}Hizo {o['pts']}</small>"
                                                 f"{esc(OT.get(o['n']) or ('Se nos fue esta semana con '+str(o['pts'])+' puntos. Lo sobrevive '+o['eq']+'.'))}</div>" for o in D.get("obituarios", [])]
    col2 = []
    if D.get("previa"):
        col2 = ["<h2 class='sec'>Previa de la semana " + str(w + 1) + "</h2><p style='font-style:italic;color:#5b5b5b;font-size:14px'>Sale de las proyecciones. La Pizarra no acepta apuestas.</p>"]
        col2 += [f"<div class='prev'><div><b>{esc(x['fav'])}</b><small>{x['fav_pts']}</small></div><div class='ln'>−{x['linea']}</div><div><b>{esc(x['otro'])}</b><small>{x['otro_pts']}</small></div>"
                 f"<span class='tag'>FAVORITO: {esc(x['fav']).upper()} · O/U {x['ou']}</span></div>" for x in D["previa"]]
    R = D.get("records") or {}
    if R:
        col2 = col2 or []
        col1.append("<h2 class='sec'>Libro de récords</h2>")
        for k, nom in [("alta", "Puntuación más alta"), ("baja", "Puntuación más baja"), ("paliza", "Paliza más grande"), ("cerrado", "Partido más cerrado"),
                       ("derrota", "Más puntos en una derrota"), ("racha_g", "Racha ganadora más larga"), ("racha_p", "Racha perdedora más larga")]:
            x = R.get(k)
            if not x: continue
            det = f"{esc(x['eq'])}{' vs '+esc(x['vs']) if x.get('vs') else ''}{' · Sem. '+str(x['w']) if x.get('w') else ''}"
            col1.append(f"<div class='rec'><div><small>{nom.upper()}</small>{'<span class=nuevo>NUEVO</span>' if x.get('nuevo') else ''}<br>{det}</div><div class='v'>{('+' if k in ('paliza','cerrado') else '')}{x['v']}</div></div>")
    h.append(f"<div class='dos'><div>{''.join(col1)}</div><div>{''.join(col2)}</div></div>")
    if D.get("intercambios"):
        h.append("<h2 class='sec'>Intercambios</h2>")
        for lados in D["intercambios"]:
            if len(lados) != 2: continue
            ul = lambda l: "<ul>" + "".join(f"<li>{esc(r['n'])} <small>{esc(r['pe'])}</small></li>" for r in l["recibe"]) + "</ul>"
            h.append(f"<div class='tx'><div><b>{esc(lados[0]['eq'])}</b> recibe{ul(lados[0])}</div><div style='color:#b8121b;font-size:22px'>⇄</div><div><b>{esc(lados[1]['eq'])}</b> recibe{ul(lados[1])}</div></div>")
    if D.get("movimientos"):
        h.append("<h2 class='sec'>Movimientos</h2>")
        for x in D["movimientos"]:
            ag = ", ".join(f"{esc(j['n'])} <small>{esc(j['pe'])}</small>" for j in x["agrega"]); su = ", ".join(f"{esc(j['n'])} <small>{esc(j['pe'])}</small>" for j in x["suelta"])
            h.append(f"<div class='mv'><span>{x['tipo']}{' · $'+str(x['faab']) if x.get('faab') is not None else ''}</span><div><b>{esc(x['eq'])}</b>{' agrega '+ag if ag else ''}{', suelta '+su if su and ag else (' suelta '+su if su else '')}</div></div>")
    if S.get("avisos"):
        h.append("<div class='avisos'>" + "".join(f"<div><b>{esc(x.get('titulo'))}</b>{esc(x.get('texto'))}<br><i>{esc(x.get('pie'))}</i></div>" for x in S["avisos"] if isinstance(x, dict)) + "</div>")
    wa = "https://wa.me/?text=" + urllib.request.quote(f"{titulo} · Semana {w}: {tit} {url}")
    h.append(f"<a class='compartir' href='{wa}' target='_blank' rel='noopener'>Compartir por WhatsApp</a>")
    h.append(f"<p class='pie'>Hecho automáticamente con los datos reales de la liga por <a href='https://lapizarra.mx'>La Pizarra</a>. Los textos los escribe una IA; los números son reales.</p>")
    h.append("</div></div></body></html>")
    return "\n".join(h)


# ---------------------------------------------------------------- Principal
def main():
    cfg = json.load(open(os.path.join(AQUI, "periodico.json"), encoding="utf-8"))
    ligas = [l for l in cfg.get("ligas", []) if l.get("plataforma", "sleeper") == "sleeper"]
    solo = os.environ.get("SOLO_LIGA", "").strip()
    if solo: ligas = [l for l in ligas if str(l["liga"]) == solo]
    hoy = date.today().isoformat()
    ligas = [l for l in ligas if not l.get("hasta") or l["hasta"] >= hoy]
    if not ligas: print("Periódico: no hay ligas activas en periodico.json"); return
    state = get(f"{SLEEPER}/state/nfl"); season = int(state.get("season") or datetime.now().year)
    w = int(os.environ.get("SEMANA") or 0) or semana_terminada(season)
    if not w: print("Periódico: todavía no termina ninguna semana"); return
    print(f"Periódico: temporada {season}, semana {w}, {len(ligas)} liga(s)")
    P = get(f"{SLEEPER}/players/nfl")
    PROJ, PROJ_SIG = proyecciones(season, w), proyecciones(season, w + 1)
    print(f"Periódico: proyecciones semana {w}: {len(PROJ)} jugadores; semana {w+1}: {len(PROJ_SIG)}")
    total = 0.0
    for cfgl in ligas:
        lid = str(cfgl["liga"])
        try:
            L = Liga(lid, season, w, P)
            D = calcular(L, PROJ, PROJ_SIG)
            if not D.get("matchups"): print(f"Periódico: {lid} sin matchups en la semana {w}"); continue
            nombre = L.league.get("name") or "Tu liga"
            titulo = cfgl.get("titulo") or f"El Pizarrón de {nombre}"
            T, costo = escribir(D, nombre, w); total += costo
            carpeta = os.path.join(AQUI, "docs", "periodico", lid); os.makedirs(carpeta, exist_ok=True)
            url = f"https://lapizarra.mx/periodico/{lid}/{season}-{w}.html"
            fecha = datetime.now(timezone.utc).strftime("%d/%m/%Y")
            doc = render(nombre, titulo, w, fecha, D, T, url)
            for f in (f"{season}-{w}.html", "index.html"):
                open(os.path.join(carpeta, f), "w", encoding="utf-8").write(doc)
            json.dump(dict(w=w, temporada=season, titulo=titulo, titular=(T or {}).get("titular") or "", url=f"/periodico/{lid}/{season}-{w}.html"),
                      open(os.path.join(carpeta, "ultimo.json"), "w", encoding="utf-8"), ensure_ascii=False)
            print(f"Periódico: listo {titulo} → {url}")
        except Exception as ex:
            print(f"Periódico: falló la liga {lid}:", repr(ex))
    print(f"Periódico: costo total de IA ≈ ${total:.3f} USD")


if __name__ == "__main__":
    main()
