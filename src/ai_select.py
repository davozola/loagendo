"""«Selección Ontoca» con IA (20-10-2026; 28-10-2026, David: también para «Hoy» y para cada uno de los próximos días).

Para cada día de los próximos AHEAD_DAYS y cada alcance («day»: solo ese día; «week»: ese día y los seis siguientes), las
reglas proponen candidatos (``catalog.query_events(featured=True)``) y la IA elige SIZE con los criterios de
``config/ia_seleccion.md``. Lo que de verdad decide la calidad es qué candidatos ve: los TOP_POOL mejor puntuados (la
puntuación pesa el nivel de sala) más los INDIE_POOL mejores de salas que no son de referencia, con imagen y texto propios,
para que la IA pueda elegir pequeño y de barrio. Se comprueba la respuesta (fichas existentes, sin repetir, sin dos del
mismo festival o serie, como mucho MAX_PER_CAT por categoría). Desde el 30-10-2026 (David) ya no se completa con las
reglas: si la IA elige 6, salen 6; y devuelve aparte las «populares» (grandes citas de mucho público que no elige), que
la web marca como «Popular» sin decir que las hemos elegido.
Una llamada por día y alcance mientras no cambien los criterios; queda guardado en ``ai_selection`` con candidatos,
elegidas, motivos, modelo y criterios. Las reglas de la web ordenan después por hora y quitan lo pasado.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZE = 10
TOP_POOL, INDIE_POOL = 50, 50   # mitad de salas que no son de referencia (30-10-2026)
CANDIDATES = TOP_POOL + INDIE_POOL
MAX_PER_CAT = 3
AHEAD_DAYS = 7          # hoy y los siete días siguientes, en los dos alcances (carrusel «Hoy» y «7 días»)
FAR_DAYS = 30           # 30-10-2026, David: hasta 30 días vista, solo el alcance «día» (las filas «Selección Ontoca» de cada día)
FAR_REFRESH_DAYS = 3    # un día lejano se vuelve a elegir cada 3 días (las salas siguen publicando)
REFERENCE_TIER = 12     # config/venue_prestige.json: equipamientos de referencia
PROMPT_VERSION = 4          # 3 (30-10-2026): calidad antes que popularidad, sin relleno, «populares» aparte; 4: «mas» para los tipos del carrusel
MAX_EXTRA = 40
PER_TYPE = 6
MIN_SIZE = 3            # 30-10-2026: con menos de 3 elegidas queda la selección de reglas; con 3 o 4 salen esas (mejor menos y mejores)
MAX_POPULAR = 8
SCOPES = ('day', 'week')

SYSTEM = """Eres el editor de Ontoca, agenda cultural de Barcelona. Eliges la «Selección Ontoca» entre los candidatos que recibes (lista JSON con n, título, categoría, canales, fecha, hora, sala, barrio, gratis, tipo, cartel, extracto y si la sala es grande o pequeña).
Responde con la herramienta seleccionar: entre 5 y 10 elegidas (cada una con su n y un motivo de como máximo 12 palabras); aparte, hasta 8 populares (solo su n), según los criterios; y en «mas», hasta 40 n más que también recomendarías con el mismo criterio de las elegidas (para el filtro por tipo del carrusel: hasta 6 por categoría, si las hay buenas; nunca populares ni nada de la lista de «no»).
Usa solo los datos de cada ficha; no inventes."""

TOOL = {'name': 'seleccionar', 'description': 'La Selección Ontoca (entre 5 y 10) y las grandes citas populares que no se eligen.',
        'input_schema': {'type': 'object', 'required': ['elegidas', 'populares'], 'properties': {
            'elegidas': {'type': 'array', 'items': {'type': 'object', 'required': ['n', 'motivo'],
                                                    'properties': {'n': {'type': 'integer'}, 'motivo': {'type': 'string'}}}},
            'populares': {'type': 'array', 'items': {'type': 'integer'}},
            'mas': {'type': 'array', 'items': {'type': 'integer'}}}}}


def guide():
    try: return (ROOT / 'config' / 'ia_seleccion.md').read_text(encoding='utf-8').strip()
    except OSError: return ''


def version():
    return f"{PROMPT_VERSION}-{hashlib.sha256(guide().encode()).hexdigest()[:8]}"


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_selection (
      day TEXT PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
      candidates_json TEXT NOT NULL, picks_json TEXT NOT NULL, usage_json TEXT)""")
    cols = {r[1] for r in conn.execute('PRAGMA table_info(ai_selection)')}
    if 'scope' not in cols:   # 28-10-2026: un alcance por fila («day» o «week»); las filas antiguas eran de la semana
        conn.executescript("""CREATE TABLE ai_selection_new (day TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'week', created_at TEXT NOT NULL,
            model TEXT NOT NULL, prompt_version TEXT NOT NULL, candidates_json TEXT NOT NULL, picks_json TEXT NOT NULL, usage_json TEXT, PRIMARY KEY(day, scope));
          INSERT INTO ai_selection_new(day,scope,created_at,model,prompt_version,candidates_json,picks_json,usage_json)
            SELECT day,'week',created_at,model,prompt_version,candidates_json,picks_json,usage_json FROM ai_selection;
          DROP TABLE ai_selection; ALTER TABLE ai_selection_new RENAME TO ai_selection;""")
    # 30-10-2026: las «populares» que la IA marca aparte (grandes citas que no elige).
    if 'popular_json' not in {r[1] for r in conn.execute('PRAGMA table_info(ai_selection)')}: conn.execute('ALTER TABLE ai_selection ADD COLUMN popular_json TEXT')
    # 30-10-2026: más elegidas con el mismo criterio, para el filtro por tipo del carrusel (Música, Teatro…).
    if 'extra_json' not in {r[1] for r in conn.execute('PRAGMA table_info(ai_selection)')}: conn.execute('ALTER TABLE ai_selection ADD COLUMN extra_json TEXT')


