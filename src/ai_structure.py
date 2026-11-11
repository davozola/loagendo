"""Estructura de las fichas largas con IA (2-11-2026, David).

Casos difíciles: una ficha de varios días que en realidad es una exposición o instalación
(«By the stream», que la fuente da como espectáculo) y que además anuncia actos con día y hora
dentro del texto (performance, taller, inauguración, visita guiada). El extractor de datos
(src/ai_extract.py) solo pregunta por fichas de 4 días o menos, así que esos actos no salían.

Para las fichas de 7 días o más que pasan un filtro por reglas, la IA devuelve el formato y la
categoría de la ficha en su conjunto y las sesiones sueltas, todo con cita literal. Aquí se
comprueba sin IA (la cita está en el texto, el día y la hora se leen en la cita, la fecha cae
dentro de la ficha) y se decide qué se aplica solo:

  · sesiones comprobadas: siempre. Cada una pasa a ser un acto de un día (fuente
    ``venue_ia_sesiones``) enlazado a su ficha madre, con su propia fila en la agenda de ese día.
    No se crea si ese día ya hay en el mismo sitio un acto que es el mismo (misma hora o título).
    Lo que deja de salir no se borra: deja de publicarse y queda anotado.
  · formato y categoría: solo con confianza alta; nunca pasa a exposición una ficha cuyo título
    nombra una actividad («Visites guiades a l'exposició…»); pasar a exposición exige que la cita
    hable de exposición o instalación; la categoría solo cambia con el paso a exposición o cuando
    las reglas no estaban seguras. Lo demás queda como sugerencia para revisar. La corrección
    editorial siempre manda.

Modelo Sonnet (prueba del 2-11-2026 con 30 fichas, scripts/prueba_estructura_ia.py: 4 de 4
cambios de formato correctos, 0 errores y 23 de 23 sesiones; Haiku perdía la mitad de las
sesiones y daba por exposición unas visitas guiadas). Pocas fichas al día: llamada directa, no
lote, para poder reintentar si el modelo no admite forzar la herramienta.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.error

from src.ai_extract import day_ok, fold, quote_in, time_ok

MODEL = 'claude-sonnet-5-5'
PROMPT_VERSION = 2
SOURCE = 'venue_ia_sesiones'
SLUG = 'ia_sesiones'
LABEL = 'Sesión de la ficha'
MIN_DAYS = 7
MIN_TEXT = 80
MAX_TEXT = 3000
CHUNK = 8
MAX_PER_RUN = 48          # fichas por pasada del motor (la primera vez hay ~180; luego, unas pocas al día)
CONFIDENCE = {'alta': 0.9, 'media': 0.6, 'baja': 0.3}
APPLY = 0.85
SKIP_FORMATS = {'workshop', 'course'}

FORMATS = ['exhibition', 'program', 'one_shot', 'workshop', 'course', 'festival', 'ongoing']
FORMAT_LABELS = {'one_shot': 'Actos y funciones', 'workshop': 'Talleres', 'course': 'Cursos', 'program': 'Ciclos y programas',
                 'festival': 'Festivales', 'exhibition': 'Exposiciones', 'ongoing': 'Actividades continuadas'}
CATEGORIES = ['musica', 'escena', 'cine', 'arte', 'visitas', 'charlas', 'talleres', 'fiestas']
SESSION_TYPES = ['inauguracion', 'performance', 'taller', 'charla', 'visita', 'concierto', 'proyeccion', 'espectaculo', 'presentacion',
                 'recital', 'lectura', 'clausura', 'otro']
TYPE_LABEL = {'inauguracion': 'Inauguració', 'performance': 'Performance', 'taller': 'Taller', 'charla': 'Xerrada', 'visita': 'Visita guiada',
              'concierto': 'Concert', 'proyeccion': 'Projecció', 'espectaculo': 'Espectacle', 'presentacion': 'Presentació', 'recital': 'Recital',
              'lectura': 'Lectura', 'clausura': 'Cloenda', 'otro': 'Activitat'}
# Categoría de trabajo con que entra el acto (la clasificación normal decide después por su título).
TYPE_CATEGORY = {'inauguracion': 'Arte y exposiciones', 'clausura': 'Arte y exposiciones', 'performance': 'Artes escénicas', 'espectaculo': 'Artes escénicas',
                 'taller': 'Talleres y experiencias', 'charla': 'Literatura y palabra', 'presentacion': 'Literatura y palabra', 'lectura': 'Literatura y palabra',
                 'concierto': 'Música y vida nocturna', 'proyeccion': 'Cine y audiovisual'}

EXPO_RX = re.compile(r"\b(instal[.l]*acio|instalacion|exposicio|exposicion|mostra|muestra)\b")
SESS_RX = re.compile(r"\b(performance|inauguracio|inauguracion|taller|xerrada|charla|conferencia|visita (guiada|comentada)|concert|concierto|presentacio|"
                     r"presentacion|taula rodona|mesa redonda|espectacle|projeccio|recital|clausura|cloenda)\b")
HOUR_RX = re.compile(r"\b([01]?\d|2[0-3])([:.]\d{2})?\s*h\b|\b([01]?\d|2[0-3]):\d{2}\b|\ba (les|las) \d")
# Título que nombra la actividad: la ficha ES esa actividad aunque pase en una exposición.
ACTIVITY_TITLE_RX = re.compile(r"^\W*(visita|visites|itinerari|itinerario|ruta|taller|tallers|curs|cursos|curso|presentacio|presentacion|xerrada|charla|"
                               r"conferencia|cicle|ciclo|concert|concierto|espectacle|projeccio)\b")

SYSTEM = """Ordenas fichas de actividades culturales de Barcelona que duran varios días. Recibes título, fechas (inicio y fin), sala, el formato y la categoría que tiene ahora y el texto de la fuente.
Devuelve, para cada ficha (n):
- formato: qué es la ficha en su conjunto, uno de exhibition (exposición o instalación que se puede visitar en horario de sala), program (ciclo o temporada de sesiones, visitas que se repiten), one_shot (acto o función), workshop (taller), course (curso de varias sesiones), festival (muestra o festival con varias compañías o artistas), ongoing (actividad continuada). Con cita literal del texto que lo justifica.
  · REGLA 1: si el título nombra una actividad (Visita, Visites guiades, Itinerari, Taller, Curs, Presentació, Xerrada, Cicle, Concert…), la ficha ES esa actividad aunque se haga dentro de una exposición: «Visites guiades a l'exposició X» es program/visitas, no exhibition/arte.
  · REGLA 2: si el texto dice que hay una instal·lació o exposició visitable durante un periodo («Instal·lació: del 22 d'octubre al 10 de novembre», «es pot visitar fins al…»), la ficha es exhibition aunque además tenga una performance o un taller: confianza alta, y cita esa frase.
  · Si dudas entre el formato actual y otro, deja el actual.
- categoria: una de musica, escena (teatro, danza, circo), cine, arte (exposiciones y arte), visitas, charlas (charlas, presentaciones, libros y lectura), talleres (talleres y cursos), fiestas. Es la de la ficha en su conjunto: una exposición es arte aunque incluya una performance; un curso es talleres aunque trate de literatura. Si dudas, deja la actual.
- sesiones: SOLO los actos sueltos que el texto anuncia con un día concreto dentro de las fechas de la ficha (inauguración, performance, taller, charla, visita guiada, concierto, recital, lectura…). Para cada uno: tipo; titulo: el nombre del acto copiado LITERAL del texto, SIN la fecha ni la hora (p. ej. «Taller-conversa amb Heidi Ramírez», «Lectura compartida de Naixem de dona, d'Adrienne Rich», «Inauguració»); fecha (AAAA-MM-DD); inicio y fin (HH:MM) si constan; y cita LITERAL donde se leen el día y la hora. No incluyas el horario general de apertura ni rangos de días; no deduzcas una fecha que no esté escrita.
- confianza: alta, media o baja; motivo: una frase.
Todo con citas copiadas literalmente del texto, sin cambiar nada: se comprueban automáticamente. Si algo no aparece, omítelo. No deduzcas ni completes. Responde SIEMPRE llamando a la herramienta estructura, con una entrada por ficha; no escribas texto aparte."""

_q = {'type': 'string'}
TOOL = {'name': 'estructura', 'description': 'Formato, categoría y sesiones de cada ficha, con citas literales.',
        'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'formato', 'categoria', 'confianza'], 'properties': {
                'n': {'type': 'integer'},
                'formato': {'type': 'object', 'properties': {'valor': {'type': 'string', 'enum': FORMATS}, 'cita': _q}},
                'categoria': {'type': 'string', 'enum': CATEGORIES},
                'sesiones': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'tipo': {'type': 'string', 'enum': SESSION_TYPES}, 'titulo': _q, 'fecha': _q, 'inicio': _q, 'fin': _q, 'cita': _q}}},
                'confianza': {'type': 'string', 'enum': ['alta', 'media', 'baja']},
                'motivo': {'type': 'string'}}}}}}}


# ---------- qué se pregunta ----------
def span_days(ev):
    try: return (dt.date.fromisoformat(str(ev.get('end'))[:10]) - dt.date.fromisoformat(str(ev.get('start'))[:10])).days
    except ValueError: return 0


def needs(ev):
    """Fichas de 7 días o más con texto propio que hablan de exposición o instalación, o que anuncian
    actos con hora dentro. Las sesiones creadas aquí no se vuelven a preguntar."""
    if ev.get('source') == SOURCE or span_days(ev) < MIN_DAYS: return False
    # Talleres y cursos (11-11-2026, consumo): eran el 82 % de lo preguntado (2.014 de 2.448, casi todos cursos trimestrales de
    # los centros cívicos de Open Data) y la respuesta fue siempre «taller/curso, sin sesiones sueltas». Con Sonnet era más de
    # la mitad del gasto diario de IA. Su horario ya lo dan las reglas; esta tarea es para exposiciones e instalaciones.
    if ((ev.get('structure_basis') or {}).get('format') or ev.get('format')) in SKIP_FORMATS: return False
    text = ev.get('source_text') or ''
    if len(text.strip()) < MIN_TEXT: return False
    t = fold((ev.get('title') or '') + '\n' + text)
    return bool(EXPO_RX.search(t) or (SESS_RX.search(t) and HOUR_RX.search(t)))


def payload(ev):
    """Lo que se le enseña. El formato y la categoría «actuales» son los de antes de aplicar esta
    tarea (structure_basis): si no, aplicar la respuesta cambiaría la huella y se volvería a preguntar."""
    basis = ev.get('structure_basis') or {}
    return {'titulo': (ev.get('source_title') or ev.get('title') or '')[:200], 'fechas': [str(ev.get('start') or '')[:10], str(ev.get('end') or '')[:10]],
            'sala': (ev.get('source_venue') or (ev.get('venue_names') or [''])[0] or '')[:100],
            'formato_actual': basis.get('format') or ev.get('format') or '', 'categoria_actual': basis.get('category') or ev.get('public_category') or '',
            'texto': (ev.get('source_text') or '')[:MAX_TEXT]}


# ---------- comprobación (sin IA) ----------
MONTHS = r"(gener|febrer|marc|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre|enero|febrero|marzo|mayo|junio|julio|agosto|septiembre|noviembre|diciembre)"
WEEKDAYS = r"(dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo)"
DATE_IN_TITLE_RX = re.compile(r"[\s:,.\-–(]*\b((el|la|els|les|dia|day)\s+)?(" + WEEKDAYS + r"\b|\d{1,2}\s+(de\s+|d')?" + MONTHS + r"\b|a les \d|a las \d|\d{1,2}([:.]\d{2})?\s*h\b).*$")
LEAD_DATE_RX = re.compile(r"^\W*(" + WEEKDAYS + r",?\s+)?\d{1,2}\s+(de\s+|d')?" + MONTHS + r"(\s+de\s+\d{4})?[\s.:,\-–]*")
GENERIC_TITLES = {'inauguracio', 'inauguracion', 'performance', 'taller', 'visita guiada', 'visita', 'recital', 'presentacio', 'presentacion', 'xerrada',
                  'charla', 'lectura', 'concert', 'cloenda', 'clausura'}


def fold_keep(text):
    """Como fold, pero letra a letra y sin cambiar la longitud: las posiciones valen para el original."""
    return ''.join((fold(c) or ' ')[:1] if c.strip() else ' ' for c in str(text or ''))


def session_title(raw, kind, parent):
    """Nombre del acto sin fecha ni hora; si queda genérico, «Tipo · Ficha». Nada redactado: sale del
    texto, o del tipo y el título de la ficha madre."""
    raw = str(raw or '').strip()
    lead = LEAD_DATE_RX.match(fold_keep(raw))
    if lead: raw = raw[lead.end():]                      # «13 d'abril de 2026. Cants I–IV» → «Cants I–IV»
    m = DATE_IN_TITLE_RX.search(fold_keep(raw))
    cut = raw[:m.start()] if m and m.start() > 0 else ('' if m else raw)
    cut = cut.strip(' :,.-–')
    for a, b in (('"', '"'), ("'", "'"), ('«', '»'), ('“', '”')):   # cierra la comilla que la fecha dejó abierta
        if a in cut and cut.count(a) + (cut.count(b) if a != b else 0) == 1: cut += b
    if len(cut) < 3: cut = TYPE_LABEL.get(kind, 'Activitat')
    if fold(cut) in GENERIC_TITLES: cut = f"{cut[0].upper()}{cut[1:]} · {parent}"
    return cut


def verify(row, pl):
    """(respuesta comprobada, descartes). ``pl`` es el payload que se le enseñó."""
    text = (pl.get('titulo') or '') + '\n' + (pl.get('texto') or '')
    start, end = (pl.get('fechas') or ['', ''])[:2]
    got, dropped = {'confidence': row.get('confianza') if row.get('confianza') in CONFIDENCE else 'baja', 'reason': str(row.get('motivo') or '')[:300]}, []
    f = row.get('formato') or {}
    if f.get('valor') in FORMATS and quote_in(f.get('cita') or '', text): got.update(format=f['valor'], format_quote=f['cita'])
    elif f.get('valor'): dropped.append(f"formato {f.get('valor')}: la cita no está en el texto")
    if row.get('categoria') in CATEGORIES: got['category'] = row['categoria']
    sessions = []
    for s in row.get('sesiones') or []:
        q, date, title = s.get('cita') or '', s.get('fecha') or '', s.get('titulo') or ''
        why = ('cita no está en el texto' if not quote_in(q, text) else
               'título no es literal' if not quote_in(title, text) else
               'fecha fuera de la ficha' if not (start <= date <= (end or start)) else
               'el día no se lee en la cita' if not day_ok(date, q) else
               'la hora no se lee en la cita' if s.get('inicio') and not time_ok(s['inicio'], q) else '')
        if why: dropped.append(f"sesión «{title[:50]}» {date} {s.get('inicio') or ''}: {why}"); continue
        kind = s.get('tipo') if s.get('tipo') in SESSION_TYPES else 'otro'
        sessions.append({'type': kind, 'title': session_title(title, kind, pl.get('titulo') or ''), 'raw_title': title.strip(), 'date': date,
                         'time': s.get('inicio') or '', 'end': s.get('fin') if s.get('fin') and time_ok(s['fin'], q) else '', 'quote': q})
    got['sessions'] = sessions; got['dropped'] = dropped
    return got, dropped


def parse(row, pl):
    """Para ai_assist._answers: (respuesta en JSON, confianza, motivo)."""
    got, dropped = verify(row, pl)
    return json.dumps(got, ensure_ascii=False), CONFIDENCE[got['confidence']], (got['reason'] + (f' · {len(dropped)} datos descartados por la comprobación' if dropped else ''))[:300]


def decide(answer, ev, rule_status='', editorial=False):
    """Qué se aplica solo y qué queda como sugerencia. ``ev`` con el formato y la categoría de antes."""
    out = {'format': None, 'category': None, 'suggested': {}}
    if not answer: return out
    high = CONFIDENCE.get(answer.get('confidence'), 0) >= APPLY
    activity_title = bool(ACTIVITY_TITLE_RX.search(fold(ev.get('source_title') or ev.get('title') or '')))
    f, cur_f = answer.get('format'), (ev.get('structure_basis') or {}).get('format') or ev.get('format')
    if f and f != cur_f:
        ok = high and not (activity_title and f == 'exhibition') and (f != 'exhibition' or EXPO_RX.search(fold(answer.get('format_quote') or '')))
        if ok: out['format'] = f
        else: out['suggested']['format'] = f
    c, cur_c = answer.get('category'), (ev.get('structure_basis') or {}).get('category') or ev.get('public_category')
    if c and c != cur_c:
        # Con el paso a exposición (el tipo de la fuente engañaba) o donde las reglas no estaban seguras.
        ok = high and not editorial and rule_status != 'excluida' and not (activity_title and c == 'arte') and (
            (out['format'] == 'exhibition' and c == 'arte') or rule_status in ('pendiente', 'probable'))
        if ok: out['category'] = c
        else: out['suggested']['category'] = c
    return out


# ---------- sesiones → actos de un día ----------
def _place(name):
    return fold(str(name or '').split(' · ')[0])


def _words(title):
    return {w for w in re.split(r'[^a-z0-9]+', fold(title)) if len(w) > 3}


def covered(session, parent, by_day):
    """El mismo acto ya está publicado ese día en el mismo sitio (Open Data publica a veces la
    inauguración aparte): misma hora, o título que comparte la mayoría de sus palabras."""
    place = _place((parent.get('venue_names') or [''])[0])
    words = _words(session['raw_title'] if fold(session['title']).split(' · ')[0] in GENERIC_TITLES else session['title'])
    for e in by_day.get(session['date'], []):
        if e['key'] == parent['key'] or e.get('source') == SOURCE or _place((e.get('venue_names') or [''])[0]) != place: continue
        times = {o.get('time') for o in e.get('occurrences') or [] if o.get('date') == session['date']} | {e.get('time')}
        if session['time'] and session['time'] in times: return e['key']
        other = _words(e.get('title') or '')
        if words and other and len(words & other) / min(len(words), len(other)) >= 0.6: return e['key']
    return None


def child_record(parent, s, answer_hash):
    """Ficha (forma de src.sync) de una sesión: un día, con su hora si consta, en el sitio de la ficha madre."""
    from src.venue_feeds import record_from_jsonld
    v0 = (parent.get('venues') or [{}])[0] if parent.get('venues') else {}
    name = (parent.get('venue_names') or [v0.get('name') or ''])[0] or v0.get('name') or ''
    location = {'@type': 'Place', 'name': name, 'address': {'@type': 'PostalAddress', 'streetAddress': v0.get('address') or '', 'addressLocality': 'Barcelona'}}
    if parent.get('coordinates'): location['geo'] = {'latitude': parent['coordinates']['lat'], 'longitude': parent['coordinates']['lon']}
    node = {'@type': 'Event', 'name': s['title'], 'url': parent.get('url') or '', 'location': location, 'description': s['quote'],
            'startDate': s['date'] + ('T' + s['time'] if s['time'] else ''), 'endDate': s['date'] + ('T' + s['end'] if s['end'] else ''),
            'x_sessions': [s['time']] if s['time'] else [], 'x_time_verified': bool(s['time'])}
    if parent.get('is_free'): node['offers'] = {'@type': 'Offer', 'price': 0}
    venue = {'slug': SLUG, 'name': name, 'type': 'culture', 'category': TYPE_CATEGORY.get(s['type'])}
    record = record_from_jsonld(venue, node, parent.get('url') or '')
    if not record: return None
    record['id'] = hashlib.sha256('\0'.join((SLUG, parent['key'], s['date'], s['time'], fold(s['title']))).encode()).hexdigest()[:24]
    record['raw']['loagendo']['source_label'] = parent.get('source_label') or LABEL
    record['raw']['ia_estructura'] = {'parent': parent['key'], 'parent_title': parent.get('title') or '', 'type': s['type'], 'quote': s['quote'],
                                      'raw_title': s['raw_title'], 'model': MODEL, 'prompt_version': PROMPT_VERSION, 'answer_hash': answer_hash}
    record['alerts'] = [a for a in record['alerts'] if a != 'VENUE_SCHEMA_ORG_EVENT'] + ['AI_EXTRACTED_VERIFIED', 'SESSION_OF_PARENT']
    record['evidence_level'] = 'parent_text_ai_verified'; record['time_evidence_field'] = 'ia_cita'
    return record


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS source_record_retirements (source TEXT NOT NULL, id TEXT NOT NULL, run_id INTEGER, retired_at TEXT NOT NULL,
      previous_eligibility TEXT, reason TEXT);
    CREATE TABLE IF NOT EXISTS ai_structure_skips (source TEXT NOT NULL, parent TEXT NOT NULL, date TEXT NOT NULL, title TEXT NOT NULL,
      covered_by TEXT NOT NULL, seen_at TEXT NOT NULL, PRIMARY KEY(parent, date, title));
    """)


def sync_sessions(conn, events, today=None):
    """Crea o actualiza los actos de un día de las sesiones vigentes y retira (sin borrar) los que ya
    no salen. ``events``: el listado (catalog.all_events)."""
    from mvp import catalog
    from src import ai_assist
    from src.sync import _upsert_record, initialize as init_sync, now_utc
    today = (today or catalog.today()).isoformat() if not isinstance(today, str) else today
    init_sync(conn); initialize(conn)
    by_day = {}
    for e in events:
        if catalog.is_public(e) and e.get('source') != SOURCE:
            for d in {e['start']} | {o.get('date') for o in e.get('occurrences') or [] if o.get('date')}: by_day.setdefault(d, []).append(e)
    with conn:
        run_id = conn.execute('INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)', (SOURCE, now_utc(), 'running', '0')).lastrowid
    records, skipped = [], []
    for parent in events:
        if parent.get('source') == SOURCE or not catalog.is_public(parent): continue
        s = ai_assist.structure_for(conn, parent['key'], parent)
        if not s: continue
        try: answer = json.loads(s['answer'])
        except ValueError: continue
        for x in answer.get('sessions') or []:
            if x['date'] < today: continue
            hit = covered(x, parent, by_day)
            if hit: skipped.append((parent['key'], x, hit)); continue
            r = child_record(parent, x, s['input_hash'])
            if r: records.append(r)
    seen = set(); records = [r for r in records if not (r['id'] in seen or seen.add(r['id']))]
    now = now_utc(); mutated = 0
    with conn:
        for r in records:
            mutated += int(_upsert_record(conn, run_id, r)[0])
            # Retirada antes y vuelve a salir (la ficha madre volvió a publicarse): se publica otra vez.
            if r['eligibility'] != 'exclude':
                conn.execute("UPDATE source_records SET eligibility=? WHERE source=? AND id=? AND eligibility='exclude'", (r['eligibility'], SOURCE, r['id']))
        for pkey, x, hit in skipped:
            conn.execute('INSERT INTO ai_structure_skips VALUES(?,?,?,?,?,?) ON CONFLICT(parent,date,title) DO UPDATE SET covered_by=excluded.covered_by,seen_at=excluded.seen_at',
                         (SOURCE, pkey, x['date'], x['title'], hit, now))
        # Lo que ya no sale (la ficha madre cambió o la sesión ahora está publicada por su fuente): deja de publicarse.
        retired = 0
        for rid, el in conn.execute("SELECT id, eligibility FROM source_records WHERE source=? AND end_date>=? AND eligibility<>'exclude'", (SOURCE, today)).fetchall():
            if rid in seen: continue
            conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source=? AND id=?", (SOURCE, rid))
            conn.execute('INSERT INTO source_record_retirements(source,id,run_id,retired_at,previous_eligibility,reason) VALUES(?,?,?,?,?,?)',
                         (SOURCE, rid, run_id, now, el, 'la sesión ya no sale de su ficha madre o ya la publica otra fuente'))
            retired += 1
        conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=0,rows_received=?,rows_mutated=?,warning_json=? WHERE id=?",
                     (now, len(records), mutated, json.dumps([f'{len(skipped)} sesiones ya publicadas por otra ficha', f'{retired} retiradas']), run_id))
    return {'sessions': len(records), 'mutated': mutated, 'skipped': len(skipped), 'retired': retired}


