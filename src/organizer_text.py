"""Texto de la web del organizador para fichas de GuiaBCN que no traen texto (20-10-2026).

Unas 600 fichas de GuiaBCN no tienen descripción ni en la página ni en la API del Ajuntament
(«texte» y «resum» vacíos), pero sí el enlace a la web oficial del acto. De esa página se toma la
descripción breve que la propia web publica para compartirla (og:description o meta description),
tal cual, y la ficha la muestra como «Texto de la web del organizador». Decisión de David, 20-10-2026.

Para no poner un texto que no es del acto:
  · no se usan portadas (URL sin ruta), redes sociales ni ticketeras;
  · el texto tiene que tener al menos 60 caracteres y compartir alguna palabra propia con el título
    del acto (en el texto, en el título de la página o en su URL);
  · un texto que la misma web repite para tres actos distintos es el genérico del sitio: no vale.
Se respeta robots.txt; cada enlace se lee una vez (se reintenta a los 30 días si falló).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import unicodedata
from urllib.parse import urlsplit

MIN_TEXT = 60
MAX_TEXT = 700
SHORT = 80
CREDIT = 'la web del organizador'
SKIP_HOSTS = re.compile(r"(?:^|\.)(?:barcelona\.cat|bcn\.cat|instagram\.com|facebook\.com|fb\.me|twitter\.com|x\.com|youtube\.com|youtu\.be|tiktok\.com|linkedin\.com|"
                        r"ticketmaster\.\w+|entradas\.com|eventbrite\.\w+|atrapalo\.com|fever\w*\.com|dice\.fm|wegow\.com|taquilla\.com|tickets\.\w+|"
                        r"oneboxtds\.com|codetickets\.com|entradium\.com|koobin\.com|google\.\w+|goo\.gl|wa\.me|whatsapp\.com|linktr\.ee|mailto)$")
STOP = {'concert', 'concierto', 'espectacle', 'espectaculo', 'exposicio', 'exposicion', 'taller', 'cicle', 'ciclo', 'festival', 'barcelona', 'visita',
        'xerrada', 'presentacio', 'activitat', 'teatre', 'teatro', 'musica', 'dansa', 'cinema', 'familiar', 'infantil', 'amb', 'con', 'per', 'para', 'del', 'dels',
        'les', 'els', 'las', 'los', 'una', 'que', 'the', 'and', 'dels', 'amb', 'sala', 'nova', 'nou', 'gran', 'edicio', 'edicion', 'tots', 'todos', 'tota', 'toda', 'aquest', 'esta', 'este', 'sobre', 'entre', 'més', 'mes', 'cada', 'dues', 'tres', 'partit', 'lliga', 'festa', 'major', 'fiesta', 'dates'}


def _words(text):
    t = unicodedata.normalize('NFKD', str(text or '').lower()).encode('ascii', 'ignore').decode()
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 4 and not w.isdigit() and w not in STOP}


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS organizer_texts (source TEXT NOT NULL, id TEXT NOT NULL, url TEXT NOT NULL, text TEXT NOT NULL DEFAULT '',
      page_title TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(source, id))""")


def usable_link(url):
    parts = urlsplit(str(url or ''))
    if parts.scheme not in ('http', 'https') or not parts.netloc: return False
    if SKIP_HOSTS.search(parts.netloc.lower().split(':')[0]): return False
    return parts.path.strip('/') != '' or bool(parts.query)   # una portada describe el sitio, no el acto


def page_text(page):
    from src.venue_feeds import og_meta
    meta = og_meta(page)
    text = meta.get('og:description') or ''
    if not text:
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', page or '', re.I) or \
            re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']', page or '', re.I)
        if m:
            import html as _h; text = _h.unescape(m.group(1))
    title = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page or '', re.I) or re.search(r'<title>(.*?)</title>', page or '', re.I | re.S)
    import html as _h
    return ' '.join(_h.unescape(text).split()), ' '.join(_h.unescape(title.group(1)).split()) if title else ''


def jsonld_text(page, title):
    """Descripción del schema.org Event de la página que es este acto (suele ser más completa que og:description)."""
    from src.venue_feeds import jsonld_events
    import html as _h
    words = _words(title)
    for node in jsonld_events(page or ''):
        if words & _words(str(node.get('name') or '')):
            text = re.sub(r'<[^>]+>', ' ', str(node.get('description') or ''))
            return ' '.join(_h.unescape(text).split())
    return ''


