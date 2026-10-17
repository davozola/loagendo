"""Directory of venues (config/venues.json) used to point a record at the
venue's own website.

A concert discovered through a third-party listing is published with a link
to the hall that hosts it, never to the listing. The mapping from a venue
name as a source spells it ("Razzmatazz 2", "La [2] de Apolo") to the entry
in config/venues.json goes through normalised names and explicit aliases.
Nothing is guessed: a venue missing from the directory gets no link.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

VENUES_PATH = Path(__file__).resolve().parents[1] / "config" / "venues.json"


def normalise(name):
    text = unicodedata.normalize("NFKD", str(name or "").replace("’", "'").replace("‘", "'")).encode("ascii", "ignore").decode().lower()  # curly apostrophes would otherwise vanish ("L’Auditori" → "lauditori")
    text = re.sub(r"[\[\]().,'’·/-]", " ", text)
    text = re.sub(r"\b(sala|la|el|els|les|the|de|del|d|club|teatre|teatro|barcelona|bcn)\b", " ", text)
    return " ".join(text.split())


@lru_cache(maxsize=1)
def _index(path=str(VENUES_PATH)):
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}, {}
    by_name, by_slug = {}, {}
    for venue in data.get("venues", []):
        if venue.get("type") in ("ticketing", "aggregator") or not venue.get("url"): continue
        site = venue.get("site") or "https://" + venue["url"].split("/", 3)[2] + "/"
        entry = {"slug": venue["slug"], "name": venue["name"], "url": site, "type": venue.get("type", "")}
        by_slug[venue["slug"]] = entry
        for alias in [venue["name"]] + list(venue.get("aliases") or []):
            key = normalise(alias)
            if key: by_name.setdefault(key, entry)
    return by_name, by_slug


@lru_cache(maxsize=4096)
def site_for(venue_name):
    """The directory entry for a venue name, or None. Exact normalised match
    first; then a match where the name starts with the directory name (so
    "Razzmatazz 3" finds Razzmatazz) when that prefix is at least 5 letters.
    A name that merely ends with a directory name is not a match: the Reial
    Acadèmia de Belles Arts de Sant Jordi is not the Sant Jordi Club."""
    by_name, _ = _index()
    key = normalise(venue_name)
    if not key: return None
    if key in by_name: return by_name[key]
    for alias, entry in by_name.items():
        if len(alias) >= 5 and key.startswith(alias + " "): return entry
    return None


@lru_cache(maxsize=None)
def venue_type(slug):
    """'music', 'theatre', 'ticketing', 'aggregator'… for a venue_<slug> source."""
    try: data = json.loads(VENUES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return ""
    return next((v.get("type", "") for v in data.get("venues", []) if v.get("slug") == slug), "")
