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
    out["historial"] = {L.equipo(rid): [f"S{x['w']}: {r1(x['pts'])} ({x['res']})" for x in h] for rid, h in hist.items()}
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
LOTERIA = ["El Gallo", "El Diablito", "La Dama", "El Catrín", "El Paraguas", "La Sirena", "La Escalera", "La Botella",
           "El Barril", "El Árbol", "El Melón", "El Valiente", "El Gorrito", "La Muerte", "La Pera", "La Bandera",
           "El Bandolón", "El Violoncello", "La Garza", "El Pájaro", "La Mano", "La Bota", "La Luna", "El Cotorro",
           "El Borracho", "El Corazón", "La Sandía", "El Tambor", "El Camarón", "Las Jaras", "El Músico", "La Araña",
           "El Soldado", "La Estrella", "El Cazo", "El Mundo", "El Nopal", "El Alacrán", "La Rosa", "La Calavera",
           "La Campana", "El Cantarito", "El Venado", "El Sol", "La Corona", "La Chalupa", "El Pino", "El Pescado",
           "La Palma", "La Maceta", "El Arpa", "La Rana"]
PICANTE = {
    "familiar": "Tono: carrilla de cuates pero apto para todo público: sin groserías ni doble sentido.",
    "normal": "Tono: carrilla de cuates con groserías suaves ocasionales (\"no manches\", \"qué oso\", \"le dieron baile\") y algo de doble sentido ligero.",
    "albur": ("Tono: carrilla pesada de cuates CON ALBURES MEXICANOS. Mete albures y doble sentido ingeniosos con frecuencia "
              "(juegos de palabras al estilo del albur chilango), y groserías mexicanas moderadas cuando sumen al chiste. "
              "El albur debe ser ingenioso y de juego de palabras: nada explícito ni gráfico, no describas actos sexuales, "
              "y nada homofóbico, machista o que se burle de alguien por lo que es."),
}
REGLAS = """Eres el redactor estrella de "El Pizarrón", el periódico semanal de una liga de fantasy football entre amigos en México.
Tu estilo mezcla la nota roja y los encabezados de periódico popular mexicano ("¡LO HICIERON CACHITOS!", "¡SE LE APARECIÓ EL DIABLO!"),
el chisme de espectáculos y la narración de un cronista deportivo mexicano apasionado. Usa referencias de la cultura popular mexicana
(dichos, refranes, telenovelas, el futbol mexicano, la lotería, la taquería de la esquina, el tráfico de la CDMX) cuando caigan bien.
Sé creativo y variado: cada crónica con un ángulo distinto, nada de repetir fórmulas, apodos ni remates.

{picante}

Reglas firmes:
- Usa SOLO los datos que te doy. No inventes marcadores, puntos, lesiones, jugadas, noticias, intercambios ni récords. Si un dato no está, no lo menciones.
- Los números que escribas deben coincidir exactamente con los datos.
- La carrilla es solo sobre el fantasy (decisiones, banca, rachas, jugadores, waivers). Nada sobre la vida privada, el físico, la familia,
  la religión, la orientación sexual, la nacionalidad, el dinero o el trabajo de nadie.
- Los nombres de equipos y de jugadores van tal cual. A los managers puedes llamarlos por su nombre de usuario.
- Respuesta: SOLO un objeto JSON válido, sin texto antes ni después y sin ```.
"""
FORMATO = """Devuelve exactamente este JSON:
{
 "titular": "titular principal estilo periódico popular mexicano (máx. 70 caracteres)",
 "subtitulo": "una línea con 2 o 3 datos de la semana",
 "resumen": "un párrafo de 4-6 frases que repase todos los matchups con mucho sabor",
 "partidos": [ {"id": <id del matchup>, "etiqueta": "NOTA ROJA|CHISME|ESPECTÁCULOS|DEPORTES|ÚLTIMA HORA",
               "titular": "máx. 80 caracteres", "bajada": "una frase corta y graciosa",
               "historia": ["párrafo sobre el ganador", "párrafo sobre el perdedor (si dejó puntos en la banca, restriégaselo)"],
               "cita": "una frase inventada del ganador después del partido"} ],
 "banca": "2-3 frases sobre la tabla de puntos dejados en la banca (quién dejó más)",
 "sospecha": "si hay dato de 'sospecha', un párrafo estilo citatorio de la dirección de la escuela; si no, null",
 "premios": {"snell": "2-3 frases", "pitts": "2-3 frases", "foles": "2-3 frases", "burrow": "2-3 frases"},
 "loteria": [ {"eq": "nombre exacto del equipo", "carta": "una carta de la lista", "verso": "un verso corto estilo gritón de lotería sobre su semana"} ],
 "obituarios": [ {"n": "nombre del jugador", "texto": "2-3 frases estilo esquela"} ],
 "avisos": [ {"titulo": "SE BUSCA / SE VENDE / SE RENTA / SE PERDIÓ / etc.", "texto": "1-2 frases", "pie": "remate corto"} ]  (4 avisos)
}
- Un objeto en "partidos" por cada matchup, en el mismo orden que te los doy.
- "loteria": un objeto por cada equipo del power ranking, en ese orden; cada equipo con una carta DISTINTA de esta lista: {cartas}."""

