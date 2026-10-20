"""Ayuda de IA (Claude API) para los casos que las reglas no resuelven (20-10-2026).

Dos tareas, ambas con salida cerrada (nunca texto que acabe en la web):
  · categoria: fichas pendientes, ambiguas o solo «probables» → una de las 8 categorías,
    «excluida» o «pendiente», con confianza y motivo.
  · duplicado: pares candidatos que las reglas no fusionan → «mismo», «distinto» o «sesion».

Trazabilidad: cada respuesta se guarda en ``ai_suggestions`` con el modelo, la versión del prompt
y la huella de lo que se le enseñó; si la ficha cambia, la respuesta deja de valer. Prioridad:
corrección editorial > regla fuerte > IA (confianza alta) > regla débil. Decisión de David
(20-10-2026): aplicar automáticamente con confianza alta; sin tope de gasto (se vigila el uso,
que queda anotado por lote en ``ai_batches``).

Coste: modelo Haiku, API de lotes (mitad de precio), instrucciones en caché y 40 fichas por
petición. Clave: ANTHROPIC_API_KEY en .env (o variable de entorno). Sin clave, no hace nada.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

from src.network import tls_context

ROOT = Path(__file__).resolve().parents[1]
API = 'https://api.anthropic.com/v1'
MODEL = 'claude-haiku-5-5'
PROMPT_VERSION = {'categoria': 2, 'duplicado': 2, 'datos': 1, 'descripcion': 1, 'familia': 1}
APPLY_CATEGORY = 0.8      # confianza mínima para que la IA decida la categoría
APPLY_DUPLICATE = 0.85    # confianza mínima para fusionar dos fichas
ITEMS_PER_REQUEST = 40
MAX_REQUESTS_PER_BATCH = 150

CATEGORY_KEYS = ['musica', 'escena', 'cine', 'arte', 'charlas', 'talleres', 'fiestas', 'deporte', 'excluida', 'pendiente']

SYSTEM_CATEGORY = """Clasificas actividades de la agenda cultural de Barcelona (Brollant) en UNA categoría según su naturaleza.
Categorías:
- musica: conciertos, recitales, sesiones de DJ, clubbing, audiciones, coros, ópera en concierto.
- escena: teatro, danza, circo, títeres, magia, monólogos y comedia, musicales, cuentacuentos y narración oral.
- cine: proyecciones, ciclos de cine, cortometrajes, documentales.
- arte: exposiciones (todas: de arte, historia, ciencia, fotografía), inauguraciones, instalaciones, performance artística.
- charlas: conferencias, debates, presentaciones de libros, clubes de lectura, recitales de poesía, visitas guiadas, rutas e itinerarios.
- talleres: talleres, cursos, clases, actividades participativas, juegos y gincanas, catas y cocina, grupos comunitarios de barrio.
- fiestas: fiestas mayores y populares, castañadas, mercados, ferias, ferias de artesanía, correfocs, sardanas, bailes populares.
- deporte: competiciones y partidos, carreras populares, caminatas deportivas.
- excluida: no es un plan de agenda cultural: servicios (punto TIC, asesoramiento, orientación laboral o de estudios), campañas y recogidas solidarias, convocatorias y premios, grupos de apoyo (duelo, demencia, salud), ocio social o profesional (citas, intercambio de idiomas, pub crawls, networking, ferias de empleo, congresos), productos de ticketera.
- pendiente: no hay información suficiente para decidir.
Reglas: una visita o un taller dentro de una exposición es charlas o talleres, no arte. Una sesión dentro de un festival o ciclo se clasifica por la actividad, no por el festival. Usa solo lo que dicen los datos; no supongas. Confianza entre 0 y 1: por encima de 0.8 solo si el dato lo deja claro. El motivo, como máximo 12 palabras.
Recibes una lista JSON de fichas (n, título, sala, categoría de la fuente, tipo, extracto). Responde con la herramienta clasificar, una entrada por ficha."""

SYSTEM_DUPLICATE = """Comparas pares de fichas de una agenda cultural de Barcelona que vienen de fuentes distintas y decides si son el mismo acto.
- mismo: el mismo acto en la misma fecha y lugar (pueden diferir el título, la hora de puertas o el formato del nombre).
- distinto: actos diferentes (otra obra, otro artista, otra sesión u otro día).
- sesion: una ficha es el festival, ciclo o programa y la otra una sesión dentro de él.
Usa solo los datos. Confianza entre 0 y 1; por encima de 0.85 solo si es inequívoco. Motivo, como máximo 12 palabras.
Recibes una lista JSON de pares (n, a, b). Responde con la herramienta comparar, una entrada por par."""

TOOL_CATEGORY = {'name': 'clasificar', 'description': 'Devuelve la categoría de cada ficha.',
                 'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
                     'type': 'object', 'required': ['n', 'categoria', 'confianza', 'motivo'],
                     'properties': {'n': {'type': 'integer'}, 'categoria': {'type': 'string', 'enum': CATEGORY_KEYS},
                                    'confianza': {'type': 'number'}, 'motivo': {'type': 'string'}}}}}}}
TOOL_DUPLICATE = {'name': 'comparar', 'description': 'Devuelve el veredicto de cada par.',
                  'input_schema': {'type': 'object', 'required': ['pares'], 'properties': {'pares': {'type': 'array', 'items': {
                      'type': 'object', 'required': ['n', 'veredicto', 'confianza', 'motivo'],
                      'properties': {'n': {'type': 'integer'}, 'veredicto': {'type': 'string', 'enum': ['mismo', 'distinto', 'sesion']},
                                     'confianza': {'type': 'number'}, 'motivo': {'type': 'string'}}}}}}}
def _parse_category(row, payload):
    if row.get('categoria') not in CATEGORY_KEYS: return None
    return row['categoria'], _conf(row), str(row.get('motivo') or '')[:300]


def _parse_duplicate(row, payload):
    if row.get('veredicto') not in ('mismo', 'distinto', 'sesion'): return None
    return row['veredicto'], _conf(row), str(row.get('motivo') or '')[:300]


def _parse_datos(row, payload):
    from src.ai_extract import verify
    start, end = (payload.get('fechas') or ['', ''])[:2]
    kept, dropped = verify(row, payload.get('texto') or '', start or '', end or start or '')
    return json.dumps(kept, ensure_ascii=False), 1.0, f'{len(dropped)} datos descartados por no pasar la comprobación de cita' if dropped else ''


def _conf(row):
    try: return max(0.0, min(1.0, float(row.get('confianza'))))
    except (TypeError, ValueError): return 0.0


def _tasks():
    from src import ai_extract, ai_describe, ai_family
    return {'familia': (ai_family.SYSTEM, ai_family.TOOL, 'fichas', ai_family.parse),
            'categoria': (SYSTEM_CATEGORY, TOOL_CATEGORY, 'fichas', _parse_category),
            'duplicado': (SYSTEM_DUPLICATE, TOOL_DUPLICATE, 'pares', _parse_duplicate),
            'datos': (ai_extract.SYSTEM, ai_extract.TOOL, 'fichas', _parse_datos),
            'descripcion': (ai_describe.SYSTEM, ai_describe.TOOL, 'fichas', ai_describe.parse)}


def load_key(env_path=None):
    if os.environ.get('ANTHROPIC_API_KEY'): return os.environ['ANTHROPIC_API_KEY'].strip()
    path = Path(env_path) if env_path else ROOT / '.env'
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            key, _, value = line.partition('=')
            if key.strip() == 'ANTHROPIC_API_KEY': return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ''


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ai_suggestions (
      task TEXT NOT NULL, item TEXT NOT NULL, input_hash TEXT NOT NULL, model TEXT NOT NULL, prompt_version INTEGER NOT NULL,
      answer TEXT NOT NULL, confidence REAL NOT NULL, reason TEXT NOT NULL DEFAULT '', batch_id TEXT, created_at TEXT NOT NULL,
      PRIMARY KEY(task,item));
    CREATE TABLE IF NOT EXISTS ai_suggestion_log (
      task TEXT NOT NULL, item TEXT NOT NULL, input_hash TEXT NOT NULL, model TEXT NOT NULL, prompt_version INTEGER NOT NULL,
      answer TEXT NOT NULL, confidence REAL NOT NULL, reason TEXT NOT NULL DEFAULT '', batch_id TEXT, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ai_batches (
      batch_id TEXT PRIMARY KEY, task TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, items_json TEXT NOT NULL,
      created_at TEXT NOT NULL, ended_at TEXT, usage_json TEXT, error TEXT);
    """)


