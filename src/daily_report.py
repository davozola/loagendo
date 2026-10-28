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
import sqlite3
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
    # Sesiones con hora de cada festival en la web (28-10-2026, David): dos sesiones sueltas no son el programa (DART). El festival
    # sigue pendiente hasta que su cobertura es completa (src/festival_finder.coverage).
    from src.festival_finder import coverage, _connected_festivals
    connected = _connected_festivals()
    kids = {}
    for e in items:
        fs = e.get('fs')
        if fs and not fs[2] and (e.get('tm') or any(o[1] for o in e.get('o') or [])):
            k = kids.setdefault(fs[0], {'n': 0, 'days': set()}); k['n'] += 1; k['days'].update([o[0] for o in e.get('o') or [] if o[1]] or [e['a']])
    for e in items:
        fs = e.get('fs')
        head = (bool(fs) and bool(fs[2])) or (not fs and e.get('f') == 'festival' and e['a'] != e['b'])
        if not head or e.get('kd') == 'exhibition' or e.get('f') == 'exhibition' or e['b'] < t or e['a'] > horizon: continue
        try: span = (dt.date.fromisoformat(e['b']) - dt.date.fromisoformat(e['a'])).days
        except ValueError: continue
        if span > SEASON_DAYS: continue
        key = '%s:%s' % (e['s'], e['i'])
        hours = 'programa' if e.get('pf') else 'a mano' if e.get('mh') else 'por días' if e.get('hb') else 'con sesiones' if any(o[1] for o in e.get('o') or []) else ''
        if not hours and fs:
            k = kids.get(fs[0]) or {'n': 0, 'days': set()}
            if coverage(e['a'], e['b'], k['days'], k['n'], fs[0] in connected) == 'completa': hours = '%d sesiones' % k['n']
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



# ---------- Calidad del conjunto (26-10-2026): frescura, cobertura, duplicados, correcciones ----------
AUTOMATION = ROOT / 'config' / 'automation.json'
AUDIT_DIR = ROOT / 'reports' / 'auditorias'
STALE_FACTOR = 2.5        # una fuente está atrasada si su última lectura buena es más vieja que 2,5 veces su frecuencia
STALE_MIN_HOURS = 12
VENUE_PAST_DAYS = 60      # sala con actividad en los últimos 60 días…
VENUE_AHEAD_DAYS = 60     # …y nada en los próximos 60: ha dejado de aportar
VENUE_MIN_PAST = 5
DUP_DAYS = 14             # duplicados sospechosos: actos de un día en las próximas 2 semanas
DUP_GENERIC = {'taller', 'tallers', 'concert', 'concerts', 'concierto', 'festival', 'cicle', 'ciclo', 'espectacle', 'espectaculo', 'jornades', 'jornada',
               'projeccio', 'cinema', 'cinefòrum', 'cineforum', 'visita', 'visites', 'guiada', 'festa', 'major', 'fiesta', 'barcelona', 'edicio', 'activitat',
               'familiar', 'infantil', 'xerrada', 'conferencia', 'presentacio', 'llibre', 'exposicio', 'nou', 'tardor', 'nadal', 'sessio', 'club', 'live', 'night',
               'party', 'session', 'dj', 'amb', 'para', 'per', 'del', 'dels', 'les', 'los', 'las', 'the', 'and'}


def _expected_minutes():
    """{fuente: minutos entre lecturas} según config/automation.json; las salas, por su trabajo común."""
    try: jobs = [j for j in json.loads(AUTOMATION.read_text(encoding='utf-8'))['jobs'] if j.get('enabled', True)]
    except (OSError, ValueError, KeyError): return {}, {}
    by_source = {j['source']: j['every_minutes'] for j in jobs if j.get('source')}
    by_kind = {j['kind']: j['every_minutes'] for j in jobs}
    return by_source, by_kind


