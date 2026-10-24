"""Traducciones oficiales de la descripción: las que publica la propia sala (24-10-2026).

Algunas salas publican cada acto en catalán, castellano e inglés. Cuando la sala tiene la
descripción en el idioma de la web pública, se usa la suya antes que la traducción automática
(src/ai_translate.py). Se lee lo mismo que ya da la ficha, en el otro idioma:
  · Palau de la Música: la misma programación en JSON en /es/ y /en/ (subtítulo e intérpretes de
    la producción, unidos como lo hace el conector, src/venue_feeds.palau_json_nodes);
  · Jamboree: la página del concierto en /es/ y /en/ (og:description, como el conector);
  · MACBA y Teatre Lliure: la página del acto en el idioma que declara su <link hreflang> o, si no
    lo declara (Lliure), su selector de idioma con la misma dirección (/es/x → /en/x); se lee la
    misma descripción que archiva src/guia_detail.py.
Solo se guarda si la página dice estar en ese idioma (<html lang>), el texto no es el original y no
parece estar en otro idioma (CCCB y Apolo tienen páginas /en/ con el texto en catalán o una
plantilla). Se guarda la URL, la fecha y la huella del HTML; cada cambio queda en el historial.
Se respeta robots.txt y cada acto se vuelve a mirar a los 3 días. Nada se borra.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import time
from urllib.parse import urljoin, urlsplit

from src.ai_translate import TARGETS, guess_lang

RECHECK_DAYS = 3
MIN_TEXT = 40
# L'Auditori no: su descripción (meta) sale en catalán en las tres versiones (comprobado el 24-10-2026).
PAGE_SOURCES = ('web_macba', 'web_teatre_lliure')


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS official_translations (
      source TEXT NOT NULL, id TEXT NOT NULL, lang TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL, page_sha256 TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL, PRIMARY KEY(source, id, lang));
    CREATE TABLE IF NOT EXISTS official_translation_log (
      source TEXT NOT NULL, id TEXT NOT NULL, lang TEXT NOT NULL, url TEXT NOT NULL, text TEXT NOT NULL,
      status TEXT NOT NULL, page_sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL);
    """)


def _now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def _strip(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())


def page_lang(page):
    m = re.search(r'<html[^>]*\blang=["\']?([a-zA-Z]{2})', page or '', re.I)
    return m.group(1).lower() if m else ''


def alternates(page, base):
    """{idioma: url} de los <link rel="alternate" hreflang> de la página."""
    out = {}
    for tag in re.findall(r'<link\b[^>]*>', page or '', re.I):
        lang = re.search(r'hreflang=["\']([a-zA-Z]{2})(?:-[a-zA-Z]+)?["\']', tag); href = re.search(r'href=["\']([^"\']+)', tag)
        if lang and href and 'alternate' in tag.lower(): out.setdefault(lang.group(1).lower(), urljoin(base, html.unescape(href.group(1))))
    return out


def switch_links(page, base):
    """Sin hreflang: los enlaces del selector de idioma que llevan a la misma página con otro prefijo
    (/es/epitap → /en/epitap). Solo si la página los enlaza; no se inventan direcciones."""
    parts = urlsplit(base); m = re.match(r'^/(ca|es|en)(/.+)$', parts.path)
    if not m: return {}
    hrefs = {urljoin(base, html.unescape(h)).rstrip('/') for h in re.findall(r'<a\b[^>]*href=["\']([^"\']+)', page or '', re.I)}
    out = {m.group(1): base}  # la propia página, en su idioma
    for lang in ('ca', 'es', 'en'):
        candidate = f'{parts.scheme}://{parts.netloc}/{lang}{m.group(2)}'
        if candidate.rstrip('/') in hrefs: out[lang] = candidate
    return out


def acceptable(text, original, lang, declared):
    """'ok' o el motivo por el que no vale como traducción oficial."""
    text = (text or '').strip()
    if len(text) < MIN_TEXT: return 'corto'
    if declared and declared != lang: return 'otro_idioma'
    if ' '.join(text.split()) == ' '.join((original or '').split()): return 'igual_que_original'
    guess = guess_lang(text)
    if guess and guess != lang: return 'otro_idioma'
    return 'ok'


def _save(conn, source, rid, lang, url, text, status, page):
    initialize(conn)
    sha = hashlib.sha256((page or '').encode('utf-8')).hexdigest() if page else ''
    prev = conn.execute('SELECT url,text,status FROM official_translations WHERE source=? AND id=? AND lang=?', (source, rid, lang)).fetchone()
    now = _now()
    with conn:
        conn.execute("""INSERT INTO official_translations(source,id,lang,url,text,status,page_sha256,fetched_at) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source,id,lang) DO UPDATE SET url=excluded.url,text=excluded.text,status=excluded.status,page_sha256=excluded.page_sha256,fetched_at=excluded.fetched_at""",
                     (source, rid, lang, url, text if status == 'ok' else '', status, sha, now))
        if prev != (url, text if status == 'ok' else '', status):
            conn.execute('INSERT INTO official_translation_log VALUES (?,?,?,?,?,?,?,?)', (source, rid, lang, url, text if status == 'ok' else '', status, sha, now))


def _due(conn, sources, today, limit):
    """Actos vigentes de esas fuentes que no se han mirado en RECHECK_DAYS días (en algún idioma)."""
    initialize(conn)
    before = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec='seconds')
    marks = ','.join('?' for _ in sources); langs = len(TARGETS)
    return conn.execute(f"""SELECT r.source,r.id,r.source_url,r.raw_json FROM source_records r
        WHERE r.source IN ({marks}) AND r.end_date>=? AND r.source_url LIKE 'https://%'
          AND (SELECT COUNT(*) FROM official_translations o WHERE o.source=r.source AND o.id=r.id AND o.fetched_at>=?)<?
        ORDER BY r.start_date, r.id LIMIT ?""", (*sources, today, before, langs, limit)).fetchall()


