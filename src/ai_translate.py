"""Traducción automática de descripciones al inglés y al castellano.

La tarea «traduccion» fue la muestra del 23-10-2026 (solo inglés, no publica). Las tareas
«traduccion_en» y «traduccion_es» (24-10-2026) son las de producción: el original se conserva siempre,
cada traducción guarda modelo, versión del prompt, huella del texto y resultado de la comprobación, y
solo se publica la que la pasa (si no, la ficha enseña el original).
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

PROMPT_VERSION = 1  # la comprobación es v2 (24-10-2026)
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


NUMBER_WORDS = {w: n for n, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split())}


def _names(text):
    """Nombres propios probables: dos o más palabras seguidas con mayúscula («Martín Rechimuzzi»,
    «Jacques Rancière», «Universitat Autònoma de Barcelona»). Una palabra suelta con mayúscula puede ser
    un país o el inicio de una exclamación que se traduce («Alemanya», «¡Prepárate»): no cuenta."""
    out = set()
    cap = r"[A-ZÀ-Ý][\wÀ-ÿ'’-]+"
    for m in re.finditer(rf"{cap}(?:\s+(?:de |del |i |y |la |el )?{cap})+", text):
        words = [w for w in re.findall(cap, m.group(0)) if fold(w) not in COMMON]
        if len(words) >= 2: out.add(' '.join(words))
    return out


# Números escritos con letras en catalán/castellano, décadas y siglos en romanos: la traducción puede
# pasarlos a cifras («tres actes» → three acts / 3 acts; «dels vuitanta» → 1980s; «s. XII» → 12th century).
WORDS_CA_ES = {'u': 1, 'un': 1, 'una': 1, 'uno': 1, 'dos': 2, 'dues': 2, 'tres': 3, 'quatre': 4, 'cuatro': 4, 'cinc': 5, 'cinco': 5, 'sis': 6, 'seis': 6,
               'set': 7, 'siete': 7, 'vuit': 8, 'ocho': 8, 'nou': 9, 'nueve': 9, 'deu': 10, 'diez': 10, 'onze': 11, 'once': 11, 'dotze': 12, 'doce': 12,
               'tretze': 13, 'trece': 13, 'catorze': 14, 'catorce': 14, 'quinze': 15, 'quince': 15, 'setze': 16, 'dieciseis': 16, 'vint': 20, 'veinte': 20,
               'zero': 0, 'cero': 0, 'disset': 17, 'diecisiete': 17, 'divuit': 18, 'dieciocho': 18, 'dinou': 19, 'diecinueve': 19,
               'desena': 10, 'decena': 10, 'dotzena': 12, 'docena': 12, 'duo': 2, 'trio': 3, 'quartet': 4, 'cuarteto': 4, 'quintet': 5, 'quinteto': 5, 'sextet': 6, 'sexteto': 6,
               'primer': 1, 'primera': 1, 'primero': 1, 'segon': 2, 'segona': 2, 'segundo': 2, 'segunda': 2, 'tercer': 3, 'tercera': 3, 'tercero': 3}
DECADES_CA_ES = {'vint': 20, 'veinte': 20, 'trenta': 30, 'treinta': 30, 'quaranta': 40, 'cuarenta': 40, 'cinquanta': 50, 'cincuenta': 50,
                 'seixanta': 60, 'sesenta': 60, 'setanta': 70, 'setenta': 70, 'vuitanta': 80, 'ochenta': 80, 'noranta': 90, 'noventa': 90}
ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100}


def _roman(token):
    total = 0
    for a, b in zip(token, token[1:] + ' '):
        v = ROMAN[a]; total += -v if b != ' ' and ROMAN.get(b, 0) > v else v
    return total


def _numbers(text, english=False):
    """Números normalizados («21:00» y «21 h» → 21; «16.30» → 1630 y 16). En inglés también las palabras
    (three → 3) y la hora de tarde (4 pm → 16). En catalán/castellano, números con letras, décadas y siglos."""
    found = set()
    for n in NUM.findall(text):
        found.add(n.replace('.', '').replace(',', '').replace(':', '').lstrip('0') or '0')
        if re.fullmatch(r'\d{1,2}[:.]\d{2}', n): found.add(str(int(re.split(r'[:.]', n)[0])))  # hora
    low = fold(text)
    if english:
        found |= {str(v) for w, v in NUMBER_WORDS.items() if re.search(rf'\b{w}\b', low)}
        for h, mm in re.findall(r'\b(\d{1,2})([:.]\d{2})?\s*p\.?\s?m\b', low):
            found.add(str(int(h) % 12 + 12)); found.discard(h.lstrip('0') or '0')  # «8 pm» es la hora 20, no un 8 nuevo
            if mm: found.discard((h + mm[1:]).lstrip('0'))
    else:
        found |= {str(v) for w, v in WORDS_CA_ES.items() if re.search(rf'\b{w}\b', low)}
        for w, v in DECADES_CA_ES.items():
            if re.search(rf'\b(?:dels|de los|anys|años|decada|dècada)\s+{w}\b', low) or re.search(rf'\b{w}s?\b', low): found |= {str(1900 + v), str(v)}
        for r in re.findall(r'\b(?:s\.|segle|siglo|seg\.)\s*([IVXLC]{1,6})\b', text): found.add(str(_roman(r)))
    return found


def check(source, en):
    """(ok, problemas, avisos). Rechaza lo grave (datos perdidos o inventados); avisa de lo dudoso."""
    problems, warnings = [], []
    if not en.strip(): return False, ['vacía']
    src_nums, en_nums = _numbers(source), _numbers(en, english=True)
    missing = sorted(n for n in src_nums if n not in en_nums and not (len(n) == 4 and n.endswith('00') and n[:2] in en_nums))
    # Lo que la fuente escribe con letras puede salir con letras: solo cuentan las cifras de verdad del original.
    digits_src = {n.replace('.', '').replace(',', '').replace(':', '').lstrip('0') or '0' for n in NUM.findall(source)}
    missing = [n for n in missing if n in digits_src]
    if missing: problems.append('faltan números: ' + ', '.join(missing[:5]))
    added = sorted(n for n in en_nums - src_nums if n.isdigit() and not (n.endswith('00') and len(n) == 4 and n[:2] in src_nums))
    if added: problems.append('números nuevos: ' + ', '.join(added[:5]))
    lost_urls = [u for u in URL.findall(source) if u.rstrip('.,;)') not in en]
    if lost_urls: problems.append('enlaces perdidos')
    ratio = len(en) / max(1, len(source))
    if not 0.6 <= ratio <= 1.6: problems.append(f'longitud rara ({ratio:.2f})')
    # Nombres: solo aviso, porque una institución o un acontecimiento se traducen con razón
    # («Universitat Ramon Llull» → Ramon Llull University, «Guerra Civil» → Civil War).
    names = _names(source); lost = sorted(n for n in names if not any(fold(w) in fold(en) for w in n.split() if len(w) > 3))
    if lost: warnings.append('revisar nombres: ' + ', '.join(lost[:4]))
    return not problems, problems + warnings if problems else ([] if not warnings else ['aviso · ' + '; '.join(warnings)])


# ---------- producción: inglés y castellano (24-10-2026) ----------
TARGETS = ('en', 'es')
LANG_NAMES = {'en': 'English', 'es': 'Spanish (Spain)'}
STYLE = {'en': 'Plain, natural British English.', 'es': 'Castellano de España, natural y sencillo.'}


def system_for(lang):
    return f"""You translate event descriptions from a Barcelona cultural listings site (Ontoca) into {LANG_NAMES[lang]}.
