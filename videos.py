"""
La Pizarra · Videos oficiales (29 oct 2026; v2 el mismo día)

Los videos más importantes de la semana de los canales OFICIALES de YouTube (Liga MX, Champions, Premier, NBA, NFL, F1).
Solo se guardan id, título, canal, fecha y vistas; el video se ve con el reproductor de YouTube (sus términos lo permiten).

Dos formas de leer YouTube:
  1. Con la llave gratis de YouTube (secreto YT_API_KEY): lo más confiable. Trae las vistas reales de cada video, la
     duración (para quitar los "shorts") y encuentra solo el canal oficial de la Liga MX.
  2. Sin llave: el RSS público de cada canal (a veces YouTube lo contesta con error; se reintenta y si no, se quedan los
     de la vez anterior). El RSS también trae las vistas.

"Los más importantes de la semana": de los últimos 7 días, solo resúmenes y jugadas (no shorts, no videos de años
pasados), ordenados por vistas, con extra a los clásicos y partidos grandes.

Sale en docs/datos/videos.json = {al, v: [{id, t, c: liga, n: canal, ts, vw: vistas, k: 1 si es clásico/partido grande}], can, dbg}
Se llama desde build_site.py. Prueba sola: python videos.py
"""
import json, os, re, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# liga: (candidatos de canal, búsqueda para encontrarlo con la llave, palabras que debe traer el título)
CANALES = {
    "mx":  (["@LIGABBVAMX", "@ligabbvamx", "user:LIGABBVAMX"], "LIGA BBVA MX", [r"\b\d{1,2}\s*-\s*\d{1,2}\b", "resumen", "mejores momentos", "goles", "jugadas"]),
    "ucl": (["@ChampionsLeague", "user:UEFA", "@UEFA"], "UEFA Champions League", ["highlights", "every champions league goal", "best goals", "resumen"]),
    "eng": (["UCG5qGWdu8nIRZqJ_GgDwQ-w", "@premierleague"], "Premier League", ["highlights", "goals"]),
    "nba": (["UCWJ2lWNubArHWmf3FIHbfcQ", "@NBA"], "NBA", ["highlights", "game recap"]),
    "nfl": (["@NFL", "user:NFL"], "NFL", ["highlights", "game recap", "best plays", "every touchdown"]),
    "f1":  (["UCB_qr75-ydFVKSF9Dmo6izg", "@Formula1"], "FORMULA 1", ["highlights"]),
}
# Lo que no queremos aunque pase el filtro: otras ligas del mismo canal, previas, entrevistas, clásicos de otros años
FUERA = {"mx": r"expansi[oó]n|femenil|previa|#lapr|podcast|entrevista", "ucl": r"classic|ballon|reaction|europa league|conference league|uel\b|uecl",
         "eng": r"all .* goals and assists|career|classic|compilation", "nba": r"", "nfl": r"preview|podcast|report|picks|rankings|mic'd", "f1": r"onboard|interview"}
# Partidos grandes: si el título trae dos de estos de la misma liga (o dice clásico/derby), suben
GRANDES = {
    "mx": ["america", "américa", "chivas", "guadalajara", "pumas", "cruz azul", "tigres", "monterrey", "rayados", "toluca"],
    "ucl": ["real madrid", "barcelona", "bayern", "liverpool", "manchester city", "arsenal", "psg", "paris", "inter", "juventus", "milan", "chelsea", "atlético", "atletico"],
    "eng": ["liverpool", "manchester city", "man city", "arsenal", "manchester united", "man united", "chelsea", "tottenham", "spurs", "newcastle"],
    "nba": ["lakers", "celtics", "warriors", "knicks", "thunder", "nuggets", "cavaliers", "bucks", "76ers", "spurs"],
    "nfl": ["chiefs", "eagles", "cowboys", "bills", "49ers", "ravens", "packers", "lions", "steelers"],
    "f1": [],
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "es-MX,es;q=0.9,en;q=0.8", "Cookie": "CONSENT=YES+1; SOCS=CAI"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}
KEY = os.environ.get("YT_API_KEY", "").strip()
DIAS = 7