def _active_sources():
    """Fuentes que el motor debe leer hoy: trabajos con fuente, salas activas (agendas IA y schema.org) y Eventbrite."""
    out = set(_expected_minutes()[0])
    try:
        from src.ai_agenda import load_agendas
        out |= {'venue_ia_' + a['slug'] for a in load_agendas() if a.get('activa') and not a.get('descartada')}
    except Exception: pass
    try:
        venues = json.loads((ROOT / 'config' / 'venues.json').read_text(encoding='utf-8'))
        venues = venues['venues'] if isinstance(venues, dict) else venues
        out |= {'venue_' + v['slug'] for v in venues if v.get('enabled') and v.get('slug')}
    except (OSError, ValueError, KeyError, TypeError): pass
    return out


def _freshness(conn, now):
    """Fuentes atrasadas respecto a su propia frecuencia: [{source, hours, expected_hours, last_ok, error}]."""
    by_source, by_kind = _expected_minutes()
    last_ok = dict(conn.execute("SELECT source, MAX(COALESCE(finished_at, started_at)) FROM sync_runs WHERE status='completed' GROUP BY source").fetchall())
    out = []
    for s in sorted(_active_sources()):
        every = by_source.get(s) or (by_kind.get('ai_agenda') if s.startswith('venue_ia_') else by_kind.get('eventbrite') if s == 'venue_eventbrite' else by_kind.get('venues'))
        if not every: continue
        limit_h = max(STALE_MIN_HOURS, every / 60 * STALE_FACTOR)
        ok = last_ok.get(s)
        hours = (now - dt.datetime.fromisoformat(ok).astimezone(dt.timezone.utc)).total_seconds() / 3600 if ok else None
        if hours is None and not conn.execute('SELECT 1 FROM sync_runs WHERE source=? LIMIT 1', (s,)).fetchone(): continue  # nunca leída: aún no toca
        if hours is None or hours > limit_h:
            err = conn.execute("SELECT error FROM sync_runs WHERE source=? AND status<>'completed' ORDER BY id DESC LIMIT 1", (s,)).fetchone()
            out.append({'source': s, 'hours': hours, 'expected_hours': every / 60, 'last_ok': ok, 'error': (err or [''])[0] or ''})
    return sorted(out, key=lambda x: -(x['hours'] or 1e9))


def _snapshot(conn, today, dim, counts):
    """Guarda el recuento del día y devuelve el de hace 7 días (o None)."""
    conn.execute("CREATE TABLE IF NOT EXISTS report_snapshots (day TEXT NOT NULL, dim TEXT NOT NULL, key TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(day, dim, key))")
    with conn:
        conn.executemany("INSERT OR REPLACE INTO report_snapshots(day,dim,key,n) VALUES(?,?,?,?)", [(today.isoformat(), dim, k, n) for k, n in counts.items()])
    before = dict(conn.execute("SELECT key, n FROM report_snapshots WHERE day=? AND dim=?", ((today - dt.timedelta(days=7)).isoformat(), dim)).fetchall())
    return before or None


def _coverage_by(conn, today):
    """Fichas publicables en los próximos 30 días por categoría y por distrito, con la referencia de hace 7 días."""
    end = (today + dt.timedelta(days=30)).isoformat()
    from src.taxonomy import CATEGORIES
    cats, dists = {}, {}
    for cat, district in conn.execute("""SELECT e.category, json_extract(l.projection_json,'$.district') FROM source_records r
            JOIN event_classification e ON e.source=r.source AND e.id=r.id LEFT JOIN listing_projections l ON l.source=r.source AND l.id=r.id
            WHERE r.eligibility<>'exclude' AND e.category NOT IN ('excluida','pendiente')
              AND substr(r.start_date,1,10)<=? AND substr(COALESCE(NULLIF(r.end_date,''),r.start_date),1,10)>=?""", (end, today.isoformat())):
        label = CATEGORIES.get(cat, (cat,))[0]; cats[label] = cats.get(label, 0) + 1
        if district: dists[district] = dists.get(district, 0) + 1
    return {'categories': (cats, _snapshot(conn, today, 'categoria', cats)), 'districts': (dists, _snapshot(conn, today, 'distrito', dists))}


