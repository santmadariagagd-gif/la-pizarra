"""
contar_cuentas.py — cuántas cuentas y cuánta gente juega (3 nov 2026; tablero 4 nov 2026).

1. bitacora/cuentas.json: solo números (sin correos ni nombres). Es público (está en el repositorio).
2. Firestore admin/tablero: el tablero de Santiago (lapizarra.mx/?tablero=1). Trae además apodos de las cuentas nuevas,
   quién invitó a quién y los pedidos de El Pizarrón. Solo lo puede leer la cuenta del dueño (reglas de Firebase).
   Guarda un historial diario (h) para las gráficas.
Se corre cada día con la automatización "Contar cuentas" y también a mano. Necesita FIREBASE_SA.
"""
import json, os, time
from collections import Counter
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import firebase_admin
from firebase_admin import auth, credentials, firestore

MX = ZoneInfo("America/Mexico_City")
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SA"])))
db = firestore.client()
ahora = time.time() * 1000
U = list(auth.list_users().iterate_all())
ult = lambda u: max(u.user_metadata.last_sign_in_timestamp or 0, getattr(u.user_metadata, "last_refresh_timestamp", 0) or 0)
dias = lambda n: sum(1 for u in U if (u.user_metadata.creation_timestamp or 0) > ahora - n * 864e5)
activos = lambda n: sum(1 for u in U if ult(u) > ahora - n * 864e5)
prov = Counter(p.provider_id for u in U for p in (u.provider_data or []))
cuenta = lambda col: int(db.collection(col).count().get()[0][0].value)
docs = lambda col, *campos: [d.to_dict() or {} for d in db.collection(col).select(list(campos)).stream()]
uids = lambda col, campo="uid": len({x.get(campo) for x in docs(col, campo)} - {None})

