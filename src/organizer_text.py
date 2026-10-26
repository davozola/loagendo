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
from html.parser import HTMLParser
from urllib.parse import urlsplit

MIN_TEXT = 60
MAX_TEXT = 700
SHORT = 80
# Lo leído antes de esta hora con resultado «corto» o «sin texto» se vuelve a leer en la siguiente pasada:
# el lector anterior cortaba en el primer apóstrofo y no leía el cuerpo de la página (24-10-2026).
REREAD_BEFORE = '2026-10-24T09:00:00+00:00'
CREDIT = 'la web del organizador'
SKIP_HOSTS = re.compile(r"(?:^|\.)(?:barcelona\.cat|bcn\.cat|instagram\.com|facebook\.com|fb\.me|twitter\.com|x\.com|youtube\.com|youtu\.be|tiktok\.com|linkedin\.com|"
                        r"ticketmaster\.\w+|entradas\.com|eventbrite\.\w+|atrapalo\.com|fever\w*\.com|dice\.fm|wegow\.com|taquilla\.com|tickets\.\w+|"
                        r"oneboxtds\.com|ra\.co|codetickets\.com|entradium\.com|koobin\.com|google\.\w+|goo\.gl|wa\.me|whatsapp\.com|linktr\.ee|mailto)$")
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
    """(descripción que la web publica para compartir, título de la página). Con src.venue_feeds.meta_tags:
    un apóstrofo («d'exploració») ya no corta el texto (24-10-2026)."""
    from src.venue_feeds import meta_tags
    tags = meta_tags(page)
    text = tags.get('og:description') or tags.get('description') or ''
    title = tags.get('og:title') or tags.get('<title>') or ''
    return ' '.join(text.split()), ' '.join(title.split())


# Texto y foto del cuerpo de la página del acto (24-10-2026), para webs de sala que no publican
# og:description ni og:image (Arts Santa Mònica) o publican una frase corta.
BOILER = re.compile(r"cookie|galetes|newsletter|butllet[ií]|bolet[ií]n|subscriu|suscr[ií]bete|uneix-te|privacitat|privacidad|avís legal|aviso legal|"
                    r"tots els drets|todos los derechos|javascript", re.I)
SKIP_TAGS = {'script', 'style', 'noscript', 'svg', 'template', 'nav', 'footer', 'header', 'aside', 'form', 'button', 'select'}
BAD_IMAGE = re.compile(r"logo|icon|sprite|avatar|placeholder|blank|pixel|banner-cookie|\.svg(?:\?|$)|\.gif(?:\?|$)", re.I)


class _Body(HTMLParser):
    """Párrafos (<p>) y fotos (<img>) del contenido, a partir del encabezado que lleva el título del acto."""
    def __init__(self, title_words):
        super().__init__(convert_charrefs=True)
        self.words = title_words; self.skip = 0; self.heading = None; self.started = False
        self.para = None; self.paras = []; self.images = []; self.has_main = False; self.in_main = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or '') for k, v in attrs if k}
        if tag in SKIP_TAGS: self.skip += 1; return
        if self.skip: return
        if tag in ('main', 'article'): self.has_main = True; self.in_main += 1
        if tag in ('h1', 'h2'): self.heading = []
        elif tag == 'p': self.para = []
        elif tag == 'br' and self.para is not None: self.para.append(' ')
        elif tag == 'img' and self.started:
            src = a.get('src') or a.get('data-src') or ''
            if src and not src.startswith('data:') and not BAD_IMAGE.search(src): self.images.append(src)

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            if self.skip: self.skip -= 1
            return
        if self.skip: return
        if tag in ('main', 'article') and self.in_main: self.in_main -= 1
        if tag in ('h1', 'h2') and self.heading is not None:
            if self.words & _words(''.join(self.heading)): self.started = True
            self.heading = None
        elif tag == 'p' and self.para is not None:
            if self.started: self.paras.append(' '.join(''.join(self.para).split()))
            self.para = None

    def handle_data(self, data):
        if self.skip: return
        if self.heading is not None: self.heading.append(data)
        if self.para is not None: self.para.append(data)


