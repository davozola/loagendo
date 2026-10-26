"""Buscador de programas de festival (25-10-2026).

Para cada festival o fiesta del que solo tenemos la ficha general (src/festivals.py), busca su web oficial y la
página de su programa, y mira cómo se podría leer. No importa nada: deja un informe para decidir qué conectar.

  1. Web oficial: primero los enlaces que ya trae la ficha (GuiaBCN «Web», Open Data, Generalitat…); si no hay,
     y el trabajo lo permite (``buscar_web``), una búsqueda web con IA que solo propone direcciones. Una web se da
     por buena si su página dice el nombre propio del festival (sin IA).
  2. Página del programa, con reglas: enlaces «programa», «programació», «schedule», «agenda», «lineup»,
     «cartell», «horaris»… de la web oficial.
  3. Cómo leerlo, de más a menos fiable: plataformas con API (Accelevents, Sched, Pretalx, Eventbrite, Dice…),
     The Events Calendar o Events Manager de WordPress, iCal, JSON-LD; si no, lectura con IA comprobada; un PDF
     se marca aparte.

Respeta robots.txt. Cada festival se revisa como mucho una vez por semana (``festival_programs``, sin borrar
nada: se guarda la última revisión con su fecha). Informe: reports/festivales_programas.html (+ .json).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports' / 'festivales_programas'
RECHECK_DAYS = 7
MAX_PROBES = 40          # webs revisadas por pasada
MAX_AI_SEARCHES = 15     # búsquedas con IA por pasada
# Agregadores y redes: no son la web oficial de un festival.
NOT_OFFICIAL = re.compile(r"(?:^|\.)(?:barcelona\.cat|bcn\.cat|gencat\.cat|diba\.cat|bcn\.es|guiadelocio|timeout|songkick|conciertos\.club|"
                          r"facebook|instagram|twitter|x\.com|tiktok|youtube|youtu\.be|linkedin|wikipedia|google|goo\.gl|bit\.ly|"
                          r"ticketmaster|entradas\.com|eventbrite|dice\.fm|xceed|feverup|ra\.co|wegow|ontoca|loagendo|"
                          # Enlaces técnicos de los datos (26-10-2026): el «PRODID» de los .ics de Open Data apunta a la librería ics-py en GitHub.
                          r"github\.com|gitlab\.com|git\.io|bitbucket\.org|schema\.org|w3\.org)\b", re.I)
PROGRAM_WORDS = re.compile(r"\b(?:programa|programaci[oó]n?|program(?:me)?|schedule|agenda|line-?up|cartel+|horaris?|horarios?|sessions|sesiones|"
                           r"activitats|actividades|calendari|calendario)\b", re.I)
# Enlaces de pie de página que nunca son el programa (26-10-2026: Lens Dans daba «aviso legal»).
NOT_PROGRAM = re.compile(r"aviso|legal|privacidad|privacitat|privacy|cookies?|contact[eo]?|condiciones|condicions|terms|termes|accesibilidad|accessibilitat", re.I)
URL_RX = re.compile(r"https?://[^\s\"'<>\\)\]]+")
PLATFORMS = [  # (nombre, patrón en el HTML o en la dirección, cómo se leería)
    ('Accelevents', re.compile(r"accelevents", re.I), 'api'),
    ('Sched', re.compile(r"\.sched\.com", re.I), 'api'),
    ('Pretalx', re.compile(r"pretalx", re.I), 'api'),
    ('Eventbrite', re.compile(r"eventbrite\.[a-z.]+/e/", re.I), 'api'),
    ('Dice', re.compile(r"dice\.fm/(?:event|venue)", re.I), 'api'),
    ('Xceed', re.compile(r"xceed\.me", re.I), 'api'),
    ('Ticketmaster', re.compile(r"ticketmaster\.es", re.I), 'api'),
    ('The Events Calendar (WordPress)', re.compile(r"tribe-events|/wp-json/tribe/", re.I), 'api'),
    ('Events Manager (WordPress)', re.compile(r"events-manager|em-calendar|wp-events-plugin", re.I), 'ical'),
    ('iCal', re.compile(r"\.ics\b|webcal://", re.I), 'ical'),
]


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS festival_programs (slug TEXT PRIMARY KEY, name TEXT NOT NULL, record TEXT, start TEXT, end TEXT,
      web TEXT, web_how TEXT, web_ok INTEGER, program_url TEXT, reading TEXT, platform TEXT, detail TEXT, checked_at TEXT NOT NULL)""")


def _host(url):
    try: return urlsplit(url).netloc.lower().removeprefix('www.')
    except ValueError: return ''


