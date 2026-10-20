"""Sala dentro de un recinto: «Sala 1 Pau Casals» → «L'Auditori de Barcelona · Sala 1 Pau Casals» (20-10-2026).

Muchas fuentes dan solo la sala («Sala 1 Pau Casals», «Sala Petita», «La 2») y en la tarjeta no se
sabe dónde es. El nombre del recinto no se inventa: sale de otras fichas EN LA MISMA DIRECCIÓN que
lo escriben completo («L'Auditori de Barcelona - Sala 1 Pau Casals», «Teatre Nacional de Catalunya
- Sala Petita»):
  1. la misma sala con prefijo en otra ficha → ese prefijo;
  2. una sala genérica («Espai 5», «Sala d'Exposicions Temporals») en una dirección donde todas las
     fichas con prefijo comparten el mismo recinto → ese recinto;
  3. una sala genérica («La 2») donde la dirección tiene un nombre propio claramente dominante
     («Sala Apolo») → ese nombre.
Si no hay evidencia, el nombre queda como lo da la fuente.
"""
from __future__ import annotations

import collections
import re
import sqlite3
import unicodedata

SEP = re.compile(r"\s+[-–—]\s+")
GENERIC = re.compile(r"^(?:sala|espai|aula|auditori|la|el|petit|teatre)\b\s*(?:\(?\d+\)?|\[\d+\]|[ivx]+\b|petita|gran|tallers|polivalent|"
                     r"d'exposicions|d exposicions|de exposiciones|d'actes|d actes|de actos|cinc|de teclats|principal|annex)?(?:\b.*)?$")
# Nombres que ya son un recinto por sí mismos: no se les antepone otro («CCCB», «Museu Egipci»).
STANDALONE = re.compile(r"^(?:museu|museo|fundacio|fundacion|cccb|macba|tnc|l'auditori|l auditori|biblioteca|pavello|teatre nacional|"
                        r"centre de cultura|palau de|palau robert|gran teatre|mercat de les flors)\b")
STREET_PREFIX = re.compile(r"^(?:c|cl|carrer|calle|pl|placa|plaza|pza|av|avda|avinguda|avenida|pg|passeig|paseo|rbla|rambla|ptge|passatge|via|ronda|trav|travessera|gran via)\b\.?\s*(?:de |del |d'|de la |dels |de les |de l')?")


def _fold(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower().replace('’', "'")
    return ' '.join(re.sub(r"[^a-z0-9'()\[\] ]+", ' ', text).split())


def address_key(address):
    """«C Lepant 150, 08013 BARCELONA» y «Carrer de Lepant, 150, 08013 Barcelona» → ('lepant', '150')."""
    a = _fold(str(address or '').split(',')[0] + ' ' + ' '.join(str(address or '').split(',')[1:2]))
    a = STREET_PREFIX.sub('', a)
    m = re.match(r"([a-z' ]+?)\s+(\d+)", a)
    return (m.group(1).strip(), m.group(2)) if m else None


def is_generic(name):
    f = _fold(name)
    return bool(f) and (f in ('auditori', 'la 2', 'la (2)', 'la [2]', 'la cinc', 'sala petita', 'sala gran') or
                        (len(f.split()) <= 4 and bool(re.match(r"^(?:sala|espai|aula)\s+(?:\d+|d'exposicions|d exposicions|petita|gran|tallers|polivalent|d'actes|de teclats)\b", f))))


class Rooms:
    def __init__(self, rows):
        self.suffix = {}                                  # (dirección, sala) → recinto
        prefixes = collections.defaultdict(collections.Counter)
        names = collections.defaultdict(collections.Counter)
        for venue, address in rows:
            key = address_key(address)
            if not key or not venue: continue
            parts = SEP.split(venue.strip(), maxsplit=1)
            if len(parts) == 2 and parts[0] and parts[1]:
                self.suffix.setdefault((key, _fold(parts[1])), parts[0].strip())
                prefixes[key][parts[0].strip()] += 1
            elif not is_generic(venue):
                names[key][venue.strip()] += 1
        self.prefix = {k: c.most_common(1)[0][0] for k, c in prefixes.items() if len(c) == 1}
        self.dominant = {}
        for k, c in names.items():
            (top, n), total = c.most_common(1)[0], sum(c.values())
            if n >= 3 and n / total >= 0.6: self.dominant[k] = top

    def full_name(self, name, address):
        name = (name or '').strip()
        if not name or SEP.search(name) or '·' in name or STANDALONE.match(_fold(name)): return name
        key = address_key(address)
        if not key: return name
        building = self.suffix.get((key, _fold(name)))
        if not building and is_generic(name): building = self.prefix.get(key) or self.dominant.get(key)
        if not building or _fold(building) in _fold(name) or _fold(name) in _fold(building): return name
        return f'{building} · {name}'


_CACHE = {'stamp': None, 'rooms': None}


def rooms(conn):
    try:
        stamp = conn.execute('SELECT COUNT(*), MAX(rowid) FROM source_venues').fetchone()
        if stamp != _CACHE['stamp']:
            _CACHE.update(stamp=stamp, rooms=Rooms(conn.execute("SELECT venue, address FROM source_venues WHERE COALESCE(address,'')<>''").fetchall()))
    except sqlite3.DatabaseError:
        return Rooms([])
    return _CACHE['rooms']
