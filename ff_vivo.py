"""
ff_vivo.py — Avisos al teléfono de tu fantasy en vivo (24 nov 2026). Lo llama avisos.py en cada vuelta mientras hay partidos.

Para cada persona con avisos activados y su liga de Sleeper guardada en la cuenta (usuarios/{uid}: sleeper = usuario,
liga = id de la liga), mientras haya partidos de la NFL en juego (marcador público de ESPN):
  · "+6.4 de J. Allen": un titular tuyo suma 5.5 puntos o más entre una revisión y otra (casi siempre un TD).
  · "Tu rival te pasó" / "Volviste a ir arriba": cambia quién va ganando (con al menos 1 punto de diferencia).
  · Resultado final del matchup, una vez por semana, cuando ya terminaron todos los partidos de la semana.
Estado en sistema/avisos E["ff"][uid] = {w, a, b, p: {sid: puntos}, fin}. Categoría de avisos: "fantasy".
Privacidad: el log de GitHub es público; los avisos no llevan nombres de equipos de fantasy (solo jugadores de la NFL).
Nombres de jugadores: docs/datos/paq_fantasy.json (sleeper: sid → [nombre, posición, equipo, gsis]).
"""
import json, os, time, urllib.request

API = "https://api.sleeper.app/v1"
ESPN_NFL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
_NOM = None


def _j(url):
    req = urllib.request.Request(url, headers={"User-Agent": "La Pizarra (lapizarra.mx)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _nombre(sid):
    global _NOM
    if _NOM is None:
        try:
            P = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "paq_fantasy.json"), encoding="utf-8"))
            _NOM = P.get("sleeper") or {}
        except Exception:
            _NOM = {}
    if sid and sid.isalpha(): return f"la defensa de {sid}"
    n = (_NOM.get(str(sid)) or [""])[0]
    if not n: return "un jugador tuyo"
    w = n.split(" ")
    return f"{w[0][0]}. {' '.join(w[1:])}" if len(w) > 1 else n


def _pts(v): return f"{round(v or 0, 2):g}"


def _jugada(t, ap):
    """Última jugada de ESPN (en inglés) → texto corto en español, si menciona al jugador."""
    import re
    T = str(t or "")
    if not ap or len(ap) < 3 or ap not in T: return ""
    y = re.search(r"for (-?\d+) (?:yds|yards)", T, re.I); y = y.group(1) if y else None
    td = bool(re.search("touchdown", T, re.I)); yd = f" de {y} yardas" if y else ""
    if re.search("field goal is good", T, re.I):
        d = re.search(r"(\d+) (?:yard|yd) field goal", T, re.I); return f"gol de campo de {d.group(1)} yardas" if d else "gol de campo"
    if re.search("pass", T, re.I) and not re.search("incomplete", T, re.I):
        rec = bool(re.search(r"to [A-Z][\w.'-]*\.?\s?" + re.escape(ap), T))
        return ("recepción de TD" if td else "recepción") + yd if rec else ("pase de TD" if td else "pase") + yd
    if re.search(r"(run|rush|left end|right end|up the middle|tackle|guard)", T, re.I): return ("carrera de TD" if td else "carrera") + yd
    return "touchdown" if td else ""


def _equipo(sid):
    _nombre(sid)
    return (_NOM.get(str(sid)) or ["", "", ""])[2] if _NOM else ""


