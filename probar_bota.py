"""probar_bota.py — prueba para la Bota de Oro (8 oct 2026). No toca la página.

La corre la automatización "Probar Bota de Oro" (botón Run workflow) y deja el reporte en prueba_bota.txt.
Revisa, país por país de la UEFA, qué ligas trae API-Football (para escoger la primera división de cada uno), si
tiene goleadores de la temporada actual y quiénes van arriba. Unos 110 pedidos (el plan deja 7,500 al día).
"""
import json, os, time, urllib.parse, urllib.request

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
# país en API-Football: id que creo que es la primera división (se confirma con el reporte)
PAISES = {"England": 39, "Spain": 140, "Italy": 135, "Germany": 78, "France": 61, "Portugal": 94, "Netherlands": 88,
          "Belgium": 144, "Turkey": 203, "Czech-Republic": 345, "Greece": 197, "Poland": 106, "Denmark": 119, "Norway": 103,
          "Cyprus": 318, "Switzerland": 207, "Austria": 218, "Scotland": 179, "Sweden": 113, "Croatia": 210, "Israel": 383,
          "Hungary": 271, "Romania": 283, "Ukraine": 333, "Azerbaidjan": 419, "Slovenia": 373, "Slovakia": 332, "Bulgaria": 172,
          "Serbia": 286, "Russia": 235, "Iceland": 164, "Ireland": 357, "Armenia": 342, "Kosovo": 664, "Bosnia": 315,
          "Finland": 244, "Latvia": 365, "Lithuania": 362, "Estonia": 329, "Belarus": 116, "Kazakhstan": 389, "Georgia": 327,
          "Moldova": 394, "Macedonia": 371, "Albania": 310, "Montenegro": 355, "Luxembourg": 261, "Malta": 393, "Wales": 110,
          "Northern-Ireland": 408, "Faroe-Islands": 367, "Andorra": 312, "San-Marino": 404, "Gibraltar": 758}
lineas = []
def out(*a):
    s = " ".join(str(x) for x in a); print(s); lineas.append(s)
usados = 0
def api(ruta, **q):
    global usados
    url = f"{BASE}/{ruta}" + ("?" + urllib.parse.urlencode(q) if q else "")
    for intento in range(3):
        time.sleep(0.25)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"x-apisports-key": KEY, "User-Agent": "LaPizarra/1.0"}), timeout=40) as r:
                j = json.loads(r.read().decode("utf-8")); usados += 1
        except Exception as e:
            out(f"  ! {ruta} {q}: {str(e).replace(KEY, '***')}"); return []
        e = j.get("errors")
        if e and "rateLimit" in json.dumps(e) and intento < 2: time.sleep(5); continue
        if e and (not isinstance(e, list) or e): out(f"  ! {ruta} {q}: {e}")
        return j.get("response") or []
    return []

out("=== PRUEBA BOTA DE ORO (API-Football) ===")
for pais, lid in PAISES.items():
    L = api("leagues", country=pais, type="league")
    resumen = []
    for x in L:
        lg, ss = x.get("league") or {}, x.get("seasons") or []
        cur = next((s for s in ss if s.get("current")), ss[-1] if ss else {})
        resumen.append(f"{lg.get('id')}={lg.get('name')} ({cur.get('year')}{', goleo' if (cur.get('coverage') or {}).get('top_scorers') else ''})")
    out(f"\n-- {pais}: " + " | ".join(resumen[:8]))
    sel = next((x for x in L if (x.get("league") or {}).get("id") == lid), None)
    if not sel:
        out(f"   ! el id {lid} no está entre las ligas de {pais}"); continue
    ss = sel.get("seasons") or []
    cur = next((s for s in ss if s.get("current")), ss[-1] if ss else {})
    temp = cur.get("year")
    top = api("players/topscorers", league=lid, season=temp)
    out(f"   ELEGIDA {lid} {sel['league']['name']} · temporada {temp} ({cur.get('start')} a {cur.get('end')}) · goleadores: {len(top)}")
    for p in top[:3]:
        st = p["statistics"][0]
        out(f"     {p['player']['name']} ({st['team']['name']}): {st['goals']['total']} goles, {st['games']['minutes']} min, "
            f"{st['goals'].get('assists')} asist, penales {st.get('penalty', {}).get('scored')}, nacionalidad {p['player'].get('nationality')}")
out(f"\nPedidos usados: {usados}")
open("prueba_bota.txt", "w").write("\n".join(lineas) + "\n")
