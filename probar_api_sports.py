# Prueba si la llave de API-Football también sirve (plan gratis) para Fórmula 1 y NBA de API-Sports,
# y si el plan gratis deja ver la temporada actual. No imprime la llave. Escribe prueba_api_sports.txt.
import os, json, urllib.request
KEY=os.environ.get("API_FOOTBALL_KEY","").strip()
P=[("F1 estado","https://v1.formula-1.api-sports.io/status"),
   ("F1 carreras 2026","https://v1.formula-1.api-sports.io/races?season=2026&type=Race"),
   ("F1 pilotos 2026","https://v1.formula-1.api-sports.io/rankings/drivers?season=2026"),
   ("NBA estado","https://v2.nba.api-sports.io/status"),
   ("NBA juegos 2026-27","https://v2.nba.api-sports.io/games?season=2026&date=2026-10-27"),
   ("NBA tabla 2026-27","https://v2.nba.api-sports.io/standings?league=standard&season=2026")]
out=[]
for n,u in P:
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers={"x-apisports-key":KEY}),timeout=30); d=json.load(r)
        resp=d.get("response"); err=d.get("errors")
        if n.endswith("estado"):
            s=resp if isinstance(resp,dict) else {}
            out.append(f"{n}: plan={((s.get('subscription') or {}).get('plan'))} activo={((s.get('subscription') or {}).get('active'))} usadas hoy={((s.get('requests') or {}).get('current'))}/{((s.get('requests') or {}).get('limit_day'))} errores={err}")
        else:
            ej=json.dumps((resp or [None])[0],ensure_ascii=False)[:300] if resp else ""
            out.append(f"{n}: resultados={len(resp or [])} errores={err} ejemplo={ej}")
    except Exception as ex: out.append(f"{n}: falló {ex}")
open("prueba_api_sports.txt","w",encoding="utf-8").write("\n".join(out)+"\n"); print("\n".join(out))
