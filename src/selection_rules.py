"""Salas que nunca entran en la «Selección Ontoca» (2-11-2026, David: «City Hall nunca puede ser Selección Ontoca»).

La lista está en config/seleccion_excluidas.json (nombres de sala y fuentes). Una ficha queda fuera si es de una de esas
fuentes o si alguna de sus salas lleva ese nombre (comparación sin acentos ni mayúsculas, por palabra completa: «Sala City
Hall» sí, «City Hallway» no). Se aplica en los candidatos de la IA (src/ai_select.py), en la selección por reglas
(catalog.query_events con featured) y al publicar (src/publish_static.py), también sobre elecciones ya guardadas.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'config' / 'seleccion_excluidas.json'
_CACHE = {}


def _fold(s):
    s = unicodedata.normalize('NFKD', str(s or '')).lower()
    return ''.join(c for c in s if not unicodedata.combining(c))


def rules(path=None):
    p = Path(path or PATH)
    key = str(p)
    if key not in _CACHE:
        try: data = json.loads(p.read_text(encoding='utf-8'))
        except (OSError, ValueError): data = {}
        names = [_fold(n).strip() for n in data.get('salas') or [] if str(n).strip()]
        _CACHE[key] = (set(data.get('fuentes') or []), [re.compile(r'(?<![a-z0-9])' + re.escape(n) + r'(?![a-z0-9])') for n in names])
    return _CACHE[key]


def excluded(event, path=None):
    """True si la ficha no puede salir en la Selección. Sin ficha (clave desconocida), False."""
    if not event: return False
    sources, names = rules(path)
    if event.get('source') in sources: return True
    venues = list(event.get('venue_names') or []) + [v.get('name', '') if isinstance(v, dict) else str(v) for v in event.get('venues') or []]
    return any(rx.search(_fold(v)) for v in venues for rx in names)
