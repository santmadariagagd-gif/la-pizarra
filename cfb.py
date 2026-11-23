"""
cfb.py — futbol americano colegial y draft de la NFL para La Pizarra (18 nov 2026).

Datos de College Football Data (collegefootballdata.com, API v2). Llave gratis en el secreto CFBD_API_KEY:
1,000 consultas al mes. Por eso todo pasa por una caché en .afcache/cfbd/ (GitHub la guarda entre corridas) con un
tiempo de vida por tipo de dato, y un tope de 900 consultas por mes.

Arma docs/datos/cfb.json:
  al, season, week, st (regular|postseason)
  ap / cfp: [[rank, school, conf, votos_1er_lugar]]  (Top 25 de AP y ranking del College Football Playoff si ya salió)
  games: partidos de la semana (y los de la anterior) entre equipos FBS, con ranking
  teams: {school: [abreviatura, color, logo, conferencia]} solo de los equipos que aparecen
  pros: tablero de prospectos para el draft (ver `tablero`), top 160
  draft: {y, order: [[pick, equipo_nfl, "w-l", [necesidades]]]} (si la temporada terminara hoy, sin cambios por intercambios)
"""
import hashlib, json, math, os, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timezone

BASE = "https://api.collegefootballdata.com"
KEY = os.environ.get("CFBD_API_KEY", "").strip()
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".afcache", "cfbd")
TOPE_MES = 1500   # Tier 1: 5,000 al mes compartidas; hasta 3,000 son para el marcador en vivo (cfb_vivo.py)
POWER = {"SEC", "Big Ten", "Big 12", "ACC"}


def _uso():
    p = os.path.join(CACHE, "_uso.json")
    try: U = json.load(open(p))
    except Exception: U = {}
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    return p, U, mes


def get(ruta, ttl, **q):
    """GET con caché. ttl en horas. Si no hay llave, se pasó del tope o falla, regresa lo último guardado (o None)."""
    os.makedirs(CACHE, exist_ok=True)
    url = BASE + ruta + ("?" + urllib.parse.urlencode({k: v for k, v in q.items() if v is not None}) if q else "")
    f = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".json")
    viejo = None
    if os.path.exists(f):
        try:
            viejo = json.load(open(f))
            if time.time() - viejo["t"] < ttl * 3600: return viejo["d"]
        except Exception: viejo = None
    p, U, mes = _uso()
    if not KEY or U.get(mes, 0) >= TOPE_MES:
        return viejo["d"] if viejo else None
    try:
        r = urllib.request.Request(url, headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json", "User-Agent": "lapizarra.mx"})
        with urllib.request.urlopen(r, timeout=90) as x: d = json.loads(x.read().decode())
        U[mes] = U.get(mes, 0) + 1; json.dump(U, open(p, "w"))
        json.dump({"t": time.time(), "d": d}, open(f, "w"))
        return d
    except Exception as e:
        print("Colegial:", ruta, getattr(e, "code", ""), str(e)[:120])
        return viejo["d"] if viejo else None


def g(x, *ks, d=None):
    """Lee un campo en camelCase o snake_case (la API v2 usa camelCase)."""
    for k in ks:
        if isinstance(x, dict) and x.get(k) is not None: return x[k]
    return d


# ---------------------------------------------------------------- semana actual
def semana(season):
    cal = get("/calendar", 24 * 7, year=season) or []
    now = datetime.now(timezone.utc).isoformat()
    sem, st = None, "regular"
    for c in cal:
        ini, fin = g(c, "startDate", "firstGameStart"), g(c, "endDate", "lastGameStart")
        if not ini: continue
        if ini[:10] <= now[:10]: sem, st = g(c, "week"), g(c, "seasonType", "season_type") or "regular"
    if sem is None and cal: sem, st = g(cal[0], "week"), g(cal[0], "seasonType", "season_type") or "regular"
    return sem or 1, st


# ---------------------------------------------------------------- tablero de prospectos
# Valor de cada posición en el draft (en desviaciones estándar): un QB o un EDGE buenos se van antes que un RB igual de bueno.
VALOR = {"QB": .6, "EDGE": .4, "OT": .4, "CB": .3, "WR": .3, "DL": .2, "S": 0, "LB": -.1, "TE": -.2, "IOL": -.2, "RB": -.3}
POS = {"QB": "QB", "RB": "RB", "FB": "RB", "WR": "WR", "TE": "TE", "OT": "OT", "OL": "IOL", "OG": "IOL", "G": "IOL", "C": "IOL", "T": "OT",
       "DE": "EDGE", "EDGE": "EDGE", "OLB": "LB", "DT": "DL", "NT": "DL", "DL": "DL", "LB": "LB", "ILB": "LB", "MLB": "LB",
       "CB": "CB", "DB": "CB", "S": "S", "SAF": "S", "FS": "S", "SS": "S"}


def _z(vals):
    v = [x for x in vals if x is not None]
    if len(v) < 3: return lambda x: 0.0
    m = sum(v) / len(v); s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v)) or 1
    return lambda x: 0.0 if x is None else max(-3, min(3, (x - m) / s))