def _venues_lost(conn, today):
    """Salas que aportaban (≥5 actos en los últimos 60 días) y no tienen nada en los próximos 60."""
    past, ahead = (today - dt.timedelta(days=VENUE_PAST_DAYS)).isoformat(), (today + dt.timedelta(days=VENUE_AHEAD_DAYS)).isoformat()
    from src.dedupe import _clean
    stats = {}
    for venue, start, end, source in conn.execute("""SELECT v.venue, substr(r.start_date,1,10), substr(COALESCE(NULLIF(r.end_date,''),r.start_date),1,10), r.source
            FROM source_records r JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
            WHERE r.eligibility<>'exclude' AND substr(r.start_date,1,10)>=? AND substr(r.start_date,1,10)<=? AND julianday(substr(r.end_date,1,10))-julianday(substr(r.start_date,1,10))<=7""", (past, ahead)):
        key = _clean(venue)
        if not key or len(key) < 4: continue
        s = stats.setdefault(key, {'venue': venue, 'past': 0, 'ahead': 0, 'sources': set()})
        if start < today.isoformat(): s['past'] += 1
        else: s['ahead'] += 1
        s['sources'].add(source)
    from src.taxonomy import OUTDOOR_VENUE, norm
    address = re.compile(r"^(?:carrer|c\.|calle|placa|pl\.|plaza|rambla|gran via|avinguda|av\.|passeig|pg\.|diversos|varios)\b|\d")
    lost = [dict(s, sources=sorted(s['sources'])) for s in stats.values() if s['past'] >= VENUE_MIN_PAST and s['ahead'] == 0
            and not address.search(norm(s['venue'])) and not OUTDOOR_VENUE.search(norm(s['venue'])) and s['sources'] != {'venue_eventbrite'}]
    return sorted(lost, key=lambda s: -s['past'])


