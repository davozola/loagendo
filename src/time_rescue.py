"""Rescate de horas cuando una fuente deja de darlas (nivel 1, 23-10-2026).

Mientras una fuente tiene abierta la alerta TIME_COVERAGE_DROP (src/time_health.py), este trabajo
busca la hora de sus actos sin hora en la página propia de cada acto, sin tocar el conector:

  1. Lectura con reglas: schema.org del acto, calendario de funciones impreso o, en un acto de un
     día, la única hora escrita en la página (src/official_dates.read_page).
  2. Si no sale nada, lectura con IA (Haiku) de esa página, con la misma comprobación sin IA de las
     agendas de sala: la cita tiene que estar literalmente en la página, la hora dentro de la cita
     y la cita cerca del título del acto. Si no pasa, no entra.

Cada intento queda en ``time_rescue`` (método, hora, cita, URL, modelo, fecha). Las horas
rescatadas pasan a ``known_times`` con evidencia «rescate_pagina» o «rescate_ia»: la ficha las usa
solo si la lectura actual de la fuente no da hora para ese día. La alerta no se cierra por esto:
sigue abierta hasta que el propio conector vuelva a leer horas, para que se arregle.
Respeta robots.txt; cada acto se vuelve a intentar a los 3 días como mucho.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3

from src import known_times

WINDOW_DAYS = 30
RETRY_DAYS = 3
PROMPT_VERSION = 1
SYSTEM = """Lees la página web de un acto cultural de Barcelona (concierto, función, charla…) y dices a qué hora empieza el día indicado.
Reglas estrictas:
- Solo si la hora está escrita en el texto para ese acto y ese día. Nada deducido, nada inventado.
- Si hay hora de apertura de puertas y hora de inicio, da la de inicio. Si hay varias horas y no sabes cuál es la del acto ese día, deja hora vacía.
- cita_hora: copia literal y corta (máx. 120 caracteres) del texto donde se lee la hora; tiene que poder encontrarse tal cual en el texto.
- hora en formato HH:MM. Si no hay hora escrita, hora y cita_hora vacías.
Responde con la herramienta hora."""
TOOL = {'name': 'hora', 'description': 'Hora de inicio del acto con su cita literal.',
        'input_schema': {'type': 'object', 'required': ['hora', 'cita_hora'],
                         'properties': {'hora': {'type': 'string'}, 'cita_hora': {'type': 'string'}}}}


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS time_rescue (source TEXT NOT NULL, id TEXT NOT NULL, day TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL, method TEXT NOT NULL DEFAULT '', local_time TEXT NOT NULL DEFAULT '', quote TEXT NOT NULL DEFAULT '',
      model TEXT NOT NULL DEFAULT '', prompt_version INTEGER NOT NULL DEFAULT 0, checked_at TEXT NOT NULL, PRIMARY KEY(source, id, day))""")


