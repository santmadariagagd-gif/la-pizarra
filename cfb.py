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
TOPE_MES = 900
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
        with urllib.request.urlopen(r, timeout=40) as x: d = json.loads(x.read().decode())
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


def tablero(season, fbs=None):
    stats = [x for x in (get("/stats/player/season", 20, year=season) or []) if not fbs or g(x, "team") in fbs]   # solo FBS
    ppa = get("/ppa/players/season", 20, year=season) or []
    roster = get("/roster", 24 * 7, year=season, classification="fbs") or []
    rec = {}
    import re as _re, unicodedata as _ud
    norm = lambda n: _re.sub(r"[^a-z]", "", _ud.normalize("NFD", str(n or "").lower()).encode("ascii", "ignore").decode().replace(" jr", "").replace(" iii", "").replace(" ii", ""))
    porn = defaultdict(list)   # nombre → reclutas (si no hay roster, se cruzan por nombre)
    for y in (season - 5, season - 4, season - 3, season - 2, season - 1):
        for r in get("/recruiting/players", 24 * 300, year=y, classification="HighSchool") or []:
            t = (g(r, "stars") or 0, g(r, "rating") or 0, y, g(r, "committedTo", "committed_to"))
            rec[str(g(r, "id"))] = t; porn[norm(g(r, "name"))].append(t)
    # jugadores: id → {n, t, conf, pos, s{}}
    J = {}
    for x in stats:
        pid = str(g(x, "playerId", "player_id"))
        j = J.setdefault(pid, dict(n=g(x, "player"), t=g(x, "team"), conf=g(x, "conference"), pos=g(x, "position"), s={}))
        try: j["s"][f"{g(x, 'category')}.{g(x, 'statType', 'stat_type')}"] = float(g(x, "stat"))
        except Exception: pass
    for x in ppa:
        pid = str(g(x, "id"))
        if pid in J:
            a = g(x, "averagePPA", "average_ppa") or {}
            J[pid]["ppa"] = g(a, "all"); J[pid]["plays"] = g(x, "countablePlays", "countable_plays") or 0
    R = {}
    for x in roster:
        pid = str(g(x, "id"))
        R[pid] = dict(y=g(x, "year"), pos=g(x, "position"), t=g(x, "team"), n=f"{g(x, 'firstName', 'first_name', d='')} {g(x, 'lastName', 'last_name', d='')}".strip(),
                      h=g(x, "height"), w=g(x, "weight"), rid=[str(i) for i in (g(x, "recruitIds", "recruit_ids") or [])])
    # quién puede ir al draft: 3er año o más (con roster) o reclutado hace 3+ años
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
    print("Colegial: años en el roster", dict(sorted(((str(k), v) for k, v in _ys.items()))), "→", "se usa" if usa_y else "no se usa; se usa el reclutamiento")
    def elegible(pid):
        r = R.get(pid)
        if usa_y and r and r.get("y"): return r["y"] >= 3
        rc = recluta(pid)
        if rc: return rc[2] <= season - 2      # clase de prepa de hace 3+ años al draft
        return None
    S = lambda j, k: j["s"].get(k)
    if os.environ.get("CFB_DEBUG", "0") == "1":
        print("Colegial (diagnóstico): stat", json.dumps(stats[:1])[:300], "| roster", json.dumps(roster[:1])[:300])
        _pc = defaultdict(int)
        for pid, j in list(J.items())[:3000]: _pc[str(j.get("pos")) + "/" + str(POS.get((j.get("pos") or "").upper())) + "/" + str(elegible(pid))] += 1
        print("Colegial (diagnóstico): pos/mapeo/elegible", sorted(_pc.items(), key=lambda x: -x[1])[:15])
        print("Colegial (diagnóstico): tipos de estadística", sorted({k for j in list(J.values())[:400] for k in j["s"]})[:40])
    grupos = defaultdict(list)
    for pid, j in J.items():
        p = POS.get((j.get("pos") or (R.get(pid) or {}).get("pos") or "").upper())
        if not p or elegible(pid) is False: continue
        if p in ("DL", "EDGE") and (S(j, "defensive.SACKS") or 0) >= 4: p = "EDGE" if p == "EDGE" or (S(j, "defensive.SACKS") or 0) >= 6 else p
        j["p"] = p; j["id"] = pid; grupos[p].append(j)
    # índices de producción por posición (z dentro de su grupo)
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
    zr = _z([r[1] for r in rec.values()])
    for j in todos:
        rc = recluta(j["id"])
        j["st"] = rc[0] if rc else 0
        talento = zr(rc[1]) if rc else -0.6
        conf = 0 if (j.get("conf") in POWER or j.get("t") == "Notre Dame") else -0.6
        j["sc"] = j["pr"] + 0.35 * talento + conf + VALOR.get(j["p"], 0) - (0.4 if elegible(j["id"]) is None else 0)
    # línea ofensiva: no hay estadísticas individuales; entran los de 3er año o más con 4-5 estrellas, por su reclutamiento
    for pid, r in R.items():
        p = POS.get((r.get("pos") or "").upper())
        if p not in ("OT", "IOL") or elegible(pid) is not True: continue
        rc = recluta(pid)
        if not rc or rc[0] < 4: continue
        todos.append(dict(id=pid, n=r["n"], t=r["t"], conf=None, p=p, st=rc[0], s={}, sc=0.9 * zr(rc[1]) + 0.5 + VALOR[p], ol=1))
    print(f"Colegial: tablero con {len(J)} jugadores FBS, roster {len(R)}, reclutas {len(rec)}; elegibles conocidos {sum(1 for j in todos if elegible(j['id']))} de {len(todos)}")
    todos.sort(key=lambda j: -j["sc"])
    out, porpos = [], defaultdict(int)
    for j in todos[:160]:
        porpos[j["p"]] += 1
        r = R.get(j["id"]) or {}
        rc = recluta(j["id"]); cl = (r.get("y") if usa_y else None) or (min(4, season - rc[2] + 1) if rc else None)
        out.append(dict(id=j["id"], n=j["n"], p=j["p"], t=j["t"], c=cl, st=j.get("st") or 0, h=r.get("h"), w=r.get("w"),
                        rp=porpos[j["p"]], sc=round(j["sc"], 2), x=_linea(j), ol=j.get("ol", 0)))
    return out


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


