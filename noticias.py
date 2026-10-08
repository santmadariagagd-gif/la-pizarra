"""noticias.py — "Lo último": notas cortas que La Pizarra arma sola con datos que ya tiene (7 oct 2026).

Sin textos de otros medios: cada nota se escribe aquí con datos de API-Football (fútbol) y nflverse (NFL).
Solo noticias de la semana: lo que pasó en los últimos 7 días o los avisos de lesión para los próximos 7.

Tipos (campo "tipo"):
  lesion     · baja o duda por lesión (NFL y las 5 grandes de Europa + Champions; la Liga MX no trae lesiones)
  suspension · expulsados de la semana (todas las ligas) y suspendidos que avisa API-Football (Europa)
  racha      · rachas de victorias / sin perder / sin ganar / derrotas que siguieron esta semana
  goles      · tripletes, líder de goleo que anotó esta semana, goleadas
  fichaje    · altas y bajas de la Liga MX de los últimos 7 días (en periodo de traspasos)
  tecnico    · cambio de entrenador en la Liga MX en los últimos 7 días

Uso:
  - Dentro de build_site.py: from noticias import generar; out['noticias'] = generar(af, ...)
  - Prueba sola (automatización "Probar noticias"): python noticias.py  → prueba_noticias.txt + noticias_muestra.json
"""
import csv, io, json, os, re, time, unicodedata, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MX = timezone(timedelta(hours=-6))
TEMP = 2026
# liga: (id API-Football, nombre, ¿trae lesiones?)
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
         "Paris Saint Germain": "PSG", "Tottenham": "Tottenham", "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen",
         "Manchester United": "Manchester United", "Manchester City": "Manchester City", "Sevilla": "Sevilla", "Real Betis": "Betis",
         "Athletic Club": "Athletic", "AS Roma": "Roma", "Olympique Marseille": "Marsella", "Marseille": "Marsella"}
LESION_ES = {"knee": "la rodilla", "muscle": "MUSCULAR", "hamstring": "el isquiotibial", "ankle": "el tobillo", "thigh": "el muslo",
             "calf": "la pantorrilla", "back": "la espalda", "shoulder": "el hombro", "groin": "la ingle", "adductor": "el aductor",
             "foot": "el pie", "hip": "la cadera", "achilles": "el tendón de Aquiles", "concussion": "una conmoción", "head": "la cabeza",
             "illness": "enfermedad", "abdominal": "el abdomen", "toe": "un dedo del pie", "thumb": "el pulgar", "finger": "un dedo",
             "hand": "la mano", "wrist": "la muñeca", "elbow": "el codo", "rib": "las costillas", "chest": "el pecho", "neck": "el cuello",
             "quad": "el cuádriceps", "leg": "la pierna", "heel": "el talón", "pelvis": "la pelvis", "fracture": "una fractura",
             "ligament": "un ligamento", "cruciate": "el ligamento cruzado", "jumpers knee": "tendinitis en la rodilla", "virus": "enfermedad",
             "health": "problemas de salud", "personal": "motivos personales", "covid": "enfermedad"}
NO_LESION = ("coach's decision", "inactive", "off the roster", "loan agreement", "not registered", "international duty", "lack of fitness")
SUSP = ("red card", "yellow card", "suspended", "suspension")


