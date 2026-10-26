"""Vigilancia de fuentes y del motor, con aviso por correo (25-10-2026).

Completa src/time_health.py (fuentes que dejan de dar horas) con tres alertas más, en la misma
tabla ``source_alerts``:

  · ACTS_DROP: una fuente trae de pronto muchos menos actos. Cada día se guarda cuántos actos
    activos tiene cada fuente en los próximos 30 días (``source_volume``) y se compara con la
    mediana de los 7 días anteriores; por debajo de la mitad (o a cero) se abre la alerta. Una
    fuente que desaparece del todo cuenta como cero. Lo que ya teníamos no se borra: la alerta es
    porque lo nuevo deja de entrar (web rediseñada, conector roto).
  · JOB_FAILING: un trabajo del motor lleva tres pasadas seguidas sin terminar bien.
  · PUBLISH_STALE: la web lleva más de 12 horas sin publicarse.

Cada alerta nueva se avisa una vez por correo a hola@ontoca.com (src/mailer.py) y, en el Mac,
con una notificación. Las alertas se cierran solas cuando el problema desaparece. Nada se borra.
"""
from __future__ import annotations

import datetime as dt
import json

from src.time_health import _notify, initialize as init_health

WINDOW_DAYS = 30
MIN_HISTORY = 3
MIN_USUAL_ACTS = 10    # fuentes pequeñas bailan mucho de un día a otro
DROP_RATIO = 0.5
JOB_FAILURES = 3
PUBLISH_STALE_HOURS = 12
EMAIL_MAX_AGE_DAYS = 2  # una alerta más vieja sin avisar (p. ej. antes de poner la clave) no se manda
LABELS = {'ACTS_DROP': 'trae muchos menos actos', 'TIME_COVERAGE_DROP': 'ha dejado de dar horas',
          'JOB_FAILING': 'falla en cada pasada', 'PUBLISH_STALE': 'la web no se publica'}


