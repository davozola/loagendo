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
# Llevan la palabra pero no son un festival (25-10-2026, decisión de David): talleres «per a festes», exposiciones
# «Mostra…», mercados, conciertos «+ Concert» u «Orchestra», presentaciones, ciclos de visitas y semanas temáticas.
NOT_FESTIVAL = re.compile(r"orchestra|orquestra|presentacio|parlem de|recital|mostra de comerc|caps de setmana|setmana europea|setmana de l album|"
                          r"setmana de la ciencia|setmana del voluntariat|black week|\+ concert|"
                          r"^(?:taller|exposicio|mercat|concert|gran ball|mati|matinades|comissio|dates|cinema polivalent|bingo|jornades)\b")
# Título que es el nombre de un festival (ficha general suelta): «Mozilla Festival», «20a Mostra de Cinema Àrab…».
FESTIVAL_NAME = re.compile(r"\b(?:festival|fest|biennal|bienal|open house)\b|\bmostra\b.*\b(?:cinema|cine|films?|teatre|dansa|video|fotoperiodisme)\b|\bfesta major\b|\bfestes de\b")
FIESTA = re.compile(r"\bfesta major\b|\bfestes (?:de|del|majors)\b|\bfiesta mayor\b|\bfiestas de\b")
MIN_CHILDREN = 2   # 25-10-2026: desde 2 actividades (antes 3); con 1 si su ficha general existe
# Palabras que no distinguen un festival de otro al unir ficha general y actividades por su nombre propio.
GENERIC = {"festival", "festivals", "fest", "festa", "festes", "major", "edicio", "edicion", "edition", "de", "d", "del", "dels", "la", "el", "les", "els",
           "l", "i", "y", "bcn", "barcelona", "internacional", "international", "digital", "digitals", "arts", "art", "music", "musica", "musics", "the",
           "of", "a", "en", "al", "cine", "cinema", "documental", "musical", "arquitectura", "creacio", "contemporania", "contemporanea", "teatre", "teatro",
           "dansa", "per", "ciutat", "nova", "new", "any", "cicle", "mostra", "setmana", "week", "weekend", "semana", "biennal", "bienal", "catalunya", "s"}
# Palabra única demasiado común para unir sin más («Jazz», «Ciència»): solo vale si los dos nombres quedan iguales.
COMMON = {"jazz", "ciencia", "flamenc", "flamenco", "guitar", "guitarra", "blues", "gospel", "rock", "humor", "dones", "fotografia", "photo", "concurs", "simfonies"}


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
    return p if WORDS.search(fold(p)) and not NOT_FESTIVAL.search(fold(p)) else ""


def bracket(title):
    """«CLOSA SELECTS w/ MRAK - Halloween [Balla Festival]» → «Balla Festival»."""
    m = re.search(r"\[([^\]]*\b(?:festival|fest)\b[^\]]*)\]", str(title or ""), re.I)
    return m.group(1).strip() if m else ""


def core(text):
    """Nombre propio de un festival: sin edición, año ni palabras genéricas («25è Festival … "Escena Poblenou"» → {escena, poblenou})."""
    words = re.split(r"[\s'\-]+", fold(text))
    return {w for w in words if w and w not in GENERIC and not re.fullmatch(r"\d+(?:e|a|o|r|n|t|th|st|nd|rd)?|[xvil]+|20\d\d", w)}


def is_festival_name(title):
    """El título es el nombre de un festival o fiesta (ficha general), no una actividad ni un taller «per a festes»."""
    f = fold(title)
    return bool(FESTIVAL_NAME.search(f)) and not NOT_FESTIVAL.search(f) and not prefix(title) and not re.search(r":\s", str(title or "")) and bool(core(title))


def same_festival(a, b):
    """Dos nombres propios que son el mismo festival: uno contiene al otro; una sola palabra común no basta."""
    if not a or not b: return False
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    if not small <= big: return False
    if len(small) == 1 and small != big and (next(iter(small)) in COMMON or len(next(iter(small))) < 3): return False
    return True


def _overlap(a0, a1, b0, b1):
    return not (str(a1 or a0)[:10] < str(b0)[:10] or str(a0)[:10] > str(b1 or b0)[:10])


