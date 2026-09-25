# API Cahier de Prépa

Client Python, synchronisation de fichiers et serveur HTTP JSON pour un compte
élève sur un site [Cahier de Prépa](https://cahier-de-prepa.fr) (testé sur
`ecg1-clemenceau`, version 13).

Le site n'a pas d'API : tout passe par la connexion web et le parsing du HTML.
Si le site est mis à jour, un parseur peut casser (voir `cahier_prepa/client.py`).

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # puis remplis les valeurs
```

`.env` :

| Variable | Rôle |
|---|---|
| `CDP_BASE_URL` | URL du site, ex. `https://cahier-de-prepa.fr/your-class` |
| `CDP_LOGIN` / `CDP_PASSWORD` | Ton compte élève |
| `CDP_API_KEY` | Clé exigée par le serveur HTTP (en-tête `X-API-Key`) |
| `CDP_DOWNLOAD_DIR` | Dossier de la synchro via le serveur (défaut `downloads`) |

## Ligne de commande

Sortie en JSON. Préfixe : `.venv/bin/python -m cahier_prepa`.

| Commande | Rôle |
|---|---|
| `matieres` | Matières et rubriques disponibles (colles, cdt, docs) |
| `colles <matière> [-n N \| --tout]` | Programme de colles (semaine courante par défaut) |
| `cdt <matière> [-n N \| --tout] [--voir cours\|TP\|DS]` | Cahier de texte |
| `semaines <matière> [--rubrique cdt]` | Numéros de semaines pour `-n` |
| `docs [matière] [--rep ID]` | Répertoires et documents |
| `agenda [--mois AAMM]` | Événements du mois (ex. `2610`) |
| `recents [--type …] [--matiere …] [--recherche …]` | Nouveautés |
| `download <id> [--dest dossier]` | Télécharge un fichier |
| `sync` | Voir ci-dessous |

Les clés de matière viennent de `matieres` (ex. `maths`, `hgg`, `angl`).

## Synchronisation automatique

```bash
python -m cahier_prepa sync                       # télécharge le nouveau / modifié
python -m cahier_prepa sync --dry-run             # liste sans télécharger
python -m cahier_prepa sync --baseline            # mémorise l'existant, sans télécharger
python -m cahier_prepa sync --webhook https://…   # POST {"nouveaux": [...]} s'il y a du nouveau
```

Options : `--dest` (défaut `downloads`), `--state` (défaut `.sync_state.json`).

- Les fichiers sont rangés comme sur le site : `downloads/Matière/Dossier/fichier.pdf`.
- Un fichier est retéléchargé si le prof l'a remplacé (le paramètre `v=` de son lien change).
- La première exécution télécharge tout. Pour ne récupérer que les futurs documents, lance `--baseline` d'abord.
- La commande renvoie la liste JSON des fichiers nouveaux (`[]` s'il n'y en a pas).


## Serveur HTTP

```bash
.venv/bin/uvicorn cahier_prepa.server:app --host 127.0.0.1 --port 8000
```

Toutes les routes exigent l'en-tête `X-API-Key: <CDP_API_KEY>` (401 sinon).

| Route | Rôle |
|---|---|
| `GET /matieres` | Matières |
| `GET /recents?type=&matiere=&recherche=` | Nouveautés |
| `GET /colles/{matiere}?semaine=&tout=` | Programme de colles |
| `GET /cdt/{matiere}?semaine=&tout=&voir=` | Cahier de texte |
| `GET /semaines/{matiere}?rubrique=progcolles\|cdt` | Semaines |
| `GET /documents?matiere=` ou `?rep=` | Répertoires et documents |
| `GET /agenda?mois=2610` | Agenda du mois |
| `GET /download/{id}` | Renvoie le fichier |
| `POST /sync?dry_run=&baseline=` | Lance la synchro |

Exemples :

```bash
curl -H "X-API-Key: $CDP_API_KEY" localhost:8000/colles/maths
curl -H "X-API-Key: $CDP_API_KEY" -o dm1.pdf localhost:8000/download/3836
```

Erreurs : `401` clé invalide, `403` contenu inaccessible pour ton compte,
`502` erreur côté Cahier de Prépa ou réseau.

## Utilisation en Python

```python
from cahier_prepa import CahierPrepa

c = CahierPrepa.from_env()
c.login()
c.colles("maths")            # -> [Bloc(titre, texte, liens=[Lien(nom, url, doc_id)])]
c.docs("maths")              # -> Dossier(chemin, repertoires, documents, recents)
c.agenda("2610")             # -> [Evenement(date, titre, type, evt_id)]
c.download(3836, "downloads")
```