def body_text(page, title, limit=MAX_TEXT):
    """(texto, imagen) del cuerpo de la página del acto: los párrafos de 80 caracteres o más que siguen al
    encabezado con el título, tal cual y en su orden, hasta ``limit``; y su primera foto. Nada si la página
    no tiene un encabezado con palabras propias del título (entonces no sabemos qué parte es del acto)."""
    p = _Body(_words(title))
    try: p.feed(page or '')
    except Exception: pass
    out = []
    for para in p.paras:
        if len(para) < 80 or BOILER.search(para) or para in out: continue
        if out and len('\n\n'.join(out + [para])) > limit: break
        out.append(para)
    return '\n\n'.join(out)[:limit], (p.images[0] if p.images else '')


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
              AND (o.id IS NULL OR (o.status<>'ok' AND (o.fetched_at<? OR (o.status IN ('corto','sin_texto') AND o.fetched_at<?))))
            ORDER BY r.start_date LIMIT ?""", (today, retry, REREAD_BEFORE, limit * 3)).fetchall()
    except sqlite3.DatabaseError: own = []
    # Agendas propias de sala que no son de IA (Palau, Sala VOL, Nau Bostik…) sin texto (26-10-2026).
    try:
        own += [r for r in conn.execute("""SELECT r.source, r.id, r.title, r.source_url FROM source_records r
            JOIN listing_projections l ON l.source=r.source AND l.id=r.id
            LEFT JOIN organizer_texts o ON o.source=r.source AND o.id=r.id
            WHERE r.source LIKE 'venue_%' AND r.source NOT LIKE 'venue_ia_%' AND r.end_date>=? AND r.eligibility<>'exclude'
              AND COALESCE(json_extract(l.projection_json,'$.has_description'),0)=0
              AND (o.id IS NULL OR (o.status<>'ok' AND o.fetched_at<?))
            ORDER BY r.start_date LIMIT ?""", (today, retry, limit * 3)) if _first_party(r[0])]
    except sqlite3.DatabaseError: pass
    for source, rid, title, url in own:
        # El enlace es la página del acto en la web de la propia sala: no hace falta que la URL lleve el título
        # (ID numéricos, 26-10-2026); que el texto sea del acto se comprueba al leerla (no_es_del_acto).
        if usable_link(url): out.append((source, rid, title, url))
        if len(out) >= limit: return out
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, e.description, e.links_json FROM source_records r
            JOIN source_enrichments e ON e.source=r.source AND e.id=r.id
            LEFT JOIN organizer_texts o ON o.source=r.source AND o.id=r.id
            WHERE r.source='guiabcn' AND r.end_date>=? AND r.eligibility<>'exclude'
              AND NOT EXISTS (SELECT 1 FROM source_records t WHERE t.source='opendatabcn_agenda' AND t.id=r.id)
              AND length(trim(COALESCE(e.description,'')))<?
              AND (o.id IS NULL OR (o.status<>'ok' AND (o.fetched_at<? OR (o.status IN ('corto','sin_texto') AND o.fetched_at<?))))
            ORDER BY r.start_date LIMIT ?""", (today, SHORT, retry, REREAD_BEFORE, limit * 3)).fetchall()
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


def _first_party(source):
    from src.dedupe import first_party
    return first_party(source)


# Información práctica de la página (cómo llegar, horario del museo, compra de entradas): no describe el acto.
PRACTICAL = re.compile(r"p[aà]rquing|parking|aparcament|aparcamiento|com arribar|c[oó]mo llegar|transport p[uú]blic|\bmetro\b|autob[uú]s|"
                       r"obert de|abierto de|horari d['’]obertura|horario de apertura|prepara la teva visita|prepara tu visita|"
                       r"comprar entrades|comprar entradas|\bhorari\b|\bhorario\b|\bpreu\b|\bprecio\b|iva incl|accessibilitat|accesibilidad", re.I)


