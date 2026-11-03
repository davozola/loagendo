"""La Selecció: la newsletter de los jueves (4-11-2026, diseño aprobado por David en el lienzo «Ontoca · La Selecció»).

Una edición por semana, hecha con la Selección que ya existe (src/ai_select.py, alcance «day»): viernes, sábado y domingo
para el fin de semana; lunes a miércoles para «Els dies següents». No se elige nada nuevo.

La IA solo escribe opinión (titular, introducción y el «per què» de cada plan) en catalán, castellano e inglés. Fechas,
horas, sala, precio y foto salen siempre de la ficha. Cada texto de la IA pasa una comprobación: cifras y nombres propios
tienen que estar en los datos de las fichas; si no, el texto se descarta y el plan sale solo con sus datos.

Ritmo (job «seleccio», cada 15 minutos):
- miércoles desde las 9:00: se prepara la edición del jueves y la prueba llega a hola@ontoca.com con el enlace a la
  página privada de revisión (functions/seleccio/revisar.js);
- hasta el jueves a las 8:45: se aplican los cambios de la revisión (quitar, protagonista, otro texto, texto propio) y,
  con la aprobación, se programan en Brevo las campañas de las 9:00 (una por idioma y lista);
- jueves 8:45 sin aprobación: no sale nada, aviso a hola@ y la edición queda guardada.
Todo cambio queda en el historial de la edición (quién, qué decía, qué dice). Tablas: seleccio_editions.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import struct
import unicodedata
import urllib.request
from html import escape as esc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config' / 'seleccio.json'
ARCHIVE = ROOT / 'data' / 'seleccio'
LANGS = ('ca', 'es', 'en')
PROMPT_VERSION = 1
MIN_ITEMS = 3          # con menos, no hay edición (lo dice la prueba del miércoles)
MAX_WEEKEND = 7        # protagonista y hasta seis más
MAX_NEXT = 4
LIMITS = {'head': 70, 'intro_words': 90, 'why_words': 50}
BREVO = 'https://api.brevo.com/v3'

try:
    from zoneinfo import ZoneInfo
    MADRID = ZoneInfo('Europe/Madrid')
except Exception:  # pragma: no cover
    MADRID = dt.timezone(dt.timedelta(hours=1))


# ---------- configuración y base de datos ----------

def config(path=None):
    base = {'enabled': False, 'test_to': 'hola@ontoca.com', 'site_url': 'https://ontoca.com', 'api_url': 'https://ontoca.com/api/seleccio',
            'lists': {'ca': None, 'es': None, 'en': None}, 'prepare_at': '09:00', 'deadline': '08:45', 'send_at': '09:00'}
    try: base.update(json.loads(Path(path or CONFIG).read_text(encoding='utf-8')))
    except (OSError, ValueError): pass
    return base


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS seleccio_editions (
        id TEXT PRIMARY KEY, number INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL,
        review_key TEXT NOT NULL, data_json TEXT NOT NULL, ai_json TEXT NOT NULL DEFAULT '[]', history_json TEXT NOT NULL DEFAULT '[]',
        actions_seq INTEGER NOT NULL DEFAULT 0, approved_at TEXT, campaigns_json TEXT, preview_sent_at TEXT, notified_at TEXT, sent_at TEXT)""")


def now_utc(): return dt.datetime.now(dt.timezone.utc)


def stamp(): return now_utc().isoformat(timespec='seconds')


def load(conn, eid):
    initialize(conn)
    row = conn.execute('SELECT id,number,status,review_key,data_json,ai_json,history_json,actions_seq,approved_at,campaigns_json,preview_sent_at,notified_at,sent_at FROM seleccio_editions WHERE id=?', (eid,)).fetchone()
    if not row: return None
    keys = ('id', 'number', 'status', 'review_key', 'data', 'ai', 'history', 'actions_seq', 'approved_at', 'campaigns', 'preview_sent_at', 'notified_at', 'sent_at')
    ed = dict(zip(keys, row))
    for k in ('data', 'ai', 'history', 'campaigns'): ed[k] = json.loads(ed[k]) if ed[k] else ([] if k in ('ai', 'history') else None)
    return ed


def save(conn, ed):
    with conn:
        conn.execute("""INSERT INTO seleccio_editions(id,number,created_at,updated_at,status,review_key,data_json,ai_json,history_json,actions_seq,approved_at,campaigns_json,preview_sent_at,notified_at,sent_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET number=excluded.number,updated_at=excluded.updated_at,status=excluded.status,
            data_json=excluded.data_json,ai_json=excluded.ai_json,history_json=excluded.history_json,actions_seq=excluded.actions_seq,approved_at=excluded.approved_at,
            campaigns_json=excluded.campaigns_json,preview_sent_at=excluded.preview_sent_at,notified_at=excluded.notified_at,sent_at=excluded.sent_at""",
            (ed['id'], ed.get('number'), ed.get('created_at') or stamp(), stamp(), ed['status'], ed['review_key'], json.dumps(ed['data'], ensure_ascii=False),
             json.dumps(ed.get('ai') or [], ensure_ascii=False), json.dumps(ed.get('history') or [], ensure_ascii=False), ed.get('actions_seq') or 0,
             ed.get('approved_at'), json.dumps(ed['campaigns']) if ed.get('campaigns') else None, ed.get('preview_sent_at'), ed.get('notified_at'), ed.get('sent_at')))


# ---------- datos de las fichas ----------

CAT_NAMES = {'musica': ('Música', 'Música', 'Music'), 'escena': ('Escena', 'Escena', 'Stage'), 'cine': ('Cinema', 'Cine', 'Film'),
             'arte': ('Art i exposicions', 'Arte y exposiciones', 'Art'), 'charlas': ('Xerrades i visites', 'Charlas y visitas', 'Talks'),
             'talleres': ('Tallers', 'Talleres', 'Workshops'), 'fiestas': ('Festes', 'Fiestas', 'Parties'), 'deporte': ('Esport', 'Deporte', 'Sport')}
CAT_COLORS = {'musica': '#000000', 'escena': '#FCA47C', 'cine': '#BBA6EA', 'arte': '#A1CCA6', 'charlas': '#23CED9', 'talleres': '#3D5BD9', 'fiestas': '#F9D779', 'deporte': '#097C87'}
WEEKDAYS = {'ca': ('dl', 'dt', 'dc', 'dj', 'dv', 'ds', 'dg'), 'es': ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom'), 'en': ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')}
WEEKDAYS_LONG = {'ca': ('dilluns', 'dimarts', 'dimecres', 'dijous', 'divendres', 'dissabte', 'diumenge'), 'es': ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'),
                 'en': ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')}
MONTHS = {'ca': ('de gener', 'de febrer', 'de març', 'd’abril', 'de maig', 'de juny', 'de juliol', 'd’agost', 'de setembre', 'd’octubre', 'de novembre', 'de desembre'),
          'es': ('de enero', 'de febrero', 'de marzo', 'de abril', 'de mayo', 'de junio', 'de julio', 'de agosto', 'de septiembre', 'de octubre', 'de noviembre', 'de diciembre'),
          'en': ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December')}
AND = {'ca': ' i ', 'es': ' y ', 'en': ' and '}
TO = {'ca': ' a ', 'es': ' a ', 'en': '–'}
FREE = {'ca': 'Gratis', 'es': 'Gratis', 'en': 'Free'}
BASE = {'ca': '', 'es': '/es', 'en': '/en'}


def public_source(source): return 'sala_' + source[9:] if source.startswith('venue_ia_') else source


def _day(d): return d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])