def _now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def _hash(payload): return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


# ---------- lo que se le enseña ----------
def category_payload(ev):
    return {'titulo': (ev.get('title') or '')[:200], 'sala': (ev.get('source_venue') or (ev.get('venue_names') or [''])[0] or '')[:100],
            'categoria_fuente': ev.get('category') or '', 'tipo': ev.get('format') or ev.get('kind') or '',
            'extracto': (ev.get('summary') or '')[:300]}


def pair_payload(a, b):
    side = lambda e: {'fuente': e['source'], 'titulo': (e.get('title') or '')[:200], 'fechas': [e.get('start'), e.get('end')],
                      'hora': e.get('time') or '', 'sala': (e.get('source_venue') or (e.get('venue_names') or [''])[0] or '')[:100]}
    return {'a': side(a), 'b': side(b)}


_CACHE = {'stamp': None, 'map': {}}


def suggestions(conn):
    """{(task,item): {answer, confidence, reason, input_hash, model, prompt_version}} (recarga si cambia la tabla)."""
    try: stamp = conn.execute('SELECT COUNT(*), MAX(created_at) FROM ai_suggestions').fetchone()
    except sqlite3.DatabaseError: return {}
    if stamp != _CACHE['stamp']:
        rows = conn.execute('SELECT task,item,answer,confidence,reason,input_hash,model,prompt_version FROM ai_suggestions').fetchall()
        _CACHE.update(stamp=stamp, map={(t, i): {'answer': a, 'confidence': c, 'reason': r, 'input_hash': h, 'model': m, 'prompt_version': v}
                                        for t, i, a, c, r, h, m, v in rows})
    return _CACHE['map']


