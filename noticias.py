"""noticias.py — "Lo último": titulares cortos que La Pizarra arma sola con datos que ya tiene (7 oct 2026).

Sin textos de otros medios: cada nota se escribe aquí con datos de API-Football (fútbol) y nflverse (NFL).
Solo noticias de la semana: lo que pasó en los últimos 7 días, rachas de equipos que juegan en los próximos 7 días
y avisos de lesión o suspensión para los partidos de los próximos 7 días.

Cada nota: {tipo, liga, eq, t (fecha ISO), tit (titular), det (renglón de detalle), peso (importancia),
            fx (id del partido de API-Football, para abrirlo) o nid (id del partido de la NFL)}
Tipos: lesion · suspension · racha · goles · fichaje · tecnico

Uso:
  - En build_site.py: from noticias import generar; out['noticias'] = generar(af, propiedad, sched=out['sched'])
  - Prueba sola (automatización "Probar noticias"): python noticias.py  → prueba_noticias.txt + noticias_muestra.json
"""
import csv, io, json, os, re, time, unicodedata, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MX = timezone(timedelta(hours=-6))
TEMP = 2026
# liga: (id API-Football, nombre, ¿API-Football trae lesiones?)
LIGAS = {"mx": (262, "Liga MX", False), "eng": (39, "Premier League", True), "esp": (140, "La Liga", True),
         "ita": (135, "Serie A", True), "ger": (78, "Bundesliga", True), "fra": (61, "Ligue 1", True),
         "ucl": (2, "Champions League", True)}
EQ_MX = {2278: "Guadalajara", 2279: "Tigres", 2280: "Tijuana", 2281: "Toluca", 2282: "Monterrey", 2283: "Atlas",
         2285: "Santos Laguna", 2286: "Pumas", 2287: "América", 2288: "Necaxa", 2289: "León", 2290: "Querétaro",
         2291: "Puebla", 2292: "Pachuca", 2295: "Cruz Azul", 2298: "Juárez", 2312: "Atlante", 2314: "Atlético San Luis",
         14002: "Mazatlán"}
FAMA = {"club america": 3, "guadalajara chivas": 3, "cruz azul": 3, "u.n.a.m. - pumas": 3, "tigres uanl": 3, "monterrey": 3,
        "toluca": 2, "cf pachuca": 2, "leon": 2, "santos laguna": 2, "atlas": 2,
        "real madrid": 3, "barcelona": 3, "manchester united": 3, "liverpool": 3, "manchester city": 3, "arsenal": 3, "chelsea": 3,
        "bayern munchen": 3, "paris saint germain": 3, "juventus": 3, "inter": 3, "ac milan": 3,
        "atletico madrid": 2, "tottenham": 2, "borussia dortmund": 2, "napoli": 2, "as roma": 2, "lazio": 2, "marseille": 2,
        "newcastle": 2, "bayer leverkusen": 2, "aston villa": 1, "real betis": 1, "sevilla": 1, "athletic club": 1, "atalanta": 1}
# Nombres en español de equipos de Europa que se leen raro en inglés
EQ_ES = {"Bayern München": "Bayern Múnich", "Inter": "Inter de Milán", "AC Milan": "Milan", "Atletico Madrid": "Atlético de Madrid",
         "Paris Saint Germain": "PSG", "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen", "Real Betis": "Betis",
         "Athletic Club": "Athletic", "AS Roma": "Roma", "Olympique Marseille": "Marsella", "Marseille": "Marsella",
         "FC Augsburg": "Augsburgo", "Alaves": "Alavés", "Atletico Madrid": "Atlético de Madrid", "Sevilla": "Sevilla"}
LESION_ES = {"knee": "la rodilla", "muscle": "MUSCULAR", "hamstring": "el isquiotibial", "ankle": "el tobillo", "thigh": "el muslo",
             "calf": "la pantorrilla", "back": "la espalda", "shoulder": "el hombro", "groin": "la ingle", "adductor": "el aductor",
             "foot": "el pie", "hip": "la cadera", "achilles": "el tendón de Aquiles", "concussion": "conmoción", "head": "la cabeza",
             "illness": "enfermedad", "abdominal": "el abdomen", "toe": "un dedo del pie", "thumb": "el pulgar", "finger": "un dedo",
             "hand": "la mano", "wrist": "la muñeca", "elbow": "el codo", "rib": "las costillas", "chest": "el pecho", "neck": "el cuello",
             "quad": "el cuádriceps", "leg": "la pierna", "heel": "el talón", "pelvis": "la pelvis", "fracture": "fractura",
             "cruciate": "el ligamento cruzado", "jumpers knee": "tendinitis en la rodilla", "virus": "enfermedad",
             "health": "problemas de salud", "personal": "motivos personales", "covid": "enfermedad"}