def sessions(card, days):
    """Día → horas de la ficha dentro de los días pedidos (de «o» o de «hb», como la web)."""
    want, out = {d.isoformat() for d in days}, {}
    for day, time in card.get('o') or []:
        if day in want: out.setdefault(day, set()).update([time] if time else [])
    if not out and card.get('hb') and card.get('a'):
        start = _day(card['a'])
        for times, offsets in card['hb'].items():
            for off in offsets:
                day = (start + dt.timedelta(days=int(off))).isoformat()
                if day in want: out.setdefault(day, set()).update(t for t in re.split(r'\s*·\s*', times) if t)
    if not out:   # programa sin horas: los días del periodo en que está abierto
        for d in days:
            if str(card.get('a') or '') <= d.isoformat() <= str(card.get('b') or card.get('a') or ''): out[d.isoformat()] = set()
    return {k: sorted(v) for k, v in sorted(out.items())}


def when_label(sess, lang):
    """«Dv 6 i ds 7 · 19:00 · dg 8 · 11:00». Los días seguidos con las mismas horas van juntos."""
    if not sess: return ''
    groups = []
    for day, times in sess.items():
        if groups and groups[-1][1] == times: groups[-1][0].append(day)
        else: groups.append(([day], times))
    parts = []
    for days, times in groups:
        ds = [dt.date.fromisoformat(d) for d in days]
        name = lambda d: f'{WEEKDAYS[lang][d.weekday()]} {d.day}'
        if len(ds) == 1: label = name(ds[0])
        elif len(ds) == 2: label = name(ds[0]) + AND[lang] + name(ds[1])
        else: label = name(ds[0]) + TO[lang] + name(ds[-1])
        times_label = AND[lang].join([', '.join(times[:-1]), times[-1]]) if len(times) > 1 else (times[0] if times else '')
        parts.append(label + (f' · {times_label}' if times_label else ''))
    out = ' · '.join(parts)
    return out[:1].upper() + out[1:]


def price_label(detail):
    if detail.get('is_free'): return None
    text = str(detail.get('price_label') or '').strip()
    if not text: return ''
    text = re.sub(r'\s*\(\+ despeses de gestió\)|\s*\(\+ gastos de gestión\)', '', text)
    first = text.split(' · ')[0].replace('Entrada general: ', '').replace('Entrada general de: ', '')
    return first if len(first) <= 40 else ''


