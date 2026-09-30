"""probar_api_football.py — prueba de calidad de API-Football con Liga MX, temporada 2024 (plan gratis).

No toca la página. Lo corre la automatización "Probar API-Football" (botón Run workflow) y deja el
reporte en prueba_api_football.txt dentro del repositorio. Gasta unos 20 pedidos de los 100 diarios.
La clave va en el secret API_FOOTBALL_KEY (nunca en este archivo: el repositorio es público).
"""
import json, os, time, urllib.request, urllib.parse
from collections import Counter

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
LIGA, TEMP = 262, 2024          # 262 = Liga MX en API-Football (se verifica abajo)
PAGINAS_JUGADORES = 10          # 20 jugadores por página -> muestra de ~200
lineas = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lineas.append(s)

usados = 0
def api(ruta, **params):
    """Un pedido a la API. Respeta el límite del plan gratis (10 por minuto)."""
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
        if err and ("rateLimit" in json.dumps(err) and intento == 0):
            out("  (límite por minuto, espero 60 s)"); time.sleep(60); continue
        if err: out(f"  ! {ruta} {params}: {err}")
        return j
    return None

def pct(n, d): return f"{round(100*n/d)}%" if d else "–"

def main():
    if not KEY:
        out("Falta el secret API_FOOTBALL_KEY."); return
    out("=== PRUEBA API-FOOTBALL · Liga MX temporada 2024 ===")
    st = api("status")
    if st and st.get("response"):
        r = st["response"]; out("Cuenta:", r.get("subscription", {}).get("plan"), "· pedidos hoy:", r.get("requests"))

    out("\n--- 1. Liga y cobertura ---")
    lg = api("leagues", id=LIGA)
    if not lg or not lg.get("response"):
        out("No encontré la liga 262. Ligas de México disponibles:")
        mx = api("leagues", country="Mexico") or {}
        for x in mx.get("response", []): out(" ", x["league"]["id"], x["league"]["name"])
        return
    L = lg["response"][0]; out("Liga:", L["league"]["name"], "·", L["country"]["name"])
    for s in L.get("seasons", []):
        if s.get("year") == TEMP:
            out("Temporada", TEMP, ":", s.get("start"), "a", s.get("end"))
            cov = s.get("coverage", {}); fx = cov.get("fixtures", {})
            out("Cobertura según la API:")
            for k, v in [("Eventos del partido (goles, tarjetas)", fx.get("events")), ("Alineaciones", fx.get("lineups")),
                         ("Estadísticas de partido", fx.get("statistics_fixtures")), ("Estadísticas de jugadores por partido", fx.get("statistics_players")),
                         ("Tabla", cov.get("standings")), ("Jugadores (temporada)", cov.get("players")), ("Goleadores", cov.get("top_scorers")),
                         ("Asistidores", cov.get("top_assists")), ("Lesiones", cov.get("injuries")), ("Predicciones", cov.get("predictions")), ("Momios", cov.get("odds"))]:
                out(f"  {'Sí' if v else 'No'} · {k}")
    out("Temporadas disponibles en la liga:", [s.get("year") for s in L.get("seasons", [])][-6:])

    out("\n--- 2. Partidos de la temporada ---")
    fx = api("fixtures", league=LIGA, season=TEMP) or {}
    F = fx.get("response", [])
    out("Partidos:", len(F))
    if F:
        fechas = sorted(f["fixture"]["date"][:10] for f in F); out("Del", fechas[0], "al", fechas[-1])
        rondas = Counter(f["league"].get("round", "").split(" - ")[0] for f in F); out("Fases:", dict(rondas))
    terminados = [f for f in F if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")]
    muestra = sorted(terminados, key=lambda f: f["fixture"]["date"])[-1] if terminados else None

    if muestra:
        fid = muestra["fixture"]["id"]; h, a = muestra["teams"]["home"]["name"], muestra["teams"]["away"]["name"]
        out(f"\n--- 3. Partido de muestra: {h} {muestra['goals']['home']}-{muestra['goals']['away']} {a} ({muestra['fixture']['date'][:10]}, {muestra['league'].get('round')}) ---")
        ev = (api("fixtures/events", fixture=fid) or {}).get("response", [])
        out("Eventos:", len(ev), "· tipos:", dict(Counter(e.get("type") for e in ev)))
        for e in ev[:6]: out(f"  {e['time'].get('elapsed')}' {e.get('type')} {e.get('detail')} · {e['player'].get('name')} ({e['team'].get('name')})")
        lu = (api("fixtures/lineups", fixture=fid) or {}).get("response", [])
        for t in lu: out(f"Alineación {t['team']['name']}: formación {t.get('formation')}, titulares {len(t.get('startXI', []))}, banca {len(t.get('substitutes', []))}, DT {t.get('coach', {}).get('name')}")
        sts = (api("fixtures/statistics", fixture=fid) or {}).get("response", [])
        for t in sts: out(f"Estadísticas {t['team']['name']}:", ", ".join(f"{s['type']}={s['value']}" for s in t.get("statistics", [])[:10]))
        pl = (api("fixtures/players", fixture=fid) or {}).get("response", [])
        for t in pl:
            P = t.get("players", []); con = [p for p in P if p["statistics"][0]["games"].get("minutes")]
            out(f"Jugadores {t['team']['name']}: {len(P)} ({len(con)} con minutos)")
            for p in con[:3]:
                s = p["statistics"][0]
                out(f"  {p['player']['name']}: {s['games'].get('minutes')} min, calif. {s['games'].get('rating')}, tiros {s['shots'].get('total')}, pases {s['passes'].get('total')} ({s['passes'].get('accuracy')} buenos), entradas {s['tackles'].get('total')}")

    out("\n--- 4. Goleadores y asistidores de la temporada ---")
    for ruta, nombre, campo in [("players/topscorers", "Goleadores", "total"), ("players/topassists", "Asistidores", "assists")]:
        R = (api(ruta, league=LIGA, season=TEMP) or {}).get("response", [])
        out(f"{nombre} ({len(R)}):")
        for p in R[:10]:
            s = p["statistics"][0]; out(f"  {p['player']['name']} ({s['team']['name']}): {s['goals'].get(campo)} en {s['games'].get('appearences')} partidos")

    out(f"\n--- 5. Estadísticas de temporada de jugadores (muestra de {PAGINAS_JUGADORES} páginas) ---")
    J, total_pag = [], None
    for pg in range(1, PAGINAS_JUGADORES + 1):
        r = api("players", league=LIGA, season=TEMP, page=pg) or {}
        J += r.get("response", []); total_pag = r.get("paging", {}).get("total")
        if total_pag and pg >= total_pag: break
    out("Páginas totales en la API:", total_pag, f"(≈{(total_pag or 0)*20} jugadores; todo costaría {total_pag} pedidos)")
    S = [(p["player"], p["statistics"][0]) for p in J if p.get("statistics")]
    jug = [(pl, s) for pl, s in S if s["games"].get("minutes")]
    out("Jugadores en la muestra:", len(S), "· con minutos:", len(jug))
    campos = [("Minutos", lambda s: s["games"].get("minutes")), ("Posición", lambda s: s["games"].get("position")),
              ("Calificación", lambda s: s["games"].get("rating")), ("Tiros", lambda s: s["shots"].get("total")),
              ("Pases", lambda s: s["passes"].get("total")), ("Pases clave", lambda s: s["passes"].get("key")),
              ("Entradas", lambda s: s["tackles"].get("total")), ("Duelos", lambda s: s["duels"].get("total")),
              ("Regates", lambda s: s["dribbles"].get("attempts")), ("Faltas", lambda s: s["fouls"].get("committed")),
              ("Foto", None), ("Fecha de nacimiento", None), ("Nacionalidad", None)]
    out("Qué tan completos vienen los datos (jugadores con minutos):")
    for n, f in campos:
        if f: c = sum(1 for _, s in jug if f(s) not in (None, "", 0))
        elif n == "Foto": c = sum(1 for p, _ in jug if p.get("photo"))
        elif n == "Fecha de nacimiento": c = sum(1 for p, _ in jug if (p.get("birth") or {}).get("date"))
        else: c = sum(1 for p, _ in jug if p.get("nationality"))
        out(f"  {n}: {pct(c, len(jug))}")
    for pl, s in sorted(jug, key=lambda x: -(x[1]["games"].get("minutes") or 0))[:5]:
        out(f"  Ej.: {pl['name']} ({s['team']['name']}, {s['games'].get('position')}): {s['games'].get('minutes')} min, {s['goals'].get('total')} goles, {s['goals'].get('assists')} asist., calif. {s['games'].get('rating')}")

    out("\n--- 6. Lesiones ---")
    inj = (api("injuries", league=LIGA, season=TEMP) or {}).get("response", [])
    out("Registros:", len(inj))
    for i in inj[:5]: out(f"  {i['player'].get('name')} ({i['team'].get('name')}): {i['player'].get('type')} · {i['player'].get('reason')} · {i['fixture'].get('date','')[:10]}")

    out(f"\nPedidos usados en esta prueba: {usados}")

try:
    main()
except Exception as ex:
    out("Error inesperado:", str(ex).replace(KEY, "***") if KEY else ex)
with open("prueba_api_football.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lineas) + "\n")