def _work(e):
    """La obra o el festival al que pertenece una ficha: dos sesiones de lo mismo no van las dos en la selección."""
    fest = (e.get('festival') or {}).get('slug') if isinstance(e.get('festival'), dict) else None
    return fest or e.get('series') or (e.get('title') or '').strip().lower()


def candidates(conn, day, scope='week'):
    """Los TOP_POOL mejor puntuados y, además, los INDIE_POOL mejores de salas que no son de referencia (con imagen y texto
    propios), para que la selección no sea solo grandes equipamientos y música."""
    from mvp import catalog
    kw = {'featured_days': 1} if scope == 'day' else {}
    items = catalog.query_events(conn, day=day, featured=True, public=True, page_size=400, **kw)['items']
    usable = [e for e in items if (e.get('media') or e.get('has_description')) and not e.get('is_promo')]
    top = usable[:TOP_POOL]
    seen = {e['key'] for e in top}
    indie = [e for e in usable if e['key'] not in seen and (e.get('venue_tier') or 0) < REFERENCE_TIER and e.get('media') and e.get('has_description')][:INDIE_POOL]
    return top + indie


def _venue(e):
    """La sala, sin la sala interior («Palau de la Música Catalana · Sala Petit» = Palau): no se repite en la selección (30-10-2026)."""
    import re
    return re.split(r'\s+[·–-]\s+', str((e.get('venue_names') or [''])[0]).strip().lower())[0]


def _payload(n, e):
    return {'n': n, 'titulo': e['title'][:160], 'categoria': e.get('public_category'), 'canales': e.get('channels') or [],
            'fecha': e.get('featured_date') or e['start'], 'hora': e.get('time') or '', 'sala': (e.get('venue_names') or [''])[0][:80],
            'sala_grande': (e.get('venue_tier') or 0) >= REFERENCE_TIER, 'barrio': e.get('district') or '', 'gratis': bool(e.get('is_free')),
            'tipo': e.get('kind'), 'cartel': (e.get('lineup') or [])[:5], 'extracto': (e.get('summary') or '')[:200]}


def pick(rows, items, size=SIZE):
    """Comprueba la respuesta: [(n, tipo, motivo)] → [(item, tipo, motivo)]. Sin repetir ficha ni obra o festival, como mucho
    MAX_PER_CAT por categoría. Sin cuotas (28-10-2026) y sin relleno con las reglas (30-10-2026, David): mejor menos y mejores."""
    out, seen, works, per_cat, venues = [], set(), set(), {}, set()
    def ok(n):
        if not (isinstance(n, int) and 0 <= n < len(items)) or n in seen: return False
        e = items[n]
        return per_cat.get(e.get('public_category'), 0) < MAX_PER_CAT and _work(e) not in works and (not _venue(e) or _venue(e) not in venues)
    def add(n, kind, why):
        e = items[n]; out.append((e, kind, why)); seen.add(n); works.add(_work(e)); per_cat[e.get('public_category')] = per_cat.get(e.get('public_category'), 0) + 1
        if _venue(e): venues.add(_venue(e))
    for n, kind, why in rows:
        if len(out) >= size: break
        if ok(n): add(n, kind, why)
    return out[:size]


