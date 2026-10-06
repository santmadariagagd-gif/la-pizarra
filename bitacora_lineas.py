# Bitácora de líneas de la NFL (La Pizarra, 5 oct 2026)
# -----------------------------------------------------------------------------------------------
# Para qué: encontrar de dónde saca ESPN Pick'em sus líneas (siempre terminan en .5 y no cambian una vez
# publicadas) para dejar de depender de ESPN y tener la MISMA línea con una fuente con permiso comercial
# (The Odds API). Esto es temporal: se corre las semanas 5 y 6 de 2026 y luego se decide.
#
# Qué hace cada vez que corre (cada 2 horas, workflow "Bitácora de líneas"):
#   1. Lee la quiniela de ESPN Pick'em (gratis) y anota la línea de cada partido, cuándo la vio por primera
#      vez y si cambió después.
#   2. Pide a The Odds API las líneas de todas las casas de EE. UU. (1 crédito) SOLO si:
#        - apareció un partido nuevo en ESPN (= ESPN acaba de publicar la semana)  → "nueva"
#        - ESPN cambió alguna línea ya publicada                                  → "cambio"
#        - todavía no hay foto del día y ya son las 7 am en CDMX                   → "diaria"
#   3. Compara: para cada casa, en cuántos partidos su línea es IGUAL a la de ESPN; también reglas como
#      "mediana redondeada a .5". El resumen sale en el registro de Actions.
# Guarda todo en bitacora/lineas.json (fuera de docs/ para que la tarea de la página no lo pise).
# Convención de línea (igual que en todo el sitio): L = ventaja del LOCAL (+2.5 = el local recibe 2.5).
import json, os, sys, statistics, time, urllib.request
from datetime import datetime, timezone, timedelta

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bitacora", "lineas.json")
CDMX = timezone(timedelta(hours=-6))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
ESPN_FIX = {"WSH": "WAS", "LAR": "LA"}
NOMBRES = {  # The Odds API usa nombres completos → abreviaturas de nflverse
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def pedir(url, headers=None):
    rq = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(rq, timeout=25) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)


def leer_espn():
    """→ (semana, etiqueta, {"VIS@LOC": {"L": float, "mappings": [...]}})"""
    d, _ = pedir("https://gambit-api.fantasy.espn.com/apis/v1/challenges/pigskinpickem")
    per = d.get("currentScoringPeriod") or {}
    juegos = {}
    for p in d.get("propositions", []):
        O = p.get("possibleOutcomes") or []
        A = next((o for o in O if o.get("subType") == "AWAY"), None)
        H = next((o for o in O if o.get("subType") == "HOME"), None)
        if not A or not H or p.get("spread") is None:
            continue
        a = ESPN_FIX.get(A["abbrev"], A["abbrev"]); h = ESPN_FIX.get(H["abbrev"], H["abbrev"])
        maps = [m for o in O for m in (o.get("mappings") or []) if m.get("type") == "BETTING_LINE"]
        juegos[f"{a}@{h}"] = {"L": float(p["spread"]), "mappings": maps, "fecha": p.get("date")}
    return per.get("id"), per.get("label"), juegos


def leer_casas(clave):
    """→ ({"VIS@LOC": {casa: L}}, créditos restantes)"""
    url = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
           f"?regions=us&markets=spreads&oddsFormat=american&apiKey={clave}")
    d, hd = pedir(url)
    out = {}
    for ev in d:
        a = NOMBRES.get(ev.get("away_team")); h = NOMBRES.get(ev.get("home_team"))
        if not a or not h:
            continue
        casas = {}
        for b in ev.get("bookmakers", []):
            for m in b.get("markets", []):
                if m.get("key") != "spreads":
                    continue
                pt = next((o.get("point") for o in m.get("outcomes", []) if o.get("name") == ev.get("home_team")), None)
                if pt is not None:
                    casas[b.get("key")] = float(pt)
        if casas:
            out[f"{a}@{h}"] = casas
    rest = next((v for k, v in hd.items() if k.lower() == "x-requests-remaining"), None)
    return out, rest




