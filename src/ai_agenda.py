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
EMPTY_PAGE_MIN_ACTIVE = 3    # con menos actos vigentes, una página vacía puede ser simplemente que no hay programación
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
CANCELLED_RX = re.compile(r"\b(?:ajornat|ajornada|aplazad[oa]|cancel[.·]?lat|cancel[.·]?lada|cancelad[oa]|anul[.·]?lat|anul[.·]?lada|anulad[oa]|suspes|suspesa|suspendid[oa]|postponed|cancelled|canceled)\b")
MEMBERS_RX = re.compile(r"exclusiu per a soci|nomes per a soci|exclusivo para soci|solo para soci|members only")
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
- En una noticia, la fecha de publicación no es la del acto: usa solo la fecha en que el acto ocurre, tal como la escribe el texto.
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
AUTO_PATH = ROOT / 'data' / 'agendas_auto.json'


def load_agendas(path=CONFIG_PATH, auto_path=AUTO_PATH):
    """Agendas configuradas y, detrás, las que el buscador de programas de festival pone solas (data/agendas_auto.json);
    si una está en las dos, manda la configurada."""
    try: out = json.loads(Path(path).read_text(encoding='utf-8')).get('agendas', [])
    except (OSError, ValueError): out = []
    if auto_path and path == CONFIG_PATH:
        have = {a.get('slug') for a in out}
        try: out += [a for a in json.loads(Path(auto_path).read_text(encoding='utf-8')).get('agendas', []) if a.get('slug') not in have]
        except (OSError, ValueError): pass
    return out


_BY_SOURCE = {}


def agenda_for_source(source):
    """Agenda de config/agendas_ia.json de una fuente venue_ia_<slug> (o {})."""
    if not _BY_SOURCE: _BY_SOURCE.update({'venue_ia_' + a['slug']: a for a in load_agendas() if a.get('slug')})
    return _BY_SOURCE.get(source, {})


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
        if not self.skip and data.strip():
            # Dos números de elementos distintos no se pegan (28-10-2026, Documenta: «02/11/2026» y «19:00 h» en dos
            # <span> daban «02/11/202619:00 h» y la hora no se podía leer). Solo entre cifra y cifra: una palabra
            # partida en dos etiquetas («<b>B</b>arcelona») sigue entera.
            prev = next((p for p in reversed(self.parts) if p), '')
            if prev and prev[-1:].isdigit() and data.lstrip()[:1].isdigit(): self.parts.append(' ')
            self.parts.append(data)


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