import re as _re, unicodedata as _ud
norm = lambda n: _re.sub(r"[^a-z]", "", _ud.normalize("NFD", str(n or "").lower()).encode("ascii", "ignore").decode().replace(" jr", "").replace(" iii", "").replace(" ii", ""))
_REC = {}


def reclutas(desde, hasta):
    """{id: (estrellas, rating, clase, escuela)} y {nombre: [...]} de las clases de prepa desde..hasta (caché larga)."""
    rec, porn = {}, defaultdict(list)
    for y in range(desde, hasta + 1):
        if y not in _REC: _REC[y] = get("/recruiting/players", 24 * 300, year=y, classification="HighSchool") or []
        for r in _REC[y]:
            t = (g(r, "stars") or 0, g(r, "rating") or 0, y, g(r, "committedTo", "committed_to"))
            rec[str(g(r, "id"))] = t; porn[norm(g(r, "name"))].append(t)
    return rec, porn


def candidatos(season, fbs=None, ttl=20, actual=True, todos_=False):
    """Jugadores con sus rasgos: pr (producción z por posición), tal (z de recluta), cp (1 si no es Power 4), ypc (OL: z de la
    carrera de su equipo), elegibilidad. Mismo cálculo para la temporada actual y para las pasadas (con las que se calibra)."""
    stats = [x for x in (get("/stats/player/season", ttl, year=season) or []) if not fbs or g(x, "team") in fbs]
    ppa = get("/ppa/players/season", ttl, year=season) or []
    roster = get("/roster", 24 * (7 if actual else 300), year=season, classification="fbs") or []
    tst = get("/stats/season", ttl if actual else 24 * 300, year=season) or []
    rec, porn = reclutas(season - 6, season - 1)
    J = {}
    for x in stats:
        pid = str(g(x, "playerId", "player_id"))
        j = J.setdefault(pid, dict(n=g(x, "player"), t=g(x, "team"), conf=g(x, "conference"), pos=g(x, "position"), s={}))
        try: j["s"][f"{g(x, 'category')}.{g(x, 'statType', 'stat_type')}"] = float(g(x, "stat"))
        except Exception: pass
    for x in ppa:
        pid = str(g(x, "id"))
        if pid in J: J[pid]["ppa"] = g(g(x, "averagePPA", "average_ppa") or {}, "all")
    R = {}
    for x in roster:
        R[str(g(x, "id"))] = dict(y=g(x, "year"), pos=g(x, "position"), t=g(x, "team"), n=f"{g(x, 'firstName', 'first_name', d='')} {g(x, 'lastName', 'last_name', d='')}".strip(),
                                  h=g(x, "height"), w=g(x, "weight"), rid=[str(i) for i in (g(x, "recruitIds", "recruit_ids") or [])])
    conf_eq = {}
    TY = defaultdict(dict)
    for x in tst:
        try: TY[g(x, "team")][g(x, "statName", "stat_name")] = float(g(x, "statValue", "stat_value"))
        except Exception: pass
        conf_eq[g(x, "team")] = g(x, "conference")
    ypc = {t: v.get("rushingYards", 0) / v["rushingAttempts"] for t, v in TY.items() if v.get("rushingAttempts")}
    zy = _z(list(ypc.values()))
    def recluta(pid):
        for i in (R.get(pid) or {}).get("rid", []):
            if i in rec: return rec[i]
        j = J.get(pid) or R.get(pid) or {}
        L = porn.get(norm(j.get("n")), [])
        if len(L) > 1: L = [x for x in L if x[3] == j.get("t")] or L[:1]
        return L[0] if L else None
    _ys = defaultdict(int)
    for r in R.values(): _ys[r.get("y")] += 1
    usa_y = sum(v for k, v in _ys.items() if isinstance(k, int) and k >= 3) > 0.15 * max(1, len(R))   # el año del roster a veces viene todo en 1
    def elegible(pid):
        r = R.get(pid)
        if usa_y and r and r.get("y"): return r["y"] >= 3
        rc = recluta(pid)
        if rc: return rc[2] <= season - 2      # clase de prepa de hace 3+ años al draft
        return None
    S = lambda j, k: j["s"].get(k)
    grupos = defaultdict(list)
    for pid, j in J.items():
        p = POS.get((j.get("pos") or (R.get(pid) or {}).get("pos") or "").upper())
        if not p or (elegible(pid) is False and not todos_): continue
        if p in ("DL", "EDGE") and (S(j, "defensive.SACKS") or 0) >= 4: p = "EDGE" if p == "EDGE" or (S(j, "defensive.SACKS") or 0) >= 6 else p
        j["p"] = p; j["id"] = pid; grupos[p].append(j)
    def prod(p, L):
        if p == "QB":
            L = [j for j in L if (S(j, "passing.ATT") or 0) >= 120]
            f = [("ppa", lambda j: j.get("ppa"), .45), ("yds", lambda j: S(j, "passing.YDS"), .2),
                 ("td", lambda j: (S(j, "passing.TD") or 0) - (S(j, "passing.INT") or 0), .2), ("pct", lambda j: S(j, "passing.PCT"), .15)]
        elif p == "RB":
            L = [j for j in L if (S(j, "rushing.CAR") or 0) >= 60]
            f = [("yds", lambda j: S(j, "rushing.YDS"), .45), ("ypc", lambda j: S(j, "rushing.YPC"), .2), ("td", lambda j: S(j, "rushing.TD"), .2),
                 ("rec", lambda j: S(j, "receiving.YDS"), .15)]
        elif p in ("WR", "TE"):
            L = [j for j in L if (S(j, "receiving.REC") or 0) >= (20 if p == "WR" else 12)]
            f = [("yds", lambda j: S(j, "receiving.YDS"), .5), ("ypr", lambda j: S(j, "receiving.YPR"), .2), ("td", lambda j: S(j, "receiving.TD"), .3)]
        elif p in ("EDGE", "DL"):
            L = [j for j in L if (S(j, "defensive.TOT") or 0) >= 12]
            f = [("sk", lambda j: S(j, "defensive.SACKS"), .45), ("tfl", lambda j: S(j, "defensive.TFL"), .35), ("hur", lambda j: S(j, "defensive.QB HUR"), .2)]
        elif p == "LB":
            L = [j for j in L if (S(j, "defensive.TOT") or 0) >= 25]
            f = [("tot", lambda j: S(j, "defensive.TOT"), .4), ("tfl", lambda j: S(j, "defensive.TFL"), .3), ("sk", lambda j: S(j, "defensive.SACKS"), .15),
                 ("pd", lambda j: S(j, "defensive.PD"), .15)]
        elif p in ("CB", "S"):
            L = [j for j in L if (S(j, "defensive.TOT") or 0) >= 12]
            f = [("pd", lambda j: S(j, "defensive.PD"), .45), ("int", lambda j: S(j, "interceptions.INT"), .35), ("tot", lambda j: S(j, "defensive.TOT"), .2)]
        else:
            return []
        zs = {k: _z([fn(j) for j in L]) for k, fn, _ in f}
        for j in L: j["pr"] = sum(w * zs[k](fn(j)) for k, fn, w in f)
        return L
    todos = []
    for p, L in grupos.items(): todos += prod(p, L)
    zr = _z([r[1] for r in rec.values() if r[2] <= season - 2])
    potencia = lambda t, c: 0 if (c in POWER or t == "Notre Dame") else 1
    for j in todos:
        rc = recluta(j["id"]); r = R.get(j["id"]) or {}
        j.update(st=rc[0] if rc else 0, tal=zr(rc[1]) if rc else -0.8, cp=potencia(j["t"], j.get("conf")), ypc=0.0, ol=0,
                 el=elegible(j["id"]), h=r.get("h"), w=r.get("w"), cl=(r.get("y") if usa_y else None) or (min(4, season - rc[2] + 1) if rc else None))
    # línea ofensiva: sin estadísticas individuales → su reclutamiento y qué tan bien corre su equipo
    for pid, r in R.items():
        p = POS.get((r.get("pos") or "").upper())
        if p not in ("OT", "IOL") or elegible(pid) is not True: continue
        rc = recluta(pid)
        if not rc or rc[0] < 3: continue
        if p == "IOL" and (r.get("h") or 0) >= 77: p = "OT"     # "OL" genérico: los de 1.96 m o más casi siempre juegan de tackle
        todos.append(dict(id=pid, n=r["n"], t=r["t"], conf=conf_eq.get(r["t"]), p=p, st=rc[0], s={}, pr=0.0, tal=zr(rc[1]), cp=potencia(r["t"], conf_eq.get(r["t"])),
                          ypc=zy(ypc.get(r["t"])), ol=1, el=True, h=r.get("h"), w=r.get("w"), cl=min(4, season - rc[2] + 1)))
    return todos