def category_for(conn, key, ev):
    """La sugerencia vigente de categoría para la ficha (o None si no hay o si la ficha cambió)."""
    s = suggestions(conn).get(('categoria', key))
    if not s or s['prompt_version'] != prompt_version('categoria') or s['input_hash'] != _hash(category_payload(ev)): return None
    return s


def same_pairs(conn):
    """Pares que la IA da por el mismo acto con confianza alta (para la fusión de duplicados)."""
    out = []
    for (task, item), s in suggestions(conn).items():
        if task == 'duplicado' and s['answer'] == 'mismo' and s['confidence'] >= APPLY_DUPLICATE and s['prompt_version'] == prompt_version('duplicado'):
            a, _, b = item.partition('|'); out.append((a, b))
    return out


# ---------- candidatos ----------
def category_candidates(conn, events, today):
    from src import taxonomy
    current = suggestions(conn); out = []
    for e in events:
        # Pendientes (la IA decide) y ambiguas (la IA solo señala discrepancias para revisión).
        if e.get('rule_status') != 'pendiente' and not e.get('rule_ambiguous'): continue
        if not taxonomy.eligible(e, today) or e.get('category_status') == 'editorial': continue
        payload = category_payload(e); s = current.get(('categoria', e['key']))
        if s and s['input_hash'] == _hash(payload) and s['prompt_version'] == prompt_version('categoria'): continue
        out.append((e['key'], payload))
    return out


def data_candidates(conn, events, today):
    from src import ai_extract, taxonomy
    current = suggestions(conn); out = []
    for e in events:
        if not taxonomy.eligible(e, today) or not ai_extract.needs(e): continue
        payload = ai_extract.payload(e); s = current.get(('datos', e['key']))
        if s and s['input_hash'] == _hash(payload) and s['prompt_version'] == prompt_version('datos'): continue
        out.append((e['key'], payload))
    return out


