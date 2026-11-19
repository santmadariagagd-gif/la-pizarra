"""
leer_reglas.py — baja las reglas de Firestore publicadas (19 nov 2026), cifradas, para armar el archivo completo.

Las reglas traen el correo del dueño y el log/artefactos de GitHub son públicos: por eso se cifran con la llave pública
que llega como input (RSA + AES); solo quien tiene la llave privada (Claude, en su sesión) las puede leer.
"""
import base64, json, os, subprocess
import google.auth.transport.requests
from google.oauth2 import service_account

sa = json.loads(os.environ["FIREBASE_SA"]); pid = sa["project_id"]
cr = service_account.Credentials.from_service_account_info(sa, scopes=["https://www.googleapis.com/auth/cloud-platform"])
s = google.auth.transport.requests.AuthorizedSession(cr)
r = s.get(f"https://firebaserules.googleapis.com/v1/projects/{pid}/releases/cloud.firestore"); print("release:", r.status_code)
r.raise_for_status(); rs = r.json()["rulesetName"]
r = s.get(f"https://firebaserules.googleapis.com/v1/{rs}"); print("ruleset:", r.status_code, r.json().get("createTime"))
src = r.json()["source"]["files"][0]["content"]
os.makedirs("salida", exist_ok=True)
open("salida/pub.pem", "wb").write(base64.b64decode(os.environ["PUB"]))
open("salida/reglas.txt", "w").write(src)
subprocess.run("cd salida && openssl rand -out k.bin 32 && openssl enc -aes-256-cbc -pbkdf2 -salt -in reglas.txt -out reglas.enc -pass file:k.bin "
               "&& openssl pkeyutl -encrypt -pubin -inkey pub.pem -in k.bin -out k.enc && rm reglas.txt k.bin", shell=True, check=True)
print("Reglas cifradas:", len(src), "caracteres")
# el log es público pero va cifrado; así se puede bajar sin artefactos
for n in ("k.enc", "reglas.enc"):
    b = base64.b64encode(open("salida/" + n, "rb").read()).decode()
    print(f"==={n}===")
    for i in range(0, len(b), 4000): print("CIF:" + b[i:i + 4000])
