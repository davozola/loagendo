"""Horario oficial de GuiaBCN, fila a fila y día a día.

La API de listado de GuiaBCN solo trae fechas. El horario está en el detalle
(`pg=detall`), en `timetable.horari`: una fila por tramo, con `dies`, `hores`,
`preu`, `observacions` y a veces `periode`. Cada fila se interpreta por
separado y solo se asigna una hora a un día cuando días y horas se leen sin
ambigüedad; lo que no se entiende se deja sin hora (nunca se rellena).
"""
from __future__ import annotations
import datetime as dt
import html
import re

# El orden de los parámetros importa: con id_doc al final el servidor responde
# 406 (comprobado el 18-10-2026; la primera pasada del motor cayó entera a la
# página web por esto).
DETAIL_API = 'https://apinasia.bcn.cat/services/asia/retroapiguiabcn/?pg=detall&id_doc={id}&xout=json&idma=ca'
ROW_FIELDS = ('dies', 'hores', 'preu', 'observacions', 'periode')

MONTHS = {'gener': 1, 'enero': 1, 'febrer': 2, 'febrero': 2, 'març': 3, 'marzo': 3, 'abril': 4, 'maig': 5, 'mayo': 5,
          'juny': 6, 'junio': 6, 'juliol': 7, 'julio': 7, 'agost': 8, 'agosto': 8, 'setembre': 9, 'septiembre': 9,
          'octubre': 10, 'novembre': 11, 'noviembre': 11, 'desembre': 12, 'diciembre': 12}
WEEKDAYS = {'dilluns': 0, 'lunes': 0, 'dimarts': 1, 'martes': 1, 'dimecres': 2, 'miércoles': 2, 'miercoles': 2,
            'dijous': 3, 'jueves': 3, 'divendres': 4, 'viernes': 4, 'dissabte': 5, 'sábado': 5, 'sabado': 5,
            'diumenge': 6, 'domingo': 6}
_MONTH = '(' + '|'.join(sorted(MONTHS, key=len, reverse=True)) + ')'
_WEEKDAY = '(' + '|'.join(sorted(WEEKDAYS, key=len, reverse=True)) + r')s?'
_OF = r"(?:\s+(?:de\s+|d['’]\s*)|\s+)"
# Palabras de enlace que pueden quedar entre días u horas sin cambiar su sentido.
_DAY_GLUE = re.compile(r"\b(?:i|y|and|de|del|d['’]|dies|dia|els|les|los|las|el|la|al|a|cada|tots|todos)\b|[,;.:/\-–]", re.I)
_HOUR_GLUE = re.compile(r"\b(?:i|y|o|and|or|a|de|les|las|la|hores|horas|h|partir)\b|[,;.:\-–()]", re.I)


def plain(markup):
    """Texto de una celda de la API (HTML pequeño) en una línea."""
    text = re.sub(r'<br\s*/?>|</p>|</li>', ' ', str(markup or ''), flags=re.I)
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).replace('\xa0', ' ').split())


def notes(markup):
    """Precio u observaciones: cada párrafo es una indicación distinta
    («Cal inscripció prèvia», «Places limitades»), se separan con «·»."""
    parts = re.split(r'<br\s*/?>|</p>|</li>|</div>', str(markup or ''), flags=re.I)
    return ' · '.join(dict.fromkeys(p for p in (plain(x) for x in parts) if p))


def api_rows(detail):
    """Filas `timetable.horari` de una respuesta `pg=detall`, como texto plano.

    Devuelve None si la respuesta no es un detalle reconocible (para que quien
    llama recurra a la página web) y [] si es un detalle sin horario."""
    try:
        item = detail['page']['central']['detall']
    except (TypeError, KeyError):
        return None
    item = item.get('item', item) if isinstance(item, dict) else None
    if not isinstance(item, dict):
        return None
    horari = (item.get('timetable') or {}).get('horari') if isinstance(item.get('timetable'), dict) else None
    if isinstance(horari, dict):
        horari = [horari]
    rows = []
    for raw in horari or []:
        if not isinstance(raw, dict):
            continue
        row = {key: (notes(raw.get(key)) if key in ('preu', 'observacions') else plain(raw.get(key))) for key in ROW_FIELDS}
        row = {key: value for key, value in row.items() if value}
        if row:
            rows.append(row)
    return rows


LINK_LABELS = {'web': 'Web del evento', 'web inscripcions': 'Inscripciones', "web venda d'entrades": 'Entradas'}