def pide(url, intentos=4):
    """YouTube a veces contesta 404 a sus propios RSS por un rato: se reintenta unas veces antes de rendirse."""
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            cod = getattr(e, "code", 0) or 0
            if i == intentos - 1 or not (cod in (404, 429) or cod >= 500): raise
            time.sleep(3 + 4 * i)

def api(ruta, **q):
    q["key"] = KEY
    return json.loads(pide("https://www.googleapis.com/youtube/v3/" + ruta + "?" + urllib.parse.urlencode(q), intentos=2))

def iso_dur(d):   # PT1M5S → 65
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    return (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0

def bueno(liga, t, palabras):
    tl = t.lower()
    if "#short" in tl or "shorts" in tl: return False
    if not any(re.search(p, tl) for p in palabras): return False
    if FUERA.get(liga) and re.search(FUERA[liga], tl): return False
    año = datetime.now().year
    temporadas = [int(b) for a, b in re.findall(r"\b(20\d\d)\s*[-/]\s*(\d\d)\b", t)]
    años = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", t)]
    if temporadas and max(temporadas) >= año % 100: return True      # "2026-27"
    if años and max(años) < año: return False                         # "Highlights 2021": video viejo
    return True

def grande(liga, t):
    tl = t.lower(); L = GRANDES.get(liga) or []
    return 1 if sum(1 for x in L if x in tl) >= 2 or "clásico" in tl or "clasico" in tl or "derby" in tl else 0

def por_api(liga, cands, busq, cache, dbg):
    cid = cache.get(liga)
    if not cid:
        for c in cands:
            try:
                if c.startswith("@"): j = api("channels", part="id", forHandle=c)
                elif c.startswith("UC"): j = {"items": [{"id": c}]}
                else: continue
                if j.get("items"): cid = j["items"][0]["id"]; break
            except Exception as e: dbg.setdefault(liga, []).append([c, str(e)[:80]])
        if not cid:
            j = api("search", part="snippet", q=busq, type="channel", maxResults=1)
            if j.get("items"): cid = j["items"][0]["snippet"]["channelId"]
    if not cid: raise RuntimeError("sin canal")
    ch = api("channels", part="contentDetails,snippet", id=cid)["items"][0]
    nombre, up = ch["snippet"]["title"], ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    for _ in range(3):   # hasta 150 videos (la NFL sube muchísimos al día)
        q = dict(part="contentDetails", playlistId=up, maxResults=50)
        if tok: q["pageToken"] = tok
        j = api("playlistItems", **q); its = j.get("items") or []
        ids += [x["contentDetails"]["videoId"] for x in its]
        tok = j.get("nextPageToken")
        if not tok or not its or datetime.fromisoformat(its[-1]["contentDetails"].get("videoPublishedAt", "2000-01-01T00:00:00Z").replace("Z", "+00:00")).timestamp() < time.time() - DIAS * 86400: break
    V = []
    for i in range(0, len(ids), 50):
        for x in api("videos", part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).get("items") or []:
            ts = datetime.fromisoformat(x["snippet"]["publishedAt"].replace("Z", "+00:00")).timestamp()
            if iso_dur(x["contentDetails"].get("duration")) < 70: continue   # shorts
            V.append({"id": x["id"], "t": x["snippet"]["title"][:140], "ts": int(ts), "vw": int(x["statistics"].get("viewCount", 0))})
    return cid, nombre, V

def por_rss(liga, cands, cache, dbg):
    for c in cands:
        cid = cache.get(liga) if c.startswith("@") and cache.get(liga) else c
        if cid.startswith("@"):
            try:
                h = pide(f"https://www.youtube.com/{c}", intentos=2)
                m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', h)
                cid = m.group(1) if m else None
            except Exception as e: dbg.setdefault(liga, []).append([c, str(e)[:80]]); cid = None
            if not cid: continue
        q = f"user={cid[5:]}" if cid.startswith("user:") else f"channel_id={cid}"
        try: x = ET.fromstring(pide(f"https://www.youtube.com/feeds/videos.xml?{q}"))
        except Exception as e: dbg.setdefault(liga, []).append([c, str(e)[:80]]); continue
        nombre = (x.findtext("a:title", default="", namespaces=NS) or "").strip(); V = []
        for e in x.findall("a:entry", NS):
            vid = e.findtext("yt:videoId", default="", namespaces=NS); t = (e.findtext("a:title", default="", namespaces=NS) or "").strip()
            try: ts = datetime.fromisoformat(e.findtext("a:published", default="", namespaces=NS).replace("Z", "+00:00")).timestamp()
            except Exception: ts = 0
            st = e.find("m:group/m:community/m:statistics", NS); vw = int(st.get("views", 0)) if st is not None else 0
            if vid and t: V.append({"id": vid, "t": t[:140], "ts": int(ts), "vw": vw})
        chid = e.findtext("yt:channelId", default="", namespaces=NS) if x.findall("a:entry", NS) else ""
        return (chid or (cid if cid.startswith("UC") else "")), nombre, V
    raise RuntimeError("sin canal")

def generar(ruta_prev=None):
    prev = {}
    if ruta_prev and os.path.exists(ruta_prev):
        try: prev = json.load(open(ruta_prev, encoding="utf-8"))
        except Exception: prev = {}
    cache = {k: v.get("id") for k, v in (prev.get("can") or {}).items() if str(v.get("id", "")).startswith("UC")}
    ahora = time.time(); salida = []; can = {}; dbg = {"modo": ["api" if KEY else "rss"]}
    for liga, (cands, busq, palabras) in CANALES.items():
        try:
            cid, nombre, V = por_api(liga, cands, busq, cache, dbg) if KEY else por_rss(liga, cands, cache, dbg)
            can[liga] = {"id": cid, "n": nombre}
            B = [{**x, "c": liga, "n": nombre, "k": grande(liga, x["t"])} for x in V if ahora - x["ts"] < DIAS * 86400 and bueno(liga, x["t"], palabras)]
            B.sort(key=lambda x: -(x["vw"] * (3 if x["k"] else 1)))
            salida += B[:6]
            dbg.setdefault(liga, []).append(["ok", f"{nombre}: {len(B)} de {len(V)}"])
            if len(B) < 2: dbg[liga].append(["títulos", [x["t"][:70] for x in V[:10]]])   # para ajustar el filtro
            if B:   # puntaje relativo a su liga: así la F1 o la NBA (millones de vistas) no tapan a las demás
                med = sorted(x["vw"] for x in B)[len(B) // 2] or 1
                for x in B: x["sc"] = round(x["vw"] / med * (3 if x["k"] else 1) * (1.5 if "highlight" in x["t"].lower() or "resumen" in x["t"].lower() else 1), 2)
        except Exception as e:
            dbg.setdefault(liga, []).append(["error", str(e)[:100]])
            salida += [x for x in prev.get("v") or [] if x.get("c") == liga and ahora - x.get("ts", 0) < DIAS * 86400 and bueno(liga, x.get("t", ""), palabras)]
            if liga in (prev.get("can") or {}): can[liga] = prev["can"][liga]
    # en "Todo": se intercalan las ligas (el mejor de cada una, luego el segundo…)
    por = {}
    for x in sorted(salida, key=lambda x: -x.get("sc", 0)): por.setdefault(x["c"], []).append(x)
    salida = [L[i] for i in range(6) for L in por.values() if i < len(L)]
    return {"al": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "v": salida, "can": can, "dbg": dbg}

if __name__ == "__main__":
    r = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "videos.json")
    out = generar(r)
    json.dump(out, open(r, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(len(out["v"]), "videos", out["dbg"])
