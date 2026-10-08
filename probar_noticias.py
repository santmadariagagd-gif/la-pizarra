"""probar_noticias.py — prueba de "Noticias propias" (7 oct 2026).

No toca la página. La corre la automatización "Probar noticias" (botón Run workflow) y deja el reporte en
prueba_noticias.txt. Revisa qué tan completos vienen en API-Football los datos para armar notas cortas solas:
lesiones (injuries) por liga y fichajes (transfers) de algunos equipos de la Liga MX. Unos 30 pedidos.
La clave va en el secret API_FOOTBALL_KEY (la misma que usa la actualización de la página).
"""
import json, os, time, urllib.request, urllib.parse
from collections import Counter
from datetime import date, datetime, timedelta, timezone

BASE = "https://v3.football.api-sports.io"
KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
TEMP = 2026
HOY = datetime.now(timezone(timedelta(hours=-6))).date()   # fecha de México
LIGAS = [("mx", 262, "Liga MX"), ("eng", 39, "Premier League"), ("esp", 140, "La Liga"), ("ita", 135, "Serie A"),
         ("ger", 78, "Bundesliga"), ("fra", 61, "Ligue 1"), ("ucl", 2, "Champions League"), ("por", 94, "Liga Portugal"),
         ("arg", 128, "Liga Argentina")]
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

def R(ruta, **p): return (api(ruta, **p) or {}).get("response", []) or []

def fecha(s):
    try: return datetime.fromisoformat(str(s).replace("Z", "+00:00")).date()
    except Exception: return None

out(f"=== PRUEBA DE NOTICIAS PROPIAS (API-Football) · {HOY} ===")
if not KEY:
    out("! Falta el secret API_FOOTBALL_KEY"); open("prueba_noticias.txt", "w").write("\n".join(lineas) + "\n"); raise SystemExit(0)

# ---------------------------------------------------------------- 1. Lesiones por liga
out("\n=========== 1. Lesiones (injuries) por liga · temporada", TEMP, "===========")
out("Cobertura = lo que API-Football dice que trae; Registros = cuántas lesiones hay en la temporada;")
out("Últimos 7 días = registros ligados a partidos de la última semana o la que viene.")
resumen = []
for clave, lid, nombre in LIGAS:
    cov = None
    L = R("leagues", id=lid, season=TEMP)
    if L:
        for s in L[0].get("seasons", []):
            if s.get("year") == TEMP: cov = (s.get("coverage") or {}).get("injuries")
    inj = R("injuries", league=lid, season=TEMP)
    recientes = [x for x in inj if (d := fecha((x.get("fixture") or {}).get("date"))) and abs((d - HOY).days) <= 7]
    tipos = Counter((x.get("player") or {}).get("type") for x in inj)
    razones = Counter((x.get("player") or {}).get("reason") for x in inj)
    out(f"\n-- {nombre} (id {lid}) · cobertura: {cov} · registros: {len(inj)} · últimos 7 días: {len(recientes)}")
    out("   tipos:", dict(tipos.most_common(4)))
    out("   razones más comunes:", dict(razones.most_common(8)))
    # Muestra: lo más reciente, un renglón por jugador
    vistos, n = set(), 0
    for x in sorted(inj, key=lambda x: (x.get("fixture") or {}).get("date") or "", reverse=True):
        p, t, f = x.get("player") or {}, x.get("team") or {}, x.get("fixture") or {}
        if p.get("id") in vistos: continue
        vistos.add(p.get("id")); n += 1
        out(f"   · {str(f.get('date'))[:10]} · {t.get('name')} · {p.get('name')} · {p.get('type')} · {p.get('reason')}")
        if n >= 6: break
    resumen.append((nombre, cov, len(inj), len(recientes)))

# ---------------------------------------------------------------- 2. Lesiones de hoy (todas las ligas)
out("\n=========== 2. Lesiones de partidos de hoy (todas las ligas del mundo) ===========")
hoy = R("injuries", date=str(HOY))
out(f"Registros: {len(hoy)} · de nuestras ligas: {sum(1 for x in hoy if (x.get('league') or {}).get('id') in [l[1] for l in LIGAS])}")

# ---------------------------------------------------------------- 3. Fichajes de equipos de la Liga MX
out("\n=========== 3. Fichajes (transfers) · 5 equipos de la Liga MX ===========")
eqs = R("teams", league=262, season=TEMP)
desde = HOY - timedelta(days=150)
for e in eqs[:5]:
    t = e.get("team") or {}
    T = R("transfers", team=t.get("id"))
    movs = []
    for j in T:
        for m in j.get("transfers") or []:
            d = fecha(m.get("date"))
            if d and d >= desde: movs.append((d, (j.get("player") or {}).get("name"), (m.get("teams") or {}).get("out", {}).get("name"),
                                             (m.get("teams") or {}).get("in", {}).get("name"), m.get("type")))
    movs.sort(reverse=True)
    out(f"\n-- {t.get('name')} (id {t.get('id')}) · movimientos en los últimos 150 días: {len(movs)}")
    for d, jug, de, a, tipo in movs[:6]:
        out(f"   · {d} · {jug} · {de} → {a} · {tipo}")

# ---------------------------------------------------------------- Resumen
out("\n=========== Resumen ===========")
for nombre, cov, n, rec in resumen:
    out(f"{nombre:18} cobertura {str(cov):5} · {n:4} lesiones en la temporada · {rec:3} en la última semana")
out(f"\nPedidos usados en esta prueba: {usados}")
open("prueba_noticias.txt", "w").write("\n".join(lineas) + "\n")