SLOTS = {}


def pos_draft(t):
    t = (t or "").lower()
    if "quarter" in t: return "QB"
    if "running" in t or "fullback" in t: return "RB"
    if "wide" in t: return "WR"
    if "tight" in t: return "TE"
    if "tackle" in t and "defensive" not in t: return "OT"
    if "guard" in t or "center" in t or "offensive line" in t: return "IOL"
    if "defensive end" in t or "edge" in t or "outside linebacker" in t: return "EDGE"
    if "defensive tackle" in t or "nose" in t or "defensive line" in t: return "DL"
    if "linebacker" in t: return "LB"
    if "corner" in t: return "CB"
    if "safety" in t: return "S"
    return None


RASGOS = ["pr", "tal", "cp", "ypc"]
PL = list(VALOR)


def _x(j):
    """Producción con peso propio por posición (no vale igual un buen RB que un buen EDGE), recluta, conferencia, línea ofensiva."""
    return ([j["pr"] if j["p"] == p else 0.0 for p in PL] + [j["tal"], j["cp"], j["ypc"] if j.get("ol") else 0.0, j["tal"] if j.get("ol") else 0.0]
            + [1.0 if j["p"] == p else 0.0 for p in PL])


def heur(j):
    return j["pr"] + 0.35 * j["tal"] - 0.6 * j["cp"] + VALOR.get(j["p"], 0) + (0.5 + 0.3 * j["ypc"] if j.get("ol") else 0)


