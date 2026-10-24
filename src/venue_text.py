"""Texto completo de la página del acto en la web de la propia sala (25-10-2026).

Varias salas solo nos dan, por su programación, una línea (subtítulo e intérpretes del Palau,
compositor del Liceu, og:description del Jamboree) o la meta descripción recortada «…» (MACBA,
Lliure, L'Auditori, CCCB). La página de cada acto tiene el texto entero. Se lee el bloque de la
descripción de cada web, una regla por sala comprobada a mano en su página (RULES): nunca la página
entera, para no coger avisos, horarios de taquilla ni cajas de «también te interesa».

En el mismo paso se leen las versiones de la página en castellano e inglés que la sala enlaza
(<link hreflang>, su selector de idioma o /es/ y /en/ en el Jamboree), con el mismo bloque: son la
traducción oficial de ese texto y tienen prioridad sobre la automática. Solo se aceptan si la
página dice estar en ese idioma y el texto no es el original ni parece de otro idioma.

Procedencia: URL, fecha y huella del HTML de cada lectura, e historial de cambios
(venue_text_log). La ficha conserva el texto de la fuente; el completo se muestra cuando es más
largo. Se respeta robots.txt, media pausa entre páginas, y cada acto se vuelve a leer a los 3 días.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import sqlite3
import time
from html.parser import HTMLParser

from src.ai_translate import TARGETS
from src.official_translations import acceptable, alternates, jamboree_url, page_lang, switch_links

RECHECK_DAYS = 3
MIN_TEXT = 150
MAX_TEXT = 3000
# Bloque de la descripción en cada web (comprobado en sus páginas el 24/25-10-2026):
#   ('class', token) = primer elemento con esa clase; ('id', valor) = elemento con ese id.
#   'p': párrafos y elementos de lista del bloque; 'text': todo el texto del bloque (el Lliure escribe con <br>).
RULES = {
    'venue_palau_musica': {'match': ('class', 'production_description'), 'mode': 'p'},
    'venue_liceu': {'match': ('class', 'wrapper-paragraph'), 'mode': 'p'},
    'venue_jamboree': {'match': ('class', 'elementor-widget-theme-post-content'), 'mode': 'p'},
    'web_teatre_lliure': {'match': ('id', 'infoPlay-1'), 'mode': 'text'},
    'web_macba': {'match': ('class', 'detail-text-col-8'), 'mode': 'p'},
    'web_auditori': {'match': ('class', 'wp-block-post-content'), 'mode': 'p'},
    'web_cccb': {'match': ('class', 'mp-formated-content'), 'mode': 'p'},
}
SKIP = {'script', 'style', 'noscript', 'svg', 'template', 'button', 'form', 'select', 'nav', 'iframe'}
VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'col', 'embed', 'param', 'track'}
BLOCK = {'p', 'div', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'blockquote', 'tr', 'dd', 'dt', 'figcaption'}
BOILER = re.compile(r"cookie|galetes|newsletter|subscriu|suscr[ií]bete|privacitat|privacidad|avís legal|aviso legal|^\s*(?:saber más|saber més|saber-ne més|read more|see more|llegir més|leer más|veure més|ver más|més info|más info|more info)\s*$", re.I)


class _Block(HTMLParser):
    def __init__(self, rule):
        super().__init__(convert_charrefs=True)
        self.kind, self.value = rule['match']; self.mode = rule['mode']
        self.depth = 0; self.done = False; self.skip = 0; self.item = None; self.items = []; self.buf = []

    def _hit(self, attrs):
        a = dict(attrs)
        if self.kind == 'id': return a.get('id') == self.value
        return self.value in (a.get('class') or '').split()

    def handle_starttag(self, tag, attrs):
        if self.done: return
        if not self.depth:
            if self._hit(attrs) and tag not in VOID: self.depth = 1
            return
        if tag not in VOID: self.depth += 1
        if tag in SKIP: self.skip += 1; return
        if self.skip: return
        if self.mode == 'p':
            if tag in ('p', 'li'): self.item = []
            elif tag == 'br' and self.item is not None: self.item.append('\n')
        elif tag == 'br' or tag in BLOCK: self.buf.append('\n')

    def handle_endtag(self, tag):
        if self.done or not self.depth or tag in VOID: return
        if tag in SKIP and self.skip: self.skip -= 1
        elif not self.skip:
            if self.mode == 'p' and tag in ('p', 'li') and self.item is not None:
                self.items.append(''.join(self.item)); self.item = None
            elif self.mode == 'text' and tag in BLOCK: self.buf.append('\n')
        self.depth -= 1
        if not self.depth: self.done = True

    def handle_data(self, data):
        if self.done or not self.depth or self.skip: return
        if self.mode == 'p':
            if self.item is not None: self.item.append(data)
        else: self.buf.append(data)

    def text(self):
        raw = '\n\n'.join(self.items) if self.mode == 'p' else ''.join(self.buf)
        paras, out = re.split(r'\n\s*\n', raw), []
        for para in paras:
            lines = [' '.join(l.split()) for l in para.split('\n')]
            para = '\n'.join(l for l in lines if l and not BOILER.search(l))
            if para and para not in out: out.append(para)
        text = '\n\n'.join(out)
        if len(text) > MAX_TEXT:  # se corta en el último párrafo entero que cabe
            cut = text[:MAX_TEXT].rsplit('\n', 1)[0]; text = cut if len(cut) > MAX_TEXT // 2 else text[:MAX_TEXT]
        return text


def extract(source, page):
    rule = RULES.get(source)
    if not rule or not page: return ''
    parser = _Block(rule)
    try: parser.feed(page); parser.close()
    except Exception: pass
    return parser.text()


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS venue_texts (
      source TEXT NOT NULL, id TEXT NOT NULL, lang TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL, page_sha256 TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL, PRIMARY KEY(source, id, lang));
    CREATE TABLE IF NOT EXISTS venue_text_log (
      source TEXT NOT NULL, id TEXT NOT NULL, lang TEXT NOT NULL, url TEXT NOT NULL, text TEXT NOT NULL,
      status TEXT NOT NULL, page_sha256 TEXT NOT NULL, fetched_at TEXT NOT NULL);
    """)


