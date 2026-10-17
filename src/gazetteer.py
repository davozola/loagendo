"""District and coordinates for records whose source does not say.

Only the municipal feeds (Open Data BCN, GuiaBCN, Diputació) label records with
a district. The Generalitat and the halls' own feeds give an address and often
coordinates but no district, so every concert at Heliogàbal or Sidecar fell
out of the "Gràcia" or "Ciutat Vella" filter. This module learns from what the
city already told us:

- a NAME index: normalised venue name → the district the municipal feeds give
  that venue (majority) and its coordinates (median), built from the archived
  records themselves;
- a POINT index: every municipal venue with coordinates and a district, so a
  record that only carries coordinates takes the district of its nearest
  labelled neighbours (5 nearest within 400 m, majority; ties go unresolved).

Nothing is guessed from prose; a record that matches neither stays without a
district, as before. config/venues.json may carry an explicit ``district`` for a
hall, which wins over both indexes. The result is cached per database state
(count of venue rows) so a listing pays for it once.
"""
from __future__ import annotations

import math
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from statistics import median

from src.venue_directory import normalise, site_for, _index as _directory

DISTRICT_SOURCES = ("opendatabcn_agenda", "guiabcn", "diba_bibliotecas", "diba_turismo")
NEAREST_K = 5
NEAREST_MAX_M = 400.0


def _distance_m(lat1, lon1, lat2, lon2):
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2)) * 111_320.0
    y = (lat2 - lat1) * 110_540.0
    return math.hypot(x, y)


class Gazetteer:
    def __init__(self, by_name, points):
        self.by_name = by_name      # normalised name -> {'district','lat','lon','n'}
        self.points = points        # [(lat, lon, district)]
        self._nearest_cache = {}

    def for_name(self, name):
        key = normalise(name)
        if not key: return None
        hit = self.by_name.get(key)
        if hit: return hit
        entry = site_for(name)
        if entry:
            for alias, e in _directory()[0].items():
                if e["slug"] == entry["slug"] and alias in self.by_name: return self.by_name[alias]
        return None

    def district_near(self, lat, lon):
        """Majority district among the nearest labelled venues; None when none is close or the vote ties."""
        key = (round(lat, 4), round(lon, 4))
        if key in self._nearest_cache: return self._nearest_cache[key]
        near = sorted(((_distance_m(lat, lon, plat, plon), d) for plat, plon, d in self.points), key=lambda t: t[0])[:NEAREST_K]
        near = [(dist, d) for dist, d in near if dist <= NEAREST_MAX_M]
        result = None
        if near:
            votes = Counter(d for _, d in near).most_common()
            if len(votes) == 1 or votes[0][1] > votes[1][1]: result = votes[0][0]
        self._nearest_cache[key] = result
        return result

    def resolve(self, venue_names, coordinates):
        """(district, coordinates, how) for a record; ``how`` names the evidence or is ''."""
        directory_district = next((v.get("district") for v in _directory_entries() if v.get("district") and any(site_for(n) and site_for(n)["slug"] == v["slug"] for n in venue_names or [])), None)
        if directory_district: return directory_district, coordinates or _directory_coords(venue_names), "directory"
        for name in venue_names or []:
            hit = self.for_name(name)
            if hit:
                coords = coordinates or ({"lat": hit["lat"], "lon": hit["lon"]} if hit.get("lat") is not None else None)
                return hit["district"], coords, "venue_name"
        if coordinates and coordinates.get("lat") is not None:
            d = self.district_near(float(coordinates["lat"]), float(coordinates["lon"]))
            if d: return d, coordinates, "nearest_venues"
        return None, coordinates, ""


@lru_cache(maxsize=1)
def _directory_entries(path=None):
    import json
    from src.venue_directory import VENUES_PATH
    try: return tuple(json.loads(VENUES_PATH.read_text(encoding="utf-8")).get("venues", []))
    except (OSError, ValueError): return ()


def _directory_coords(venue_names):
    for n in venue_names or []:
        entry = site_for(n)
        if not entry: continue
        for v in _directory_entries():
            if v["slug"] == entry["slug"] and v.get("lat") is not None and v.get("lon") is not None: return {"lat": v["lat"], "lon": v["lon"]}
    return None


def _build(conn: sqlite3.Connection):
    from mvp.catalog import DISTRICTS, district_of
    import json
    names = defaultdict(lambda: {"districts": Counter(), "lats": [], "lons": []})
    points = []
    rows = conn.execute("SELECT r.source, r.id, r.raw_json, v.venue, v.lat, v.lon FROM source_records r JOIN source_venues v ON v.source=r.source AND v.id=r.id WHERE r.source IN (%s)" % ",".join("?" * len(DISTRICT_SOURCES)), DISTRICT_SOURCES)
    for source, rid, raw_text, venue, lat, lon in rows:
        try: district = district_of(json.loads(raw_text), source)
        except ValueError: district = None
        if district not in DISTRICTS: continue
        key = normalise(venue)
        if key:
            entry = names[key]; entry["districts"][district] += 1
            if lat is not None and lon is not None: entry["lats"].append(float(lat)); entry["lons"].append(float(lon))
        if lat is not None and lon is not None: points.append((float(lat), float(lon), district))
    # Venues without a district label but with coordinates (Generalitat, halls, Songkick)
    # still contribute their coordinates to the name index, so a hall's feed
    # that gives no position inherits the position another source published.
    for venue, lat, lon in conn.execute("SELECT venue, lat, lon FROM source_venues WHERE lat IS NOT NULL AND lon IS NOT NULL AND source NOT IN (%s)" % ",".join("?" * len(DISTRICT_SOURCES)), DISTRICT_SOURCES):
        key = normalise(venue)
        if key and key not in names: names[key]["lats"].append(float(lat)); names[key]["lons"].append(float(lon))
    by_name = {}
    for key, entry in names.items():
        district = entry["districts"].most_common(1)[0][0] if entry["districts"] else None
        lat = median(entry["lats"]) if entry["lats"] else None; lon = median(entry["lons"]) if entry["lons"] else None
        if district: by_name[key] = {"district": district, "lat": lat, "lon": lon, "n": sum(entry["districts"].values())}
        elif lat is not None: by_name[key] = {"district": None, "lat": lat, "lon": lon, "n": 0}
    gaz = Gazetteer(by_name, points)
    # Second pass: a venue known only by coordinates takes the district of its neighbours.
    for key, entry in by_name.items():
        if entry["district"] is None and entry["lat"] is not None: entry["district"] = gaz.district_near(entry["lat"], entry["lon"])
    gaz.by_name = {k: v for k, v in by_name.items() if v["district"]}
    return gaz


_CACHE = {"stamp": None, "gazetteer": None}


def gazetteer(conn: sqlite3.Connection):
    stamp = conn.execute("SELECT COUNT(*), MAX(rowid) FROM source_venues").fetchone()
    if _CACHE["stamp"] != stamp:
        _CACHE["gazetteer"] = _build(conn); _CACHE["stamp"] = stamp
    return _CACHE["gazetteer"]


def invalidate():
    _CACHE["stamp"] = None; _CACHE["gazetteer"] = None
