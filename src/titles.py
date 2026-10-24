"""Título que se muestra (24-10-2026): limpieza sin tocar el título de la fuente, que se conserva.

Reglas (decisión de David, 24-10-2026, tras la revisión de problemas de la web):
  1. Espacios: repetidos fuera; ninguno justo dentro de las comillas («" De 9 a 5"» → «"De 9 a 5"»).
  2. Comillas sin cerrar: si queda una comilla abierta sin pareja, se cierra al final
     («Activitat familiar "Tula Contes» → «Activitat familiar "Tula Contes"»).
  3. Marcas de estado del Ajuntament al final («*Ajornat», «**Anul·lat**»): fuera del título; el estado
     ya lo gestiona src/event_status.py.
  4. Prefijo genérico delante de un nombre entre comillas, cuando la categoría ya lo dice:
     «Concert "Dani Martin", dins la gira…» → «Dani Martin, dins la gira…» (Música);
     «Espectacle "X"» → «X» (Teatro y danza). «Espectacle familiar…», «Taller…», «Visita…» se quedan.
  5. Todo en mayúsculas → cada palabra con mayúscula inicial, salvo partículas («de», «la», «i»…)
     y siglas conocidas o sin vocales («GRAN GALA FLAMENCO» → «Gran Gala Flamenco»,
     «EL TENORIU» → «El Tenoriu», «DJ», «BCN», «MACBA» se quedan).
No se reescribe nada más: ni sinónimos, ni orden, ni traducción.
"""
from __future__ import annotations

import re

QUOTES = (('"', '"'), ('«', '»'), ('“', '”'))
NEW_MARK = re.compile(r"\s*-?\s*\*+\s*(?:nou|nova|nuevo|nueva|new|n)\s*\*+\s*$", re.I)   # «*NOU*», «*N*»: novedad, no es título
STATUS_TAIL = re.compile(r"\s*(?:\*+|-|–)\s*(?:places exhaurides|entrades exhaurides|ajornat|ajornada|aplazad[oa]|suspès|suspes|suspesa|suspendid[oa]|cancel·lat|cancel·lada|cancel\.lat|cancel\.lada|cancelad[oa]|anul·lat|anul·lada|anulad[oa])\s*\**\s*$", re.I)
PREFIX = {
    'musica': re.compile(r'^(?:concert|concierto)\s+["«“]([^"»”]+)["»”](.*)$', re.I),
    'escena': re.compile(r'^(?:espectacle|espectáculo|espectaculo)\s+["«“]([^"»”]+)["»”](.*)$', re.I),
}
PARTICLES = {'de', 'del', 'dels', 'la', 'las', 'les', 'el', 'els', 'los', 'lo', 'i', 'y', 'e', 'o', 'a', 'al', 'en', 'amb', 'con', 'per', 'para', 'pel', 'pels',
             'por', 'un', 'una', 'the', 'of', 'and', 'in', 'on', 'at', 'to', 'for', "d'", "l'"}
KEEP = {'DJ', 'DJS', 'BCN', 'MACBA', 'CCCB', 'MNAC', 'OBC', 'TNC', 'FC', 'UK', 'USA', 'EU', 'LGTBI', 'LGTBIQ', 'IA', 'AI', 'TV', 'VR', 'XXL', 'MC', 'BSO',
        'II', 'III', 'IV', 'VI', 'VII', 'VIII', 'IX', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XX', 'XXI', 'NYC', 'LA', 'UB', 'UPF', 'UAB', 'CIDOB', 'MOCO', 'BAM', 'SAT'}


def _spaces(t):
    t = ' '.join(t.split())
    # «''Bach, Beethoven i Ravel"»: dos apóstrofos hacen de comilla de apertura.
    t = re.sub(r"(?<![\w'])''(?=\w)", '"', t)
    if t.count('"') % 2 == 0:
        # «" De 9 a 5"»: dentro de cada pareja de comillas rectas, sin espacios en los bordes.
        t = re.sub(r'"\s*([^"]*?)\s*"', lambda m: '"' + m.group(1) + '"', t)
    else:
        t = re.sub(r'(^|[\s(])"\s+(?=\S)', r'\1"', t)   # comilla de apertura suelta: sin espacio detrás
    for o, c in QUOTES[1:]:
        t = re.sub(re.escape(o) + r'\s+', o, t); t = re.sub(r'\s+' + re.escape(c), c, t)
    return t


CLOSER = re.compile(r"['’”»](?=\s|$|[.,;:!?)])")   # una comilla que cierra (no el apóstrofo de «l'Òpera»)


def _close_quotes(t):
    """Cierra una comilla abierta sin pareja, solo si nada la cierra ya de otra manera («" Iniciació…'» se deja: la
    fuente la cerró con un apóstrofo). Con comillas simples de apertura («'Enquadernació (quinzenal)"») no se toca."""
    if re.search(r"(?:^|\s)['‘]\w", t): return t
    if t.count('"') % 2 == 1:
        last = t.rstrip()
        if last.endswith('"') and last.count('"') == 1: t = last[:-1].rstrip()   # comilla suelta al final
        elif not CLOSER.search(t[t.rfind('"') + 1:]) and not last.endswith('"'): t = last + '"'
    for o, c in QUOTES[1:]:
        if t.count(o) > t.count(c) and not CLOSER.search(t[t.rfind(o) + 1:]): t = t.rstrip() + c
    return t


def _is_all_caps(t):
    letters = [ch for ch in t if ch.isalpha()]
    return len(letters) >= 4 and sum(ch.isupper() for ch in letters) / len(letters) >= 0.9


def _word(w, first):
    core = re.sub(r"[^\w·'’-]", '', w)
    if not core: return w
    up = core.upper()
    if up in KEEP or (len(core) <= 4 and not re.search(r'[AEIOUÀÁÈÉÍÏÒÓÚÜ]', up)): return w
    low = w.lower()
    if not first and core.lower() in PARTICLES: return low
    # «D'ESTIU» → «d'Estiu»; «L'ART» → «L'Art»
    m = re.match(r"^([dlnsmt]['’])(.+)$", low)
    if m: return (m.group(1).capitalize() if first else m.group(1)) + m.group(2)[:1].upper() + m.group(2)[1:]
    i = next((k for k, ch in enumerate(low) if ch.isalpha()), None)
    return low if i is None else low[:i] + low[i].upper() + low[i + 1:]


def _title_case(t):
    words = t.split(' ')
    return ' '.join(_word(w, i == 0 or words[i - 1].endswith((':', '-', '–', '"', '«', '“'))) for i, w in enumerate(words))


def display_title(title, category=''):
    """El título limpio para mostrar; si nada cambia, el mismo."""
    t = str(title or '')
    if not t.strip(): return t
    t = NEW_MARK.sub('', STATUS_TAIL.sub('', t)); t = NEW_MARK.sub('', t)
    t = _close_quotes(_spaces(t))
    rx = PREFIX.get(category)
    if rx:
        m = rx.match(t)
        if m and len(m.group(1).strip()) >= 2: t = (m.group(1).strip() + m.group(2)).strip()
        t = _close_quotes(_spaces(t))
    if _is_all_caps(t): t = _title_case(t)
    return t
