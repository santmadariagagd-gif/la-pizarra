"""
cfb_juegos.py — Quiniela colegial y Llave del Playoff (23 nov 2026). Lo llama build_site.py después de armar cfb.json.

Quiniela: cada semana de temporada regular (hasta la de campeonatos de conferencia) se escogen hasta 10 partidos grandes
(con equipos del ranking; primero los que se juegan en sábado). Una vez escritos en Firestore no cambian.
  cfb_jornadas/{temporada}-{semana} = {s, w, primero, g: [[id, local, visita, patada]]}
  cfb_picks/{temporada}-{semana}_{uid} = {uid, jid, w, s, p: {id: "h"|"a"}, t}   (la página los escribe antes de `primero`)
Llave del Playoff: cuando ya están los partidos del College Football Playoff en College Football Data (después del 6 de
diciembre), los 12 sembrados = esos equipos ordenados por el ranking final del comité (sembrado directo, reglas 2026-27).
Si hace falta corregir a mano: cfp_bracket.json en la raíz = {"seeds": [12 escuelas en orden]}.
  cfb_jornadas/{temporada}-cfp = {s, w: "cfp", primero (1er partido de la 1ª ronda), seeds}
  cfb_picks/{temporada}-cfp_{uid} = {..., p: {r1: [4 sembrados], qf: [4], sf: [2], c: sembrado}}
  Cruces: 1ª ronda 5-12, 6-11, 7-10, 8-9; cuartos 1 vs (8/9), 4 vs (5/12), 2 vs (7/10), 3 vs (6/11); semis (1|4) y (2|3).
  Puntos: 1 por ganador de 1ª ronda, 2 de cuartos, 4 de semis, 8 el campeón (máximo 28).
Tabla: docs/datos/cfb_tabla.json = {s, al, w: {semana: {pr, g, res: {id: h|a}, fin}}, t: {hash12(uid): {a, w: {semana: aciertos}, ll}}, L}
"""
import hashlib, json, os, time
from datetime import datetime, timezone

import cfb as _c

R1 = [(5, 12), (6, 11), (7, 10), (8, 9)]
QF = [(1, 3), (4, 0), (2, 2), (3, 1)]     # (sembrado que descansa, índice del partido de 1ª ronda que le toca)
SF = [(0, 1), (2, 3)]                      # índices de cuartos que se enfrentan


def _ts(iso):
    try: return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except Exception: return 0


def _sabado(iso):
    try: return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(timezone.utc).weekday() in (5, 6)   # sábado (y la noche que ya es domingo en UTC)
    except Exception: return False


def escoge(C):
    """Hasta 10 partidos de la semana: los dos rankeados primero, luego uno rankeado; primero los del sábado."""
    now = time.time()
    G = [g for g in C.get("games", []) if g["w"] == C["week"] and not g.get("ok") and g.get("ko") and not g.get("tbd") and _ts(g["ko"]) > now + 3600 and (g.get("hr") or g.get("ar"))]
    def peso(g):
        a, b = g.get("hr") or 99, g.get("ar") or 99
        return (0 if _sabado(g["ko"]) else 1, -(2 if a < 99 and b < 99 else 1), min(a, b))
    G.sort(key=peso)
    return G[:10] if len(G) >= 4 else []