class Festivals:
    """Reconoce festivales y fiestas en las fichas vigentes del catálogo.

    ``records``: títulos o tuplas (título, inicio, fin). Con fechas, la ficha general suelta de un festival
    («Festival Escena Poblenou 2026») se une al grupo de sus actividades («25è Festival … "Escena Poblenou": …»)
    si los dos nombres propios coinciden y las fechas se solapan (25-10-2026)."""

    def __init__(self, records, config=None):
        self.config = load() if config is None else config
        self.programs = {}
        recs = [(r, "", "") if isinstance(r, str) else (tuple(r) + ("", ""))[:3] for r in records]
        counts, spans = {}, {}
        for t, a, b in recs:
            p = prefix(t) or bracket(t)
            if not p: continue
            k = _strip_edition(p)
            counts.setdefault(k, []).append(p)
            if a: lo, hi = spans.get(k, (a, b or a)); spans[k] = (min(lo, a), max(hi, b or a))
        names = [(t, a, b, core(t)) for t, a, b in recs if is_festival_name(t)]
        def has_umbrella(k):
            c = core(k); lo, hi = spans.get(k, ("", ""))
            return any(same_festival(c, n[3]) and (not lo or not n[1] or _overlap(n[1], n[2], lo, hi)) for n in names)
        self.auto = {k: max(v, key=len) for k, v in counts.items() if len(k) >= 4 and (len(v) >= MIN_CHILDREN or has_umbrella(k))}
        self.linked = {}
        for t, a, b, c in names:
            if _strip_edition(t) in self.auto: continue
            hits = [k for k in self.auto if same_festival(c, core(k)) and (not a or k not in spans or _overlap(a, b, *spans[k]))]
            if len(hits) == 1: self.linked[fold(t)] = hits[0]

    @staticmethod
    def _slug(key):
        return "auto-" + re.sub(r"[^a-z0-9]+", "-", key).strip("-")[:60]

    @staticmethod
    def _kind(name):
        return "fiesta" if FIESTA.search(fold(name)) else "festival"

    def _out(self, slug, name, umbrella):
        return {"slug": slug, "name": name, "umbrella": umbrella, "kind": self._kind(name)}

    def of(self, title, raw_festival=None, venue="", start="", end=""):
        """{'slug', 'name', 'umbrella', 'kind'} o None. kind: «festival» o «fiesta» (fiesta mayor)."""
        if isinstance(raw_festival, dict) and raw_festival.get("slug"):
            return self._out(raw_festival["slug"], raw_festival.get("name") or raw_festival["slug"], False)
        f = fold(title)
        p = prefix(title) or bracket(title)
        for c in self.config:
            if c["rx"].search(f):
                child = (bool(p) and bool(c["rx"].search(fold(p)))) or _activity_after(title, c["rx"])
                umbrella = not child and (len(_leftover(f, c["rx"])) <= 1 or bool(GENERIC_PLACE.match(fold(venue))))
                return self._out(c["slug"], c["nombre"], umbrella)
        if p:
            k = _strip_edition(p)
            if k in self.auto:
                return self._out(self._slug(k), _display(self.auto[k]), False)
        if f in self.linked:
            k = self.linked[f]
            return self._out(self._slug(k), _display(self.auto[k]), True)
        k = _strip_edition(title)
        if k in self.auto:
            return self._out(self._slug(k), _display(self.auto[k]), True)
        # Ficha general sin actividades: es festival si dura más de un día (o es fiesta mayor). Una fiesta o un
        # concierto de una noche con «Festival» en el nombre no lo es (decisión de David, 25-10-2026).
        # Un acto de un día («49è Correfoc de Festa Major», «Gran concert de Festa Major») es un acto, no la ficha general.
        if is_festival_name(title) and start and end and str(end)[:10] > str(start)[:10]:
            return self._out(self._slug(" ".join(sorted(core(title)))), _display(title), True)
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
        try: titles = [tuple(r) for r in conn.execute("SELECT title, substr(start_date,1,10), substr(COALESCE(NULLIF(end_date,''),start_date),1,10) FROM source_records WHERE end_date>=? AND eligibility<>'exclude'", (today,))]
        except Exception: titles = []
        obj = Festivals(titles)
        obj.programs = programs(conn, today)
        _CACHE.update(key=key, obj=obj)
    return _CACHE["obj"]


MANUAL_HOURS = ROOT / "config" / "horarios_festivales.json"


_MANUAL = {"key": None, "data": {}}


def manual_hours(path=MANUAL_HOURS):
    """Horas que David pone a mano a una ficha de festival (26-10-2026): {ficha: {día: {time, kind, source}}}.
    Están en config, así que ninguna actualización las sobrescribe; cada día es explícito (nada se extrapola)."""
    try: stamp = (str(path), Path(path).stat().st_mtime)
    except OSError: return {}
    if _MANUAL["key"] == stamp: return _MANUAL["data"]
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    out = {}
    for row in data.get("horarios", []):
        key, source = str(row.get("ficha") or "").strip(), str(row.get("fuente") or "").strip()
        kind = "primera" if "primera" in str(row.get("tipo") or "").lower() else "apertura"
        for day, time in (row.get("dias") or {}).items():
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(day)) and re.fullmatch(r"\d{1,2}:\d{2}", str(time)):
                out.setdefault(key, {})[day] = {"time": str(time).zfill(5), "kind": kind, "source": source}
    _MANUAL.update(key=stamp, data=out)
    return out


def programs(conn, today=None):
    """{festival: [{date, time, title, room, url}]}: actos de festivales con abono, que van en la ficha del festival
    en vez de tener ficha propia (raw.item.x_programa, 25-10-2026)."""
    import datetime as dt
    today = today or dt.date.today().isoformat()
    out = {}
    try:
        rows = conn.execute("""SELECT raw_json FROM source_records WHERE raw_json LIKE '%"x_programa": true%' AND end_date>=?""", (today,)).fetchall()
    except Exception:
        return out
    for (raw,) in rows:
        try: item = json.loads(raw).get("item") or {}
        except ValueError: continue
        slug = (item.get("x_festival") or {}).get("slug")
        start = str(item.get("startDate") or "")
        if not slug or not item.get("x_programa") or len(start) < 10: continue
        out.setdefault(slug, []).append({"date": start[:10], "time": start[11:16] if len(start) >= 16 else "", "title": " ".join(str(item.get("name") or "").split()),
                                         "room": str(item.get("x_room") or ""), "url": str(item.get("url") or "")})
    for v in out.values(): v.sort(key=lambda p: (p["date"], p["time"], p["title"]))
    return out
