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
    print(f"Tablero: guardado ({len(h)} días de historial)")
except Exception as ex:
    print("Tablero: no se pudo guardar:", repr(ex))