def escribir(datos, liga_nombre, w, picante="normal"):
    if os.environ.get("SIN_IA") == "1" or not os.environ.get("ANTHROPIC_API_KEY"):
        print("Periódico: sin IA (SIN_IA=1 o falta ANTHROPIC_API_KEY); se publica solo con datos"); return None, 0
    hechos = {k: datos.get(k) for k in ("matchups", "alta", "baja", "cerrado", "paliza", "promedio", "honor", "castigados",
                                         "premios", "obituarios", "sospecha", "banca_total", "intercambios", "historial")}
    hechos["tabla"] = [{k: t[k] for k in ("lugar", "eq", "g", "p", "racha", "mov")} for t in datos.get("tabla", [])]
    hechos["power_ranking"] = [x["eq"] for x in datos.get("power", [])]
    sistema = REGLAS.replace("{picante}", PICANTE.get(picante, PICANTE["normal"]))
    msg = f"Liga: {liga_nombre}. Semana {w}.\n\nDATOS:\n{json.dumps(hechos, ensure_ascii=False)}\n\n" + FORMATO.replace("{cartas}", ", ".join(LOTERIA))
    body = dict(model=MODELO, max_tokens=16000, system=sistema, messages=[dict(role="user", content=msg)])
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


# ---------------------------------------------------------------- HTML (estilo La Pizarra: pizarrón verde, gis y amarillo)
def logo_svg():
    try:
        t = open(os.path.join(AQUI, "template.html"), encoding="utf-8").read()
        m = re.search(r'<symbol id="lp-logo" viewBox="0 0 64 64">(.*?)</symbol>', t, re.S)
        if m: return f'<svg viewBox="0 0 64 64" width="38" height="38" aria-hidden="true">{m.group(1)}</svg>'
    except Exception: pass
    return ""