NO_LESION = ("coach's decision", "inactive", "off the roster", "loan agreement", "not registered", "international duty", "lack of fitness")
SUSP = ("red card", "yellow card", "suspended", "suspension")
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def sin_acentos(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def lesion_es(razon):
    """'Knee Injury' → 'lesión en la rodilla'; 'Muscle Injury' → 'lesión muscular'; 'Illness' → 'enfermedad'."""
    r = sin_acentos(razon)
    for k in sorted(LESION_ES, key=len, reverse=True):
        if k in r:
            v = LESION_ES[k]
            if v == "MUSCULAR": return "lesión muscular"
            if v in ("enfermedad", "problemas de salud", "motivos personales", "conmoción", "fractura", "tendinitis en la rodilla"): return v
            return "lesión en " + v
    return "lesión"


def fecha_mx(s):
    try: return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(MX)
    except Exception: return None


def eq_nombre(t, lg):
    if lg == "mx" and t.get("id") in EQ_MX: return EQ_MX[t["id"]]
    return EQ_ES.get(t.get("name"), t.get("name") or "")


def fama(t): return FAMA.get(sin_acentos(t.get("name")), 0)


def corto(nombre):
    """'C. Palmer' → 'Palmer'; 'Joao Pedro' y 'Raphinha' se quedan igual."""
    m = re.match(r"^[A-ZÁÉÍÓÚÑ][a-z]?\.\s+(.+)$", str(nombre or "").strip())
    return m.group(1) if m else str(nombre or "").strip()


def dia(d, hoy):
    """'hoy', 'mañana', 'ayer' o el día de la semana ('sábado')."""
    dd = (d.date() - hoy.date()).days
    return {0: "hoy", 1: "mañana", -1: "ayer"}.get(dd, DIAS[d.weekday()])


def nota(tipo, liga, eq, t, tit, det, peso, **extra):
    return dict(tipo=tipo, liga=liga, eq=eq, t=str(t), tit=tit, det=det, peso=round(float(peso), 1), **extra)


# ------------------------------------------------------------------ Fútbol
def futbol(af, hoy, log=print):
    notas = []
    ini, fin = hoy - timedelta(days=7), hoy + timedelta(days=7)
    for lg, (lid, lnom, con_lesiones) in LIGAS.items():
        try:
            fx = af("fixtures", league=lid, season=TEMP)
        except Exception as e:
            log(f"  ! {lnom} partidos: {e}"); continue
        jugados = sorted([f for f in fx if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")], key=lambda f: f["fixture"]["date"])
        semana = [f for f in jugados if (d := fecha_mx(f["fixture"]["date"])) and d >= ini]
        prox = {}   # equipo → (su siguiente partido, lado del rival)
        for f in sorted(fx, key=lambda f: f["fixture"]["date"]):
            if f["fixture"]["status"]["short"] in ("NS", "TBD"):
                for lado, otro in (("home", "away"), ("away", "home")):
                    prox.setdefault(f["teams"][lado]["id"], (f, otro))
        por_id = {f["fixture"]["id"]: f for f in fx}

        # --- Rachas: si siguieron esta semana, o si el equipo juega en los próximos 7 días ("llega con…")
        hist = defaultdict(list)
        for f in jugados:
            gh, ga = f["goals"]["home"], f["goals"]["away"]
            if gh is None or ga is None: continue
            for lado, gf, gc in (("home", gh, ga), ("away", ga, gh)):
                hist[f["teams"][lado]["id"]].append((f, "G" if gf > gc else "E" if gf == gc else "P", f["teams"][lado]))
        for tid, h in hist.items():
            ult_f, _, team = h[-1]
            jugo = fecha_mx(ult_f["fixture"]["date"]) >= ini
            sig = prox.get(tid)
            sig_d = fecha_mx(sig[0]["fixture"]["date"]) if sig else None
            llega = (not jugo) and sig_d is not None and sig_d <= fin
            if not jugo and not llega: continue
            def racha(cond):
                n = 0
                for _, r, _ in reversed(h):
                    if not cond(r): break
                    n += 1
                return n
            g, sp, sg, p = racha(lambda r: r == "G"), racha(lambda r: r != "P"), racha(lambda r: r != "G"), racha(lambda r: r == "P")
            if p >= 4 and p >= sg: que, peso = f"{p} derrotas seguidas", 5 + p
            elif g >= 4: que, peso = f"{g} victorias seguidas", 6 + g
            elif sp >= 7 and sp > g: que, peso = f"{sp} partidos sin perder", 4 + sp / 2
            elif sg >= 5: que, peso = f"{sg} partidos sin ganar", 4 + sg / 2
            else: continue
            nom = eq_nombre(team, lg)
            if llega:
                rival = eq_nombre(sig[0]["teams"][sig[1]], lg)
                notas.append(nota("racha", lg, nom, sig[0]["fixture"]["date"], f"{nom} llega con {que}",
                                  f"{dia(sig_d, hoy).capitalize()} contra {rival}", peso - 1 + fama(team), fx=sig[0]["fixture"]["id"]))
            else:
                notas.append(nota("racha", lg, nom, ult_f["fixture"]["date"], f"{nom} suma {que}",
                                  f"Último partido: {dia(fecha_mx(ult_f['fixture']['date']), hoy)}", peso + fama(team), fx=ult_f["fixture"]["id"]))

        # --- Goleadas de la semana
        for f in semana:
            gh, ga = f["goals"]["home"], f["goals"]["away"]
            if gh is None or abs(gh - ga) < 4: continue
            gana, pierde = ("home", "away") if gh > ga else ("away", "home")
            d = fecha_mx(f["fixture"]["date"])
            notas.append(nota("goles", lg, eq_nombre(f["teams"][gana], lg), f["fixture"]["date"],
                              f"{eq_nombre(f['teams'][gana], lg)} goleó {max(gh, ga)}-{min(gh, ga)} a {eq_nombre(f['teams'][pierde], lg)}",
                              f"{dia(d, hoy).capitalize()}", 5 + abs(gh - ga) + fama(f["teams"][gana]) + fama(f["teams"][pierde]), fx=f["fixture"]["id"]))

        # --- Líder(es) de goleo (antes de los eventos, para no repetir "triplete" y "líder" del mismo jugador)
        try: top = af("players/topscorers", league=lid, season=TEMP)
        except Exception as e: top = []; log(f"  ! {lnom} goleo: {e}")
        mxg = (top[0]["statistics"][0]["goals"]["total"] or 0) if top else 0
        lideres = {x["player"]["id"] for x in top if (x["statistics"][0]["goals"]["total"] or 0) == mxg and mxg >= 3}

        # --- Eventos de los partidos de la semana (goles por jugador y expulsiones): fixtures?ids= de 20 en 20
        goles_sem = defaultdict(int)
        ids = [f["fixture"]["id"] for f in semana]
        det = []
        for i in range(0, len(ids), 20):
            try: det += af("fixtures", ids="-".join(map(str, ids[i:i + 20])))
            except Exception as e: log(f"  ! {lnom} eventos: {e}")
        for f in det:
            d = fecha_mx(f["fixture"]["date"])
            por_jug = defaultdict(int)
            for ev in f.get("events") or []:
                t, pl = ev.get("team") or {}, ev.get("player") or {}
                if ev.get("type") == "Goal" and ev.get("detail") in ("Normal Goal", "Penalty") and (ev.get("comments") or "") != "Penalty Shootout":
                    por_jug[(pl.get("id"), pl.get("name"), t.get("id"))] += 1
                    goles_sem[pl.get("id")] += 1
                if ev.get("type") == "Card" and ev.get("detail") in ("Red Card", "Second Yellow card"):
                    rival = f["teams"]["away" if f["teams"]["home"]["id"] == t.get("id") else "home"]
                    sig = prox.get(t.get("id"))
                    como = "doble amarilla" if ev.get("detail") == "Second Yellow card" else "roja directa"
                    det_txt = f"{eq_nombre(t, lg)} · {como}" + (f" · próximo: contra {eq_nombre(sig[0]['teams'][sig[1]], lg)}" if sig else "")
                    notas.append(nota("suspension", lg, eq_nombre(t, lg), f["fixture"]["date"],
                                      f"{corto(pl.get('name'))}, expulsado ante {eq_nombre(rival, lg)}", det_txt, 4 + fama(t), fx=f["fixture"]["id"]))
            for (pid, pn, tid), n in por_jug.items():
                if n >= 3 and pid not in lideres:
                    local = f["teams"]["home"]["id"] == tid
                    tm, rival = (f["teams"]["home"], f["teams"]["away"]) if local else (f["teams"]["away"], f["teams"]["home"])
                    notas.append(nota("goles", lg, eq_nombre(tm, lg), f["fixture"]["date"],
                                      f"{'Triplete' if n == 3 else f'{n} goles'} de {corto(pn)} ante {eq_nombre(rival, lg)}",
                                      f"{eq_nombre(tm, lg)} · {dia(d, hoy)}", 9 + fama(tm), fx=f["fixture"]["id"]))

        # --- Líder de goleo que anotó esta semana
        for x in top:
            st = x["statistics"][0]; gt = st["goals"]["total"] or 0
            if gt < mxg or mxg < 3: break
            pid = x["player"]["id"]
            if goles_sem[pid] > 0:
                tm = st["team"]
                lider = "comparte el liderato de goleo" if len(lideres) > 1 else "líder de goleo"
                hizo = "triplete" if goles_sem[pid] == 3 else f"{goles_sem[pid]} goles" if goles_sem[pid] > 1 else "gol"
                notas.append(nota("goles", lg, eq_nombre(tm, lg), hoy.isoformat(), f"{corto(x['player']['name'])} llega a {gt} goles",
                                  f"{eq_nombre(tm, lg)} · {hizo} esta semana · {lider}", 8 + fama(tm)))

        # --- Lesiones y suspensiones que avisa API-Football para los próximos 7 días
        if con_lesiones:
            try: inj = af("injuries", league=lid, season=TEMP)
            except Exception as e: inj = []; log(f"  ! {lnom} lesiones: {e}")
            imp = {x["player"]["id"] for x in top[:15]}
            try: imp |= {x["player"]["id"] for x in af("players/topassists", league=lid, season=TEMP)[:10]}
            except Exception: pass
            vistos, cand = set(), []
            for x in sorted(inj, key=lambda x: (x.get("fixture") or {}).get("date") or ""):
                pl, t, fxi = x.get("player") or {}, x.get("team") or {}, x.get("fixture") or {}
                d = fecha_mx(fxi.get("date"))
                if not d or not (hoy - timedelta(hours=12) <= d <= fin) or pl.get("id") in vistos: continue
                vistos.add(pl.get("id"))
                razon = sin_acentos(pl.get("reason"))
                if any(k in razon for k in NO_LESION): continue
                f0 = por_id.get(fxi.get("id"))
                rival = ""
                if f0:
                    otro = "away" if f0["teams"]["home"]["id"] == t.get("id") else "home"
                    rival = eq_nombre(f0["teams"][otro], lg)
                nom, quien = eq_nombre(t, lg), corto(pl.get("name"))
                ante = f" ante {rival}" if rival else ""
                if any(k in razon for k in SUSP):
                    tipo, tit, det_txt = "suspension", f"{quien}, suspendido{ante}", f"{nom} · {dia(d, hoy)}"
                elif pl.get("type") == "Questionable":
                    tipo, tit, det_txt = "lesion", f"{quien}, en duda{ante}", f"{nom} · {lesion_es(pl.get('reason'))} · {dia(d, hoy)}"
                else:
                    tipo, tit, det_txt = "lesion", f"{quien}, baja{ante}", f"{nom} · {lesion_es(pl.get('reason'))} · {dia(d, hoy)}"
                peso = (6 if pl.get("id") in imp else 0) + 2 * fama(t)
                if peso >= 4: cand.append(nota(tipo, lg, nom, fxi.get("date"), tit, det_txt, peso, fx=fxi.get("id")))
            cand.sort(key=lambda n: -n["peso"])
            por_eq, n_liga = defaultdict(int), 0
            for n in cand:
                if por_eq[n["eq"]] >= 2: continue
                por_eq[n["eq"]] += 1; n_liga += 1; notas.append(n)
                if n_liga >= 5: break
    return notas


def liga_mx_mercado(af, hoy, log=print):
    """Fichajes y cambios de técnico de la Liga MX en los últimos 7 días (2 pedidos por equipo)."""
    notas, ini = [], (hoy - timedelta(days=7)).date()
    for tid, nom in EQ_MX.items():
        if tid == 2312: continue   # Atlante no está en el torneo
        try: T = af("transfers", team=tid)
        except Exception as e: log(f"  ! fichajes {nom}: {e}"); T = []
        vistos = set()
        for j in T:
            pj = j.get("player") or {}
            for m in j.get("transfers") or []:
                try: d = datetime.fromisoformat(m.get("date")).date()
                except Exception: continue
                if d < ini or d > hoy.date(): continue
                tin, tout = (m.get("teams") or {}).get("in") or {}, (m.get("teams") or {}).get("out") or {}
                if tin.get("id") == tout.get("id"): continue
                if re.search(r"\b(U\d\d|Sub-?\d\d|II|B)\b|Tapat|Premier|Reserv", f"{tin.get('name')} {tout.get('name')}"): continue
                if (pj.get("id"), d) in vistos: continue
                vistos.add((pj.get("id"), d))
                modo = {"Loan": "a préstamo", "Free": "como agente libre", "Free agent": "como agente libre",
                        "Return from loan": "de regreso de préstamo"}.get(m.get("type"), "")
                if tin.get("id") == tid:
                    tit, det_txt = f"{nom} ficha a {pj.get('name')}", f"Llega de {EQ_MX.get(tout.get('id'), tout.get('name'))}" + (f" {modo}" if modo else "")
                else:
                    tit, det_txt = f"{pj.get('name')} deja {nom}", f"Se va a {EQ_MX.get(tin.get('id'), tin.get('name'))}" + (f" {modo}" if modo else "")
                notas.append(nota("fichaje", "mx", nom, d, tit, det_txt, 5 + fama({"name": nom})))
        try: C = af("coachs", team=tid)
        except Exception as e: log(f"  ! técnico {nom}: {e}"); C = []
        for c in C:
            for k in c.get("career") or []:
                if (k.get("team") or {}).get("id") != tid or k.get("end"): continue
                try: d = datetime.fromisoformat(k.get("start")).date()
                except Exception: continue
                if ini <= d <= hoy.date():
                    notas.append(nota("tecnico", "mx", nom, d, f"{c.get('name')}, nuevo técnico de {nom}", "Liga MX", 12))
    return notas


# ------------------------------------------------------------------ NFL (reporte oficial de lesiones, vía nflverse)
NFL_EQ = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals",
          "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts",
          "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAR": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
          "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants", "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers",
          "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}
def nfl(hoy, propiedad=None, csv_texto=None, sched=None, log=print):
    """propiedad: {nombre: % de ligas con dueño} (D.fantasy) para quedarse con jugadores que importan.
    sched: D.sched (partidos de nflverse) para decir contra quién y cuándo juegan y abrir el partido."""
    if csv_texto is None:
        url = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{TEMP}.csv"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LaPizarra/1.0"}), timeout=60) as r:
            csv_texto = r.read().decode("utf-8")
    filas = list(csv.DictReader(io.StringIO(csv_texto)))
    filas = [f for f in filas if f.get("season_type") == "REG"]
    if not filas: return []
    sem = max(int(f["week"]) for f in filas)
    propiedad, sched = propiedad or {}, sched or []
    def partido(tm):
        for g in sched:
            if g.get("w") == sem and tm in (g.get("h"), g.get("a")): return g
        return None
    notas = []
    for f in filas:
        if int(f["week"]) != sem or f.get("position") not in ("QB", "RB", "WR", "TE"): continue
        own = propiedad.get(f["full_name"], 0) or 0
        if own < (25 if f["position"] == "QB" else 40): continue
        est, prac = f.get("report_status") or "", f.get("practice_status") or ""
        les = lesion_es(f.get("report_primary_injury") or f.get("practice_primary_injury"))
        tm = "LA" if f["team"] == "LAR" else f["team"]
        eq = NFL_EQ.get(tm, tm)
        g = partido(tm)
        cuando = ""
        if g and g.get("ko"):
            d = fecha_mx(g["ko"])
            rival = NFL_EQ.get(g["a"] if g["h"] == tm else g["h"], "")
            if d and rival: cuando = f" · {dia(d, hoy)} contra los {rival}"
        nom = f["full_name"]
        if est == "Out": tit, peso = f"{nom} no juega en la semana {sem}", 10
        elif est == "Doubtful": tit, peso = f"{nom}, duda seria para la semana {sem}", 9
        elif est == "Questionable": tit, peso = f"{nom}, en duda para la semana {sem}", 6
        elif not est and prac.startswith("Did Not"): tit, peso = f"{nom} no entrenó", 7
        else: continue
        extra = {"nid": g["id"]} if g else {}
        notas.append(nota("lesion", "nfl", eq, hoy.isoformat(), tit, f"{eq} · {les}{cuando}", peso + own / 20, **extra))
    return notas


