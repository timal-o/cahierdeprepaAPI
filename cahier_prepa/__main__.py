"""CLI : python -m cahier_prepa <commande> ... (sortie JSON)."""

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass

from .client import CahierPrepa, CahierPrepaError


def _dump(obj) -> None:
    def conv(o):
        if isinstance(o, list):
            return [conv(x) for x in o]
        return asdict(o) if is_dataclass(o) else o

    print(json.dumps(conv(obj), ensure_ascii=False, indent=2))


def main() -> int:
    p = argparse.ArgumentParser(prog="cahier_prepa")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("matieres", help="matières et rubriques disponibles")

    r = sub.add_parser("recents", help="nouveautés")
    r.add_argument("--type", default="tout", choices=["tout", "infos", "colles", "docs", "agenda"])
    r.add_argument("--matiere", default="tout")
    r.add_argument("--recherche")

    for name, helptxt in (("colles", "programme de colles"), ("cdt", "cahier de texte")):
        c = sub.add_parser(name, help=helptxt)
        c.add_argument("matiere")
        g = c.add_mutually_exclusive_group()
        g.add_argument("-n", "--semaine", type=int, help="numéro de semaine (voir `semaines`)")
        g.add_argument("--tout", action="store_true", help="toute l'année")
        if name == "cdt":
            c.add_argument("--voir", choices=["cours", "TP", "DS"])

    s = sub.add_parser("semaines", help="liste des semaines")
    s.add_argument("matiere")
    s.add_argument("--rubrique", default="progcolles", choices=["progcolles", "cdt"])

    d = sub.add_parser("docs", help="arborescence de documents")
    d.add_argument("matiere", nargs="?")
    d.add_argument("--rep", help="identifiant de répertoire")

    a = sub.add_parser("agenda", help="agenda du mois")
    a.add_argument("--mois", help="AAMM, ex. 2610")

    dl = sub.add_parser("download", help="télécharger un document")
    dl.add_argument("doc_id")
    dl.add_argument("--dest", default="downloads")

    sy = sub.add_parser("sync", help="télécharge les documents nouveaux/modifiés")
    sy.add_argument("--dest", default="downloads")
    sy.add_argument("--state", default=".sync_state.json")
    sy.add_argument("--baseline", action="store_true", help="mémorise l'existant sans télécharger")
    sy.add_argument("--dry-run", action="store_true", help="liste sans télécharger ni mémoriser")
    sy.add_argument("--webhook", help="URL appelée en POST (JSON) s'il y a du nouveau")

    args = p.parse_args()
    try:
        c = CahierPrepa.from_env()
        if c.login_name:
            c.login()
        if args.cmd == "matieres":
            _dump(c.matieres())
        elif args.cmd == "recents":
            _dump(c.recents(args.type, args.matiere, args.recherche))
        elif args.cmd == "colles":
            _dump(c.colles(args.matiere, args.semaine, args.tout))
        elif args.cmd == "cdt":
            _dump(c.cdt(args.matiere, args.semaine, args.tout, args.voir))
        elif args.cmd == "semaines":
            _dump(c.semaines(args.matiere, args.rubrique))
        elif args.cmd == "docs":
            _dump(c.docs(args.matiere, args.rep))
        elif args.cmd == "agenda":
            _dump(c.agenda(args.mois))
        elif args.cmd == "sync":
            from .sync import synchroniser

            nouveaux = synchroniser(c, args.dest, args.state, args.baseline, args.dry_run)
            _dump(nouveaux)
            if nouveaux and args.webhook and not args.dry_run:
                import requests

                requests.post(args.webhook, json={"nouveaux": nouveaux}, timeout=20).raise_for_status()
        elif args.cmd == "download":
            print(c.download(args.doc_id, args.dest))
    except (CahierPrepaError, KeyError) as e:
        print(f"Erreur : {e!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