def verify(item, text, links, today, salas=None, other_places=False, own_name='', whole_page=False):
    """(acto comprobado o None, motivos de descarte).

    ``whole_page`` (28-10-2026, In-Edit): la página es la ficha de un solo acto (enlazada desde la agenda con
    «seguir»: {«ficha»: true}); su título encabeza la página y las sesiones van después de la sinopsis, así que la
    cercanía al título no se exige. Las citas siguen teniendo que estar literalmente en la página."""
    hay = fold(text); why = []
    _near_ = (lambda *a: True) if whole_page else _near
    title = ' '.join(str(item.get('titulo') or '').split())
    tpos = _positions(title, hay)
    if not title or not tpos: return None, ['título que no está en la página']
    # Actos que la propia página da por anulados o aplazados («[Acte ajornat]», «(ANULADO)»), o que no son para el
    # público («Exclusiu per a socis», justo después del título): no se publican (27-10-2026).
    if CANCELLED_RX.search(fold(title)): return None, ['acto anulado o aplazado según la página']
    if any(MEMBERS_RX.search(hay[p:p + len(title) + 300]) for p in tpos): return None, ['acto solo para socios']
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
        if not _near_(tpos, _positions(place, hay), 1500, 1500): return None, [f"lugar que no está junto al acto: {place!r}"]
        out['sala'] = {'name': place, 'address': ''}
    for s in item.get('sesiones') or []:
        qd = str(s.get('cita_fecha') or ''); dpos = _positions(qd, hay)
        if not dpos: why.append(f"cita de fecha que no está en la página: {qd!r}"); continue
        # La fecha va delante (cabecera de día, hasta NEAR_DATE_BEFORE) o justo detrás del título.
        if not _near_(tpos, dpos, NEAR_DATE_BEFORE, NEAR_DATE_AFTER):
            why.append(f"fecha lejos del título: {qd!r}"); continue
        d = _date_from_quote(s.get('fecha'), qd, today)
        if not d: why.append(f"fecha que no cuadra con su cita: {s.get('fecha')} / {qd!r}"); continue
        hour = ''
        h, qh = str(s.get('hora') or '').strip(), str(s.get('cita_hora') or '')
        # Hora escrita justo detrás de la fecha (28-10-2026, Zumzeig «Ds 7.11.26 (19:00)», Documenta «02/11/2026 19:00 h»):
        # si la IA no da hora, se toma con reglas de la aparición de la fecha más cercana al título. Una sola hora,
        # pegada a esa fecha (como mucho 3 caracteres en medio); la cita es la fecha con su hora, tal cual en la página.
        def _glued():
            near = [p for p in dpos if any(-NEAR_DATE_BEFORE <= p - t <= NEAR_DATE_AFTER for t in tpos)] or ([] if not whole_page else dpos)
            # Primero la aparición que va detrás del título (listados «Título · fecha (hora)»); si no, la de delante.
            for p in sorted(near, key=lambda p: (not any(0 <= p - t <= NEAR_DATE_AFTER for t in tpos), min(abs(p - t) for t in tpos))):
                tail = hay[p + len(fold(qd)):p + len(fold(qd)) + 20]
                m = re.match(r"[\s(,·-]{0,3}([01]?\d|2[0-3])[:.]([0-5]\d)\s*h?\)?(?![\d:.]|\s*(?:-|–|a)\s*\d)", tail)
                if m: return f"{int(m.group(1)):02d}:{m.group(2)}", (qd + tail[:m.end()]).strip()
            return '', ''
        if not h or not re.fullmatch(r"\d{1,2}:\d{2}", h):
            gh, gq = _glued()
            if gh: h, qh = gh, gq
        if h:
            hpos = _positions(qh, hay)
            if re.fullmatch(r"\d{1,2}:\d{2}", h) and hpos and _near_(tpos, hpos, NEAR_TIME, NEAR_TIME) and f"{int(h[:-3]):02d}:{h[-2:]}" in times_in(qh):
                hour = f"{int(h[:-3]):02d}:{h[-2:]}"; out['quotes'].setdefault('time', qh)
            else: why.append(f"hora sin cita válida: {h} / {qh!r}")   # una hora de la IA que no cuadra no se sustituye: queda sin hora
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
        if ppos and a and b and a <= b and (_near_(tpos, ppos, 1500, 1500)):
            out['periodo'] = (a.isoformat(), b.isoformat()); out['quotes'].setdefault('date', qp)
        else: why.append(f"periodo sin cita válida: {p!r}")
    if not out['sesiones'] and not out.get('periodo'): return None, why or ['sin fecha comprobada']
    price, qpr = str(item.get('precio') or '').strip(), str(item.get('cita_precio') or '')
    if price:
        ppos = _positions(qpr, hay); digits = re.findall(r"\d+(?:[.,]\d+)?", price)
        ok = ppos and _near_(tpos, ppos, NEAR_PRICE, NEAR_PRICE) and (all(x in qpr for x in digits) if digits else FREE_RX.search(fold(qpr)))
        if ok: out['precio'] = price; out['quotes']['price'] = qpr
        else: why.append(f"precio sin cita válida: {price!r}")
    m = re.fullmatch(r"\[?L(\d+)\]?", str(item.get('enlace') or '').strip())
    if m and 1 <= int(m.group(1)) <= len(links):
        url = links[int(m.group(1)) - 1]
        if f"[l{m.group(1)}]" in hay: out['url'] = url
    # El enlace tiene que ser de ESTE acto (28-10-2026, Zumzeig: cada bloque entero es un enlace y su marca queda detrás,
    # así que la IA tomaba la del acto anterior: «Krakatoa» → /films/animals-bestials/). Si su ruta no comparte palabras
    # con el título y otro enlace de la página sí, se usa ese; si no hay ninguno, la página de la agenda.
    from src.official_dates import same_act
    if out.get('url') and urlsplit(out['url']).path.strip('/') and not same_act(title, urlsplit(out['url']).path):
        own = [l for l in links if urlsplit(l).netloc == urlsplit(out['url']).netloc and urlsplit(l).path.strip('/') and same_act(title, urlsplit(l).path)]
        if len(set(own)) == 1: why.append(f"enlace de otro acto ({out['url']}); vale {own[0]}"); out['url'] = own[0]
        else: why.append(f"enlace de otro acto descartado: {out['url']}"); out.pop('url')
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
EXHIBITION_SEGMENTS = {'exposicions', 'exposicio', 'exposiciones', 'exposicion', 'exhibitions', 'exhibition', 'expos', 'expo'}