def _save(conn, source, rid, lang, url, text, status, page):
    sha = hashlib.sha256(page.encode('utf-8')).hexdigest() if page else ''
    text = text if status == 'ok' else ''
    prev = conn.execute('SELECT url,text,status FROM venue_texts WHERE source=? AND id=? AND lang=?', (source, rid, lang)).fetchone()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute("""INSERT INTO venue_texts(source,id,lang,url,text,status,page_sha256,fetched_at) VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(source,id,lang) DO UPDATE SET url=excluded.url,text=excluded.text,status=excluded.status,page_sha256=excluded.page_sha256,fetched_at=excluded.fetched_at""",
                     (source, rid, lang, url, text, status, sha, now))
        if prev != (url, text, status): conn.execute('INSERT INTO venue_text_log VALUES (?,?,?,?,?,?,?,?)', (source, rid, lang, url, text, status, sha, now))


def candidates(conn, today, limit):
    before = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec='seconds')
    marks = ','.join('?' for _ in RULES)
    return conn.execute(f"""SELECT r.source,r.id,r.source_url FROM source_records r
        LEFT JOIN venue_texts v ON v.source=r.source AND v.id=r.id AND v.lang='orig'
        WHERE r.source IN ({marks}) AND r.end_date>=? AND r.eligibility<>'exclude' AND r.source_url LIKE 'https://%'
          AND (v.id IS NULL OR v.fetched_at<?)
        ORDER BY v.fetched_at IS NOT NULL, r.start_date, r.id LIMIT ?""", (*RULES, today, before, limit)).fetchall()


def run(conn, job=None, fetcher=None, today=None):
    """Trabajo «textos-sala»."""
    from src.venue_feeds import fetch, robots_allows
    job = job or {}; real = fetcher is None; fetcher = fetcher or fetch
    today = today or dt.date.today().isoformat(); timeout = job.get('timeout_seconds', 15)
    initialize(conn); last = {'t': 0.0}; pages = {}; stats = {}

    def get(url):
        """(status, html); None si robots.txt no deja. Una página se lee una vez por pasada (varios días, misma obra)."""
        if url in pages: return pages[url]
        if real:
            if not robots_allows(url): pages[url] = (None, ''); return pages[url]
            wait = 0.5 - (time.monotonic() - last['t'])
            if wait > 0: time.sleep(wait)
            last['t'] = time.monotonic()
        try: st, _, body = fetcher(url, timeout)
        except Exception as error: st, body = 0, ''
        pages[url] = (st, body if st == 200 else ''); return pages[url]

    for source, rid, url in candidates(conn, today, job.get('limit', 300)):
        st, page = get(url)
        if st is None: status, text = 'robots', ''
        elif not page: status, text = f'http_{st}', ''
        else:
            text = extract(source, page); status = 'ok' if len(text) >= MIN_TEXT else ('corto' if text else 'sin_bloque')
        _save(conn, source, rid, 'orig', url, text, status, page)
        stats[status] = stats.get(status, 0) + 1
        if status != 'ok':
            for lang in TARGETS: _save(conn, source, rid, lang, '', '', 'sin_original', '')
            continue
        own = page_lang(page)
        links = (alternates(page, url) or switch_links(page, url)) if source != 'venue_jamboree' else {lang: jamboree_url(url, lang) for lang in TARGETS}
        for lang in TARGETS:
            link = links.get(lang) or ''
            if own == lang or (link and link.rstrip('/') == url.rstrip('/')): status_l, text_l, page_l = 'es_el_original', '', ''
            elif not link: status_l, text_l, page_l = 'sin_version', '', ''
            else:
                st_l, page_l = get(link)
                if st_l is None: status_l, text_l = 'robots', ''
                elif not page_l: status_l, text_l = f'http_{st_l}', ''
                else:
                    text_l = extract(source, page_l)
                    status_l = acceptable(text_l, text, lang, page_lang(page_l)) if len(text_l) >= MIN_TEXT else 'corto'
            _save(conn, source, rid, lang, link, text_l, status_l, page_l)
            stats[f'{lang}:{status_l}'] = stats.get(f'{lang}:{status_l}', 0) + 1
    return {'status': 'completed', 'resultado': stats}


def text_for(conn, source, rid, lang='orig'):
    """(texto, url) aceptado de la página de la sala en ese idioma ('orig' = la página de la ficha), o None."""
    try: row = conn.execute("SELECT text,url,fetched_at FROM venue_texts WHERE source=? AND id=? AND lang=? AND status='ok' AND text<>''", (source, rid, lang)).fetchone()
    except sqlite3.DatabaseError: return None
    return {'text': row[0], 'url': row[1], 'date': row[2][:10]} if row else None