def ordenar(notas, maximo=40, max_lesiones=14):
    """Quita repetidas y ordena por importancia (máximo 14 lesiones en total, para que no tapen lo demás)."""
    vistos, salida, les = set(), [], 0
    for n in sorted(notas, key=lambda n: (-n["peso"], str(n["t"]))):
        if n["tit"] in vistos: continue
        if n["tipo"] == "lesion":
            les += 1
            if les > max_lesiones: continue
        vistos.add(n["tit"]); salida.append(n)
    return salida[:maximo]


def generar(af, propiedad=None, log=print, hoy=None, sched=None):
    hoy = hoy or datetime.now(MX)
    notas = []
    if af:
        try: notas += futbol(af, hoy, log)
        except Exception as e: log(f"  ! noticias de fútbol: {e}")
        if hoy.month in (1, 2, 6, 7, 8, 9, 12):   # periodos de traspasos de la Liga MX (con margen)
            try: notas += liga_mx_mercado(af, hoy, log)
            except Exception as e: log(f"  ! fichajes Liga MX: {e}")
    try: notas += nfl(hoy, propiedad, sched=sched, log=log)
    except Exception as e: log(f"  ! noticias NFL: {e}")
    return ordenar(notas)


# ------------------------------------------------------------------ Prueba sola (automatización "Probar noticias")
if __name__ == "__main__":
    KEY = os.environ.get("API_FOOTBALL_KEY", "").strip()
    BASE = os.environ.get("AF_BASE", "https://v3.football.api-sports.io")
    usados = [0]
    def af(ruta, **q):
        url = f"{BASE}/{ruta}" + ("?" + urllib.parse.urlencode(q) if q else "")
        for intento in range(3):
            time.sleep(0.3)
            req = urllib.request.Request(url, headers={"x-apisports-key": KEY, "User-Agent": "LaPizarra/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r: j = json.loads(r.read().decode("utf-8"))
            usados[0] += 1
            e = j.get("errors")
            if e and "rateLimit" in json.dumps(e) and intento < 2: time.sleep(5); continue
            if e and (not isinstance(e, list) or e): raise RuntimeError(f"{ruta}: {e}")
            return j.get("response") or []
    lineas = []
    def log(*a):
        s = " ".join(str(x) for x in a); print(s); lineas.append(s)
    prop = {}
    try: prop = {x["n"]: x.get("own") or 0 for x in json.load(open("docs/datos/paq_fantasy.json")).get("fantasy", [])}
    except Exception as e: log("  (sin % de dueño de fantasy:", e, ")")
    hoy = datetime.now(MX)
    log(f"=== MUESTRA DE NOTICIAS · {hoy:%Y-%m-%d %H:%M} (hora de México) ===")
    N = generar(af, prop, log, hoy)
    for n in N:
        log(f"[{n['liga']:>3}] {n['tipo']:10} peso {n['peso']:>4} · {n['tit']}  —  {n['det']}")
    log(f"\nNotas: {len(N)} · pedidos usados: {usados[0]}")
    open("prueba_noticias.txt", "w").write("\n".join(lineas) + "\n")
    json.dump(N, open("noticias_muestra.json", "w"), ensure_ascii=False, indent=1)