def venue_category(agenda, page_url='', act_url=''):
    """Categoría de la fuente para una ficha de la agenda (24-10-2026). Un museo o centro cultural
    (type «culture») programa de todo: talleres familiares, conciertos, visitas, charlas… Su tipo ya no
    hace que todo sea «Arte y exposiciones»: solo lo que está en su sección de exposiciones (un tramo de
    la ruta que es exactamente «exposicions», «exposiciones», «exhibitions»…; «exposicions-i-activitats»
    no cuenta). Manda la página del acto; la del listado, solo si el acto no tiene página propia.
    Lo demás se clasifica por título y texto, o lo decide la IA de pendientes.
    Las salas de música, teatro o cine siguen dando su categoría (None = la del tipo de sala)."""
    if agenda.get('type', 'culture') != 'culture': return None
    url = act_url if urlsplit(act_url or '').netloc else page_url
    segments = {seg.lower() for seg in urlsplit(url or '').path.split('/') if seg}
    return 'Arte y exposiciones' if segments & EXHIBITION_SEGMENTS else ''


def records_for(agenda, accepted, page_url, page_hash, model):
    """Fichas (forma de src.sync) de los actos comprobados: una por día con sus pases; un periodo, una ficha."""
    from src.venue_feeds import record_from_jsonld
    slug = 'ia_' + agenda['slug']
    out = []
    for act in accepted:
        sala = act.get('sala') or {'name': agenda['name'], 'address': agenda.get('address') or ''}
        venue = {'slug': slug, 'name': sala['name'], 'type': agenda.get('type', 'culture')}
        cat = venue_category(agenda, page_url, act.get('url') or '')
        if cat is not None: venue['category'] = cat
        address = {'@type': 'PostalAddress', 'streetAddress': sala.get('address') or '', 'addressLocality': 'Barcelona'}
        base = {'@type': 'Event', 'name': act['titulo'], 'url': act.get('url') or page_url,
                'location': {'@type': 'Place', 'name': sala['name'], 'address': address}}
        if act.get('precio'): base['offers'] = {'@type': 'Offer', 'price': act['precio']}
        if act.get('image'): base['image'] = act['image']
        days = {}
        for day, hour in act['sesiones']: days.setdefault(day, set()).add(hour)
        nodes = []
        # Festival leído como agenda (28-10-2026, In-Edit): cada sesión es un acto del festival (x_festival, src/festivals.py).
        if agenda.get('festival'): base['x_festival'] = agenda['festival']
        for day, hours in sorted(days.items()):
            times = sorted(h for h in hours if h)
            # x_time_verified: la hora sale de una cita comprobada en la página (una sesión de club a las 00:00 vale).
            nodes.append({**base, 'startDate': day + (('T' + times[0]) if times else ''), 'endDate': day, 'x_sessions': times, 'x_time_verified': bool(times)})
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
    # «seguir»: noticias o fichas enlazadas desde la página (el Zoo anuncia su Festa del Cor como noticia):
    # se leen también las primeras «max» cuyo enlace cumple «patron».
    follow = agenda.get('seguir') or {}
    queue, seen = list(expand_urls(agenda, today)), set()
    while queue:
        url = queue.pop(0)
        if url in seen: continue
        seen.add(url)
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
        if follow.get('patron') and url in expand_urls(agenda, today):
            extra = [l for l in dict.fromkeys(links) if re.search(follow['patron'], l) and l not in seen][:int(follow.get('max', 8))]
            queue.extend(extra)
    # Sin cambios en ninguna página: no se llama a la IA. Si cambia una, se leen todas (las fichas de la
    # agenda se recalculan juntas y lo que falte deja de publicarse).
    if result['unchanged']: return result
    listing = set(expand_urls(agenda, today))
    for page, text, links, page_url, body in fetched:
        whole = bool(follow.get('ficha')) and page['url'] not in listing
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
            act, why = verify(item, text, links, today, agenda.get('salas'), bool(agenda.get('otros_lugares')), agenda['name'], whole_page=whole)
            if act: act['page'] = page_url; act['page_hash'] = page['hash']; act['why_partial'] = why; result['accepted'].append(act)
            else: result['rejected'].append({'item': item, 'why': why, 'page': page_url})
        page['events'] = len(items)
    # Página propia de los actos que el listado da sin hora (28-10-2026, programas de festival): «seguir_actos»: N lee como
    # mucho N de esas páginas (mismo sitio, enlace del propio acto) y las comprueba como ficha de un acto (whole_page).
    budget = int(agenda.get('seguir_actos') or 0)
    if budget:
        hosts = {urlsplit(p['url']).netloc for p in result['pages'] if p.get('url')}
        for act in list(result['accepted']):
            if budget <= 0: break
            u = act.get('url') or ''
            if not u or any(h for _, h in act['sesiones']) or urlsplit(u).netloc not in hosts or u in seen: continue
            seen.add(u); budget -= 1
            if fetcher is fetch and not robots_allows(u): continue
            status, final_url, body = fetcher(u, timeout)
            if status != 200: continue
            text, links = clean(body, final_url or u); text = text[:MAX_CHARS]
            for item in ask(agenda, text, final_url or u, today, key, requester=requester, usage=usage):
                if fold(item.get('titulo') or '') != fold(act['titulo']) and fold(act['titulo']) not in fold(item.get('titulo') or ''): continue
                got, why = verify(item, text, links, today, agenda.get('salas'), bool(agenda.get('otros_lugares')), agenda['name'], whole_page=True)
                if got and any(h for _, h in got['sesiones']):
                    got['titulo'] = act['titulo']; got['page'] = final_url or u; got['page_hash'] = hashlib.sha256(text.encode()).hexdigest()[:20]; got['why_partial'] = why
                    got.setdefault('url', u); result['accepted'].append(got)
                    # La ficha del acto manda sobre la línea sin hora del listado: esa no se publica aparte (sin duplicados).
                    if act in result['accepted']: result['accepted'].remove(act)
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
        cat = venue_category(agenda, page_url, str(node.get('url') or ''))
        record = record_from_jsonld({**venue, **({'category': cat} if cat is not None else {})}, node, page_url)
        if not record: continue
        record['raw'].setdefault('loagendo', {})['source_label'] = LABEL
        record['raw']['ai_agenda'] = {'page': page_url, 'page_hash': page_hash, 'model': 'reglas: schema.org', 'prompt_version': PROMPT_VERSION}
        record['evidence_level'] = 'venue_page_schema_org'
        out.append(record)
    return out