def api_links(detail):
    """Enlaces que la ficha oficial declara (`interestinfo`: web del evento,
    inscripciones, entradas). Son los únicos enlaces útiles: el resto de la
    página es menú del Ajuntament."""
    try: item = detail['page']['central']['detall']
    except (TypeError, KeyError): return []
    item = item.get('item', item) if isinstance(item, dict) else {}
    info = (item.get('interestinfo') or {}).get('item') if isinstance(item.get('interestinfo'), dict) else None
    out = []
    for entry in (info if isinstance(info, list) else [info] if info else []):
        url = str((entry or {}).get('interinfo') or '').strip()
        if url.startswith(('https://', 'http://')):
            label = str(entry.get('label') or '').strip()
            out.append({'label': LINK_LABELS.get(label.casefold(), label or 'Web del evento'), 'url': url})
    return out


def _clock(hour, minute):
    hour, minute = int(hour), int(minute or 0)
    return f'{hour:02d}:{minute:02d}' if hour <= 23 and minute <= 59 else None


def parse_hours(text):
    """'de 09.00 h a 18.00 h' → {'ranges': [('09:00','18:00')], 'sessions': []}.

    'a les 17.30 h i a les 20.30 h' → sesiones 17:30 y 20:30. Si queda texto que
    no es hora ni enlace («portes», «aprox.», «matí»…), devuelve None."""
    source = str(text or '').casefold()
    if not source.strip():
        return None
    source = re.sub(r'\([^)]*\)', ' ', source)  # «a les 10.30 h (anglès)»
    # «A partir de les 10 h i fins exhaurir existències»: la hora de inicio es la que cuenta.
    source = re.sub(r"\b(?:i\s+)?fins\s+(?:a\s+)?(?:exhaurir|esgotar|acabar)\s+(?:les\s+)?(?:existències|places|entrades)\b", ' ', source)
    ranges, sessions = [], []
    range_re = re.compile(r"(?:\bdes\s+de\s+les\s+|\bde\s+(?:les\s+)?|\bd['’]\s*)(\d{1,2})(?:[.:](\d{2}))?\s*(h\b)?\s*(?:a|fins\s+a)\s+(?:les\s+)?(\d{1,2})(?:[.:](\d{2}))?\s*(h\b)?")
    def take_range(match):
        if not (match.group(2) or match.group(5) or match.group(3) or match.group(6)):
            return match.group(0)  # «de 10 a 14» sin minutos ni «h»: podría no ser hora
        start, end = _clock(match.group(1), match.group(2)), _clock(match.group(4), match.group(5))
        if not start or not end:
            return match.group(0)
        ranges.append((start, end)); return ' '
    rest = range_re.sub(take_range, source)
    def take_session(match):
        value = _clock(match.group(1) or match.group(3), match.group(2) or match.group(4))
        if not value:
            return match.group(0)
        if value not in sessions: sessions.append(value)
        return ' '
    rest = re.sub(r'\b(\d{1,2})[.:](\d{2})\s*h?\b|\b(\d{1,2})()\s*h\b', take_session, rest)
    if (not ranges and not sessions) or _HOUR_GLUE.sub(' ', rest).strip():
        return None
    return {'ranges': ranges, 'sessions': sessions}


def hours_label(parsed):
    """Etiqueta pública: '09:00–18:00', '17:30 · 20:30' o ambas cosas."""
    bits = [f'{a}–{b}' for a, b in parsed['ranges']] + list(parsed['sessions'])
    return ' · '.join(bits)


def _span(start, end):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def _dated(day, month, start, end):
    """El año lo da el propio evento: solo vale una fecha dentro de su rango."""
    for year in sorted({start.year, end.year}):
        try:
            value = dt.date(year, month, day)
        except ValueError:
            continue
        if start <= value <= end:
            return value
    return None