def _dup_suspects(conn, today):
    """Actos de un día, mismo día y mismo sitio, de fuentes distintas, con una palabra propia del título en común y sin fusionar.
    No son sospechosos dos pases con horas distintas: son sesiones."""
    from src.dedupe import canonical_groups, _title_keys, _same_site, _generic_site, _clean
    groups = canonical_groups(conn)
    root = lambda k: groups.get(k, k)
    end = (today + dt.timedelta(days=DUP_DAYS)).isoformat()
    rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), v.venue, v.lat, v.lon,
            (SELECT GROUP_CONCAT(local_time) FROM candidate_occurrences o WHERE o.source=r.source AND o.id=r.id AND COALESCE(o.local_time,'')<>'')
            FROM source_records r JOIN event_classification e ON e.source=r.source AND e.id=r.id
            LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
            WHERE r.eligibility<>'exclude' AND e.category NOT IN ('excluida','pendiente') AND substr(r.start_date,1,10) BETWEEN ? AND ?
              AND substr(r.start_date,1,10)=substr(COALESCE(NULLIF(r.end_date,''),r.start_date),1,10)""", (today.isoformat(), end)).fetchall()
    by_day = {}
    for s, i, title, day, venue, lat, lon, times in rows:
        words = {w for k in _title_keys(title) for w in k.split() if len(w) >= 4 and w not in DUP_GENERIC} - set(_clean(venue or '').split())
        by_day.setdefault(day, []).append({'key': f'{s}:{i}', 'source': s, 'title': title, 'venue': venue or '', 'lat': lat, 'lon': lon, 'address': '',
                                           'words': words, 'times': set((times or '').split(',')) - {''}})
    out = []
    for day, items in by_day.items():
        for n, a in enumerate(items):
            if _generic_site(a): continue
            for b in items[n + 1:]:
                if a['source'] == b['source'] or root(a['key']) == root(b['key']): continue
                if {a['source'], b['source']} == {'guiabcn', 'opendatabcn_agenda'} and a['key'].split(':')[1] == b['key'].split(':')[1]: continue  # gemelas
                common, least = a['words'] & b['words'], min(len(a['words']), len(b['words']))
                if not common or (len(common) < 2 and len(common) < least) or len(common) < 0.6 * least: continue
                if a['times'] and b['times'] and not (a['times'] & b['times']): continue   # otra hora: otra sesión
                if _same_site(a, b, km=0.15): out.append({'day': day, 'a': a, 'b': b})
    return out


def _corrections(conn, since):
    """Correcciones editoriales de los últimos 7 días (clasificación y exclusiones)."""
    try:
        rows = conn.execute("SELECT new_json FROM classification_override_log WHERE changed_at>=?", (since,)).fetchall()
    except sqlite3.DatabaseError: return None
    excluded = sum(1 for (j,) in rows if '"excluida"' in (j or ''))
    return {'total': len(rows), 'excluded': excluded}


def _safe(fn, *args, default=None):
    """Un indicador que no se puede calcular (tabla que aún no existe, base de pruebas) no tumba el parte."""
    try: return fn(*args)
    except (sqlite3.DatabaseError, OSError, ValueError, KeyError): return default


def _audit(today):
    """Última auditoría semanal (src/weekly_audit.py) de los últimos 7 días: {day, patterns, serious, file}."""
    try: files = sorted(AUDIT_DIR.glob('*.json'))
    except OSError: return None
    for f in reversed(files):
        if (today - dt.timedelta(days=7)).isoformat() <= f.stem[:10] <= today.isoformat():   # nunca una auditoría posterior al día del parte
            try: return json.loads(f.read_text(encoding='utf-8'))
            except ValueError: return None
    return None


_WD_TEXT = {'dilluns': 0, 'dimarts': 1, 'dimecres': 2, 'dijous': 3, 'divendres': 4, 'dissabte': 5, 'diumenge': 6,
            'lunes': 0, 'martes': 1, 'miercoles': 2, 'jueves': 3, 'viernes': 4, 'sabado': 5, 'domingo': 6}
_MO_TEXT = {'gener': 1, 'febrer': 2, 'marc': 3, 'abril': 4, 'maig': 5, 'juny': 6, 'juliol': 7, 'agost': 8, 'setembre': 9, 'octubre': 10, 'novembre': 11,
            'desembre': 12, 'enero': 1, 'febrero': 2, 'marzo': 3, 'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8, 'septiembre': 9, 'noviembre': 11, 'diciembre': 12}


def date_contradictions(conn, today, limit=40):
    """Textos de la fuente con un día de la semana que no es el de la fecha que acompaña («dissabte 30 d'octubre» en
    2026 es viernes; Pinocchio, Open Data, 27-10-2026). Solo fechas dentro del periodo de la propia ficha, para no
    tomar referencias a otros años. No se corrige nada: se avisa para revisarlo a mano."""
    import json as _json, re as _re, unicodedata as _ud
    from mvp.catalog import source_description
    fold = lambda t: ''.join(c for c in _ud.normalize('NFKD', t.lower()) if not _ud.combining(c))
    rx = _re.compile(r"\b(" + '|'.join(_WD_TEXT) + r")\s+(\d{1,2})\s+(?:de\s+|d['’]\s*)(" + '|'.join(_MO_TEXT) + r")\b")
    out = []
    for s, i, title, a, b, raw in conn.execute("""SELECT source,id,title,substr(start_date,1,10),substr(end_date,1,10),raw_json FROM source_records
                                                WHERE end_date>=? AND eligibility<>'exclude'""", (today.isoformat(),)):
        try: d0, d1 = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
        except (TypeError, ValueError): continue
        try: text = fold(str(source_description(_json.loads(raw or '{}'), s) or ''))
        except (ValueError, TypeError, AttributeError): continue
        for m in rx.finditer(text):
            for year in {d0.year, d1.year}:
                try: d = dt.date(year, _MO_TEXT[m.group(3)], int(m.group(2)))
                except ValueError: continue
                if d0 - dt.timedelta(days=1) <= d <= d1 + dt.timedelta(days=1) and d.weekday() != _WD_TEXT[m.group(1)]:
                    out.append({'source': s, 'id': i, 'title': title, 'quote': m.group(0), 'date': d.isoformat()})
                    break
        if len(out) >= limit: break
    return out


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
            'festivals': _festivals(conn, today), 'ai': _ai(conn, since, today), 'fest_watch': _festival_watch(conn, today, now, catalog_path),
            'freshness': _safe(_freshness, conn, now, default=[]), 'coverage': _safe(_coverage_by, conn, today, default={}),
            'venues_lost': _safe(_venues_lost, conn, today, default=[]), 'dups': _safe(_dup_suspects, conn, today, default=[]), 'date_text': _safe(date_contradictions, conn, today, default=[]),
            'corrections': _safe(_corrections, conn, (now - dt.timedelta(days=7)).isoformat(timespec='seconds')), 'audit': _audit(today)}


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
    """(asunto, html, texto) del parte (26-10-2026): arriba lo que pide atención; debajo, los indicadores en pocas líneas."""
    day = dt.date.fromisoformat(data['today'])
    alerts, pub = data['alerts'], data['publication']
    fresh, lost, dups, audit = data.get('freshness') or [], data.get('venues_lost') or [], data.get('dups') or [], data.get('audit')
    review = [a for a in alerts if (a.get('triage') or {}).get('class', 'revisar') == 'revisar']
    waiting = [a for a in alerts if a not in review]
    serious = (audit or {}).get('serious') or []
    # Trabajos cuya última pasada sigue mal y piden revisión (p. ej. Open Data con 373 filas de 4.905: «suspect»).
    jobs_bad = [f for f in data['failing'] if (f.get('triage') or {}).get('class') == 'revisar' and f['last'] not in ('completed', 'skipped')
                and f['job'] not in {a['source'] for a in alerts}]
    attention = len(review) + len(fresh) + len(jobs_bad) + (1 if lost else 0) + (1 if dups else 0) + (1 if serious else 0)
    state = 'rojo' if any(a['kind'] in ('PUBLISH_STALE', 'ACTS_DROP') for a in alerts) or serious else 'ámbar' if attention or waiting else 'verde'
    dot = {'verde': '#12b76a', 'ámbar': '#f79009', 'rojo': '#d92d20'}[state]
    subject = 'Ontoca · parte del %s · %s' % (day.strftime('%d-%m'), ('%d para revisar' % attention) if attention else 'todo en orden')
    td = 'style="padding:4px 8px;border-bottom:1px solid #eee"'
    tdr = 'style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right"'
    h2 = lambda t: '<h2 style="font-size:15px;margin:20px 0 6px">%s</h2>' % t
    li = lambda items: '<ul style="margin:0 0 6px;padding-left:18px">%s</ul>' % ''.join('<li style="margin:2px 0">%s</li>' % x for x in items)
    num = lambda n: f'{n:,}'.replace(',', '.') if isinstance(n, int) else esc(n)
    hrs = lambda h: 'nunca' if h is None else ('%d h' % h if h < 48 else '%d días' % (h // 24))
    parts = ['<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222;max-width:680px">',
             '<p style="font-size:18px;margin:0 0 4px"><span style="display:inline-block;width:10px;height:10px;border-radius:50%%;background:%s"></span> Parte del %s</p>' % (dot, day.strftime('%d-%m-%Y'))]
    # ---------- Requiere atención ----------
    parts.append(h2('Requiere tu atención' + (' (%d)' % attention if attention else '')))
    items = []
    for a in serious[:5]:
        items.append('<b>Error grave</b> (auditoría del %s): <a href="https://ontoca.com/e/%s">%s</a> · %s' % (esc(audit['day'][8:10] + '/' + audit['day'][5:7]), esc(a['key'].replace(':', '/', 1)), esc(a['title']), esc(a['problem'])))
    for a in review:
        items.append('<b>%s</b> %s · %s<br><span style="color:#666;font-size:12px">%s · desde %s</span>' % (esc(a['source']), LABELS.get(a['kind'], a['kind']), _badge(a['triage']) if a.get('triage') else '', esc(a['detail'][:200]), esc(a['first_seen_at'][:10])))
    for f in jobs_bad:
        items.append('<b>%s</b> · última pasada: %s · %s<br><span style="color:#666;font-size:12px">%s</span>' % (esc(f['job']), esc(f['status']), _badge(f['triage']), esc((f['error'] or '')[:200])))
    for f in fresh:
        items.append('<b>%s</b> %s (lee cada %s)%s' % (esc(f['source']), 'nunca se ha leído bien' if f['hours'] is None else 'sin leer bien desde hace ' + hrs(f['hours']), hrs(f['expected_hours']), (' · <span style="color:#666">%s</span>' % esc(f['error'][:120])) if f['error'] else ''))
    if lost:
        items.append('<b>%d sala%s sin nada próximo</b> tras %s: %s' % (len(lost), 's' if len(lost) != 1 else '', 'tener actividad en los últimos 60 días',
                     esc(' · '.join('%s (%d, %s)' % (s['venue'][:40], s['past'], '/'.join(s['sources'])) for s in lost[:6]))))
    if dups:
        items.append('<b>%d posibles duplicados</b> sin fusionar (mismo día, sitio y título; horas distintas no cuentan):%s' % (len(dups), li(
            '%s · %s <span style="color:#777">(%s)</span> = %s <span style="color:#777">(%s)</span>' % (esc(d['day'][8:10] + '/' + d['day'][5:7]), esc(d['a']['title'][:60]), esc(d['a']['source']), esc(d['b']['title'][:60]), esc(d['b']['source'])) for d in dups[:8])))
    dates_txt = data.get('date_text') or []
    if dates_txt:
        items.append('<b>%d textos con día y fecha que no cuadran</b> (de la fuente; no se cambian, revisar o avisar a la fuente):%s' % (len(dates_txt), li(
            '%s <span style="color:#777">(%s)</span> · «%s» es %s' % (esc(d['title'][:60]), esc(d['source']), esc(d['quote']), esc(['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'][dt.date.fromisoformat(d['date']).weekday()])) for d in dates_txt[:8])))
    parts.append(li(items) if items else '<p style="color:#067647;margin:0">Nada. Todo en orden.</p>')
    if waiting:
        parts.append('<p style="color:#555;margin:4px 0">%s (se recupera sola): %s.</p>' % (TRIAGE['esperar'][0], esc(', '.join('%s (%s)' % (a['source'], a['first_seen_at'][:10]) for a in waiting))))
    if data['resolved']:
        parts.append('<p style="color:#555;margin:4px 0">Resueltas en 24 h: %s.</p>' % esc(', '.join('%s (%s)' % (r['source'], LABELS.get(r['kind'], r['kind'])) for r in data['resolved'])))
    # ---------- Indicadores ----------
    parts.append(h2('Indicadores'))
    lines = []
    if pub:
        c = pub['counts']
        lines.append('Web: <b>%s</b> fichas · publicada %s UTC%s' % (num(c.get('events', '')), esc((pub['at'] or '')[:16].replace('T', ' ')), '' if (pub.get('deploy') in (None, 'deployed', 'ok', 'completed')) else ' · despliegue: ' + esc(pub['deploy'])))
    new = data['new']
    lines.append('Planes nuevos: <b>%d</b> ayer · %d en 7 días' % (new[-1][1] if new else 0, sum(n for _, n in new)))
    tr = data.get('traffic')
    if tr and not tr.get('error'): lines.append('Visitas ayer: <b>%s</b> · acciones %s' % (esc(tr['visits']), esc(tr['actions'])))
    tot, before = data['total_acts'], data['total_week_ago']
    drops = [s for s in data['sources'] if s['change'] is not None and s['change'] <= -NOTABLE and max(s['acts'], s['week_ago'] or 0) >= 10]
    lines.append('Fuentes: <b>%s</b> actos en 30 días%s · %d fuentes%s' % (num(tot), (' (%s hace 7 días)' % num(before)) if before else '', len(data['sources']),
                 ('; bajan: ' + esc(', '.join('%s %s' % (s['source'], _delta(s['change'])) for s in drops[:6]))) if drops else ''))
    cov = data.get('coverage') or {}
    for label, key in (('Categorías', 'categories'), ('Distritos', 'districts')):
        now_, week = cov.get(key, ({}, None))
        if not now_: continue
        top = sorted(now_.items(), key=lambda kv: -kv[1])
        fmt = lambda k, n: '%s %s%s' % (esc(k), num(n), (' <span style="color:%s">%s</span>' % ('#b42318' if n < week.get(k, 0) else '#067647', _delta((n - week[k]) / week[k]))) if week and week.get(k) and abs(n - week[k]) / week[k] >= 0.1 else '')
        lines.append('%s (30 días): %s%s' % (label, ' · '.join(fmt(k, n) for k, n in top[:10]), '' if week else ' <span style="color:#999">(la comparación semanal empieza en 7 días)</span>'))
    corr = data.get('corrections')
    if corr: lines.append('Correcciones editoriales en 7 días: <b>%d</b> (%d fuera de la agenda)' % (corr['total'], corr['excluded']))
    if audit:
        lines.append('Auditoría semanal (%s): %s' % (esc(audit['day'][8:10] + '/' + audit['day'][5:7]), esc(' · '.join(p['title'] for p in audit.get('patterns', [])[:3])) or 'sin patrones'))
    ai = data.get('ai')
    if ai:
        tk = ai['tokens']
        lines.append('IA 24 h: %s tokens · %d categorías y %d fusiones decididas por IA' % (num(tk.get('input_tokens', 0) + tk.get('output_tokens', 0)), ai['categories'], ai['merges']))
    r = data['runs']
    lines.append('Motor 24 h: %d pasadas correctas · %d con problemas%s' % (r.get('completed', 0), sum(v for k, v in r.items() if k not in ('completed', 'skipped', 'running')),
                 (' (%s)' % esc(', '.join('%s: %s' % (f['job'], TRIAGE[f['triage']['class']][0]) for f in data['failing'] if f.get('triage')))) if data['failing'] else ''))
    fw = data.get('fest_watch')
    if fw and fw['new']:
        lines.append('Festivales nuevos: %s' % esc(', '.join(n['name'] for n in fw['new'][:5])))
    parts.append(li(lines))
    if ai and ai['sample']:
        parts.append('<p style="margin:10px 0 4px;color:#555">Lunes · muestra de fusiones por IA para revisar:</p><ol style="margin:0;padding-left:20px;color:#555">%s</ol>'
                     % ''.join('<li>%s = %s <span style="color:#999">· %.2f · %s</span></li>' % (esc(x['a']), esc(x['b']), x['confidence'], esc(x['reason'])) for x in ai['sample'][:10]))
    parts.append('<p style="color:#999;font-size:12px;margin-top:20px">Generado por el motor de Ontoca. Las alertas nuevas también llegan al momento, una sola vez.</p></div>')
    text = '\n'.join([subject, '', 'Requiere atención: %d' % attention] + ['- [Revisar] %s %s: %s' % (a['source'], LABELS.get(a['kind'], a['kind']), a['detail'][:160]) for a in review] +
                     ['- %s: %s' % (f['job'], (f['error'] or '')[:160]) for f in jobs_bad] + ['- %s %s' % (f['source'], 'nunca se ha leído bien' if f['hours'] is None else 'sin leer bien desde hace ' + hrs(f['hours'])) for f in fresh] + (['- %d posibles duplicados' % len(dups)] if dups else []) +
                     (['- %d salas sin nada próximo' % len(lost)] if lost else []) + ['- Error grave: %s · %s' % (a['title'], a['problem']) for a in serious[:5]] +
                     ['', 'Fichas publicadas: %s' % ((pub or {}).get('counts', {}).get('events', '?')), 'Actos de las fuentes en 30 días: %s' % tot])
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