def image_size(path):
    """Ancho y alto de un JPEG o PNG sin dependencias (para elegir protagonista con foto horizontal)."""
    try:
        with open(path, 'rb') as f: head = f.read(64 * 1024)
    except OSError: return None
    if head[:8] == b'\x89PNG\r\n\x1a\n': return struct.unpack('>II', head[16:24])
    if head[:2] == b'\xff\xd8':
        i = 2
        while i + 9 < len(head):
            if head[i] != 0xFF: i += 1; continue
            marker, size = head[i + 1], struct.unpack('>H', head[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack('>HH', head[i + 5:i + 9]); return w, h
            i += 2 + size
    return None


def _catalog(dist):
    dist = Path(dist)
    cards = {f"{c['s']}:{c['i']}": c for c in json.loads((dist / 'data' / 'catalog.json').read_text(encoding='utf-8'))['items']}
    return cards


def _detail(dist, key, cache):
    from src.publish_static import shard_of
    shard = shard_of(key)
    if shard not in cache:
        try: cache[shard] = json.loads((Path(dist) / 'data' / 'detail' / f'{shard}.json').read_text(encoding='utf-8'))
        except (OSError, ValueError): cache[shard] = {}
    return cache[shard].get(key) or {}


def facts_text(item):
    return ' '.join(str(x) for x in (item['title'], item.get('description', ''), item.get('venue', ''), item.get('district', ''),
                                     item.get('festival', ''), ' '.join(item.get('lineup') or []), item.get('motivo', '')) if x)


def make_item(key, card, detail, days, part, dist, motivo=''):
    s = sessions(card, days)
    if not s: return None
    cat = detail.get('public_category') or card.get('pc') or ''
    img = card.get('mi') or ''
    size = image_size(Path(dist) / img.lstrip('/')) if img else None
    venue = (detail.get('venue_names') or card.get('v') or [''])[0]
    return {'key': key, 'part': part, 'title': detail.get('title') or card['t'], 'category': cat, 'color': CAT_COLORS.get(cat, '#000000'),
            'venue': venue.split(' · ')[0].split(' - ')[0], 'district': card.get('d') or '', 'sessions': s,
            'when': {l: when_label(s, l) for l in LANGS}, 'free': bool(card.get('fr') or detail.get('is_free')), 'price': price_label({**detail, 'is_free': card.get('fr')}),
            'img': img, 'img_ok': bool(size and 1.3 <= size[0] / max(size[1], 1) <= 2.0 and size[0] >= 900), 'img_wide': bool(size and size[0] / max(size[1], 1) >= 1.2),
            'path': f"/e/{public_source(card['s'])}/{card['i']}", 'description': str(detail.get('description') or detail.get('summary') or '')[:1500],
            'festival': (detail.get('festival') or {}).get('name', '') if isinstance(detail.get('festival'), dict) else '',
            'lineup': [x.get('name', '') if isinstance(x, dict) else str(x) for x in (detail.get('lineup') or [])][:8], 'motivo': motivo,
            'why': {l: '' for l in LANGS}, 'why_src': {l: '' for l in LANGS}, 'removed': False}


def thursday_for(today):
    """El jueves de la edición: el siguiente (o hoy si es jueves)."""
    return today + dt.timedelta(days=(3 - today.weekday()) % 7)


def choose(conn, thursday, dist, rules_path=None):
    """Planes de la edición desde la Selección guardada, sin elegir nada nuevo."""
    from src.ai_select import picks_for
    from src.selection_rules import excluded
    cards, cache = _catalog(dist), {}
    weekend = [thursday + dt.timedelta(days=i) for i in (1, 2, 3)]
    following = [thursday + dt.timedelta(days=i) for i in (4, 5, 6)]
    motivos = {}
    for d in weekend + following:
        try:
            row = conn.execute("SELECT picks_json FROM ai_selection WHERE day=? AND scope='day'", (d.isoformat(),)).fetchone()
            for p in json.loads(row[0]) if row else []: motivos.setdefault(p['key'], p.get('motivo') or '')
        except Exception: pass
    items, seen = [], set()
    for part, days, cap in (('weekend', weekend, MAX_WEEKEND), ('next', following, MAX_NEXT)):
        # Por turnos entre los días (el primero de cada día, luego el segundo…): si no, el viernes y el sábado llenan la
        # edición y el domingo se queda fuera (4-11-2026, prueba con la Selección real).
        queues, got = [list(picks_for(conn, d.isoformat(), 'day')) for d in days], 0
        while got < cap and any(queues):
            for q in queues:
                if got >= cap: break
                while q:
                    key = q.pop(0)
                    if key in seen or key not in cards: continue
                    detail = _detail(dist, key, cache)
                    if excluded({**detail, 'source': cards[key]['s'], 'venue_names': detail.get('venue_names') or cards[key].get('v')}, rules_path): continue
                    item = make_item(key, cards[key], detail, days, part, dist, motivos.get(key, ''))
                    if item: items.append(item); seen.add(key); got += 1; break
    return items, len(cards)


# ---------- textos de la IA y su comprobación ----------

ALLOWED = {'barcelona', 'ontoca', 'seleccio', 'festival', 'divendres', 'dissabte', 'diumenge', 'dilluns', 'dimarts', 'dimecres', 'dijous',
           'viernes', 'sabado', 'domingo', 'lunes', 'martes', 'miercoles', 'jueves', 'friday', 'saturday', 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday'}
STOP = re.compile(r'[A-Za-zÀ-ÿ’\'·.-]+')


def fold(s): return unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode().lower()


def unknown_terms(text, facts):
    """Cifras y nombres propios del texto que no están en los datos. Vacío = texto aceptado."""
    f, bad = fold(facts), []
    digits = set(re.findall(r'\d+', f))
    bad += [n for n in re.findall(r'\d+', text) if n not in digits]
    for sentence in re.split(r'(?<=[.!?:])\s+|\n+', text):
        words = sentence.split()
        for i, w in enumerate(words):
            core = w.strip('«»"“”(),;:.!?¡¿—–-')
            if i == 0 or len(core) < 3 or not core[:1].isupper(): continue
            token = fold(core).strip("’'")
            if token in ALLOWED or not token: continue
            if token not in f: bad.append(core)
    return bad


def check_text(kind, text, facts):
    text = str(text or '').strip()
    if not text: return 'vacío'
    if kind == 'head' and len(text) > LIMITS['head']: return 'titular demasiado largo'
    if kind == 'intro' and len(text.split()) > LIMITS['intro_words']: return 'introducción demasiado larga'
    if kind == 'why' and len(text.split()) > LIMITS['why_words']: return 'texto demasiado largo'
    bad = unknown_terms(text, facts)
    return ('no está en las fichas: ' + ', '.join(dict.fromkeys(bad))[:200]) if bad else ''


SYSTEM = """Eres el editor de «La Selecció», la newsletter de los jueves de Ontoca, agenda cultural de Barcelona. Escribes como una pequeña publicación cultural: con criterio, curiosidad e independencia; nunca como un catálogo ni como publicidad.
Recibes los planes ya elegidos (JSON con n, título, categoría, sala, barrio, descripción de la sala y motivo de la selección). Respondes con la herramienta redactar, en catalán, castellano e inglés:
- titular: de 4 a 9 palabras, como máximo 60 caracteres, que conecte dos o tres planes del fin de semana;
- intro: de 50 a 80 palabras sobre el fin de semana, nombrando planes concretos;
- protagonista: el n del plan del fin de semana más singular entre los que tienen foto (foto=true);
- planes: para cada n, por qué vale la pena en 15 a 40 palabras, sin repetir la descripción.
Reglas: usa solo lo que dicen los datos de cada plan; no inventes nada (ni personas, ni obras, ni premios, ni historia). No escribas fechas, horas, días ni precios: salen aparte. Nombres propios solo si están en los datos. Sin superlativos vacíos ni signos de exclamación."""

TOOL = {'name': 'redactar', 'description': 'Titular, introducción, protagonista y texto de cada plan, en los tres idiomas.',
        'input_schema': {'type': 'object', 'required': ['titular', 'intro', 'protagonista', 'planes'], 'properties': {
            'titular': {'type': 'object', 'required': list(LANGS), 'properties': {l: {'type': 'string'} for l in LANGS}},
            'intro': {'type': 'object', 'required': list(LANGS), 'properties': {l: {'type': 'string'} for l in LANGS}},
            'protagonista': {'type': 'integer'},
            'planes': {'type': 'array', 'items': {'type': 'object', 'required': ['n', *LANGS], 'properties': {'n': {'type': 'integer'}, **{l: {'type': 'string'} for l in LANGS}}}}}}}

TRANSLATE = {'name': 'traducir', 'description': 'El texto en los idiomas pedidos, fiel al original.',
             'input_schema': {'type': 'object', 'required': ['textos'], 'properties': {'textos': {'type': 'object', 'properties': {l: {'type': 'string'} for l in LANGS}}}}}


def _payload(items):
    return [{'n': n, 'titulo': it['title'], 'categoria': it['category'], 'sala': it['venue'], 'barrio': it['district'], 'parte': it['part'],
             'foto': it['img_ok'], 'festival': it.get('festival') or '', 'descripcion': it.get('description', '')[:1200], 'motivo': it.get('motivo') or ''} for n, it in enumerate(items)]


def _call(body, label, requester=None):
    from src import ai_assist
    key = ai_assist.load_key()
    with ai_assist.usage_label('seleccio', label):
        return (requester or ai_assist._request)('POST', f'{ai_assist.API}/messages', key, body, timeout=180)


def _tool_input(message, name):
    for block in message.get('content') or []:
        if block.get('type') == 'tool_use' and block.get('name') == name: return block.get('input') or {}
    return {}


def write_texts(ed, requester=None, model=None, only=None, avoid=None):
    """Pide los textos a la IA y aplica los que pasan la comprobación. only: 'intro' o una clave para pedir otra versión."""
    from src import ai_assist
    d, items = ed['data'], [it for it in ed['data']['items'] if not it['removed']]
    if only and only != 'intro': items = [it for it in items if it['key'] == only]
    ask = SYSTEM + ('' if not avoid else '\n\nEscribe una versión distinta de esta, con otro enfoque: ' + json.dumps(avoid, ensure_ascii=False))
    body = {'model': model or ai_assist.MODEL, 'max_tokens': 4000, 'system': ask, 'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'redactar'},
            'messages': [{'role': 'user', 'content': json.dumps(_payload(items), ensure_ascii=False)}]}
    message = _call(body, f"{ed['id']} {only or 'todo'}", requester)
    out, log = _tool_input(message, 'redactar'), {'at': stamp(), 'model': body['model'], 'prompt_version': PROMPT_VERSION, 'only': only, 'usage': message.get('usage') or {}, 'rejected': []}
    all_facts = ' '.join(facts_text(it) for it in d['items'] if not it['removed'])
    if only in (None, 'intro'):
        for part in ('head', 'intro'):
            for l in LANGS:
                text = str((out.get('titular' if part == 'head' else 'intro') or {}).get(l) or '').strip()
                why = check_text(part, text, all_facts)
                if why: log['rejected'].append({'what': part, 'lang': l, 'text': text, 'why': why})
                else: d[part][l], d[part + '_src'][l] = text, 'ia'
    if only is None:
        n = out.get('protagonista')
        if isinstance(n, int) and 0 <= n < len(items) and items[n]['img_ok'] and items[n]['part'] == 'weekend': d['hero'] = items[n]['key']
    for p in out.get('planes') or []:
        n = p.get('n')
        if not isinstance(n, int) or not 0 <= n < len(items) or (only == 'intro'): continue
        it = items[n]
        for l in LANGS:
            text = str(p.get(l) or '').strip()
            why = check_text('why', text, facts_text(it))
            if why: log['rejected'].append({'what': it['key'], 'lang': l, 'text': text, 'why': why})
            else: it['why'][l], it['why_src'][l] = text, 'ia'
    ed.setdefault('ai', []).append(log)
    return log


def translate_edit(ed, target_key, lang, text, facts, requester=None, model=None):
    """El texto que escribe David, traducido a los otros dos idiomas (comprobado contra su texto y la ficha)."""
    from src import ai_assist
    others = [l for l in LANGS if l != lang]
    body = {'model': model or ai_assist.MODEL, 'max_tokens': 1500, 'tools': [TRANSLATE], 'tool_choice': {'type': 'tool', 'name': 'traducir'},
            'system': 'Traduces textos breves de una newsletter cultural de Barcelona. Fiel al original, mismo tono, sin añadir nada. Los nombres propios no se traducen.',
            'messages': [{'role': 'user', 'content': json.dumps({'idioma_original': lang, 'texto': text, 'traducir_a': others}, ensure_ascii=False)}]}
    message = _call(body, f"{ed['id']} traduccion {target_key}", requester)
    got, done = (_tool_input(message, 'traducir').get('textos') or {}), {}
    for l in others:
        t = str(got.get(l) or '').strip()
        if t and not unknown_terms(t, text + ' ' + facts): done[l] = t
    ed.setdefault('ai', []).append({'at': stamp(), 'model': body['model'], 'translation_of': target_key, 'from': lang, 'usage': message.get('usage') or {}, 'accepted': list(done)})
    return done


# ---------- la edición ----------

def build(conn, thursday, dist, *, requester=None, model=None, rules_path=None, number=None):
    initialize(conn)
    items, total = choose(conn, thursday, dist, rules_path)
    weekend = [it for it in items if it['part'] == 'weekend']
    data = {'thursday': thursday.isoformat(), 'weekend': [(thursday + dt.timedelta(days=i)).isoformat() for i in (1, 2, 3)],
            'items': items, 'hero': next((it['key'] for it in weekend if it['img_ok']), None), 'catalog_total': total,
            'head': {l: '' for l in LANGS}, 'head_src': {l: '' for l in LANGS}, 'intro': {l: '' for l in LANGS}, 'intro_src': {l: '' for l in LANGS}}
    if number is None:
        number = (conn.execute("SELECT COUNT(*) FROM seleccio_editions WHERE status='sent'").fetchone()[0] or 0) + 1
    ed = {'id': thursday.isoformat(), 'number': number, 'status': 'draft' if len(weekend) >= MIN_ITEMS else 'empty',
          'review_key': secrets.token_urlsafe(24), 'data': data, 'ai': [], 'history': [], 'actions_seq': 0}
    if ed['status'] == 'draft': write_texts(ed, requester, model)
    save(conn, ed)
    return ed


def ordered(data):
    weekend = [it for it in data['items'] if it['part'] == 'weekend' and not it['removed']]
    hero = next((it for it in weekend if it['key'] == data.get('hero')), None)
    rest = [it for it in weekend if it is not hero]
    first = lambda it: min((d + ' ' + (t[0] if t else '99')) for d, t in it['sessions'].items()) if it['sessions'] else '9999'
    following = sorted((it for it in data['items'] if it['part'] == 'next' and not it['removed']), key=first)   # por fecha y hora
    return hero, rest, following


# ---------- correo ----------

UI = {
    'ca': {'num': 'La Selecció · núm. {n}', 'band': 'Cap de setmana del {a} al {b}', 'also': 'També aquest cap de setmana', 'next': 'Els dies següents',
           'cta_item': 'Veure la fitxa i les entrades →', 'all': 'Tota l’agenda, cada dia', 'all_sub': 'Més de {n} plans a Barcelona. Filtra per dia, hora, barri i preu.',
           'open': 'Obre l’agenda', 'browser': 'Veure-la al navegador', 'why_get': 'Reps aquest correu perquè et vas subscriure a La Selecció a ontoca.com. Un sol correu, cada dijous a les 9 h. Mesurem les obertures i els clics per millorar la Selecció.',
           'lang': 'Canviar d’idioma', 'unsub': 'Donar-me de baixa', 'privacy': 'Privacitat', 'legal': 'Avís legal', 'subject': 'La Selecció · {head}', 'fallback_head': 'Els plans del cap de setmana', 'free': 'Gratis'},
    'es': {'num': 'La Selecció · núm. {n}', 'band': 'Fin de semana del {a} al {b}', 'also': 'También este fin de semana', 'next': 'Los días siguientes',
           'cta_item': 'Ver la ficha y las entradas →', 'all': 'Toda la agenda, cada día', 'all_sub': 'Más de {n} planes en Barcelona. Filtra por día, hora, barrio y precio.',
           'open': 'Abre la agenda', 'browser': 'Verla en el navegador', 'why_get': 'Recibes este correo porque te suscribiste a La Selecció en ontoca.com. Un solo correo, cada jueves a las 9 h. Medimos las aperturas y los clics para mejorar la Selecció.',
           'lang': 'Cambiar de idioma', 'unsub': 'Darme de baja', 'privacy': 'Privacidad', 'legal': 'Aviso legal', 'subject': 'La Selecció · {head}', 'fallback_head': 'Los planes del fin de semana', 'free': 'Gratis'},
    'en': {'num': 'La Selecció · no. {n}', 'band': 'Weekend of {a} to {b}', 'also': 'Also this weekend', 'next': 'The days after',
           'cta_item': 'See the listing and tickets →', 'all': 'The whole agenda, every day', 'all_sub': 'Over {n} plans in Barcelona. Filter by day, time, neighbourhood and price.',
           'open': 'Open the agenda', 'browser': 'View in browser', 'why_get': 'You get this email because you subscribed to La Selecció at ontoca.com. One email, every Thursday at 9 am. We measure opens and clicks to improve La Selecció.',
           'lang': 'Change language', 'unsub': 'Unsubscribe', 'privacy': 'Privacy', 'legal': 'Legal notice', 'subject': 'La Selecció · {head}', 'fallback_head': 'This weekend’s plans', 'free': 'Free'},
}
LEGAL_PATHS = {'privacy': {'ca': '/privacitat', 'es': '/es/privacidad', 'en': '/en/privacy'}, 'legal': {'ca': '/avis-legal', 'es': '/es/aviso-legal', 'en': '/en/legal-notice'}}
FONT = "'Inter Tight', Helvetica, Arial, sans-serif"


def long_date(d, lang):
    d = _day(d)
    if lang == 'en': return f'{WEEKDAYS_LONG[lang][d.weekday()]}, {d.day} {MONTHS[lang][d.month - 1]} {d.year}'
    return f'{WEEKDAYS_LONG[lang][d.weekday()].capitalize()}, {d.day} {MONTHS[lang][d.month - 1]} de {d.year}'


def short_date(d, lang):
    d = _day(d)
    return f'{d.day} {MONTHS[lang][d.month - 1]}' if lang == 'en' else f'{d.day} {MONTHS[lang][d.month - 1]}'


def _link(site, lang, path, key=''):
    sep = '&' if '?' in path else '?'
    return f"{site}{BASE[lang]}{path}{sep}mtm_campaign=seleccio&mtm_source=newsletter&mtm_medium=email" + (f'&mtm_content={key}' if key else '')


def render(ed, lang, mode='email', site=None):
    """HTML de la edición. mode: 'email' (Brevo, con sus marcas de baja), 'preview' (prueba a hola@) o 'web' (archivo)."""
    site = (site or config()['site_url']).rstrip('/')
    d, u = ed['data'], UI[lang]
    hero, rest, following = ordered(d)
    head = d['head'].get(lang) or u['fallback_head']
    intro = d['intro'].get(lang) or ''
    a, b = _day(d['weekend'][0]), _day(d['weekend'][-1])
    band = u['band'].format(a=a.day, b=short_date(b, lang)) if lang != 'en' else u['band'].format(a=f'{a.day}', b=short_date(b, lang))
    pad = 'padding-left:40px;padding-right:40px'
    line = 'border-top:1px solid #000000'
    img = lambda it: f"{site}{it['img']}"
    def cat(it):
        names = CAT_NAMES.get(it['category'])
        name = names[LANGS.index(lang)] if names else ''
        fest = it.get('festival') or ''
        label = ' · '.join(x for x in (name, fest) if x)
        return (f'<div style="font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#000000">'
                f'<span style="display:inline-block;width:10px;height:10px;border:1px solid #000000;background:{it["color"]};vertical-align:-1px;margin-right:8px"></span>{esc(label)}</div>') if label else ''
    def facts(it):
        price = u['free'] if it['free'] else (it['price'] or '')
        bits = [x for x in (it['venue'], price) if x]
        return f'<strong style="color:#000000">{esc(it["when"][lang])}</strong>' + ''.join(f' · {esc(x)}' for x in bits)
    out = []
    pre = esc(intro[:140]) if intro else esc(head)
    out.append(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
               f'<meta name="color-scheme" content="light"><title>{esc(head)}</title>'
               '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;700&display=swap">'
               '<style>a{color:#000000}@media (max-width:620px){.wrap{width:100%!important}.px{padding-left:20px!important;padding-right:20px!important}'
               '.h1{font-size:34px!important;line-height:37px!important}.h2{font-size:28px!important;line-height:31px!important}'
               '.stack,.stack tbody,.stack tr,.stack td{display:block!important;width:100%!important}.thumb{padding:0 0 16px 0!important}.thumb img{width:100%!important;height:auto!important}}</style>'
               f'</head><body style="margin:0;padding:0;background:#F4F4F1">')
    out.append(f'<div style="display:none;max-height:0;overflow:hidden">{pre}</div>')
    if mode == 'preview':
        out.append(f'<!--PREVIEW_BANNER-->')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F4F4F1"><tr><td align="center" style="padding:24px 0">'
               f'<table role="presentation" class="wrap" width="600" cellpadding="0" cellspacing="0" style="width:600px;background:#FFFFFF;border:1px solid #000000;font-family:{FONT};color:#000000">')
    browser = _link(site, lang, f"/seleccio/{d['thursday']}/")
    out.append(f'<tr><td class="px" style="{pad};padding-top:26px;padding-bottom:18px"><table role="presentation" width="100%"><tr>'
               f'<td style="font-size:26px;font-weight:700;letter-spacing:-.04em">ontoca<span style="color:#097C87">.</span></td>'
               f'<td align="right" style="font-size:13px">' + ('' if mode == 'web' else f'<a href="{browser}" style="color:#444444">{u["browser"]}</a>') + '</td></tr></table></td></tr>')
    out.append(f'<tr><td class="px" style="{line};border-bottom:1px solid #000000;background:#23CED9;{pad};padding-top:20px;padding-bottom:20px">'
               f'<div style="font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase">{esc(u["num"].format(n=ed.get("number") or 1))}</div>'
               f'<div style="margin-top:6px;font-size:16px;font-weight:500">{esc(long_date(d["thursday"], lang))}</div></td></tr>')
    out.append(f'<tr><td class="px" style="background:#F9D779;border-bottom:1px solid #000000;{pad};padding-top:12px;padding-bottom:12px;font-size:16px;font-weight:700">{esc(band)}</td></tr>')
    out.append(f'<tr><td class="px" style="{pad};padding-top:34px;padding-bottom:34px"><h1 class="h1" style="margin:0;font-size:44px;line-height:46px;font-weight:700;letter-spacing:-.035em">{esc(head)}</h1>'
               + (f'<p style="margin:20px 0 0;font-size:18px;line-height:28px">{esc(intro)}</p>' if intro else '') + '</td></tr>')
    if hero:
        url = _link(site, lang, hero['path'], hero['key'])
        out.append(f'<tr><td style="{line}"><a href="{url}"><img src="{img(hero)}" width="600" alt="{esc(hero["title"])}" style="display:block;width:100%;max-width:600px;height:auto;border:0"></a></td></tr>' if hero['img'] else '')
        out.append(f'<tr><td class="px" style="{pad};padding-top:24px;padding-bottom:34px;border-bottom:1px solid #000000">{cat(hero)}'
                   f'<h2 class="h2" style="margin:12px 0 0;font-size:32px;line-height:35px;font-weight:700;letter-spacing:-.03em"><a href="{url}" style="color:#000000;text-decoration:none">{esc(hero["title"])}</a></h2>'
                   + (f'<p style="margin:16px 0 0;font-size:17px;line-height:26px">{esc(hero["why"][lang])}</p>' if hero['why'][lang] else '')
                   + f'<p style="margin:16px 0 0;padding-top:14px;border-top:1px solid #D6D6D6;font-size:15px;line-height:24px;color:#444444">{facts(hero)}</p>'
                   f'<p style="margin:16px 0 0"><a href="{url}" style="font-size:16px;font-weight:700;color:#000000">{u["cta_item"]}</a></p></td></tr>')
    if rest:
        out.append(f'<tr><td class="px" style="{pad};padding-top:30px;padding-bottom:4px;font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase">{u["also"] if hero else u["band"].split(" del ")[0]}</td></tr>')
        for i, it in enumerate(rest):
            url = _link(site, lang, it['path'], it['key'])
            border = 'border-bottom:1px solid #D6D6D6;' if i < len(rest) - 1 else ''
            thumb = (f'<td class="thumb" width="180" valign="top" style="padding:0 24px 0 0;width:180px"><a href="{url}"><img src="{img(it)}" width="180" alt="{esc(it["title"])}" style="display:block;width:180px;height:auto;border:1px solid #000000"></a></td>') if it['img'] else ''
            out.append(f'<tr><td class="px" style="{pad};padding-top:20px;padding-bottom:24px;{border}"><table role="presentation" class="stack" width="100%" cellpadding="0" cellspacing="0"><tr>{thumb}'
                       f'<td valign="top">{cat(it)}<h3 style="margin:8px 0 0;font-size:21px;line-height:25px;font-weight:700;letter-spacing:-.02em"><a href="{url}" style="color:#000000;text-decoration:none">{esc(it["title"])}</a></h3>'
                       + (f'<p style="margin:8px 0 0;font-size:16px;line-height:24px">{esc(it["why"][lang])}</p>' if it['why'][lang] else '')
                       + f'<p style="margin:10px 0 0;font-size:14px;line-height:22px;color:#444444">{facts(it)}</p></td></tr></table></td></tr>')
    if following:
        rows = ''.join(f'<div style="margin-top:16px;padding-top:16px;{"border-top:1px solid #CFCFCF;" if i else ""}"><div style="font-size:14px;font-weight:700">{esc(it["when"][lang])}</div>'
                       f'<div style="margin-top:4px;font-size:18px;line-height:23px;font-weight:700"><a href="{_link(site, lang, it["path"], it["key"])}" style="color:#000000;text-decoration:none">{esc(it["title"])}</a></div>'
                       f'<div style="margin-top:4px;font-size:15px;line-height:22px;color:#444444">' + ' · '.join(esc(x) for x in ((it["why"][lang] or ''), it['venue'], u['free'] if it['free'] else (it['price'] or '')) if x) + '</div></div>'
                       for i, it in enumerate(following))
        out.append(f'<tr><td class="px" style="{line};background:#F4F4F1;{pad};padding-top:28px;padding-bottom:28px"><div style="font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase">{u["next"]}</div>{rows}</td></tr>')
    total = max(1000, (int(d.get('catalog_total') or 0) // 1000) * 1000)
    out.append(f'<tr><td class="px" align="center" style="{line};{pad};padding-top:34px;padding-bottom:34px"><div style="font-size:22px;font-weight:700;letter-spacing:-.02em">{u["all"]}</div>'
               f'<p style="margin:8px 0 0;font-size:16px;line-height:24px;color:#444444">{u["all_sub"].format(n=f"{total:,}".replace(",", "." if lang != "en" else ","))}</p>'
               f'<a href="{_link(site, lang, "/")}" style="display:inline-block;margin-top:20px;padding:14px 28px;background:#000000;color:#FFFFFF;font-size:16px;font-weight:700;text-decoration:none">{u["open"]}</a></td></tr>')
    unsub = '{{ unsubscribe }}' if mode == 'email' else '#'
    change = f'{site}/seleccio/idioma?e={{{{ contact.EMAIL }}}}&t={{{{ contact.SELECCIO_T }}}}' if mode == 'email' else '#'
    footer = (f'<p style="margin:0">{u["why_get"]}</p><p style="margin:12px 0 0">' if mode != 'web' else '<p style="margin:0">') + \
             (f'<a href="{change}" style="color:#444444">{u["lang"]}</a> · <a href="{unsub}" style="color:#444444">{u["unsub"]}</a> · ' if mode != 'web' else '') + \
             f'<a href="{site}{LEGAL_PATHS["privacy"][lang]}" style="color:#444444">{u["privacy"]}</a> · <a href="{site}{LEGAL_PATHS["legal"][lang]}" style="color:#444444">{u["legal"]}</a></p>' \
             '<p style="margin:12px 0 0">Ontoca · Barcelona · hola@ontoca.com</p>'
    out.append(f'<tr><td class="px" style="{line};{pad};padding-top:24px;padding-bottom:30px;font-size:13px;line-height:21px;color:#444444">{footer}</td></tr>')
    out.append('</table></td></tr></table></body></html>')
    return ''.join(out)


def subject(ed, lang):
    head = ed['data']['head'].get(lang) or UI[lang]['fallback_head']
    return UI[lang]['subject'].format(head=head)


def text_version(ed, lang):
    hero, rest, following = ordered(ed['data'])
    lines = [subject(ed, lang), '', ed['data']['intro'].get(lang) or '', '']
    for it in ([hero] if hero else []) + rest + following:
        lines += [it['title'], it['when'][lang] + ' · ' + it['venue'], it['why'][lang], config()['site_url'] + BASE[lang] + it['path'], '']
    return '\n'.join(x for x in lines if x is not None)


# ---------- Cloudflare (página de revisión) y Brevo ----------

def env(name):
    from src.mailer import env_value
    return env_value(name)


def _http(method, url, body=None, headers=None, opener=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'content-type': 'application/json', 'accept': 'application/json', **(headers or {})})
    if opener: return opener(req, timeout)
    from src.network import tls_context
    with urllib.request.urlopen(req, timeout=timeout, context=tls_context()) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def deadline(ed, cfg):
    h, m = (int(x) for x in cfg['deadline'].split(':'))
    return dt.datetime.combine(_day(ed['id']), dt.time(h, m), MADRID)


def send_time(ed, cfg):
    h, m = (int(x) for x in cfg['send_at'].split(':'))
    return dt.datetime.combine(_day(ed['id']), dt.time(h, m), MADRID)


def public_summary(ed, cfg):
    """Lo que ve la página de revisión: textos por idioma, datos y estado. Nada de configuración ni claves."""
    d = ed['data']
    items = [{k: it[k] for k in ('key', 'part', 'title', 'venue', 'when', 'why', 'why_src', 'removed', 'img', 'img_ok')} for it in d['items']]
    return {'id': ed['id'], 'number': ed.get('number'), 'status': ed['status'], 'hero': d.get('hero'), 'head': d['head'], 'intro': d['intro'], 'intro_src': d['intro_src'],
            'items': items, 'deadline': deadline(ed, cfg).isoformat(), 'send_at': send_time(ed, cfg).isoformat(), 'changes': len(ed.get('history') or []), 'site': cfg['site_url']}


def push(ed, cfg, opener=None):
    token = env('SELECCIO_TOKEN')
    if not token: return {'status': 'skipped', 'reason': 'Falta SELECCIO_TOKEN en .env'}
    body = {'id': ed['id'], 'key': ed['review_key'], 'deadline': deadline(ed, cfg).isoformat(), 'approved': ed['status'] in ('approved', 'scheduled'),
            'seq': ed.get('actions_seq') or 0, 'summary': public_summary(ed, cfg), 'preview': {l: render(ed, l, 'web', cfg['site_url']) for l in LANGS}}
    try: return {'status': 'ok', **(_http('POST', cfg['api_url'] + '/edicion', body, {'authorization': 'Bearer ' + token}, opener) or {})}
    except Exception as error: return {'status': 'failed', 'error': str(error)[:300]}


def pull(ed, cfg, opener=None):
    token = env('SELECCIO_TOKEN')
    if not token: return []
    try: got = _http('GET', f"{cfg['api_url']}/acciones?id={ed['id']}&after={ed.get('actions_seq') or 0}", None, {'authorization': 'Bearer ' + token}, opener)
    except Exception: return None
    return got.get('actions') or []


def _find(d, key): return next((it for it in d['items'] if it['key'] == key), None)


def apply_actions(ed, actions, requester=None):
    """Aplica los cambios de la revisión en orden. Cada uno queda en el historial con lo que había antes."""
    d, changed = ed['data'], False
    for a in sorted(actions, key=lambda x: x['seq']):
        kind, key, lang = a.get('type'), a.get('item') or '', a.get('lang') or 'ca'
        entry = {'at': a.get('at') or stamp(), 'who': 'David', 'action': kind, 'item': key, 'lang': lang}
        it = _find(d, key) if key and key != 'intro' else None
        if kind in ('remove', 'restore') and it:
            entry['before'], it['removed'] = it['removed'], kind == 'remove'; entry['after'] = it['removed']
            if it['removed'] and d.get('hero') == key: d['hero'] = next((x['key'] for x in d['items'] if x['part'] == 'weekend' and not x['removed'] and x['img_ok']), None)
        elif kind == 'hero' and it and it['img']:
            entry['before'], d['hero'] = d.get('hero'), key; entry['after'] = key
        elif kind == 'regenerate' and (it or key == 'intro'):
            before = d['intro'] if key == 'intro' else it['why']
            entry['before'] = dict(before); write_texts(ed, requester, only=key or 'intro', avoid=before.get(lang))
            entry['after'] = dict(d['intro'] if key == 'intro' else it['why']); entry['who'] = 'IA (a petición de David)'
        elif kind == 'edit' and (it or key == 'intro'):
            text = str(a.get('text') or '').strip()[:1200]
            target, src = (d['intro'], d['intro_src']) if key == 'intro' else (it['why'], it['why_src'])
            entry['before'] = dict(target)
            target[lang], src[lang] = text, 'david'
            facts = ' '.join(facts_text(x) for x in d['items']) if key == 'intro' else facts_text(it)
            for l, t in translate_edit(ed, key, lang, text, facts, requester).items(): target[l], src[l] = t, 'traducido'
            entry['after'] = dict(target)
        elif kind == 'approve':
            entry['before'], ed['status'], ed['approved_at'] = ed['status'], 'approved', a.get('at') or stamp()
        elif kind == 'unapprove':
            entry['before'], ed['status'], ed['approved_at'] = ed['status'], 'draft', None
        else:
            continue
        ed.setdefault('history', []).append(entry); changed = True
        ed['actions_seq'] = max(ed.get('actions_seq') or 0, a['seq'])
    return changed


def brevo(method, path, body=None, opener=None):
    key = env('BREVO_API_KEY')
    if not key: raise RuntimeError('Falta BREVO_API_KEY en .env')
    return _http(method, BREVO + path, body, {'api-key': key}, opener)


def schedule(ed, cfg, opener=None):
    """Una campaña por idioma, a su lista, a las 9:00. Sin lista configurada, ese idioma no se envía (queda dicho)."""
    when, made, missing = send_time(ed, cfg), {}, []
    for l in LANGS:
        lid = (cfg.get('lists') or {}).get(l)
        if not lid: missing.append(l); continue
        got = brevo('POST', '/emailCampaigns', {'name': f"La Selecció {ed['id']} ({l})", 'subject': subject(ed, l), 'previewText': (ed['data']['intro'].get(l) or '')[:140],
                                               'sender': {'name': 'Ontoca', 'email': 'hola@ontoca.com'}, 'replyTo': 'hola@ontoca.com', 'htmlContent': render(ed, l, 'email', cfg['site_url']),
                                               'recipients': {'listIds': [int(lid)]}, 'scheduledAt': when.isoformat(), 'inlineImageActivation': False}, opener)
        made[l] = got.get('id')
    return made, missing


def unschedule(ed, opener=None):
    for l, cid in (ed.get('campaigns') or {}).get('ids', {}).items():
        try: brevo('DELETE', f'/emailCampaigns/{cid}', None, opener)
        except Exception: pass
    ed['campaigns'] = None


def preview_mail(ed, cfg):
    url = f"{cfg['site_url']}/seleccio/revisar?id={ed['id']}&k={ed['review_key']}"
    dl = deadline(ed, cfg)
    weekend = len([it for it in ed['data']['items'] if it['part'] == 'weekend' and not it['removed']])
    following = len([it for it in ed['data']['items'] if it['part'] == 'next' and not it['removed']])
    rejected = sum(len(x.get('rejected') or []) for x in ed.get('ai') or [])
    banner = (f'<table role="presentation" width="100%" style="background:#FFFFFF;border-bottom:2px solid #000000;font-family:{FONT}"><tr><td align="center" style="padding:20px">'
              f'<table role="presentation" width="600" class="wrap" style="width:600px"><tr><td style="font-size:13px;font-weight:700;letter-spacing:.1em;text-transform:uppercase">Prueba · no se ha enviado a nadie</td></tr>'
              f'<tr><td style="padding-top:8px;font-size:16px;line-height:24px">Así la recibirán el jueves a las {cfg["send_at"]}: {weekend} planes del fin de semana y {following} de los días siguientes. '
              f'Textos de la IA comprobados con las fichas' + (f' ({rejected} descartados por no cuadrar con los datos)' if rejected else '') + '.</td></tr>'
              f'<tr><td style="padding-top:16px"><a href="{url}" style="display:block;padding:15px 20px;background:#000000;color:#FFFFFF;text-align:center;font-size:17px;font-weight:700;text-decoration:none">Revisar y aprobar</a></td></tr>'
              f'<tr><td style="padding-top:10px;font-size:14px;color:#444444">Si no la apruebas antes del jueves a las {dl.strftime("%H:%M")}, no se envía.</td></tr></table></td></tr></table>')
    return render(ed, 'ca', 'preview', cfg['site_url']).replace('<!--PREVIEW_BANNER-->', banner)


def notify(subject_line, html, text, cfg):
    from src import mailer
    return mailer.send(subject_line, html, text, to=cfg['test_to'])


def archive(ed, cfg, root=ARCHIVE):
    folder = Path(root) / ed['id']
    folder.mkdir(parents=True, exist_ok=True)
    for l in LANGS: (folder / f'{l}.html').write_text(render(ed, l, 'web', cfg['site_url']), encoding='utf-8')
    (Path(root) / 'latest.json').write_text(json.dumps({'id': ed['id'], 'number': ed.get('number')}), encoding='utf-8')


# ---------- el ritmo de la semana ----------

def run(conn, job=None, *, now=None, dist=None, requester=None, opener=None, cfg=None):
    cfg = cfg or config()
    if not cfg.get('enabled'): return {'status': 'skipped', 'reason': 'La Selecció está apagada (config/seleccio.json: enabled)'}
    initialize(conn)
    now = (now or now_utc()).astimezone(MADRID)
    dist = Path(dist or ROOT / 'dist')
    thursday = thursday_for(now.date())
    out = {'status': 'completed', 'edition': thursday.isoformat()}
    ed = load(conn, thursday.isoformat())
    ph, pm = (int(x) for x in cfg['prepare_at'].split(':'))
    prepare_from = dt.datetime.combine(thursday - dt.timedelta(days=1), dt.time(ph, pm), MADRID)
    if ed is None:
        if now < prepare_from: return {**out, 'step': 'esperando al miércoles'}
        if now >= deadline({'id': thursday.isoformat()}, cfg): return {**out, 'step': 'fuera de plazo: no se prepara'}
        ed = build(conn, thursday, dist, requester=requester)
        out['built'] = len(ed['data']['items'])
        if ed['status'] == 'empty':
            notify(f"La Selecció {ed['id']}: esta semana no hay edición", f"<p>Solo hay {len([i for i in ed['data']['items'] if i['part'] == 'weekend'])} planes del fin de semana en la Selección (mínimo {MIN_ITEMS}). No se envía nada.</p>", 'No hay edición esta semana.', cfg)
            ed['notified_at'] = stamp(); save(conn, ed)
            return {**out, 'step': 'sin edición (pocos planes)'}
        out['push'] = push(ed, cfg, opener)['status']
        sent = notify(f"[Prueba] La Selecció núm. {ed['number']} · aprueba antes del jueves a las {cfg['deadline']}", preview_mail(ed, cfg), text_version(ed, 'ca'), cfg)
        if sent.get('status') == 'sent': ed['preview_sent_at'] = stamp()
        save(conn, ed)
        return {**out, 'step': 'prueba enviada', 'preview': sent.get('status')}
    if ed['status'] in ('sent', 'not_sent', 'empty'): return {**out, 'step': ed['status']}
    if now < deadline(ed, cfg):
        actions = pull(ed, cfg, opener)
        if actions:
            was = ed['status']
            touched = [a for a in actions if a.get('type') not in ('approve', 'unapprove')]
            apply_actions(ed, actions, requester)
            if ed.get('campaigns') and (touched or ed['status'] != 'approved'):
                unschedule(ed, opener)
                if ed['status'] == 'scheduled': ed['status'] = 'approved'
            save(conn, ed); out['applied'] = len(actions); out['push'] = push(ed, cfg, opener)['status']
        if ed['status'] == 'approved' and not ed.get('campaigns'):
            try:
                ids, missing = schedule(ed, cfg, opener)
                ed['campaigns'] = {'ids': ids, 'missing': missing, 'at': stamp()}
                ed['status'] = 'scheduled' if ids else 'approved'
                save(conn, ed); out['scheduled'] = ids; out['missing_lists'] = missing
            except Exception as error:
                out['schedule_error'] = str(error)[:300]
        return {**out, 'step': ed['status']}
    # Pasado el plazo
    if ed['status'] == 'scheduled':
        if now >= send_time(ed, cfg):
            ed['status'], ed['sent_at'] = 'sent', stamp(); save(conn, ed); archive(ed, cfg)
            return {**out, 'step': 'enviada', 'campaigns': ed['campaigns']}
        return {**out, 'step': 'programada'}
    if not ed.get('notified_at'):
        reason = 'No la aprobaste antes de las ' + cfg['deadline'] if ed['status'] != 'approved' else 'Estaba aprobada pero no se pudo programar en Brevo (revisa las listas de config/seleccio.json)'
        notify(f"La Selecció núm. {ed['number']} no sale esta semana", f'<p style="font-family:Helvetica,Arial,sans-serif;font-size:17px;line-height:1.5"><strong>Esta semana no se envía.</strong> {esc(reason)}, así que a las {cfg["send_at"]} no saldrá nada. '
               f'La edición queda guardada con todos sus textos y cambios. El miércoles que viene a las {cfg["prepare_at"]} te llegará la prueba de la siguiente.</p>', reason, cfg)
        ed['notified_at'] = stamp()
    ed['status'] = 'not_sent'; save(conn, ed)
    return {**out, 'step': 'no enviada'}


# ---------- páginas web (archivo y confirmación) ----------

CONFIRMED = {
    'ca': ('Subscripció confirmada', 'Fet. Ens veiem dijous.', 'La primera Selecció t’arribarà el proper dijous a les 9 h. Un sol correu a la setmana; te’n pots donar de baixa des de qualsevol edició.', 'Perquè no se’n vagi a promocions, afegeix hola@ontoca.com als teus contactes.', 'Llegir l’última edició', 'Tornar a l’agenda'),
    'es': ('Suscripción confirmada', 'Hecho. Nos vemos el jueves.', 'La primera Selecció te llegará el próximo jueves a las 9 h. Un solo correo a la semana; puedes darte de baja desde cualquier edición.', 'Para que no vaya a promociones, añade hola@ontoca.com a tus contactos.', 'Leer la última edición', 'Volver a la agenda'),
    'en': ('Subscription confirmed', 'Done. See you on Thursday.', 'Your first Selecció arrives next Thursday at 9 am. One email a week; unsubscribe from any edition.', 'To keep it out of promotions, add hola@ontoca.com to your contacts.', 'Read the latest edition', 'Back to the agenda'),
}

SOON = {'ca': ('La primera edició surt aviat.', 'Cada dijous a les 9 h, els plans de Barcelona que valen la pena: una selecció per al cap de setmana i els dies següents.'),
        'es': ('La primera edición sale pronto.', 'Cada jueves a las 9 h, los planes de Barcelona que valen la pena: una selección para el fin de semana y los días siguientes.'),
        'en': ('The first edition is on its way.', 'Every Thursday at 9 am, the Barcelona plans worth your time: a selection for the weekend and the days after.')}


def _page(lang, title, body, css=''):
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)} · Ontoca</title>'
            f'<meta name="robots" content="noindex">' + (f'<link rel="stylesheet" href="{css}">' if css else '') +
            f'<style>body{{margin:0;font-family:{FONT};color:#000;background:#fff}}.w{{max-width:640px;margin:0 auto;padding:0 16px}}header{{height:56px;border-bottom:1px solid #000;display:flex;align-items:center}}'
            '.logo{font-size:24px;font-weight:700;letter-spacing:-.04em;text-decoration:none;color:#000}.logo span{color:#097C87}.band{background:#F9D779;border-bottom:1px solid #000;padding:12px 16px;font-weight:700}'
            '.k{font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase}h1{font-size:34px;line-height:1.08;letter-spacing:-.035em;margin:8px 0 0}p{font-size:17px;line-height:1.55}'
            '.b{display:flex;align-items:center;justify-content:center;min-height:52px;border:1px solid #000;font-weight:700;text-decoration:none;color:#000;margin-top:12px}.b.d{background:#000;color:#fff}</style></head>'
            f'<body><header><div class="w"><a class="logo" href="{BASE[lang] or "/"}">ontoca<span>.</span></a></div></header>{body}</body></html>')


