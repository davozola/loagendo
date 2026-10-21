"""Festivales y eventos paraguas (21-10-2026).

Un festival (48h Open House, el Festival de Jazz, MIRA, Sâlmon, una fiesta mayor…) tiene una ficha
paraguas y muchas actividades con ficha propia. Aquí se reconoce a qué festival pertenece cada ficha:
  · los de config/festivals.json, por un patrón en el título de cualquier fuente;
  · el resto, por el prefijo que repiten sus títulos en la agenda municipal
    («58è Festival Internacional de Jazz de Barcelona: Concert …», «"Festa Major de la Sagrera": …»),
    si lleva una palabra de festival y se repite en al menos tres fichas vigentes;
  · las fichas leídas del programa oficial de un festival lo dicen en sus datos (raw.item.x_festival).
Paraguas = la ficha del festival entero (sin «Prefijo: actividad» en el título). En la web, las
actividades del mismo festival se agrupan en la lista y cada ficha dice de qué festival forma parte.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "festivals.json"
WORDS = re.compile(r"\b(?:festival|fest|festa major|festes|biennal|bienal|mostra|open house|setmana|nit de|nit dels|gallery weekend|marato|maratón)\b")
MIN_CHILDREN = 3


def fold(text):
    t = unicodedata.normalize("NFKD", str(text or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9'\- ]+", " ", t).split())


def _strip_edition(text):
    t = fold(text)
    t = re.sub(r"^(?:\d+\s*(?:e|a|o|r|n|t)?|[xvil]+)\s+(?:edicio\s+(?:de\s+)?|edicion\s+(?:de\s+)?)?", "", t)
    t = re.sub(r"\b20\d\d\b", "", t)
    return " ".join(t.replace("'", " ").split())


def load(path=CONFIG):
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError): return []
    out = []
    for f in data.get("festivales", []):
        try: out.append({**f, "rx": re.compile(f["patron"])})
        except (re.error, KeyError): pass
    return out


def prefix(title):
    """«58è Festival Internacional de Jazz de Barcelona: Concert "X"» → «58è Festival Internacional de Jazz de Barcelona»."""
    t = str(title or "").strip().strip("'\"«»“”")
    m = re.match(r"^(.{6,90}?)\s*[\"'»”]?\s*:\s+\S", t)
    if not m: return ""
    p = m.group(1).strip(" '\"«»“”")
    return p if WORDS.search(fold(p)) else ""


class Festivals:
    """Reconoce festivales en un conjunto de títulos (los vigentes del catálogo)."""

    def __init__(self, titles, config=None):
        self.config = load() if config is None else config
        counts = {}
        for t in titles:
            p = prefix(t)
            if p: counts.setdefault(_strip_edition(p), []).append(p)
        self.auto = {k: max(v, key=len) for k, v in counts.items() if len(v) >= MIN_CHILDREN and len(k) >= 6}

    def of(self, title, raw_festival=None, venue=""):
        """{'slug', 'name', 'umbrella'} o None."""
        if isinstance(raw_festival, dict) and raw_festival.get("slug"):
            return {"slug": raw_festival["slug"], "name": raw_festival.get("name") or raw_festival["slug"], "umbrella": False}
        f = fold(title)
        p = prefix(title)
        for c in self.config:
            if c["rx"].search(f):
                child = (bool(p) and bool(c["rx"].search(fold(p)))) or _activity_after(title, c["rx"])
                umbrella = not child and (len(_leftover(f, c["rx"])) <= 1 or bool(GENERIC_PLACE.match(fold(venue))))
                return {"slug": c["slug"], "name": c["nombre"], "umbrella": umbrella}
        if p:
            k = _strip_edition(p)
            if k in self.auto:
                return {"slug": "auto-" + re.sub(r"[^a-z0-9]+", "-", k).strip("-")[:60], "name": _display(self.auto[k]), "umbrella": False}
        k = _strip_edition(title)
        if k in self.auto:
            return {"slug": "auto-" + re.sub(r"[^a-z0-9]+", "-", k).strip("-")[:60], "name": _display(self.auto[k]), "umbrella": True}
        return None


def _activity_after(title, rx):
    """«Festival d'Arquitectura "48h Open House BCN": Visita al …» es una actividad, no el festival."""
    return bool(re.search(r":\s+\S|\s[|–]\s", str(title or "")))


def _display(p):
    return " ".join(re.sub(r"[\"«»“”]", "", str(p)).split()).strip(" '")


GENERIC_PLACE = re.compile(r"^(?:diversos|diverses|diferents|varios|varias|distints|tota la ciutat|barcelona)\b")
FILLER = {"festival", "fest", "festa", "festes", "major", "edicio", "edicion", "de", "d", "del", "la", "el", "les", "els", "i", "y", "bcn",
          "barcelona", "internacional", "digital", "arts", "music", "musica", "the", "of", "a", "en", "cine", "cinema", "documental",
          "musical", "arquitectura", "vives", "contemporania", "creacio", "teatre", "dansa", "jazz", "per", "ciutat"}


def _leftover(folded, rx):
    """Lo que dice el título además del nombre del festival («Visita a la Casa Bloc»)."""
    rest = rx.sub(" ", folded)
    rest = re.sub(r"\b(?:\d+\s*(?:e|a|o|r|n|t)?|[xvil]+|20\d\d)\b", " ", rest)
    return [w for w in re.split(r"[\s'\-]+", rest) if w and w not in FILLER]


_CACHE = {"key": None, "obj": None}


def for_conn(conn):
    """Festivals del catálogo vigente (se recalcula si cambian las fichas)."""
    import datetime as dt
    try: key = conn.execute("SELECT COUNT(*), MAX(rowid) FROM source_records").fetchone()
    except Exception: key = None
    if _CACHE["key"] != key or _CACHE["obj"] is None:
        today = dt.date.today().isoformat()
        try: titles = [t for (t,) in conn.execute("SELECT title FROM source_records WHERE end_date>=? AND eligibility<>'exclude'", (today,))]
        except Exception: titles = []
        _CACHE.update(key=key, obj=Festivals(titles))
    return _CACHE["obj"]
