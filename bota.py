"""bota.py — Bota de Oro (8 oct 2026). La llama build_site.py: out['bota'] = bota(af, out.get('sel_plantel')).

Reglas (European Sports Media; revisadas el 8 oct 2026 con Wikipedia y la tabla de Planet Football del 21 sep):
  puntos = goles de liga × factor de la liga según el ranking UEFA de países (columna "2026", el que rige la temporada):
    ×2   lugares 1–5    · ×1.5 lugares 6–22    · ×1 el resto de Europa
  Solo goles de liga (no copas). Las ligas de año calendario (Suecia, Noruega, Letonia…) cuentan su temporada de este
  año (la 2026 para la Bota 2026-27). Empate: menos minutos, luego más asistencias, luego menos penales.
Datos: players/topscorers de cada primera división (los 20 primeros de cada liga; ~55 pedidos). Un jugador que cambió
de liga a media temporada suma sus goles de cada liga (ej. Ure: Sirius en Suecia y luego Sevilla).
Mexicanos: los de nacionalidad México entre los goleadores + los convocados de la Selección (out['sel_plantel']) que
juegan en Europa, con sus goles de players?id=&season= (~30 pedidos).

Formato: {"temp":"2026-27","al":"AAAA-MM-DD","ls":[fila…],"mex":[fila…],"faltan":[liga…]}
  fila = [id, nombre, nacionalidad, puntos, goles, minutos, asistencias, penales, clubes, ligas, factor máx, año calendario(0/1)]
"""
from datetime import datetime, timedelta, timezone

MX = timezone(timedelta(hours=-6))
# país (en español): (id de la primera división en API-Football, factor). Ids confirmados con probar_bota.py (8 oct 2026).
LIGAS = {
    "Inglaterra": (39, 2), "Italia": (135, 2), "España": (140, 2), "Alemania": (78, 2), "Francia": (61, 2),
    "Portugal": (94, 1.5), "Países Bajos": (88, 1.5), "Bélgica": (144, 1.5), "Turquía": (203, 1.5), "Chequia": (345, 1.5),
    "Grecia": (197, 1.5), "Polonia": (106, 1.5), "Dinamarca": (119, 1.5), "Noruega": (103, 1.5), "Chipre": (318, 1.5),
    "Suiza": (207, 1.5), "Austria": (218, 1.5), "Escocia": (179, 1.5), "Suecia": (113, 1.5), "Croacia": (210, 1.5),
    "Israel": (383, 1.5), "Hungría": (271, 1.5),
    "Rumania": (283, 1), "Ucrania": (333, 1), "Azerbaiyán": (419, 1), "Eslovenia": (373, 1), "Eslovaquia": (332, 1),
    "Bulgaria": (172, 1), "Serbia": (286, 1), "Rusia": (235, 1), "Islandia": (164, 1), "Irlanda": (357, 1), "Armenia": (342, 1),
    "Kosovo": (664, 1), "Bosnia": (315, 1), "Finlandia": (244, 1), "Letonia": (365, 1), "Lituania": (362, 1), "Estonia": (329, 1),
    "Bielorrusia": (116, 1), "Kazajistán": (389, 1), "Georgia": (327, 1), "Moldavia": (394, 1), "Macedonia del Norte": (371, 1),
    "Albania": (310, 1), "Montenegro": (355, 1), "Luxemburgo": (261, 1), "Malta": (393, 1), "Gales": (110, 1),
    "Irlanda del Norte": (408, 1), "Islas Feroe": (367, 1), "Andorra": (312, 1), "San Marino": (404, 1), "Gibraltar": (758, 1)}
NOMBRE_LIGA = {"Inglaterra": "Premier", "Italia": "Serie A", "España": "LaLiga", "Alemania": "Bundesliga", "Francia": "Ligue 1"}
CALENDARIO = {"Noruega", "Suecia", "Finlandia", "Islandia", "Irlanda", "Letonia", "Lituania", "Estonia", "Bielorrusia",
              "Kazajistán", "Georgia", "Islas Feroe"}
NAC_ES = {"Mexico": "México"}


def temporada(hoy=None):
    """Bota 2026-27 = temporada 2026 de API-Football (la europea 2026-27 y la de año calendario 2026)."""
    hoy = hoy or datetime.now(MX)
    return hoy.year if hoy.month >= 7 else hoy.year - 1


