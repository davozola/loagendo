"""Agendas de sala leídas con IA y comprobadas contra el texto de la página (20-10-2026).

Para salas sin datos estructurados (ni JSON-LD, ni iCal, ni API): se descarga su página de agenda,
se limpia (fuera menú, pie y scripts) y Haiku devuelve los actos que la página anuncia, cada dato
con la frase exacta de donde sale. Nada pasa a la base sin esta comprobación, que no usa IA:

  · el título está literalmente en la página;
  · la fecha sale de su cita (el número del día; el mes, el año y el día de la semana si la cita
    los nombra) y la cita está cerca del título;
  · la hora está en su cita, cerca del título; el precio también;
  · el enlace es uno de los enlaces reales de la página; la sala (agendas de varias salas), una de
    las configuradas.

Un dato que no pasa se descarta; un acto sin fecha comprobada no entra. Ahorro: si el texto de la
página no ha cambiado desde la última lectura, no se llama a la IA. Las fichas quedan como fuente
``venue_ia_<sala>`` («Datos de la sala»), con la página, su huella, el modelo, la versión de las
instrucciones y las citas. Lo que desaparece de la página no se borra: deja de publicarse.
Imágenes: la que la propia sala pone para compartir la ficha del acto (og:image), con su crédito.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from src.ai_extract import fold, times_in

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / 'config' / 'agendas_ia.json'
PROMPT_VERSION = 1
LABEL = 'Datos de la sala'
CHUNK_CHARS = 8000           # ~2.500 tokens por petición: la respuesta (una entrada por acto) cabe entera
MAX_CHARS = 70000            # tope de texto por agenda y pasada
IMAGE_BUDGET = 40            # páginas de acto leídas por agenda y pasada para su imagen
NEAR_TIME, NEAR_PRICE, NEAR_DATE_AFTER, NEAR_DATE_BEFORE = 500, 900, 700, 5000

MONTHS = {1: ('gen', 'ene', 'jan'), 2: ('feb', 'febr'), 3: ('mar',), 4: ('abr', 'apr'), 5: ('mai', 'may'), 6: ('jun',),
          7: ('jul',), 8: ('ago', 'aug'), 9: ('set', 'sep'), 10: ('oct',), 11: ('nov',), 12: ('des', 'dic', 'dec')}
MONTH_RX = re.compile(r"\b(gener|febrer|marc|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre|enero|febrero|marzo|mayo|junio|julio|agosto|"
                      r"septiembre|setiembre|noviembre|diciembre|january|february|march|april|june|july|august|september|october|november|december|"
                      r"gen|ene|febr|feb|mar|abr|apr|mai|may|jun|jul|ago|aug|set|sep|oct|nov|des|dic|dec)\.?\b")
WEEKDAYS = {0: ('dilluns', 'lunes', 'monday', 'dl', 'lun'), 1: ('dimarts', 'martes', 'tuesday', 'dt', 'mar'), 2: ('dimecres', 'miercoles', 'wednesday', 'dc', 'mie', 'mi'),
            3: ('dijous', 'jueves', 'thursday', 'dj', 'jue', 'ju'), 4: ('divendres', 'viernes', 'friday', 'dv', 'vie', 'vi'),
            5: ('dissabte', 'sabado', 'saturday', 'ds', 'sab', 'sa'), 6: ('diumenge', 'domingo', 'sunday', 'dg', 'dom', 'do')}
WEEKDAY_FULL = re.compile(r"\b(dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo|"
                          r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b")
FREE_RX = re.compile(r"gratu|gratis|lliure|libre|free|sense cost|sin coste")

SYSTEM = """Lees la página de agenda de una sala o espacio cultural de Barcelona y devuelves los actos que anuncia, para la agenda Brollant.
Reglas estrictas:
- Devuelve TODOS los actos con fecha que aparecen en el texto, uno por uno, aunque sean muchos (50 o más) y aunque se repitan cada semana: no resumas, no agrupes, no te quedes con una muestra.
- Solo actos que la página anuncia explícitamente con fecha. Nada deducido, nada inventado. Si la agenda es de varias salas, indica en sala cuál de las salas_posibles.
- Solo actos en la ciudad de Barcelona: si el texto dice que es en otra ciudad (Madrid, online, etc.), no lo incluyas.
- Si otros_lugares es true y el texto dice que el acto es en otro lugar de Barcelona (otro cine, museo, sala…), pon en sala ese lugar tal como aparece escrito y en cita_sala la frase donde se lee. Si otros_lugares es false, no incluyas actos que el texto sitúa en otro lugar.
- titulo: tal como aparece en la página (cópialo literal, sin añadir ni traducir).
- sesiones: cada fecha (y hora, si la página la da) del acto. fecha en formato AAAA-MM-DD. Si la página no da el año o el mes junto al día, usa la fecha futura más próxima coherente con la página y con la fecha de hoy que te doy.
- cita_fecha y cita_hora: copia literal y corta (máx. 120 caracteres) del texto donde se lee el día y la hora; tiene que poder encontrarse tal cual en la página. cita_fecha nunca es solo un número: incluye el mes o el día de la semana que lo acompañan («20 octubre», «Dimarts 27», «21.10.26»). Si no hay hora escrita, hora y cita_hora vacías.
- Si la página da un periodo («del 15 d'octubre al 22 de novembre»), usa periodo {inicio, fin, cita} en lugar de una sesión por día.
- precio y cita_precio solo si la página lo escribe para ese acto.
- enlace: la marca [Ln] que va justo con ese acto en el texto, si la hay (por ejemplo L12); si no, vacío.
- No incluyas actos ya pasados respecto a la fecha de hoy.
Responde con la herramienta actos."""

TOOL = {'name': 'actos', 'description': 'Actos que anuncia la página, con citas literales.',
        'input_schema': {'type': 'object', 'required': ['actos'], 'properties': {'actos': {'type': 'array', 'items': {
            'type': 'object', 'required': ['titulo'],
            'properties': {'titulo': {'type': 'string'}, 'sala': {'type': 'string'}, 'enlace': {'type': 'string'},
                           'sesiones': {'type': 'array', 'items': {'type': 'object', 'required': ['fecha', 'cita_fecha'], 'properties': {
                               'fecha': {'type': 'string'}, 'cita_fecha': {'type': 'string'}, 'hora': {'type': 'string'}, 'cita_hora': {'type': 'string'}}}},
                           'periodo': {'type': 'object', 'properties': {'inicio': {'type': 'string'}, 'fin': {'type': 'string'}, 'cita': {'type': 'string'}}},
                           'cita_sala': {'type': 'string'},
                           'precio': {'type': 'string'}, 'cita_precio': {'type': 'string'}}}}}}}


# ---------- configuración ----------
def load_agendas(path=CONFIG_PATH):
    try: return json.loads(Path(path).read_text(encoding='utf-8')).get('agendas', [])
    except (OSError, ValueError): return []


def expand_urls(agenda, today):
    monday = today - dt.timedelta(days=today.weekday())
    out = []
    for url in agenda.get('urls') or []:
        out.append(re.sub(r"\{lunes\+(\d+)\}", lambda m: (monday + dt.timedelta(days=int(m.group(1)))).isoformat(), url))
    return out


# ---------- limpieza de la página ----------
class _Cleaner(HTMLParser):
    # <header>, <form> y <button> no se saltan: muchas webs ponen dentro la cabecera de cada acto
    # (Antic Teatre: <article><header>fecha, título…</header>) o envuelven el listado en un filtro.
    SKIP = {'script', 'style', 'noscript', 'svg', 'nav', 'footer', 'iframe', 'template', 'select'}
    BLOCK = {'p', 'div', 'li', 'tr', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article', 'dt', 'dd', 'td', 'th', 'time'}

    def __init__(self, base_url):
        super().__init__(convert_charrefs=True)
        self.base = base_url; self.parts = []; self.skip = 0; self.links = []; self.stack = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1; return
        if self.skip: return
        if tag in self.BLOCK: self.parts.append('\n')
        if tag == 'a':
            href = dict(attrs).get('href') or ''
            url = urljoin(self.base, html.unescape(href)).split('#', 1)[0]
            if url.startswith(('http://', 'https://')):
                if url not in self.links: self.links.append(url)
                self.stack.append(self.links.index(url) + 1)
            else: self.stack.append(None)

    def handle_endtag(self, tag):
        if tag in self.SKIP: self.skip = max(0, self.skip - 1); return
        if self.skip: return
        if tag == 'a' and self.stack:
            n = self.stack.pop()
            if n: self.parts.append(f' [L{n}] ')
        if tag in self.BLOCK: self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip and data.strip(): self.parts.append(data)


def clean(page, base_url):
    """(texto con marcas [Ln] tras cada enlace, lista de enlaces)."""
    parser = _Cleaner(base_url)
    try: parser.feed(page or ''); parser.close()
    except Exception: pass
    text = ''.join(parser.parts)
    lines = [' '.join(line.split()) for line in text.split('\n')]
    out, last = [], None
    for line in lines:
        if not line or line == last: continue
        out.append(line); last = line
    # Sin marcas de enlaces repetidas en la misma línea («[L3] [L3]»).
    joined = re.sub(r"(\[L\d+\])(?:\s*\1)+", r"\1", '\n'.join(out))
    return joined, parser.links


def chunks(text, size=CHUNK_CHARS):
    out, cur = [], ''
    for line in text.split('\n'):
        if len(cur) + len(line) + 1 > size and cur: out.append(cur); cur = ''
        cur += line + '\n'
    if cur.strip(): out.append(cur)
    return out


# ---------- comprobación ----------
def _positions(needle, hay):
    n = fold(needle).strip(' .,;:"\'«»'); out = []
    if len(n) < 3: return out
    i = hay.find(n)
    while i >= 0: out.append(i); i = hay.find(n, i + 1)
    return out


def _date_from_quote(iso, quote, today, allow_past=False):
    """La fecha de la IA es coherente con su cita: el día está; el mes, el año y el día de la semana, si
    la cita los nombra, coinciden; sin mes en la cita, es la fecha futura más próxima con ese día."""
    try: d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError: return None
    q = fold(quote)
    if (d < today and not allow_past) or d < today - dt.timedelta(days=1200) or d > today + dt.timedelta(days=400): return None
    if not re.search(rf"(?<!\d)0?{d.day}(?!\d)", q): return None
    years = set(re.findall(r"\b(20\d\d)\b", q))
    if years and str(d.year) not in years: return None
    # «21/10», «21.10.26», «21-10-2026» (el guion solo con año: «22-26 octubre» es un intervalo de días).
    numeric = re.search(rf"(?<!\d)0?{d.day}\s*[/.]\s*(1[0-2]|0?[1-9])(?!\d)(?:\s*[/.]\s*(\d{{2,4}}))?|(?<!\d)0?{d.day}-(1[0-2]|0?[1-9])-(\d{{2,4}})", q)
    months = [m for m in MONTH_RX.findall(q)]
    if numeric:
        month, year = numeric.group(1) or numeric.group(3), numeric.group(2) or numeric.group(4)
        if int(month) != d.month: return None
        if year and int(year[-2:]) != d.year % 100: return None
    elif months:
        if not any(m[:3] in MONTHS[d.month] or m in MONTHS[d.month] for m in months): return None
    else:
        # Sin mes: tiene que ser la primera fecha futura con ese número de día.
        if allow_past: return None
        probe = today
        while probe.day != d.day: probe += dt.timedelta(days=1)
        if probe != d: return None
    wd = WEEKDAY_FULL.findall(q)
    if len(set(wd)) == 1 and wd[0] not in WEEKDAYS[d.weekday()]: return None
    return d


def _near(a_positions, b_positions, before, after):
    return any(-before <= b - a <= after for a in a_positions for b in b_positions)


def _same_place(a, b):
    a, b = fold(a), fold(b)
    return bool(a and b) and (a in b or b in a)


def verify(item, text, links, today, salas=None, other_places=False, own_name=''):
    """(acto comprobado o None, motivos de descarte)."""
    hay = fold(text); why = []
    title = ' '.join(str(item.get('titulo') or '').split())
    tpos = _positions(title, hay)
    if not title or not tpos: return None, ['título que no está en la página']
    out = {'titulo': title, 'sesiones': [], 'quotes': {}}
    # Sala (agendas de varias salas): una de las configuradas.
    if salas:
        sala = next((s for s in salas if fold(s['name']) == fold(item.get('sala'))), None)
        if not sala: return None, [f"sala no configurada: {item.get('sala')!r}"]
        out['sala'] = sala
    elif other_places and str(item.get('sala') or '').strip() and not _same_place(item['sala'], own_name):
        # Acto en otro lugar (Goethe-Institut en el Institut français, Casa Amèrica en Cinemes Girona):
        # el lugar tiene que estar escrito en la página, cerca del título.
        place = ' '.join(str(item['sala']).split())
        if not _near(tpos, _positions(place, hay), 1500, 1500): return None, [f"lugar que no está junto al acto: {place!r}"]
        out['sala'] = {'name': place, 'address': ''}
    for s in item.get('sesiones') or []:
        qd = str(s.get('cita_fecha') or ''); dpos = _positions(qd, hay)
        if not dpos: why.append(f"cita de fecha que no está en la página: {qd!r}"); continue
        # La fecha va delante (cabecera de día, hasta NEAR_DATE_BEFORE) o justo detrás del título.
        if not _near(tpos, dpos, NEAR_DATE_BEFORE, NEAR_DATE_AFTER):
            why.append(f"fecha lejos del título: {qd!r}"); continue
        d = _date_from_quote(s.get('fecha'), qd, today)
        if not d: why.append(f"fecha que no cuadra con su cita: {s.get('fecha')} / {qd!r}"); continue
        hour = ''
        h, qh = str(s.get('hora') or '').strip(), str(s.get('cita_hora') or '')
        if h:
            hpos = _positions(qh, hay)
            if re.fullmatch(r"\d{1,2}:\d{2}", h) and hpos and _near(tpos, hpos, NEAR_TIME, NEAR_TIME) and f"{int(h[:-3]):02d}:{h[-2:]}" in times_in(qh):
                hour = f"{int(h[:-3]):02d}:{h[-2:]}"; out['quotes'].setdefault('time', qh)
            else: why.append(f"hora sin cita válida: {h} / {qh!r}")
        out['sesiones'].append((d.isoformat(), hour)); out['quotes'].setdefault('date', qd)
    p = item.get('periodo') or {}
    if p.get('inicio') and p.get('fin'):
        qp = str(p.get('cita') or ''); ppos = _positions(qp, hay)
        a, b = _date_from_quote(p['inicio'], qp, today, allow_past=True), _date_from_quote(p['fin'], qp, today)
        if not a and b and str(p['inicio'])[:10] <= today.isoformat():
            # Obra en cartel desde antes de hoy («Del dv. 19.04.24 al dc. 30.12.26») que la IA recorta a
            # hoy: vale la primera fecha que da la cita, si es anterior a hoy.
            first = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})(?!\d)", fold(qp))
            if first:
                y = int(first.group(3)); y = y + 2000 if y < 100 else y
                try:
                    cand = dt.date(y, int(first.group(2)), int(first.group(1)))
                    if cand < today: a = cand
                except ValueError: pass
        if ppos and a and b and a <= b and (_near(tpos, ppos, 1500, 1500)):
            out['periodo'] = (a.isoformat(), b.isoformat()); out['quotes'].setdefault('date', qp)
        else: why.append(f"periodo sin cita válida: {p!r}")
    if not out['sesiones'] and not out.get('periodo'): return None, why or ['sin fecha comprobada']
    price, qpr = str(item.get('precio') or '').strip(), str(item.get('cita_precio') or '')
    if price:
        ppos = _positions(qpr, hay); digits = re.findall(r"\d+(?:[.,]\d+)?", price)
        ok = ppos and _near(tpos, ppos, NEAR_PRICE, NEAR_PRICE) and (all(x in qpr for x in digits) if digits else FREE_RX.search(fold(qpr)))
        if ok: out['precio'] = price; out['quotes']['price'] = qpr
        else: why.append(f"precio sin cita válida: {price!r}")
    m = re.fullmatch(r"\[?L(\d+)\]?", str(item.get('enlace') or '').strip())
    if m and 1 <= int(m.group(1)) <= len(links):
        url = links[int(m.group(1)) - 1]
        if f"[l{m.group(1)}]" in hay: out['url'] = url
    return out, why


# ---------- IA ----------
def ask(agenda, text, page_url, today, key, requester=None, model=None, usage=None):
    from src import ai_assist
    requester = requester or ai_assist._request; model = model or ai_assist.MODEL
    found = []
    salas = [s['name'] for s in agenda.get('salas') or []]
    for part in chunks(text):
        context = {'sala': agenda['name'], 'salas_posibles': salas, 'otros_lugares': bool(agenda.get('otros_lugares')), 'pagina': page_url, 'hoy': today.isoformat(), 'texto': part}
        body = {'model': model, 'max_tokens': 16000,
                'system': [{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
                'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'actos'},
                'messages': [{'role': 'user', 'content': json.dumps(context, ensure_ascii=False)}]}
        message = requester('POST', f'{ai_assist.API}/messages', key, body, timeout=180)
        if usage is not None:
            for k, v in (message.get('usage') or {}).items():
                if isinstance(v, int): usage[k] = usage.get(k, 0) + v
            usage.setdefault('stop_reasons', {}); reason = message.get('stop_reason') or '?'
            usage['stop_reasons'][reason] = usage['stop_reasons'].get(reason, 0) + 1
        for block in message.get('content') or []:
            if block.get('type') == 'tool_use' and block.get('name') == 'actos':
                found.extend(x for x in (block.get('input') or {}).get('actos') or [] if isinstance(x, dict))
    return found


# ---------- registros ----------
def records_for(agenda, accepted, page_url, page_hash, model):
    """Fichas (forma de src.sync) de los actos comprobados: una por día con sus pases; un periodo, una ficha."""
    from src.venue_feeds import record_from_jsonld
    slug = 'ia_' + agenda['slug']
    out = []
    for act in accepted:
        sala = act.get('sala') or {'name': agenda['name'], 'address': agenda.get('address') or ''}
        venue = {'slug': slug, 'name': sala['name'], 'type': agenda.get('type', 'culture')}
        address = {'@type': 'PostalAddress', 'streetAddress': sala.get('address') or '', 'addressLocality': 'Barcelona'}
        base = {'@type': 'Event', 'name': act['titulo'], 'url': act.get('url') or page_url,
                'location': {'@type': 'Place', 'name': sala['name'], 'address': address}}
        if act.get('precio'): base['offers'] = {'@type': 'Offer', 'price': act['precio']}
        if act.get('image'): base['image'] = act['image']
        days = {}
        for day, hour in act['sesiones']: days.setdefault(day, set()).add(hour)
        nodes = []
        for day, hours in sorted(days.items()):
            times = sorted(h for h in hours if h)
            nodes.append({**base, 'startDate': day + (('T' + times[0]) if times else ''), 'endDate': day, 'x_sessions': times})
        if act.get('periodo') and not nodes:
            a, b = act['periodo']; nodes.append({**base, 'startDate': a, 'endDate': b})
        for node in nodes:
            record = record_from_jsonld(venue, node, page_url)
            if not record: continue
            if not act.get('url'):  # sin ficha propia: la clave lleva el título (varios actos en la misma página y día)
                record['id'] = hashlib.sha256(('\0'.join((slug, page_url, fold(act['titulo']), record['start']))).encode()).hexdigest()[:24]
            record['raw']['loagendo']['source_label'] = LABEL
            record['raw']['ai_agenda'] = {'page': page_url, 'page_hash': page_hash, 'model': model, 'prompt_version': PROMPT_VERSION, 'quotes': act['quotes']}
            record['alerts'] = [a for a in record['alerts'] if a != 'VENUE_SCHEMA_ORG_EVENT'] + ['AI_EXTRACTED_VERIFIED']
            record['evidence_level'] = 'venue_page_ai_verified'; record['time_evidence_field'] = 'ia_cita'
            out.append(record)
    return out


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS ai_agenda_pages (slug TEXT NOT NULL, url TEXT NOT NULL, text_hash TEXT NOT NULL, checked_at TEXT NOT NULL,
      changed_at TEXT, events INTEGER, PRIMARY KEY(slug, url));
    CREATE TABLE IF NOT EXISTS ai_agenda_images (url TEXT PRIMARY KEY, image TEXT NOT NULL DEFAULT '', fetched_at TEXT NOT NULL);
    """)