def populars(ns, items, chosen):
    """Las «populares» de la respuesta: fichas existentes, sin las elegidas ni repetir obra, como mucho MAX_POPULAR."""
    out, works = [], {_work(e) for e, _, _ in chosen}
    for n in ns:
        if len(out) >= MAX_POPULAR: break
        if isinstance(n, int) and 0 <= n < len(items) and _work(items[n]) not in works:
            out.append(items[n]); works.add(_work(items[n]))
    return out


def stale(created_at, day, today):
    """Una selección hecha hay que repetirla (30-10-2026): si el día está lejos (más de AHEAD_DAYS) y tiene más de
    FAR_REFRESH_DAYS días, o si el día ya entró en la semana pero se eligió cuando aún estaba lejos."""
    try: made = dt.datetime.fromisoformat(created_at).date(); d = dt.date.fromisoformat(day)
    except (TypeError, ValueError): return True
    if (d - today).days > AHEAD_DAYS: return (today - made).days >= FAR_REFRESH_DAYS
    return (d - made).days > AHEAD_DAYS


def ensure(conn, key, day=None, scope='week', model=None, requester=None, today=None):
    """Calcula la selección de un día y alcance si no está hecha con los criterios vigentes o se ha quedado vieja."""
    from mvp import catalog
    from src import ai_assist
    initialize(conn); day = day or catalog.today().isoformat(); model = model or ai_assist.MODEL
    today = today or catalog.today()
    row = conn.execute('SELECT prompt_version, created_at FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    if row and row[0] == version() and not stale(row[1], day, today): return {'status': 'already_done', 'day': day, 'scope': scope}
    items = candidates(conn, day, scope)
    if len(items) < SIZE: return {'status': 'skipped', 'reason': 'pocos candidatos', 'day': day, 'scope': scope}
    with ai_assist.usage_label('seleccion', f'{day} {scope}'):
        message = (requester or ai_assist._request)('POST', f'{ai_assist.API}/messages', key, request_body(items, day, scope, model), timeout=180)
    chosen, popular, extra = parse(message, items, with_extra=True)
    picks = [{'key': e['key'], 'title': e['title'], 'tipo': kind, 'motivo': why} for e, kind, why in chosen]
    pops = [{'key': e['key'], 'title': e['title']} for e in popular]
    extras = [{'key': e['key'], 'title': e['title']} for e in extra]
    if len(picks) < MIN_SIZE: return {'status': 'skipped', 'reason': f'la IA eligió {len(picks)} (mínimo {MIN_SIZE})', 'day': day, 'scope': scope, 'usage': message.get('usage') or {}}
    with conn:
        conn.execute("""INSERT INTO ai_selection(day,scope,created_at,model,prompt_version,candidates_json,picks_json,usage_json,popular_json,extra_json) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(day,scope) DO UPDATE SET created_at=excluded.created_at,model=excluded.model,prompt_version=excluded.prompt_version,
            candidates_json=excluded.candidates_json,picks_json=excluded.picks_json,usage_json=excluded.usage_json,popular_json=excluded.popular_json,extra_json=excluded.extra_json""",
                     (day, scope, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), model, version(),
                      json.dumps([e['key'] for e in items]), json.dumps(picks, ensure_ascii=False), json.dumps(message.get('usage') or {}),
                      json.dumps(pops, ensure_ascii=False), json.dumps(extras, ensure_ascii=False)))
    return {'status': 'completed', 'day': day, 'scope': scope, 'picks': [p['title'][:50] for p in picks], 'populares': [p['title'][:50] for p in pops], 'usage': message.get('usage') or {}}


def request_body(items, day, scope, model):
    listing = [_payload(n, e) for n, e in enumerate(items)]
    ask = SYSTEM + '\n\n' + guide() + ('\n\nAlcance: solo el día ' + day + '. Reparte las elegidas entre mañana, tarde y noche si hay con qué.' if scope == 'day'
                                         else '\n\nAlcance: del ' + day + ' a los seis días siguientes. Reparte días.')
    return {'model': model, 'max_tokens': 3000,
            'system': [{'type': 'text', 'text': ask, 'cache_control': {'type': 'ephemeral'}}],
            'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'seleccionar'},
            'messages': [{'role': 'user', 'content': json.dumps(listing, ensure_ascii=False)}]}


def _ints(values):
    out = []
    for x in values or []:
        x = x.get('n') if isinstance(x, dict) else x
        try: out.append(int(x))
        except (TypeError, ValueError): continue
    return out