def bota(af, plantel=None, log=print, hoy=None):
    hoy = hoy or datetime.now(MX)
    T = temporada(hoy)
    J, faltan = {}, []
    por_id = {lid: (pais, f) for pais, (lid, f) in LIGAS.items()}
    def suma(pid, nombre, nac, pais, f, club, g, mins, asis, pen):
        if not pid or not g: return
        x = J.setdefault(pid, dict(n=nombre, nac=nac, ent={}))
        k = (pais, club)
        if k in x["ent"]: return   # misma liga y club ya contados
        x["ent"][k] = (f, g, mins or 0, asis or 0, pen or 0)
    for pais, (lid, f) in LIGAS.items():
        try: top = af("players/topscorers", league=lid, season=T)
        except Exception as e: log(f"  ! Bota de Oro {pais}: {e}"); top = []
        validos = 0
        for p in top:
            pl = p.get("player") or {}
            for st in p.get("statistics") or []:
                if (st.get("league") or {}).get("id") != lid: continue
                g = (st.get("goals") or {}).get("total") or 0
                if g: validos += 1
                suma(pl.get("id"), pl.get("name") or "", pl.get("nationality") or "", pais, f, (st.get("team") or {}).get("name") or "",
                     g, (st.get("games") or {}).get("minutes"), (st.get("goals") or {}).get("assists"), (st.get("penalty") or {}).get("scored"))
        if validos < 5: faltan.append(pais)
    # Convocados de la Selección que juegan en Europa (aunque no estén entre los 20 goleadores de su liga)
    mex_ids = set()
    for p in plantel or []:
        try: R = af("players", id=p.get("id"), season=T)
        except Exception: R = []
        for st in ((R[0].get("statistics") if R else None) or []):
            lid = (st.get("league") or {}).get("id")
            if lid in por_id:
                pais, f = por_id[lid]
                mex_ids.add(p.get("id"))
                suma(p.get("id"), (R[0].get("player") or {}).get("name") or p.get("n") or "", "Mexico", pais, f, (st.get("team") or {}).get("name") or "",
                     (st.get("goals") or {}).get("total") or 0, (st.get("games") or {}).get("minutes"), (st.get("goals") or {}).get("assists"),
                     (st.get("penalty") or {}).get("scored"))
                if not ((st.get("goals") or {}).get("total") or 0):   # sin goles: igual aparece en Mexicanos con 0
                    J.setdefault(p.get("id"), dict(n=(R[0].get("player") or {}).get("name") or p.get("n") or "", nac="Mexico", ent={}))
                    J[p.get("id")]["ent"].setdefault((pais, (st.get("team") or {}).get("name") or ""), (f, 0, (st.get("games") or {}).get("minutes") or 0, 0, 0))
    filas = []
    for pid, x in J.items():
        E = sorted(x["ent"].items(), key=lambda kv: -kv[1][1])   # la liga donde más goles lleva, primero
        pts = sum(f * g for _, (f, g, *_r) in E)
        filas.append([pid, x["n"], NAC_ES.get(x["nac"], x["nac"]), round(pts, 1), sum(v[1] for _, v in E), sum(v[2] for _, v in E),
                      sum(v[3] for _, v in E), sum(v[4] for _, v in E),
                      " / ".join(dict.fromkeys(c for (_p, c), _v in E)),
                      " · ".join(dict.fromkeys(NOMBRE_LIGA.get(p, p) for (p, _c), _v in E)),
                      max(v[0] for _, v in E), 1 if any(p in CALENDARIO for (p, _c), _v in E) else 0])
    filas.sort(key=lambda r: (-r[3], r[5] or 10**6, -r[6], r[7]))
    ls = [r for r in filas if r[3] > 0]
    mex = [r for r in filas if r[2] == "México" or r[0] in mex_ids]
    log(f"Bota de Oro {T}-{str(T + 1)[2:]}: {len(ls)} jugadores con goles, líder {ls[0][1]} {ls[0][3]} pts" if ls else "Bota de Oro: sin datos")
    return {"temp": f"{T}-{str(T + 1)[2:]}", "al": hoy.date().isoformat(), "ls": ls, "mex": mex, "faltan": faltan}
