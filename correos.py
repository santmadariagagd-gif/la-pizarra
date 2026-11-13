"""
correos.py — recordatorios por correo (13 nov 2026). Los llama avisos.py en cada corrida (cada 5 min con cron-job.org).

Por qué: casi nadie prende los avisos al teléfono (1 de 18 cuentas). El correo le llega a todos los que tienen cuenta.
Se mandan con Resend (secreto RESEND_API_KEY, dominio lapizarra.mx verificado) desde avisos@lapizarra.mx.

Dos correos, nada más:
  1. Cierre de la Quiniela Liga MX (jornada, Liguilla o Llave): entre 2 y 8 horas antes del cierre, a quien jugó la anterior
     y todavía no hace sus picks. Si ya le llega el aviso al teléfono de "Recordatorios", no se le manda correo.
  2. Tu semana (lunes de 9 a 12): cómo te fue (aciertos, lugar, reto, survivor, fantasy) y lo que viene.
Cada correo trae link para dejar de recibirlos (lapizarra.mx/?correos=0 → Firestore correos/{uid}.no = true).
Lo enviado se anota en sistema/avisos (E["mail"]) para no repetir. Máx. 90 correos por corrida (Resend gratis: 100 al día).
"""
import hashlib, html, json, os, time, urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

MX = ZoneInfo("America/Mexico_City")
KEY = os.environ.get("RESEND_API_KEY", "")
DE = "La Pizarra <avisos@lapizarra.mx>"
WEB = "https://lapizarra.mx"
BAJA = WEB + "/?correos=0"
TOPE = 90
NJ = {18: "los cuartos de final", 19: "las semifinales", 20: "la final", "llave": "la Llave de la Liguilla"}
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def cuando(ts):
    d = datetime.fromtimestamp(ts, MX); hoy = datetime.now(MX).date()
    h = d.strftime("%I:%M").lstrip("0") + (" am" if d.hour < 12 else " pm")
    dia = "hoy" if d.date() == hoy else "mañana" if (d.date() - hoy).days == 1 else f"el {DIAS[d.weekday()]}"
    return f"{dia} a las {h}"