The source text is usually Catalan, sometimes Spanish or English. Translate it faithfully and completely:
- Do not add, remove, summarise or explain anything. No new adjectives, opinions or calls to action.
- Keep proper names exactly as written, including accents and diacritics (Händel stays Händel, Pérez stays Pérez):
  people, groups, venues, works, festivals, organisations, streets, neighbourhoods.
  Titles of works stay in their original language (you may keep quotation marks as in the source).
- Keep every number, date, time, price, age and URL exactly as in the source (digits stay digits; 24-hour times stay 24-hour).
- {STYLE[lang]} Keep paragraph breaks.
- If the text is already in {LANG_NAMES[lang]}, return it unchanged.
Also return the language of the source text (ca, es, en or other).
Answer with the tool traducir, one entry per item (n)."""


def tool_for(lang):
    return {'name': 'traducir', 'description': f'{LANG_NAMES[lang]} translation of each description.',
            'input_schema': {'type': 'object', 'required': ['items'], 'properties': {'items': {'type': 'array', 'items': {
                'type': 'object', 'required': ['n', 'source_lang', 'text'],
                'properties': {'n': {'type': 'integer'}, 'source_lang': {'type': 'string'}, 'text': {'type': 'string'}}}}}}}


MARKERS = {'ca': {'els', 'amb', 'per', 'aquest', 'aquesta', 'dels', 'i', 'què', 'també', 'però', 'seva', 'seu', 'fins', 'molt', 'una', 'és', 'més', 'pel', 'als', 'on'},
           'es': {'los', 'con', 'para', 'por', 'este', 'esta', 'las', 'y', 'también', 'pero', 'su', 'sus', 'muy', 'hasta', 'una', 'es', 'más', 'que', 'donde'},
           'en': {'the', 'and', 'with', 'of', 'for', 'is', 'this', 'to', 'in', 'on', 'from', 'by', 'are'}}


def guess_lang(text):
    """Idioma probable del texto por palabras frecuentes ('ca', 'es', 'en' o '' si no está claro).
    Solo sirve para no pedir lo que ya está en el idioma de destino; la palabra final la da la respuesta."""
    words = re.findall(r"[a-zà-ÿ·]+", (text or '').lower()[:1500])
    if any("l·l" in w for w in words): words.append('i')  # ela geminada: catalán
    score = {k: sum(w in m for w in words) for k, m in MARKERS.items()}
    best = sorted(score.items(), key=lambda x: -x[1])
    return best[0][0] if best[0][1] >= 4 and best[0][1] >= 2 * best[1][1] else ''


def check_target(source, target, lang):
    """Como check(), para el idioma de destino: en inglés, igual; en castellano, los números del destino
    se leen con las palabras de catalán/castellano y solo cuentan como nuevas las cifras escritas."""
    if lang == 'en': return check(source, target)
    problems, warnings = [], []
    if not target.strip(): return False, ['vacía']
    src_nums, tgt_nums = _numbers(source), _numbers(target)
    digits = lambda t: {n.replace('.', '').replace(',', '').replace(':', '').lstrip('0') or '0' for n in NUM.findall(t)}
    digits_src = digits(source)
    missing = sorted(n for n in src_nums & digits_src if n not in tgt_nums)
    if missing: problems.append('faltan números: ' + ', '.join(missing[:5]))
    tgt_hours = {str(int(re.split(r'[:.]', n)[0])) for n in NUM.findall(target) if re.fullmatch(r'\d{1,2}[:.]\d{2}', n)}
    added = sorted(n for n in digits(target) | tgt_hours if n not in src_nums)
    if added: problems.append('números nuevos: ' + ', '.join(added[:5]))
    if [u for u in URL.findall(source) if u.rstrip('.,;)') not in target]: problems.append('enlaces perdidos')
    ratio = len(target) / max(1, len(source))
    if not 0.7 <= ratio <= 1.5: problems.append(f'longitud rara ({ratio:.2f})')
    names = _names(source); lost = sorted(n for n in names if not any(fold(w) in fold(target) for w in n.split() if len(w) > 3))
    if lost: warnings.append('revisar nombres: ' + ', '.join(lost[:4]))
    return not problems, problems + warnings if problems else ([] if not warnings else ['aviso · ' + '; '.join(warnings)])


def parser_for(lang):
    def parse_target(row, payload):
        text = str(row.get('text') or '').strip(); src = str(row.get('source_lang') or '').strip().lower()[:5]
        if not text: return None  # vacía: se vuelve a pedir
        if src == lang:  # ya estaba en el idioma de destino: no hay traducción que publicar
            return json.dumps({'text': '', 'source_lang': src, 'ok': False, 'problems': ['ya en el idioma']}, ensure_ascii=False), 0.0, 'ya en el idioma'
        ok, problems = check_target(payload['text'], text, lang)
        return json.dumps({'text': text, 'source_lang': src, 'ok': ok, 'problems': problems}, ensure_ascii=False), 1.0 if ok else 0.0, '; '.join(problems)
    return parse_target


def parse(row, payload):
    en = str(row.get('en') or '').strip(); lang = str(row.get('source_lang') or '').strip().lower()[:5]
    if not en: return None  # respuesta vacía: se vuelve a pedir en un grupo más pequeño
    ok, problems = check(payload['text'], en)
    return json.dumps({'en': en, 'source_lang': lang, 'ok': ok, 'problems': problems}, ensure_ascii=False), 1.0 if ok else 0.0, '; '.join(problems)