def calibra(season, fbs):
    """Aprende cuánto pesa cada cosa con los drafts de verdad: temporadas season-3..season-1 contra los drafts siguientes.
    Valor de la selección: 1 para el pick 1, 0 para el 262 (escala logarítmica); los no escogidos valen 0. Se prueba
    entrenando sin el último año; si la fórmula a mano sale mejor en esa prueba, se queda la fórmula a mano."""
    import numpy as np
    filas, ys, hist, años, hs, ps = [], [], [], [], [], []
    global SLOTS
    porY = defaultdict(lambda: defaultdict(list))
    for Y in (season - 3, season - 2, season - 1):
        dp = get("/draft/picks", 24 * 300, year=Y + 1) or []
        if not dp: continue
        for x in dp:
            pp = pos_draft(g(x, "position")); ov = g(x, "overall")
            if pp and ov: porY[Y][pp].append(ov)
        D = {}
        for x in dp:
            D[(norm(g(x, "name")), g(x, "collegeTeam", "college_team"))] = x
            D.setdefault((norm(g(x, "name")), None), x)
        C = candidatos(Y, fbs, ttl=24 * 300, actual=False)
        for j in C:
            x = D.get((norm(j["n"]), j["t"])) or D.get((norm(j["n"]), None))
            ov = g(x, "overall") if x else None
            v = max(0.0, 1 - math.log(ov) / math.log(262)) if ov else 0.0
            filas.append(_x(j)); ys.append(v); años.append(Y); hs.append(heur(j)); ps.append(j["p"])
            if ov: hist.append(dict(n=g(x, "name"), p=j["p"], t=g(x, "collegeTeam", "college_team"), y=Y + 1, o=ov, eq=g(x, "nflTeam", "nfl_team"),
                                    pr=j["pr"], tal=j["tal"], h=g(x, "height") or j.get("h"), w=g(x, "weight") or j.get("w")))
    # lugar promedio del k-ésimo jugador de cada posición en los drafts (p. ej. el 3er OT suele irse en el pick ~20)
    SLOTS = {}
    for pp in VALOR:
        L = [sorted(porY[Y][pp]) for Y in porY if porY[Y][pp]]
        if not L: continue
        n = max(len(l) for l in L)
        SLOTS[pp] = [sum(l[k] if k < len(l) else 262 for l in L) / len(L) for k in range(n)]
    print("Colegial: lugares históricos por posición", {pp: [round(v) for v in L[:4]] + [len(L)] for pp, L in SLOTS.items()})
    if len(filas) < 300: return None, [], ""
    X, y, A, H = np.array(filas), np.array(ys), np.array(años), np.array(hs)
    def ajusta(m, lam):
        return np.linalg.solve(X[m].T @ X[m] + np.eye(X.shape[1]) * lam, X[m].T @ y[m])
    ult = A.max(); te = A == ult; yy = y[te]; c1 = 1 - math.log(32) / math.log(262)
    def mide(pred):
        o = np.argsort(-pred); return int(sum(1 for i in o[:32] if yy[i] >= c1)), int(sum(1 for i in o[:100] if yy[i] > 0))
    res = {"a mano": (mide(H[te]), None)}
    for lam in (0.1, 1.0, 10.0):
        res[f"aprendida λ={lam}"] = (mide(X[te] @ ajusta(A != ult, lam)), lam)
    # con cupos por posición (aprendidos sin el año de prueba)
    def slots_de(años_ok):
        S2 = {}
        for pp in VALOR:
            L = [sorted(porY[Y][pp]) for Y in porY if Y in años_ok and porY[Y][pp]]
            if L: S2[pp] = [sum(l[k] if k < len(l) else 262 for l in L) / len(L) for k in range(max(len(l) for l in L))]
        return S2
    def con_cupos(pred, S2):
        P = [ps[i] for i in range(len(ps)) if te[i]]; o = np.argsort(-pred); kk = defaultdict(int); esp = np.zeros(len(pred))
        for i in o:
            L = S2.get(P[i]) or []; n = kk[P[i]]; kk[P[i]] += 1
            esp[i] = L[n] if n < len(L) else (L[-1] if L else 262) + 25 * (n - len(L) + 1)
        return -esp
    S2 = slots_de({Y for Y in porY if Y != ult})
    for lam in (0.1, 1.0):
        res[f"aprendida con cupos λ={lam}"] = (mide(con_cupos(X[te] @ ajusta(A != ult, lam), S2)), ("c", lam))
    res["a mano con cupos"] = (mide(con_cupos(H[te], S2)), ("c", None))
    for k, ((a, b), _) in res.items(): print(f"Colegial: prueba con el draft {ult + 1} · {k}: top 32 → {a} de 1ª ronda; top 100 → {b} escogidos")
    # siempre con cupos (el mock necesita la mezcla de posiciones de un draft real); entre esas, la que mejor salió
    cands = {k: v for k, v in res.items() if isinstance(v[1], tuple)}
    mejor = max(cands, key=lambda k: (cands[k][0][1] + 2 * cands[k][0][0]))
    (r1, dr), (_, lam) = cands[mejor]
    nota = f"probado con el draft {ult + 1}: de su top 32, {r1} fueron de 1ª ronda; de su top 100, {dr} fueron escogidos"
    if lam is None:
        print("Colegial: se queda la fórmula a mano (con cupos)"); return None, hist, nota
    w = ajusta(np.ones(len(y), bool), lam)
    print("Colegial: se usa la fórmula aprendida", mejor, "con", len(y), "jugadores y", len(hist), "drafteados")
    return w, hist, nota