def sin_acentos(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def lesion_es(razon):
    """'Knee Injury' → 'una lesión en la rodilla'; 'Illness' → 'enfermedad'."""
    r = sin_acentos(razon)
    for k in sorted(LESION_ES, key=len, reverse=True):
        if k in r:
            v = LESION_ES[k]
            if v == "MUSCULAR": return "una lesión muscular"
            if v in ("enfermedad", "problemas de salud", "motivos personales", "una conmoción", "una fractura", "tendinitis en la rodilla"): return v
            return "una lesión en " + v
    return "una lesión"


def fecha_mx(s):
    try: return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(MX)
    except Exception: return None


def eq_nombre(t, lg):
    if lg == "mx" and t.get("id") in EQ_MX: return EQ_MX[t["id"]]
    return EQ_ES.get(t.get("name"), t.get("name") or "")


def fama(t): return FAMA.get(sin_acentos(t.get("name")), 0)


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
def dia(d, hoy):
    dd = (d.date() - hoy.date()).days
    if dd == 0: return "hoy"
    if dd == 1: return "mañana"
    if dd == -1: return "ayer"
    return ("el " if dd > 0 else "el ") + DIAS[d.weekday()]


# ------------------------------------------------------------------ Fútbol
def futbol(af, hoy, log=print):
    notas = []
    ini, fin = hoy - timedelta(days=7), hoy + timedelta(days=7)
    for lg, (lid, lnom, con_lesiones) in LIGAS.items():
        try:
            fx = af("fixtures", league=lid, season=TEMP)
        except Exception as e:
            log(f"  ! {lnom} partidos: {e}"); continue
        jugados = [f for f in fx if (f["fixture"]["status"]["short"] in ("FT", "AET", "PEN"))]
        jugados.sort(key=lambda f: f["fixture"]["date"])
        semana = [f for f in jugados if (d := fecha_mx(f["fixture"]["date"])) and d >= ini]
        prox = {}   # equipo → su siguiente partido
        for f in sorted(fx, key=lambda f: f["fixture"]["date"]):
            if f["fixture"]["status"]["short"] in ("NS", "TBD"):
                for lado, otro in (("home", "away"), ("away", "home")):
                    prox.setdefault(f["teams"][lado]["id"], (f, otro))
        por_id = {f["fixture"]["id"]: f for f in fx}

        # --- Rachas (de todo el torneo), solo si siguieron esta semana
        hist = defaultdict(list)   # equipo → [(fecha, 'G'/'E'/'P', partido)]
        for f in jugados:
            gh, ga = f["goals"]["home"], f["goals"]["away"]
            if gh is None or ga is None: continue
            for lado, gf, gc in (("home", gh, ga), ("away", ga, gh)):
                hist[f["teams"][lado]["id"]].append((f, "G" if gf > gc else "E" if gf == gc else "P", f["teams"][lado]))
        for tid, h in hist.items():
            ult_f, ult_r, team = h[-1]
            if fecha_mx(ult_f["fixture"]["date"]) < ini: continue
            def racha(cond):
                n = 0
                for _, r, _ in reversed(h):
                    if not cond(r): break
                    n += 1
                return n
            g, sp, sg, p = racha(lambda r: r == "G"), racha(lambda r: r != "P"), racha(lambda r: r != "G"), racha(lambda r: r == "P")
            nom = eq_nombre(team, lg)
            txt = None
            if p >= 4 and p >= sg: txt, peso = f"{nom} suma {p} derrotas seguidas en {lnom}.", 5 + p
            elif g >= 4: txt, peso = f"{nom} suma {g} victorias seguidas en {lnom}.", 6 + g
            elif sp >= 7 and sp > g: txt, peso = f"{nom} lleva {sp} partidos sin perder en {lnom}.", 4 + sp / 2
            elif sg >= 5: txt, peso = f"{nom} lleva {sg} partidos sin ganar en {lnom}" + (f" ({p} derrotas seguidas)." if p >= 3 else "."), 4 + sg / 2
            elif p >= 4: txt, peso = f"{nom} suma {p} derrotas seguidas en {lnom}.", 5 + p
            if txt:
                notas.append(dict(tipo="racha", liga=lg, eq=nom, t=ult_f["fixture"]["date"], txt=txt,
                                  peso=peso + fama(team), fx=ult_f["fixture"]["id"]))

        # --- Goleadas de la semana
        for f in semana:
            gh, ga = f["goals"]["home"], f["goals"]["away"]
            if gh is None or abs(gh - ga) < 4: continue
            gana, pierde = ("home", "away") if gh > ga else ("away", "home")
            notas.append(dict(tipo="goles", liga=lg, eq=eq_nombre(f["teams"][gana], lg), t=f["fixture"]["date"],
                              txt=f"{eq_nombre(f['teams'][gana], lg)} goleó {max(gh, ga)}-{min(gh, ga)} a {eq_nombre(f['teams'][pierde], lg)}.",
                              peso=5 + abs(gh - ga) + fama(f["teams"][gana]) + fama(f["teams"][pierde]), fx=f["fixture"]["id"]))

        # Líder(es) de goleo (se piden antes para no repetir "triplete" y "líder" del mismo jugador)
        try: top = af("players/topscorers", league=lid, season=TEMP)
        except Exception as e: top = []; log(f"  ! {lnom} goleo: {e}")
        mxg = (top[0]["statistics"][0]["goals"]["total"] or 0) if top else 0
        lideres = {x["player"]["id"] for x in top if (x["statistics"][0]["goals"]["total"] or 0) == mxg and mxg >= 3}
        # --- Eventos de los partidos de la semana (goles por jugador y expulsiones): fixtures?ids= de 20 en 20
        goles_sem = defaultdict(lambda: [0, None, None])   # jugador → [goles, nombre, equipo]
        ids = [f["fixture"]["id"] for f in semana]
        det = []
        for i in range(0, len(ids), 20):
            try: det += af("fixtures", ids="-".join(map(str, ids[i:i + 20])))
            except Exception as e: log(f"  ! {lnom} eventos: {e}")
        for f in det:
            por_jug = defaultdict(int)
            for ev in f.get("events") or []:
                t, p = ev.get("team") or {}, ev.get("player") or {}
                if ev.get("type") == "Goal" and ev.get("detail") in ("Normal Goal", "Penalty") and (ev.get("comments") or "") != "Penalty Shootout":
                    por_jug[(p.get("id"), p.get("name"), t.get("id"))] += 1
                    g = goles_sem[p.get("id")]; g[0] += 1; g[1] = p.get("name"); g[2] = t
                if ev.get("type") == "Card" and ev.get("detail") in ("Red Card", "Second Yellow card"):
                    rival = f["teams"]["away" if f["teams"]["home"]["id"] == t.get("id") else "home"]
                    sig = prox.get(t.get("id"))
                    sig_txt = ""
                    if sig:
                        sf, otro = sig
                        sig_txt = f" Su siguiente partido: contra {eq_nombre(sf['teams'][otro], lg)}."
                    como = "doble amarilla" if ev.get("detail") == "Second Yellow card" else "roja directa"
                    notas.append(dict(tipo="suspension", liga=lg, eq=eq_nombre(t, lg), t=f["fixture"]["date"],
                                      txt=f"{p.get('name')} ({eq_nombre(t, lg)}) fue expulsado con {como} ante {eq_nombre(rival, lg)}.{sig_txt}",
                                      peso=4 + fama(t), fx=f["fixture"]["id"]))
            for (pid, pn, tid), n in por_jug.items():
                if n >= 3 and pid not in lideres:
                    tm = f["teams"]["home"] if f["teams"]["home"]["id"] == tid else f["teams"]["away"]
                    rival = f["teams"]["away"] if tm is f["teams"]["home"] else f["teams"]["home"]
                    notas.append(dict(tipo="goles", liga=lg, eq=eq_nombre(tm, lg), t=f["fixture"]["date"],
                                      txt=f"{pn} ({eq_nombre(tm, lg)}) hizo {'triplete' if n == 3 else f'{n} goles'} ante {eq_nombre(rival, lg)}.",
                                      peso=9 + fama(tm), fx=f["fixture"]["id"]))

        # --- Líder de goleo que anotó esta semana
        if top:
            mx = (top[0]["statistics"][0]["goals"]["total"] or 0)
            for x in top:
                st = x["statistics"][0]; gt = st["goals"]["total"] or 0
                if gt < mx or mx < 3: break
                pid = x["player"]["id"]
                if goles_sem[pid][0] > 0:
                    empatados = sum(1 for y in top if (y["statistics"][0]["goals"]["total"] or 0) == mx)
                    lider = "comparte el liderato de goleo" if empatados > 1 else "es el líder de goleo"
                    tm = st["team"]
                    notas.append(dict(tipo="goles", liga=lg, eq=eq_nombre(tm, lg), t=hoy.isoformat(),
                                      txt=f"{x['player']['name']} ({eq_nombre(tm, lg)}) anotó {goles_sem[pid][0] if goles_sem[pid][0] < 3 else 'triplete' if goles_sem[pid][0] == 3 else goles_sem[pid][0]} esta semana, llega a {gt} goles y {lider} de {lnom}.".replace("anotó 1 esta", "anotó esta").replace("anotó triplete", "hizo triplete"),
                                      peso=8 + fama(tm)))

        # --- Lesiones y suspensiones que avisa API-Football para los próximos 7 días
        if con_lesiones:
            try: inj = af("injuries", league=lid, season=TEMP)
            except Exception as e: inj = []; log(f"  ! {lnom} lesiones: {e}")
            imp = {x["player"]["id"] for x in top[:15]} if top else set()
            try: imp |= {x["player"]["id"] for x in af("players/topassists", league=lid, season=TEMP)[:10]}
            except Exception: pass
            vistos, cand = set(), []
            for x in sorted(inj, key=lambda x: (x.get("fixture") or {}).get("date") or ""):
                p, t, fxi = x.get("player") or {}, x.get("team") or {}, x.get("fixture") or {}
                d = fecha_mx(fxi.get("date"))
                if not d or not (hoy - timedelta(hours=12) <= d <= fin) or p.get("id") in vistos: continue
                vistos.add(p.get("id"))
                razon = sin_acentos(p.get("reason"))
                if any(k in razon for k in NO_LESION): continue
                f0 = por_id.get(fxi.get("id"))
                rival = ""
                if f0:
                    otro = "away" if f0["teams"]["home"]["id"] == t.get("id") else "home"
                    rival = f" contra {eq_nombre(f0['teams'][otro], lg)}"
                cuando = f"{dia(d, hoy)}{rival}"
                nom = eq_nombre(t, lg)
                if any(k in razon for k in SUSP):
                    txt, tipo = f"{p.get('name')} ({nom}) está suspendido para el partido de {cuando}.", "suspension"
                elif p.get("type") == "Questionable":
                    txt, tipo = f"{p.get('name')} ({nom}) está en duda para {cuando} por {lesion_es(p.get('reason'))}.", "lesion"
                else:
                    txt, tipo = f"{p.get('name')} ({nom}) es baja para {cuando} por {lesion_es(p.get('reason'))}.", "lesion"
                peso = (6 if p.get("id") in imp else 0) + 2 * fama(t)
                if peso >= 4: cand.append(dict(tipo=tipo, liga=lg, eq=nom, t=fxi.get("date"), txt=txt, peso=peso, fx=fxi.get("id")))
            cand.sort(key=lambda n: -n["peso"])
            por_eq = defaultdict(int)
            for n in cand:
                if por_eq[n["eq"]] >= 2: continue
                por_eq[n["eq"]] += 1; notas.append(n)
                if sum(por_eq.values()) >= 5: break
    return notas


def liga_mx_mercado(af, hoy, log=print):
    """Fichajes y cambios de técnico de la Liga MX en los últimos 7 días (2 pedidos por equipo)."""
    notas, ini = [], (hoy - timedelta(days=7)).date()
    for tid, nom in EQ_MX.items():
        if tid in (2312,): continue   # Atlante no está en el torneo
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
                clave = (pj.get("id"), d)
                if clave in vistos: continue
                vistos.add(clave)
                tipo = {"Loan": "a préstamo", "Free": "como agente libre", "Free agent": "como agente libre", "Return from loan": "de regreso de préstamo"}.get(m.get("type"), "")
                if tin.get("id") == tid:
                    txt = f"{nom} incorpora a {pj.get('name')}, que llega de {EQ_MX.get(tout.get('id'), tout.get('name'))}" + (f" {tipo}." if tipo else ".")
                else:
                    txt = f"{pj.get('name')} deja {nom} y se va a {EQ_MX.get(tin.get('id'), tin.get('name'))}" + (f" {tipo}." if tipo else ".")
                notas.append(dict(tipo="fichaje", liga="mx", eq=nom, t=str(d), txt=txt, peso=5 + fama({"name": nom})))
        try: C = af("coachs", team=tid)
        except Exception as e: log(f"  ! técnico {nom}: {e}"); C = []
        for c in C:
            for k in c.get("career") or []:
                if (k.get("team") or {}).get("id") != tid or k.get("end"): continue
                try: d = datetime.fromisoformat(k.get("start")).date()
                except Exception: continue
                if ini <= d <= hoy.date():
                    notas.append(dict(tipo="tecnico", liga="mx", eq=nom, t=str(d), txt=f"{c.get('name')} es el nuevo técnico de {nom}.", peso=12))
    return notas


# ------------------------------------------------------------------ NFL (reporte oficial de lesiones, vía nflverse)
NFL_EQ = {"ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills", "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals",
          "CLE": "Browns", "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers", "HOU": "Texans", "IND": "Colts",
          "JAX": "Jaguars", "KC": "Chiefs", "LA": "Rams", "LAR": "Rams", "LAC": "Chargers", "LV": "Raiders", "MIA": "Dolphins",
          "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants", "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers",
          "SEA": "Seahawks", "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders"}
def nfl(hoy, propiedad=None, csv_texto=None, sched=None, log=print):
    """propiedad: {nombre: % de ligas con dueño} (D.fantasy) para quedarse con jugadores que importan."""
    if csv_texto is None:
        url = f"https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{TEMP}.csv"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LaPizarra/1.0"}), timeout=60) as r:
            csv_texto = r.read().decode("utf-8")
    filas = list(csv.DictReader(io.StringIO(csv_texto)))
    if not filas: return []
    sem = max(int(f["week"]) for f in filas if f.get("season_type") == "REG")
    propiedad = propiedad or {}
    notas = []
    for f in filas:
        if f.get("season_type") != "REG" or int(f["week"]) != sem or f.get("position") not in ("QB", "RB", "WR", "TE"): continue
        own = propiedad.get(f["full_name"], 0) or 0
        if own < 40 and f["position"] != "QB": continue
        if f["position"] == "QB" and own < 25: continue
        est, prac = f.get("report_status") or "", f.get("practice_status") or ""
        les = lesion_es(f.get("report_primary_injury") or f.get("practice_primary_injury"))
        eq = NFL_EQ.get(f["team"], f["team"])
        nom = f"{f['full_name']} ({f['position']}, {eq})"
        if est == "Out": txt, peso = f"{nom} no juega en la semana {sem} por {les}.", 10
        elif est == "Doubtful": txt, peso = f"{nom} es duda seria para la semana {sem} por {les}.", 9
        elif est == "Questionable": txt, peso = f"{nom} está en duda para la semana {sem} por {les}.", 6
        elif not est and prac.startswith("Did Not"): txt, peso = f"{nom} no entrenó por {les}. Hay que seguir su estado para la semana {sem}.", 7
        else: continue
        notas.append(dict(tipo="lesion", liga="nfl", eq=eq, t=hoy.isoformat(), txt=txt.replace("por enfermedad", "por enfermedad"),
                          peso=peso + own / 20))
    return notas


def ordenar(notas, hoy, maximo=40):
    """Quita repetidas, deja solo la semana y ordena por importancia y fecha."""
    vistos, salida = set(), []
    for n in sorted(notas, key=lambda n: (-n["peso"], str(n["t"])), reverse=False):
        if n["txt"] in vistos: continue
        vistos.add(n["txt"]); n["peso"] = round(n["peso"], 1); salida.append(n)
    return salida[:maximo]


def generar(af, propiedad=None, log=print, hoy=None):
    hoy = hoy or datetime.now(MX)
    notas = []
    try: notas += futbol(af, hoy, log)
    except Exception as e: log(f"  ! noticias de fútbol: {e}")
    if hoy.month in (1, 2, 6, 7, 8, 9, 12):   # periodos de traspasos de la Liga MX (con margen)
        try: notas += liga_mx_mercado(af, hoy, log)
        except Exception as e: log(f"  ! fichajes Liga MX: {e}")
    try: notas += nfl(hoy, propiedad, log=log)
    except Exception as e: log(f"  ! noticias NFL: {e}")
    return ordenar(notas, hoy)


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
    try:
        fan = json.load(open("docs/datos/paq_fantasy.json")).get("fantasy", [])
        prop = {x["n"]: x.get("own") or 0 for x in fan}
    except Exception as e: log("  (sin % de dueño de fantasy:", e, ")")
    hoy = datetime.now(MX)
    log(f"=== MUESTRA DE NOTICIAS · {hoy:%Y-%m-%d %H:%M} (hora de México) ===")
    N = generar(af, prop, log, hoy)
    ICON = {"lesion": "🩹 Lesión", "suspension": "🟥 Suspensión", "racha": "📈 Racha", "goles": "⚽ Goles", "fichaje": "🔁 Fichaje", "tecnico": "📋 Técnico"}
    for n in N:
        log(f"[{n['liga']:>3}] {ICON.get(n['tipo'], n['tipo']):14} {str(n['t'])[:10]} · peso {n['peso']:>4} · {n['txt']}")
    log(f"\nNotas: {len(N)} · pedidos usados: {usados[0]}")
    open("prueba_noticias.txt", "w").write("\n".join(lineas) + "\n")
    json.dump(N, open("noticias_muestra.json", "w"), ensure_ascii=False, indent=1)