CSS = """
:root{--board:#1F332D;--board2:#263D36;--deep:#15241F;--chalk:#ECEFE7;--dim:#A8B8AF;--line:#3A554C;--yellow:#F2D466;--blue:#9CC7E6;
--red:#F29C8C;--green:#8FD6A6;--wood:#7A5232;--paper:#F6F0DF;--ink:#1B2A38;--disp:"Barlow Condensed","Arial Narrow",Arial,sans-serif;
--body:"Barlow","Helvetica Neue",Arial,sans-serif;--gis:"Cabin Sketch","Barlow Condensed",sans-serif;--mano:"Caveat",cursive}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:#101c18;color:var(--chalk);font:17px/1.6 var(--body)}
.hoja{max-width:940px;margin:18px auto;background:radial-gradient(ellipse at 20% 0%,rgba(255,255,255,.05),transparent 55%),radial-gradient(ellipse at 90% 60%,rgba(255,255,255,.035),transparent 50%),var(--board);
 border:14px solid var(--wood);border-radius:6px;box-shadow:inset 0 0 60px rgba(0,0,0,.45),0 10px 40px rgba(0,0,0,.5);padding:0 0 28px;position:relative}
@media(max-width:640px){.hoja{margin:0;border-width:7px;border-radius:0}}
.pad{padding:0 24px}@media(max-width:640px){.pad{padding:0 16px}}
.cab{text-align:center;padding:26px 16px 10px;position:relative}
.cab .marca{display:inline-flex;align-items:center;gap:8px;font:600 15px var(--disp);letter-spacing:.14em;text-transform:uppercase;color:var(--dim)}
.cab h1{margin:6px 0 0;font:700 clamp(54px,13vw,104px)/.9 var(--gis);color:var(--chalk);letter-spacing:.01em}
.cab h2{margin:4px 0 0;font:700 clamp(22px,5vw,34px)/1.1 var(--gis);color:var(--yellow)}
.cab .ed{margin:14px auto 0;max-width:720px;border-top:2px dashed rgba(236,239,231,.35);border-bottom:2px dashed rgba(236,239,231,.35);padding:8px 0;font:600 14px var(--disp);letter-spacing:.16em;text-transform:uppercase;color:var(--dim)}
.cab svg.jug{position:absolute;opacity:.45}
.tit{margin:26px 0 8px;text-align:center;font:700 clamp(34px,7vw,60px)/1 var(--disp);text-transform:uppercase;color:var(--yellow);letter-spacing:.01em;text-shadow:0 0 1px rgba(0,0,0,.3)}
.sub{text-align:center;font:500 19px/1.4 var(--mano);font-size:24px;color:var(--chalk);margin:0 0 16px}
.res{font-size:18px}
h3.sec{font:700 30px/1.1 var(--gis);color:var(--yellow);margin:36px 0 12px;display:flex;align-items:center;gap:10px}
h3.sec::after{content:"";flex:1;border-bottom:2px dashed rgba(242,212,102,.45);margin-top:8px}
p.nota{color:var(--dim);font-style:italic;margin:-6px 0 12px;font-size:15px}
.marcs{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:10px}
.mc{background:var(--board2);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
.mc .r{display:flex;justify-content:space-between;gap:10px;font:600 19px/1.35 var(--disp)}.mc .r.g b{color:var(--yellow)}.mc .r.p{color:var(--dim)}
.mc i{display:block;font:500 20px/1.2 var(--mano);color:var(--blue);margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:16px}th,td{padding:8px 6px;border-bottom:1px dashed var(--line);text-align:right}
th{font:600 13px var(--disp);letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}td.l,th.l{text-align:left}
.up{color:var(--green);font-weight:700}.dn{color:var(--red);font-weight:700}
.cajas{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.caja{border:2px solid rgba(236,239,231,.55);border-radius:12px;text-align:center;padding:12px 8px}
.caja .k{font:600 13px var(--disp);letter-spacing:.12em;text-transform:uppercase;color:var(--dim)}.caja .v{font:700 36px/1.1 var(--gis);color:var(--yellow)}.caja .s{font-size:14px;color:var(--chalk)}
.fichas{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}
.ficha{background:var(--board2);border:1px solid var(--line);border-radius:10px;text-align:center;padding:12px 8px}
.ficha b{display:block;font:700 18px/1.15 var(--disp)}.ficha small{color:var(--dim);display:block;font-size:13px}
.ficha .v{font:700 36px/1.1 var(--gis);color:var(--yellow)}.ficha.mal .v{color:var(--red)}
.ficha .sello{display:inline-block;transform:rotate(-6deg);border:2px solid var(--red);color:var(--red);border-radius:4px;font:700 12px var(--disp);letter-spacing:.14em;padding:1px 8px;margin:4px 0 2px}
.ficha .est{display:block;color:var(--yellow);font-size:18px;line-height:1}
.barras .b{display:grid;grid-template-columns:minmax(0,1.3fr) 3fr auto;gap:10px;align-items:center;margin:6px 0;font-size:15px}
.barras .b span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.barras .b i{display:block;height:14px;border-radius:7px;background:var(--yellow)}.barras .b em{font:700 18px var(--disp);font-style:normal;color:var(--yellow)}
.barras small{display:block;color:var(--dim);grid-column:1/-1;margin:-4px 0 4px;font-size:13px}
.cron{margin-top:26px;padding-top:16px;border-top:2px dashed rgba(236,239,231,.3)}
.et{display:inline-block;font:700 13px var(--disp);letter-spacing:.14em;padding:3px 10px;border-radius:4px;color:#1B2A38;background:var(--yellow)}
.et.NOTA{background:var(--red)}.et.CHISME{background:#F4B6D2}.et.ESPECTÁCULOS{background:var(--blue)}.et.DEPORTES{background:var(--green)}
.cron h4{margin:8px 0 4px;font:700 clamp(26px,5vw,36px)/1.05 var(--disp);text-transform:uppercase;color:var(--chalk)}
.cron .baj{font:500 22px/1.25 var(--mano);color:var(--blue)}
.marc{display:flex;justify-content:space-between;align-items:center;background:var(--deep);border-radius:10px;padding:10px 14px;margin:12px 0;gap:10px}
.marc b{font:700 20px var(--disp);display:block}.marc small{color:var(--dim)}.marc .m{font:700 26px var(--gis);color:var(--yellow);white-space:nowrap}
.cita{font:600 clamp(24px,4.5vw,30px)/1.2 var(--mano);color:var(--yellow);margin:14px 0 0;padding-left:16px;border-left:4px solid var(--yellow)}
.cita small{display:block;font:400 14px var(--body);color:var(--dim);margin-top:4px}
.papel{background:var(--paper);color:var(--ink);border-radius:4px;padding:18px 22px;margin:30px auto;max-width:720px;transform:rotate(-1deg);box-shadow:0 8px 20px rgba(0,0,0,.4);position:relative}
.papel::before{content:"";position:absolute;top:-12px;left:50%;width:110px;height:26px;margin-left:-55px;background:rgba(255,255,230,.55);transform:rotate(2deg)}
.papel h4{margin:0 0 8px;font:700 24px var(--disp);letter-spacing:.08em;color:#B53A2E;text-transform:uppercase}
.premios{display:grid;grid-template-columns:1fr 1fr;gap:12px}@media(max-width:640px){.premios{grid-template-columns:1fr}}
.premio{background:var(--board2);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.premio .ic{font-size:30px}.premio h5{margin:2px 0 0;font:700 22px/1.1 var(--disp);color:var(--yellow);text-transform:uppercase}
.premio i{color:var(--dim);font-size:14px;display:block}.premio p{margin:8px 0 0}
.lot{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}@media(max-width:760px){.lot{grid-template-columns:repeat(2,1fr)}}
.carta{background:var(--paper);color:var(--ink);border:6px solid #fff;outline:3px solid #B53A2E;outline-offset:-12px;border-radius:6px;padding:16px 12px 12px;text-align:center;box-shadow:0 6px 16px rgba(0,0,0,.35);position:relative}
.carta .n{position:absolute;top:10px;left:14px;font:700 22px var(--disp);color:#B53A2E}
.carta .nom{font:700 21px/1.05 var(--disp);text-transform:uppercase;margin:16px 0 6px;letter-spacing:.03em}
.carta .eq{font:600 15px var(--body);border-top:1px solid #c9bfa6;padding-top:6px}.carta .ver{font:500 18px/1.15 var(--mano);color:#5a4632;margin-top:4px}
.carta small{display:block;color:#7b6a55;font-size:12px}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:28px}@media(max-width:700px){.dos{grid-template-columns:1fr}}
.esq{border:2px solid rgba(236,239,231,.5);border-radius:6px;padding:12px 14px;margin-bottom:10px;text-align:center}
.esq b{font:700 20px var(--disp)}.esq small{display:block;color:var(--dim);font-style:italic}
.prev{background:var(--board2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:8px;text-align:center}
.prev b{font:700 17px/1.1 var(--disp)}.prev small{display:block;color:var(--dim)}.prev .ln{font:700 30px var(--gis);color:var(--yellow)}
.prev .tag{grid-column:1/-1;font:600 12px var(--disp);letter-spacing:.1em;color:var(--dim)}
.rec{border-bottom:1px dashed var(--line);padding:8px 0;display:flex;justify-content:space-between;gap:10px;align-items:center}
.rec .v{font:700 30px var(--gis);color:var(--yellow)}.rec small{color:var(--dim);font:600 12px var(--disp);letter-spacing:.1em}
.nuevo{background:var(--yellow);color:#1B2A38;font:700 10px var(--disp);letter-spacing:.1em;padding:1px 6px;border-radius:3px;margin-left:6px}
.tx{display:grid;grid-template-columns:1fr auto 1fr;gap:10px;background:var(--board2);border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.tx ul{margin:4px 0;padding-left:18px}.tx .fl{font-size:26px;color:var(--yellow);align-self:center}
.mv{display:grid;grid-template-columns:130px 1fr;gap:10px;border-bottom:1px dashed var(--line);padding:8px 0;font-size:15px}
.mv span{font:700 12px var(--disp);letter-spacing:.1em;color:var(--blue)}small.pe{color:var(--dim);font-size:12px}
.posts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-top:6px}
.post{background:#F7E58A;color:#2b2a1f;padding:14px 14px 12px;box-shadow:0 6px 14px rgba(0,0,0,.35);transform:rotate(-1.5deg)}
.post:nth-child(2n){transform:rotate(1.2deg);background:#F9C9D9}.post:nth-child(3n){background:#BFE3F5;transform:rotate(-.6deg)}
.post b{display:block;font:700 18px var(--disp);text-transform:uppercase}.post i{display:block;font:500 18px var(--mano);margin-top:4px}
.cta{text-align:center;margin:36px 0 0;padding:20px;border:2px dashed rgba(236,239,231,.4);border-radius:14px}
.cta b{display:block;font:700 26px var(--gis);color:var(--yellow)}
.compartir{display:inline-block;margin-top:12px;background:#25D366;color:#0b2b17;text-decoration:none;font:700 17px var(--disp);letter-spacing:.04em;padding:12px 22px;border-radius:999px}
.pie{text-align:center;color:var(--dim);font-size:13px;margin-top:18px}.pie a{color:var(--yellow)}
"""
JUGADA = ('<svg class="jug" style="{pos}" width="150" height="90" viewBox="0 0 150 90" fill="none" stroke="#ECEFE7" stroke-width="2.5" stroke-linecap="round">'
          '<circle cx="20" cy="70" r="7"/><circle cx="50" cy="70" r="7"/><circle cx="80" cy="70" r="7"/>'
          '<path d="M30 20 l10 10 M40 20 l-10 10 M100 15 l10 10 M110 15 l-10 10"/>'
          '<path d="M50 62 C55 35 90 30 120 40 M114 34 l6 6 -8 3" stroke="#F2D466"/></svg>')
