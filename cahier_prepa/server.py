"""Serveur HTTP JSON.

Lancement :
    CDP_API_KEY=... .venv/bin/uvicorn cahier_prepa.server:app --host 127.0.0.1 --port 8000
Chaque requête doit envoyer l'en-tête `X-API-Key`.
"""

import os
import secrets
import threading

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .client import AuthError, CahierPrepa, CahierPrepaError
from .sync import synchroniser

API_KEY = os.environ.get("CDP_API_KEY", "")
if not API_KEY:
    raise RuntimeError("Définis CDP_API_KEY (clé exigée dans l'en-tête X-API-Key).")


def verifier_cle(x_api_key: str = Header("")) -> None:
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, "Clé API invalide")


app = FastAPI(
    title="Cahier de Prépa API",
    dependencies=[Depends(verifier_cle)],
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

_verrou = threading.Lock()
_client: CahierPrepa | None = None


def appeler(fn):
    """Exécute fn(client) avec un client connecté, se reconnecte si la session a expiré."""
    global _client
    with _verrou:
        if _client is None:
            _client = CahierPrepa.from_env()
            _client.login()
        try:
            return fn(_client)
        except AuthError:
            _client.login()
            return fn(_client)


@app.exception_handler(AuthError)
def _auth(_, e):
    return JSONResponse({"detail": str(e)}, status_code=403)


@app.exception_handler(CahierPrepaError)
@app.exception_handler(requests.RequestException)
def _amont(_, e):
    return JSONResponse({"detail": f"Erreur côté Cahier de Prépa : {e}"}, status_code=502)


@app.get("/matieres")
def matieres():
    return appeler(lambda c: c.matieres())


@app.get("/recents")
def recents(type: str = "tout", matiere: str = "tout", recherche: str | None = None):
    return appeler(lambda c: c.recents(type, matiere, recherche))


@app.get("/colles/{matiere}")
def colles(matiere: str, semaine: int | None = None, tout: bool = False):
    return appeler(lambda c: c.colles(matiere, semaine, tout))


@app.get("/cdt/{matiere}")
def cdt(matiere: str, semaine: int | None = None, tout: bool = False, voir: str | None = None):
    return appeler(lambda c: c.cdt(matiere, semaine, tout, voir))


@app.get("/semaines/{matiere}")
def semaines(matiere: str, rubrique: str = "progcolles"):
    return appeler(lambda c: c.semaines(matiere, rubrique))


@app.get("/documents")
def documents(matiere: str | None = None, rep: str | None = None):
    return appeler(lambda c: c.docs(matiere, rep))


@app.get("/agenda")
def agenda(mois: str | None = None):
    return appeler(lambda c: c.agenda(mois))


@app.get("/download/{doc_id}")
def download(doc_id: int):
    def ouvrir(c: CahierPrepa):
        r = c.session.get(c._url("download"), params={"id": doc_id}, stream=True, timeout=60)
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):
            r.close()
            raise AuthError(f"Document {doc_id} inaccessible.")
        return r

    r = appeler(ouvrir)
    headers = {k: r.headers[k] for k in ("Content-Disposition", "Content-Length") if k in r.headers}
    return StreamingResponse(
        r.iter_content(65536),
        media_type=r.headers.get("Content-Type", "application/octet-stream"),
        headers=headers,
        background=None,
    )


@app.post("/sync")
def sync(dry_run: bool = False, baseline: bool = False):
    dest = os.environ.get("CDP_DOWNLOAD_DIR", "downloads")
    return appeler(lambda c: synchroniser(c, dest=dest, baseline=baseline, dry_run=dry_run))
