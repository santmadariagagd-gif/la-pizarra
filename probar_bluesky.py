"""
probar_bluesky.py — muestra de lo que pasa (y lo que no) por el filtro de Noticias de la portada (3 nov 2026).

Lee las mismas listas y medios de Bluesky que la página y aplica los MISMOS filtros (los toma de template.html para que
nunca se desfasen). Escribe bitacora/bs_muestra.json con, por deporte: las que pasan, y las que casi pasan (son noticia
fuerte pero fallaron otra regla), para poder afinar. Se corre con la automatización "Probar noticias" (workflow_dispatch).
"""
import json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone

AQUI = os.path.dirname(os.path.abspath(__file__))
API = "https://public.api.bsky.app/xrpc/"
T = open(os.path.join(AQUI, "template.html"), encoding="utf-8").read()

def rx(nombre):
    m = re.search(r"const " + nombre + r"=/(.*)/i;", T)
    return re.compile(m.group(1), re.I) if m else None

FUERTE, GRANDES, CTX, NO, LIVE, NFL, NBA = rx("BS_FUERTE"), rx("BS_FUT_GRANDES"), rx("BS_FUT_CTX"), rx("BS_NO"), rx("BS_LIVE"), rx("BS_NFL_CTX"), rx("BS_NBA_CTX")
SOC, APU = rx("BS_SOCCER"), rx("BS_APUESTA")
SERIOS = set(json.loads("[" + re.search(r"BS_SERIOS=new Set\(\[(.*?)\]\)", T).group(1) + "]"))
packs = json.loads(re.sub(r"(\w+):\[", r'"\1":[', re.search(r"packs:(\{fut:.*?\]\]\})", T).group(1)).replace("'", '"'))
medios = json.loads(re.sub(r"(\w+):\[", r'"\1":[', re.search(r"medios:(\{fut:.*?\})\}", T).group(1)))

def get(ruta, **q):
    with urllib.request.urlopen(API + ruta + "?" + urllib.parse.urlencode(q), timeout=25) as r:
        return json.loads(r.read().decode())

def verif(a):
    v = a.get("verification") or {}
    return v.get("verifiedStatus") == "valid" or v.get("trustedVerifierStatus") == "valid" or not a.get("handle", "").endswith(".bsky.social")

out = {"al": datetime.now(timezone.utc).isoformat(), "fuentes": {}, "dep": {}}
for k in ("fut", "nfl", "nba"):
    feeds = []
    for h, rk in packs.get(k, []):
        try:
            did = get("com.atproto.identity.resolveHandle", handle=h)["did"]
            sp = get("app.bsky.graph.getStarterPack", starterPack=f"at://{did}/app.bsky.graph.starterpack/{rk}")
            l = sp["starterPack"]["list"]["uri"]; f = get("app.bsky.feed.getListFeed", list=l, limit=100).get("feed", [])
            feeds += f; out["fuentes"][f"{k}:{h}"] = len(f)
        except Exception as e: out["fuentes"][f"{k}:{h}"] = str(e)[:80]
    for h in medios.get(k, []):
        try:
            f = get("app.bsky.feed.getAuthorFeed", actor=h, filter="posts_no_replies", limit=50).get("feed", [])
            feeds += f; out["fuentes"][f"{k}:{h}"] = len(f)
        except Exception as e: out["fuentes"][f"{k}:{h}"] = str(e)[:60]
    si, casi, vistos = [], [], set()
    lim = time.time() - 3 * 86400
    for x in feeds:
        P = x.get("post") or {}; t = (P.get("record") or {}).get("text", ""); A = P.get("author") or {}
        if not P or x.get("reason") or x.get("reply") or (P.get("record") or {}).get("reply") or P.get("uri") in vistos: continue
        vistos.add(P.get("uri"))
        try: ts = datetime.fromisoformat((P.get("record") or {}).get("createdAt", "").replace("Z", "+00:00")).timestamp()
        except Exception: ts = 0
        if ts < lim or len(t) < 50: continue
        motivos = []
        if not verif(A): motivos.append("no verificado")
        if NO and NO.search(t): motivos.append("promo/no")
        if LIVE.search(t): motivos.append("en vivo/horario/política")
        serio = A.get("handle") in SERIOS
        if APU.search(t): motivos.append("apuestas")
        if not FUERTE.search(t) and not serio: motivos.append("no es noticia fuerte")
        if k == "nfl" and (not NFL.search(t) or SOC.search(t) or (serio and NBA.search(t))): motivos.append("no es NFL")
        if k == "nba" and (not NBA.search(t) or SOC.search(t) or (serio and NFL.search(t))): motivos.append("no es NBA")
        tk = re.sub(r"https?:\S+|\S+\.\S+/\S*", "", t.lower())[:70]
        if tk in vistos: motivos.append("repetida")
        vistos.add(tk)
        if k == "fut" and not GRANDES.search(t): motivos.append("sin equipo grande")
        if k == "fut" and not CTX.search(t): motivos.append("no habla de fútbol")
        r = {"@": A.get("handle"), "t": t[:240], "ver": verif(A)}
        if not motivos: si.append(r)
        elif "no es noticia fuerte" not in motivos or len(motivos) == 1: casi.append({**r, "por": motivos})
    out["dep"][k] = {"pasan": si[:40], "casi": casi[:40], "total": len(vistos)}
os.makedirs(os.path.join(AQUI, "bitacora"), exist_ok=True)
json.dump(out, open(os.path.join(AQUI, "bitacora", "bs_muestra.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print({k: (len(v["pasan"]), len(v["casi"]), v["total"]) for k, v in out["dep"].items()}, out["fuentes"])
