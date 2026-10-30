"""
La Pizarra · Videos oficiales (29 oct 2026)

Resúmenes y jugadas de los canales OFICIALES de YouTube (Liga MX, Champions, Premier, NBA, NFL, F1). YouTube publica
un RSS gratis por canal (youtube.com/feeds/videos.xml?channel_id=…) y sus términos permiten poner los videos en otra
página con su reproductor. Solo se guardan id, título, canal y fecha; el video se ve con el reproductor de YouTube.

Sale en docs/datos/videos.json = {al, v: [{id, t, c: liga, n: canal, ts}], can: {liga: {id, n}}}
Se llama desde build_site.py (corrida de la mañana y de la noche). Prueba sola: python videos.py
"""
import json, os, re, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# liga: (@ del canal o ids posibles, palabras que debe traer el título para que sea resumen o jugada)
# Candidatos: id del canal (UC…), "user:" nombre viejo de usuario (RSS ?user=) o "@" del canal (se busca su id en la página)
CANALES = {
    "mx":  (["@LIGABBVAMX", "@ligabbvamx", "user:LIGABBVAMX", "user:ligamx", "@LigaMXoficial"], ["resumen", "goles", "gol ", "highlights"]),
    "ucl": (["user:UEFAchampionsleague", "@ChampionsLeague", "user:UEFA", "@UEFA"], ["highlights", "goals", "resumen"]),
    "eng": (["UCG5qGWdu8nIRZqJ_GgDwQ-w", "user:premierleague", "@premierleague"], ["highlights", "goals"]),
    "nba": (["UCWJ2lWNubArHWmf3FIHbfcQ", "user:NBA", "@NBA"], ["highlights", "game recap", "full game"]),
    "nfl": (["@NFL", "user:NFL"], ["highlights", "game recap", "best plays", "every touchdown"]),
    "f1":  (["user:Formula1", "@Formula1", "UCB_qr75-ydFVKSF9Dmo6izg"], ["highlights", "race", "qualifying"]),
}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "es-MX,es;q=0.9,en;q=0.8", "Cookie": "CONSENT=YES+1; SOCS=CAI"}
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "m": "http://search.yahoo.com/mrss/"}

def pide(url, intentos=4):
    """YouTube a veces contesta 404 a sus propios RSS por un rato: se reintenta unas veces antes de rendirse."""
    for i in range(intentos):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == intentos - 1 or "404" not in str(e) and "429" not in str(e) and "5" != str(getattr(e, "code", ""))[:1]: raise
            time.sleep(3 + 4 * i)

def canal_id(c, cache):
    if (c.startswith("UC") and len(c) == 24) or c.startswith("user:"): return c
    if c in cache: return cache[c]
    try:
        h = pide(f"https://www.youtube.com/{c}")
        m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', h) or re.search(r'youtube\.com/channel/(UC[\w-]{22})', h)
        if m: cache[c] = m.group(1); return m.group(1)
    except Exception as e:
        print("Videos: no se encontró", c, e)
    return None

def feed(cid):
    q = f"user={cid[5:]}" if cid.startswith("user:") else f"channel_id={cid}"
    x = ET.fromstring(pide(f"https://www.youtube.com/feeds/videos.xml?{q}"))
    nombre = (x.findtext("a:title", default="", namespaces=NS) or "").strip()
    V = []
    for e in x.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        t = (e.findtext("a:title", default="", namespaces=NS) or "").strip()
        pub = e.findtext("a:published", default="", namespaces=NS)
        try: ts = datetime.fromisoformat(pub.replace("Z", "+00:00")).timestamp()
        except Exception: ts = 0
        if vid and t: V.append({"id": vid, "t": t[:140], "ts": int(ts)})
    return nombre, V

def generar(ruta_prev=None):
    prev = {}
    if ruta_prev and os.path.exists(ruta_prev):
        try: prev = json.load(open(ruta_prev, encoding="utf-8"))
        except Exception: prev = {}
    cache = {}
    for k, v in (prev.get("can") or {}).items():
        if v.get("h"): cache[v["h"]] = v["id"]
    ahora = time.time(); salida = []; can = {}; dbg = {}
    for liga, (cands, palabras) in CANALES.items():
        ok = False
        for c in cands:
            cid = canal_id(c, cache)
            if not cid: dbg.setdefault(liga, []).append([c, "sin id"]); continue
            try: nombre, V = feed(cid)
            except Exception as e: print("Videos:", liga, c, e); dbg.setdefault(liga, []).append([c, str(e)[:80]]); continue
            can[liga] = {"id": cid, "n": nombre, "h": c if c.startswith("@") else ""}
            buenos = [x for x in V if ahora - x["ts"] < 5 * 86400 and any(p in x["t"].lower() for p in palabras)
                      and "#shorts" not in x["t"].lower()]
            for x in buenos[:8]: salida.append({**x, "c": liga, "n": nombre})
            print(f"Videos: {liga} → {nombre} ({cid}): {len(buenos)} de {len(V)}")
            dbg.setdefault(liga, []).append([c, f"ok {nombre}: {len(buenos)} de {len(V)}"])
            ok = True; break
        if not ok:   # si un canal falla, se quedan sus videos de la vez anterior
            salida += [x for x in prev.get("v") or [] if x.get("c") == liga and ahora - x.get("ts", 0) < 5 * 86400]
            if liga in (prev.get("can") or {}): can[liga] = prev["can"][liga]
    salida.sort(key=lambda x: -x["ts"])
    return {"al": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "v": salida, "can": can, "dbg": dbg}

if __name__ == "__main__":
    r = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "videos.json")
    out = generar(r)
    json.dump(out, open(r, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(len(out["v"]), "videos")