def write_pages(out, root=ARCHIVE):
    """dist/seleccio/…: confirmación de alta, archivo de ediciones y la última («Veure un exemple»), en los tres idiomas."""
    out, root = Path(out), Path(root)
    latest = None
    try: latest = json.loads((root / 'latest.json').read_text(encoding='utf-8'))['id']
    except (OSError, ValueError, KeyError): pass
    written = 0
    for l in LANGS:
        base = out / BASE[l].lstrip('/') / 'seleccio' if BASE[l] else out / 'seleccio'
        t = CONFIRMED[l]
        body = (f'<div class="band">{t[0]}</div><main class="w" style="padding-top:32px;padding-bottom:40px"><div class="k">La Selecció</div><h1>{t[1]}</h1><p>{t[2]}</p><p style="color:#444;font-size:15px">{t[3]}</p>'
                f'<a class="b d" href="{BASE[l]}/seleccio/">{t[4]}</a><a class="b" href="{BASE[l] or "/"}">{t[5]}</a></main>')
        (base / 'confirmada').mkdir(parents=True, exist_ok=True)
        (base / 'confirmada' / 'index.html').write_text(_page(l, t[0], body), encoding='utf-8'); written += 1
        for folder in sorted(p for p in root.glob('????-??-??') if p.is_dir()):
            src = folder / f'{l}.html'
            if not src.exists(): continue
            (base / folder.name).mkdir(parents=True, exist_ok=True)
            (base / folder.name / 'index.html').write_text(src.read_text(encoding='utf-8'), encoding='utf-8'); written += 1
        if latest and (root / latest / f'{l}.html').exists():
            (base / 'index.html').write_text((root / latest / f'{l}.html').read_text(encoding='utf-8'), encoding='utf-8'); written += 1
        else:   # antes de la primera edición, «Veure un exemple» explica qué llegará
            (base / 'index.html').write_text(_page(l, 'La Selecció', f'<div class="band">La Selecció</div><main class="w" style="padding-top:32px;padding-bottom:40px"><h1>{SOON[l][0]}</h1><p>{SOON[l][1]}</p><a class="b" href="{BASE[l] or "/"}">{CONFIRMED[l][5]}</a></main>'), encoding='utf-8'); written += 1
    return written