def parse_days(text, start, end):
    """Días del evento a los que se refiere una fila, o None si no está claro.

    Entiende fechas sueltas o en lista («17 octubre, 18 octubre i 19 octubre»,
    «12 i 19 de desembre»), rangos («del 3 al 7 de novembre»), fechas
    numéricas (17/10/2026), días de la semana («Dissabte», «Dilluns i dimecres»,
    «De dilluns a divendres») y «cada dia». Cualquier palabra de más
    (festius, excepte, vigílies…) hace que la fila no se asigne."""
    source = str(text or '').casefold().strip()
    if not source or start is None or end is None or end < start:
        return None
    # «Dilluns excepte 12 octubre»: las fechas exceptuadas se restan; si la
    # excepción no son fechas concretas (festius, vacances…), no se asigna.
    base, _, excluded = source.partition('excepte')
    if excluded:
        removed = parse_days(excluded, start, end) if not re.search(r'[a-z]', re.sub(_MONTH + '|' + _DAY_GLUE.pattern, ' ', excluded)) else None
        included = parse_days(base, start, end)
        return None if removed is None or included is None else included - removed
    rest, dates, weekdays = source, set(), set()
    # «Dissabte 24 d'octubre»: ese día de la semana solo confirma la fecha.
    confirming = {WEEKDAYS[m.group(1)] for m in re.finditer(r'\b' + _WEEKDAY + r',?\s+(?=\d)', rest)}
    rest = re.sub(r'\b' + _WEEKDAY + r',?\s+(?=\d)', ' ', rest)
    if re.fullmatch(r"(?:obert\s+|abierto\s+)?(?:cada\s+dia|tots\s+els?\s+dies|todos\s+los\s+d[ií]as|diari(?:ament)?)(?:\s+de\s+l['’]any|\s+del\s+año)?\.?", source):
        return set(_span(start, end))
    def numeric(match):
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100: year += 2000
        if year:
            try: value = dt.date(year, int(match.group(2)), int(match.group(1)))
            except ValueError: return match.group(0)
            if not start <= value <= end: raise _Unclear
        else:
            value = _dated(int(match.group(1)), int(match.group(2)), start, end)
            if not value: raise _Unclear
        dates.add(value); return ' '
    def date_range(match):
        first_month = MONTHS[match.group(2)] if match.group(2) else MONTHS[match.group(4)]
        a, b = _dated(int(match.group(1)), first_month, start, end), _dated(int(match.group(3)), MONTHS[match.group(4)], start, end)
        if not a or not b or b < a: raise _Unclear
        dates.update(_span(a, b)); return ' '
    def weekday_range(match):
        a, b = WEEKDAYS[match.group(1)], WEEKDAYS[match.group(2)]
        weekdays.update(range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)]); return ' '
    try:
        rest = re.sub(r'\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b', numeric, rest)
        rest = re.sub(r"\b(?:del?\s+|de\s+l['’]\s*)(\d{1,2})(?:" + _OF + _MONTH + r")?\s+(?:al?|a\s+l['’])\s*(\d{1,2})" + _OF + _MONTH + r'\b', date_range, rest)
        rest = re.sub(r"\b(?:de|del|des\s+de)\s+" + _WEEKDAY + r"\s+(?:a|al|fins\s+a)\s+" + _WEEKDAY + r'\b', weekday_range, rest)
        # Listas: «12 i 19 de desembre» toma el mes del siguiente que se nombra.
        pending = []
        for match in re.finditer(r'\b(\d{1,2})\b(?:' + _OF + _MONTH + r'\b)?', rest):
            pending.append(int(match.group(1)))
            if match.group(2):
                for day in pending:
                    value = _dated(day, MONTHS[match.group(2)], start, end)
                    if not value: raise _Unclear
                    dates.add(value)
                pending = []
        for day in pending:
            # «Dimarts 20»: sin mes, vale si en las fechas del evento solo hay un día 20.
            matches = [d for d in _span(start, end) if d.day == day]
            if len(matches) != 1: return None
            dates.add(matches[0])
        rest = re.sub(r'\b(\d{1,2})\b(?:' + _OF + _MONTH + r'\b)?', ' ', rest)
    except _Unclear:
        return None
    # «1r i 3r divendres del mes», «els tercers dimecres de mes», «últim dissabte de cada mes».
    def monthly(match):
        wanted = {_ORDINALS[o] for o in re.findall(_ORDINAL, match.group(1))}
        days_of_week = {WEEKDAYS[w] for w in re.findall(r'\b' + _WEEKDAY + r'\b', match.group(2))}
        weekend = {5, 6} <= days_of_week   # «1r dissabte i diumenge»: el cap de setmana del 1r dissabte
        for d in _span(start, end):
            if weekend and d.weekday() == 6:
                sat = d - dt.timedelta(days=1)
                if ((sat.day - 1) // 7 + 1) in wanted or (-1 in wanted and (sat + dt.timedelta(days=7)).month != sat.month):
                    if start <= d <= end: dates.add(d)
                continue
            if d.weekday() not in days_of_week: continue
            nth = (d.day - 1) // 7 + 1
            last = (d + dt.timedelta(days=7)).month != d.month
            if nth in wanted or (-1 in wanted and last): dates.add(d)
        return ' '
    # «1r dissabte i diumenge del mes»: varios días de la semana para el mismo ordinal.
    rest = re.sub(r"\b((?:" + _ORDINAL + r")s?(?:\s*(?:,|i|y)\s*(?:" + _ORDINAL + r")s?)*)\s+(" + _WEEKDAY + r"(?:\s*(?:,|i|y)\s*" + _WEEKDAY + r")*)\s+(?:del|de)\s+(?:cada\s+)?mes\b", monthly, rest)
    named = {WEEKDAYS[m.group(1)] for m in re.finditer(r'\b' + _WEEKDAY + r'\b', rest)}
    rest = re.sub(r'\b' + _WEEKDAY + r'\b', ' ', rest)
    if _DAY_GLUE.sub(' ', rest).strip():
        return None
    if confirming and any(d.weekday() not in confirming for d in dates):
        return None
    weekdays |= named
    if not dates and not weekdays:
        return None
    # «Dijous i divendres i 31 octubre»: los días de la semana y las fechas se suman.
    return dates | {d for d in _span(start, end) if d.weekday() in weekdays}


_ORDINALS = {'1r': 1, '1er': 1, '1º': 1, 'primer': 1, 'primero': 1, '2n': 2, '2º': 2, 'segon': 2, 'segundo': 2,
             '3r': 3, '3er': 3, '3º': 3, 'tercer': 3, 'tercero': 3, '4t': 4, '4º': 4, 'quart': 4, 'cuarto': 4,
             '5è': 5, 'cinquè': 5, 'quinto': 5, 'últim': -1, 'ultim': -1, 'darrer': -1, 'último': -1, 'ultimo': -1}
_ORDINAL = '(?:' + '|'.join(sorted(map(re.escape, _ORDINALS), key=len, reverse=True)) + ')'


class _Unclear(Exception):
    pass


def part_of_day(text):
    """«Matinal», «Matins», «Horari de matí», «Tarda» → 'mañana' / 'tarde' / 'noche'; «Consulteu horaris al
    programa» → 'programa' (sin hora concreta en la fuente)."""
    if re.search(r"\bconsult|\bsegons\s+programaci|\bseg[uú]n\s+programaci", str(text or ''), re.I) and re.search(r"program|\bweb\b|enllaç|enlace", str(text or ''), re.I):
        return 'programa'   # «Consulteu horaris al programa del festival»: hay sesiones, cada una con su hora
    t = re.sub(r"\b(?:horari|horario|de|del|la|el|en|per|por|sessió|sesión|h)\b|[.,:()]", ' ', str(text or '').casefold()).split()
    if len(t) != 1: return ''
    return {'matí': 'mañana', 'matins': 'mañana', 'matinal': 'mañana', 'mañana': 'mañana', 'mañanas': 'mañana', 'matinades': 'mañana',
            'tarda': 'tarde', 'tardes': 'tarde', 'tarde': 'tarde', 'vespre': 'tarde', 'nit': 'noche', 'noche': 'noche'}.get(t[0], '')


CLOSED = re.compile(r"^\s*(?:tancat|tancada|cerrado|cerrada|closed)\b", re.I)


def period_days(row, start, end):
    """Días que abarca el periodo propio de una fila («Del 14 octubre a l'11
    novembre»), o None si no es una fecha concreta («Curs escolar»)."""
    return parse_days(row.get('periode'), start, end) if row.get('periode') else None


def schedule_by_day(rows, start, end):
    """{fecha ISO: etiqueta} con los días en que hay actividad.

    La etiqueta es la hora del día; queda vacía ('') si ese día hay actividad
    pero la hora no se puede afirmar (fila sin horas, o dos filas que dicen
    horas distintas para el mismo día; las sesiones sí se suman). Un periodo
    propio de la fila restringe sus días. Las excepciones vagas de las
    observaciones («Excepte vacances») no se aplican: la nota se enseña en la
    ficha."""
    start, end = _date(start), _date(end)
    out, origin, conflicts = {}, {}, set()
    single_day = start is not None and start == end
    previous_days, previous_index = None, None
    unclear, closed, parts = set(), set(), {}
    for index, row in enumerate(rows):
        if row.get('dies'):
            # «Dissabte, diumenge i festius»: los festivos no se pueden fechar; el fin de semana sí.
            days = parse_days(_HOLIDAYS.sub('', row.get('dies')), start, end); group = index
            within = period_days(row, start, end)
            if days is not None and within is not None: days = days & within
            if days is not None and row.get('season'): days = {d for d in days if in_season(d, row['season'])}
        else:
            # Sin días: continúa la fila anterior (otro grupo u otra sesión el mismo día).
            days, group = previous_days, previous_index
        previous_days, previous_index = days, group
        if row.get('dies') and not row.get('periode') and index and rows[index - 1].get('periode'):
            # Periodo vacío bajo otro = el mismo periodo (rowspan en la web: «Del 3 octubre a l'1 novembre / Dissabte / Diumenge…»).
            row = {**row, 'periode': rows[index - 1]['periode']}; rows[index] = row
            if days is not None:
                within = period_days(row, start, end)
                if within is not None: days = days & within
        if row.get('dies') and not (row.get('hores') or '').strip() and index and rows[index - 1].get('hores'):
            # Celda de horas vacía = la del día anterior (en la web es un rowspan: «Dissabte / Diumenge: a les 10.30 h»).
            row = {**row, 'hores': rows[index - 1]['hores']}; rows[index] = row
        if CLOSED.match(row.get('hores') or ''):
            closed.update(d.isoformat() for d in days or ())  # «Tots els dies: Tancat» en agosto
            continue
        parsed = parse_hours(row.get('hores'))
        if days is None and single_day and not any(r.get('dies') for r in rows[1:]):
            days = {start}  # un solo día: no hay a qué otro día atribuir la hora
        if not parsed:
            part = part_of_day(row.get('hores'))
            for d in days or ():
                (parts.__setitem__(d.isoformat(), part) if part else unclear.add(d.isoformat()))
            continue
        for day in days or ():
            key = day.isoformat()
            if key in conflicts: continue
            if key not in out:
                out[key], origin[key] = parsed, group; continue
            previous = out[key]
            if origin[key] != group and (previous['ranges'] or parsed['ranges']) and previous != parsed:
                # Dos filas distintas dicen horarios distintos para el mismo día.
                conflicts.add(key); del out[key]; continue
            out[key] = {'ranges': sorted(set(previous['ranges']) | set(parsed['ranges'])),
                        'sessions': sorted(set(previous['sessions']) | set(parsed['sessions']))}
    labels = {key: hours_label(value) for key, value in out.items()}
    labels.update({key: part for key, part in parts.items() if key not in labels})   # «Matinal» → 'mañana'
    labels.update({key: '' for key in (unclear | conflicts) if key not in labels})
    return dict(sorted((k, v) for k, v in labels.items() if k not in closed))


def _date(value):
    if isinstance(value, dt.date): return value
    try: return dt.date.fromisoformat(str(value)[:10])
    except ValueError: return None


def summary(rows, start, end):
    """Lo que se guarda y se enseña a partir de las filas.

    - ``by_day``: hora por día (lo que usan listado y ficha).
    - ``schedule_time``: etiqueta común si todos los días comparten horario, o
      la de la única fila; vacía si el horario cambia según el día.
    - ``schedule_text``: el horario tal como lo publica la fuente, una parte
      por fila («17 octubre, 18 octubre i 19 octubre: de 09.00 h a 18.00 h · …»).
    """
    by_day = schedule_by_day(rows, start, end)
    labels = set(by_day.values()) - {''}
    parsed_rows = [parse_hours(r.get('hores')) for r in rows]
    if len(labels) == 1 and '' not in by_day.values() and (len(rows) == 1 or len({hours_label(p) for p in parsed_rows if p}) == 1):
        schedule_time = labels.pop()
    elif not by_day and len(rows) == 1 and parsed_rows[0]:
        schedule_time = hours_label(parsed_rows[0])
    else:
        schedule_time = ''
    if len(rows) == 1 and not rows[0].get('periode'):
        schedule_text = rows[0].get('hores', '')
    else:
        # Agrupado por periodo: «Del 4 juny al 2 agost: De dimarts a dissabte d'11:00 h a 18:00 h; Diumenge …»
        groups = []
        # Observaciones que cambian de fila en fila («Dilluns: passacarrers», «Dimarts: fira»): van con su día.
        own = len({r['observacions'] for r in rows if r.get('dies') and r.get('observacions')}) > 1
        for r in rows:
            line = ' '.join(x for x in (r.get('dies', ''), r.get('hores', '')) if x) if r.get('periode') else ': '.join(x for x in (r.get('dies', ''), r.get('hores', '')) if x)
            if own and r.get('observacions'): line += f" ({r['observacions']})"
            if groups and groups[-1][0] == r.get('periode', ''): groups[-1][1].append(line)
            else: groups.append((r.get('periode', ''), [line]))
        schedule_text = ' · '.join((f"{p}: " if p else '') + ('; ' if p else ' · ').join(lines) for p, lines in groups)
    facts = {}
    if rows:
        if len(rows) == 1 and rows[0].get('dies'): facts['schedule_days'] = rows[0]['dies']
        facts['schedule_hours'] = schedule_text
        prices = list(dict.fromkeys(r['preu'] for r in rows if r.get('preu')))
        if prices: facts['price_text'] = ' · '.join(prices)
        # El periodo ya va dentro del horario; aquí solo las observaciones.
        own = len({r['observacions'] for r in rows if r.get('dies') and r.get('observacions')}) > 1
        notes = [] if own else list(dict.fromkeys(r['observacions'] for r in rows if r.get('observacions')))
        if not any(r.get('periode') for r in rows[1:]) and rows[0].get('periode') and len(rows) == 1: notes.insert(0, rows[0]['periode'])
        if notes: facts['schedule_note'] = ' · '.join(notes)
    return {'by_day': by_day, 'schedule_time': schedule_time, 'schedule_text': schedule_text, 'facts': facts}


# Horario semanal en texto corrido, como lo da la Agenda Cultural de la Generalitat:
# «Dimarts: 20.30 h Dimecres i dijous: 20 h Divendres i dissabtes: 17 h i 21 h Diumenges: 16.30 h
#  Durada aproximada: 180 minuts». Cada «días: horas» es una fila.
_WEEKLY_HEAD = re.compile(
    r"(?:(?<=\s)|^)((?:(?:de|del|des\s+de|els|les|los|cada|tots|todos)\s+)?"
    r"(?:" + _WEEKDAY[1:-3] + r"|tots\s+els\s+dies|cada\s+dia|todos\s+los\s+d[ií]as)s?\b[^:.()]{0,60}):", re.I)
_WEEKLY_TAIL = re.compile(r"\b(?:durada|duración|duracion|durant|preu|precio|entrades|entradas|venda|horari\s+de\s+taquilla|taquilla)\b.*$", re.I | re.S)
_HOLIDAYS = re.compile(r"\s*(?:(?:,|\bi\b|\by\b)\s*(?:festius|festivos|vigílies(?:\s+de\s+festiu)?|vísperas(?:\s+de\s+festivo)?)|\s+no\s+festius|\s+no\s+festivos|\s+excepte\s+(?:els\s+)?festius|\s+excepto\s+festivos)\b", re.I)
# Temporada: «del 25 de setembre al 24 de juny», «de l'1 de novembre al 31 de març», «d'octubre a abril».
_SEASON = (r"(?:\bdel?\s+(?:l['’]\s*)?|\bd['’]\s*|\bde\s+)?(?:(\d{1,2})" + _OF + r")?" + _MONTH
           + r"\s+(?:al?|fins\s+al?)\s+(?:l['’]\s*)?(?:(\d{1,2})" + _OF + r")?" + _MONTH + r"\b")
_SEASON_HEAD = re.compile(r"(?:horari\s+d['’](?:hivern|estiu)\s*)?(?:\(\s*)?" + _SEASON + r"\s*\)?\s*:?", re.I)


def season_of(text):
    """((mes, día), (mes, día)) de una temporada que se repite cada año, o None."""
    m = re.search(_SEASON, str(text or '').casefold())
    if not m: return None
    return ((MONTHS[m.group(2)], int(m.group(1) or 1)), (MONTHS[m.group(4)], int(m.group(3) or 31)))


def in_season(day, season):
    (a, b), k = season, (day.month, day.day)
    a, b = tuple(a), tuple(b)
    return a <= k <= b if a <= b else (k >= a or k <= b)


def _block_rows(block, season):
    heads = list(_WEEKLY_HEAD.finditer(block))
    if not heads and not season:
        # Sin «:»: «els tercers dimecres de mes a les 20 h», «Dimecres, de 16.30 a 19.30 h».
        m = re.match(r"^(.+?),?\s+((?:a\s+les\b|a\s+las\b|de\s+(?:les\s+)?\d|d['’]\s*\d|des\s+de\b).*)$", block.strip(), re.I)
        return [{'dies': m.group(1), 'hores': _WEEKLY_TAIL.sub('', m.group(2)).strip(' .;,')}] if m and re.search(_WEEKDAY[1:-3] + '|dia|mes', m.group(1), re.I) else None
    if not heads:
        # «Horari d'estiu (de l'1 d'abril al 31 d'octubre) De 10 h a 20 h»: todos los días de la temporada.
        hours = _WEEKLY_TAIL.sub('', block).strip(' .;,')
        return [{'dies': 'cada dia', 'hores': hours, 'season': season}] if season and parse_hours(hours) else None
    if block[:heads[0].start()].strip(' .;,'):
        return None
    rows = []
    for n, head in enumerate(heads):
        hours = block[head.end(): heads[n + 1].start() if n + 1 < len(heads) else len(block)]
        hours = _WEEKLY_TAIL.sub('', hours).strip(' .;,')
        days = head.group(1).strip()
        if not hours: return None
        # Horas por temporada dentro de la fila: «d'11 a 19.30 h (del 25 de setembre al 24 de juny) i de 10 a 20 h (del 25 de juny…)».
        parts = [(m.start(), m.end(), season_of(m.group(1))) for m in re.finditer(r"\(([^)]*)\)", hours)]
        parts = [x for x in parts if x[2]]
        if parts and not season:
            last = 0
            for a, b, inner in parts:
                rows.append({'dies': days, 'hores': hours[last:a].strip(' .;,') or '?', 'season': inner}); last = b
                hours_left = re.sub(r"^\s*(?:i|y|;|,)\s*", '', hours[last:]); last = len(hours) - len(hours_left)
            if hours[last:].strip(' .;,'): return None
            continue
        if re.search(r"\d{1,2}" + _OF + _MONTH, hours, re.I) and not re.search(r"excepte|excepto|tancat", hours, re.I):
            hours = '?'   # otras fechas mezcladas en la hora: ese día hay actividad, la hora no se afirma
        rows.append({'dies': days, 'hores': hours, **({'season': season} if season else {})})
    return rows


def weekly_rows(text):
    """Filas {dies, hores[, season]} de un horario semanal en texto corrido, o [] si no tiene esa forma.

    Solo se aceptan textos que son enteramente «días: horas», opcionalmente en bloques
    de temporada («Horari d'hivern (de l'1 de novembre al 31 de març): …»). «i festius»
    se quita de los días: los festivos no se pueden fechar, pero el domingo sí; el texto
    original sigue en la ficha. «12 h o 17 h» son dos pases."""
    source = ' '.join(str(text or '').split())
    # «Diumenge: 22 de novembre: 18 h»: la fecha va con el día, no con la hora.
    source = re.sub(r"\b(" + _WEEKDAY[1:-3] + r")s?:\s+(\d{1,2}\s+(?:de\s+|d['’]\s*)" + _MONTH + r")\s*:", r"\1 \2:", source, flags=re.I)
    # «… de 10 a 19 h Dilluns tancat»: también es una fila.
    source = re.sub(r"(?<=\s)(" + _WEEKDAY[1:-3] + r")s?\s+(tancat|tancada|cerrado|cerrada)\b", r"\1: \2", source, flags=re.I)
    marks = [m for m in _SEASON_HEAD.finditer(source)
             if m.group(0).rstrip().endswith((':', ')')) and (m.start() == 0 or source[m.start() - 1] in ' .;')
             and not re.search(r"\(\s*$", source[:m.start()])]
    # Una temporada solo es cabecera de bloque si va al principio o tras el bloque anterior.
    blocks = []
    if marks and not source[:marks[0].start()].strip(' .;,'):
        for n, m in enumerate(marks):
            body = source[m.end(): marks[n + 1].start() if n + 1 < len(marks) else len(source)]
            blocks.append((body, season_of(m.group(0))))
    else:
        blocks = [(source, None)]
    rows = []
    for body, season in blocks:
        got = _block_rows(body, season)
        if got is None: return []
        rows += got
    return rows


_NOT_ACTIVITY = re.compile(r"^\s*(?:grup|grupo|horari|horario|torn|sessió\s+\d|cal\s+inscripci|inscripci|places|plazas|aforament|aforo|entrada|l['’]entrada|informació|información|preu|precio|iniciació|avançat|nivell|sala\b|a\s+la\s+sala|cotxeres|casinet)|\bsala\s+\d|\banys\b|\baños\b", re.I)


def notes_by_day(rows, start, end):
    """{fecha ISO: actividad} cuando cada fila trae su propia observación
    («Dilluns: passacarrers», «Dijous: vermut comunitari»). Una nota común a todo el
    evento no se reparte por días: va en la ficha."""
    start, end = _date(start), _date(end)
    # Solo programas cortos (una semana de fiesta, unas jornadas): en cursos de meses las
    # observaciones son grupos y salas («Grup A», «Cotxeres-C (sala 9)»), no la actividad del día.
    if not start or not end or (end - start).days > 21:
        return {}
    rows = [{**r, 'observacions': ' · '.join(x for x in str(r.get('observacions') or '').split(' · ') if x and not _NOT_ACTIVITY.search(x))} for r in rows]
    if len({r['observacions'] for r in rows if r.get('dies') and r.get('observacions')}) < 2:
        return {}
    out, days = {}, None
    for row in rows:
        if row.get('dies'):
            days = parse_days(_HOLIDAYS.sub('', row['dies']), start, end)
            within = period_days(row, start, end)
            if days is not None and within is not None: days = days & within
            if days is not None and row.get('season'): days = {d for d in days if in_season(d, row['season'])}
        note = row.get('observacions')
        if not note or not days or CLOSED.match(row.get('hores') or ''): continue
        for d in days:
            items = out.setdefault(d.isoformat(), [])
            if note not in items: items.append(note)
    return {k: ' · '.join(v) for k, v in sorted(out.items())}


def dated_outside(rows, start, end, margin=14):
    """Fechas concretas del detalle que caen fuera de las fechas del listado.

    El listado de GuiaBCN a veces recorta el periodo («17–23 octubre») mientras el detalle
    dice «16 octubre i 24 octubre: a les 17.30 h». Solo cuentan las filas con fechas
    escritas (con mes y sin días de la semana), nunca «Dissabte» o «cada dia», que se
    extenderían a días que nadie ha anunciado. Devuelve {fecha: hora} fuera de [start, end]."""
    a, b = _date(start), _date(end)
    if not a or not b: return {}
    explicit = [r for r in rows if r.get('dies') and re.search(_MONTH, r['dies'].casefold())
                and not re.search(r'\b' + _WEEKDAY + r'\b', r['dies'].casefold()) and not r.get('periode')
                and not re.search(r"\b(?:del?|de\s+l['’])\s*\d.*\b(?:al?|a\s+l['’])\s*\d", r['dies'].casefold())   # rangos: no
                and not re.search(r"\b(?:cada|tots|todos|excepte|excepto)\b", r['dies'].casefold())]
    if not explicit: return {}
    wide = schedule_by_day(explicit, a - dt.timedelta(days=margin), b + dt.timedelta(days=margin))
    return {k: v for k, v in wide.items() if not (a.isoformat() <= k <= b.isoformat())}


_NO_SHOW = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s+(?:no\s+hay\s+funci|no\s+hi\s+ha\s+funci|sin\s+funci|sense\s+funci|no\s+hi\s+ha\s+sessi|no\s+hay\s+sesi)", re.I)
_ONE_SHOW = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s*(?:,|-|–)?\s*(?:a\s+las|a\s+les|at)\s+(\d{1,2})[.:](\d{2})", re.I)
_TIME_JOIN = re.compile(r"\s+(?:a\s+las|a\s+les|at)\s+", re.I)


def lines_schedule(text, start, end):
    """{fecha ISO: horas} de un horario de sala en líneas (Teatre Lliure, 20-10-2026):
    «De miércoles a viernes a las 19.30 h», «Sábados a las 17.00 h y a las 20.30 h»,
    «28/11 no hay función», «Función escolar / 25/11 a las 10.30 h». Solo lo que dice el texto."""
    s0, e0 = _date(start), _date(end)
    if not s0 or not e0: return {}
    def dated(day, month):
        for year in sorted({s0.year, e0.year}):
            try:
                d = dt.date(year, int(month), int(day))
            except ValueError:
                continue
            if s0 <= d <= e0: return d.isoformat()
        return None
    weekly, skip, extra = [], set(), {}
    for line in str(text or '').split('\n'):
        line = ' '.join(line.split())
        if not line: continue
        m = _NO_SHOW.match(line)
        if m:
            d = dated(m.group(1), m.group(2))
            if d: skip.add(d)
            continue
        m = _ONE_SHOW.match(line)
        if m:
            d = dated(m.group(1), m.group(2))
            if d: extra.setdefault(d, []).append(f'{int(m.group(3)):02d}:{m.group(4)}')
            continue
        if re.match(r"(?:de\s+|del\s+|els\s+|los\s+)?" + _WEEKDAY, line, re.I) and _TIME_JOIN.search(line):
            weekly.append(_TIME_JOIN.sub(': ', line, count=1))
    rows = weekly_rows('. '.join(weekly)) if weekly else []
    hours = schedule_by_day(rows, start, end) if rows else {}
    for d in skip: hours.pop(d, None)
    for d, times in extra.items():
        current = [x for x in (hours.get(d) or '').split(' · ') if x]
        hours[d] = ' · '.join(sorted(set(current + times)))
    return dict(sorted(hours.items()))