def official_links(texts):
    """Direcciones de los datos de la ficha que pueden ser la web oficial (no agregadores ni redes)."""
    out = []
    for text in texts:
        for url in URL_RX.findall(str(text or '')):
            url = html.unescape(url).rstrip('.,;')
            if not _host(url) or NOT_OFFICIAL.search(_host(url)) or re.search(r"\.(?:jpe?g|png|gif|webp|pdf|svg)(?:\?|$)", url, re.I): continue
            if url not in out: out.append(url)
    return out


def candidates(conn, today=None):
    """Festivales vigentes sin actividades: [{slug, name, record, start, end, texts}]."""
    from src.festivals import for_conn
    today = (today or dt.date.today()).isoformat()
    fest = for_conn(conn)
    rows = conn.execute("""SELECT source, id, title, substr(start_date,1,10), substr(COALESCE(NULLIF(end_date,''),start_date),1,10), raw_json FROM source_records
        WHERE eligibility<>'exclude' AND COALESCE(NULLIF(end_date,''),start_date)>=? AND (lower(title) LIKE '%fest%' OR lower(title) LIKE '%mostra%'
        OR lower(title) LIKE '%biennal%' OR lower(title) LIKE '%open house%' OR raw_json LIKE '%"x_festival"%')""", (today,)).fetchall()
    groups = {}
    for source, rid, title, start, end, raw in rows:
        raw_fest = None
        if '"x_festival"' in (raw or ''):
            try: raw_fest = (json.loads(raw).get('item') or {}).get('x_festival')
            except ValueError: pass
        f = fest.of(title, raw_fest, start=start, end=end)
        if not f: continue
        g = groups.setdefault(f['slug'], {'slug': f['slug'], 'name': f['name'], 'kind': f.get('kind', 'festival'), 'children': 0, 'umbrellas': []})
        if f['umbrella']: g['umbrellas'].append({'record': f'{source}:{rid}', 'title': title, 'start': start, 'end': end, 'raw': raw})
        else: g['children'] += 1
    out = []
    for g in groups.values():
        if g['children'] or not g['umbrellas']: continue
        u = sorted(g['umbrellas'], key=lambda x: x['start'])[0]
        texts = [x['raw'] for x in g['umbrellas']]
        for x in g['umbrellas']:
            s, i = x['record'].split(':', 1)
            for (links,) in conn.execute('SELECT links_json FROM source_enrichments WHERE source=? AND id=?', (s, i)) if _has(conn, 'source_enrichments') else []:
                texts.append(links)
            for (facts,) in conn.execute('SELECT facts_json FROM source_detail_facts WHERE source=? AND id=?', (s, i)) if _has(conn, 'source_detail_facts') else []:
                texts.append(facts)
        out.append({'slug': g['slug'], 'name': g['name'], 'kind': g['kind'], 'record': u['record'], 'start': min(x['start'] for x in g['umbrellas']),
                    'end': max(x['end'] for x in g['umbrellas']), 'texts': texts})
    return sorted(out, key=lambda c: c['start'])


def _has(conn, table):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())


def _plain(body):
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body or '', flags=re.S | re.I)
    return ' '.join(html.unescape(re.sub(r"<[^>]+>", ' ', body)).split())


def names_the_festival(body, name):
    """La página dice el nombre propio del festival (todas sus palabras distintivas)."""
    from src.festivals import core, fold
    words = core(name)
    text = fold(_plain(body)[:200_000])
    return bool(words) and all(re.search(r"\b%s\b" % re.escape(w), text) for w in words)


def program_links(body, base):
    out = []
    for href, text in re.findall(r"<a\b[^>]*href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", body or '', re.S | re.I):
        label = _plain(text)
        url = urljoin(base, html.unescape(href))
        if NOT_PROGRAM.search(label) or NOT_PROGRAM.search(urlsplit(url).path): continue
        if not url.startswith('http') or _host(url) and _host(url) != _host(base) and not any(p[1].search(url) for p in PLATFORMS): continue
        if PROGRAM_WORDS.search(label) or PROGRAM_WORDS.search(urlsplit(url).path.replace('-', ' ').replace('/', ' ')):
            if url not in out: out.append(url)
    return out[:8]


def reading_of(body, url):
    """(plataforma, cómo se leería) de una página: api, ical, jsonld, pdf o ia."""
    for name, rx, how in PLATFORMS:
        if rx.search(url) or rx.search(body or ''):
            return name, how
    if re.search(r'application/ld\+json[^>]*>[^<]*"@type"\s*:\s*"[A-Za-z]*Event"', body or '', re.S): return 'JSON-LD', 'jsonld'
    if re.search(r'href=["\'][^"\']+\.pdf["\']', body or '', re.I) and re.search(r'program', body or '', re.I): return 'PDF', 'pdf'
    return '', 'ia'