def comp(j, hist):
    """El drafteado más parecido de su posición (producción, recluta, estatura y peso)."""
    best, bd = None, 1e9
    for h in hist:
        if h["p"] != j["p"]: continue
        d = (j["pr"] - h["pr"]) ** 2 + 0.6 * (j["tal"] - h["tal"]) ** 2
        if j.get("h") and h.get("h"): d += ((j["h"] - h["h"]) / 2) ** 2
        if j.get("w") and h.get("w"): d += ((j["w"] - h["w"]) / 15) ** 2
        if d < bd: bd, best = d, h
    return [best["n"], best["t"], best["y"], best["o"], best["eq"]] if best else None


def tablero(season, fbs=None):
    todos = candidatos(season, fbs)
    w, hist, nota = None, [], ""
    try: w, hist, nota = calibra(season, fbs)
    except Exception as e: print("Colegial: calibración no se pudo:", repr(e)[:200])
    for j in todos:
        if w is not None: j["sc"] = float(sum(a * b for a, b in zip(_x(j), w)))
        else: j["sc"] = heur(j)
        if j.get("el") is None: j["sc"] -= 0.05 if w is not None else 0.4
    todos.sort(key=lambda j: -j["sc"])
    if SLOTS:
        # Cada posición tiene su "cupo" histórico: el mejor OT según la puntuación toma el lugar donde suele irse el 1er OT,
        # el 2º el del 2º OT, etc. Así el tablero trae la mezcla de posiciones de un draft de verdad.
        k = defaultdict(int)
        for j in todos:
            L = SLOTS.get(j["p"]) or []
            i = k[j["p"]]; k[j["p"]] += 1
            j["esp"] = L[i] if i < len(L) else (L[-1] if L else 262) + 25 * (i - len(L) + 1)
        todos.sort(key=lambda j: (j["esp"], -j["sc"]))
    print(f"Colegial: {len(todos)} candidatos ({sum(1 for j in todos if j.get('ol'))} de línea ofensiva)")
    out, porpos = [], defaultdict(int)
    for k, j in enumerate(todos[:200], 1):
        porpos[j["p"]] += 1
        s = {kk: round(v, 1) for kk, v in (j.get("s") or {}).items() if kk.split(".")[0] in ("passing", "rushing", "receiving", "defensive", "interceptions")}
        out.append(dict(id=j["id"], n=j["n"], p=j["p"], t=j["t"], c=j.get("cl"), st=j.get("st") or 0, h=j.get("h"), w=j.get("w"),
                        rp=porpos[j["p"]], sc=round(j["sc"], 3), x=_linea(j), ol=j.get("ol", 0), r=min(8, int((j.get("esp") or k) - 1) // 32 + 1),
                        s=s, cmp=comp(j, hist) if hist else None))
    return out, nota


def _linea(j):
    s = j.get("s") or {}; p = j["p"]; f = lambda k: int(s.get(k) or 0)
    if p == "QB": return f"{f('passing.YDS'):,} yds · {f('passing.TD')} TD · {f('passing.INT')} INT".replace(",", ",")
    if p == "RB": return f"{f('rushing.YDS'):,} yds · {s.get('rushing.YPC') or 0:.1f} por acarreo · {f('rushing.TD')} TD"
    if p in ("WR", "TE"): return f"{f('receiving.REC')} rec · {f('receiving.YDS'):,} yds · {f('receiving.TD')} TD"
    if p in ("EDGE", "DL"): return f"{round((s.get('defensive.SACKS') or 0)*2)/2:g} capturas · {round((s.get('defensive.TFL') or 0)*2)/2:g} TFL · {f('defensive.QB HUR')} presiones"
    if p == "LB": return f"{f('defensive.TOT')} tacleadas · {round((s.get('defensive.TFL') or 0)*2)/2:g} TFL · {round((s.get('defensive.SACKS') or 0)*2)/2:g} capturas"
    if p in ("CB", "S"): return f"{f('defensive.PD')} pases defendidos · {f('interceptions.INT')} INT · {f('defensive.TOT')} tacleadas"
    if j.get("ol"): return f"{j.get('st', 0)} estrellas como recluta"
    return ""


# ---------------------------------------------------------------- Playoff de 12 proyectado
# Reglas 2026-27: campeones de ACC, Big Ten, Big 12 y SEC; el mejor de American, CUSA, MAC, Mountain West, Pac-12 o Sun Belt;
# Notre Dame si queda entre los 12; el resto por ranking. Los 4 mejores rankeados descansan la 1ª ronda; sin reacomodo.
G6 = {"American Athletic", "American", "Conference USA", "Mid-American", "Mountain West", "Pac-12", "Sun Belt"}


def playoff(L, fuente):
    if len(L) < 12: return None
    auto = {}
    for c in ("SEC", "Big Ten", "Big 12", "ACC"):
        t = next((r for r in L if r[2] == c), None)
        if t: auto[t[1]] = f"Campeón proyectado de la {c}" if c != "SEC" else "Campeón proyectado de la SEC"
    t = next((r for r in L if r[2] in G6), None)
    if t: auto[t[1]] = "Mejor de las conferencias chicas"
    nd = next((r for r in L if r[1] == "Notre Dame" and r[0] <= 12), None)
    if nd: auto[nd[1]] = "Notre Dame entre los 12"
    campo = [r for r in L if r[1] in auto]
    for r in L:
        if len(campo) >= 12: break
        if r[1] not in auto: campo.append(r)
    campo = sorted(campo, key=lambda r: r[0])[:12]
    return dict(f=fuente, s=[[i + 1, r[1], r[0], auto.get(r[1], "Invitado por ranking"), r[2]] for i, r in enumerate(campo)])


# ---------------------------------------------------------------- ficha de equipo (23 nov 2026)
def fichas(season, teams, RK):
    """docs/datos/cfb_eq.json: de cada equipo FBS, récord, partidos de la temporada y su ranking semana a semana."""
    G = (get("/games", 6, year=season, seasonType="regular") or []) + (get("/games", 6, year=season, seasonType="postseason") or [])
    E = {}
    for x in G:
        h, a = g(x, "homeTeam", "home_team"), g(x, "awayTeam", "away_team")
        hp, ap = g(x, "homePoints", "home_points"), g(x, "awayPoints", "away_points"); ok = 1 if g(x, "completed") else 0
        neu = 1 if g(x, "neutralSite", "neutral_site") else 0
        for t, o, loc, pf, pc in ((h, a, 2 if neu else 1, hp, ap), (a, h, 2 if neu else 0, ap, hp)):
            if t not in teams: continue
            E.setdefault(t, {"g": []})["g"].append([g(x, "week"), o, loc, pf, pc, ok, g(x, "startDate", "start_date"), (g(x, "notes") or "")[:40],
                                                   1 if g(x, "seasonType", "season_type") == "postseason" else 0])
    for t, e in E.items():
        e["g"].sort(key=lambda r: (r[8], r[6] or ""))
        gan = sum(1 for r in e["g"] if r[5] and r[3] is not None and r[4] is not None and r[3] > r[4])
        per = sum(1 for r in e["g"] if r[5] and r[3] is not None and r[4] is not None and r[3] < r[4])
        e["r"] = f"{gan}-{per}"; e["c"] = g(teams[t], "conference") or ""
    for sem in RK or []:
        if g(sem, "seasonType", "season_type") != "regular": continue
        w = g(sem, "week")
        for pol in g(sem, "polls") or []:
            nom = g(pol, "poll") or ""; k = 1 if nom.startswith("AP") else 2 if "Playoff" in nom else 0
            if not k: continue
            for r in g(pol, "ranks") or []:
                t = g(r, "school")
                if t in E:
                    rk = E[t].setdefault("rk", {}); rk.setdefault(str(w), [None, None])[k - 1] = g(r, "rank")
    T = {s_: [g(t, "abbreviation") or s_[:4].upper(), g(t, "color") or "#555555", (g(t, "logos") or [""])[0], g(t, "conference") or "", g(t, "mascot") or ""] for s_, t in teams.items()}
    return {"s": season, "eq": E, "teams": T}


# ---------------------------------------------------------------- carrera al Heisman (23 nov 2026)
def heisman(season, fbs, fich):
    """Índice de La Pizarra: producción en su posición (z), récord de su equipo y su ranking. QB pesa más (así vota la gente)."""
    C = candidatos(season, fbs, todos_=True)
    rec = {}
    for t, e in (fich or {}).get("eq", {}).items():
        try: w_, l_ = map(int, e.get("r", "0-0").split("-")); rec[t] = w_ / max(1, w_ + l_)
        except Exception: pass
    rk_ult = {}
    for t, e in (fich or {}).get("eq", {}).items():
        R = e.get("rk") or {}
        if R:
            w_ = max(R, key=int); rk_ult[t] = R[w_][1] or R[w_][0]
    L = []
    for j in C:
        if j["p"] not in ("QB", "RB", "WR", "TE") or j.get("ol"): continue
        r = rk_ult.get(j["t"])
        hz = j["pr"] + {"QB": 0.6, "RB": 0.1, "WR": 0.0, "TE": -0.3}[j["p"]] + 1.6 * (rec.get(j["t"], 0.5) - 0.5) + (0.6 if r and r <= 10 else 0.3 if r else 0) - 0.5 * j["cp"]
        L.append((hz, j))
    L.sort(key=lambda x: -x[0])
    return [dict(n=j["n"], p=j["p"], t=j["t"], x=_linea(j), hz=round(hz, 2), rec=(fich or {}).get("eq", {}).get(j["t"], {}).get("r", ""), rk=rk_ult.get(j["t"]))
            for hz, j in L[:12]]


# ---------------------------------------------------------------- todo junto
STATS_BX = {"totalYards": "yd", "netPassingYards": "py", "rushingYards": "ry", "turnovers": "to", "firstDowns": "fd", "thirdDownEff": "d3",
            "possessionTime": "pos", "totalPenaltiesYards": "pen", "sacks": "sk", "completionAttempts": "ca", "yardsPerPass": "ypp", "yardsPerRushAttempt": "ypr"}
LIDER = {"passing": "Pase", "rushing": "Carrera", "receiving": "Recepción"}


def detalle(season, w, st, games):
    """Agrega a cada partido: ln {sp: puntos de ventaja del local (positivo = favorito el local), ou, pv: casa}, wp (prob. del local antes
    del partido), tv, bx {h:{...}, a:{...}} (estadísticas de equipo) y ld {h:[[tipo, jugador, texto]], a:[...]} (líderes)."""
    por = {}
    for x in games: por.setdefault(x["w"], []).append(x)
    for ww, L in por.items():
        ttl = 3 if ww == w else 24
        idx = {x["id"]: x for x in L}
        for r in get("/lines", ttl, year=season, week=ww, seasonType=st) or []:
            x = idx.get(g(r, "id"))
            if not x: continue
            ls = g(r, "lines") or []
            ln = next((l for l in ls if str(g(l, "provider")).lower() in ("consensus", "draftkings", "espn bet", "bovada")), ls[0] if ls else None)
            if ln and g(ln, "spread") is not None:
                try: x["ln"] = dict(sp=-float(g(ln, "spread")), ou=float(g(ln, "overUnder", "over_under")) if g(ln, "overUnder", "over_under") is not None else None, pv=g(ln, "provider"))
                except Exception: pass
        for r in get("/metrics/wp/pregame", ttl, year=season, week=ww, seasonType=st) or []:
            x = idx.get(g(r, "gameId", "game_id"))
            if x and g(r, "homeWinProbability", "home_win_probability") is not None: x["wp"] = round(float(g(r, "homeWinProbability", "home_win_probability")), 3)
        for r in get("/games/media", 24, year=season, week=ww, seasonType=st) or []:
            x = idx.get(g(r, "id"))
            if x and g(r, "outlet") and str(g(r, "mediaType", "media_type")).lower() in ("tv", "web", "") and not x.get("tv"): x["tv"] = g(r, "outlet")
        if not any(x.get("ok") for x in L): continue
        for r in get("/games/teams", ttl, year=season, week=ww, seasonType=st, classification="fbs") or []:
            x = idx.get(g(r, "id"))
            if not x: continue
            bx = {}
            for t in g(r, "teams") or []:
                lado = "h" if (g(t, "homeAway", "home_away") == "home") else "a"
                d = {}
                for s_ in g(t, "stats") or []:
                    k = STATS_BX.get(g(s_, "category"))
                    if k: d[k] = g(s_, "stat")
                bx[lado] = d
            if bx: x["bx"] = bx
        for r in get("/games/players", ttl, year=season, week=ww, seasonType=st, classification="fbs") or []:
            x = idx.get(g(r, "id"))
            if not x: continue
            ld = {}
            for t in g(r, "teams") or []:
                lado = "h" if (g(t, "homeAway", "home_away") == "home") else "a"; out = []
                for c in g(t, "categories") or []:
                    nom = g(c, "name")
                    if nom not in LIDER: continue
                    tipos = {g(tp, "name"): {g(a_, "name"): g(a_, "stat") for a_ in g(tp, "athletes") or []} for tp in g(c, "types") or []}
                    yd = tipos.get("YDS") or {}
                    if not yd: continue
                    try: top = max(yd, key=lambda n: float(yd[n] or 0))
                    except Exception: continue
                    ex = []
                    if nom == "passing" and tipos.get("C/ATT", {}).get(top): ex.append(f"{tipos['C/ATT'][top]}")
                    if nom == "rushing" and tipos.get("CAR", {}).get(top): ex.append(f"{tipos['CAR'][top]} acarreos")
                    if nom == "receiving" and tipos.get("REC", {}).get(top): ex.append(f"{tipos['REC'][top]} recepciones")
                    ex.append(f"{yd[top]} yardas")
                    td = (tipos.get("TD") or {}).get(top)
                    if td and str(td) != "0": ex.append(f"{td} TD")
                    if nom == "passing" and (tipos.get("INT") or {}).get(top) not in (None, "0", 0): ex.append(f"{tipos['INT'][top]} INT")
                    out.append([LIDER[nom], top, ", ".join(ex)])
                ld[lado] = out
            if ld: x["ld"] = ld
    n = lambda k: sum(1 for x in games if x.get(k))
    print(f"Colegial: detalle → línea {n('ln')}, probabilidad {n('wp')}, TV {n('tv')}, estadísticas {n('bx')}, líderes {n('ld')}, marcador por cuarto {n('ls')}")


def arma(season, nfl):
    """nfl = {rec: {equipo: [w, l, t]}, sos: {equipo: float}, nec: {equipo: [posiciones]}}"""
    if not KEY and not os.path.isdir(CACHE):
        print("Colegial: falta el secreto CFBD_API_KEY; no se arma nada"); return None
    w, st = semana(season)
    teams = {g(t, "school"): t for t in (get("/teams/fbs", 24 * 30, year=season) or [])}
    usados = set()
    # rankings
    ap, cfp, apv, cfpv = [], [], [], []
    RK = get("/rankings", 6, year=season, seasonType=st) or get("/rankings", 6, year=season) or []
    if RK:
        # cada encuesta con su semana más reciente (el ranking del comité sale el martes; la AP del domingo puede ir una semana adelante)
        for ult in sorted(RK, key=lambda x: (1 if g(x, "seasonType", "season_type") == "postseason" else 0, g(x, "week") or 0)):
          for pol in g(ult, "polls") or []:
            nom = g(pol, "poll") or ""
            L = [[g(r, "rank"), g(r, "school"), g(r, "conference"), g(r, "firstPlaceVotes", "first_place_votes") or 0] for r in sorted(g(pol, "ranks") or [], key=lambda r: g(r, "rank") or 99)]
            if nom.startswith("AP"): apv, ap = ap, L[:25]
            elif "Playoff" in nom: cfpv, cfp = cfp, L[:25]
    # lugar de la semana anterior en la misma encuesta (5º campo; None = no estaba)
    for L, P in ((ap, apv), (cfp, cfpv)):
        pv = {r[1]: r[0] for r in P}
        for r in L: r.append(pv.get(r[1]) if P else -1)
    rank = {r[1]: r[0] for r in (cfp or ap)}
    cfp12 = playoff(cfp or ap, "cfp" if cfp else "ap")
    try:
        FICH = fichas(season, teams, RK)
        os.makedirs("docs/datos", exist_ok=True)
        json.dump(FICH, open("docs/datos/cfb_eq.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    except Exception as e: FICH = None; print("Colegial: fichas de equipo no se pudieron:", repr(e)[:200])
    try: HZ = heisman(season, set(teams), FICH)
    except Exception as e: HZ = []; print("Colegial: Heisman no se pudo:", repr(e)[:200])
    # partidos: esta semana y la anterior, solo con algún equipo FBS
    games = []
    for ww, ttl in ((w, 3), (w - 1, 24)):
        if ww < 1: continue
        for x in get("/games", ttl, year=season, week=ww, seasonType=st) or []:
            h, a = g(x, "homeTeam", "home_team"), g(x, "awayTeam", "away_team")
            if "fbs" not in (str(g(x, "homeClassification", "home_classification")) + str(g(x, "awayClassification", "away_classification"))).lower(): continue
            if not (rank.get(h) or rank.get(a)) and not (g(x, "homeConference", "home_conference") in POWER and g(x, "awayConference", "away_conference") in POWER): continue
            G1 = dict(id=g(x, "id"), w=ww, ko=g(x, "startDate", "start_date"), tbd=1 if g(x, "startTimeTBD", "start_time_tbd") else 0,
                              h=h, a=a, hp=g(x, "homePoints", "home_points"), ap=g(x, "awayPoints", "away_points"), ok=1 if g(x, "completed") else 0,
                              hr=rank.get(h), ar=rank.get(a), n=g(x, "notes") or "")
            v = g(x, "venue"); ls = [g(x, "homeLineScores", "home_line_scores"), g(x, "awayLineScores", "away_line_scores")]
            if v: G1["v"] = v
            if g(x, "neutralSite", "neutral_site"): G1["neu"] = 1
            if g(x, "conferenceGame", "conference_game"): G1["cg"] = 1
            if all(isinstance(l, list) and l for l in ls): G1["ls"] = ls
            games.append(G1)
            usados |= {h, a}
    games.sort(key=lambda x: (x["w"], x["ko"] or ""))
    # Detalle de los partidos (23 nov 2026): línea de Las Vegas, probabilidad, canal, estadísticas y líderes. Una consulta por semana
    # por cada dato (semana actual cada 3 h, la anterior cada 24 h).
    try: detalle(season, w, st, games)
    except Exception as e: print("Colegial: detalle de partidos no se pudo:", repr(e)[:200])
    pros, nota = [], ""
    try: pros, nota = tablero(season, set(teams))
    except Exception as e: print("Colegial: tablero de prospectos no se pudo:", repr(e)[:200])
    usados |= {r[1] for r in ap + cfp} | {p["t"] for p in pros}
    T = {}
    for s in usados:
        t = teams.get(s)
        if not t: continue
        logos = g(t, "logos") or []
        T[s] = [g(t, "abbreviation") or s[:4].upper(), g(t, "color") or "#555555", logos[0] if logos else "", g(t, "conference") or ""]
    # orden del draft si la temporada terminara hoy: peor récord primero; empate → calendario más fácil primero
    order = []
    if nfl and nfl.get("rec"):
        pct = lambda r: (r[0] + .5 * r[2]) / max(1, sum(r))
        eqs = sorted(nfl["rec"], key=lambda t: (pct(nfl["rec"][t]), nfl.get("sos", {}).get(t, .5)))
        for i, t in enumerate(eqs, 1):
            r = nfl["rec"][t]; order.append([i, t, f"{r[0]}-{r[1]}" + (f"-{r[2]}" if r[2] else ""), (nfl.get("nec") or {}).get(t, [])])
    lim = sum(v for k, v in (_uso()[1]).items() if k == _uso()[2])
    print(f"Colegial: semana {w} ({st}), {len(games)} partidos, AP {len(ap)}, CFP {len(cfp)}, {len(pros)} prospectos; consultas este mes: {lim}/{TOPE_MES}")
    rec = {t: e.get("r") for t, e in ((FICH or {}).get("eq") or {}).items() if t in T and e.get("r")}
    return dict(al=datetime.now(timezone.utc).isoformat()[:16], season=season, week=w, st=st, ap=ap, cfp=cfp, games=games, teams=T, pros=pros, rec=rec,
                draft=dict(y=season + 1, order=order, nota=nota), cfp12=cfp12, heisman=HZ)
