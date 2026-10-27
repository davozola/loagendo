"""Editorial weight of a venue in the weekly selection (config/venue_prestige.json).

A venue name is matched against the patterns of each tier as whole words on
the normalised name (src.venue_directory.normalise). When several patterns
match, a pattern that matches at the start of the name wins over one found
inside it, and the longest pattern wins among those: "Biblioteca de Catalunya"
is the national library (its own pattern), not the neighbourhood library
network, and "Centre Cívic Sagrada Família" is a civic centre, not the
basilica. A name matching nothing scores 0.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from src.venue_directory import normalise, site_for

PRESTIGE_PATH = Path(__file__).resolve().parents[1] / "config" / "venue_prestige.json"


@lru_cache(maxsize=1)
def _patterns(path=str(PRESTIGE_PATH)):
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return ()
    out = []
    for tier in data.get("tiers", []):
        for pattern in tier.get("patterns", []):
            key = pattern if str(pattern).startswith("slug:") else normalise(pattern)
            if key: out.append((key, int(tier.get("points", 0)), str(tier.get("label", ""))))
    return tuple(out)


@lru_cache(maxsize=4096)
def venue_points(name):
    """(points, tier label) for one venue name; (0, '') when unknown."""
    text = normalise(name)
    if not text: return 0, ""
    slug = (site_for(name) or {}).get("slug", "")
    best = None
    for key, points, label in _patterns():
        if key.startswith("slug:"):
            if slug and key[5:] == slug: rank = (True, 999)  # an exact directory identification beats any name pattern
            else: continue
        else:
            match = re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", text)
            if not match: continue
            rank = (match.start() == 0, len(key))
        if best is None or rank > best[0]: best = (rank, points, label)
    return (best[1], best[2]) if best else (0, "")


def prestige(names):
    """Best (points, label) across a record's venue names."""
    best = (0, "")
    for name in names or []:
        candidate = venue_points(name)
        if candidate[0] > best[0]: best = candidate
    return best


@lru_cache(maxsize=1)
def _expo_patterns(path=str(PRESTIGE_PATH)):
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return ()
    return tuple(k for k in (normalise(p) for p in (data.get("exposiciones") or {}).get("patterns", [])) if k)


def art_space(names):
    """¿Es un espacio de arte de referencia para destacar exposiciones (Selección Ontoca en Expos)? Lista aparte
    de los puntos de la portada (config/venue_prestige.json, «exposiciones»; 27-10-2026): museos, centros de arte y
    fotografía y galerías elegidas una a una. Se compara como el resto: palabras enteras del nombre normalizado."""
    pats = _expo_patterns()
    for name in names or []:
        text = normalise(name)
        if text and any(re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text) for k in pats): return True
    return False