def data_for(conn, key, ev):
    """Datos extraídos y comprobados vigentes para la ficha (dict) o None."""
    from src import ai_extract
    s = suggestions(conn).get(('datos', key))
    if not s or s['prompt_version'] != prompt_version('datos') or s['input_hash'] != _hash(ai_extract.payload(ev)): return None
    try: return json.loads(s['answer'])
    except ValueError: return None


def description_candidates(conn, events, today):
    from src import ai_describe, taxonomy
    current = suggestions(conn); out = []
    for e in events:
        if not taxonomy.eligible(e, today) or not ai_describe.needs(e): continue
        payload = ai_describe.payload(e); s = current.get(('descripcion', e['key']))
        if s and s['input_hash'] == _hash(payload) and s['prompt_version'] == prompt_version('descripcion'): continue
        out.append((e['key'], payload))
    return out


def description_for(conn, key, ev):
    """Descripción breve vigente y aceptada ({es, ca, model}) o None."""
    from src import ai_describe
    s = suggestions(conn).get(('descripcion', key))
    if not s or s['prompt_version'] != prompt_version('descripcion') or s['input_hash'] != _hash(ai_describe.payload(ev)): return None
    try: d = json.loads(s['answer'])
    except ValueError: return None
    # Se vuelve a comprobar con las reglas vigentes (así una mejora de la comprobación vale también
    # para lo ya generado, sin volver a llamar a la API).
    payload = ai_describe.payload(ev); es, ca = d.get('es', ''), d.get('ca', '')
    if not (es and ca) or ai_describe.check(es, payload) or ai_describe.check(ca, payload): return None
    return {'es': es, 'ca': ca, 'model': s['model']}


def family_candidates(conn, events, today):
    from src import ai_family, taxonomy
    current = suggestions(conn); out = []
    for e in events:
        if not taxonomy.eligible(e, today) or not ai_family.needs(e): continue
        payload = ai_family.payload(e); s = current.get(('familia', e['key']))
        if s and s['input_hash'] == _hash(payload) and s['prompt_version'] == prompt_version('familia'): continue
        out.append((e['key'], payload))
    return out


def family_for(conn, key, ev):
    """Recomendación «en familia» vigente y aceptada ({es, ca, confidence, model}) o None."""
    from src import ai_family
    s = suggestions(conn).get(('familia', key))
    if not s or s['prompt_version'] != prompt_version('familia') or s['input_hash'] != _hash(ai_family.payload(ev)): return None
    try: d = json.loads(s['answer'])
    except ValueError: return None
    if not ai_family.accepted(d, s['confidence']): return None
    return {'es': d['es'], 'ca': d['ca'], 'confidence': s['confidence'], 'model': s['model']}


def duplicate_candidates(conn, events, today):
    from src import dedupe
    by_key = {e['key']: e for e in events}; current = suggestions(conn); out = []
    try: rows = conn.execute('SELECT a,b,score,reason FROM match_candidates').fetchall()
    except sqlite3.DatabaseError: return []
    groups = dedupe.canonical_groups(conn)
    for a, b, score, reason in rows:
        if dedupe._collapsible(score or 0, (reason or '').split(';')): continue
        ea, eb = by_key.get(a), by_key.get(b)
        if not ea or not eb or max(ea['end'], eb['end']) < today: continue
        if groups.get(a, a) == groups.get(b, b): continue  # las reglas ya los agrupan
        payload = pair_payload(ea, eb); item = f'{a}|{b}'; s = current.get(('duplicado', item))
        if s and s['input_hash'] == _hash(payload) and s['prompt_version'] == prompt_version('duplicado'): continue
        out.append((item, payload))
    return out