out = {
    "al": datetime.now(timezone.utc).isoformat(),
    "cuentas": len(U), "verificadas": sum(1 for u in U if u.email_verified),
    "nuevas_7d": dias(7), "nuevas_30d": dias(30), "activas_7d": activos(7), "activas_30d": activos(30),
    "por_forma_de_entrar": dict(prov),
    "perfiles": cuenta("perfiles"), "amistades": cuenta("amistades"), "grupos": cuenta("grupos"),
    "con_avisos_al_telefono": cuenta("avisos_tk"),
    "juegan": {"quiniela_liga_mx": uids("qmx_picks"), "survivor_liga_mx": uids("smx_picks"), "fantasy": uids("fan_ucl"),
               "reto_del_dia": uids("rd_resp"), "duelos": cuenta("duelos"), "posts": cuenta("posts")},
    "pizarron_pedidos": int(db.collection("pizarron").where("est", "==", "pedido").count().get()[0][0].value),
}
os.makedirs("bitacora", exist_ok=True)
json.dump(out, open("bitacora/cuentas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(out)

# ---------------- Tablero (solo para el dueño) ----------------
try:
    hoy = datetime.now(MX).date()
    dia = lambda ms: datetime.fromtimestamp(ms / 1000, MX).date().isoformat()
    perf = {d.id: (d.to_dict() or {}) for d in db.collection("perfiles").select(["a", "iv"]).stream()}
    alias = lambda uid: (perf.get(uid, {}).get("a") or "Sin apodo")[:24]
    # altas por día (últimos 60 días) y el total acumulado
    altas = Counter(dia(u.user_metadata.creation_timestamp) for u in U if u.user_metadata.creation_timestamp)
    inicio = hoy - timedelta(days=59); total = sum(n for d, n in altas.items() if d < inicio.isoformat()); serie = []
    for i in range(60):
        d = (inicio + timedelta(days=i)).isoformat(); total += altas.get(d, 0); serie.append([d, altas.get(d, 0), total])
    # actividad por día (último acceso: solo cuenta el más reciente de cada quien) y juego por jornada
    act1 = activos(1)
    qmx = Counter(); smx = Counter(); fan = Counter(); rd = Counter()
    for x in docs("qmx_picks", "s", "j"):
        if x.get("s") and x.get("j") is not None: qmx[f"{x['s']}-{x['j']}"] += 1
    for x in docs("smx_picks", "s", "j"):
        if x.get("s") and x.get("j") is not None: smx[f"{x['s']}-{x['j']}"] += 1
    for d in db.collection("fan_ucl").select(["uid"]).stream():
        fan[d.id.rsplit("_", 1)[0]] += 1
    for d in db.collection("rd_resp").select(["uid"]).stream():
        rd[d.id.split("_", 1)[0]] += 1
    ult_n = lambda C, n: sorted(C.items(), key=lambda kv: kv[0])[-n:]
    rd14 = [[(hoy - timedelta(days=13 - i)).isoformat(), rd.get((hoy - timedelta(days=13 - i)).isoformat(), 0)] for i in range(14)]
    # invitaciones
    inv = Counter(x.get("iv") for x in perf.values() if x.get("iv"))
    invit = [[alias(u), n] for u, n in inv.most_common(10)]
    # cuentas nuevas (apodo, fecha, cómo entró) y pedidos de El Pizarrón
    nuevas = sorted(U, key=lambda u: -(u.user_metadata.creation_timestamp or 0))[:12]
    rec = [[alias(u.uid), dia(u.user_metadata.creation_timestamp or 0), (u.provider_data[0].provider_id if u.provider_data else "?").replace(".com", ""),
            dia(ult(u)) if ult(u) else ""] for u in nuevas]
    piz = []
    for d in db.collection("pizarron").stream():
        x = d.to_dict() or {}; t = x.get("t")
        piz.append(dict(liga=x.get("liga") or d.id, nom=x.get("nom", ""), picante=x.get("picante", ""), titulo=x.get("titulo", ""), est=x.get("est", ""),
                        quien=alias(x.get("uid")), f=t.astimezone(MX).date().isoformat() if t else ""))
    ref = db.collection("admin").document("tablero"); viejo = (ref.get().to_dict() or {}) if ref.get().exists else {}
    h = [x for x in (viejo.get("h") or []) if x.get("d") != hoy.isoformat()]
    h.append(dict(d=hoy.isoformat(), c=len(U), a1=act1, a7=out["activas_7d"], p=out["con_avisos_al_telefono"], j=sum(out["juegan"][k] for k in ("quiniela_liga_mx", "survivor_liga_mx", "fantasy", "reto_del_dia"))))
    ref.set(dict(al=out["al"], n=out, altas=serie, a1=act1, qmx=ult_n(qmx, 6), smx=ult_n(smx, 6), fan=ult_n(fan, 6), rd=rd14,
                 inv=invit, invitados=sum(inv.values()), nuevas=rec, pizarron=piz, h=h[-180:]))
    print(f"Tablero: guardado ({len(h)} días de historial)"); est = dict(ok=True, dias=len(h), altas=len(serie), qmx=len(qmx), pizarron=len(piz))
except Exception as ex:
    print("Tablero: no se pudo guardar:", repr(ex)); est = dict(ok=False, error=repr(ex)[:300])
json.dump(dict(al=out["al"], **est), open("bitacora/tablero_estado.json", "w", encoding="utf-8"), ensure_ascii=False)

# ---------------- Retención (18 nov 2026): una fila por cuenta, SIN nombres ni ids (el log es público) ----------------
# Para ver quién regresa y qué usa la gente que regresa. Último uso = lo más reciente entre el último acceso de la cuenta,
# la última sincronización (usuarios.t), su último reto del día y su último post.
try:
    from collections import defaultdict
    hoyd = datetime.now(MX).date()
    rd_u = defaultdict(list)
    for d in db.collection("rd_resp").select(["uid"]).stream():
        f, _, uid = d.id.partition("_"); rd_u[uid].append(f)
    qmx_u = Counter(x.get("uid") for x in docs("qmx_picks", "uid"))
    fan_u = Counter(x.get("uid") for x in docs("fan_ucl", "uid"))
    post_u = defaultdict(list)
    for d in db.collection("posts").select(["uid", "t"]).stream():
        x = d.to_dict() or {}; t = x.get("t")
        post_u[x.get("uid")].append(t.astimezone(MX).date() if hasattr(t, "astimezone") else None)
    am_u = Counter()
    for x in docs("amistades", "u", "est"):
        if x.get("est") == "ok":
            for u in x.get("u") or []: am_u[u] += 1
    push_u = {d.id for d in db.collection("avisos_tk").stream()}
    usu = {}
    for d in db.collection("usuarios").stream():
        x = d.to_dict() or {}; pk = (x.get("picks") or {}).get(str(datetime.now().year)) or {}
        t = x.get("t")
        usu[d.id] = dict(t=t.astimezone(MX).date() if hasattr(t, "astimezone") else None, nfl=len([w for w, v in pk.items() if v]),
                         sl=1 if x.get("liga") or x.get("sleeper") else 0, fav=len(x.get("fav") or []) if isinstance(x.get("fav"), list) else len((x.get("fav") or {}).keys()) if isinstance(x.get("fav"), dict) else 0)
    filas = []
    for u in sorted(U, key=lambda u: u.user_metadata.creation_timestamp or 0):
        alta = datetime.fromtimestamp((u.user_metadata.creation_timestamp or 0) / 1000, MX).date()
        fechas = [datetime.fromtimestamp(ult(u) / 1000, MX).date()] if ult(u) else []
        us = usu.get(u.uid, {})
        if us.get("t"): fechas.append(us["t"])
        rds = sorted(rd_u.get(u.uid, []))
        if rds: fechas.append(datetime.fromisoformat(rds[-1]).date())
        fechas += [f for f in post_u.get(u.uid, []) if f]
        ultimo = max(fechas) if fechas else alta
        filas.append(dict(alta=(hoyd - alta).days, ult=(hoyd - ultimo).days, nfl=us.get("nfl", 0), qmx=qmx_u.get(u.uid, 0), rd=len(rds),
                          rd7=sum(1 for f in rds if (hoyd - datetime.fromisoformat(f).date()).days < 7), fan=fan_u.get(u.uid, 0),
                          posts=len(post_u.get(u.uid, [])), amigos=am_u.get(u.uid, 0), sleeper=us.get("sl", 0), push=int(u.uid in push_u),
                          fav=us.get("fav", 0), apodo=int(bool(perf.get(u.uid, {}).get("a"))), invitado=int(bool(perf.get(u.uid, {}).get("iv")))))
    print("Retención (una fila por cuenta, sin nombres):")
    print("alta_dias ult_dias nfl_semanas qmx_jornadas reto_dias reto_7d fantasy posts amigos sleeper push favs apodo invitado")
    for f in filas: print(" ".join(str(f[k]) for k in ("alta", "ult", "nfl", "qmx", "rd", "rd7", "fan", "posts", "amigos", "sleeper", "push", "fav", "apodo", "invitado")))
except Exception as ex:
    print("Retención: no se pudo:", repr(ex))

# ---------------- Tablero v2 (25 nov 2026): regresan, qué más usan, avisos y correos, salud de las automatizaciones ----------------
# Todo va a admin/tablero (solo lo lee el dueño). En el log solo números (es público).
try:
    extra = {}
    try:
        F = filas
        viejas = [f for f in F if f["alta"] >= 2]
        extra["ret"] = dict(viejas=len(viejas), regresaron=sum(1 for f in viejas if f["ult"] < f["alta"]),
                            semana=sum(1 for f in viejas if f["ult"] < f["alta"] and f["ult"] <= 6),
                            nuevas_30=[sum(1 for f in F if f["alta"] < 30 and f["alta"] >= 2), sum(1 for f in F if 2 <= f["alta"] < 30 and f["ult"] < f["alta"])])
        extra["j2"] = dict(nfl=sum(1 for f in F if f["nfl"]), sleeper=sum(1 for f in F if f["sleeper"]), amigos=sum(1 for f in F if f["amigos"]),
                           favs=sum(1 for f in F if f["fav"]))
    except NameError:
        pass
    try: extra.setdefault("j2", {})["cfb"] = uids("cfb_picks")
    except Exception: pass
    try: extra["j2"]["mocks"] = cuenta("mocks")
    except Exception: pass
    try: extra["j2"]["llave"] = sum(1 for x in docs("qmx_picks", "j") if x.get("j") == "llave")
    except Exception: pass
    # avisos al teléfono y correos (sistema/avisos: lo escribe avisos.py)
    try:
        EA = db.document("sistema/avisos").get().to_dict() or {}
        extra["push"] = sorted([[d, sum(c.values()), c] for d, c in (EA.get("cnt") or {}).items()])[-14:]
        mc = Counter(k.split("-")[0] for k in (EA.get("mail") or {}))
        extra["mail"] = sorted(mc.items(), key=lambda kv: -kv[1])
        extra["cfbv"] = EA.get("cfbv") or {}
    except Exception as ex:
        print("Tablero v2: avisos", repr(ex)[:120])
    # salud de las automatizaciones y lo último que cambió (API de GitHub con el token de la corrida)
    tok, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if tok and repo:
        import urllib.request
        gh = lambda ruta: json.loads(urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{repo}/{ruta}",
                     headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json", "User-Agent": "la-pizarra"}), timeout=30).read())
        try:
            R = gh("actions/runs?per_page=100").get("workflow_runs") or []
            lim = datetime.now(timezone.utc) - timedelta(days=7); W = {}
            for r in R:
                n = r.get("name") or "?"; t = r.get("created_at") or ""
                w = W.setdefault(n, dict(n=n, ult=t, est=r.get("conclusion") or r.get("status"), corridas=0, fallas=0))
                if datetime.fromisoformat(t.replace("Z", "+00:00")) >= lim:
                    w["corridas"] += 1; w["fallas"] += int(r.get("conclusion") == "failure")
            extra["wf"] = sorted(W.values(), key=lambda w: w["ult"], reverse=True)
        except Exception as ex:
            print("Tablero v2: corridas", repr(ex)[:120])
        try:
            C = gh("commits?per_page=60")
            extra["cambios"] = [[c["commit"]["author"]["date"], c["commit"]["message"].split("\n")[0][:140]] for c in C
                                if not c["commit"]["message"].startswith("Actualización automática")][:12]
        except Exception as ex:
            print("Tablero v2: cambios", repr(ex)[:120])
    db.collection("admin").document("tablero").set(extra, merge=True)
    print("Tablero v2:", {k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in extra.items()})
except Exception as ex:
    print("Tablero v2: no se pudo:", repr(ex)[:200])