# ---------------------------------------------------------------- todo junto
def arma(season, nfl):
    """nfl = {rec: {equipo: [w, l, t]}, sos: {equipo: float}, nec: {equipo: [posiciones]}}"""
    if not KEY and not os.path.isdir(CACHE):
        print("Colegial: falta el secreto CFBD_API_KEY; no se arma nada"); return None
    w, st = semana(season)
    teams = {g(t, "school"): t for t in (get("/teams/fbs", 24 * 30, year=season) or [])}
    usados = set()
    # rankings
    ap, cfp = [], []
    RK = get("/rankings", 6, year=season, seasonType=st) or get("/rankings", 6, year=season) or []
    if RK:
        ult = max(RK, key=lambda x: (1 if g(x, "seasonType", "season_type") == "postseason" else 0, g(x, "week") or 0))
        for pol in g(ult, "polls") or []:
            nom = g(pol, "poll") or ""
            L = [[g(r, "rank"), g(r, "school"), g(r, "conference"), g(r, "firstPlaceVotes", "first_place_votes") or 0] for r in sorted(g(pol, "ranks") or [], key=lambda r: g(r, "rank") or 99)]
            if nom.startswith("AP"): ap = L[:25]
            elif "Playoff" in nom: cfp = L[:25]
    rank = {r[1]: r[0] for r in (cfp or ap)}
    # partidos: esta semana y la anterior, solo con algún equipo FBS
    games = []
    for ww, ttl in ((w, 3), (w - 1, 24)):
        if ww < 1: continue
        for x in get("/games", ttl, year=season, week=ww, seasonType=st) or []:
            h, a = g(x, "homeTeam", "home_team"), g(x, "awayTeam", "away_team")
            if "fbs" not in (str(g(x, "homeClassification", "home_classification")) + str(g(x, "awayClassification", "away_classification"))).lower(): continue
            if not (rank.get(h) or rank.get(a)) and not (g(x, "homeConference", "home_conference") in POWER and g(x, "awayConference", "away_conference") in POWER): continue
            games.append(dict(id=g(x, "id"), w=ww, ko=g(x, "startDate", "start_date"), tbd=1 if g(x, "startTimeTBD", "start_time_tbd") else 0,
                              h=h, a=a, hp=g(x, "homePoints", "home_points"), ap=g(x, "awayPoints", "away_points"), ok=1 if g(x, "completed") else 0,
                              hr=rank.get(h), ar=rank.get(a), n=g(x, "notes") or ""))
            usados |= {h, a}
    games.sort(key=lambda x: (x["w"], x["ko"] or ""))
    pros = []
    try: pros = tablero(season, set(teams))
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
    return dict(al=datetime.now(timezone.utc).isoformat()[:16], season=season, week=w, st=st, ap=ap, cfp=cfp, games=games, teams=T, pros=pros,
                draft=dict(y=season + 1, order=order))