def sync_agenda(conn, agenda, key, today=None, fetcher=None, requester=None, timeout=30, force=False):
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
        res = read_agenda(agenda, today, key, fetcher=fetcher, requester=requester, timeout=timeout, conn=conn, usage=usage, force=force)
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
        # Página cambiada que ya no trae ningún acto cuando la sala tenía programación (Filmoteca en mantenimiento,
        # 25-10-2026: «temporalment fora de servei»): es un fallo de la fuente, no un vacío de programación. Se marca
        # como fallida (la vigilancia avisa a la tercera) y no se deja de publicar nada.
        if not res['accepted'] and not res.get('rules_nodes'):
            active = conn.execute("SELECT COUNT(*) FROM source_records WHERE source=? AND end_date>=? AND eligibility<>'exclude'", (source, today.isoformat())).fetchone()[0]
            if active >= EMPTY_PAGE_MIN_ACTIVE:
                raise RuntimeError('la página ha cambiado y no trae ningún acto (tenía %d vigentes): web caída, rediseñada o sin programación publicada' % active)
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
            # Motivos de cada descarte (28-10-2026): para revisar una agenda nueva sin volver a gastar IA.
            warn += [f"descartado · {str((r.get('item') or {}).get('titulo') or '')[:80]} · {'; '.join(r.get('why') or [])[:240]} · {r.get('page', '')}" for r in res['rejected'][:200]]
            warn += [f"parcial · {a['titulo'][:80]} · {'; '.join(a.get('why_partial') or [])[:240]} · {a.get('page', '')}" for a in res['accepted'] if a.get('why_partial')][:200]
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now, len(res['pages']) + images, len(records), mutated, json.dumps(warn), run_id))
        return {'source': source, 'status': 'completed', 'via': sorted({p.get('via') for p in res['pages'] if p.get('via')}), 'rows_received': len(records), 'rows_mutated': mutated,
                'rejected': len(res['rejected']), 'images_fetched': images, 'usage': usage}
    except Exception as error:
        with conn: conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',warning_json=?,error=? WHERE id=?", (now_utc(), json.dumps([str(error)]), str(error)[:500], run_id))
        return {'source': source, 'status': 'failed', 'rows_received': 0, 'rows_mutated': 0, 'error': str(error), 'usage': usage}


