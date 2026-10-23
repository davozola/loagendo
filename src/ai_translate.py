"""Traducción automática de descripciones al inglés · MUESTRA (23-10-2026).

Solo para evaluar calidad y coste antes de decidir nada: no escribe en la base ni publica.
Reglas (las de siempre con la IA: evaluación y trazabilidad):
  · se traduce la descripción de la fuente, no el título (nombres de obras, artistas y salas se quedan como están);
  · fiel al original: sin añadir, quitar ni resumir; sin adjetivos nuevos;
  · comprobación automática: los números, enlaces y nombres propios del original tienen que seguir en
    la traducción, y la longitud tiene que ser comparable. Lo que no pasa se marca como rechazado.
Cada resultado guarda modelo, versión del prompt y huella del texto original.
"""
from __future__ import annotations

import hashlib
import json
import re

from src.ai_extract import fold

PROMPT_VERSION = 1
MIN_TEXT = 80
MAX_TEXT = 2500

SYSTEM = """You translate event descriptions from a Barcelona cultural listings site (Ontoca) into English.
The source text is usually Catalan, sometimes Spanish. Translate it faithfully and completely:
- Do not add, remove, summarise or explain anything. No new adjectives, opinions or calls to action.
- Keep proper names exactly as written: people, groups, venues, works, festivals, organisations, streets, neighbourhoods.
  Titles of works stay in their original language (you may keep quotation marks as in the source).
- Keep every number, date, time, price, age and URL exactly as in the source.
- Plain, natural British English. Keep paragraph breaks.
- If the text is already in English, return it unchanged.
Also return the language of the source text (ca, es, en or other).
Answer with the tool traducir, one entry per item (n)."""

TOOL = {'name': 'traducir', 'description': 'English translation of each description.',
        'input_schema': {'type': 'object', 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'source_lang', 'en'],
            'properties': {'n': {'type': 'integer'}, 'source_lang': {'type': 'string'}, 'en': {'type': 'string'}}}}}}}

NUM = re.compile(r'\d+(?:[.,:]\d+)*')
URL = re.compile(r'https?://\S+|www\.\S+')
# Palabras con mayúscula que no son nombres (inicio de frase, meses, días, términos comunes) en ca/es.
COMMON = {'el', 'la', 'els', 'les', 'los', 'las', 'un', 'una', 'en', 'a', 'de', 'del', 'i', 'y', 'amb', 'con', 'per', 'para', 'aquest', 'aquesta', 'este', 'esta',
          'gener', 'febrer', 'marc', 'abril', 'maig', 'juny', 'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre',
          'enero', 'febrero', 'marzo', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'noviembre', 'diciembre',
          'dilluns', 'dimarts', 'dimecres', 'dijous', 'divendres', 'dissabte', 'diumenge', 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo',
          'barcelona', 'catalunya', 'cataluna', 'espanya', 'espana'}


def needs(text):
    return MIN_TEXT <= len((text or '').strip())


def payload(ev):
    return {'text': (ev.get('description') or '').strip()[:MAX_TEXT]}


def text_hash(text):
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()[:16]


def _names(text):
    """Nombres propios probables: palabras con mayúscula que no van tras un punto y no son comunes."""
    out = set()
    for m in re.finditer(r'(?<![.!?¿¡:]\s)(?<!^)\b([A-ZÀ-Ý][\wÀ-ÿ\'’-]{2,})', text):
        word = m.group(1)
        if fold(word) not in COMMON: out.add(word)
    return out


def check(source, en):
    """(ok, problemas). Comprobaciones baratas que detectan lo grave: datos perdidos o inventados."""
    problems = []
    if not en.strip(): return False, ['vacía']
    src_nums = set(NUM.findall(source)); en_nums = set(NUM.findall(en))
    missing = sorted(n for n in src_nums if n not in en_nums and n.replace('.', '').replace(',', '') not in {x.replace('.', '').replace(',', '') for x in en_nums})
    if missing: problems.append('faltan números: ' + ', '.join(missing[:5]))
    added = sorted(n for n in en_nums - src_nums if n.replace('.', '').replace(',', '') not in {x.replace('.', '').replace(',', '') for x in src_nums})
    if added: problems.append('números nuevos: ' + ', '.join(added[:5]))
    lost_urls = [u for u in URL.findall(source) if u.rstrip('.,;)') not in en]
    if lost_urls: problems.append('enlaces perdidos')
    names = _names(source); kept = {n for n in names if fold(n) in fold(en)}
    if names and len(kept) < 0.8 * len(names): problems.append('nombres cambiados: ' + ', '.join(sorted(names - kept)[:5]))
    ratio = len(en) / max(1, len(source))
    if not 0.6 <= ratio <= 1.6: problems.append(f'longitud rara ({ratio:.2f})')
    return not problems, problems


def parse(row, payload):
    en = str(row.get('en') or '').strip(); lang = str(row.get('source_lang') or '').strip().lower()[:5]
    ok, problems = check(payload['text'], en)
    return json.dumps({'en': en, 'source_lang': lang, 'ok': ok, 'problems': problems}, ensure_ascii=False), 1.0 if ok else 0.0, '; '.join(problems)