def extras(ns, items, chosen, popular):
    """Las «mas» de la respuesta: fichas existentes, sin elegidas, populares ni obras repetidas; como mucho PER_TYPE por categoría."""
    out, works, per_cat = [], {_work(e) for e, _, _ in chosen} | {_work(e) for e in popular}, {}
    for n in ns:
        if len(out) >= MAX_EXTRA or not (0 <= n < len(items)): continue
        e = items[n]; c = e.get('public_category')
        if _work(e) in works or per_cat.get(c, 0) >= PER_TYPE: continue
        out.append(e); works.add(_work(e)); per_cat[c] = per_cat.get(c, 0) + 1
    return out


def parse(message, items, with_extra=False):
    """(elegidas comprobadas, populares comprobadas[, «mas» comprobadas]) de la respuesta de la IA."""
    rows, pops, mas = [], [], []
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use':
            data = block.get('input') or {}
            for r in data.get('elegidas') or []:
                try: rows.append((int(r['n']), 'seleccion', str(r.get('motivo') or '')[:200]))
                except (KeyError, TypeError, ValueError): continue
            # A veces llegan como {"n": 3} o "3" en vez de 3 (30-10-2026: cinco días sin populares por eso).
            pops = _ints(data.get('populares')); mas = _ints(data.get('mas'))
    chosen = pick(rows, items)
    popular = populars(pops, items, chosen)
    return (chosen, popular, extras(mas, items, chosen, popular)) if with_extra else (chosen, popular)


def ensure_ahead(conn, key, model=None, requester=None, today=None, ahead=AHEAD_DAYS):
    """Las selecciones de hoy y de los próximos días, en los dos alcances. Resumen con las llamadas hechas y el uso."""
    from mvp import catalog
    today = today or catalog.today()
    out, usage = [], {}
    for offset in range(max(ahead, FAR_DAYS) + 1):
        day = (today + dt.timedelta(days=offset)).isoformat()
        for scope in (SCOPES if offset <= ahead else ('day',)):   # más allá de la semana, solo «día»: el carrusel no lo usa
            r = ensure(conn, key, day=day, scope=scope, model=model, requester=requester, today=today)
            out.append(r)
            for k, v in (r.get('usage') or {}).items():
                if isinstance(v, int): usage[k] = usage.get(k, 0) + v
    return {'status': 'completed', 'calls': sum(1 for r in out if r['status'] == 'completed'), 'days': max(ahead, FAR_DAYS) + 1, 'usage': usage,
            'skipped': [(r['day'], r['scope'], r.get('reason')) for r in out if r['status'] == 'skipped']}


MANUAL_PATH = ROOT / 'config' / 'seleccion_manual.json'


def _window(day, scope):
    d = dt.date.fromisoformat(day)
    return [day] if scope == 'day' else [(d + dt.timedelta(days=i)).isoformat() for i in range(7)]


def pinned_for(day, scope='week', path=None):
    """Fichas fijadas a mano en la Selección (config/seleccion_manual.json, 30-10-2026) con algún día dentro del alcance."""
    try: rows = json.loads(Path(path or MANUAL_PATH).read_text(encoding='utf-8')).get('fijadas') or []
    except (OSError, ValueError): return []
    win = set(_window(day, scope))
    return [str(r['ficha']) for r in rows if r.get('ficha') and win & set(r.get('dias') or [])]


def pinned_day(key, day, scope='week', path=None):
    """El primer día fijado de esa ficha dentro del alcance (para la fecha de la tarjeta)."""
    try: rows = json.loads(Path(path or MANUAL_PATH).read_text(encoding='utf-8')).get('fijadas') or []
    except (OSError, ValueError): return day
    win = _window(day, scope)
    days = sorted(d for r in rows if str(r.get('ficha')) == key for d in (r.get('dias') or []) if d in win)
    return days[0] if days else day


def picks_for(conn, day, scope='week'):
    """Claves de la Selección para ese día y alcance, en orden: primero las fijadas a mano y después las de la IA."""
    pins = pinned_for(day, scope)
    try: row = conn.execute('SELECT picks_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    except Exception: row = None
    return pins + [k for k in ([p['key'] for p in json.loads(row[0])] if row else []) if k not in pins]


def extras_for(conn, day, scope='week'):
    """Claves de las «mas» (más elegidas con el mismo criterio, para el filtro por tipo del carrusel) o []."""
    try: row = conn.execute('SELECT extra_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    except Exception: return []
    return [p['key'] for p in json.loads(row[0])] if row and row[0] else []


def populars_for(conn, day, scope='week'):
    """Claves de las «populares» de ese día y alcance (30-10-2026) o []."""
    try: row = conn.execute('SELECT popular_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    except Exception: return []
    pins = set(pinned_for(day, scope))
    return [p['key'] for p in json.loads(row[0]) if p['key'] not in pins] if row and row[0] else []
