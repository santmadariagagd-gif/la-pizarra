"""probar_api_football.py — prueba de calidad de API-Football (plan gratis, temporada 2024).

No toca la página. Lo corre la automatización "Probar API-Football" (botón Run workflow) y deja el
reporte en prueba_api_football.txt dentro del repositorio. La clave va en el secret API_FOOTBALL_KEY.
Prueba 1 (29 sep 2026): Liga MX. Prueba 2: las 5 ligas europeas y la Champions, temporada 2024-25.
Unos 45 pedidos de los 100 diarios; tarda ~5 min (el plan gratis deja 10 pedidos por minuto).
"""
import json, os, time, urllib.request, urllib.parse
from collections import Counter

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
TEMP = 2024
# id de API-Football, nombre, partidos máximos de un equipo en la temporada (para detectar totales imposibles)
LIGAS = [(39, "Premier League", 38), (140, "LaLiga", 38), (135, "Serie A", 38),
         (78, "Bundesliga", 34), (61, "Ligue 1", 34), (2, "Champions League", 17)]
lineas = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lineas.append(s)

usados = 0
def api(ruta, **params):
    global usados
    url = f"{BASE}/{ruta}" + ("?" + urllib.parse.urlencode(params) if params else "")
    for intento in range(2):
        time.sleep(6.5)
        req = urllib.request.Request(url, headers={"x-apisports-key": KEY, "User-Agent": "LaPizarra/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                j = json.loads(r.read().decode("utf-8")); usados += 1
        except Exception as ex:
            out(f"  ! {ruta} falló: {str(ex).replace(KEY, '***')}"); return None
        err = j.get("errors")
        if err and "rateLimit" in json.dumps(err) and intento == 0:
            out("  (límite por minuto, espero 60 s)"); time.sleep(60); continue
        if err: out(f"  ! {ruta} {params}: {err}")
        return j
    return None

def pct(n, d): return f"{round(100*n/d)}%" if d else "–"
def st(p): return (p.get("statistics") or [{}])[0]

def liga(lid, nombre, maxp):
    out(f"\n=========== {nombre} (id {lid}) · temporada {TEMP}-{str(TEMP+1)[2:]} ===========")
    lg = (api("leagues", id=lid) or {}).get("response", [])
    if not lg: out("No encontré la liga."); return
    for s in lg[0].get("seasons", []):
        if s.get("year") == TEMP:
            cov = s.get("coverage", {}); fx = cov.get("fixtures", {})
            si = [n for n, v in [("eventos", fx.get("events")), ("alineaciones", fx.get("lineups")), ("stats de partido", fx.get("statistics_fixtures")),
                                  ("stats de jugadores por partido", fx.get("statistics_players")), ("lesiones", cov.get("injuries")),
                                  ("predicciones", cov.get("predictions")), ("momios", cov.get("odds"))] if v]
            no = [n for n, v in [("eventos", fx.get("events")), ("alineaciones", fx.get("lineups")), ("lesiones", cov.get("injuries")),
                                  ("stats de jugadores por partido", fx.get("statistics_players"))] if not v]
            out("Cobertura sí:", ", ".join(si)); out("Cobertura no:", ", ".join(no) or "—")
    for ruta, nombre_t, campo in [("players/topscorers", "Goleadores", "total"), ("players/topassists", "Asistidores", "assists")]:
        R = (api(ruta, league=lid, season=TEMP) or {}).get("response", [])
        raros = [p for p in R if (st(p).get("games", {}).get("appearences") or 0) > maxp]
        out(f"{nombre_t} (top 5 de {len(R)}; con más de {maxp} partidos, imposible: {len(raros)}):")
        for p in R[:5]:
            s = st(p); out(f"  {p['player']['name']} ({s.get('team',{}).get('name')}): {s.get('goals',{}).get(campo)} en {s.get('games',{}).get('appearences')} partidos")
        for p in raros[:3]:
            s = st(p); out(f"  RARO: {p['player']['name']} ({s.get('team',{}).get('name')}) {s.get('games',{}).get('appearences')} partidos")
    J = []
    for pg in (1, 2, 3):   # el plan gratis solo deja 3 páginas
        J += (api("players", league=lid, season=TEMP, page=pg) or {}).get("response", [])
    jug = [st(p) for p in J if st(p).get("games", {}).get("minutes")]
    raros = [p for p in J if (st(p).get("games", {}).get("appearences") or 0) > maxp]
    out(f"Muestra de jugadores: {len(J)} ({len(jug)} con minutos; con partidos imposibles: {len(raros)})")
    campos = [("calificación", lambda s: s["games"].get("rating")), ("tiros", lambda s: s["shots"].get("total")),
              ("pases clave", lambda s: s["passes"].get("key")), ("entradas", lambda s: s["tackles"].get("total")),
              ("duelos", lambda s: s["duels"].get("total")), ("regates", lambda s: s["dribbles"].get("attempts"))]
    out("Datos completos:", ", ".join(f"{n} {pct(sum(1 for s in jug if f(s) not in (None,'',0)), len(jug))}" for n, f in campos))
    inj = (api("injuries", league=lid, season=TEMP) or {}).get("response", [])
    out(f"Lesiones registradas: {len(inj)}" + (f" · tipos: {dict(Counter(i['player'].get('type') for i in inj).most_common(3))}" if inj else ""))
    for i in inj[:2]: out(f"  {i['player'].get('name')} ({i['team'].get('name')}): {i['player'].get('type')} · {i['player'].get('reason')} · {i['fixture'].get('date','')[:10]}")

def main():
    if not KEY: out("Falta el secret API_FOOTBALL_KEY."); return
    out("=== PRUEBA API-FOOTBALL · ligas europeas y Champions ===")
    s = (api("status") or {}).get("response") or {}
    out("Cuenta:", s.get("subscription", {}).get("plan"), "· pedidos hoy:", s.get("requests"))
    for lid, nombre, maxp in LIGAS: liga(lid, nombre, maxp)
    out(f"\nPedidos usados en esta prueba: {usados}")

try:
    main()
except Exception as ex:
    out("Error inesperado:", str(ex).replace(KEY, "***") if KEY else ex)
with open("prueba_api_football.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lineas) + "\n")
