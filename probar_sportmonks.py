"""probar_sportmonks.py — prueba de calidad de Sportmonks (Football API v3).

No toca la página. Lo corre la automatización "Probar Sportmonks" (botón Run workflow) y deja el
reporte en prueba_sportmonks.txt dentro del repositorio. La clave va en el secret SPORTMONKS_KEY.

Con la cuenta gratis solo hay 2 ligas (Dinamarca y Escocia): sirve para ver CÓMO vienen los datos.
Con la prueba de 14 días del plan Growth, el mismo script revisa las ligas que escojas (Liga MX, etc.).
Revisa: ligas de la suscripción, ids de las ligas que nos interesan, tabla, goleadores y asistidores,
partidos recientes y próximos, un partido completo (eventos, alineaciones, formaciones, DT,
estadísticas de equipo y de jugador), bajas antes de un partido, duelos previos, plantel, Selección
mexicana y partidos en vivo. Unos 30–60 pedidos (el límite es 2,000 por hora por tipo de dato).
"""
import json, os, time, urllib.request, urllib.parse, urllib.error
from collections import Counter
from datetime import date, timedelta

BASE = "https://api.sportmonks.com/v3/football"
KEY = os.environ.get("SPORTMONKS_KEY", "").strip()
HOY = date.today()
lineas = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lineas.append(s)

