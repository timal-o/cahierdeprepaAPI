"""Client pour un site Cahier de Prépa (https://cahier-de-prepa.fr)."""

import os
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

USER_AGENT = "Mozilla/5.0 (cahier-prepa-client)"


class CahierPrepaError(Exception):
    pass


class AuthError(CahierPrepaError):
    pass


@dataclass
class Recent:
    titre: str
    url: str
    date: str
    detail: str


@dataclass
class Lien:
    nom: str
    url: str
    doc_id: int | None = None


@dataclass
class Matiere:
    cle: str
    nom: str
    colles: bool = False
    cdt: bool = False
    docs: bool = False


@dataclass
class Semaine:
    numero: int
    libelle: str
    courante: bool = False


@dataclass
class Bloc:
    """Un <article> : programme de colles ou séance du cahier de texte."""

    titre: str
    texte: str
    liens: list[Lien] = field(default_factory=list)


@dataclass
class Document:
    doc_id: int
    nom: str
    type: str
    date: str
    taille: str
    url: str


@dataclass
class Repertoire:
    nom: str
    cle: str  # "rep=477" -> "477", ou clé de matière ("maths")
    contenu: str
    verrouille: bool = False


@dataclass
class Dossier:
    chemin: list[str]
    repertoires: list[Repertoire]
    documents: list[Document]
    recents: list[Document]


@dataclass
class Evenement:
    date: str  # ISO
    titre: str
    type: int | None
    evt_id: int | None


def _texte(el: Tag) -> str:
    return re.sub(r"[ \t\xa0]+", " ", el.get_text("\n", strip=True)).strip()


def _doc_id(href: str) -> int | None:
    m = re.search(r"[?&]id=(\d+)", href)
    return int(m.group(1)) if m else None


