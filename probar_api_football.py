"""probar_api_football.py — prueba 3 de API-Football (plan Pro, temporada actual 2026).

No toca la página. La corre la automatización "Probar API-Football" (botón Run workflow) y deja el reporte
en prueba_api_football.txt. La clave va en el secret API_FOOTBALL_KEY (misma cuenta; el plan Pro se contrata
en el tablero de api-football.com).
Qué revisa, para comparar con Sportmonks: Liga MX (partidos, jornadas, tabla, goleo, un partido completo con
alineaciones y posición en cancha, eventos, estadísticas de equipo y de jugador con calificación, lesiones,
previa con alineación probable), Champions, Selección mexicana, FA Cup, Libertadores, temporada pasada y en vivo.
Unos 35 pedidos (el Pro deja 7,500 al día).
"""
import json, os, time, urllib.request, urllib.parse
from collections import Counter
from datetime import date

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
TEMP = 2026
lineas = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lineas.append(s)

usados = 0
def api(ruta, **params):
    global usados
    url = f"{BASE}/{ruta}" + ("?" + urllib.parse.urlencode(params) if params else "")
    for intento in range(2):
        time.sleep(0.4)
        req = urllib.request.Request(url, headers={"x-apisports-key": KEY, "User-Agent": "LaPizarra/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                j = json.loads(r.read().decode("utf-8")); usados += 1
        except Exception as ex:
            out(f"  ! {ruta} falló: {str(ex).replace(KEY, '***')}"); return None
        err = j.get("errors")
        if err and "rateLimit" in json.dumps(err) and intento == 0:
            out("  (límite por minuto, espero 60 s)"); time.sleep(60); continue
        if err and (not isinstance(err, list) or err): out(f"  ! {ruta} {params}: {err}")
        return j
    return None

def R(ruta, **p): return (api(ruta, **p) or {}).get("response", [])
def pct(n, d): return f"{round(100*n/d)}%" if d else "–"
def fin(f): return (f.get("fixture", {}).get("status", {}) or {}).get("short") in ("FT", "AET", "PEN")
def nom(f): return f"{f['teams']['home']['name']} {f['goals']['home']}-{f['goals']['away']} {f['teams']['away']['name']}"

# ---------------------------------------------------------------- 0. Cuenta
def cuenta():
    out("=========== 0. Cuenta ===========")
    j = api("status"); a = (j or {}).get("response", {}) if isinstance((j or {}).get("response"), dict) else {}
    out("Plan:", (a.get("subscription") or {}).get("plan"), "· activo:", (a.get("subscription") or {}).get("active"),
        "· pedidos hoy:", (a.get("requests") or {}).get("current"), "de", (a.get("requests") or {}).get("limit_day"))

# ---------------------------------------------------------------- 1. Liga MX
def liga_mx():
    out("\n=========== 1. Liga MX (id 262) · temporada 2026 ===========")
    F = R("fixtures", league=262, season=TEMP)
    out(f"Partidos de la temporada: {len(F)} · estados: {dict(Counter((f['fixture']['status'] or {}).get('short') for f in F))}")
    out("Rondas:", sorted({f['league'].get('round') for f in F}, key=str)[:30])
    hoy = date.today().isoformat()
    jug = sorted([f for f in F if fin(f)], key=lambda f: f["fixture"]["date"])
    prox = sorted([f for f in F if (f['fixture']['status'] or {}).get('short') in ("NS", "TBD")], key=lambda f: f["fixture"]["date"])
    if jug: out("Último jugado:", nom(jug[-1]), jug[-1]["fixture"]["date"], "· ronda:", jug[-1]["league"].get("round"), "· estadio:", (jug[-1]["fixture"].get("venue") or {}).get("name"), "· árbitro:", jug[-1]["fixture"].get("referee"))

    # Tabla
    S = R("standings", league=262, season=TEMP)
    grupos = (S[0]["league"]["standings"] if S else [])
    out(f"Tabla: {len(grupos)} grupo(s) · nombres: {[ (g[0].get('group') if g else None) for g in grupos ]}")
    for g in grupos[:1]:
        for r in g[:3]: out(f"  {r['rank']}. {r['team']['name']} · {r['points']} pts · PJ {r['all']['played']} G {r['all']['win']} E {r['all']['draw']} P {r['all']['lose']} GF {r['all']['goals']['for']} GC {r['all']['goals']['against']} · forma {r.get('form')}")

    # Goleo (el punto flaco: comparar con Sportmonks: Rondón 10, Henry Martín 6, Carranza 6, Estupiñán 6 al 1 oct)
    G = R("players/topscorers", league=262, season=TEMP)
    out("Goleo (top 5):", " | ".join(f"{p['player']['name']} ({p['statistics'][0]['team']['name']}): {p['statistics'][0]['goals']['total']} en {p['statistics'][0]['games']['appearences']} PJ" for p in G[:5]))
    A = R("players/topassists", league=262, season=TEMP)
    out("Asistencias (top 3):", " | ".join(f"{p['player']['name']}: {p['statistics'][0]['goals']['assists']}" for p in A[:3]))

    # Partido completo
    if jug: partido(jug[-1]["fixture"]["id"], nom(jug[-1]))
    # Previa
    if prox: previa(prox[0])
    # Lesiones de la liga
    I = R("injuries", league=262, season=TEMP)
    out(f"Lesiones registradas en la temporada: {len(I)} · ej.: " + " | ".join(f"{i['player']['name']} ({i['team']['name']}): {i['player'].get('reason')}" for i in I[:4]))
    # Temporada pasada
    F25 = R("fixtures", league=262, season=2025)
    out(f"Temporada 2025 (pasada): {len(F25)} partidos · rondas: {sorted({f['league'].get('round') for f in F25}, key=str)[:8]}…")
    S25 = R("standings", league=262, season=2025)
    out(f"  Tabla 2025: {len(S25[0]['league']['standings']) if S25 else 0} grupo(s)")

def partido(fid, nombre):
    out(f"\n  --- Partido completo: {nombre} (id {fid}) ---")
    L = R("fixtures/lineups", fixture=fid)
    for t in L:
        xi = t.get("startXI") or []
        out(f"  {t['team']['name']}: formación {t.get('formation')} · DT {(t.get('coach') or {}).get('name')} · titulares {len(xi)} · banca {len(t.get('substitutes') or [])} · con posición en cancha (grid): {pct(sum(1 for p in xi if (p['player'] or {}).get('grid')), len(xi))}")
        out("    ej.:", ", ".join(f"{p['player']['name']} #{p['player'].get('number')} {p['player'].get('pos')} {p['player'].get('grid')}" for p in xi[:3]))
    E = R("fixtures/events", fixture=fid)
    out(f"  Eventos: {len(E)} · {dict(Counter(e['type'] + '/' + str(e.get('detail')) for e in E).most_common(8))}")
    for e in E[:4]: out(f"    {e['time']['elapsed']}{'+' + str(e['time']['extra']) if e['time'].get('extra') else ''}' {e['type']} {e.get('detail')}: {(e.get('player') or {}).get('name')} {('→ ' + str((e.get('assist') or {}).get('name'))) if (e.get('assist') or {}).get('name') else ''} ({e['team']['name']})")
    T = R("fixtures/statistics", fixture=fid)
    for t in T[:1]:
        out(f"  Estadísticas de equipo ({t['team']['name']}): {len(t['statistics'])} datos · " + ", ".join(f"{s['type']}={s['value']}" for s in t["statistics"]))
    P = R("fixtures/players", fixture=fid)
    todos = [p for t in P for p in t.get("players", [])]
    jugaron = [p for p in todos if (p["statistics"][0]["games"].get("minutes") or 0) > 0]
    out(f"  Estadísticas por jugador: {len(todos)} jugadores, {len(jugaron)} con minutos")
    def tiene(p, *k):
        v = p["statistics"][0]
        for x in k: v = (v or {}).get(x)
        return v is not None
    campos = [("calificación", "games", "rating"), ("minutos", "games", "minutes"), ("tiros", "shots", "total"), ("a gol", "shots", "on"), ("goles", "goals", "total"), ("asist.", "goals", "assists"),
              ("pases", "passes", "total"), ("precisión", "passes", "accuracy"), ("pases clave", "passes", "key"), ("faltas", "fouls", "committed"), ("recibidas", "fouls", "drawn"), ("duelos", "duels", "total"),
              ("regates", "dribbles", "success"), ("barridas", "tackles", "total"), ("intercep.", "tackles", "interceptions"), ("atajadas", "goals", "saves"), ("fuera de lugar", "offsides")]
    out("  Qué tan completos (de los que jugaron): " + ", ".join(f"{n} {pct(sum(1 for p in jugaron if tiene(p, *k)), len(jugaron))}" for n, *k in campos))
    rt = [(p["player"]["name"], p["statistics"][0]["games"].get("rating")) for p in jugaron[:3]]
    out("  Calificación (ej.):", rt)
    h = R("fixtures/headtohead", h2h=f"{L[0]['team']['id']}-{L[1]['team']['id']}") if len(L) == 2 else []
    out(f"  Duelos previos: {len(h)}")

def previa(f):
    fid = f["fixture"]["id"]
    out(f"\n  --- Previa: {f['teams']['home']['name']} vs {f['teams']['away']['name']} ({f['fixture']['date']}) ---")
    L = R("fixtures/lineups", fixture=fid)
    out(f"  Alineación probable ya publicada: {len(L)} equipos")
    I = R("injuries", fixture=fid)
    out(f"  Bajas para el partido: {len(I)} · " + " | ".join(f"{i['player']['name']} ({i['team']['name']}): {i['player'].get('reason')} · {i['player'].get('type')}" for i in I[:5]))
    O = R("odds", fixture=fid)
    casas = [b["name"] for o in O for b in o.get("bookmakers", [])]
    out(f"  Momios: {len(casas)} casas · {casas[:5]}")
    Pr = R("predictions", fixture=fid)
    if Pr: out(f"  Predicción incluida: {(Pr[0].get('predictions') or {}).get('percent')} · consejo: {(Pr[0].get('predictions') or {}).get('advice')}")

# ---------------------------------------------------------------- 2. Otras competencias
def otras():
    out("\n=========== 2. Champions, FA Cup, Libertadores, Leagues Cup ===========")
    for lid, nombre in [(2, "Champions League"), (45, "FA Cup"), (13, "Copa Libertadores"), (772, "Leagues Cup")]:
        F = R("fixtures", league=lid, season=TEMP)
        rondas = sorted({f['league'].get('round') for f in F}, key=str)
        out(f"{nombre} ({lid}): {len(F)} partidos · estados {dict(Counter((f['fixture']['status'] or {}).get('short') for f in F))} · rondas: {rondas[:10]}{'…' if len(rondas) > 10 else ''}")
        S = R("standings", league=lid, season=TEMP)
        if S: out(f"  Tabla: {len(S[0]['league']['standings'])} grupo(s); 1º: {S[0]['league']['standings'][0][0]['team']['name']} ({S[0]['league']['standings'][0][0]['points']} pts)")
    out("\n=========== 3. Selección mexicana ===========")
    T = R("teams", name="Mexico")
    nac = [t for t in T if t["team"].get("national")]
    if nac:
        tid = nac[0]["team"]["id"]
        F = R("fixtures", team=tid, season=TEMP)
        out(f"México (id {tid}): {len(F)} partidos en 2026 · " + " | ".join(f"{f['fixture']['date'][:10]} {f['league']['name']}: {nom(f)} ({f['fixture']['status']['short']})" for f in sorted(F, key=lambda f: f['fixture']['date'])[-6:]))
    else: out("No se encontró la selección")
    out("\n=========== 4. En vivo ahora ===========")
    V = R("fixtures", live="all")
    out(f"Partidos en vivo en todo el mundo: {len(V)} · ej.: " + " | ".join(f"{f['league']['name']}: {nom(f)} {f['fixture']['status']['elapsed']}'" for f in V[:4]))

def main():
    if not KEY: out("Falta el secret API_FOOTBALL_KEY."); return
    out(f"=== PRUEBA API-FOOTBALL (Pro) · {date.today()} ===")
    cuenta()
    for paso in (liga_mx, otras):
        try: paso()
        except Exception as ex: out(f"  ! Error en {paso.__name__}: {ex}")
    out(f"\nPedidos usados: {usados}")

if __name__ == "__main__":
    try: main()
    finally:
        with open("prueba_api_football.txt", "w", encoding="utf-8") as f: f.write("\n".join(lineas) + "\n")