def run(conn, job=None, requester=None, fetcher=None, today=None):
    """Trabajo «agendas-ia»: lee las agendas activas (las demás solo con la muestra)."""
    from src import ai_assist
    key = ai_assist.load_key()
    if not key: return {'status': 'skipped', 'reason': 'Falta ANTHROPIC_API_KEY en .env'}
    # «hasta» (28-10-2026): un festival leído como agenda (In-Edit) deja de leerse cuando acaba; lo publicado se queda.
    # «pausa_hasta» (28-10-2026, Tradicionàrius fuera de servicio): no se lee ni avisa hasta esa fecha; después, sola.
    day = (today or dt.date.today()).isoformat()
    agendas = [a for a in load_agendas() if a.get('activa') and not a.get('descartada') and not (a.get('hasta') and day > a['hasta']) and not (a.get('pausa_hasta') and day <= a['pausa_hasta'])]
    results = [sync_agenda(conn, a, key, today=today, fetcher=fetcher, requester=requester, timeout=(job or {}).get('timeout_seconds', 30)) for a in agendas]
    if any(r.get('rows_mutated') for r in results):
        from mvp import catalog; catalog.invalidate_cache()
    # Una agenda caída no tumba el trabajo: «partial» si fallan algunas, «failed» solo si fallan todas (26-10-2026).
    ok = sum(r['status'] == 'completed' for r in results)
    status = 'completed' if ok == len(results) else 'partial' if ok else 'failed'
    usage = {}
    for r in results:
        for k, v in (r.get('usage') or {}).items():
            if isinstance(v, int): usage[k] = usage.get(k, 0) + v
    return {'status': status, 'agendas': results, 'usage': usage}