# ---------- API ----------
def _request(method, url, key, body=None, timeout=60, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as response:  # nosec B310: API oficial
        payload = response.read()
    return payload.decode('utf-8') if raw else json.loads(payload)


GUIDE_PATH = ROOT / 'config' / 'ia_instrucciones.md'


def guide():
    """Instrucciones editoriales editables (config/ia_instrucciones.md) para la categoría."""
    try: return GUIDE_PATH.read_text(encoding='utf-8').strip()
    except OSError: return ''


def prompt_version(task):
    """Versión del prompt: la fija del código más la huella de las instrucciones editables, para que
    editar el archivo invalide las respuestas anteriores."""
    base = PROMPT_VERSION[task]
    if task != 'categoria' or not guide(): return base
    return base * 1000 + int(hashlib.sha256(guide().encode()).hexdigest()[:5], 16) % 1000


def _params(task, chunk, model):
    system, tool, field, _ = _tasks()[task]
    if task == 'categoria' and guide(): system = system + '\n\n' + guide()  # en caché: apenas cuesta
    listing = [{'n': n, **payload} for n, (_, payload) in enumerate(chunk)]
    per_item = {'datos': 400, 'descripcion': 260, 'familia': 220}.get(task, 150)  # tope de salida, no se cobra si no se usa
    return {'model': model, 'max_tokens': min(32000, 200 + per_item * len(chunk)),
            'system': [{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}],
            'tools': [tool], 'tool_choice': {'type': 'tool', 'name': tool['name']},
            'messages': [{'role': 'user', 'content': json.dumps(listing, ensure_ascii=False)}]}


def _answers(task, message, chunk):
    """[(n, answer, confidence, reason)] a partir de un mensaje con tool_use (ya validado por la tarea)."""
    _, tool, field, parse = _tasks()[task]
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use' and block.get('name') == tool['name']:
            out = []
            for row in (block.get('input') or {}).get(field) or []:
                try: n = int(row['n'])
                except (KeyError, TypeError, ValueError): continue
                if not 0 <= n < len(chunk): continue
                parsed = parse(row, chunk[n][1])
                if parsed: out.append((n, *parsed))
            return out
    return []


def _store(conn, task, chunk, answers, model, batch_id):
    now = _now(); stored = 0
    with conn:
        for n, answer, confidence, reason in answers:
            item, payload = chunk[n]; row = (task, item, _hash(payload), model, prompt_version(task), answer, confidence, reason, batch_id, now)
            conn.execute("""INSERT INTO ai_suggestions(task,item,input_hash,model,prompt_version,answer,confidence,reason,batch_id,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(task,item) DO UPDATE SET input_hash=excluded.input_hash,model=excluded.model,
                prompt_version=excluded.prompt_version,answer=excluded.answer,confidence=excluded.confidence,reason=excluded.reason,
                batch_id=excluded.batch_id,created_at=excluded.created_at""", row)
            conn.execute('INSERT INTO ai_suggestion_log VALUES (?,?,?,?,?,?,?,?,?,?)', row); stored += 1
    return stored


def ask_now(task, items, key=None, model=MODEL, usage=None, requester=None, retries=2):
    """Llamada directa (sin lote), para evaluar: [(item, payload)] → {item: (answer, confidence, reason)}.
    Si una respuesta llega cortada o se salta fichas, las que faltan se reintentan en grupos más
    pequeños (hasta ``retries`` veces)."""
    key = key or load_key(); out = {}; requester = requester or _request
    usage = usage if usage is not None else {}
    pending, size = list(items), ITEMS_PER_REQUEST
    for attempt in range(retries + 1):
        for start in range(0, len(pending), size):
            chunk = pending[start:start + size]
            message = requester('POST', f'{API}/messages', key, _params(task, chunk, model), timeout=180)
            for k, v in (message.get('usage') or {}).items():
                if isinstance(v, int): usage[k] = usage.get(k, 0) + v
            reason = message.get('stop_reason') or '?'
            usage.setdefault('stop_reasons', {}); usage['stop_reasons'][reason] = usage['stop_reasons'].get(reason, 0) + 1
            for n, answer, confidence, why in _answers(task, message, chunk):
                out[chunk[n][0]] = (answer, confidence, why)
        pending = [x for x in pending if x[0] not in out]
        if not pending: break
        size = 10
    usage['sin_respuesta'] = len(pending)
    return out


def collect(conn, key, requester=_request):
    """Recoge los lotes terminados y guarda las respuestas."""
    stored = 0; usage = {'input_tokens': 0, 'output_tokens': 0, 'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}
    for batch_id, task, model, items_json in conn.execute("SELECT batch_id,task,model,items_json FROM ai_batches WHERE status='in_progress'").fetchall():
        info = requester('GET', f'{API}/messages/batches/{batch_id}', key)
        if info.get('processing_status') != 'ended': continue
        chunks = json.loads(items_json); batch_usage = dict.fromkeys(usage, 0)
        text = requester('GET', info['results_url'], key, raw=True, timeout=300) if info.get('results_url') else ''
        for line in text.splitlines():
            if not line.strip(): continue
            row = json.loads(line); result = row.get('result') or {}
            chunk = [tuple(x) for x in chunks.get(row.get('custom_id'), [])]
            if result.get('type') != 'succeeded' or not chunk: continue
            message = result['message']
            for k in batch_usage: batch_usage[k] += int((message.get('usage') or {}).get(k) or 0)
            stored += _store(conn, task, chunk, _answers(task, message, chunk), model, batch_id)
        for k in usage: usage[k] += batch_usage[k]
        with conn:
            conn.execute("UPDATE ai_batches SET status='ended', ended_at=?, usage_json=? WHERE batch_id=?", (_now(), json.dumps(batch_usage), batch_id))
    return stored, usage


def submit(conn, key, task, items, model=MODEL, requester=_request):
    """Envía un lote con hasta MAX_REQUESTS_PER_BATCH peticiones de ITEMS_PER_REQUEST elementos."""
    if not items: return None
    pending = {tuple(x)[0] for (j,) in conn.execute("SELECT items_json FROM ai_batches WHERE status='in_progress' AND task=?", (task,))
               for chunk in json.loads(j).values() for x in chunk}
    items = [x for x in items if x[0] not in pending][:ITEMS_PER_REQUEST * MAX_REQUESTS_PER_BATCH]
    if not items: return None
    chunks = {f'{task[:3]}-{n}': items[start:start + ITEMS_PER_REQUEST] for n, start in enumerate(range(0, len(items), ITEMS_PER_REQUEST))}
    body = {'requests': [{'custom_id': cid, 'params': _params(task, chunk, model)} for cid, chunk in chunks.items()]}
    info = requester('POST', f'{API}/messages/batches', key, body, timeout=300)  # lotes grandes: subida de varios MB
    with conn:
        conn.execute('INSERT INTO ai_batches(batch_id,task,model,status,items_json,created_at) VALUES(?,?,?,?,?,?)',
                     (info['id'], task, model, 'in_progress', json.dumps(chunks, ensure_ascii=False), _now()))
    return {'batch_id': info['id'], 'items': len(items), 'requests': len(chunks)}


def run(conn, job=None, requester=_request, today=None):
    """Trabajo automático «ia-asistente»: recoge lo terminado y envía lo nuevo."""
    job = job or {}; key = load_key()
    if not key: return {'status': 'skipped', 'reason': 'Falta ANTHROPIC_API_KEY en .env'}
    initialize(conn); model = job.get('model') or MODEL
    from mvp import catalog
    today = today or catalog.today().isoformat()
    try:
        stored, usage = collect(conn, key, requester)
        if stored: catalog.invalidate_cache()
        events = catalog.all_events(conn)
        sent = {}
        for task, finder in (('categoria', category_candidates), ('datos', data_candidates), ('descripcion', description_candidates), ('familia', family_candidates), ('duplicado', duplicate_candidates)):
            if job.get(task, True): sent[task] = submit(conn, key, task, finder(conn, events, today), model, requester)
        selection = None
        if job.get('seleccion', True):
            from src import ai_select
            selection = ai_select.ensure(conn, key, model=model, requester=requester if requester is not _request else None)
        return {'status': 'completed', 'stored': stored, 'usage': usage, 'submitted': sent, 'selection': selection}
    except urllib.error.HTTPError as err:
        return {'status': 'failed', 'error': f'API de Claude: HTTP {err.code}'}
