"""
contar_cuentas.py — cuántas cuentas y cuánta gente juega (3 nov 2026). Solo números: no guarda correos ni nombres.
Escribe bitacora/cuentas.json. Se corre con la automatización "Contar cuentas" (workflow_dispatch). Necesita FIREBASE_SA.
"""
import json, os, time
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import auth, credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SA"])))
db = firestore.client()
ahora = time.time() * 1000
U = list(auth.list_users().iterate_all())
dias = lambda n: sum(1 for u in U if (u.user_metadata.creation_timestamp or 0) > ahora - n * 864e5)
activos = lambda n: sum(1 for u in U if max(u.user_metadata.last_sign_in_timestamp or 0, getattr(u.user_metadata, "last_refresh_timestamp", 0) or 0) > ahora - n * 864e5)
prov = {}
for u in U:
    for p in u.provider_data or []: prov[p.provider_id] = prov.get(p.provider_id, 0) + 1
cuenta = lambda col: int(db.collection(col).count().get()[0][0].value)
uids = lambda col, campo="uid": len({(d.to_dict() or {}).get(campo) for d in db.collection(col).select([campo]).stream()} - {None})
out = {
    "al": datetime.now(timezone.utc).isoformat(),
    "cuentas": len(U), "verificadas": sum(1 for u in U if u.email_verified),
    "nuevas_7d": dias(7), "nuevas_30d": dias(30), "activas_7d": activos(7), "activas_30d": activos(30),
    "por_forma_de_entrar": prov,
    "perfiles": cuenta("perfiles"), "amistades": cuenta("amistades"), "grupos": cuenta("grupos"),
    "con_avisos_al_telefono": cuenta("avisos_tk"),
    "juegan": {"quiniela_liga_mx": uids("qmx_picks"), "survivor_liga_mx": uids("smx_picks"), "fantasy": uids("fan_ucl"),
               "reto_del_dia": uids("rd_resp"), "duelos": cuenta("duelos"), "posts": cuenta("posts")},
}
os.makedirs("bitacora", exist_ok=True)
json.dump(out, open("bitacora/cuentas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(out)