def corre(A, cache):
    """A = el objeto Avisos (subs, E, db, manda). cache = dict que dura toda la corrida (ligas, usuarios)."""
    subs = A.subs or {}
    if not subs: return False
    try: sb = _j(ESPN_NFL)
    except Exception as e: print("Fantasy en vivo: ESPN", repr(e)[:120]); return False
    est = [((ev.get("competitions") or [{}])[0].get("status") or ev.get("status") or {}).get("type", {}).get("state") for ev in sb.get("events") or []]
    vivo, todo = "in" in est, bool(est) and all(s == "post" for s in est)
    ULT = {}   # equipo → última jugada de su partido
    for ev in sb.get("events") or []:
        C = (ev.get("competitions") or [{}])[0]; lp = ((C.get("situation") or {}).get("lastPlay") or {}).get("text") or ""
        for c in C.get("competitors") or []: ULT[{"WSH": "WAS", "JAX": "JAX", "LAR": "LA"}.get(c["team"]["abbreviation"], c["team"]["abbreviation"])] = lp
    E = A.E.setdefault("ff", {})
    if not vivo and not (todo and any(not x.get("fin") for x in E.values())): return False
    if "estado" not in cache:
        try: cache["estado"] = _j(f"{API}/state/nfl")
        except Exception: cache["estado"] = {}
    w = int(cache["estado"].get("week") or 0)
    if not w: return False
    # quién tiene liga (una lectura por corrida)
    if "quien" not in cache:
        Q = {}
        for uid in subs:
            try: d = A.db.usuario(uid)
            except Exception: d = {}
            if d.get("sleeper") and d.get("liga") and (d.get("fsrc") or "sleeper") != "espn": Q[uid] = (str(d["sleeper"]), str(d["liga"]))
        cache["quien"] = Q
        print(f"Fantasy en vivo: {len(Q)} personas con liga de Sleeper y avisos")
    mus = {}
    n = 0
    for uid, (usr, lid) in cache["quien"].items():
        try:
            key = ("u", usr)
            if key not in cache: cache[key] = _j(f"{API}/user/{urllib.request.quote(usr)}") or {}
            u_id = cache[key].get("user_id")
            if ("r", lid) not in cache: cache[("r", lid)] = _j(f"{API}/league/{lid}/rosters") or []
            R = next((r for r in cache[("r", lid)] if r.get("owner_id") == u_id or u_id in (r.get("co_owners") or [])), None)
            if not R: continue
            if lid not in mus: mus[lid] = _j(f"{API}/league/{lid}/matchups/{w}") or []
            M = next((m for m in mus[lid] if m.get("roster_id") == R["roster_id"]), None)
            if not M or M.get("matchup_id") is None: continue
            O = next((m for m in mus[lid] if m.get("matchup_id") == M["matchup_id"] and m.get("roster_id") != R["roster_id"]), None)
            a, b = float(M.get("points") or 0), float((O or {}).get("points") or 0)
            pp = {s: float((M.get("players_points") or {}).get(s) or 0) for s in (M.get("starters") or []) if s and s != "0"}
            S = E.get(uid) or {}
            if S.get("w") != w: S = {"w": w, "a": a, "b": b, "p": pp, "fin": False}; E[uid] = S; continue
            if vivo:
                # jugadas grandes de tus titulares (máximo un aviso por revisión: la más grande)
                sube = sorted(((pp[s] - (S["p"].get(s) or 0), s) for s in pp if s in S["p"]), reverse=True)
                if sube and sube[0][0] >= 5.5:
                    d, s = sube[0]
                    eq = _equipo(s); eq = {"LAR": "LA"}.get(eq, eq); ap = (_NOM.get(str(s)) or [""])[0].split(" ")[-1] if _NOM else ""
                    jug = _jugada(ULT.get(eq, ""), ap)
                    A.manda(uid, "fantasy", f"+{_pts(d)} de {_nombre(s)}" + (f": {jug}" if jug else ""), f"Tu fantasy: vas {_pts(a)} – {_pts(b)}" + (" · arriba" if a > b else " · abajo" if a < b else ""),
                            "/#fmatch", f"ff|{uid}|{w}|{s}|{int(pp[s] * 10)}"); n += 1
                antes, ahora = (S["a"] or 0) - (S["b"] or 0), a - b
                if O and antes * ahora < 0 and abs(ahora) >= 1:
                    if ahora < 0: A.manda(uid, "fantasy", "Tu rival te pasó", f"Vas {_pts(a)} – {_pts(b)} en tu fantasy. Todavía hay partidos.", "/#fmatch", f"ffl|{uid}|{w}|{int(time.time() // 600)}")
                    else: A.manda(uid, "fantasy", "Volviste a ir arriba", f"Vas {_pts(a)} – {_pts(b)} en tu fantasy.", "/#fmatch", f"ffl|{uid}|{w}|{int(time.time() // 600)}")
                    n += 1
            if todo and not S.get("fin") and O:
                res = "Ganaste" if a > b else "Perdiste" if a < b else "Empataste"
                A.manda(uid, "fantasy", f"{res} tu matchup de la semana {w}", f"Quedó {_pts(a)} – {_pts(b)}. Mira cómo te fue.", "/#fmatch", f"fff|{uid}|{w}")
                S["fin"] = True; n += 1
            S.update(a=a, b=b, p=pp); E[uid] = S
        except Exception as e:
            print("Fantasy en vivo:", repr(e)[:150])
    # limpieza: semanas viejas
    for k in [k for k, x in E.items() if x.get("w") and x["w"] < w - 1]: E.pop(k, None)
    if n: print(f"Fantasy en vivo: {n} avisos")
    return vivo