def initialize(conn):
    init_health(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS source_volume (source TEXT NOT NULL, day TEXT NOT NULL, acts INTEGER NOT NULL,
      measured_at TEXT NOT NULL, PRIMARY KEY(source, day))""")
    columns = {r[1] for r in conn.execute('PRAGMA table_info(source_alerts)')}
    if 'emailed_at' not in columns: conn.execute('ALTER TABLE source_alerts ADD COLUMN emailed_at TEXT')


def measure_volume(conn, today):
    """{fuente: actos activos (no excluidos) que caen en los próximos 30 días}."""
    end = (today + dt.timedelta(days=WINDOW_DAYS)).isoformat()
    rows = conn.execute("""SELECT source, COUNT(*) FROM source_records WHERE eligibility<>'exclude'
        AND substr(start_date,1,10)<=? AND substr(COALESCE(NULLIF(end_date,''),start_date),1,10)>=? GROUP BY source""", (end, today.isoformat())).fetchall()
    return {s: n for s, n in rows}


def _open(conn, source, kind):
    return conn.execute('SELECT id FROM source_alerts WHERE source=? AND kind=? AND resolved_at IS NULL', (source, kind)).fetchone()


def _raise(conn, source, kind, detail, now, opened):
    row = _open(conn, source, kind)
    if row:
        conn.execute('UPDATE source_alerts SET last_seen_at=?, detail=? WHERE id=?', (now, detail, row[0])); return
    conn.execute('INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES(?,?,?,?,?)', (source, kind, detail, now, now))
    opened.append({'source': source, 'kind': kind, 'detail': detail})


def _clear(conn, source, kind, now, resolved):
    row = _open(conn, source, kind)
    if row:
        conn.execute('UPDATE source_alerts SET resolved_at=? WHERE id=?', (now, row[0])); resolved.append({'source': source, 'kind': kind})


def _festival_sources():
    """Fuentes de un solo festival (config/venues.json, type festival): al acabar el festival se quedan a cero
    sin que nada se haya roto, así que no cuentan para ACTS_DROP."""
    from pathlib import Path
    try: venues = json.loads((Path(__file__).resolve().parents[1] / 'config' / 'venues.json').read_text(encoding='utf-8'))
    except (OSError, ValueError): return set()
    venues = venues.get('venues', venues) if isinstance(venues, dict) else venues
    return {'venue_' + v['slug'] for v in venues if v.get('type') == 'festival'}


def check_volume(conn, today, now, opened, resolved):
    current = measure_volume(conn, today)
    skip = _festival_sources()
    since = (today - dt.timedelta(days=7)).isoformat()
    known = {r[0] for r in conn.execute('SELECT DISTINCT source FROM source_volume WHERE day>=? AND day<?', (since, today.isoformat()))}
    for source in sorted(set(current) | known):
        acts = current.get(source, 0)
        if source in skip: continue
        conn.execute("""INSERT INTO source_volume(source,day,acts,measured_at) VALUES(?,?,?,?)
            ON CONFLICT(source,day) DO UPDATE SET acts=excluded.acts, measured_at=excluded.measured_at""", (source, today.isoformat(), acts, now))
        history = sorted(r[0] for r in conn.execute('SELECT acts FROM source_volume WHERE source=? AND day<? ORDER BY day DESC LIMIT 7', (source, today.isoformat())))
        if len(history) < MIN_HISTORY: continue
        usual = history[len(history) // 2]
        if usual >= MIN_USUAL_ACTS and acts < usual * DROP_RATIO:
            detail = ('%d actos en los próximos 30 días frente a %d habituales' % (acts, usual)) + (': no llega nada' if not acts else '') + '. Revisar el conector o la web de la fuente.'
            _raise(conn, source, 'ACTS_DROP', detail, now, opened)
        elif acts >= usual * DROP_RATIO:
            _clear(conn, source, 'ACTS_DROP', now, resolved)
    return current


def check_jobs(conn, config, now_dt, opened, resolved):
    now = now_dt.isoformat(timespec='seconds')
    for job in (config or {}).get('jobs', []):
        if not job.get('enabled', True): continue
        statuses = [r[0] for r in conn.execute("""SELECT status FROM automation_runs WHERE job_name=? AND status NOT IN ('running')
            ORDER BY id DESC LIMIT ?""", (job['name'], JOB_FAILURES))]
        if len(statuses) == JOB_FAILURES and all(s not in ('completed', 'skipped') for s in statuses):
            last = conn.execute('SELECT error FROM automation_runs WHERE job_name=? ORDER BY id DESC LIMIT 1', (job['name'],)).fetchone()
            _raise(conn, job['name'], 'JOB_FAILING', 'Últimas %d pasadas: %s. %s' % (JOB_FAILURES, ', '.join(statuses), ((last or [''])[0] or '')[:240]), now, opened)
        elif statuses and statuses[0] in ('completed', 'skipped'):
            _clear(conn, job['name'], 'JOB_FAILING', now, resolved)
        if job.get('kind') == 'publish':
            row = conn.execute("SELECT MAX(finished_at) FROM automation_runs WHERE job_name=? AND status='completed'", (job['name'],)).fetchone()
            last_ok = dt.datetime.fromisoformat(row[0]) if row and row[0] else None
            if last_ok and last_ok.tzinfo is None: last_ok = last_ok.replace(tzinfo=dt.timezone.utc)
            if last_ok and now_dt - last_ok > dt.timedelta(hours=PUBLISH_STALE_HOURS):
                _raise(conn, job['name'], 'PUBLISH_STALE', 'Última publicación correcta: %s (hace %d h).' % (row[0][:16].replace('T', ' '), (now_dt - last_ok).total_seconds() // 3600), now, opened)
            elif last_ok:
                _clear(conn, job['name'], 'PUBLISH_STALE', now, resolved)


def alert_email(alerts):
    rows = ''.join('<tr><td style="padding:6px 10px;border-bottom:1px solid #eee"><b>%s</b> %s</td></tr><tr><td style="padding:0 10px 10px;color:#555;border-bottom:1px solid #eee">%s</td></tr>'
                   % (_esc(a['source']), LABELS.get(a['kind'], a['kind']), _esc(a['detail'])) for a in alerts)
    subject = ('Ontoca · alerta: %s %s' % (alerts[0]['source'], LABELS.get(alerts[0]['kind'], ''))) if len(alerts) == 1 else 'Ontoca · %d alertas nuevas' % len(alerts)
    html = '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222"><p>El motor de Ontoca ha abierto %s:</p><table style="border-collapse:collapse;width:100%%;max-width:640px">%s</table><p style="color:#777;font-size:12px">La alerta se cierra sola cuando la fuente se recupera. Lo ya publicado no se borra.</p></div>' % ('una alerta' if len(alerts) == 1 else '%d alertas' % len(alerts), rows)
    text = '\n'.join('- %s %s: %s' % (a['source'], LABELS.get(a['kind'], a['kind']), a['detail']) for a in alerts)
    return subject, html, text


def email_new_alerts(conn, now_dt, send=None):
    """Un correo con las alertas abiertas que aún no se han avisado (cada alerta, una sola vez)."""
    since = (now_dt - dt.timedelta(days=EMAIL_MAX_AGE_DAYS)).isoformat(timespec='seconds')
    rows = conn.execute("""SELECT id,source,kind,detail FROM source_alerts WHERE resolved_at IS NULL AND emailed_at IS NULL AND first_seen_at>=?
        ORDER BY first_seen_at""", (since,)).fetchall()
    if not rows: return None
    alerts = [dict(zip(('id', 'source', 'kind', 'detail'), r)) for r in rows]
    if send is None:
        from src.mailer import send
    result = send(*alert_email(alerts))
    if result.get('status') == 'sent':
        with conn:
            conn.executemany('UPDATE source_alerts SET emailed_at=? WHERE id=?', [(now_dt.isoformat(timespec='seconds'), a['id']) for a in alerts])
    return {**result, 'alerts': len(alerts)}


def check(conn, config=None, today=None, now=None, notify=_notify, send=None):
    """Una pasada: mide, abre o cierra alertas y avisa de las nuevas. Devuelve lo que ha cambiado."""
    initialize(conn)
    now_dt = now or dt.datetime.now(dt.timezone.utc)
    today = today or dt.date.today()
    stamp = now_dt.isoformat(timespec='seconds')
    opened, resolved = [], []
    with conn:
        check_volume(conn, today, stamp, opened, resolved)
        check_jobs(conn, config, now_dt, opened, resolved)
    for a in opened:
        if notify: notify('Ontoca: %s %s' % (a['source'], LABELS.get(a['kind'], '')), a['detail'])
    mail = email_new_alerts(conn, now_dt, send=send)
    return {'opened': opened, 'resolved': resolved, 'email': mail}


def _esc(value):
    import html
    return html.escape(str(value or ''))