def excerpt_paragraphs(excerpt, title):
    """Párrafos del acto en el texto ya leído de su página oficial (official_pages.excerpt, una línea por bloque):
    las líneas largas con frases, sin menús, avisos de cookies ni textos legales; tal cual, sin reescribir."""
    out = []
    for line in str(excerpt or '').split('\n'):
        line = ' '.join(line.split())
        if len(line) < 90 or len(line.split()) < 12 or BOILER.search(line) or PRACTICAL.search(line) or line.isupper(): continue
        if not re.search(r"[.!?…»)]$", line): continue
        out.append(line)
        if sum(len(x) for x in out) >= MAX_TEXT: break
    text = ' '.join(out)[:MAX_TEXT]
    head = str(excerpt or '').split('\n', 1)[0]
    return text if len(text) >= MIN_TEXT and _words(title) & (_words(text) | _words(head)) else ''


def from_official_pages(conn):
    """Sin red (26-10-2026): para las fichas sin texto aceptado, los párrafos del acto en la página oficial que
    official_dates ya leyó para la hora y el precio. Mismos filtros; el genérico del sitio se descarta en run()."""
    try:
        rows = conn.execute("""SELECT p.source, p.id, p.url, p.excerpt, r.title FROM official_pages p
            JOIN source_records r ON r.source=p.source AND r.id=p.id
            LEFT JOIN organizer_texts o ON o.source=p.source AND o.id=p.id
            WHERE p.status='ok' AND p.excerpt<>'' AND r.end_date>=date('now') AND (o.id IS NULL OR o.status<>'ok')""").fetchall()
    except sqlite3.DatabaseError: return 0
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'); n = 0
    with conn:
        for source, rid, url, excerpt, title in rows:
            text = excerpt_paragraphs(excerpt, title)
            if not text or not usable_link(url): continue
            conn.execute("""INSERT INTO organizer_texts(source,id,url,text,page_title,status,fetched_at) VALUES(?,?,?,?,?,'ok',?)
                ON CONFLICT(source,id) DO UPDATE SET url=excluded.url,text=excluded.text,page_title=excluded.page_title,status='ok',fetched_at=excluded.fetched_at""",
                         (source, rid, url, text, str(excerpt).split('\n', 1)[0][:300], now)); n += 1
    return n


def run(conn, limit=150, fetcher=None, timeout=15, today=None):
    from src.venue_feeds import fetch, robots_allows
    import time
    initialize(conn); fetcher = fetcher or fetch
    reused = from_official_pages(conn)
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
                        # La página propia del acto: su schema.org o, si no, sus párrafos, cuando dicen más.
                        longer = jsonld_text(page, title)
                        body, body_image = body_text(page, title)
                        for candidate in (longer, body):
                            if len(candidate) > len(text): text = candidate
                        # Imagen que la sala pone para compartir el acto, con su crédito, si la ficha no tiene; si la
                        # página no la declara (og:image), la primera foto del contenido del acto (24-10-2026).
                        from src.venue_feeds import og_meta
                        from urllib.parse import urljoin
                        image = og_meta(page).get('og:image', '') or (urljoin(final or url, body_image) if body_image else '')
                        if image.startswith(('https://', 'http://')) and not conn.execute('SELECT 1 FROM media_assets WHERE source=? AND id=?', (source, rid)).fetchone():
                            from src.media import register
                            venue = conn.execute('SELECT venue FROM source_venues WHERE source=? AND id=? ORDER BY seq LIMIT 1', (source, rid)).fetchone()
                            with conn: register(conn, source, rid, image, alt=title, credit=venue[0] if venue else '')
                            images += 1
                    if len(text) < MIN_TEXT: status = 'corto'
                    elif PRACTICAL.search(text[:40]): status = 'no_es_del_acto'  # «COMPRAR ENTRADES…», «Horari…» (26-10-2026)
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
    return {'status': 'completed', 'attempted': found, 'with_text': ok, 'images': images, 'from_official_pages': reused}


def texts(conn):
    """{(source, id): (texto, url)} aceptados."""
    try: return {(s, i): (t, u) for s, i, t, u in conn.execute("SELECT source,id,text,url FROM organizer_texts WHERE status='ok' AND text<>''")}
    except sqlite3.DatabaseError: return {}
