"""Descripciones breves con IA, en castellano y catalán (20-10-2026).

Una o dos frases (≤ 240 caracteres) a partir SOLO de los datos de la ficha. Comprobación automática
antes de aceptarla:
  · todo número y todo nombre propio de la frase tiene que estar en los datos de entrada;
  · sin adjetivos promocionales ni llamadas a la acción;
  · longitud acotada y las dos lenguas presentes.
Lo que no pasa se guarda como rechazado (con el motivo) y no se muestra. El texto original de la
fuente no se toca nunca: la web enseña la descripción breve encima, marcada como automática, y el
original debajo. Se publica solo cuando ``config/ia.json`` tiene ``descripciones_publicas: true``
(tras revisar la muestra de ``scripts/muestra_descripciones.py``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.ai_extract import fold

ROOT = Path(__file__).resolve().parents[1]
MAX_CHARS = 240
MIN_TEXT = 80

PROMO = re.compile(r"\b(?:imprescindible|increible|espectacular|maravillos[oa]|meravellos[ao]?|inolvidable|inoblidable|"
                   r"fascinant[e]?|apasionante|apassionant|imperdible|no te lo pierdas|no t'ho perdis|no et perdis|no os lo perdais|unmissable|"
                   r"genial|extraordinari[oa]?|brillant[e]?|el mejor|la millor|el millor|la mejor|ven a|vine a|reserva ya)\b")
# «Fantástico» es promoción («un espectáculo fantástico») salvo como género o tipo, detrás de su
# nombre: «criaturas fantásticas», «literatura fantàstica», «seres fantásticos» (20-10-2026).
FANTASTIC = re.compile(r"\bfantastic[oa]?s?\b")
FANTASTIC_GENRE = re.compile(r"\b(?:criatur\w*|ser|sers|seres|essers?|mon|mons|mundos?|literatur\w*|personatg\w*|personaj\w*|anim\w*|bestiari\w*|"
                             r"univers\w*|genere|genero|cinema|cine|relat\w*|cont\w*|cuent\w*|novel\w*|imaginari\w*|fauna|realisme|realismo|ficcio\w*|ficcion\w*)\s+fantastic")
# Nombres que el castellano traduce del catalán de la fuente (o al revés): no son datos nuevos.
EQUIV = {'navidad': 'nadal', 'ayuntamiento': 'ajuntament', 'mujeres': 'dones', 'ano': 'any', 'anos': 'anys', 'nueva': 'nova', 'nuevo': 'nou',
         'media': 'mitjana', 'estado': 'estat', 'chaikovski': 'txaikovski', 'chaikovsky': 'txaikovski', 'espana': 'espanya', 'cataluna': 'catalunya'}
STOP_CAPS = {'el', 'la', 'els', 'les', 'los', 'las', 'un', 'una', 'en', 'a', 'de', 'del', 'con', 'amb', 'para', 'per', 'y', 'i', 'este', 'esta', 'aquest', 'aquesta',
             'exposicion', 'exposicio', 'concierto', 'concert', 'taller', 'espectaculo', 'espectacle', 'proyeccion', 'projeccio', 'charla', 'xerrada', 'visita',
             'fiesta', 'festa', 'barcelona', 'ciclo', 'cicle', 'festival', 'sesion', 'sessio', 'teatro', 'teatre', 'danza', 'dansa', 'cine', 'cinema', 'musica',
             'actividad', 'activitat', 'propuesta', 'proposta', 'obra', 'presentacion', 'presentacio', 'conferencia', 'muestra', 'mostra', 'ruta', 'itinerario', 'itinerari'}

SYSTEM = """Escribes descripciones breves para fichas de una agenda cultural de Barcelona (Brollant), en castellano (es) y en catalán (ca).
Cada descripción: una o dos frases, como máximo 240 caracteres, que digan qué es la actividad y lo esencial para decidir si ir (de qué trata, quién participa, para quién es).
Usa SOLO la información de los datos recibidos. Prohibido: inventar o deducir datos; añadir fechas, horas o precios (ya se muestran aparte); adjetivos promocionales u opiniones ("imprescindible", "increíble", "único", "espectacular"…); llamadas a la acción ("no te lo pierdas"); repetir el título literalmente al principio.
Mantén los nombres propios tal como aparecen en los datos. Si los datos no dan para una descripción útil, devuelve es y ca vacíos.
Se comprueba automáticamente que cada nombre y número de tu texto esté en los datos.
Responde con la herramienta describir, una entrada por ficha (n)."""

TOOL = {'name': 'describir', 'description': 'Descripción breve de cada ficha en castellano y catalán.',
        'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'es', 'ca'],
            'properties': {'n': {'type': 'integer'}, 'es': {'type': 'string'}, 'ca': {'type': 'string'}}}}}}}


def payload(ev):
    return {'titulo': (ev.get('title') or '')[:200], 'categoria': ev.get('category') or '', 'sala': ((ev.get('venue_names') or [''])[0] or '')[:100],
            'barrio': ev.get('district') or '', 'artistas': (ev.get('lineup') or [])[:8], 'texto': (ev.get('source_text') or '')[:1500]}


def needs(ev):
    return len((ev.get('source_text') or '').strip()) >= MIN_TEXT


def _proper_nouns(sentence_text):
    """Palabras con mayúscula que no abren frase (posibles nombres propios), plegadas."""
    out = set()
    for sentence in re.split(r'(?<=[.!?…])\s+', sentence_text):
        words = re.findall(r"[\wÀ-ÿ'’·-]+", sentence)
        for i, w in enumerate(words):
            if i == 0 or not w[:1].isupper() or len(w) < 3: continue
            f = fold(w).strip("'’-")
            if f and f not in STOP_CAPS: out.add(f)
    return out


def _cognate(word, words):
    """Misma palabra en la otra lengua (orquesta/orquestra, sinfonía/simfonia, cívico/cívic, fundación/fundació)."""
    from difflib import SequenceMatcher
    return len(word) >= 4 and any(w[:2] == word[:2] and SequenceMatcher(None, w, word).ratio() >= 0.72 for w in words if abs(len(w) - len(word)) <= 3)


def check(text, source_payload):
    """Lista de problemas (vacía = aceptable)."""
    problems = []
    if not text: return ['vacía']
    if len(text) > MAX_CHARS + 60: problems.append(f'larga ({len(text)} caracteres)')
    f = fold(text); src = fold(json.dumps(source_payload, ensure_ascii=False))
    m = PROMO.search(f)
    if m: problems.append(f'promocional: «{m.group(0)}»')
    elif FANTASTIC.search(f) and len(FANTASTIC.findall(f)) > len(FANTASTIC_GENRE.findall(f)): problems.append('promocional: «fantastic»')
    for n in set(re.findall(r'\d+', f)):
        if not re.search(rf'(?<!\d){n}(?!\d)', src): problems.append(f'número que no está en los datos: {n}')
    words = set(re.findall(r"[a-z0-9']+", src))
    for word in _proper_nouns(text):
        if word in src or EQUIV.get(word, '\0') in src or _cognate(word, words): continue
        problems.append(f'nombre que no está en los datos: {word}')
    return problems


def parse(row, source_payload):
    es, ca = (row.get('es') or '').strip(), (row.get('ca') or '').strip()
    if not es and not ca: return json.dumps({'es': '', 'ca': '', 'ok': False, 'problems': ['sin datos suficientes']}, ensure_ascii=False), 0.0, 'sin datos suficientes'
    problems = [f'es: {p}' for p in check(es, source_payload)] + [f'ca: {p}' for p in check(ca, source_payload)]
    ok = not problems
    return json.dumps({'es': es, 'ca': ca, 'ok': ok, 'problems': problems}, ensure_ascii=False), 1.0 if ok else 0.0, '; '.join(problems)[:300]


def public_enabled():
    try: return bool(json.loads((ROOT / 'config' / 'ia.json').read_text()).get('descripciones_publicas'))
    except (OSError, ValueError): return False
