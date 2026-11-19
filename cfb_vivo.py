"""
cfb_vivo.py — marcadores en vivo del futbol americano colegial (19 nov 2026).

Lo llama avisos.py en cada corrida (cada 5 min con cron-job.org). Solo pide a College Football Data (/scoreboard, plan
Tier 1 de 1 USD/mes: 5,000 consultas) cuando hay algún partido de docs/datos/cfb.json en juego: desde 10 min antes de la
patada hasta 4 h 30 min después. Escribe Firestore vivo/cfb = {t, g: {id: [pts_local, pts_visita, cuarto, reloj, estado, posesión]}}
(la página lo lee con un solo listener). Tope: 3,000 consultas al mes (lleva la cuenta en sistema/avisos → E["cfbv"]).
"""
import json, os, time, urllib.request
from datetime import datetime, timezone

KEY = os.environ.get("CFBD_API_KEY", "").strip()
TOPE = 3000


def _g(x, *ks):
    for k in ks:
        if isinstance(x, dict) and x.get(k) is not None: return x[k]
    return None


def corre(av):
    try: C = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "datos", "cfb.json"), encoding="utf-8"))
    except Exception: return
    now = time.time()
    def ts(g):
        try: return datetime.fromisoformat(g["ko"].replace("Z", "+00:00")).timestamp()
        except Exception: return 0
    ids = {str(g["id"]) for g in C.get("games", []) if g.get("ko") and not g.get("ok") and ts(g) - 600 <= now <= ts(g) + 4.5 * 3600}
    if not ids: return
    mes = datetime.now(timezone.utc).strftime("%Y-%m")
    U = av.E.setdefault("cfbv", {})
    if not KEY or U.get(mes, 0) >= TOPE:
        print("Colegial en vivo: sin llave o se llegó al tope del mes"); return
    try:
        r = urllib.request.Request("https://api.collegefootballdata.com/scoreboard?classification=fbs",
                                   headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json", "User-Agent": "lapizarra.mx"})
        with urllib.request.urlopen(r, timeout=25) as x: S = json.loads(x.read().decode())
        U[mes] = U.get(mes, 0) + 1
    except Exception as e:
        print("Colegial en vivo:", getattr(e, "code", ""), str(e)[:150]); return
    out = {}
    for x in S or []:
        gid = str(_g(x, "id"))
        if gid not in ids: continue
        h, a = _g(x, "homeTeam", "home_team") or {}, _g(x, "awayTeam", "away_team") or {}
        st = (_g(x, "status") or "").lower()
        out[gid] = [_g(h, "points"), _g(a, "points"), _g(x, "period"), _g(x, "clock") or "",
                    "fin" if "complet" in st or "final" in st else "vivo" if "progress" in st or "live" in st else "prog",
                    _g(x, "possession") or ""]
    av.db.c.collection("vivo").document("cfb").set({"t": int(now), "g": out})
    av.db.guarda_estado(av.E)
    print(f"Colegial en vivo: {len(out)} partidos ({sum(1 for v in out.values() if v[4] == 'vivo')} en juego); consultas del mes {U[mes]}")