def plantilla(titulo, parrafos, boton, url, pie=""):
    """Correo sencillo con los colores de La Pizarra (pizarrón verde, amarillo). Tablas para que se vea bien en Gmail/Outlook."""
    P = "".join(f'<p style="margin:0 0 14px;font-size:16px;line-height:1.5;color:#ECEFE7">{p}</p>' for p in parrafos)
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(titulo)}</title></head>
<body style="margin:0;background:#15241F;font-family:Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#15241F;padding:24px 12px"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#1F332D;border-radius:16px;border:1px solid #3A554C">
<tr><td style="padding:22px 24px 6px;font:800 24px Helvetica,Arial,sans-serif;color:#ECEFE7">La <span style="color:#F2D466">Pizarra</span></td></tr>
<tr><td style="padding:10px 24px 4px"><h1 style="margin:0 0 14px;font:800 26px/1.15 Helvetica,Arial,sans-serif;color:#ECEFE7">{html.escape(titulo)}</h1>{P}
<a href="{url}" style="display:inline-block;margin:6px 0 18px;background:#F2D466;color:#15241F;text-decoration:none;font:700 17px Helvetica,Arial,sans-serif;padding:13px 22px;border-radius:12px">{html.escape(boton)}</a></td></tr>
<tr><td style="padding:14px 24px 22px;border-top:1px solid #3A554C;font-size:12px;line-height:1.5;color:#A8B8AF">{pie}Te llega porque tienes cuenta en La Pizarra.
<a href="{BAJA}" style="color:#A8B8AF">Ya no quiero estos correos</a>.</td></tr>
</table></td></tr></table></body></html>"""


def texto_plano(titulo, parrafos, boton, url):
    import re
    limpio = lambda s: re.sub(r"<[^>]+>", "", s)
    return f"{titulo}\n\n" + "\n\n".join(limpio(p) for p in parrafos) + f"\n\n{boton}: {url}\n\n—\nLa Pizarra · Ya no quiero estos correos: {BAJA}\n"


class Correos:
    def __init__(self, av):
        self.av, self.db, self.E = av, av.db, av.E
        self.E.setdefault("mail", {})
        self.n = 0; self._quien = None

    # ---- quién puede recibir: cuentas con correo confirmado que no los apagaron ----
    def quien(self):
        if self._quien is None:
            from firebase_admin import auth
            no = {d.id for d in self.db.c.collection("correos").stream() if (d.to_dict() or {}).get("no")}
            self._quien = {u.uid: (u.email, (u.display_name or "").split(" ")[0]) for u in auth.list_users().iterate_all()
                           if u.email and u.email_verified and not u.disabled and u.uid not in no}
        return self._quien

    def manda(self, uid, clave, asunto, titulo, parrafos, boton, url):
        if clave in self.E["mail"] or self.n >= TOPE: return
        q = self.quien().get(uid)
        if not q: return
        email, nom = q
        if not KEY: print(f"✉ (sin RESEND_API_KEY) {uid[:6]}… {asunto}"); return
        cuerpo = dict(**{"from": DE}, to=[email], subject=asunto, html=plantilla(titulo, parrafos, boton, url),
                      text=texto_plano(titulo, parrafos, boton, url),
                      headers={"List-Unsubscribe": f"<{BAJA}>"}, tags=[{"name": "tipo", "value": clave.split("-")[0]}])
        try:
            r = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(cuerpo).encode(), method="POST",
                                       headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json", "User-Agent": "la-pizarra-correos/1.0"})
            with urllib.request.urlopen(r, timeout=20) as x: x.read()
            self.E["mail"][clave] = int(time.time()); self.n += 1
            print(f"✉ {uid[:6]}… {asunto}")
        except Exception as e:
            print("Correo:", getattr(e, "code", ""), str(getattr(e, "read", lambda: b"")() or e)[:200])

    # ---- 1. cierre de la Quiniela Liga MX ----
    def cierres(self):
        now = time.time()
        for jd in self.db.rango("qmx_jornadas", "primero", now + 2 * 3600, now + 8 * 3600):
            jid, sl, j, ts = jd["_id"], jd.get("s"), jd.get("j"), jd["_ts"]
            if j == "llave": prev = f"{sl}-17"
            elif isinstance(j, int): prev = f"{sl}-{j - 1}"
            else: continue
            nj = NJ.get(j, f"la jornada {j}")
            Q = self.db.donde("qmx_picks", "jid", "in", [jid, prev])
            jug = {d.get("uid") for d in Q if d.get("jid") == prev}
            hechos = {d.get("uid") for d in Q if d.get("jid") == jid and (d.get("p") or {})}
            for uid in jug - hechos:
                S = self.av.subs.get(uid)
                if S and S.get("tk") and S.get("p", {}).get("cie", 1): continue   # ya le llega al teléfono
                nom = self.quien().get(uid, ("", ""))[1]
                q = (f"{html.escape(nom)}, todavía" if nom else "Todavía") + f" no haces tus picks de {nj} en la Quiniela Liga MX."
                self.manda(uid, f"cie-{jid}-{uid[:10]}", f"⏰ {nj[0].upper() + nj[1:]} cierra {cuando(ts)}",
                           f"Cierra {cuando(ts)}", [q, "Son dos minutos: escoge local, empate o visita en cada partido. Si no, esa jornada vale cero en la tabla."],
                           "Hacer mis picks", WEB + "/#quinielamx")

    # ---- 2. tu semana (lunes) ----
    def semanal(self, solo=None):
        ahora = datetime.now(MX)
        if solo is None and (ahora.weekday() != 0 or not (9 <= ahora.hour < 12)): return
        sem = ahora.date().isoformat() if solo is None else f"prueba{int(time.time())}"
        L = self.av.lineas_semana(list(self.quien()))
        prox = self.av.lo_que_viene()
        for uid in (solo or list(self.quien())):
            P = L.get(uid) or []
            nom = self.quien()[uid][1]
            parr = []
            if P: parr.append((f"{html.escape(nom)}, así" if nom else "Así") + " te fue la semana pasada:<br>" + "<br>".join("• " + html.escape(p[:1].upper() + p[1:]) for p in P[:5]))
            else: parr.append((f"{html.escape(nom)}, esta" if nom else "Esta") + " semana en La Pizarra:")
            if prox: parr.append("Lo que viene:<br>" + "<br>".join("• " + html.escape(x) for x in prox[:4]))
            parr.append("Reta a un amigo, haz tus picks y presume tu semana en el grupo.")
            self.manda(uid, f"sem-{sem}-{uid[:10]}", "📊 Tu semana en La Pizarra", "Tu semana en La Pizarra", parr, "Ver mi semana", WEB + "/?sem=1")

    def prueba(self):
        """Workflow "Avisos" a mano con prueba_correo=1: manda el correo del lunes solo al dueño (huella del correo)."""
        duenos = [u for u, (e, _) in self.quien().items() if hashlib.sha256(e.strip().lower().encode()).hexdigest()[:16] == "bbd57af465240ba7"]
        print(f"Correo de prueba al dueño: {len(duenos)} cuenta(s)")
        self.semanal(solo=duenos)

    def corre(self):
        if os.environ.get("CORREO_PRUEBA") == "1":
            try: self.prueba()
            except Exception as e: print("Correos (prueba):", repr(e))
        try: self.cierres()
        except Exception as e: print("Correos (cierres):", repr(e))
        try: self.semanal()
        except Exception as e: print("Correos (semana):", repr(e))
        if self.n: print(f"Correos mandados: {self.n}")