usados = 0
ultimo_limite = {}
def api(ruta, **params):
    """Pide una ruta. Regresa el JSON o None (y anota el error en el reporte)."""
    global usados, ultimo_limite
    url = f"{BASE}/{ruta}" + ("?" + urllib.parse.urlencode(params, safe=";:,") if params else "")
    time.sleep(0.4)
    req = urllib.request.Request(url, headers={"Authorization": KEY, "Accept": "application/json", "User-Agent": "LaPizarra/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            j = json.loads(r.read().decode("utf-8")); usados += 1
    except urllib.error.HTTPError as ex:
        cuerpo = ""
        try: cuerpo = ex.read().decode("utf-8")[:300]
        except Exception: pass
        out(f"  ! {ruta} → HTTP {ex.code}: {cuerpo.replace(KEY, '***')}"); return None
    except Exception as ex:
        out(f"  ! {ruta} falló: {str(ex).replace(KEY, '***')}"); return None
    if j.get("rate_limit"): ultimo_limite = j["rate_limit"]
    if j.get("message") and not j.get("data"):
        out(f"  ! {ruta}: {j.get('message')}")
    return j

def datos(j):
    d = (j or {}).get("data")
    return d if d is not None else []

def pct(n, d): return f"{round(100*n/d)}%" if d else "–"
def nombre_tipo(x): return ((x.get("type") or {}).get("name") or (x.get("type") or {}).get("developer_name") or f"tipo {x.get('type_id')}")
def equipos(fx):
    P = fx.get("participants") or []
    loc = next((p for p in P if (p.get("meta") or {}).get("location") == "home"), P[0] if P else {})
    vis = next((p for p in P if (p.get("meta") or {}).get("location") == "away"), P[1] if len(P) > 1 else {})
    return loc, vis
def marcador(fx):
    loc, vis = equipos(fx); g = {}
    for s in fx.get("scores") or []:
        if s.get("description") == "CURRENT":
            sc = s.get("score") or {}; g[sc.get("participant")] = sc.get("goals")
    return f"{loc.get('name','?')} {g.get('home','?')}-{g.get('away','?')} {vis.get('name','?')}"
def estado(fx): return (fx.get("state") or {}).get("short_name") or (fx.get("state") or {}).get("state") or fx.get("state_id")

# ---------------------------------------------------------------- 1. Suscripción
def suscripcion():
    out("=========== 1. Ligas de tu suscripción ===========")
    j = api("leagues", include="currentSeason;country", per_page=50)
    L = datos(j)
    if j and j.get("subscription"):
        out("Suscripción:", json.dumps(j["subscription"], ensure_ascii=False)[:600])
    out(f"Ligas a las que tienes acceso: {len(L)}")
    for l in L:
        cs = l.get("currentseason") or l.get("current_season") or {}
        out(f"  id {l.get('id')} · {l.get('name')} ({(l.get('country') or {}).get('name','')}) · temporada actual: {cs.get('name')} (id {cs.get('id')})")
    return L

# ---------------------------------------------------------------- 2. Buscar las ligas que nos interesan
BUSCAR = ["Liga MX", "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1", "Champions League",
          "Friendlies", "Gold Cup", "Nations League", "World Cup"]
def buscar_ligas():
    out("\n=========== 2. Ids de las ligas que nos interesan (para escogerlas en el plan) ===========")
    for q in BUSCAR:
        L = datos(api(f"leagues/search/{urllib.parse.quote(q)}", include="country"))
        if not L: out(f"  {q}: sin resultados (puede ser que el plan gratis no deje buscar fuera de tus ligas)"); continue
        out(f"  {q}: " + " | ".join(f"{l.get('id')} {l.get('name')} ({(l.get('country') or {}).get('name','')})" for l in L[:6]))

# ---------------------------------------------------------------- 3. Revisión de una liga
def revisar_liga(l):
    lid = l.get("id"); cs = l.get("currentseason") or l.get("current_season") or {}; sid = cs.get("id")
    out(f"\n=========== 3. {l.get('name')} (id {lid}) · temporada {cs.get('name')} (id {sid}) ===========")
    if not sid: out("Sin temporada actual."); return

    # Tabla
    T = datos(api(f"standings/seasons/{sid}", include="participant;details.type"))
    out(f"Tabla: {len(T)} renglones")
    for r in sorted(T, key=lambda x: x.get("position") or 99)[:3]:
        det = {nombre_tipo(d): d.get("value") for d in r.get("details") or []}
        clave = {k: v for k, v in det.items() if any(w in k.lower() for w in ("played", "won", "draw", "lost", "goal"))}
        out(f"  {r.get('position')}. {(r.get('participant') or {}).get('name')} · {r.get('points')} pts · {json.dumps(clave, ensure_ascii=False)[:200]}")
    if T: out("  Datos por renglón:", ", ".join(sorted({nombre_tipo(d) for d in T[0].get('details') or []}))[:400])

    # Goleadores y asistidores (208 = goles, 209 = asistencias)
    for tid, nom in [(208, "Goleadores"), (209, "Asistidores")]:
        G = datos(api(f"topscorers/seasons/{sid}", include="player;participant", filters=f"seasonTopscorerTypes:{tid}", per_page=10))
        out(f"{nom} (top 5 de {len(G)}):")
        for g in sorted(G, key=lambda x: x.get("position") or 99)[:5]:
            out(f"  {g.get('position')}. {(g.get('player') or {}).get('display_name') or (g.get('player') or {}).get('name')} ({(g.get('participant') or {}).get('name')}): {g.get('total')}")

    # Partidos de las últimas 3 semanas y las próximas 2
    ini, fin = HOY - timedelta(days=21), HOY + timedelta(days=14)
    F = datos(api(f"fixtures/between/{ini}/{fin}", filters=f"fixtureLeagues:{lid}", include="participants;scores;state;round", per_page=50))
    out(f"Partidos del {ini} al {fin}: {len(F)} · estados: {dict(Counter(estado(f) for f in F))}")
    jugados = [f for f in F if estado(f) in ("FT", "AET", "FT_PEN", "AP", "PEN")]
    proximos = [f for f in F if estado(f) in ("NS", "TBA")]
    if F:
        f0 = F[0]; out(f"  Ejemplo: {marcador(f0)} · {f0.get('starting_at')} · jornada: {(f0.get('round') or {}).get('name')}")
    if jugados: revisar_partido(sorted(jugados, key=lambda f: f.get("starting_at") or "")[-1]["id"])
    else: out("  No hay partidos terminados en ese rango.")
    if proximos: revisar_previa(sorted(proximos, key=lambda f: f.get("starting_at") or "")[0]["id"])

def revisar_partido(fid):
    inc = "participants;scores;state;venue;events.type;lineups.details.type;lineups.position;statistics.type;formations;coaches;periods"
    fx = datos(api(f"fixtures/{fid}", include=inc))
    if not fx:   # si algún include no lo permite el plan, se vuelve a pedir con lo básico
        out("  (reintento con menos datos)")
        fx = datos(api(f"fixtures/{fid}", include="participants;scores;state;events;lineups.details.type;statistics.type"))
    if not fx: return
    out(f"\n  --- Partido completo: {marcador(fx)} ({fx.get('starting_at')}, {(fx.get('venue') or {}).get('name')}) ---")
    E = fx.get("events") or []
    out(f"  Eventos: {len(E)} · {dict(Counter(nombre_tipo(e) for e in E).most_common(8))}")
    for e in E[:4]: out(f"    {e.get('minute')}' {nombre_tipo(e)}: {e.get('player_name')} {('→ ' + str(e.get('related_player_name'))) if e.get('related_player_name') else ''}")
    Lu = fx.get("lineups") or []
    tit = [x for x in Lu if x.get("type_id") == 11]; banca = [x for x in Lu if x.get("type_id") == 12]
    out(f"  Alineaciones: {len(Lu)} jugadores ({len(tit)} titulares, {len(banca)} banca) · formaciones: {[f.get('formation') for f in fx.get('formations') or []]}")
    out(f"  Posiciones de los titulares: {dict(Counter((x.get('position') or {}).get('name') for x in tit))}")
    out(f"  Coordenadas en cancha (formation_field): {pct(sum(1 for x in tit if x.get('formation_field')), len(tit))} de titulares")
    out(f"  DT: {[c.get('name') or c.get('display_name') for c in fx.get('coaches') or []]}")
    S = fx.get("statistics") or []
    out(f"  Estadísticas de equipo: {len(S)} datos · {', '.join(sorted({nombre_tipo(s) for s in S}))[:500]}")
    con_det = [x for x in Lu if x.get("details")]
    cnt = Counter(nombre_tipo(d) for x in con_det for d in x.get("details") or [])
    out(f"  Estadísticas por jugador: {len(con_det)} de {len(Lu)} jugadores traen datos")
    jug_min = [x for x in con_det if any("minute" in nombre_tipo(d).lower() for d in x["details"])] or con_det
    out("  Qué tan completos (de los que jugaron): " + ", ".join(f"{k} {pct(v, len(jug_min))}" for k, v in cnt.most_common(18)))
    rt = [(x.get("player_name"), d.get("data", {}).get("value")) for x in con_det for d in x["details"] if "rating" in nombre_tipo(d).lower()]
    if rt: out(f"  Calificación (ej.): {rt[:3]}")
    loc, vis = equipos(fx)
    if loc.get("id") and vis.get("id"):
        H = datos(api(f"fixtures/head-to-head/{loc['id']}/{vis['id']}", include="participants;scores;state"))
        out(f"  Duelos previos: {len(H)}" + (f" · el más reciente: {marcador(sorted(H, key=lambda f: f.get('starting_at') or '')[-1])}" if H else ""))
        Q = datos(api(f"squads/teams/{loc['id']}", include="player;position"))
        out(f"  Plantel de {loc.get('name')}: {len(Q)} jugadores · posiciones: {dict(Counter((q.get('position') or {}).get('name') for q in Q))}")
        img = [p.get("image_path") for p in (loc, vis) if p.get("image_path")]
        out(f"  Escudo/foto: el API trae imágenes ({len(img)} escudos), pero sus términos dicen que los derechos son de cada dueño: no se usarán.")

def revisar_previa(fid):
    fx = datos(api(f"fixtures/{fid}", include="participants;state;sidelined.sideline.type;sidelined.player;lineups;weatherReport"))
    if not fx:
        out("  (reintento con menos datos)")
        fx = datos(api(f"fixtures/{fid}", include="participants;state;sidelined.sideline;lineups"))
    if not fx: return
    out(f"\n  --- Previa: {marcador(fx)} ({fx.get('starting_at')}) ---")
    B = fx.get("sidelined") or []
    out(f"  Bajas antes del partido: {len(B)}")
    for b in B[:5]:
        sl = b.get("sideline") or {}
        out(f"    {(b.get('player') or {}).get('display_name') or (b.get('player') or {}).get('name')} · {nombre_tipo(sl) if sl else '?'} · desde {sl.get('start_date')} hasta {sl.get('end_date')}")
    out(f"  Alineación probable/confirmada ya publicada: {len(fx.get('lineups') or [])} jugadores")
    out(f"  Clima del partido: {'sí' if fx.get('weatherreport') or fx.get('weather_report') else 'no'}")

# ---------------------------------------------------------------- 4. Selección mexicana
def seleccion():
    out("\n=========== 4. Selección mexicana ===========")
    T = datos(api("teams/search/Mexico", include="country"))
    nac = [t for t in T if t.get("type") == "national"] or T
    out("Equipos encontrados: " + " | ".join(f"{t.get('id')} {t.get('name')} ({t.get('type')})" for t in T[:6]))
    if not nac: return
    tid = nac[0]["id"]
    F = datos(api(f"fixtures/between/{HOY - timedelta(days=100)}/{HOY + timedelta(days=60)}/{tid}", include="participants;scores;state;league", per_page=50))
    out(f"Partidos de {nac[0].get('name')} (últimos 100 días y próximos 60): {len(F)}")
    for f in sorted(F, key=lambda f: f.get("starting_at") or "")[-6:]:
        out(f"  {str(f.get('starting_at'))[:10]} · {(f.get('league') or {}).get('name')} · {marcador(f)} · {estado(f)}")

# ---------------------------------------------------------------- 5. En vivo
def en_vivo():
    out("\n=========== 5. En vivo ahora ===========")
    V = datos(api("livescores/inplay", include="participants;scores;state;league"))
    out(f"Partidos en vivo que ve tu plan: {len(V)}")
    for f in V[:5]: out(f"  {(f.get('league') or {}).get('name')} · {marcador(f)} · {estado(f)}")

def main():
    if not KEY: out("Falta el secret SPORTMONKS_KEY."); return
    out(f"=== PRUEBA SPORTMONKS · {HOY} ===")
    L = suscripcion()
    buscar_ligas()
    for l in L[:12]:
        try: revisar_liga(l)
        except Exception as ex: out(f"  ! Error revisando {l.get('name')}: {ex}")
    for paso in (seleccion, en_vivo):
        try: paso()
        except Exception as ex: out(f"  ! Error en {paso.__name__}: {ex}")
    out(f"\nPedidos usados: {usados} · último límite reportado: {json.dumps(ultimo_limite)}")

if __name__ == "__main__":
    try: main()
    finally:
        with open("prueba_sportmonks.txt", "w", encoding="utf-8") as f: f.write("\n".join(lineas) + "\n")
