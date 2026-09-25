"""Synchronisation incrémentale des documents vers un dossier local."""

import json
import os
import re
import tempfile
import time
from urllib.parse import parse_qs, urlparse

from .client import AuthError, CahierPrepa, CahierPrepaError, Dossier


def _propre(nom: str) -> str:
    return re.sub(r"[/\\:]+", "-", nom).strip() or "_"


def _version(url: str) -> str:
    return parse_qs(urlparse(url).query).get("v", [""])[0]


def parcourir(c: CahierPrepa, delai: float = 0.2):
    """Parcourt toute l'arborescence de documents, yield chaque `Dossier`."""
    pile: list[dict] = [{}]
    vus: set[str] = set()
    while pile:
        cible = pile.pop()
        cle = cible.get("rep") or cible.get("matiere") or ""
        if cle in vus:
            continue
        vus.add(cle)
        try:
            dossier = c.docs(**cible)
        except AuthError:
            continue  # répertoire verrouillé pour ce compte
        yield dossier
        for r in dossier.repertoires:
            pile.append({"rep": r.cle} if r.cle.isdigit() else {"matiere": r.cle})
        time.sleep(delai)


def _charger(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _sauver(path: str, state: dict) -> None:
    d = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=d, delete=False, encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(f.name, path)


def synchroniser(
    c: CahierPrepa,
    dest: str = "downloads",
    state_path: str = ".sync_state.json",
    baseline: bool = False,
    dry_run: bool = False,
) -> list[dict]:
    """Télécharge les documents nouveaux ou modifiés.

    baseline=True : mémorise tout l'existant sans rien télécharger (à faire une
    fois si tu ne veux que les futurs documents).
    Renvoie la liste des fichiers nouveaux/modifiés.
    """
    state = _charger(state_path)
    nouveaux: list[dict] = []
    for dossier in parcourir(c):
        for doc in dossier.documents:
            cle, v = str(doc.doc_id), _version(doc.url)
            connu = state.get(cle)
            if connu and connu["v"] == v:
                continue
            chemin = [_propre(p) for p in dossier.chemin]
            entree = {
                "doc_id": doc.doc_id,
                "nom": doc.nom,
                "dossier": "/".join(dossier.chemin),
                "date": doc.date,
                "modifie": bool(connu),
                "url": doc.url,
            }
            if not (baseline or dry_run):
                try:
                    entree["fichier"] = c.download(doc.doc_id, os.path.join(dest, *chemin))
                except CahierPrepaError:
                    continue  # accès refusé : on réessaiera au prochain passage
            nouveaux.append(entree)
            if not dry_run:
                state[cle] = {"v": v, "fichier": entree.get("fichier")}
                _sauver(state_path, state)
    return nouveaux