def ai_search(name, start, end, key, requester=None):
    """Una dirección candidata a web oficial con la búsqueda web de la API de Claude. Solo propone: se comprueba después."""
    from src.ai_assist import API, MODEL, _request
    requester = requester or _request
    prompt = (f"Busca la web oficial del festival «{name}» que se celebra en Barcelona entre el {start} y el {end}. "
              "Responde solo con JSON: {\"url\": \"…\"} con la página oficial del festival (no agendas, ticketeras ni redes sociales), "
              "o {\"url\": \"\"} si no la encuentras.")
    body = {'model': MODEL, 'max_tokens': 400, 'messages': [{'role': 'user', 'content': prompt}],
            'tools': [{'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 3}]}
    message = requester('POST', f'{API}/messages', key, body, timeout=120)
    text = ' '.join(b.get('text', '') for b in message.get('content', []) if b.get('type') == 'text')
    m = re.search(r'\{[^{}]*"url"\s*:\s*"([^"]*)"[^{}]*\}', text)
    url = (m.group(1) if m else '').strip()
    return url if url.startswith('http') and not NOT_OFFICIAL.search(_host(url)) else ''


def probe(cand, fetcher, robots, key=None, ai=None):
    """Revisa un festival: web, programa y cómo leerlo."""
    res = {'web': '', 'web_how': '', 'web_ok': 0, 'program_url': '', 'reading': '', 'platform': '', 'detail': ''}
    links = official_links(cand['texts'])
    tried = []
    fallback = None   # primera web de la ficha que responde pero no nombra el festival: solo si no hay otra mejor
    for url, how in [(u, 'ficha') for u in links[:4]] + ([(None, 'ia')] if not links and key and ai else []):
        if url is None:
            try: url = ai(cand['name'], cand['start'], cand['end'], key)
            except Exception as error: res['detail'] = 'Búsqueda con IA: ' + type(error).__name__; break
            if not url: res['detail'] = 'La búsqueda con IA no encontró web'; break
        if not robots(url): tried.append(url + ' (robots.txt no deja)'); continue
        status, final, body = fetcher(url, 25)
        if status != 200: tried.append('%s (HTTP %s)' % (url, status)); continue
        ok = names_the_festival(body, cand['name'])
        if not ok:
            tried.append(url + ' (no nombra el festival)')
            if how == 'ficha' and fallback is None: fallback = (url, final, body, how)
            continue
        _read_web(res, url, final, body, how, True, fetcher, robots)
        break
    if not res['web'] and fallback:
        _read_web(res, *fallback, False, fetcher, robots)
        res['detail'] = 'La web no nombra el festival: comprobar que es la suya antes de conectar'
    if not res['web'] and tried: res['detail'] = 'Probadas: ' + '; '.join(tried)[:400]
    if not res['web'] and not links and not (key and ai) and not res['detail']: res['detail'] = 'La ficha no trae web y la búsqueda con IA está apagada'
    return res


def _read_web(res, url, final, body, how, ok, fetcher, robots):
    res.update(web=final or url, web_how=how, web_ok=int(ok))
    platform, reading = reading_of(body, final or url)
    program = '' if platform else next(iter(program_links(body, final or url)), '')
    if program and robots(program):
        s2, f2, b2 = fetcher(program, 25)
        if s2 == 200:
            res['program_url'] = f2 or program
            platform, reading = reading_of(b2, f2 or program)
    elif platform:
        res['program_url'] = final or url
    res.update(platform=platform, reading=reading if (res['program_url'] or platform) else '')


def run(conn, job=None, today=None, fetcher=None, robots=None, key=None, ai=None, now=None, out=REPORT):
    from src.venue_feeds import fetch, robots_allows
    job = job or {}
    initialize(conn)
    fetcher = fetcher or fetch
    robots = robots or (robots_allows if fetcher is fetch else (lambda u: True))
    if key is None and job.get('buscar_web', True):
        from src.ai_assist import load_key
        key = load_key() or ''
    ai = ai or ai_search
    now = now or dt.datetime.now(dt.timezone.utc)
    stamp = now.isoformat(timespec='seconds')
    auto_path = job.get('auto_path')
    connected = _connected_festivals(auto_path)
    probes = searches = 0
    new_auto = []
    for cand in candidates(conn, today):
        if cand['slug'] in connected: continue
        row = conn.execute('SELECT checked_at FROM festival_programs WHERE slug=?', (cand['slug'],)).fetchone()
        if row and row[0] >= (now - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec='seconds'): continue
        if probes >= job.get('max_probes', MAX_PROBES): break
        use_ai = searches < job.get('max_busquedas_ia', MAX_AI_SEARCHES)
        res = probe(cand, fetcher, robots, key if use_ai else None, ai)
        probes += 1; searches += int(res['web_how'] == 'ia' or res['detail'].startswith('La búsqueda con IA'))
        # 26-10-2026 (David): sin extractores nuevos; el buscador solo encuentra la web y el enlace al programa oficial.
        auto = auto_connector(cand, res) if job.get('conectar', False) else None
        if auto:
            new_auto.append(auto); res['detail'] = ('Conectado solo · ' + res['detail']).rstrip(' ·')
        with conn:
            conn.execute("""INSERT INTO festival_programs(slug,name,record,start,end,web,web_how,web_ok,program_url,reading,platform,detail,checked_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(slug) DO UPDATE SET name=excluded.name,record=excluded.record,start=excluded.start,end=excluded.end,
                web=excluded.web,web_how=excluded.web_how,web_ok=excluded.web_ok,program_url=excluded.program_url,reading=excluded.reading,
                platform=excluded.platform,detail=excluded.detail,checked_at=excluded.checked_at""",
                         (cand['slug'], cand['name'], cand['record'], cand['start'], cand['end'], res['web'], res['web_how'], res['web_ok'],
                          res['program_url'], res['reading'], res['platform'], res['detail'], stamp))
    if new_auto: save_auto(new_auto, auto_path)
    path = write_report(conn, today or dt.date.today(), out)
    return {'status': 'completed', 'revisados': probes, 'busquedas_ia': searches, 'conectados': [a['name'] for a in new_auto], 'informe': str(path), **summary(conn, today)}


def _connected_festivals(auto_path=None):
    """Festivales que ya tienen conector (config/venues.json o los conectados solos en data/festivales_auto.json)."""
    from src.venue_feeds import AUTO_FESTIVALS_PATH, load_venues
    try: venues = load_venues(auto_path=auto_path or AUTO_FESTIVALS_PATH)
    except (OSError, ValueError): return set()
    return {((v.get('feed') or {}).get('festival') or {}).get('slug') for v in venues if v.get('enabled') and (v.get('feed') or {}).get('festival')}


AUTO_PLATFORMS = {'Accelevents', 'The Events Calendar (WordPress)', 'JSON-LD'}


def auto_connector(cand, res):
    """Conector que se puede activar solo, por reglas (25-10-2026): la ficha del festival recibe su programa con el
    criterio de siempre (con entrada propia, ficha propia; si no, al programa). None si la plataforma aún no se lee."""
    url = res.get('program_url') or ''
    # Solo se conecta solo si la web nombra el festival (26-10-2026): sin eso podría ser la web de otro.
    if res.get('platform') not in AUTO_PLATFORMS or not url or not res.get('web_ok'): return None
    feed = {'festival': {'slug': cand['slug'], 'name': cand['name']}, 'desde': cand['start'], 'hasta': cand['end'], 'url': url}
    if res['platform'] == 'Accelevents':
        m = re.search(r"/e/([^/?#]+)", url) or re.search(r"/e/([^/?#]+)", res.get('web') or '')
        if not m: return None
        feed.update(kind='accelevents', event=m.group(1))
    elif res['platform'].startswith('The Events Calendar'):
        parts = urlsplit(url)
        feed.update(kind='tribe_rest', url=f"{parts.scheme}://{parts.netloc}/wp-json/tribe/events/v1/events")
    slug = 'fest_' + re.sub(r'[^a-z0-9]+', '_', cand['slug'].removeprefix('auto-')).strip('_')[:50]
    return {'slug': slug, 'name': cand['name'], 'type': 'festival', 'url': url, 'site': res.get('web') or url, 'enabled': True, 'auto': True, 'feed': feed,
            'note': 'Conectado solo por el buscador de programas (%s): %s' % (dt.date.today().isoformat(), res['platform'])}


def save_auto(entries, path=None):
    from src.venue_feeds import AUTO_FESTIVALS_PATH
    path = Path(path or AUTO_FESTIVALS_PATH)
    try: data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): data = {'nota': 'Generado por src/festival_finder.py: programas de festival conectados solos. Para corregir uno, pasarlo a config/venues.json (manda) o poner enabled: false.', 'venues': []}
    have = {v['slug'] for v in data['venues']}
    data['venues'] += [e for e in entries if e['slug'] not in have]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return len(data['venues'])


def summary(conn, today=None):
    today = (today or dt.date.today()).isoformat()
    rows = conn.execute('SELECT web, program_url, reading FROM festival_programs WHERE COALESCE(end,start)>=?', (today,)).fetchall()
    return {'festivales': len(rows), 'con_web': sum(1 for w, _, _ in rows if w), 'con_programa': sum(1 for _, p, _ in rows if p),
            'por_reglas': sum(1 for _, p, r in rows if p and r in ('api', 'ical', 'jsonld')), 'con_ia': sum(1 for _, p, r in rows if p and r == 'ia'),
            'pdf': sum(1 for _, p, r in rows if p and r == 'pdf')}


def write_report(conn, today, out=REPORT):
    rows = [dict(zip(('slug', 'name', 'record', 'start', 'end', 'web', 'web_how', 'web_ok', 'program_url', 'reading', 'platform', 'detail', 'checked_at'), r))
            for r in conn.execute('SELECT slug,name,record,start,end,web,web_how,web_ok,program_url,reading,platform,detail,checked_at FROM festival_programs '
                                  'WHERE COALESCE(end,start)>=? ORDER BY start', (today.isoformat(),))]
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix('.json').write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding='utf-8')
    e = lambda v: html.escape(str(v or ''))
    label = {'api': 'Por reglas (API)', 'ical': 'Por reglas (iCal)', 'jsonld': 'Por reglas (JSON-LD)', 'pdf': 'PDF', 'ia': 'Con IA comprobada', '': ''}
    groups = [('Conectados solos: su programa entra en la ficha del festival', [r for r in rows if r['detail'].startswith('Conectado solo')]),
              ('Programa encontrado, se puede leer por reglas (conector por hacer)', [r for r in rows if r['program_url'] and r['reading'] in ('api', 'ical', 'jsonld') and not r['detail'].startswith('Conectado solo')]),
              ('Programa encontrado, habría que leerlo con IA', [r for r in rows if r['program_url'] and r['reading'] == 'ia']),
              ('Programa en PDF', [r for r in rows if r['program_url'] and r['reading'] == 'pdf']),
              ('Web encontrada, sin página de programa', [r for r in rows if r['web'] and not r['program_url']]),
              ('Sin web encontrada', [r for r in rows if not r['web']])]
    how = {'ficha': 'enlace de la ficha', 'ia': 'búsqueda con IA'}
    day = lambda d: '%s/%s' % (d[8:10], d[5:7]) if d else ''

    def row(r):
        web = '<a href="%s">%s</a>' % (e(r['web']), e(_host(r['web']))) if r['web'] else ''
        warn = ' · no nombra el festival' if r['web'] and not r['web_ok'] else ''
        prog = '<a href="%s">programa</a>' % e(r['program_url']) if r['program_url'] else ''
        return ('<tr><td><b>%s</b><div class=s>%s</div></td><td class=d>%s → %s</td><td>%s<div class=s>%s%s</div></td><td>%s</td><td>%s<div class=s>%s%s</div></td></tr>'
                % (e(r['name']), e(r['record']), day(r['start']), day(r['end']), web, e(how.get(r['web_how'], '')), warn, prog, e(r['platform']),
                   e(label.get(r['reading'], '')), (' · ' if r['reading'] and r['detail'] else '') + e(r['detail'])))
    body = ''.join('<h2>%s <span>%d</span></h2><table><tr><th>Festival</th><th>Fechas</th><th>Web</th><th>Programa</th><th>Cómo</th></tr>%s</table>'
                   % (e(t), len(rs), ''.join(row(r) for r in rs)) for t, rs in groups if rs)
    s = summary(conn, today)
    page = ('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Programas de festivales</title>'
            '<style>body{font:14px/1.45 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;margin:16px;color:#1d1d1f}h1{font-size:20px}h2{font-size:16px;margin-top:24px}'
            'h2 span{color:#888;font-weight:400}table{border-collapse:collapse;width:100%;max-width:1100px}td,th{text-align:left;padding:6px 8px;border-bottom:1px solid #eee;vertical-align:top}'
            '.s{font-size:11px;color:#777}.d{white-space:nowrap}a{color:#2950c7}</style>'
            f'<h1>Programas de festivales · {today.strftime("%d-%m-%Y")}</h1><p>{s["festivales"]} festivales sin actividades · {s["con_web"]} con web · '
            f'{s["con_programa"]} con programa ({s["por_reglas"]} por reglas, {s["con_ia"]} con IA, {s["pdf"]} en PDF). No se ha importado nada.</p>' + body + '</html>')
    out.with_suffix('.html').write_text(page, encoding='utf-8')
    return out.with_suffix('.html')