def resumen(sem):
    """Compara cada foto de las casas contra la línea de ESPN. Devuelve texto para el registro."""
    lineas = []
    for foto in sem.get("casas", []):
        E = foto.get("espn") or {k: v["L"] for k, v in sem["espn"].items()}   # la línea de ESPN cuando se tomó la foto
        cuenta, total = {}, {}
        regla = {"mediana": [0, 0], "mediana→.5 hacia el que no es favorito": [0, 0], "mediana→.5 hacia el favorito": [0, 0]}
        for k, casas in foto["lineas"].items():
            if k not in E:
                continue
            for c, L in casas.items():
                total[c] = total.get(c, 0) + 1
                cuenta[c] = cuenta.get(c, 0) + (1 if L == E[k] else 0)
            med = statistics.median(casas.values())
            regla["mediana"][1] += 1; regla["mediana"][0] += med == E[k]
            if med % 1 == 0:   # línea entera: ¿ESPN le suma medio punto al que no es favorito o al favorito?
                dog = med + 0.5 if med >= 0 else med - 0.5   # L = ventaja del local: + = local no favorito
                fav = med - 0.5 if med >= 0 else med + 0.5
                if med == 0: dog = fav = None
            else:
                dog = fav = med
            for nom, val in (("mediana→.5 hacia el que no es favorito", dog), ("mediana→.5 hacia el favorito", fav)):
                regla[nom][1] += 1; regla[nom][0] += val == E[k]
        orden = sorted(total, key=lambda c: (-cuenta[c] / total[c], -total[c]))
        lineas.append(f"  Foto {foto['cuando']} ({foto['motivo']}): " + ", ".join(f"{c} {cuenta[c]}/{total[c]}" for c in orden[:8]))
        lineas.append("    reglas: " + ", ".join(f"{n} {v[0]}/{v[1]}" for n, v in regla.items()))
    cambios = sum(len(v.get("cambios", [])) for v in sem["espn"].values())
    lineas.append(f"  ESPN: {len(sem['espn'])} partidos; líneas de ESPN que cambiaron después de publicarse: {cambios}")
    return "\n".join(lineas)


def main():
    ahora = datetime.now(timezone.utc); hoy = ahora.astimezone(CDMX).strftime("%Y-%m-%d")
    try:
        B = json.load(open(RUTA, encoding="utf-8"))
    except Exception:
        B = {"semanas": {}}
    try:
        w, etiqueta, juegos = leer_espn()
    except Exception as ex:
        print("Bitácora: ESPN Pick'em no respondió:", ex); return
    if not w or not juegos:
        print("Bitácora: ESPN Pick'em sin partidos todavía"); return
    temporada = ahora.year if ahora.month >= 3 else ahora.year - 1
    sem = B["semanas"].setdefault(f"{temporada}-{w}", {"etiqueta": etiqueta, "espn": {}, "casas": []})
    nuevos = cambio = 0
    for k, x in juegos.items():
        e = sem["espn"].get(k)
        if e is None:
            sem["espn"][k] = {"L": x["L"], "visto": ahora.isoformat(timespec="minutes"), "mappings": x["mappings"], "fecha": x["fecha"]}
            nuevos += 1
        elif e["L"] != x["L"]:
            e.setdefault("cambios", []).append({"cuando": ahora.isoformat(timespec="minutes"), "de": e["L"], "a": x["L"]})
            e["L"] = x["L"]; cambio += 1
    if nuevos:
        sem.setdefault("primera_vez", ahora.isoformat(timespec="minutes"))
    print(f"Bitácora: ESPN {etiqueta} — {len(juegos)} partidos, {nuevos} nuevos (vistos por primera vez el {sem.get('primera_vez')})")

    motivo = "nueva" if nuevos else "cambio" if cambio else None   # cambio: ESPN movió una línea → ¿a qué casa se movió?
    if not motivo and ahora.astimezone(CDMX).hour >= 7 and not any(f["cuando"][:10] == hoy for f in sem["casas"]):
        motivo = "diaria"
    if os.environ.get("FORZAR") == "si":
        motivo = motivo or "manual"
    clave = os.environ.get("ODDS_API_KEY", "").strip()
    if motivo and clave:
        try:
            casas, rest = leer_casas(clave)
            foto = {k: v for k, v in casas.items() if k in sem["espn"]}
            sem["casas"].append({"cuando": ahora.astimezone(CDMX).strftime("%Y-%m-%d %H:%M"), "motivo": motivo, "lineas": foto,
                                 "espn": {k: v["L"] for k, v in sem["espn"].items()}})   # ESPN en ese momento
            print(f"Bitácora: foto de las casas ({motivo}): {len(foto)} partidos; créditos de The Odds API que quedan: {rest}")
        except Exception as ex:
            print("Bitácora: The Odds API no respondió:", ex)
    elif motivo:
        print("Bitácora: falta el secret ODDS_API_KEY (no se tomó foto de las casas)")
    else:
        print("Bitácora: ya hay foto de hoy; no se gastan créditos")

    os.makedirs(os.path.dirname(RUTA), exist_ok=True)
    json.dump(B, open(RUTA, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"Bitácora — semana {w}:\n" + resumen(sem))


if __name__ == "__main__":
    main()