# ---------- Palau de la Música: la programación en JSON en cada idioma ----------
def palau_text(prod):
    return ' — '.join(x for x in (_strip(prod.get('subtitle')), _strip(prod.get('performers'))) if x)


def run_palau(conn, fetcher, timeout, today, limit):
    from src.venue_feeds import load_venues
    rows = _due(conn, ('venue_palau_musica',), today, limit)
    if not rows: return {'actos': 0}
    venue = next((v for v in load_venues() if v.get('slug') == 'palau_musica' or 'palaumusica' in str((v.get('feed') or {}).get('url', ''))), None)
    feed = (venue or {}).get('feed', {}).get('url', '')
    if '/ca/' not in feed: return {'actos': 0, 'error': 'sin programación del Palau'}
    feeds = {}
    for lang in TARGETS:
        st, _, body = fetcher(feed.replace('/ca/', f'/{lang}/', 1), timeout)
        try: feeds[lang] = (json.loads(body).get('productions') or {}) if st == 200 else None
        except ValueError: feeds[lang] = None
    stats = {}
    for source, rid, url, raw_json in rows:
        pid = (re.search(r'_(\d+)/?$', url or '') or [None, None])[1]
        original = str(((json.loads(raw_json or '{}').get('loagendo')) or {}).get('description') or '')
        for lang in TARGETS:
            if feeds.get(lang) is None: status, text, link = 'sin_respuesta', '', ''
            else:
                prod = feeds[lang].get(str(pid)) if pid else None
                text = palau_text(prod) if prod else ''; link = str((prod or {}).get('url') or '')
                status = acceptable(text, original, lang, lang) if prod else 'sin_produccion'
            _save(conn, source, rid, lang, link, text, status, json.dumps(feeds[lang].get(str(pid)), ensure_ascii=False) if feeds.get(lang) and pid and feeds[lang].get(str(pid)) else '')
            stats[status] = stats.get(status, 0) + 1
    return {'actos': len(rows), 'resultado': stats}


# ---------- páginas: Jamboree (/es/, /en/) y hreflang (MACBA, Lliure, Auditori) ----------
def jamboree_url(url, lang):
    parts = urlsplit(url)
    if parts.netloc != 'jamboreejazz.com' or not parts.path.startswith('/evento/'): return ''
    return f'https://jamboreejazz.com/{lang}{parts.path}'


def run_pages(conn, fetcher, timeout, today, limit, polite):
    from src.guia_detail import MetaParser
    from src.venue_feeds import og_meta
    rows = _due(conn, ('venue_jamboree',) + PAGE_SOURCES, today, limit)
    stats = {}
    for source, rid, url, raw_json in rows:
        page_cache = {}
        def get(u):
            if u not in page_cache:
                if not polite(u): page_cache[u] = (None, '')
                else:
                    st, _, body = fetcher(u, timeout); page_cache[u] = (st, body if st == 200 else '')
            return page_cache[u]
        if source == 'venue_jamboree':
            original = str(((json.loads(raw_json or '{}').get('loagendo')) or {}).get('description') or '')
            links = {lang: jamboree_url(url, lang) for lang in TARGETS}
            read = lambda page: og_meta(page).get('og:description', '')
        else:
            row = conn.execute('SELECT description FROM source_enrichments WHERE source=? AND id=?', (source, rid)).fetchone()
            original = row[0] if row else ''
            st, page = get(url)
            links = (alternates(page, url) or switch_links(page, url)) if page else {}
            def read(page):
                parser = MetaParser(); parser.feed(page); return parser.description
        for lang in TARGETS:
            link = links.get(lang) or ''
            if not link: status, text, page = 'sin_version', '', ''
            elif link.rstrip('/') == url.rstrip('/'): status, text, page = 'es_el_original', '', ''
            else:
                st, page = get(link)
                if st is None: status, text = 'robots', ''
                elif not page: status, text = f'http_{st}', ''
                else: text = read(page).strip(); status = acceptable(text, original, lang, page_lang(page))
            _save(conn, source, rid, lang, link, text, status, page)
            stats[status] = stats.get(status, 0) + 1
    return {'actos': len(rows), 'resultado': stats}


def run(conn, job=None, fetcher=None, today=None):
    """Trabajo «traducciones-oficiales»."""
    from src.venue_feeds import fetch, robots_allows
    job = job or {}; real = fetcher is None; fetcher = fetcher or fetch
    today = today or dt.date.today().isoformat(); timeout = job.get('timeout_seconds', 15); limit = job.get('limit', 300)
    last = {'t': 0.0}
    def polite(url):
        if not real: return True
        if not robots_allows(url): return False
        wait = 0.5 - (time.monotonic() - last['t'])
        if wait > 0: time.sleep(wait)
        last['t'] = time.monotonic(); return True
    initialize(conn)
    return {'palau': run_palau(conn, fetcher, timeout, today, limit), 'paginas': run_pages(conn, fetcher, timeout, today, limit, polite)}


def official_for(conn, key, lang):
    """Traducción oficial vigente ({text, url, date}) para la ficha publicada con esa clave, o None."""
    source, _, rid = key.partition(':')
    try: row = conn.execute("SELECT text,url,fetched_at FROM official_translations WHERE source=? AND id=? AND lang=? AND status='ok'", (source, rid, lang)).fetchone()
    except sqlite3.DatabaseError: return None
    return {'text': row[0], 'url': row[1], 'date': row[2][:10]} if row and row[0] else None
