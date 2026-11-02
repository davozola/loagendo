"""Extracción con IA a partir del texto de la fuente (20-10-2026).

La IA lee el texto que publica la fuente (descripción, horario, precio) y propone sesiones, precio,
lugar, inscripción, público familiar, aire libre y franja de edad. **Cada dato llega con la cita
literal de la que sale, y aquí se comprueba**: la cita tiene que estar en el texto y el dato tiene
que poder leerse en la cita (la hora «19:00» en «a les 19 h»). Lo que no pasa la comprobación se
descarta. Así la IA no puede inventar una hora ni un precio (regla fija del proyecto).

Las franjas de edad se leen primero con reglas (``ages_by_rule``); la IA solo cubre lo que las
reglas no ven, con la misma exigencia de cita.
"""
from __future__ import annotations

import re
import unicodedata

MAX_TEXT = 2500


def fold(text):
    text = unicodedata.normalize('NFKD', str(text or '').replace('’', "'").replace('·', '.')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(text.split())


# ---------- edades por regla ----------
_N = r'(\d{1,2})'
_Y = r"(?:anys|any|anos|ano|years?|a\.)"
AGE_PATTERNS = [  # (regex, constructor, solo en el título)
    (re.compile(rf"\bde {_N} (?:a|al|fins a|fins als|hasta) {_N} {_Y}"), lambda a, b: (int(a), int(b)), False),  # «de 0 hasta 5 años» (28-10-2026)
    (re.compile(rf"\bentre {_N} [iy] {_N} {_Y}"), lambda a, b: (int(a), int(b)), False),
    (re.compile(rf"\(\s*{_N} ?[-–/a] ?{_N} ?{_Y}"), lambda a, b: (int(a), int(b)), False),
    (re.compile(rf"\b{_N} ?[-–] ?{_N} {_Y}"), lambda a, b: (int(a), int(b)), False),
    (re.compile(rf"\b(?:a partir de|des de|desde) {_N} {_Y}"), lambda a: (int(a), None), False),
    (re.compile(rf"\b(?:infants|nens|nenes|ninos|ninas|criatures|joves|jovenes|adolescents|adolescentes) (?:de|a partir de) {_N} {_Y}"), lambda a: (int(a), None), False),
    (re.compile(rf"\b(?:mes de|mas de|majors de|mayores de) {_N} {_Y}"), lambda a: (int(a), None), True),
    (re.compile(rf"(?<!\w)\+ ?{_N}\b"), lambda a: (int(a), None), True),
    (re.compile(rf"\b(?:fins a|hasta|menors de|menores de) {_N} {_Y}"), lambda a: (0, int(a)), True),
    (re.compile(rf"\bde {_N} a {_N} (?:mesos|meses)\b"), lambda a, b: (0, max(1, (int(b) + 11) // 12)), False),
    (re.compile(r"\b(?:nadons|bebes)\b"), lambda: (0, 2), True),
    (re.compile(r"\bprimera infancia\b"), lambda: (0, 3), True),
]


# Una edad en el texto no siempre es la del público (1-11-2026, auditoría del 6-11): en las tarifas es una franja de
# precio («reduïda: persones de 16 a 29 anys», «junior (4 a 12 anys)», «majors de 65 anys») y en una biografía, la de
# los artistas («tienen entre 19 y 21 años cuando dan su primer concierto», Múltipla). Esas no se toman como edad
# recomendada; si no queda otra, la ficha va sin edad (mejor ninguna que una falsa).
AGE_TARIFF = re.compile(r"(?:\bentrada|reduid|reducid|\btarifa|\bpreu|\bprecio|\bdescompte|\bdescuento|\bgratuit|\bgratuita|\bgratis\b|"
                        r"\beur\b|€|\bsenior|\bjunior|\bestudiants|\bestudiantes|\bcarnet|\bjubilat|\bjubilad|\bpensionist|\baturat|"
                        r"\bparad[oa]s\b|discapacitat|discapacidad|\bacreditar|\bbonificad|\bbonificac|\bnen \(|\bnens? \(|\bmenors\b|\bmenores\b)")
AGE_TARIFF_HEADER = re.compile(r"(?:reduid|reducid|\btarifa|\bpreu|\bprecio|\bdescompte|\bdescuento|entrada general|\bbonificad)")
AGE_TARIFF_AFTER = re.compile(r"^[\s)]*(?::|\+ ?concert|\(?\d+(?:[.,]\d+)? ?(?:€|eur))")
AGE_AUDIENCE = re.compile(r"(?:\bper a (?:infants|nens|nenes|joves|families|public)|\bper (?:infants|nens|nenes|joves)|\bpara (?:ninos|ninas|jovenes|familias|publico)|"
                          r"\bdirigid[ao]s? a|\bdirigit a|\badrecad[ao]s? a|\badrecat a|\bdestinad[ao]s? a|\brecomanad?[ao]?|\brecomendad[ao]|\bedat\b|\bedad\b|"
                          r"\bnenes i nens|\bnens i nenes|\bninos y ninas|\bpublic\b|\bpublico\b|\bage\b|\bages\b)")
AGE_PERFORMERS_BEFORE = re.compile(r"\b(?:tienen|tenen|tenien|tenian|tenia|tiene|te|cumplen|compleixen)\s*$")
AGE_SEGMENT = re.compile(r"(?:\.\s|\s\.\s|\s-\s|;|\|\||\n)")
AGE_TARIFF_WINDOW = 70


def _audience_age(text, m, lo):
    """¿La edad encontrada en el texto es la del público? (1-11-2026, auditoría del 6-11)
    · No si habla de los artistas («tienen entre 19 y 21 años cuando…», Múltipla).
    · Sí si la frase la presenta como público («activitat dirigida a joves de 16 a 35 anys», «per a infants de 0 a 14»,
      «edat recomanada»), aunque la actividad sea gratuita.
    · No si es una tarifa: en la misma frase hay precio o descuento («Entrada menors de 4 a 10 anys + concert: 8 €»,
      «junior (4 a 12 anys)»), o va en la lista de un precio reducido («Reduïda: - persones de 16 a 29 anys»), o la
      sigue un precio o dos puntos. Un «a partir de N anys» suelto tras los precios sí es el público («a partir de 3 anys»).
    · No si es de 60 años o más: en un texto es siempre una tarifa de mayores."""
    if lo >= 60: return False
    window = text[max(0, m.start() - AGE_TARIFF_WINDOW):m.start()]
    segment = AGE_SEGMENT.split(window)[-1]
    if AGE_PERFORMERS_BEFORE.search(segment): return False
    if AGE_AUDIENCE.search(segment): return True
    after = text[m.end():m.end() + 30]
    if AGE_TARIFF.search(segment) or AGE_TARIFF_AFTER.search(after): return False
    open_ended = bool(re.match(r"(?:a partir de|des de|desde)\b", m.group(0)))
    if AGE_TARIFF_HEADER.search(window) and not open_ended: return False
    return True


def ages_by_rule(title, text=''):
    """(edad mínima, edad máxima o None, cita) si el título o el texto la dicen; si no, None.
    Las fórmulas sueltas («més de 30 anys», «+18») solo valen en el título: en un texto suelen
    hablar de otra cosa («més de 30 anys d'història»). En el texto, una edad de una tarifa o de los
    artistas no cuenta (_audience_age)."""
    for source, is_title in ((title or '', True), (text or '', False)):
        t = fold(source)
        for rx, build, title_only in AGE_PATTERNS:
            if title_only and not is_title: continue
            for m in rx.finditer(t):
                try: lo, hi = build(*m.groups())
                except (TypeError, ValueError, IndexError): continue
                if hi is not None and (hi < lo or hi > 99) or lo > 99: continue
                if not is_title and not _audience_age(t, m, lo): continue
                return lo, hi, m.group(0).strip('( ')
    return None


# ---------- comprobaciones ----------
def quote_in(quote, text):
    q = fold(quote).strip(' .,;:"\''); return len(q) >= 3 and q in fold(text)


TIME_RX = re.compile(r"(?<![\d/])(\d{1,2})\s*(?:[:.,]\s*(\d{2})|h\s*(\d{2})?|\s*(?:hores|horas|hrs?)\b)|(?:a les|a las|a la|at|des de les|desde las|de les|de las|fins a les|hasta las)\s+(\d{1,2})(?:[:.](\d{2}))?")


RANGE_RX = re.compile(r"(?:de|des de|desde|entre)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(?:a|i|y|fins a|hasta|-|–)\s*(?:les\s+|las\s+)?(\d{1,2})(?:[:.](\d{2}))?\s*(?:h\b|hores|horas)")


# «8 pm», «10 am», «8 p.m.» sin minutos (2-11-2026, LOOP: «miércoles 18 noviembre 2026, 8 pm»): solo con am/pm pegado.
AMPM_RX = re.compile(r"(?<![\d:.,])(\d{1,2})\s*([ap])\.?\s*m\b\.?")


def times_in(quote):
    out = set()
    for m in AMPM_RX.finditer(fold(quote)):
        h = int(m.group(1))
        if 1 <= h <= 12: out.add(f"{(h % 12) + (12 if m.group(2) == 'p' else 0):02d}:00")
    for m in RANGE_RX.finditer(fold(quote)):
        for h, mm in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
            if 0 <= int(h) <= 24: out.add(f'{int(h) % 24:02d}:{int(mm or 0):02d}')
    q = fold(quote)
    for m in TIME_RX.finditer(q):
        h = m.group(1) or m.group(4); mm = m.group(2) or m.group(3) or m.group(5) or '00'
        if h is not None and 0 <= int(h) <= 24 and 0 <= int(mm) < 60:
            out.add(f'{int(h) % 24:02d}:{int(mm):02d}')
            # «6:30 p.m.» (In-Edit en inglés, 28-10-2026): también la hora de la tarde.
            if int(h) < 12 and re.match(r"\s*p\.?\s*m\b", q[m.end():m.end() + 8]): out.add(f'{int(h) + 12:02d}:{int(mm):02d}')
    return out


def time_ok(value, quote): return bool(re.fullmatch(r'\d{2}:\d{2}', value or '')) and value in times_in(quote)


def day_ok(date, quote):
    m = re.fullmatch(r'\d{4}-(\d{2})-(\d{2})', date or '')
    return bool(m) and re.search(rf"(?<!\d)0?{int(m.group(2))}(?!\d)", fold(quote)) is not None


def number_ok(value, quote):
    if value is None: return True
    n = float(value); nums = {float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d{1,2})?', fold(quote))}
    return n in nums


FREE_RX = re.compile(r"\b(?:gratu[iï]t|gratuita|gratis|free|entrada lliure|entrada libre|acces lliure|acceso libre|sense cost|sin coste)\b")


def verify(answer, text, start, end):
    """Deja solo lo comprobado. ``answer`` es la salida de la herramienta para una ficha."""
    out = {}; dropped = []
    sessions = []
    for s in answer.get('sesiones') or []:
        q = s.get('cita') or ''; date = s.get('fecha') or ''
        if not quote_in(q, text) or not (start <= date <= end) or not day_ok(date, q) and start != end:
            dropped.append(('sesion', s)); continue
        if s.get('inicio') and not time_ok(s['inicio'], q): dropped.append(('hora', s)); continue
        end_time = s.get('fin') if s.get('fin') and time_ok(s.get('fin'), q) else ''
        sessions.append({'date': date, 'time': s.get('inicio') or '', 'end': end_time, 'quote': q})
    if sessions: out['sessions'] = sessions
    price = answer.get('precio') or {}
    if price and quote_in(price.get('cita') or '', text):
        q = price['cita']
        if price.get('gratis') and FREE_RX.search(fold(q)): out['price'] = {'free': True, 'label': 'Gratis', 'quote': q}
        elif (price.get('min') is not None or price.get('max') is not None) and number_ok(price.get('min'), q) and number_ok(price.get('max'), q):
            lo, hi = price.get('min'), price.get('max')
            fmt = lambda v: (f'{v:.2f}'.rstrip('0').rstrip('.').replace('.', ',')) + ' €'
            label = fmt(lo) if lo is not None and (hi is None or hi == lo) else (f'{fmt(lo)} – {fmt(hi)}' if lo is not None else f'Hasta {fmt(hi)}')
            out['price'] = {'free': False, 'label': label, 'quote': q}
        else: dropped.append(('precio', price))
    place = answer.get('lugar') or {}
    if place.get('nombre') and quote_in(place.get('cita') or '', text) and fold(place['nombre']) in fold(place['cita']):
        out['place'] = {'name': place['nombre'].strip(), 'address': (place.get('direccion') or '').strip() if fold(place.get('direccion') or '') in fold(place['cita']) else '', 'quote': place['cita']}
    reg = answer.get('inscripcion') or {}
    if reg.get('requerida') and quote_in(reg.get('cita') or '', text) and re.search(r"inscrip|reserva|registr|aforament|aforo|places limitades|plazas limitadas", fold(reg['cita'])):
        out['registration'] = {'required': True, 'quote': reg['cita']}
    for key, name in (('familia', 'family'), ('aire_libre', 'outdoor')):
        v = answer.get(key) or {}
        if v.get('es') and quote_in(v.get('cita') or '', text): out[name] = {'quote': v['cita']}
    ages = answer.get('edades') or {}
    if ages and quote_in(ages.get('cita') or '', text) and (ages.get('min') is not None or ages.get('max') is not None):
        lo, hi = ages.get('min'), ages.get('max')
        months = re.search(r'mesos|meses|months', fold(ages['cita']))
        if (months or number_ok(lo, ages['cita'])) and (months or number_ok(hi, ages['cita'])):
            out['ages'] = {'min': int(lo or 0), 'max': int(hi) if hi is not None else None, 'quote': ages['cita']}
    return out, dropped


# ---------- lo que se le pide ----------
SYSTEM = """Extraes datos de actividades culturales de Barcelona a partir del texto que publica la fuente. Para cada ficha recibes título, fechas (inicio y fin), sala y texto.
Devuelve SOLO lo que el texto dice explícitamente, cada dato con una cita LITERAL copiada del texto (unas palabras, sin cambiar nada) donde se lee:
- sesiones: cada sesión con fecha (AAAA-MM-DD, dentro de las fechas de la ficha), hora de inicio y de fin (HH:MM) si constan.
- precio: gratis, o importe mínimo y máximo en euros.
- lugar: nombre de la sala o espacio y dirección, si el texto los da.
- inscripcion: si hace falta inscribirse o reservar.
- familia: si está pensada para niños o familias.
- aire_libre: si es en la calle, un parque, una plaza o al aire libre.
- edades: edad mínima y máxima del público (en años) si el texto la indica.
Si un dato no aparece, omítelo. No deduzcas, no completes, no conviertas formatos dudosos. Las citas se comprueban automáticamente contra el texto.
Responde con la herramienta extraer, una entrada por ficha (n)."""

_quote = {'type': 'string'}
TOOL = {'name': 'extraer', 'description': 'Datos extraídos de cada ficha, con su cita literal.',
        'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n'], 'properties': {
                'n': {'type': 'integer'},
                'sesiones': {'type': 'array', 'items': {'type': 'object', 'properties': {'fecha': {'type': 'string'}, 'inicio': {'type': 'string'}, 'fin': {'type': 'string'}, 'cita': _quote}}},
                'precio': {'type': 'object', 'properties': {'gratis': {'type': 'boolean'}, 'min': {'type': 'number'}, 'max': {'type': 'number'}, 'cita': _quote}},
                'lugar': {'type': 'object', 'properties': {'nombre': {'type': 'string'}, 'direccion': {'type': 'string'}, 'cita': _quote}},
                'inscripcion': {'type': 'object', 'properties': {'requerida': {'type': 'boolean'}, 'cita': _quote}},
                'familia': {'type': 'object', 'properties': {'es': {'type': 'boolean'}, 'cita': _quote}},
                'aire_libre': {'type': 'object', 'properties': {'es': {'type': 'boolean'}, 'cita': _quote}},
                'edades': {'type': 'object', 'properties': {'min': {'type': 'integer'}, 'max': {'type': 'integer'}, 'cita': _quote}}}}}}}}


def payload(ev):
    return {'titulo': (ev.get('title') or '')[:200], 'fechas': [ev.get('start'), ev.get('end')],
            'sala': (ev.get('source_venue') or (ev.get('venue_names') or [''])[0] or '')[:100], 'texto': (ev.get('source_text') or '')[:MAX_TEXT]}


def needs(ev):
    """Solo fichas con texto propio (≥ 40 caracteres) a las que les falta algo que la IA puede
    aportar (20-10-2026): la hora de un acto de un día o de pocos días, o el precio. Lo que ya da la
    fuente no se pregunta; lo ya respondido no se repite (huella de la entrada)."""
    if len((ev.get('source_text') or '').strip()) < 40: return False
    import datetime as _dt
    try: span = (_dt.date.fromisoformat(str(ev.get('end'))[:10]) - _dt.date.fromisoformat(str(ev.get('start'))[:10])).days
    except ValueError: span = 0
    own_time = bool(ev.get('time')) and ev.get('time_source') != 'ia_texto'
    own_price = bool(ev.get('price_label') or ev.get('price_text') or ev.get('is_free')) and ev.get('price_source') != 'ia_texto'
    return (span <= 4 and not own_time) or not own_price
