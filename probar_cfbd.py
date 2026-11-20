"""probar_cfbd.py — revisa el plan de College Football Data (/info) y que responda el marcador en vivo (/scoreboard). 20 nov 2026."""
import json, os, urllib.request
K = os.environ.get("CFBD_API_KEY", "").strip()
def get(r):
    q = urllib.request.Request("https://api.collegefootballdata.com" + r, headers={"Authorization": f"Bearer {K}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(q, timeout=30) as x: return x.status, json.loads(x.read().decode())
    except Exception as e: return getattr(e, "code", None), str(e)[:200]
c, i = get("/info"); print("info:", c, {k: i.get(k) for k in ("patronLevel", "remainingCalls")} if isinstance(i, dict) else i)
c, s = get("/scoreboard?classification=fbs"); print("scoreboard:", c, f"{len(s)} partidos" if isinstance(s, list) else s)
if isinstance(s, list) and s: print("estados:", sorted({str(x.get("status")) for x in s}))