def _image(conn, url, fetcher, timeout):
    row = conn.execute('SELECT image FROM ai_agenda_images WHERE url=?', (url,)).fetchone()
    if row: return row[0], False
    from src.venue_feeds import og_meta
    status, _, page = fetcher(url, timeout)
    image = og_meta(page).get('og:image', '') if status == 200 else ''
    with conn: conn.execute('INSERT OR REPLACE INTO ai_agenda_images(url,image,fetched_at) VALUES(?,?,?)', (url, image, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')))
    return image, True


def read_agenda(agenda, today, key, fetcher=None, requester=None, timeout=30, conn=None, force=False, usage=None):
    """Lee las páginas de una agenda: {'pages', 'accepted', 'rejected', 'unchanged'} (sin escribir fichas)."""
    from src.venue_feeds import fetch, robots_allows
    fetcher = fetcher or fetch
    result = {'pages': [], 'accepted': [], 'rejected': [], 'unchanged': True, 'text_chars': 0}
    fetched = []
    for url in expand_urls(agenda, today):
        if fetcher is fetch and not robots_allows(url): result['pages'].append({'url': url, 'error': 'robots.txt no lo permite'}); continue
        status, final_url, body = fetcher(url, timeout)
        if status != 200: result['pages'].append({'url': url, 'error': f'HTTP {status}'}); continue
        text, links = clean(body, final_url or url)
        text = text[:MAX_CHARS]; digest = hashlib.sha256(text.encode()).hexdigest()[:20]
        result['text_chars'] += len(text)
        page = {'url': url, 'hash': digest, 'chars': len(text)}
        if conn is not None and not force:
            row = conn.execute('SELECT text_hash FROM ai_agenda_pages WHERE slug=? AND url=?', (agenda['slug'], url)).fetchone()
            if not (row and row[0] == digest): result['unchanged'] = False
        else: result['unchanged'] = False
        fetched.append((page, text, links, final_url or url, body)); result['pages'].append(page)
    # Sin cambios en ninguna página: no se llama a la IA. Si cambia una, se leen todas (las fichas de la
    # agenda se recalculan juntas y lo que falte deja de publicarse).
    if result['unchanged']: return result
    for page, text, links, page_url, body in fetched:
        # Reglas antes que IA: si la página publica sus actos en schema.org, se toman de ahí (sin tokens).
        nodes = schema_nodes(body, agenda, today)
        if nodes:
            result.setdefault('rules_nodes', []).extend((n, page_url, page['hash']) for n in nodes)
            page['events'] = len(nodes); page['via'] = 'schema.org'
            continue
        page['via'] = 'IA'
        items = ask(agenda, text, page_url, today, key, requester=requester, usage=usage)
        result.setdefault('raw_items', 0); result['raw_items'] += len(items)
        for item in items:
            act, why = verify(item, text, links, today, agenda.get('salas'), bool(agenda.get('otros_lugares')), agenda['name'])
            if act: act['page'] = page_url; act['page_hash'] = page['hash']; act['why_partial'] = why; result['accepted'].append(act)
            else: result['rejected'].append({'item': item, 'why': why})
        page['events'] = len(items)
    # Un mismo acto en dos páginas (semanas de la Filmoteca): una sola entrada por título y enlace.
    merged = {}
    for act in result['accepted']:
        k = (fold(act['titulo']), (act.get('sala') or {}).get('name', ''))  # noqa
        if k not in merged: merged[k] = act; continue
        m = merged[k]
        m['sesiones'] = sorted(set(m['sesiones']) | set(act['sesiones']))
        for field in ('url', 'precio', 'periodo'):
            if not m.get(field) and act.get(field): m[field] = act[field]
        m['quotes'] = {**act['quotes'], **m['quotes']}
    result['accepted'] = list(merged.values())
    return result


def schema_nodes(body, agenda, today):
    """Actos schema.org (Event…) de la página, en Barcelona y de hoy en adelante; en agendas de varias salas,
    solo los de una sala configurada (el nombre del lugar del acto la contiene)."""
    from src.venue_feeds import jsonld_events, _date
    out = []
    for node in jsonld_events(body or ''):
        end = _date(node.get('endDate')) or _date(node.get('startDate'))
        if not end or end < today.isoformat(): continue
        loc = node.get('location') or {}
        if isinstance(loc, list): loc = loc[0] if loc else {}
        addr = loc.get('address') if isinstance(loc, dict) else None
        town = fold(addr.get('addressLocality') or '') if isinstance(addr, dict) else ''
        if town and 'barcelona' not in town: continue
        if agenda.get('salas'):
            where = fold(loc.get('name') or '') if isinstance(loc, dict) else ''
            if not any(fold(s['name']) in where or where in fold(s['name']) for s in agenda['salas'] if where): continue
        out.append(node)
    return out


def rules_records(agenda, nodes):
    """Fichas de los actos schema.org de la agenda (fuente venue_ia_<slug>, etiqueta «Datos de la sala»)."""
    from src.venue_feeds import record_from_jsonld
    venue = {'slug': 'ia_' + agenda['slug'], 'name': agenda['name'], 'type': agenda.get('type', 'culture'),
             'address': agenda.get('address') or ''}
    out = []
    for node, page_url, page_hash in nodes:
        record = record_from_jsonld(venue, node, page_url)
        if not record: continue
        record['raw'].setdefault('loagendo', {})['source_label'] = LABEL
        record['raw']['ai_agenda'] = {'page': page_url, 'page_hash': page_hash, 'model': 'reglas: schema.org', 'prompt_version': PROMPT_VERSION}
        record['evidence_level'] = 'venue_page_schema_org'
        out.append(record)
    return out


def sync_agenda(conn, agenda, key, today=None, fetcher=None, requester=None, timeout=30):
    """Lee una agenda y guarda sus fichas (fuente venue_ia_<slug>)."""
    from src.media import register
    from src.sync import _upsert_record, initialize as init_sync, now_utc
    from src.venue_feeds import fetch
    from src import ai_assist
    from mvp.catalog import initialize as init_catalog
    today = today or dt.date.today(); fetcher = fetcher or fetch
    init_sync(conn); init_catalog(conn); initialize(conn)
    source = 'venue_ia_' + agenda['slug']; usage = {}
    with conn:
        run_id = conn.execute('INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)', (source, now_utc(), 'running', '0')).lastrowid
    try:
        res = read_agenda(agenda, today, key, fetcher=fetcher, requester=requester, timeout=timeout, conn=conn, usage=usage)
        errors = [p['error'] for p in res['pages'] if p.get('error')]
        if errors and len(errors) == len(res['pages']): raise RuntimeError('; '.join(errors))
        if res['unchanged']:
            now = now_utc()
            with conn:
                for p in res['pages']:
                    if p.get('hash'): conn.execute('UPDATE ai_agenda_pages SET checked_at=? WHERE slug=? AND url=?', (now, agenda['slug'], p['url']))
                conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=0,rows_mutated=0,warning_json=? WHERE id=?",
                             (now, len(res['pages']), json.dumps(['página sin cambios: no se llama a la IA']), run_id))
            return {'source': source, 'status': 'completed', 'unchanged': True, 'rows_received': 0, 'rows_mutated': 0, 'usage': usage}
        images = 0
        for act in res['accepted']:
            url = act.get('url') or ''
            if url and urlsplit(url).netloc and images < IMAGE_BUDGET:
                try:
                    image, fetched = _image(conn, url, fetcher, timeout); images += fetched
                    if image: act['image'] = urljoin(url, image)
                except Exception: pass
        model = ai_assist.MODEL
        page_hash = ','.join(sorted({p.get('hash', '') for p in res['pages'] if p.get('hash')}))
        records = []
        for act in res['accepted']: records += records_for(agenda, [act], act['page'], act['page_hash'], model)
        records += rules_records(agenda, res.get('rules_nodes') or [])
        seen = set(); records = [r for r in records if not (r['id'] in seen or seen.add(r['id']))]
        mutated = 0; now = now_utc()
        with conn:
            for record in records:
                mutated += int(_upsert_record(conn, run_id, record)[0])
                image = record['raw'].get('image') or ''
                if image.startswith(('https://', 'http://')):
                    register(conn, source, record['id'], image, alt=record['title'], credit=record['venues'][0]['name'])
            # Lo que ya no está en la página (y aún no ha pasado) deja de publicarse; no se borra.
            if records and not errors:
                for (rid,) in conn.execute("SELECT id FROM source_records WHERE source=? AND end_date>=? AND eligibility<>'exclude'", (source, today.isoformat())).fetchall():
                    if rid not in seen: conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source=? AND id=?", (source, rid))
            for p in res['pages']:
                if p.get('hash'):
                    conn.execute('INSERT INTO ai_agenda_pages(slug,url,text_hash,checked_at,changed_at,events) VALUES(?,?,?,?,?,?) '
                                 'ON CONFLICT(slug,url) DO UPDATE SET text_hash=excluded.text_hash,checked_at=excluded.checked_at,changed_at=excluded.changed_at,events=excluded.events',
                                 (agenda['slug'], p['url'], p['hash'], now, now, p.get('events', 0)))
            warn = [f"{len(res['rejected'])} actos descartados por no pasar la comprobación"] if res['rejected'] else []
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now, len(res['pages']) + images, len(records), mutated, json.dumps(warn), run_id))
        return {'source': source, 'status': 'completed', 'rows_received': len(records), 'rows_mutated': mutated,
                'rejected': len(res['rejected']), 'images_fetched': images, 'usage': usage}
    except Exception as error:
        with conn: conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',warning_json=?,error=? WHERE id=?", (now_utc(), json.dumps([str(error)]), str(error)[:500], run_id))
        return {'source': source, 'status': 'failed', 'rows_received': 0, 'rows_mutated': 0, 'error': str(error), 'usage': usage}


def run(conn, job=None, requester=None, fetcher=None, today=None):
    """Trabajo «agendas-ia»: lee las agendas activas (las demás solo con la muestra)."""
    from src import ai_assist
    key = ai_assist.load_key()
    if not key: return {'status': 'skipped', 'reason': 'Falta ANTHROPIC_API_KEY en .env'}
    agendas = [a for a in load_agendas() if a.get('activa') and not a.get('descartada')]
    results = [sync_agenda(conn, a, key, today=today, fetcher=fetcher, requester=requester, timeout=(job or {}).get('timeout_seconds', 30)) for a in agendas]
    if any(r.get('rows_mutated') for r in results):
        from mvp import catalog; catalog.invalidate_cache()
    status = 'completed' if all(r['status'] == 'completed' for r in results) else 'failed'
    usage = {}
    for r in results:
        for k, v in (r.get('usage') or {}).items():
            if isinstance(v, int): usage[k] = usage.get(k, 0) + v
    return {'status': status, 'agendas': results, 'usage': usage}