# ---------- llamadas ----------
def _body(chunk, model):
    listing = [{'n': n, **pl} for n, (_, pl) in enumerate(chunk)]
    return {'model': model, 'max_tokens': 900 * len(chunk) + 200,
            'system': [{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
            'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': TOOL['name']},
            'messages': [{'role': 'user', 'content': json.dumps(listing, ensure_ascii=False)}]}


def call(key, body, requester):
    """Haiku admite forzar la herramienta; Sonnet 5.5 razona por defecto y entonces la API no deja
    forzarla (400). Se reintenta como en weekly_audit: sin razonamiento previo («between_tools») y la
    herramienta en «auto»; si tampoco, razonamiento adaptativo con esfuerzo bajo y más margen."""
    from src import ai_assist
    tries = [body,
             {**body, 'tool_choice': {'type': 'auto'}, 'thinking': {'type': 'between_tools'}, 'output_config': {'effort': 'low'}},
             {**body, 'tool_choice': {'type': 'auto'}, 'output_config': {'effort': 'low'}, 'max_tokens': max(body['max_tokens'], 16000)}]
    errors = []
    for attempt in tries:
        try:
            with ai_assist.usage_label('estructura', attempt['model']):
                return requester('POST', f'{ai_assist.API}/messages', key, attempt, timeout=300)
        except urllib.error.HTTPError as err:
            errors.append(f"HTTP {err.code}: {err.read().decode('utf-8', 'replace')[:200] if hasattr(err, 'read') else ''}")
            if err.code != 400: break
    raise RuntimeError('; '.join(errors))


def run(conn, key, events, today, requester, model=MODEL, limit=MAX_PER_RUN):
    """Pregunta por las candidatas pendientes (hasta ``limit``), guarda las respuestas comprobadas y
    actualiza los actos de un día."""
    from src import ai_assist
    items = ai_assist.structure_candidates(conn, events, today)[:limit]
    stored, failed = 0, []
    for start in range(0, len(items), CHUNK):
        chunk = items[start:start + CHUNK]
        try: message = call(key, _body(chunk, model), requester)
        except RuntimeError as err: failed.append(str(err)); break
        stored += ai_assist._store(conn, 'estructura', chunk, ai_assist._answers('estructura', message, chunk), model, 'directo')
    if stored:
        from mvp import catalog
        catalog.invalidate_cache(); events = catalog.all_events(conn)
    sessions = sync_sessions(conn, events, today)
    return {'asked': len(items), 'stored': stored, 'failed': failed, **sessions}