def candidates(conn, limit, today=None):
    """Actos de un día, de fuentes con alerta abierta, sin hora de la fuente ni rescate reciente."""
    from src.time_health import initialize as init_health
    from src.official_dates import usable
    from src.organizer_text import _words
    from urllib.parse import urlsplit
    init_health(conn); initialize(conn)
    today = today or dt.date.today()
    retry = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETRY_DAYS)).isoformat(timespec='seconds')
    rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), r.source_url FROM source_records r
        JOIN source_alerts a ON a.source=r.source AND a.kind='TIME_COVERAGE_DROP' AND a.resolved_at IS NULL
        LEFT JOIN time_rescue t ON t.source=r.source AND t.id=r.id AND t.day=substr(r.start_date,1,10)
        WHERE r.kind='single' AND r.eligibility<>'exclude' AND substr(r.start_date,1,10) BETWEEN ? AND ?
          AND NOT EXISTS (SELECT 1 FROM candidate_occurrences c WHERE c.source=r.source AND c.id=r.id AND c.local_time<>'')
          AND (t.id IS NULL OR (t.status<>'ok' AND t.checked_at<?))
        ORDER BY (t.id IS NOT NULL), r.start_date LIMIT ?""",
        (today.isoformat(), (today + dt.timedelta(days=WINDOW_DAYS)).isoformat(), retry, limit * 2)).fetchall()
    out = []
    for source, rid, title, day, url in rows:
        # Solo la página de ESTE acto (su ruta comparte palabras con el título), nunca un listado o una portada.
        if url and usable(url) and _words(title) & _words(urlsplit(url).path.replace('-', ' ').replace('_', ' ')):
            out.append((source, rid, title, day, url))
        if len(out) >= limit: break
    return out


def verify(hour, quote, text, title):
    """Hora comprobada sin IA, o ''. La cita está en el texto, contiene la hora y va cerca del título."""
    from src.ai_extract import fold, times_in
    from src.ai_agenda import _positions, _near
    hour, quote = str(hour or '').strip(), str(quote or '')
    if not re.fullmatch(r'\d{1,2}:\d{2}', hour): return ''
    hour = f'{int(hour[:-3]):02d}:{hour[-2:]}'
    hay = fold(text)
    qpos, tpos = _positions(quote, hay), _positions(title, hay)
    if not qpos or hour not in times_in(quote) or hour == '00:00': return ''
    if tpos and not _near(tpos, qpos, 2500, 2500): return ''
    return hour


def ask(text, title, day, key, requester=None, model=None):
    from src import ai_assist
    requester = requester or ai_assist._request; model = model or ai_assist.MODEL
    body = {'model': model, 'max_tokens': 300,
            'system': [{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
            'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'hora'},
            'messages': [{'role': 'user', 'content': json.dumps({'acto': title, 'dia': day, 'texto': text[:8000]}, ensure_ascii=False)}]}
    message = requester('POST', f'{ai_assist.API}/messages', key, body, timeout=60)
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use' and block.get('name') == 'hora':
            got = block.get('input') or {}
            return str(got.get('hora') or ''), str(got.get('cita_hora') or ''), model
    return '', '', model


def rescue_one(source, rid, title, day, url, fetcher, timeout, key=None, requester=None):
    from src.official_dates import read_page, page_text, excerpt_of
    cache = {}
    def cached(u, t):
        if u not in cache: cache[u] = fetcher(u, t)
        return cache[u]
    res = read_page(url, title, day, day, cached, timeout)
    if res.get('status') != 'ok': return {'status': res.get('status') or 'error'}
    if res.get('times', {}).get(day): return {'status': 'ok', 'method': 'rescate_pagina', 'time': res['times'][day], 'quote': ''}
    if not key: return {'status': 'sin_hora'}
    page = cached(url, timeout)[2]
    text = page_text(page)
    hour, quote, model = ask(excerpt_of(text, title) or text, title, day, key, requester)
    checked = verify(hour, quote, text, title)
    if checked: return {'status': 'ok', 'method': 'rescate_ia', 'time': checked, 'quote': quote, 'model': model}
    return {'status': 'sin_hora' if not hour else 'ia_sin_cita_valida', 'quote': quote, 'model': model}


def run(conn, job=None, fetcher=None, requester=None, today=None):
    """Trabajo «rescate-horas»: no hace nada si ninguna fuente tiene la alerta abierta."""
    from src.venue_feeds import fetch, robots_allows
    from src import ai_assist
    import time
    job = job or {}; fetcher = fetcher or fetch
    todo = candidates(conn, job.get('limit', 100), today)
    if not todo: return {'status': 'completed', 'checked': 0, 'rescued': 0}
    key = ai_assist.load_key() if job.get('ia', True) else None
    checked = rescued = 0; by_source = {}
    for source, rid, title, day, url in todo:
        try:
            if fetcher is fetch and not robots_allows(url): res = {'status': 'robots'}
            else:
                res = rescue_one(source, rid, title, day, url, fetcher, job.get('timeout_seconds', 15), key, requester)
                if fetcher is fetch: time.sleep(0.5)
        except Exception as error:
            res = {'status': 'error: ' + type(error).__name__}
        checked += 1; now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        with conn:
            conn.execute("""INSERT INTO time_rescue(source,id,day,url,status,method,local_time,quote,model,prompt_version,checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id,day) DO UPDATE SET url=excluded.url,status=excluded.status,method=excluded.method,local_time=excluded.local_time,
                quote=excluded.quote,model=excluded.model,prompt_version=excluded.prompt_version,checked_at=excluded.checked_at""",
                         (source, rid, day, url, res['status'], res.get('method', ''), res.get('time', ''), res.get('quote', ''), res.get('model', ''),
                          PROMPT_VERSION if res.get('method') == 'rescate_ia' else 0, now))
            if res['status'] == 'ok':
                known_times.remember(conn, source, rid, [{'local_date': day, 'local_time': res['time'], 'evidence_field': res['method']}], now)
                rescued += 1; by_source[source] = by_source.get(source, 0) + 1
    if rescued:
        from mvp import catalog; catalog.invalidate_cache()
    return {'status': 'completed', 'checked': checked, 'rescued': rescued, 'by_source': by_source}
