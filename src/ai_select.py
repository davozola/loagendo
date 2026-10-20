"""«Selección de la semana» con IA (20-10-2026; decisión de David: directamente en la web).

Las reglas (``catalog.query_events(featured=True)``) proponen ~100 candidatos de la semana con imagen o
descripción; la IA elige 7 con los criterios de ``config/ia_seleccion.md`` (≈60 % populares, 40 %
descubrimiento, variedad). Se comprueba la respuesta (fichas existentes, sin repetir, máximo 2 por
categoría) y se completa con el orden de las reglas si falta algo. Una llamada al día; queda guardado
en ``ai_selection`` con candidatos, elegidas, motivos, modelo y criterios.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZE = 7
CANDIDATES = 100  # máximo de query_events
POPULAR, DISCOVERY = 4, 3
PROMPT_VERSION = 1

SYSTEM = """Eres el editor de Brollant, agenda cultural de Barcelona. Eliges la «Selección de la semana» entre los candidatos que recibes (lista JSON con n, título, categoría, canales, fecha, hora, sala, barrio, gratis, tipo, cartel y extracto).
Responde con la herramienta seleccionar: exactamente 7 elegidas, cada una con su n, el tipo (popular o descubrimiento) y un motivo de como máximo 12 palabras.
Usa solo los datos de cada ficha; no inventes."""

TOOL = {'name': 'seleccionar', 'description': 'Las 7 actividades elegidas para la selección de la semana.',
        'input_schema': {'type': 'object', 'required': ['elegidas'], 'properties': {'elegidas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'tipo', 'motivo'],
            'properties': {'n': {'type': 'integer'}, 'tipo': {'type': 'string', 'enum': ['popular', 'descubrimiento']}, 'motivo': {'type': 'string'}}}}}}}


def guide():
    try: return (ROOT / 'config' / 'ia_seleccion.md').read_text(encoding='utf-8').strip()
    except OSError: return ''


def version():
    return f"{PROMPT_VERSION}-{hashlib.sha256(guide().encode()).hexdigest()[:8]}"


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_selection (
      day TEXT PRIMARY KEY, created_at TEXT NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
      candidates_json TEXT NOT NULL, picks_json TEXT NOT NULL, usage_json TEXT)""")


def candidates(conn, day):
    from mvp import catalog
    items = catalog.query_events(conn, day=day, featured=True, public=True, page_size=CANDIDATES)['items']
    return [e for e in items if e.get('media') or e.get('has_description')][:CANDIDATES]


def _payload(n, e):
    return {'n': n, 'titulo': e['title'][:160], 'categoria': e.get('public_category'), 'canales': e.get('channels') or [],
            'fecha': e.get('featured_date') or e['start'], 'hora': e.get('time') or '', 'sala': (e.get('venue_names') or [''])[0][:80],
            'barrio': e.get('district') or '', 'gratis': bool(e.get('is_free')), 'tipo': e.get('kind'),
            'cartel': (e.get('lineup') or [])[:5], 'extracto': (e.get('summary') or '')[:200]}


def pick(rows, items):
    """Comprueba y equilibra la respuesta: [(n, tipo, motivo)] → [(item, tipo, motivo)] (7 como máximo)."""
    out, seen, per_cat = [], set(), {}
    want = {'popular': POPULAR, 'descubrimiento': DISCOVERY}; got = {'popular': 0, 'descubrimiento': 0}
    for n, kind, why in rows:
        if not (isinstance(n, int) and 0 <= n < len(items)) or n in seen or kind not in want: continue
        cat = items[n].get('public_category')
        if per_cat.get(cat, 0) >= 2 or got[kind] >= want[kind]: continue
        out.append((items[n], kind, why)); seen.add(n); per_cat[cat] = per_cat.get(cat, 0) + 1; got[kind] += 1
    for n, kind, why in rows:  # si la IA no respetó el reparto, se completa con sus otras elegidas
        if len(out) >= SIZE: break
        if isinstance(n, int) and 0 <= n < len(items) and n not in seen and kind in want and per_cat.get(items[n].get('public_category'), 0) < 2:
            out.append((items[n], kind, why)); seen.add(n); per_cat[items[n].get('public_category')] = per_cat.get(items[n].get('public_category'), 0) + 1
    for n, e in enumerate(items):  # y si aun faltan, con el orden de las reglas
        if len(out) >= SIZE: break
        if n not in seen and per_cat.get(e.get('public_category'), 0) < 2:
            out.append((e, 'reglas', 'Completada con la puntuación de las reglas')); seen.add(n); per_cat[e.get('public_category')] = per_cat.get(e.get('public_category'), 0) + 1
    return out[:SIZE]


def ensure(conn, key, day=None, model=None, requester=None):
    """Calcula la selección del día si no está hecha con los criterios vigentes. Devuelve un resumen."""
    from mvp import catalog
    from src import ai_assist
    initialize(conn); day = day or catalog.today().isoformat(); model = model or ai_assist.MODEL
    row = conn.execute('SELECT prompt_version FROM ai_selection WHERE day=?', (day,)).fetchone()
    if row and row[0] == version(): return {'status': 'already_done', 'day': day}
    items = candidates(conn, day)
    if len(items) < SIZE: return {'status': 'skipped', 'reason': 'pocos candidatos', 'day': day}
    listing = [_payload(n, e) for n, e in enumerate(items)]
    body = {'model': model, 'max_tokens': 1500,
            'system': [{'type': 'text', 'text': SYSTEM + '\n\n' + guide(), 'cache_control': {'type': 'ephemeral'}}],
            'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'seleccionar'},
            'messages': [{'role': 'user', 'content': json.dumps(listing, ensure_ascii=False)}]}
    message = (requester or ai_assist._request)('POST', f'{ai_assist.API}/messages', key, body, timeout=180)
    rows = []
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use':
            for r in (block.get('input') or {}).get('elegidas') or []:
                try: rows.append((int(r['n']), str(r['tipo']), str(r.get('motivo') or '')[:200]))
                except (KeyError, TypeError, ValueError): continue
    chosen = pick(rows, items)
    picks = [{'key': e['key'], 'title': e['title'], 'tipo': kind, 'motivo': why} for e, kind, why in chosen]
    with conn:
        conn.execute("""INSERT INTO ai_selection(day,created_at,model,prompt_version,candidates_json,picks_json,usage_json) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(day) DO UPDATE SET created_at=excluded.created_at,model=excluded.model,prompt_version=excluded.prompt_version,
            candidates_json=excluded.candidates_json,picks_json=excluded.picks_json,usage_json=excluded.usage_json""",
                     (day, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), model, version(),
                      json.dumps([e['key'] for e in items]), json.dumps(picks, ensure_ascii=False), json.dumps(message.get('usage') or {})))
    return {'status': 'completed', 'day': day, 'picks': [(p['tipo'], p['title'][:50]) for p in picks], 'usage': message.get('usage') or {}}


def picks_for(conn, day):
    """Claves elegidas por la IA para ese día (en orden) o [] si no hay selección."""
    try: row = conn.execute('SELECT picks_json FROM ai_selection WHERE day=?', (day,)).fetchone()
    except Exception: return []
    return [p['key'] for p in json.loads(row[0])] if row else []