def candidates(conn, limit, today=None):
    today = (today or dt.date.today()).isoformat()
    retry = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat(timespec='seconds')
    out = []
    # Agendas de sala leídas con IA (23-10-2026): el listado no trae texto; la página propia del acto sí.
    try:
        own = conn.execute("""SELECT r.source, r.id, r.title, r.source_url FROM source_records r
            LEFT JOIN organizer_texts o ON o.source=r.source AND o.id=r.id
            WHERE r.source LIKE 'venue_ia_%' AND r.end_date>=? AND r.eligibility<>'exclude'
              AND COALESCE(json_extract(r.raw_json,'$.loagendo.description'),'')=''
              AND (o.id IS NULL OR (o.status<>'ok' AND o.fetched_at<?))
            ORDER BY r.start_date LIMIT ?""", (today, retry, limit * 3)).fetchall()
    except sqlite3.DatabaseError: own = []
    for source, rid, title, url in own:
        if usable_link(url) and _words(title) & _words(urlsplit(url).path.replace('-', ' ').replace('_', ' ')):
            out.append((source, rid, title, url))
        if len(out) >= limit: return out
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, e.description, e.links_json FROM source_records r
            JOIN source_enrichments e ON e.source=r.source AND e.id=r.id
            LEFT JOIN organizer_texts o ON o.source=r.source AND o.id=r.id
            WHERE r.source='guiabcn' AND r.end_date>=? AND r.eligibility<>'exclude'
              AND NOT EXISTS (SELECT 1 FROM source_records t WHERE t.source='opendatabcn_agenda' AND t.id=r.id)
              AND length(trim(COALESCE(e.description,'')))<?
              AND (o.id IS NULL OR (o.status<>'ok' AND o.fetched_at<?))
            ORDER BY r.start_date LIMIT ?""", (today, SHORT, retry, limit * 3)).fetchall()
    except sqlite3.DatabaseError: rows = []
    for source, rid, title, desc, links in rows:
        try: links = json.loads(links or '[]')
        except ValueError: links = []
        # Los enlaces oficiales de GuiaBCN son {label, url}; primero la web del acto, luego el resto.
        items = [(l.get('label', ''), l.get('url', '')) if isinstance(l, dict) else ('', l) for l in links if isinstance(l, (dict, str))]
        items.sort(key=lambda x: 0 if re.search(r'web', str(x[0]), re.I) else 1)
        url = next((u for _, u in items if usable_link(u)), '')
        if url: out.append((source, rid, title, url))
        if len(out) >= limit: break
    return out


def run(conn, limit=150, fetcher=None, timeout=15, today=None):
    from src.venue_feeds import fetch, robots_allows
    import time
    initialize(conn); fetcher = fetcher or fetch
    found = ok = images = 0; pages = {}
    for source, rid, title, url in candidates(conn, limit, today):
        status, text, ptitle = 'sin_texto', '', ''
        try:
            if fetcher is fetch and not robots_allows(url): status = 'robots'
            else:
                # Una obra con funciones diarias son varias fichas con la misma página: se lee una vez por pasada.
                if url not in pages: pages[url] = fetcher(url, timeout)
                st, final, page = pages[url]
                if st != 200: status = f'http_{st}'
                else:
                    text, ptitle = page_text(page)
                    if source.startswith('venue_ia_'):
                        longer = jsonld_text(page, title)
                        if len(longer) > len(text): text = longer
                        # Imagen que la sala pone para compartir el acto, con su crédito, si la ficha no tiene.
                        from src.venue_feeds import og_meta
                        image = og_meta(page).get('og:image', '')
                        if image.startswith(('https://', 'http://')) and not conn.execute('SELECT 1 FROM media_assets WHERE source=? AND id=?', (source, rid)).fetchone():
                            from src.media import register
                            venue = conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=? ORDER BY seq LIMIT 1', (source, rid)).fetchone()
                            with conn: register(conn, source, rid, image, alt=title, credit=venue[0] if venue else '')
                            images += 1
                    if len(text) < MIN_TEXT: status = 'corto'
                    elif not (_words(title) & (_words(text) | _words(ptitle) | _words(urlsplit(final or url).path.replace('-', ' ')))): status = 'no_es_del_acto'
                    else: status = 'ok'; ok += 1
            if fetcher is fetch and len(pages) and url == list(pages)[-1]: time.sleep(0.5)
        except Exception as error:
            status = 'error: ' + type(error).__name__
        found += 1
        with conn:
            conn.execute("""INSERT INTO organizer_texts(source,id,url,text,page_title,status,fetched_at) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET url=excluded.url,text=excluded.text,page_title=excluded.page_title,status=excluded.status,fetched_at=excluded.fetched_at""",
                         (source, rid, url, text[:MAX_TEXT] if status == 'ok' else text[:MAX_TEXT], ptitle[:300], status, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')))
    # Texto genérico del sitio: el mismo para tres actos distintos de la misma web.
    with conn:
        conn.execute("""UPDATE organizer_texts SET status='generico_del_sitio' WHERE status='ok' AND text IN (
            SELECT text FROM organizer_texts WHERE status='ok' GROUP BY text HAVING COUNT(DISTINCT url)>=3)""")
    return {'status': 'completed', 'attempted': found, 'with_text': ok, 'images': images}


def texts(conn):
    """{(source, id): (texto, url)} aceptados."""
    try: return {(s, i): (t, u) for s, i, t, u in conn.execute("SELECT source,id,text,url FROM organizer_texts WHERE status='ok' AND text<>''")}
    except sqlite3.DatabaseError: return {}
