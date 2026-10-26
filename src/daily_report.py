"""Parte diario de Ontoca (25-10-2026): métricas principales y alertas, por correo a hola@ontoca.com.

Lo envía el trabajo «parte-diario» (kind «report», config/automation.json) cada mañana a la hora
de su campo «at». Solo lee lo que el motor ya guarda (alertas, volumen y horas por fuente,
ejecuciones, resultado de la última publicación, data/first_seen.json): no recorre el catálogo.
Cada parte se guarda también en reports/partes/AAAA-MM-DD.html, se envíe o no.

Si en .env están MATOMO_URL y MATOMO_TOKEN, añade las visitas del día anterior (sitio 2).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'reports' / 'partes'
FIRST_SEEN = ROOT / 'data' / 'first_seen.json'
CATALOG = ROOT / 'dist' / 'data' / 'catalog.json'
SEASON_DAYS = 31          # igual que la web: una temporada larga no se vigila día a día
WATCH_AHEAD_DAYS = 60     # festivales que empiezan en los próximos 60 días
SOON_DAYS = 7             # los que empiezan esta semana salen siempre en la lista
MATOMO_SITE = 2
NOTABLE = 0.25   # cambio de volumen por fuente frente a hace 7 días que merece una línea
TOP_SOURCES = 12
LABELS = {'ACTS_DROP': 'trae muchos menos actos', 'TIME_COVERAGE_DROP': 'ha dejado de dar horas',
          'JOB_FAILING': 'falla en cada pasada', 'PUBLISH_STALE': 'la web no se publica'}
WAIT_DAYS = 3   # un error del servidor de la fuente se espera hasta 3 días antes de pedir revisión
# Clasificación de cada alerta y fallo (26-10-2026): qué se arregla solo y qué hay que mirar.
SERVER_ERROR = re.compile(r'HTTP (Error )?5\d\d|HTTP 0\b|timed? ?out|Connection (reset|refused|aborted)|URLError|tras reintentos|Temporary failure', re.I)
REJECTED = re.compile(r'HTTP (Error )?(401|403|404|410|429)\b|robots', re.I)
TRIAGE = {'revisar': ('Revisar', '#b42318'), 'esperar': ('Avería suya · esperar', '#b54708'), 'suelto': ('Fallo suelto', '#555')}


def triage(kind, detail, age_days=0, recovered=False):
    """(clase, motivo) de una alerta o fallo del motor: «revisar», «esperar» o «suelto».

    · suelto: falló, pero la última pasada del trabajo ya fue bien.
    · esperar: error del servidor de la fuente (5xx, sin respuesta) de menos de WAIT_DAYS días; se recupera solo.
    · revisar: la fuente nos rechaza (401/403/404/429, robots.txt), cae el volumen con la web respondiendo,
      la web no se publica, un 5xx que ya dura WAIT_DAYS días o más, o cualquier error que no se reconoce."""
    text = detail or ''
    if kind == 'PUBLISH_STALE': return 'revisar', 'La web no se publica: mirar el trabajo de publicación.'
    if kind in ('ACTS_DROP', 'TIME_COVERAGE_DROP') or 'LOW_VOLUME' in text:
        return 'revisar', 'La fuente responde pero llega mucho menos: comprobar con --run-job; si se repite, ha cambiado la web o el parser.'
    if recovered: return 'suelto', 'La última pasada ya fue bien.'
    if REJECTED.search(text): return 'revisar', 'La fuente rechaza la petición (403/404/robots.txt): revisar la URL o si nos permite leerla.'
    if SERVER_ERROR.search(text):
        if age_days < WAIT_DAYS: return 'esperar', 'Error del servidor de la fuente; lo publicado se queda y se recupera solo. Revisar si sigue dentro de %d días.' % (WAIT_DAYS - age_days)
        return 'revisar', 'Lleva %d días con error del servidor: avisar a la fuente o comprobar si ha cambiado la URL.' % age_days
    return 'revisar', 'Error no reconocido: mirar el detalle.'


def _badge(t):
    label, color = TRIAGE[t['class']]
    return '<span style="color:%s;font-weight:600">%s</span> <span style="color:#666">· %s</span>' % (color, label, esc(t['reason']))


esc = lambda v: html.escape(str(v if v is not None else ''))


def _volumes(conn, day):
    return {s: n for s, n in conn.execute('SELECT source, acts FROM source_volume WHERE day=?', (day.isoformat(),))}


def _coverage(conn, day):
    return {s: (n, t) for s, n, t in conn.execute('SELECT source, acts, timed FROM time_coverage WHERE day=?', (day.isoformat(),))}


def _festival_watch(conn, today, now, catalog_path=CATALOG):
    """Festivales y fiestas de la web publicada (26-10-2026): los nuevos y los que no tienen hora de ningún día.
    Se lee el catálogo publicado (lo que ve la gente). Cada festival se guarda en ``festival_hour_watch`` desde que se ve
    por primera vez hasta que tiene hora o termina; el parte solo lista los nuevos, los que empiezan esta semana y, los
    lunes, todos los pendientes."""
    try: items = json.loads(Path(catalog_path).read_text(encoding='utf-8'))['items']
    except (OSError, ValueError, KeyError): return None
    conn.execute("""CREATE TABLE IF NOT EXISTS festival_hour_watch (key TEXT PRIMARY KEY, name TEXT NOT NULL, start TEXT, end TEXT, source TEXT,
      hours TEXT, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, resolved_at TEXT)""")
    t, horizon = today.isoformat(), (today + dt.timedelta(days=WATCH_AHEAD_DAYS)).isoformat()
    stamp = now.isoformat(timespec='seconds')
    seen = set(); new = []
    for e in items:
        fs = e.get('fs')
        head = (bool(fs) and bool(fs[2])) or (not fs and e.get('f') == 'festival' and e['a'] != e['b'])
        if not head or e.get('kd') == 'exhibition' or e.get('f') == 'exhibition' or e['b'] < t or e['a'] > horizon: continue
        try: span = (dt.date.fromisoformat(e['b']) - dt.date.fromisoformat(e['a'])).days
        except ValueError: continue
        if span > SEASON_DAYS: continue
        key = '%s:%s' % (e['s'], e['i'])
        hours = 'programa' if e.get('pf') else 'a mano' if e.get('mh') else 'por días' if e.get('hb') else 'con sesiones' if any(o[1] for o in e.get('o') or []) else ''
        seen.add(key)
        row = conn.execute('SELECT hours, resolved_at FROM festival_hour_watch WHERE key=?', (key,)).fetchone()
        if not row:
            conn.execute('INSERT INTO festival_hour_watch(key,name,start,end,source,hours,first_seen,last_seen,resolved_at) VALUES(?,?,?,?,?,?,?,?,?)',
                         (key, e['t'], e['a'], e['b'], e['s'], hours, stamp, stamp, stamp if hours else None))
            new.append({'key': key, 'name': e['t'], 'start': e['a'], 'end': e['b'], 'source': e['s'], 'hours': hours, 'venue': (e.get('v') or [''])[0]})
        else:
            conn.execute('UPDATE festival_hour_watch SET name=?, start=?, end=?, hours=?, last_seen=?, resolved_at=CASE WHEN ?<>\'\' THEN COALESCE(resolved_at, ?) ELSE NULL END WHERE key=?',
                         (e['t'], e['a'], e['b'], hours, stamp, hours, stamp, key))
    conn.commit()
    pending = [dict(zip(('key', 'name', 'start', 'end', 'source'), r)) for r in conn.execute(
        "SELECT key,name,start,end,source FROM festival_hour_watch WHERE resolved_at IS NULL AND end>=? ORDER BY start", (t,)) if r[0] in seen]
    soon = (today + dt.timedelta(days=SOON_DAYS)).isoformat()
    new_keys = {n['key'] for n in new}
    listed = [p for p in pending if p['key'] in new_keys or p['start'] <= soon or today.weekday() == 0]
    return {'new': new, 'pending': len(pending), 'listed': listed, 'full': today.weekday() == 0}


def collect(conn, today=None, now=None, first_seen_path=FIRST_SEEN, matomo=None, catalog_path=CATALOG):
    from src.source_watch import initialize
    initialize(conn)
    today = today or dt.date.today()
    now = now or dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(hours=24)).isoformat(timespec='seconds')
    alerts = [dict(zip(('source', 'kind', 'detail', 'first_seen_at'), r)) for r in conn.execute(
        'SELECT source,kind,detail,first_seen_at FROM source_alerts WHERE resolved_at IS NULL ORDER BY first_seen_at')]
    resolved = [dict(zip(('source', 'kind'), r)) for r in conn.execute('SELECT source,kind FROM source_alerts WHERE resolved_at>=?', (since,))]
    vol_now, vol_week = _volumes(conn, today), _volumes(conn, today - dt.timedelta(days=7))
    cov = _coverage(conn, today)
    sources = []
    for s, n in vol_now.items():
        before = vol_week.get(s)
        acts, timed = cov.get(s, (0, 0))
        sources.append({'source': s, 'acts': n, 'week_ago': before, 'change': (n - before) / before if before else None,
                        'timed_share': timed / acts if acts else None})
    sources.sort(key=lambda x: -x['acts'])
    runs = dict(conn.execute('SELECT status, COUNT(*) FROM automation_runs WHERE started_at>=? GROUP BY status', (since,)).fetchall())
    # Último fallo de cada trabajo en 24 h y estado de su última pasada (para saber si ya se recuperó).
    failing = [dict(zip(('job', 'status', 'error', 'last'), r)) for r in conn.execute(
        """SELECT a.job_name, a.status, a.error, (SELECT b.status FROM automation_runs b WHERE b.job_name=a.job_name AND b.status<>'running' ORDER BY b.id DESC LIMIT 1)
           FROM automation_runs a WHERE a.id IN (SELECT MAX(id) FROM automation_runs WHERE started_at>=? AND status NOT IN ('completed','running','skipped') GROUP BY job_name)
           ORDER BY a.job_name""", (since,))]
    age = lambda iso: max(0, (now - dt.datetime.fromisoformat(iso).astimezone(dt.timezone.utc)).days) if iso else 0
    opened = {a['source']: a for a in alerts}
    for a in alerts:
        a['triage'] = dict(zip(('class', 'reason'), triage(a['kind'], a['detail'], age(a['first_seen_at']))))
    for f in failing:
        alert = opened.get(f['job'])
        f['triage'] = dict(zip(('class', 'reason'), triage('SUSPECT' if f['status'] == 'suspect' else 'JOB', f['error'], age(alert['first_seen_at']) if alert else 0,
                                                        recovered=f['last'] in ('completed', 'skipped'))))
    order = {'revisar': 0, 'esperar': 1, 'suelto': 2}
    alerts.sort(key=lambda a: order[a['triage']['class']])
    row = conn.execute("""SELECT finished_at, result_json FROM automation_runs WHERE kind='publish' AND status='completed'
                          ORDER BY id DESC LIMIT 1""").fetchone()
    publication = None
    if row:
        result = json.loads(row[1] or '{}')
        publication = {'at': row[0], 'counts': result.get('counts') or {}, 'deploy': (result.get('deploy') or {}).get('status'),
                       'links': (result.get('links') or {}).get('broken') if isinstance(result.get('links'), dict) else None}
    new_by_day = {}
    try:
        seen = json.loads(Path(first_seen_path).read_text(encoding='utf-8'))
        for value in seen.values():
            if isinstance(value, str) and len(value) >= 10 and value[:4].isdigit(): new_by_day[value[:10]] = new_by_day.get(value[:10], 0) + 1
    except (OSError, ValueError):
        pass
    last7 = [(today - dt.timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    return {'today': today.isoformat(), 'alerts': alerts, 'resolved': resolved, 'sources': sources,
            'total_acts': sum(vol_now.values()), 'total_week_ago': sum(vol_week.values()) if vol_week else None,
            'runs': runs, 'failing': failing, 'publication': publication,
            'new': [(d, new_by_day.get(d, 0)) for d in last7], 'traffic': matomo_yesterday(today) if matomo is None else matomo,
            'festivals': _festivals(conn, today), 'ai': _ai(conn, since, today), 'fest_watch': _festival_watch(conn, today, now, catalog_path)}


def _tokens(value, out):
    """Suma input_tokens/output_tokens en cualquier nivel del resultado de un trabajo."""
    if isinstance(value, dict):
        for k, v in value.items():
            if k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens') and isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + int(v)
            else: _tokens(v, out)
    elif isinstance(value, list):
        for v in value: _tokens(v, out)
    return out


def _ai(conn, since, today):
    """Lo que ha hecho la IA en las últimas 24 h (auditoría del 25-10-2026): tokens, sugerencias por tarea, categorías
    y fusiones decididas por IA, datos descartados por no pasar la cita; los lunes, una muestra de fusiones para revisar."""
    have = lambda t: bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone())
    if not have('ai_suggestion_log'): return None
    tokens = {}
    for (rj,) in conn.execute("SELECT result_json FROM automation_runs WHERE kind IN ('ai','ai_agenda','festival_finder') AND started_at>=?", (since,)):
        try: _tokens(json.loads(rj or '{}'), tokens)
        except ValueError: pass
    if have('ai_batches'):
        for (uj,) in conn.execute("SELECT usage_json FROM ai_batches WHERE ended_at>=?", (since,)):
            try: _tokens(json.loads(uj or '{}'), tokens)
            except ValueError: pass
    by_task = dict(conn.execute("SELECT task, COUNT(*) FROM ai_suggestion_log WHERE created_at>=? GROUP BY task", (since,)).fetchall())
    from src.ai_assist import APPLY_CATEGORY, APPLY_DUPLICATE
    categories = conn.execute("SELECT COUNT(*) FROM ai_suggestion_log WHERE task='categoria' AND confidence>=? AND created_at>=?", (APPLY_CATEGORY, since)).fetchone()[0]
    merges = conn.execute("SELECT COUNT(*) FROM ai_suggestion_log WHERE task='duplicado' AND answer='mismo' AND confidence>=? AND created_at>=?", (APPLY_DUPLICATE, since)).fetchone()[0]
    dropped = conn.execute("SELECT COUNT(*) FROM ai_suggestion_log WHERE task='datos' AND reason LIKE '%descartados%' AND created_at>=?", (since,)).fetchone()[0]
    sample = []
    if today.weekday() == 0:  # lunes: 20 fusiones de la semana para mirar a mano
        week = (dt.datetime.fromisoformat(since) - dt.timedelta(days=6)).isoformat(timespec='seconds')
        title = lambda key: (conn.execute('SELECT title FROM source_records WHERE source=? AND id=?', tuple(key.split(':', 1))).fetchone() or [key])[0] if ':' in key else key
        for item, reason, conf in conn.execute("SELECT item, reason, confidence FROM ai_suggestion_log WHERE task='duplicado' AND answer='mismo' AND confidence>=? AND created_at>=? ORDER BY random() LIMIT 20", (APPLY_DUPLICATE, week)):
            a, _, b = item.partition('|'); sample.append({'a': title(a), 'b': title(b), 'a_key': a, 'b_key': b, 'reason': reason, 'confidence': conf})
    return {'tokens': tokens, 'by_task': by_task, 'categories': categories, 'merges': merges, 'dropped': dropped, 'sample': sample}


def _festivals(conn, today):
    try:
        from src.festival_finder import summary
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='festival_programs'").fetchone(): return None
        return summary(conn, today)
    except Exception:
        return None


def matomo_yesterday(today):
    from src.mailer import env_value
    base, token = env_value('MATOMO_URL'), env_value('MATOMO_TOKEN')
    if not base or not token: return None
    day = (today - dt.timedelta(days=1)).isoformat()
    params = {'module': 'API', 'method': 'API.getBulkRequest', 'format': 'JSON',
              'urls[0]': urllib.parse.urlencode({'method': 'VisitsSummary.get', 'idSite': MATOMO_SITE, 'period': 'day', 'date': day}),
              'urls[1]': urllib.parse.urlencode({'method': 'Actions.getSiteSearchKeywords', 'idSite': MATOMO_SITE, 'period': 'day', 'date': day, 'filter_limit': 5})}
    data = urllib.parse.urlencode({'token_auth': token}).encode()
    try:
        from src.network import tls_context
        url = base.rstrip('/') + '/index.php?' + urllib.parse.urlencode(params)
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method='POST'), timeout=20, context=tls_context()) as r:
            summary, searches = json.loads(r.read().decode())
        return {'day': day, 'visits': summary.get('nb_visits', 0), 'visitors': summary.get('nb_uniq_visitors'), 'actions': summary.get('nb_actions', 0),
                'searches': [(s.get('label'), s.get('nb_visits')) for s in (searches or [])][:5]}
    except Exception as error:
        return {'error': type(error).__name__}


def _pct(x):
    return '' if x is None else '%d %%' % round(x * 100)


def _delta(x):
    if x is None: return '<span style="color:#999">nueva</span>'
    color = '#b42318' if x <= -NOTABLE else '#067647' if x >= NOTABLE else '#555'
    return '<span style="color:%s">%+d %%</span>' % (color, round(x * 100))


def render(data):
    """(asunto, html, texto) del parte."""
    day = dt.date.fromisoformat(data['today'])
    alerts, pub = data['alerts'], data['publication']
    state = 'rojo' if any(a['kind'] in ('PUBLISH_STALE', 'ACTS_DROP') for a in alerts) else 'ámbar' if alerts or data['failing'] else 'verde'
    dot = {'verde': '#12b76a', 'ámbar': '#f79009', 'rojo': '#d92d20'}[state]
    review = sum(1 for a in alerts if (a.get('triage') or {}).get('class', 'revisar') == 'revisar')
    subject = 'Ontoca · parte del %s · %s' % (day.strftime('%d-%m'), ('%d alerta%s · %s' % (len(alerts), 's' if len(alerts) != 1 else '',
              '%d para revisar' % review if review else 'nada que revisar')) if alerts else 'todo en orden')
    td = 'style="padding:5px 8px;border-bottom:1px solid #eee"'
    tdr = 'style="padding:5px 8px;border-bottom:1px solid #eee;text-align:right"'
    h2 = lambda t: '<h2 style="font-size:15px;margin:22px 0 8px">%s</h2>' % t
    parts = ['<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222;max-width:680px">',
             '<p style="font-size:18px;margin:0 0 4px"><span style="display:inline-block;width:10px;height:10px;border-radius:50%%;background:%s"></span> Parte del %s</p>' % (dot, day.strftime('%d-%m-%Y'))]
    # Alertas
    parts.append(h2('Alertas abiertas (%d)' % len(alerts)))
    if alerts:
        parts.append('<table style="border-collapse:collapse;width:100%%">%s</table>' % ''.join(
            '<tr><td %s><b>%s</b> %s<br>%s<br><span style="color:#666;font-size:12px">%s · desde %s</span></td></tr>' % (
                td, esc(a['source']), LABELS.get(a['kind'], a['kind']), _badge(a['triage']) if a.get('triage') else '', esc(a['detail']), esc(a['first_seen_at'][:10])) for a in alerts))
    else:
        parts.append('<p style="color:#067647;margin:0">Ninguna.</p>')
    if data['resolved']:
        parts.append('<p style="color:#555">Cerradas en las últimas 24 h: %s.</p>' % esc(', '.join('%s (%s)' % (r['source'], LABELS.get(r['kind'], r['kind'])) for r in data['resolved'])))
    # Web
    parts.append(h2('Web'))
    if pub:
        c = pub['counts']
        parts.append('<table style="border-collapse:collapse">' + ''.join('<tr><td %s>%s</td><td %s><b>%s</b></td></tr>' % (td, k, tdr, esc(v)) for k, v in [
            ('Última publicación', (pub['at'] or '')[:16].replace('T', ' ') + ' UTC'), ('Fichas publicadas', c.get('events', '')),
            ('Próximos 14 días', c.get('upcoming_14_days', '')), ('Con traducción', c.get('translations', '')), ('Despliegue', pub.get('deploy') or '')]) + '</table>')
    else:
        parts.append('<p>Sin publicación correcta registrada.</p>')
    new = data['new']
    parts.append('<p style="margin:10px 0 0">Planes nuevos en la web: <b>%d</b> ayer · %d en 7 días <span style="color:#777">(%s)</span></p>' % (
        new[-1][1] if new else 0, sum(n for _, n in new), esc(' · '.join('%s %d' % (d[8:10], n) for d, n in new))))
    t = data.get('traffic')
    if t and not t.get('error'):
        parts.append('<p style="margin:6px 0 0">Visitas (%s): <b>%s</b> · acciones %s%s</p>' % (esc(t['day'][8:10] + '-' + t['day'][5:7]), esc(t['visits']), esc(t['actions']),
                     (' · búsquedas: ' + esc(', '.join('%s (%s)' % s for s in t['searches']))) if t.get('searches') else ''))
    elif t and t.get('error'):
        parts.append('<p style="color:#777">Matomo no respondió (%s).</p>' % esc(t['error']))
    # Fuentes
    tot, before = data['total_acts'], data['total_week_ago']
    parts.append(h2('Fuentes · actos en los próximos 30 días'))
    parts.append('<p style="margin:0 0 8px">Total: <b>%s</b>%s · %d fuentes con actos</p>' % (f'{tot:,}'.replace(',', '.'), (' · hace 7 días %s' % f'{before:,}'.replace(',', '.')) if before else '', len(data['sources'])))
    top = data['sources'][:TOP_SOURCES]
    notable = [s for s in data['sources'][TOP_SOURCES:] if s['change'] is not None and abs(s['change']) >= NOTABLE and max(s['acts'], s['week_ago'] or 0) >= 10]
    rows = top + notable
    if rows:
        parts.append('<table style="border-collapse:collapse;width:100%%"><tr><th %s>Fuente</th><th %s>Actos</th><th %s>vs 7 días</th><th %s>Con hora</th></tr>%s</table>' % (
            td, tdr, tdr, tdr, ''.join('<tr><td %s>%s</td><td %s>%s</td><td %s>%s</td><td %s>%s</td></tr>' % (
                td, esc(s['source']), tdr, s['acts'], tdr, _delta(s['change']), tdr, _pct(s['timed_share'])) for s in rows)))
        if notable: parts.append('<p style="color:#777;font-size:12px">Debajo de las %d mayores, solo las que cambian un %d %% o más.</p>' % (TOP_SOURCES, NOTABLE * 100))
    else:
        parts.append('<p style="color:#777">Aún no hay medidas de volumen (empiezan con la primera pasada del motor).</p>')
    fw = data.get('fest_watch')
    if fw and (fw['new'] or fw['listed']):
        day2 = lambda d: '%s/%s' % (d[8:10], d[5:7]) if d else ''
        parts.append(h2('Festivales y fiestas'))
        if fw['new']:
            parts.append('<p style="margin:0 0 4px">Nuevos detectados:</p><ul style="margin:0;padding-left:18px">%s</ul>' % ''.join(
                '<li><b>%s</b> · %s → %s · %s · %s</li>' % (esc(n['name']), day2(n['start']), day2(n['end']), esc(n['source']),
                                                            esc('hora: ' + n['hours']) if n['hours'] else '<span style="color:#b42318">sin horario encontrado</span>') for n in fw['new']))
        if fw['listed']:
            title = 'Sin horario encontrado (%d pendientes%s)' % (fw['pending'], '' if fw['full'] else '; hoy, los nuevos y los que empiezan esta semana')
            parts.append('<p style="margin:10px 0 4px">%s:</p><ul style="margin:0;padding-left:18px">%s</ul>' % (esc(title), ''.join(
                '<li>%s · empieza el %s · <code>%s</code></li>' % (esc(p['name']), day2(p['start']), esc(p['key'])) for p in fw['listed'])))
            parts.append('<p style="color:#777;font-size:12px;margin:6px 0 0">Para poner la hora a mano: config/horarios_festivales.json, con la clave de la ficha, los días, '
                         'si es apertura o primera sesión y la fuente. Ninguna actualización la sobrescribe.</p>')
    elif fw and fw['pending']:
        parts.append('<p style="color:#777;margin-top:18px">Festivales sin horario encontrado: %d pendientes, sin novedades.</p>' % fw['pending'])
    ai = data.get('ai')
    if ai:
        tk = ai['tokens']
        parts.append(h2('IA · últimas 24 h'))
        parts.append('<p style="margin:0">%s tokens de entrada · %s de salida · %s sugerencias (%s)</p>' % (
            f"{tk.get('input_tokens', 0):,}".replace(',', '.'), f"{tk.get('output_tokens', 0):,}".replace(',', '.'), sum(ai['by_task'].values()),
            esc(', '.join('%s %d' % kv for kv in sorted(ai['by_task'].items())) or 'ninguna')))
        parts.append('<p style="margin:4px 0 0">Categorías decididas por IA: <b>%d</b> · fusiones de duplicados por IA: <b>%d</b> · fichas con datos descartados por no pasar la cita: <b>%d</b></p>'
                     % (ai['categories'], ai['merges'], ai['dropped']))
        if ai['sample']:
            parts.append('<p style="margin:8px 0 4px">Muestra semanal de fusiones por IA para revisar (si alguna no es el mismo acto, dímelo y se corrige):</p><ol style="margin:0;padding-left:20px">%s</ol>'
                         % ''.join('<li>%s <span style="color:#777">=</span> %s <span style="color:#777">· %.2f · %s</span></li>' % (esc(x['a']), esc(x['b']), x['confidence'], esc(x['reason'])) for x in ai['sample']))
    # Motor
    r = data['runs']
    parts.append(h2('Motor · últimas 24 h'))
    parts.append('<p style="margin:0">%d pasadas correctas · %d con problemas</p>' % (r.get('completed', 0), sum(v for k, v in r.items() if k not in ('completed', 'skipped', 'running'))))
    if data['failing']:
        parts.append('<ul style="margin:6px 0;padding-left:18px">%s</ul>' % ''.join('<li><b>%s</b>: %s %s<br><span style="color:#777;font-size:12px">%s</span></li>' % (
            esc(f['job']), esc(f['status']), _badge(f['triage']) if f.get('triage') else '', esc((f['error'] or '')[:200])) for f in data['failing']))
    parts.append('<p style="color:#999;font-size:12px;margin-top:24px">Generado por el motor de Ontoca en el Mac. Las alertas también llegan al momento, una sola vez.</p></div>')
    text = '\n'.join([subject, '', 'Alertas abiertas: %d' % len(alerts)] + ['- [%s] %s %s: %s' % (TRIAGE[(a.get('triage') or {}).get('class', 'revisar')][0], a['source'], LABELS.get(a['kind'], a['kind']), a['detail']) for a in alerts] +
                     ['', 'Fichas publicadas: %s · próximos 14 días: %s' % ((pub or {}).get('counts', {}).get('events', '?'), (pub or {}).get('counts', {}).get('upcoming_14_days', '?')),
                      'Planes nuevos ayer: %d' % (new[-1][1] if new else 0), 'Actos de las fuentes en 30 días: %s' % tot])
    return subject, ''.join(parts), text


def run(conn, job, today=None, now=None, send=None, out_dir=OUT_DIR):
    data = collect(conn, today=today, now=now)
    subject, body, text = render(data)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    path = out / ('%s.html' % data['today'])
    path.write_text('<!doctype html><meta charset="utf-8"><title>%s</title>%s' % (esc(subject), body), encoding='utf-8')
    if job.get('send', True) is False:
        return {'status': 'completed', 'file': str(path), 'email': {'status': 'skipped', 'reason': 'send=false'}}
    if send is None:
        from src.mailer import send
    mail = send(subject, body, text, job.get('to') or 'hola@ontoca.com')
    # Sin clave el parte queda en disco y el trabajo cuenta como hecho; si Brevo falla, se reintenta.
    status = 'failed' if mail.get('status') == 'failed' else 'completed'
    return {'status': status, 'file': str(path), 'email': mail, 'alerts': len(data['alerts'])}