def corre(C, db, alias, aqui):
    s = C["season"]; now = time.time()
    ruta = os.path.join(aqui, "docs", "datos", "cfb_tabla.json")
    try: TB = json.load(open(ruta, encoding="utf-8"))
    except Exception: TB = {}
    if TB.get("s") != s: TB = {"s": s, "w": {}, "t": {}}
    W = TB["w"]
    # 1. jornada de esta semana
    if C.get("st") == "regular" and C["week"] <= 15:
        jid = f"{s}-{C['week']}"; ref = db.collection("cfb_jornadas").document(jid); d = ref.get()
        if not d.exists:
            E = escoge(C)
            if E:
                pr = min(_ts(g["ko"]) for g in E)
                ref.set(dict(s=s, w=C["week"], primero=datetime.fromtimestamp(pr, tz=timezone.utc), g=[[str(g["id"]), g["h"], g["a"], g["ko"]] for g in E]))
                print(f"Quiniela colegial: semana {C['week']} con {len(E)} partidos (cierra {datetime.fromtimestamp(pr, tz=timezone.utc).isoformat()[:16]})")
    for d in db.collection("cfb_jornadas").where("s", "==", s).stream():
        x = d.to_dict() or {}
        if x.get("w") == "cfp": continue
        w = str(x.get("w")); pr = x["primero"].timestamp() if hasattr(x.get("primero"), "timestamp") else 0
        W.setdefault(w, {}).update(pr=int(pr), g=x.get("g") or [])
    # resultados con lo que trae cfb.json (semana actual y anterior); lo ya calificado se queda en el archivo
    porid = {str(g["id"]): g for g in C.get("games", [])}
    for w, x in W.items():
        res = x.setdefault("res", {})
        for gid, h, a, ko in x.get("g", []):
            g = porid.get(gid)
            if g and g.get("ok") and g.get("hp") is not None and g.get("ap") is not None and g["hp"] != g["ap"]:
                res[gid] = "h" if g["hp"] > g["ap"] else "a"
        x["fin"] = len(res) >= len(x.get("g", [])) or now - x.get("pr", now) > 4 * 86400
    # 2. Llave del Playoff
    L = TB.get("L") or {}
    try:
        P = _c.get("/games", 6, year=s, seasonType="postseason") or []
        cfp = [g for g in P if "playoff" in str(_c.g(g, "notes") or "").lower() or "national championship" in str(_c.g(g, "notes") or "").lower()]
        man = os.path.join(aqui, "cfp_bracket.json")
        seeds = None
        if os.path.exists(man):
            seeds = (json.load(open(man, encoding="utf-8")) or {}).get("seeds")
        if not seeds:
            eq = set()
            for g in cfp:
                for k in ("homeTeam", "awayTeam"):
                    t = _c.g(g, k, k.replace("Team", "_team"))
                    if t and t != "TBD": eq.add(t)
            rk = {r[1]: r[0] for r in (C.get("cfp") or [])}
            if len(eq) >= 12 and all(t in rk for t in eq):
                seeds = sorted(eq, key=lambda t: rk[t])[:12]
        if seeds and len(seeds) == 12:
            r1 = [g for g in cfp if "first round" in str(_c.g(g, "notes") or "").lower()]
            pr = min([_ts(_c.g(g, "startDate", "start_date")) for g in r1] or [0])
            L = dict(seeds=seeds, pr=int(pr) if pr else L.get("pr"), r=L.get("r") or {})
            if L["pr"]:
                db.collection("cfb_jornadas").document(f"{s}-cfp").set(dict(s=s, w="cfp", primero=datetime.fromtimestamp(L["pr"], tz=timezone.utc), seeds=seeds))
            # resultados: el ganador de cada partido del Playoff, convertido a su sembrado
            sd = {t: i + 1 for i, t in enumerate(seeds)}
            gana = {}
            for g in cfp:
                if not _c.g(g, "completed"): continue
                h, a = _c.g(g, "homeTeam", "home_team"), _c.g(g, "awayTeam", "away_team")
                hp, ap = _c.g(g, "homePoints", "home_points"), _c.g(g, "awayPoints", "away_points")
                if h in sd and a in sd and hp is not None and ap is not None and hp != ap:
                    gana[frozenset((sd[h], sd[a]))] = sd[h] if hp > ap else sd[a]
            r1w = [gana.get(frozenset(p)) for p in R1]
            qfw = [gana.get(frozenset((top, r1w[i]))) if r1w[i] else None for top, i in QF]
            sfw = [gana.get(frozenset((qfw[a], qfw[b]))) if qfw[a] and qfw[b] else None for a, b in SF]
            cw = gana.get(frozenset(sfw)) if all(sfw) else None
            L["r"] = dict(r1=r1w, qf=qfw, sf=sfw, c=cw)
            print(f"Llave del Playoff: {seeds[:4]}…; cierra {L['pr']}; resultados {L['r']}")
    except Exception as e: print("Llave del Playoff:", repr(e)[:200])
    TB["L"] = L
    # 3. tabla
    T = {}
    for d in db.collection("cfb_picks").where("s", "==", s).stream():
        x = d.to_dict() or {}; uid = x.get("uid")
        if not uid: continue
        h = hashlib.sha256(uid.encode()).hexdigest()[:12]
        e = T.setdefault(h, dict(a=alias(uid), w={}))
        p = x.get("p") or {}
        if x.get("w") == "cfp":
            r = L.get("r") or {}
            if L.get("pr") and now >= L["pr"]:
                pts = sum(1 for i, v in enumerate(p.get("r1") or []) if i < 4 and v and v == (r.get("r1") or [None] * 4)[i])
                pts += 2 * sum(1 for i, v in enumerate(p.get("qf") or []) if i < 4 and v and v == (r.get("qf") or [None] * 4)[i])
                pts += 4 * sum(1 for i, v in enumerate(p.get("sf") or []) if i < 2 and v and v == (r.get("sf") or [None] * 2)[i])
                pts += 8 if p.get("c") and p.get("c") == r.get("c") else 0
                e["ll"] = pts
            continue
        w = str(x.get("w")); J = W.get(w)
        if not J or now < J.get("pr", now): continue
        e["w"][w] = sum(1 for gid, v in (J.get("res") or {}).items() if p.get(gid) == v)
    TB["t"] = T; TB["al"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    json.dump(TB, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"Quiniela colegial: {len(W)} semanas, {len(T)} jugadores")