class CahierPrepa:
    def __init__(self, base_url: str, login: str | None = None, password: str | None = None):
        self.base_url = base_url.rstrip("/") + "/"
        self.login_name = login
        self.password = password
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    @classmethod
    def from_env(cls) -> "CahierPrepa":
        from dotenv import load_dotenv

        load_dotenv()
        return cls(
            os.environ["CDP_BASE_URL"],
            os.environ.get("CDP_LOGIN"),
            os.environ.get("CDP_PASSWORD"),
        )

    # -- bas niveau ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path)

    def get_html(self, path: str) -> BeautifulSoup:
        """`path` peut contenir une query string brute (ex. "cdt?hgg&n=3")."""
        r = self.session.get(self._url(path), timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        if soup.select_one("section div.warning") and soup.select_one("#connexion"):
            raise AuthError("Contenu protégé : connexion requise (appelle login()).")
        return soup

    # -- authentification ---------------------------------------------------

    def login(self, remember: bool = False) -> None:
        if not (self.login_name and self.password):
            raise AuthError("Identifiant / mot de passe manquants.")
        data = {"login": self.login_name, "motdepasse": self.password, "connexion": 1}
        if remember:
            data["permconn"] = 1
        r = self.session.post(self._url("ajax.php"), data=data, timeout=20)
        r.raise_for_status()
        try:
            payload = r.json()
        except ValueError:
            raise CahierPrepaError(f"Réponse de connexion inattendue : {r.text[:200]!r}")
        if payload.get("etat") != "ok":
            raise AuthError(payload.get("message", "Connexion refusée"))

    def logout(self) -> None:
        self.session.post(self._url("ajax.php"), data={"action": "deconnexion"}, timeout=20)

    # -- matières -----------------------------------------------------------

    def matieres(self) -> list[Matiere]:
        """Matières visibles dans le menu, avec les rubriques disponibles."""
        soup = self.get_html(".")
        out: list[Matiere] = []
        titres: dict[str, str] = {}
        courant: str | None = None
        for el in soup.select("#menu > h3, #menu > a"):
            if el.name == "h3":
                courant = el.get_text(strip=True)
                continue
            href = el.get("href", "")
            m = re.match(r"(progcolles|cdt|docs)\?([a-z0-9_-]+)$", href, re.I)
            if not m or m.group(2) == "rep":
                continue
            rubrique, cle = m.groups()
            if cle == "general":
                nom = "Général"
            else:
                nom = courant or cle
            titres.setdefault(cle, nom)
            mat = next((x for x in out if x.cle == cle), None)
            if not mat:
                mat = Matiere(cle=cle, nom=titres[cle])
                out.append(mat)
            setattr(mat, {"progcolles": "colles", "cdt": "cdt", "docs": "docs"}[rubrique], True)
        return out

    # -- semaines / colles / cahier de texte -------------------------------

    @staticmethod
    def _semaines(soup: BeautifulSoup) -> list[Semaine]:
        sel = soup.select_one("select#semaines")
        if not sel:
            return []
        return [
            Semaine(int(o["value"]), o.get_text(strip=True), o.has_attr("selected"))
            for o in sel.select("option")
            if o["value"].isdigit() and int(o["value"]) > 0
        ]

    @staticmethod
    def _query(matiere: str, semaine: int | None, tout: bool, extra: str = "") -> str:
        q = matiere
        if tout:
            q += "&tout"
        elif semaine is not None:
            q += f"&n={semaine}"
        return q + extra

    def _blocs(self, soup: BeautifulSoup) -> list[Bloc]:
        blocs = []
        for art in soup.select("section > article"):
            h = art.select_one("h3")
            titre = _texte(h) if h else ""
            liens = [
                Lien(a.get_text(strip=True), self._url(a["href"]), _doc_id(a["href"]))
                for a in art.select("a[href]")
            ]
            clone = BeautifulSoup(str(art), "html.parser")
            if clone.h3:
                clone.h3.decompose()
            blocs.append(Bloc(titre=titre, texte=_texte(clone), liens=liens))
        return blocs

    def semaines(self, matiere: str, rubrique: str = "progcolles") -> list[Semaine]:
        return self._semaines(self.get_html(f"{rubrique}?{matiere}"))

    def colles(self, matiere: str, semaine: int | None = None, tout: bool = False) -> list[Bloc]:
        """Programme de colles. Sans `semaine`, renvoie la semaine courante."""
        return self._blocs(self.get_html("progcolles?" + self._query(matiere, semaine, tout)))

    def cdt(
        self, matiere: str, semaine: int | None = None, tout: bool = False, voir: str | None = None
    ) -> list[Bloc]:
        """Cahier de texte. `voir` : "cours", "TP" ou "DS"."""
        extra = f"&voir={voir}" if voir else ""
        return self._blocs(self.get_html("cdt?" + self._query(matiere, semaine, tout, extra)))

    # -- documents ----------------------------------------------------------

    def docs(self, matiere: str | None = None, rep: int | str | None = None) -> Dossier:
        if rep is not None:
            path = f"docs?rep={rep}"
        elif matiere:
            path = f"docs?{matiere}"
        else:
            path = "docs"
        soup = self.get_html(path)
        section = soup.select_one("section")

        chemin = [
            a.get_text(strip=True) for a in section.select("#parentsdoc .nom a")
        ] or [n.get_text(strip=True) for n in section.select("#parentsdoc .nom")]

        reps, docs, recents = [], [], []
        en_recents = False
        for el in section.find_all(["h3", "p"], recursive=False):
            if el.name == "h3":
                en_recents = "récent" in el.get_text().lower()
                continue
            classes = el.get("class", [])
            if "rep" in classes:
                a = el.select_one("a[href]")
                if not a:
                    continue
                q = urlparse(a["href"]).query
                cle = parse_qs(q).get("rep", [q])[0]
                cont = el.select_one(".repcontenu")
                reps.append(
                    Repertoire(
                        nom=a.select_one(".nom").get_text(strip=True),
                        cle=cle,
                        contenu=cont.get_text(strip=True).strip("()") if cont else "",
                        verrouille=bool(el.select_one(".icon-minilock")),
                    )
                )
            elif "doc" in classes:
                a = el.select_one("a[href]")
                donnees = el.select_one(".docdonnees")
                parts = [p.strip() for p in (donnees.get_text().strip("() ") if donnees else "").split(",")]
                parts += [""] * (3 - len(parts))
                d = Document(
                    doc_id=int(el.get("data-id") or _doc_id(a["href"]) or 0),
                    nom=a.select_one(".nom").get_text(strip=True),
                    type=parts[0],
                    date=parts[1],
                    taille=parts[2].replace("\xa0", " "),
                    url=self._url(a["href"]),
                )
                (recents if en_recents else docs).append(d)
        return Dossier(chemin=chemin, repertoires=reps, documents=docs, recents=recents)

    def download(self, doc_id: int | str, dest_dir: str = "downloads") -> str:
        """Télécharge un document (`download?id=...`) et renvoie le chemin local."""
        r = self.session.get(self._url("download"), params={"id": doc_id}, timeout=60, stream=True)
        r.raise_for_status()
        if "text/html" in r.headers.get("Content-Type", ""):
            raise CahierPrepaError(f"Document {doc_id} indisponible (accès refusé ou inexistant).")
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
        name = os.path.basename(unquote(m.group(1))) if m else f"document_{doc_id}"
        os.makedirs(dest_dir, exist_ok=True)
        path = os.path.join(dest_dir, name)
        with open(path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return path

    # -- nouveautés ---------------------------------------------------------

    def recents(self, type: str = "tout", matiere: str = "tout", recherche: str | None = None) -> list[Recent]:
        from urllib.parse import quote

        q = f"recherche={quote(recherche)}" if recherche else f"type={type}&matiere={matiere}"
        soup = self.get_html("recent?" + q)
        out = []
        for art in soup.select("article.recents"):
            a = art.select_one("h3 a")
            publi = art.select_one("p.publi")
            detail = art.select_one("div")
            out.append(
                Recent(
                    titre=a.get_text(strip=True) if a else art.h3.get_text(strip=True),
                    url=self._url(a["href"]) if a else "",
                    date=re.sub(r"^Publication le\s*", "", publi.get_text(strip=True)) if publi else "",
                    detail=detail.get_text(" ", strip=True) if detail else "",
                )
            )
        return out

    # -- agenda -------------------------------------------------------------

    def agenda(self, mois: str | None = None) -> list[Evenement]:
        """Événements du mois affiché. `mois` au format AAMM (ex. "2609")."""
        path = f"agenda?mois={mois}" if mois else "agenda"
        soup = self.get_html(path)

        # Mois affiché : déduit du lien « Plus tard » (mois suivant).
        suiv = soup.select_one("a.icon-suivant")
        m = re.search(r"mois=(\d{2})(\d{2})", suiv["href"]) if suiv else None
        if mois:
            annee, mm = 2000 + int(mois[:2]), int(mois[2:])
        elif m:
            annee, mm = 2000 + int(m.group(1)), int(m.group(2)) - 1
            if mm == 0:
                annee, mm = annee - 1, 12
        else:
            today = date.today()
            annee, mm = today.year, today.month

        def decale(y: int, mo: int, delta: int) -> tuple[int, int]:
            i = y * 12 + (mo - 1) + delta
            return i // 12, i % 12 + 1

        out: list[Evenement] = []
        semaines = soup.select("#calendrier > div")
        for i, sem in enumerate(semaines):
            table = sem.select_one("table.evenements")
            if not table:
                continue
            jours = []
            for th in table.select("thead th"):
                y, mo = (annee, mm)
                if "autremois" in th.get("class", []):
                    y, mo = decale(annee, mm, -1 if i == 0 else 1)
                jours.append(date(y, mo, int(th.get_text(strip=True))))
            for tr in table.select("tbody tr"):
                col = 0
                for td in tr.find_all("td", recursive=False):
                    span = int(td.get("colspan", 1))
                    for p in td.select("p.evnmt"):
                        t = next((int(c[5:]) for c in p.get("class", []) if re.fullmatch(r"evnmt\d+", c)), None)
                        eid = td.get("data-id")
                        out.append(
                            Evenement(
                                date=jours[col].isoformat(),
                                titre=_texte(p),
                                type=t,
                                evt_id=int(eid) if eid and eid.isdigit() else None,
                            )
                        )
                    col += span
        return out
