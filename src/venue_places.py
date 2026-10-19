"""Coordenadas y dirección de un lugar a partir de otras fuentes que lo publican.

Directorios como conciertos.club o los listados de centres cívics dan solo el
nombre del lugar («Basílica de la Mercè», «Real Círculo Artístico de Barcelona»).
Otras fuentes nuestras publican ese mismo lugar con su dirección y coordenadas.
Si varias fichas con el mismo nombre de lugar coinciden en el sitio (todas a
menos de 300 m), se toma ese punto. Nada se geocodifica ni se adivina: un nombre
que nadie publica con coordenadas, o que aparece en sitios distintos, se queda sin
mapa."""
from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from statistics import median

GENERIC = {"barcelona", "diversos", "diferents", "varios", "varis", "xarxa", "online", "en linia", "secret venue", "per determinar"}


def key(name):
    import html
    text = unicodedata.normalize("NFKD", re.sub(r"['’‘`´–]", " ", html.unescape(str(name or "")))).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\b(la|el|els|les|los|las|l|de|del|d|i|y|the)\b", " ", text)
    return " ".join(text.split())


# Variantes del mismo lugar entre fuentes: castellano/catalán y abreviaturas.
WORDS = {"museo": "museu", "europeo": "europeu", "arte": "art", "moderno": "modern", "contemporaneo": "contemporani",
         "iglesia": "esglesia", "parroquia": "parroquia", "centro": "centre", "civico": "civic", "cultural": "cultural",
         "biblioteca": "biblioteca", "teatro": "teatre", "auditorio": "auditori", "plaza": "placa", "calle": "carrer",
         "jardines": "jardins", "palacio": "palau", "casa": "casa", "sala": "sala", "fundacion": "fundacio"}


def variants(name):
    """Claves con las que se reconoce un lugar: el nombre, sin paréntesis, la sigla entre
    paréntesis («MEAM»), cada parte de «MACBA - Museu d'Art…», «CC» = centre cívic y
    castellano → catalán."""
    raw = str(name or "")
    parts = [raw, re.sub(r"\([^)]*\)", " ", raw)] + re.split(r"\s+-\s+|\*", raw)
    parts += [m for m in re.findall(r"\(([^)]{4,})\)", raw)]
    out = []
    for part in parts:
        k = key(part)
        k = re.sub(r"^cc\b", "centre civic", k)
        k2 = " ".join(WORDS.get(w, w) for w in k.split())
        for x in (k, k2):
            if len(x) >= 4 and x not in GENERIC and x not in out: out.append(x)
    return out


def _km(a, b):
    dy = (a[0] - b[0]) * 111.0; dx = (a[1] - b[1]) * 111.0 * math.cos(math.radians(a[0]))
    return math.hypot(dx, dy)


def known_places(conn):
    """{nombre normalizado: (dirección, lat, lon, nº de fichas)} de lugares con un sitio claro."""
    try:
        rows = conn.execute("SELECT venue, address, lat, lon FROM source_venues WHERE lat IS NOT NULL AND lon IS NOT NULL AND venue<>''").fetchall()
    except sqlite3.DatabaseError:
        return {}
    groups = {}
    for venue, address, lat, lon in rows:
        if any(w in key(venue).split() for w in ("diversos", "diferents", "varios", "xarxa")): continue
        try: point = (float(lat), float(lon))
        except (TypeError, ValueError): continue
        if not (41.2 < point[0] < 41.6 and 1.9 < point[1] < 2.4): continue   # solo el área de Barcelona
        for k in variants(venue):
            groups.setdefault(k, []).append((point, address or ""))
    out = {}
    for k, items in groups.items():
        centre = (median(p[0] for p, _ in items), median(p[1] for p, _ in items))
        near = [(p, a) for p, a in items if _km(p, centre) <= 0.3]
        if len(near) < max(1, 0.8 * len(items)): continue   # el nombre aparece en sitios distintos: no se usa
        addresses = [a for _, a in near if a and len(a) > 8]
        address = max(set(addresses), key=addresses.count) if addresses else ""
        out[k] = (address, round(centre[0], 6), round(centre[1], 6), len(near))
    for k, value in curated().items():   # lo comprobado a mano manda
        if value[0] == "same_as":
            target = next((out[x] for x in variants(value[1]) if x in out), None)
            if target: out[k] = target
        else: out[k] = value
    return out


def curated(path=None):
    """config/places.json: lugares comprobados a mano (con su evidencia), por cada nombre y alias."""
    import json
    from pathlib import Path
    path = Path(path) if path else Path(__file__).resolve().parents[1] / "config" / "places.json"
    try: data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    out = {}
    for p in data.get("places", []):
        if p.get("same_as"):
            for name in p.get("aliases") or []:
                for k in variants(name): out[k] = ("same_as", p["same_as"])
            continue
        for name in [p["name"]] + list(p.get("aliases") or []):
            for k in variants(name): out[k] = (p.get("address", ""), float(p["lat"]), float(p["lon"]), 0)
    return out


def lookup(places, name):
    found = next((places[k] for k in variants(name) if k in places), None)
    if found: return found
    # «La Virreina» → «La Virreina Centre de la Imatge»: el único lugar cuyo nombre empieza así.
    for k in variants(name):
        if len(k) < 6: continue
        hits = [v for key2, v in places.items() if key2.startswith(k + " ") and v and v[0] != "same_as"]
        if hits and all(_km(h[1:3], hits[0][1:3]) <= 0.3 for h in hits): return hits[0]
    return None


_CACHE = {"stamp": None, "places": {}}


def cached_places(conn):
    """known_places, recalculado solo cuando cambia source_venues (para las fichas sueltas)."""
    try: stamp = conn.execute("SELECT COUNT(*), MAX(rowid) FROM source_venues").fetchone()
    except sqlite3.DatabaseError: return {}
    if stamp != _CACHE["stamp"]: _CACHE.update(stamp=stamp, places=known_places(conn))
    return _CACHE["places"]