PREMIOS = [("snell", "😶", "Premio «Ni sus luces»", "El titular que no hizo absolutamente nada"),
           ("pitts", "📉", "Premio «Prometía mucho»", "El que más le quedó a deber a su proyección"),
           ("foles", "🪑", "Premio «¿Pa' qué lo banqueas?»", "La mejor actuación desde la banca"),
           ("burrow", "💀", "Premio «Murió en la raya»", "La mejor puntuación en una derrota")]

def render(liga_nombre, titulo, w, fecha, D, T, url):
    S = T or {}
    P = {p.get("id"): p for p in (S.get("partidos") or []) if isinstance(p, dict)}
    a, M = D.get("alta"), D.get("matchups") or []
    tit = S.get("titular") or (f"¡{a['ganador']} se la llevó con {a['g_pts']}!" if a else f"Semana {w}")
    sub = S.get("subtitulo") or (f"{D['cerrado']['ganador']} sobrevivió por {D['cerrado']['margen']} · {D['paliza']['ganador']} ganó por {D['paliza']['margen']}" if M else "")
    fonts = "https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600&family=Barlow+Condensed:wght@500;600;700&family=Cabin+Sketch:wght@700&family=Caveat:wght@500;600&display=swap"
    h = [f"<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{esc(titulo)} · Semana {w}</title><meta property='og:title' content='{esc(titulo)} · Semana {w}'><meta property='og:description' content='{esc(tit)}'>",
         f"<link rel='preconnect' href='https://fonts.googleapis.com'><link rel='preconnect' href='https://fonts.gstatic.com' crossorigin><link href='{fonts}' rel='stylesheet'>",
         f"<style>{CSS}</style></head><body><div class='hoja'>",
         "<header class='cab'>" + JUGADA.replace("{pos}", "top:18px;left:16px") + JUGADA.replace("{pos}", "top:18px;right:16px;transform:scaleX(-1)"),
         f"<div class='marca'>{logo_svg()}La Pizarra presenta</div>",
         f"<h1>{esc(titulo.split(' de ')[0] if ' de ' in titulo else titulo)}</h1>",
         f"<h2>{esc(titulo.split(' de ', 1)[1]) if ' de ' in titulo else esc(liga_nombre)}</h2>",
         f"<div class='ed'>Semana {w} · {esc(fecha)} · Edición con gis y sin filtro</div></header><div class='pad'>",
         f"<div class='tit'>{esc(tit)}</div><p class='sub'>{esc(sub)}</p>"]
    if S.get("resumen"): h.append(f"<p class='res'>{esc(S['resumen'])}</p>")
    h.append("<h3 class='sec'>Los marcadores</h3><div class='marcs'>")
    for m in M:
        x = P.get(m["id"], {}); baj = f"<i>{esc(x['bajada'])}</i>" if x.get("bajada") else ""
        h.append(f"<div class='mc'><div class='r g'><span>{esc(m['ganador'])}</span><b>{m['g_pts']}</b></div><div class='r p'><span>{esc(m['perdedor'])}</span><span>{m['p_pts']}</span></div>{baj}</div>")
    h.append("</div>")
    if M:
        b, c, p = D["baja"], D["cerrado"], D["paliza"]
        h.append("<div class='cajas'>" + "".join(f"<div class='caja'><div class='k'>{k}</div><div class='v'>{v}</div><div class='s'>{esc(s)}</div></div>" for k, v, s in [
            ("🏆 La más alta", a["g_pts"], a["ganador"]), ("🥶 La más baja", b["p_pts"], b["perdedor"]),
            ("😰 De panzazo", f"{c['margen']}", f"{c['ganador']} sobrevivió"), ("🔨 La madriza", f"{p['margen']}", f"{p['ganador']} no tuvo piedad"),
            ("📊 Promedio", D["promedio"], "de la liga")]) + "</div>")
    h.append("<h3 class='sec'>La tabla</h3><table><thead><tr><th class='l'>#</th><th class='l'>Equipo</th><th>G-P</th><th>Esta semana</th><th>Racha</th></tr></thead><tbody>")
    for t in D.get("tabla", []):
        r = t["racha"]; rc = f"<span class='up'>▲ {r}</span>" if r > 0 else f"<span class='dn'>▼ {-r}</span>" if r < 0 else "–"
        h.append(f"<tr><td class='l'>{t['lugar']}</td><td class='l'>{esc(t['eq'])}</td><td>{t['g']}-{t['p']}{'-'+str(t['e']) if t['e'] else ''}</td><td>{r1(t['sem'])}</td><td>{rc}</td></tr>")
    h.append("</tbody></table>")
    if D.get("honor"):
        h.append("<h3 class='sec'>Cuadro de honor</h3><p class='nota'>Los titulares que más anotaron, de cualquier equipo</p><div class='fichas'>")
        h += [f"<div class='ficha'><span class='est'>★</span><b>{esc(x['n'])}</b><small>{x['pos']} · {esc(x['eq'])}</small><div class='v'>{x['pts']}</div><small>{'Proyección: '+str(x['proj']) if x['proj'] is not None else ''}</small></div>" for x in D["honor"]]
        h.append("</div>")
    if D.get("castigados"):
        h.append("<h3 class='sec'>Los reprobados</h3><p class='nota'>Los titulares que más le quedaron a deber a su proyección</p><div class='fichas'>")
        h += [f"<div class='ficha mal'><b>{esc(x['n'])}</b><small>{x['pos']} · {esc(x['eq'])}</small><div class='v'>{x['dif']}</div><span class='sello'>REPROBADO</span><small>Debía {x['proj']} · Hizo {x['pts']}</small></div>" for x in D["castigados"]]
        h.append("</div>")
    bt = [x for x in D.get("banca_total", []) if x["pts"] > 0]
    if bt:
        mx = max(x["pts"] for x in bt)
        h.append("<h3 class='sec'>La banca de los lamentos</h3><p class='nota'>Puntos que cada quien dejó sentados (mejor alineación posible contra la que puso)</p>")
        if S.get("banca"): h.append(f"<p>{esc(S['banca'])}</p>")
        h.append("<div class='barras'>")
        for x in bt:
            cam = x.get("cambio"); det = f"<small>{esc(cam['banca'])} ({cam['banca_pts']}) en la banca y {esc(cam['titular'])} ({cam['titular_pts']}) de titular</small>" if cam else ""
            h.append(f"<div class='b'><span>{esc(x['eq'])}</span><i style='width:{max(4, x['pts']/mx*100):.0f}%'></i><em>{x['pts']}</em>{det}</div>")
        h.append("</div>")
    if S.get("partidos"):
        h.append("<h3 class='sec'>Crónicas de la jornada</h3>")
        for m in M:
            x = P.get(m["id"])
            if not x: continue
            et = (x.get("etiqueta") or "DEPORTES").upper()
            h.append(f"<div class='cron'><span class='et {esc(et.split()[0])}'>{esc(et)}</span><h4>{esc(x.get('titular'))}</h4>"
                     f"{'<div class=baj>'+esc(x.get('bajada'))+'</div>' if x.get('bajada') else ''}"
                     f"<div class='marc'><div><b>{esc(m['ganador'])}</b><small>{m['g_record']} · {m['g_pts']}</small></div><span class='m'>+{m['margen']}</span>"
                     f"<div style='text-align:right'><b>{esc(m['perdedor'])}</b><small>{m['p_record']} · {m['p_pts']}</small></div></div>")
            h += [f"<p>{esc(par)}</p>" for par in (x.get("historia") or []) if par]
            if x.get("cita"): h.append(f"<div class='cita'>“{esc(x['cita'])}”<small>— {esc(m['ganador'])}, saliendo del estadio</small></div>")
            h.append("</div>")
    if S.get("sospecha") and D.get("sospecha"):
        sp = D["sospecha"]
        h.append(f"<div class='papel'><h4>📋 Citatorio a la dirección</h4><p><b>{esc(sp['eq'])}</b>: de {sp['antes']} a {sp['ahora']} puntos en una semana.</p><p>{esc(S['sospecha'])}</p></div>")
    pr, PT = D.get("premios") or {}, S.get("premios") or {}
    cards = []
    for k, ic, nom, desc in PREMIOS:
        d = pr.get(k)
        if not d: continue
        dato = (f"{d['n']} ({d['eq']}): {d['pts']} pts" if "n" in d else f"{d['eq']}: {d['pts']} pts y perdió por {d['margen']}")
        cards.append(f"<div class='premio'><div class='ic'>{ic}</div><h5>{nom}</h5><i>{desc}</i><p><b>{esc(dato)}</b>{('<br>'+esc(PT[k])) if PT.get(k) else ''}</p></div>")
    if cards: h.append("<h3 class='sec'>Premios de la semana</h3><div class='premios'>" + "".join(cards) + "</div>")
    if D.get("power"):
        LT = {x.get("eq"): x for x in (S.get("loteria") or []) if isinstance(x, dict)}
        h.append("<h3 class='sec'>La lotería del power ranking</h3><p class='nota'>¡Corre y se va corriendo! El orden es nuestro power ranking de la semana</p><div class='lot'>")
        for i, x in enumerate(D["power"]):
            L2 = LT.get(x["eq"], {})
            h.append(f"<div class='carta'><span class='n'>{i+1}</span><div class='nom'>{esc(L2.get('carta') or ('El Valiente' if i == 0 else '—'))}</div>"
                     f"<div class='eq'>{esc(x['eq'])}</div>{'<div class=ver>'+esc(L2.get('verso'))+'</div>' if L2.get('verso') else ''}<small>{x['g']}-{x['p']} · {esc(x.get('linea',''))}</small></div>")
        h.append("</div>")
    OT = {o.get("n"): o.get("texto") for o in (S.get("obituarios") or []) if isinstance(o, dict)}
    col1 = ["<h3 class='sec'>Minuto de silencio</h3>"] + [f"<div class='esq'>🕯️<br><b>{esc(o['n'])}</b><small>{'Se esperaban '+str(o['proj'])+' · ' if o['proj'] is not None else ''}Dio {o['pts']}</small>"
                                                          f"{esc(OT.get(o['n']) or ('Se nos fue con '+str(o['pts'])+' puntos. Lo llora '+o['eq']+'.'))}</div>" for o in D.get("obituarios", [])]
    col2 = []
    if D.get("previa"):
        col2 = [f"<h3 class='sec'>La línea de la semana {w+1}</h3><p class='nota'>Sale de las proyecciones. Aquí no se aceptan apuestas, solo carrilla.</p>"]
        col2 += [f"<div class='prev'><div><b>{esc(x['fav'])}</b><small>{x['fav_pts']}</small></div><div class='ln'>−{x['linea']}</div><div><b>{esc(x['otro'])}</b><small>{x['otro_pts']}</small></div>"
                 f"<span class='tag'>FAVORITO: {esc(x['fav']).upper()} · O/U {x['ou']}</span></div>" for x in D["previa"]]
    R = D.get("records") or {}
    rec = []
    for k, nom in [("alta", "Puntuación más alta"), ("baja", "Puntuación más baja"), ("paliza", "La madriza más grande"), ("cerrado", "El partido más cerrado"),
                   ("derrota", "Más puntos en una derrota"), ("racha_g", "Racha ganadora"), ("racha_p", "Racha perdedora")]:
        x = R.get(k)
        if not x: continue
        det = f"{esc(x['eq'])}{' vs '+esc(x['vs']) if x.get('vs') else ''}{' · Sem. '+str(x['w']) if x.get('w') else ''}"
        rec.append(f"<div class='rec'><div><small>{nom.upper()}</small>{'<span class=nuevo>¡NUEVO!</span>' if x.get('nuevo') else ''}<br>{det}</div><div class='v'>{('+' if k in ('paliza','cerrado') else '')}{x['v']}</div></div>")
    if rec: (col2 if col2 else col1).extend(["<h3 class='sec'>Libro de récords</h3>"] + rec)
    h.append(f"<div class='dos'><div>{''.join(col1)}</div><div>{''.join(col2)}</div></div>")
    if D.get("intercambios"):
        h.append("<h3 class='sec'>El tianguis de intercambios</h3>")
        for lados in D["intercambios"]:
            if len(lados) != 2: continue
            ul = lambda l: "<ul>" + "".join(f"<li>{esc(r['n'])} <small class='pe'>{esc(r['pe'])}</small></li>" for r in l["recibe"]) + "</ul>"
            h.append(f"<div class='tx'><div><b>{esc(lados[0]['eq'])}</b> se lleva{ul(lados[0])}</div><div class='fl'>⇄</div><div><b>{esc(lados[1]['eq'])}</b> se lleva{ul(lados[1])}</div></div>")
    if D.get("movimientos"):
        h.append("<h3 class='sec'>Altas y bajas</h3>")
        for x in D["movimientos"]:
            ag = ", ".join(f"{esc(j['n'])} <small class='pe'>{esc(j['pe'])}</small>" for j in x["agrega"]); su = ", ".join(f"{esc(j['n'])} <small class='pe'>{esc(j['pe'])}</small>" for j in x["suelta"])
            h.append(f"<div class='mv'><span>{x['tipo']}{' · $'+str(x['faab']) if x.get('faab') is not None else ''}</span><div><b>{esc(x['eq'])}</b>{' agrega '+ag if ag else ''}{', suelta '+su if su and ag else (' suelta '+su if su else '')}</div></div>")
    if S.get("avisos"):
        h.append("<h3 class='sec'>Clasificados</h3><div class='posts'>" + "".join(f"<div class='post'><b>{esc(x.get('titulo'))}</b>{esc(x.get('texto'))}<i>{esc(x.get('pie'))}</i></div>" for x in S["avisos"] if isinstance(x, dict)) + "</div>")
    wa = "https://wa.me/?text=" + urllib.request.quote(f"{titulo} · Semana {w}: {tit} {url}")
    h.append(f"<div class='cta'><b>¿Ya lo viste? Pásalo al grupo</b><a class='compartir' href='{wa}' target='_blank' rel='noopener'>Compartir por WhatsApp</a>"
             f"<p class='pie'>¿Quieres El Pizarrón para tu liga? Pídelo en <a href='https://lapizarra.mx'>lapizarra.mx</a></p></div>")
    h.append("<p class='pie'>Hecho con los datos reales de la liga por La Pizarra. Los textos los escribe una IA con mucha carrilla; los números son reales.</p>")
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
            T, costo = escribir(D, nombre, w, cfgl.get("picante", "normal")); total += costo
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
