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
AHEAD_DAYS = 7          # hoy y los siete días siguientes, en los dos alcances: 16 llamadas al día como mucho
REFERENCE_TIER = 12     # config/venue_prestige.json: equipamientos de referencia
PROMPT_VERSION = 3          # 3 (30-10-2026): calidad antes que popularidad, sin relleno, «populares» aparte
MIN_SIZE = 5
MAX_POPULAR = 8
SCOPES = ('day', 'week')

SYSTEM = """Eres el editor de Ontoca, agenda cultural de Barcelona. Eliges la «Selección Ontoca» entre los candidatos que recibes (lista JSON con n, título, categoría, canales, fecha, hora, sala, barrio, gratis, tipo, cartel, extracto y si la sala es grande o pequeña).
Responde con la herramienta seleccionar: entre 5 y 10 elegidas (cada una con su n y un motivo de como máximo 12 palabras) y, aparte, hasta 8 populares (solo su n), según los criterios.
Usa solo los datos de cada ficha; no inventes."""

TOOL = {'name': 'seleccionar', 'description': 'La Selección Ontoca (entre 5 y 10) y las grandes citas populares que no se eligen.',
        'input_schema': {'type': 'object', 'required': ['elegidas', 'populares'], 'properties': {
            'elegidas': {'type': 'array', 'items': {'type': 'object', 'required': ['n', 'motivo'],
                                                    'properties': {'n': {'type': 'integer'}, 'motivo': {'type': 'string'}}}},
            'populares': {'type': 'array', 'items': {'type': 'integer'}}}}}


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


def ensure(conn, key, day=None, scope='week', model=None, requester=None):
    """Calcula la selección de un día y alcance si no está hecha con los criterios vigentes. Devuelve un resumen."""
    from mvp import catalog
    from src import ai_assist
    initialize(conn); day = day or catalog.today().isoformat(); model = model or ai_assist.MODEL
    row = conn.execute('SELECT prompt_version FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    if row and row[0] == version(): return {'status': 'already_done', 'day': day, 'scope': scope}
    items = candidates(conn, day, scope)
    if len(items) < SIZE: return {'status': 'skipped', 'reason': 'pocos candidatos', 'day': day, 'scope': scope}
    message = (requester or ai_assist._request)('POST', f'{ai_assist.API}/messages', key, request_body(items, day, scope, model), timeout=180)
    chosen, popular = parse(message, items)
    picks = [{'key': e['key'], 'title': e['title'], 'tipo': kind, 'motivo': why} for e, kind, why in chosen]
    pops = [{'key': e['key'], 'title': e['title']} for e in popular]
    if len(picks) < MIN_SIZE: return {'status': 'skipped', 'reason': f'la IA eligió {len(picks)} (mínimo {MIN_SIZE})', 'day': day, 'scope': scope, 'usage': message.get('usage') or {}}
    with conn:
        conn.execute("""INSERT INTO ai_selection(day,scope,created_at,model,prompt_version,candidates_json,picks_json,usage_json,popular_json) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(day,scope) DO UPDATE SET created_at=excluded.created_at,model=excluded.model,prompt_version=excluded.prompt_version,
            candidates_json=excluded.candidates_json,picks_json=excluded.picks_json,usage_json=excluded.usage_json,popular_json=excluded.popular_json""",
                     (day, scope, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), model, version(),
                      json.dumps([e['key'] for e in items]), json.dumps(picks, ensure_ascii=False), json.dumps(message.get('usage') or {}),
                      json.dumps(pops, ensure_ascii=False)))
    return {'status': 'completed', 'day': day, 'scope': scope, 'picks': [p['title'][:50] for p in picks], 'populares': [p['title'][:50] for p in pops], 'usage': message.get('usage') or {}}


def request_body(items, day, scope, model):
    listing = [_payload(n, e) for n, e in enumerate(items)]
    ask = SYSTEM + '\n\n' + guide() + ('\n\nAlcance: solo el día ' + day + '. Reparte las elegidas entre mañana, tarde y noche si hay con qué.' if scope == 'day'
                                         else '\n\nAlcance: del ' + day + ' a los seis días siguientes. Reparte días.')
    return {'model': model, 'max_tokens': 2000,
            'system': [{'type': 'text', 'text': ask, 'cache_control': {'type': 'ephemeral'}}],
            'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'seleccionar'},
            'messages': [{'role': 'user', 'content': json.dumps(listing, ensure_ascii=False)}]}


def parse(message, items):
    """(elegidas comprobadas, populares comprobadas) de la respuesta de la IA."""
    rows, pops = [], []
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use':
            data = block.get('input') or {}
            for r in data.get('elegidas') or []:
                try: rows.append((int(r['n']), 'seleccion', str(r.get('motivo') or '')[:200]))
                except (KeyError, TypeError, ValueError): continue
            # A veces llegan como {"n": 3} o "3" en vez de 3 (30-10-2026: cinco días sin populares por eso).
            for x in data.get('populares') or []:
                x = x.get('n') if isinstance(x, dict) else x
                try: pops.append(int(x))
                except (TypeError, ValueError): continue
    chosen = pick(rows, items)
    return chosen, populars(pops, items, chosen)


def ensure_ahead(conn, key, model=None, requester=None, today=None, ahead=AHEAD_DAYS):
    """Las selecciones de hoy y de los próximos días, en los dos alcances. Resumen con las llamadas hechas y el uso."""
    from mvp import catalog
    today = today or catalog.today()
    out, usage = [], {}
    for offset in range(ahead + 1):
        day = (today + dt.timedelta(days=offset)).isoformat()
        for scope in SCOPES:
            r = ensure(conn, key, day=day, scope=scope, model=model, requester=requester)
            out.append(r)
            for k, v in (r.get('usage') or {}).items():
                if isinstance(v, int): usage[k] = usage.get(k, 0) + v
    return {'status': 'completed', 'calls': sum(1 for r in out if r['status'] == 'completed'), 'days': ahead + 1, 'usage': usage,
            'skipped': [(r['day'], r['scope'], r.get('reason')) for r in out if r['status'] == 'skipped']}


def picks_for(conn, day, scope='week'):
    """Claves elegidas por la IA para ese día y alcance (en orden) o [] si no hay selección."""
    try: row = conn.execute('SELECT picks_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    except Exception: return []
    return [p['key'] for p in json.loads(row[0])] if row else []


def populars_for(conn, day, scope='week'):
    """Claves de las «populares» de ese día y alcance (30-10-2026) o []."""
    try: row = conn.execute('SELECT popular_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    except Exception: return []
    return [p['key'] for p in json.loads(row[0])] if row and row[0] else []
