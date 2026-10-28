"""Static export of the public agenda, ready for a CDN such as Cloudflare Pages.

The live site is a set of files: the public front end, one compact catalogue
of every public record inside the horizon, one small file per day with the
first page already ranked, detail records sharded by key, and the images the
source policy authorises, each with its credit. Nothing here invents content:
every value comes from ``mvp.catalog`` (the same code the local server uses)
and every image keeps its source, original URL and licence basis.

``export`` writes the site; ``deploy`` runs the configured upload command;
``publish`` chains both behind a readiness gate so an empty or broken
catalogue is never pushed over a working site.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import os
import shutil
import subprocess
from urllib.parse import quote
import time
from pathlib import Path

from mvp import catalog

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / 'docs' / 'source_registry.json'
HORIZON_DAYS = catalog.MAX_RANGE_DAYS
PAGE_SIZE = 50
FEATURED_SIZE = 12
PICK_POOL = 100          # candidatos de la Selección por día (antes 30): de ellos salen también las selecciones por tipo
PICK_POOL_WEEK = 400     # en 7 días los 100 primeros eran casi todo música, charlas y teatro (medido el 28-10-2026): sin cine ni arte
PICKS_PER_CATEGORY = 8   # por tipo, con margen para lo que ya haya pasado; la web enseña hasta 6 y el tipo solo con 3 o más
HIGHLIGHT_SIZE = 40  # «Selección Ontoca» en la lista de cada día (además de la de portada)
DETAIL_SHARDS = 256
MAX_IMAGES_PER_EVENT = 3
MAX_ASSET_BYTES = 25 * 1024 * 1024  # Cloudflare Pages limit per file
MAX_FILES = 20000                   # Cloudflare Pages limit per deployment
THUMBNAIL_MAX_PX = 1200
GATE_MIN_EVENTS_14_DAYS = 300
STATIC_FILES = ('public.css', 'public.js', 'public-v2.css', 'analytics.js', 'legal.js',
                'fonts/inter-tight-latin-400-normal.woff2', 'fonts/inter-tight-latin-500-normal.woff2', 'fonts/inter-tight-latin-600-normal.woff2',
                'fonts/inter-tight-latin-700-normal.woff2', 'fonts/inter-tight-latin-500-italic.woff2', 'fonts/OFL-inter-tight.txt', 'vendor/leaflet.css', 'vendor/leaflet.js', 'img/hero-light.webp', 'img/hero-light-m.webp', 'img/hero-dark.webp', 'img/hero-dark-m.webp',
                'favicon.svg', 'favicon-32.png', 'apple-touch-icon.png')  # icono «o.» de la pestaña (22-10-2026)
PUBLIC_DETAIL_FIELDS = ('source', 'id', 'key', 'title', 'source_label', 'start', 'end', 'kind', 'kind_label', 'format', 'format_label', 'category', 'district',
                        'family_audience', 'has_description', 'summary', 'venue_names', 'coordinates', 'occurrences', 'has_candidate', 'date_precision',
                        'media', 'also_in', 'price_label', 'is_free', 'time', 'time_source', 'time_label', 'public_category', 'url', 'description',
                        'editorial_summary', 'time_text', 'schedule_days', 'schedule_note', 'registration_required', 'price_text', 'venues', 'organizers', 'links', 'link_label', 'confirmations', 'presentation', 'time_conflicts', 'hours_by_day', 'notes_by_day', 'lineup', 'lineup_times', 'channels', 'age_min', 'age_max', 'age_evidence', 'age_source', 'price_source', 'ai_quotes', 'ai_summary', 'family_ai', 'official_dates', 'official_page', 'open_enrollment', 'drop_in', 'program', 'manual_hours', 'data_origin', 'festival', 'venue_unconfirmed', 'venue_upcoming', 'description_credit',
                        'milestone', 'milestone_link', 'opening', 'other_days', 'sold_out', 'description_scope')
IMAGE_EXTENSIONS = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/gif': '.gif', 'image/avif': '.avif'}


def _registry(path=REGISTRY_PATH):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError): return {}


def registry_entry(registry, source):
    """The registry entry that governs ``source`` (wildcards for venue_* and ticketing)."""
    if source in registry: return registry[source]
    if source.startswith('venue_'):
        from src.media import _wildcard_entry
        return _wildcard_entry(registry, source) or {}
    return {}


def public_events(conn, today):
    """Every public record that touches the horizon, as independent copies."""
    start = today.isoformat(); end = (today + dt.timedelta(days=HORIZON_DAYS)).isoformat()
    events = [e for e in catalog.all_events(conn) if catalog.is_public(e) and e['end'] >= start and e['start'] <= end]
    repeated = songkick_repeats(events)
    return [json.loads(json.dumps(e)) for e in events if e['key'] not in repeated]


def songkick_repeats(events, min_venues=3):
    """Fichas de Songkick sin hora cuyo título sale en 3 o más salas distintas (28-10-2026: «Hal9000» en Jamboree, Safari,
    Monumental, Arena…): el nombre de un DJ residente repetido por el directorio, no un acto concreto. No se publican; el
    registro se conserva. Con hora, o con otra fuente detrás, sí."""
    from mvp.catalog import clean as _clean
    venues = {}
    for e in events:
        if e.get('source') != 'venue_songkick': continue
        venues.setdefault(_clean(e.get('title') or ''), set()).add(_clean((e.get('venue_names') or [''])[0]))
    out = set()
    for e in events:
        if e.get('source') != 'venue_songkick' or len(venues.get(_clean(e.get('title') or ''), ())) < min_venues: continue
        if any(o.get('time') for o in e.get('occurrences') or []) or e.get('time') or (e.get('confirmations') or 1) > 1: continue
        out.add(e['key'])
    return out


class ImageExporter:
    """Copies authorised, locally archived images into ``out/img`` with their credit.

    Thumbnails use ``sips`` when available (macOS); otherwise the original file is
    copied unchanged. Files already exported are reused, so a 3-hourly export
    only touches new images. Duplicate files (same sha256) share one output."""

    def __init__(self, conn, out_dir, media_root, registry, thumbnailer=None):
        self.conn = conn; self.out = Path(out_dir) / 'img'; self.media_root = Path(media_root); self.registry = registry
        self.thumbnailer = thumbnailer if thumbnailer is not None else default_thumbnailer()
        self.by_sha = {}; self.exported = {}; self.stats = {'exported': 0, 'reused': 0, 'skipped_not_local': 0, 'skipped_rights': 0, 'skipped_too_large': 0, 'failed': 0}
        self.out.mkdir(parents=True, exist_ok=True)

    def item(self, media_item):
        """An exported image for a listing/detail media item: a record's own asset, or a venue photo."""
        if media_item.get('place_id'): return self.place(media_item['place_id'])
        return self.asset(media_item['asset_id'])

    def place(self, place_id):
        key = 'place:' + str(place_id)
        if key in self.exported: return self.exported[key]
        from src.place_images import local_place_images
        if not hasattr(self, '_places'): self._places = local_place_images(self.conn)
        place = self._places.get(str(place_id)); result = None
        if place and place.get('local_path') and Path(place['local_path']).is_file():
            entry = self.registry.get('place', {})
            credit = {'source': 'place', 'source_label': 'Ajuntament de Barcelona', 'attribution': entry.get('attribution') or 'Ajuntament de Barcelona', 'original_url': place.get('page_url') or place.get('image_url') or '', 'license_url': entry.get('license_url', ''), 'basis': 'venue_photo', 'fallback': True}
            if place.get('sha256') and place['sha256'] in self.by_sha: result = {'url': self.by_sha[place['sha256']], 'credit': credit}; self.stats['reused'] += 1
            else:
                name = self._write('place-' + str(place['place_id']), Path(place['local_path']), place.get('content_type') or '')
                if name:
                    result = {'url': '/img/' + name, 'credit': credit}
                    if place.get('sha256'): self.by_sha[place['sha256']] = result['url']
        self.exported[key] = result
        return result

    def asset(self, asset_id):
        if asset_id in self.exported: return self.exported[asset_id]
        row = self.conn.execute('SELECT local_path,content_type,sha256,original_url,rights_status,alt_text,source FROM media_assets WHERE asset_id=?', (asset_id,)).fetchone()
        result = None
        if row:
            local_path, content_type, sha, original_url, rights, alt, source = row
            if rights != 'authorized': self.stats['skipped_rights'] += 1
            elif not local_path or not Path(local_path).is_file(): self.stats['skipped_not_local'] += 1
            else:
                entry = registry_entry(self.registry, source)
                credit = {'source': source, 'source_label': catalog.SOURCES.get(source, source), 'attribution': credit_name(source, entry),
                          'original_url': original_url, 'license_url': entry.get('license_url', ''), 'basis': 'source_policy'}
                if sha and sha in self.by_sha:
                    result = {'url': self.by_sha[sha], 'credit': credit}; self.stats['reused'] += 1
                else:
                    name = self._write(asset_id, Path(local_path), content_type or '')
                    if name:
                        result = {'url': '/img/' + name, 'credit': credit}
                        if sha: self.by_sha[sha] = result['url']
        self.exported[asset_id] = result
        return result

    def _write(self, asset_id, src, content_type):
        ext = IMAGE_EXTENSIONS.get(content_type.split(';')[0].strip().lower()) or (src.suffix.lower() if src.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif') else '.jpg')
        name = f'{asset_id}{ext}'; dst = self.out / name
        if dst.is_file() and dst.stat().st_size > 0:
            self.stats['reused'] += 1; return name
        try:
            ok = self.thumbnailer(src, dst) if self.thumbnailer else False
            if not ok: shutil.copyfile(src, dst)
        except OSError:
            self.stats['failed'] += 1; return None
        if dst.stat().st_size > MAX_ASSET_BYTES:
            dst.unlink(); self.stats['skipped_too_large'] += 1; return None
        self.stats['exported'] += 1
        return name


def default_thumbnailer():
    """macOS ``sips`` resizes in place without third-party packages; elsewhere None (plain copy)."""
    sips = shutil.which('sips')
    if not sips: return None
    def resize(src, dst):
        result = subprocess.run([sips, '-Z', str(THUMBNAIL_MAX_PX), str(src), '--out', str(dst)], capture_output=True, text=True, timeout=60)
        return result.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
    return resize


# Texto de horario de la fuente sin horas (26-10-2026, David): «Horaris i preus segons establiment»,
# «Consulteu horari en el programa». La tarjeta lo muestra en vez del genérico «Hora por confirmar».
_SCHEDULE_TEXT = {}
# Sede comprobada a mano (field_verifications, campo «venue», con URL de evidencia): manda sobre la de la fuente
# en tarjeta y ficha. Serielizados: Open Data da solo la sala Phenomena y el festival va en varias salas (26-10-2026).
_VERIFIED_VENUE = {}
_HINT_CLOCK = re.compile(r"\b\d{1,2}(?:[:.]\d{2})?\s*h\b|\b\d{1,2}:\d{2}\b")


def schedule_hint(text):
    text = ' '.join(str(text or '').split())
    if not text or len(text) > 80 or _HINT_CLOCK.search(text): return ''
    return text


def packed_hours(event, field='hours_by_day'):
    """Horario por día en poco espacio: {etiqueta: [días desde el inicio]}.

    Un curso semanal de nueve meses tiene decenas de días con la misma hora;
    repetir cada fecha haría crecer el catálogo sin aportar nada."""
    hours = event.get(field) or {}
    if not hours: return None
    start = dt.date.fromisoformat(event['start'])
    out = {}
    for day, label in sorted(hours.items()):
        out.setdefault(label, []).append((dt.date.fromisoformat(day) - start).days)
    return out


_RELEVANT = {'rx': None}


# Las entradas comodín del registro («venue_*», «ticket_*», «venue_ia_*») describen la regla del crédito («Nombre del
# recinto, con enlace a su página»), no el crédito: la web lo mostraba tal cual (28-10-2026). Se pone el nombre de la sala
# o de la ticketera; el enlace ya va en la ficha.
CREDIT_RULE = re.compile(r"^(?:nombre del recinto|nombre de la ticketera|sala que acoge|«datos de la sala»)", re.I)


def credit_name(source, entry):
    text = entry.get('attribution') or ''
    if text and not CREDIT_RULE.match(text): return text
    if str(source).startswith('venue_ia_'):
        from src.ai_agenda import agenda_for_source
        name = (agenda_for_source(source) or {}).get('name')
        if name: return name
    label = str(catalog.SOURCES.get(source) or '').split(' · ')[0].strip()
    return label or 'Web de la sala'


def relevant_venue(event):
    """¿Es en una sala o centro de referencia? (config/salas_relevantes.json)."""
    import unicodedata
    if _RELEVANT['rx'] is None:
        try: pats = json.loads((ROOT / 'config' / 'salas_relevantes.json').read_text(encoding='utf-8')).get('patrones', [])
        except (OSError, ValueError): pats = []
        _RELEVANT['rx'] = re.compile('|'.join(pats)) if pats else re.compile(r'(?!x)x')
    name = ' '.join(event.get('venue_names') or []).replace('·', '.').replace('’', "'")
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().lower()
    return bool(_RELEVANT['rx'].search(name))


def day_highlights(items, day, size=None, floor=60):
    """Claves a destacar en la lista del día: actos con hora ese día (no exposiciones ni
    cursos), puntuados con catalog.featured_score; uno por obra y repartidos por sala."""
    size = size or HIGHLIGHT_SIZE
    pool = []
    for e in items:
        if e.get('eligibility') == 'exclude' or e.get('kind') in ('exhibition', 'course') or not e.get('time') or e.get('is_promo'): continue
        if e['start'] != e['end'] and e['occurrences'] and not any(o['date'] == day for o in e['occurrences']): continue
        x = dict(e, featured_date=day); score, _ = catalog.featured_score(x, day)
        if score >= floor: x['featured_score'] = score; pool.append(x)
    pool.sort(key=lambda e: (-e['featured_score'], catalog.featured_rotation(e, day)))
    return [e['key'] for e in catalog.spread_venues(catalog.one_per_title(pool))][:size]

EXPO_FLOOR = 20   # «Selección Ontoca» en Expos (27-10-2026): por debajo, ninguna del tramo se destaca


def expo_rank(items, day, floor=None):
    """{clave: puntos} de las exposiciones abiertas ese día que pueden destacarse en la pestaña Expos.

    Mismas reglas explicables que la portada (catalog.featured_score: peso del espacio, imagen propia,
    descripción, coincidencia entre fuentes, horario) y +6 si se inauguró hace 14 días o menos. La web
    elige como mucho una por tramo de 9 filas y una por espacio (static/public.js, expoHighlights)."""
    floor = EXPO_FLOOR if floor is None else floor
    pool = []
    for e in items:
        if e.get('eligibility') == 'exclude' or not (e.get('kind') == 'exhibition' or e.get('format') == 'exhibition'): continue
        if not (e['start'] <= day <= e['end']) or (e.get('hours_by_day') and day not in e['hours_by_day']): continue
        # Solo museos, centros y salas con peso propio (config/venue_prestige.json, 8 puntos o más): la red de
        # proximidad (centros cívicos, bibliotecas, casals) no se destaca aunque la anuncien varias fuentes.
        # Un espacio marcado como cerrado («*Tancat temporalment») tampoco.
        # Desde el 27-10-2026 también los espacios de arte de la lista «exposiciones» (galerías y centros de arte
        # elegidos uno a uno), aunque no tengan esos puntos en la portada.
        from src.venue_prestige import prestige, art_space
        if prestige(e.get('venue_names'))[0] < 8 and not art_space(e.get('venue_names')): continue
        if re.search(r'\*\s*(?:tancat|tancada|cerrad[oa]|closed)', ' '.join(e.get('venue_names') or []), re.I): continue
        score, _ = catalog.featured_score(dict(e, featured_date=day), day)
        opened = (dt.date.fromisoformat(day) - dt.date.fromisoformat(e['start'][:10])).days
        if 0 <= opened <= 14: score += 6
        if score >= floor: pool.append((score, catalog.featured_rotation(e, day), e['key']))
    pool.sort(key=lambda x: (-x[0], x[1]))
    # El orden ya desempata (rotación diaria): la web solo necesita el puesto.
    return {k: len(pool) - i for i, (_, _, k) in enumerate(pool)}


def featured_pool(conn, day, size, **kw):
    """Candidatos de la Selección de un día en su orden, hasta ``size`` (la API da páginas de 100 como mucho)."""
    first = catalog.query_events(conn, day=day, featured=True, public=True, page_size=100, **kw)
    items = list(first['items']); page = 1
    while len(items) < min(size, first.get('total') or 0):
        page += 1
        more = catalog.query_events(conn, day=day, featured=True, public=True, page_size=100, page=page, **kw)['items']
        if not more: break
        items += more
    return {**first, 'items': items[:size]}


def picks_by_category(items, images, hidden=frozenset()):
    """{categoría: [fichas]} con los candidatos de la Selección en su orden de puntuación: con imagen o descripción,
    sin promociones, una ficha por obra y como mucho PICKS_PER_CATEGORY por categoría. Solo las categorías con 3 o más."""
    out, seen = {}, set()
    for e in items:
        cat = e.get('public_category') or ''
        if not cat or e.get('is_promo') or not (e.get('media') or e.get('has_description')): continue
        work = (cat, (e.get('series') or e.get('title') or '').strip().lower())
        if work in seen or len(out.get(cat, [])) >= PICKS_PER_CATEGORY: continue
        seen.add(work); out.setdefault(cat, []).append(e)
    return {c: [compact(e, images, hidden=hidden) for e in v] for c, v in out.items() if len(v) >= 3}


def compact(event, images, full=True, hidden=frozenset()):
    """The listing record the browser needs, with short keys to keep files small.

    The catalogue (``full=False``) carries only what filtering, ranking and the
    list rows use; the per-day files and the detail shards carry the rest
    (summary, price, image, source label, link)."""
    out = {
        's': event['source'], 'i': event['id'], 't': event['title'], 'a': event['start'], 'b': event['end'], 'kd': event['kind'], 'f': event['format'],
        'pc': event['public_category'], 'd': event['district'] or '', 'fa': 1 if event['family_audience'] else 0, 'hd': 1 if event['has_description'] else 0,
        'v': [v for v in event['venue_names'][:2]], 'g': [round(event['coordinates']['lat'], 5), round(event['coordinates']['lon'], 5)] if event.get('coordinates') else None,
        'o': [[o['date'], o['time'] or ''] for o in event['occurrences']][:80], 'fr': 1 if event['is_free'] else 0, 'ch': event.get('channels') or [], 'tm': event.get('time') or '', 'tl': event['time_label'],
    }
    vv = _VERIFIED_VENUE.get(event.get('key') or f"{event['source']}:{event['id']}")
    if vv: out['v'] = [vv]; out['g'] = None  # varias sedes: sin un punto en el mapa
    if event.get('time_conflicts'): out['tc'] = event['time_conflicts']
    # Días que abre el espacio de una exposición (y si atiende con cita previa), del horario que publica (27-10-2026).
    if event.get('opening_days') and event.get('kind') == 'exhibition': out['od'] = event['opening_days']['dias']; out['oc'] = 1 if event['opening_days'].get('cita') else 0  # días con horas que no cuadran: «por confirmar» (27-10-2026)
    tx = _SCHEDULE_TEXT.get(event.get('key') or f"{event['source']}:{event['id']}")
    if tx and not any(o.get('time') for o in event['occurrences']): out['tx'] = tx
    if event.get('hours_by_day'): out['hb'] = packed_hours(event)
    if event.get('notes_by_day'): out['nd'] = packed_hours(event, 'notes_by_day')  # actividad de cada día
    if event.get('age_source'): out['ag'] = [event['age_min'], 99 if event.get('age_max') is None else event['age_max']]  # franja de edad
    if event.get('series'): out['se'] = event['series']  # serie que la web agrupa en una fila
    if event.get('languages'): out['lg'] = event['languages']  # idioma de la actividad, si la fuente lo dice
    if event.get('milestone'): out['ms'] = event['milestone']['kind'][:2]  # «op» inauguración, «cl» clausura (src/milestones.py)
    if event.get('festival'): out['fs'] = [event['festival']['slug'], event['festival']['name'], 1 if event['festival']['umbrella'] else 0] + ([1] if event['festival'].get('kind') == 'fiesta' else [])  # festival (src/festivals.py)
    if event.get('lineup'): out['lu'] = event['lineup'][:40]
    if event.get('featured_date'): out['fd'] = event['featured_date']  # para buscar por artista
    if event.get('program'):
        out['pg'] = list(dict.fromkeys(p['title'] for p in event['program']))[:400]  # programa del festival (abono): para el buscador
        first = {}
        for p in event['program']:
            if p.get('time') and (p['date'] not in first or p['time'] < first[p['date']]): first[p['date']] = p['time']
        if first: out['pf'] = first  # primera sesión de cada día según su programa oficial (no se extrapola)
        days = {}
        for p in event['program']: days[p['date']] = days.get(p['date'], 0) + 1
        out['pn'] = days  # actuaciones por día del programa oficial: la fila del festival de abono dice cuántas hay (28-10-2026)
    if event.get('manual_hours'): out['mh'] = event['manual_hours']  # hora puesta a mano por David, con su fuente
    if event.get('drop_in'): out['di'] = 1  # la fuente dice que las sesiones son sueltas (mvp.catalog.drop_in)
    if event.get('open_enrollment'): out['oe'] = 1  # la fuente dice que te puedes apuntar en cualquier momento
    if event.get('registration_required'): out['rr'] = 1  # hay que inscribirse: etiqueta «Inscripción» en la fila de cursos (26-10-2026)
    if event.get('sold_out'): out['so'] = event['sold_out'].get('dias') or 1  # entradas agotadas: días que nombra el aviso o 1 = todos
    # Nivel de la sala (config/venue_prestige.json: 12 referencia, 8 consolidada, 3 proximidad): una de las señales con que
    # la web ordena dentro de cada hora y en Expos (28-10-2026). Los espacios de arte elegidos para Expos cuentan como 8.
    from src.venue_prestige import prestige, art_space
    vt = prestige(event.get('venue_names'))[0]
    if vt < 8 and art_space(event.get('venue_names')): vt = 8
    if vt: out['vt'] = vt
    # Precio corto para la fila (28-10-2026): el importe más bajo en euros que da la fuente y si hay más de uno («desde»).
    if not event['is_free']:
        nums = [float(x.replace(',', '.')) for x in re.findall(r'(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur\b)', str(event.get('price_label') or ''), re.I)]
        nums = [n for n in nums if 0 < n < 1000]
        if nums: out['pp'] = [min(nums), 1 if any(n != min(nums) for n in nums) else 0]
    if event.get('is_promo'): out['pm'] = 1  # título con reclamo de venta: no se destaca ni encabeza una hora
    if relevant_venue(event): out['rv'] = 1  # sala de referencia (config/salas_relevantes.json): puede destacarse
    if (event.get('confirmations') or 1) >= 3: out['cf'] = event['confirmations']  # lo anuncian tres fuentes o más
    if not full:
        # Imagen de lo que la lista puede destacar (exposiciones y programas largos, salas de referencia,
        # actos que confirman varias fuentes): se muestra solo en las filas destacadas.
        if (event['start'] != event['end'] and event['kind'] in ('exhibition', 'program')) or out.get('rv') or out.get('cf'):
            first = next((i for i in event.get('media', []) if not i.get('fallback')), None)
            exported = images.item(first) if first else None
            if exported: out['mi'] = exported['url']
        return out
    media = []
    for item in event.get('media', [])[:MAX_IMAGES_PER_EVENT]:
        exported = images.item(item)
        if exported: media.append({'u': exported['url'], 'alt': item.get('alt') or '', 'cr': exported['credit']['attribution'], **({'fb': 1} if item.get('fallback') else {})}); break
    out.update({'sl': event['source_label'], 'c': event['category'], 'su': (event['summary'] or '')[:200], 'pl': event['price_label'] or '', 'm': media, 'u': '' if event['url'] in hidden else (event['url'] or '')})
    return out


def public_detail(detail, images, hidden=frozenset()):
    out = {k: detail.get(k) for k in PUBLIC_DETAIL_FIELDS}
    out['hours_by_day'] = packed_hours(detail)
    out['notes_by_day'] = packed_hours(detail, 'notes_by_day')
    media = []
    for item in detail.get('media', [])[:MAX_IMAGES_PER_EVENT]:
        exported = images.item(item)
        if exported: media.append({'url': exported['url'], 'alt': item.get('alt') or '', 'credit': exported['credit'], **({'fallback': True} if item.get('fallback') else {})})
    out['media'] = media
    out['links'] = [{'label': l['label'], 'url': l['url']} for l in detail.get('links', []) if str(l.get('url', '')).startswith('https://') and l['url'] not in hidden]
    # Enlaces que hoy dan 404/410/5xx (src/link_check.py): fuera de la web hasta que respondan bien.
    if out.get('url') in hidden: out['url'] = ''
    if (out.get('official_page') or {}).get('url') in hidden: out['official_page'] = None
    # Descripción breve con IA: solo con config/ia.json → descripciones_publicas (tras revisar la muestra).
    from src.ai_describe import public_enabled
    if not public_enabled(): out['ai_summary'] = None
    from src import ai_family
    if not ai_family.public_enabled() or 'familia' not in (out.get('channels') or []): out['family_ai'] = None
    return out


MONTHS_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
DAYS_ES = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']
GENERIC_TIME = {'Varios días', 'Exposición', 'Hora no indicada', ''}


# Solo «19:00» con dos puntos (como la web, public.js): «12.50» puede ser un precio.
_CLOCK = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)(?!\d)')
_RANGE = re.compile(r'\b([01]?\d|2[0-3]):([0-5]\d)\s*[–-]\s*([01]?\d|2[0-3]):([0-5]\d)(?!\d)')


def _clocks(text):
    return sorted({f'{int(h):02d}:{m}' for h, m in _CLOCK.findall(str(text or ''))})


def _slot(text, times=None):
    """Hueco de calendario de un día, solo con lo que dice la fuente:
    «19:00-21:00» (rango publicado), «19:00» (hora de inicio, sin fin), «S19:00,21:00»
    (varias sesiones: día completo con las horas en la nota) o «» (día completo, sin hora)."""
    text, explicit = str(text or ''), sorted(set(times or []))
    ranges = _RANGE.findall(text)
    if ranges:
        opens = f'{int(ranges[0][0]):02d}:{ranges[0][1]}'
        # El rango vale si no hay sesiones fechadas o si la única sesión empieza a esa hora.
        if not explicit or explicit == [opens]: return f'{opens}-{int(ranges[-1][2]):02d}:{ranges[-1][3]}'
    times = explicit or _clocks(text)
    if len(times) == 1: return times[0]
    if len(times) > 1: return 'S' + ','.join(times)
    return ''


def calendar_days(detail, today, horizon_days=HORIZON_DAYS):
    """Qué se añade al calendario cada día del acto ({día: hueco}, ver _slot), desde hoy y
    dentro del horizonte publicado. Nunca inventa: sin hora publicada, día completo; sin
    hora de fin, solo la de inicio. Los días válidos son los de la propia ficha: sesiones
    fechadas, días del horario oficial (hours_by_day) o, si no hay, todos los del periodo."""
    start, end = detail.get('start') or '', detail.get('end') or ''
    if not start: return {}
    end = end or start
    first, last = max(start, today.isoformat()), min(end, (today + dt.timedelta(days=horizon_days)).isoformat())
    if first > last: return {}
    label, base = detail.get('time_label') or '', detail.get('time') or ''
    general = '' if label in GENERIC_TIME else label
    occ = {}
    for o in detail.get('occurrences') or []:
        d = str(o.get('date') or '')[:10]
        if first <= d <= last: occ.setdefault(d, set()).update(_clocks(o.get('time')))
    by_day = {d: v for d, v in (detail.get('hours_by_day') or {}).items() if first <= d <= last}
    out = {}
    if occ:
        for d, times in occ.items():
            if times: out[d] = _slot(by_day.get(d) or general or base, times)
            else: out[d] = _slot(by_day.get(d, general if start == end else ''))
    elif by_day and start != end:
        out = {d: _slot(v) for d, v in by_day.items()}
    elif start == end:
        out = {start: _slot(f'{general} {base}' if general and base and base not in general else general or base)}
    else:
        slot = _slot(general)
        day = dt.date.fromisoformat(first)
        while day.isoformat() <= last:
            out[day.isoformat()] = slot; day += dt.timedelta(days=1)
    return dict(sorted(out.items()))


def packed_calendar(detail, today):
    """Como packed_hours, {hueco: [días desde el inicio]}, pero los días seguidos van como
    [desde, hasta]: una exposición de seis meses abierta cada día ocupa un par de números."""
    days = calendar_days(detail, today)
    if not days: return None
    base = dt.date.fromisoformat(detail['start'])
    offsets = {}
    for day, slot in days.items(): offsets.setdefault(slot, []).append((dt.date.fromisoformat(day) - base).days)
    out = {}
    for slot, ns in offsets.items():
        runs = []
        for n in ns:
            if runs and isinstance(runs[-1], list) and runs[-1][1] == n - 1: runs[-1][1] = n
            elif runs and isinstance(runs[-1], int) and runs[-1] == n - 1: runs[-1] = [runs[-1], n]
            else: runs.append(n)
        out[slot] = runs
    return out


def share_card(detail, today):
    """Lo que se ve al compartir el enlace (WhatsApp, Telegram, redes): título, cuándo, dónde,
    una frase de la descripción y la imagen. Solo datos que ya publica la ficha."""
    def day(d):
        x = dt.date.fromisoformat(d); return f"{DAYS_ES[x.weekday()]} {x.day} {MONTHS_ES[x.month - 1]}"
    start, end = detail.get('start') or '', detail.get('end') or ''
    label = detail.get('time_label') or ''
    hours = '' if label in GENERIC_TIME else re.sub(r'\b0?0[:.]00\s*[–-]\s*23[:.]59\b', 'todo el día', str(label)).replace('23:59', 'medianoche')
    if start and start == end: when = day(start) + (f' · {hours}' if hours else '')
    elif start and end:
        x = dt.date.fromisoformat(end)
        span = f"Hasta el {x.day} {MONTHS_ES[x.month - 1]}" if start <= today.isoformat() else f"Del {day(start)} al {day(end)}"
        when = span + (f' · {hours}' if hours else '')
    else: when = ''
    venue = (detail.get('venue_names') or [''])[0] or ''
    text = ' '.join(str(detail.get('summary') or detail.get('description') or detail.get('editorial_summary') or '').split())
    if len(text) > 150:
        cut = text[:150]; text = (cut[:cut.rfind(' ')] if ' ' in cut else cut).rstrip(' ,.;:') + '…'
    price = 'Gratis' if detail.get('is_free') else ''
    media = detail.get('media') or []
    return {'t': detail.get('title') or '', 'w': when, 'v': venue, 'd': text, 'p': price,
            'i': media[0]['url'] if media else '', 'a': start, 'b': end, 'tm': detail.get('time') or '',
            'g': [detail['coordinates']['lat'], detail['coordinates']['lon']] if detail.get('coordinates') else None,
            'ad': ((detail.get('venues') or [{}])[0] or {}).get('address') or '',
            # Añadir al calendario (functions/cal/[[path]].js): hueco por día y web oficial del acto.
            'c': detail.get('public_category') or '', 'ch': list(detail.get('channels') or []),   # para «actos parecidos» cuando ya ha pasado
            'k': packed_calendar(detail, today), 'o': ((detail.get('official_page') or {}).get('url') or '') if str((detail.get('official_page') or {}).get('url') or '').startswith('https://') else ''}


def write_translations(conn, out, shards):
    """Traducciones automáticas de la descripción (src/ai_translate.py, 24-10-2026): deja las descripciones
    publicadas para que «ia-asistente» las traduzca y escribe /data/tr/<idioma>/<shard>.json con las ya
    hechas que pasan la comprobación ({clave: {t: texto, m: modelo, f: fecha}}). Un fichero por shard de
    ficha aunque esté vacío, para que la web no pida ficheros que no existen."""
    from src import ai_assist, ai_translate, official_translations, venue_text
    scope = {k: r.get('description_scope') for records in shards.values() for k, r in records.items()}
    texts = {k: str(r.get('description') or '').strip() for records in shards.values() for k, r in records.items()}
    texts = {k: v for k, v in texts.items() if ai_translate.needs(v)}
    try: ai_assist.queue_translations(conn, texts)
    except sqlite3.DatabaseError: pass  # base de solo lectura (pruebas): se publican las que haya
    counts = {}
    for lang in ai_translate.TARGETS:
        files = {name: {} for name in shards}
        for k, text in texts.items():
            # La de la propia sala (src/official_translations.py) antes que la automática.
            # Con el texto completo de la sala, su versión en ese idioma (misma página); si no, la del texto breve.
            if scope.get(k) == 'sala':
                source, _, rid = k.partition(':'); official = venue_text.text_for(conn, source, rid, lang)
            else: official = official_translations.official_for(conn, k, lang)
            if official: files[shard_of(k)][k] = {'t': official['text'], 'o': 1, 'u': official['url'], 'f': official['date']}; continue
            tr = ai_assist.translation_for(conn, k, text, lang)
            # Una «traducción» que devuelve el texto de origen (la IA respondió en catalán) no se publica: la web la
            # presentaba como «Traducción automática» con el original debajo (MNAC, 28-10-2026).
            if tr and (' '.join(tr['text'].split()) == ' '.join(text.split()) or ai_translate.guess_lang(tr['text']) not in ('', lang)): tr = None
            if tr: files[shard_of(k)][k] = {'t': tr['text'], 'm': tr['model'], 'f': tr['date']}
        for name, records in files.items(): _write_json(out / 'data' / 'tr' / lang / f'{name}.json', records)
        counts[lang] = sum(len(r) for r in files.values()); counts[lang + '_oficiales'] = sum(1 for r in files.values() for v in r.values() if v.get('o'))
    return {'descripciones': len(texts), 'traducidas': counts}


def shard_of(key):
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:2]


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


CONTACT_EMAIL = 'hola@ontoca.com'   # buzón de contacto (Cloudflare Email Routing → Gmail; responde vía Brevo), 23-10-2026


def credits_html(registry=None, generated_at='', counts=None, skin_css=''):
    """La página pública de Fuentes (25-10-2026): lo mínimo que piden las licencias, en tres idiomas.
    El detalle por fuente sigue en docs/source_registry.json; ya no se publica (decisión de David)."""
    from src import legal_pages
    return legal_pages.page_html('creditos', skin_css)


# Estilo de la web pública. 'v2' (por defecto desde el 23-10-2026): public-v2.css encima de
# public.css y solo modo claro. Para volver a la versión 1 basta con poner PUBLIC_SKIN = ''.
PUBLIC_SKIN = 'v2'


def v2_index(index, version):
    """La app con el estilo de la versión 2: la misma app y los mismos datos, con public-v2.css
    encima de public.css y solo modo claro. Se sirve en la portada; /v2/ redirige a ella."""
    v2 = index.replace('data-static="1"', 'data-static="1" data-skin="v2"', 1).replace('data-theme="dark"', 'data-theme="light"', 1)
    link = f'<link rel="stylesheet" href="/public-v2.css?v={version}">'
    v2 = re.sub(r'(<link rel="stylesheet" href="/public\.css[^"]*">)', lambda m: m.group(1) + link, v2, count=1)
    if link not in v2: v2 = v2.replace('</head>', link + '</head>', 1)
    return v2


def headers_file():
    # challenges.cloudflare.com: Turnstile, la comprobación antirrobots del alta de avisos (25-10-2026)
    return ('/*\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Referrer-Policy: strict-origin-when-cross-origin\n'
            "  Content-Security-Policy: default-src 'self'; connect-src 'self' https://autonomoclaro.com https://challenges.cloudflare.com; img-src 'self' https://tile.openstreetmap.org https://autonomoclaro.com; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' https://autonomoclaro.com https://challenges.cloudflare.com; frame-src https://www.openstreetmap.org https://challenges.cloudflare.com; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'\n"
            '/img/*\n  Cache-Control: public, max-age=2592000, immutable\n/data/*\n  Cache-Control: public, max-age=600\n/vendor/*\n  Cache-Control: public, max-age=604800\n/public.js\n  Cache-Control: public, max-age=0, must-revalidate\n/analytics.js\n  Cache-Control: public, max-age=0, must-revalidate\n/legal.js\n  Cache-Control: public, max-age=0, must-revalidate\n/public.css\n  Cache-Control: public, max-age=0, must-revalidate\n/public-v2.css\n  Cache-Control: public, max-age=0, must-revalidate\n/fonts/*\n  Cache-Control: public, max-age=31536000, immutable\n/favicon.svg\n  Cache-Control: public, max-age=86400\n/favicon-32.png\n  Cache-Control: public, max-age=86400\n/apple-touch-icon.png\n  Cache-Control: public, max-age=86400\n/v2/*\n  Cache-Control: public, max-age=0, must-revalidate\n/\n  Cache-Control: public, max-age=0, must-revalidate\n/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n/e/*\n  Cache-Control: public, max-age=0, must-revalidate\n')


def _content_hash(out):
    h = hashlib.sha256()
    for path in sorted(p for p in out.rglob('*') if p.is_file()):
        rel = path.relative_to(out).as_posix()
        if rel in ('data/meta.json', 'creditos.html'): continue  # carry the generation timestamp, not content
        if rel.startswith('img/'): h.update(f'{rel}:{path.stat().st_size}\n'.encode())
        else: h.update(rel.encode()); h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def _links_of(detail):
    """Los enlaces externos que la ficha pública puede mostrar: botón principal, web oficial y secundarios."""
    out = [('Botón principal', detail.get('url'))]
    if detail.get('official_page'): out.append(('Web oficial', detail['official_page'].get('url')))
    out += [(l.get('label') or '', l.get('url')) for l in detail.get('links', [])]
    return [(label, url) for label, url in out if str(url or '').startswith('https://')]


def check_links(conn, details, fetch=None):
    """Comprueba (si hay ``fetch``) y devuelve los enlaces rotos que la exportación oculta, con un resumen."""
    from src import link_check
    usage = [(url, d['source'], d['id'], label) for d in details for label, url in _links_of(d)]
    urls = {u for u, _, _, _ in usage}
    report = {'links': len(urls), 'checked': 0}
    try:
        if fetch: report = link_check.refresh(conn, urls, fetch)
        link_check.record_usage(conn, usage)
    except sqlite3.OperationalError as exc:  # base de solo lectura: se usa el último estado guardado
        report['error'] = str(exc)
    hidden = link_check.broken(conn, urls)
    report['hidden'] = len(hidden)
    return hidden, report


ALERTS_FEED_DAYS = 15   # novedades que lee el envío de alertas (alertas/worker.js): las de las dos últimas semanas


def write_alerts_feed(out, events, today, generated_at):
    """Novedades para las alertas por correo (24-10-2026): data/alertas/nuevos.json con los actos
    publicados que aparecieron por primera vez en los últimos ALERTS_FEED_DAYS días y que aún no han
    terminado. La fecha de primera aparición se guarda en data/first_seen.json, junto a la carpeta
    publicada, y no se borra. La primera vez todo lo que ya existe se marca como visto ('base'):
    nadie recibe de golpe toda la agenda como «novedad». Solo datos que ya publica la ficha."""
    path = out.parent / 'data' / 'first_seen.json'
    try: seen = json.loads(path.read_text(encoding='utf-8')); first_run = False
    except (OSError, ValueError): seen, first_run = {}, True
    for e in events:
        if e['key'] not in seen: seen[e['key']] = 'base' if first_run else generated_at
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    since = (dt.datetime.fromisoformat(generated_at) - dt.timedelta(days=ALERTS_FEED_DAYS)).isoformat(timespec='seconds')
    items = []
    for e in events:
        first = seen.get(e['key'], 'base')
        if first == 'base' or first < since or e['end'] < today.isoformat(): continue
        items.append({'k': e['key'], 'fs': first, 't': e['title'], 'a': e['start'], 'b': e['end'], 'tm': e.get('time') or '',
                      'tl': e.get('time_label') or '', 'v': (e.get('venue_names') or [''])[0] or '', 'd': e.get('district') or '',
                      'pc': e.get('public_category') or '', 'ch': e.get('channels') or [], 'fr': 1 if e.get('is_free') else 0,
                      'lu': (e.get('lineup') or [])[:10]})
    items.sort(key=lambda x: (x['fs'], x['a'], x['k']))
    _write_json(out / 'data' / 'alertas' / 'nuevos.json', {'items': items})   # sin fecha de generación: solo cambia si hay novedades
    return len(items)


PAST_KEEP_DAYS = 183   # cuánto se conserva la ficha de un acto ya celebrado (decidido el 23-10-2026: 6 meses)
PAST_SKIP_SOURCES = ('ticketmaster',)   # los caducados de Ticketmaster se borran (decisión de David)


def keep_past_cards(out, cards, today, gone=frozenset()):
    """Actos ya celebrados (23-10-2026): su dirección /e/<fuente>/<id> sigue respondiendo durante
    PAST_KEEP_DAYS con «Ya se celebró» (functions/e/[[path]].js, fuera del índice de los buscadores).
    Se guarda la última tarjeta publicada de cada acto en data/share_archive.json, junto a la carpeta
    publicada, y se vuelve a publicar con 'x': 1 solo si su fecha final ya pasó: lo que desaparece por
    otro motivo (cancelado, excluido, aplazado) no se conserva. No se borra nada del archivo.
    ``gone``: claves que la fuente da por aplazadas o canceladas (src/event_status.py, 24-10-2026): su tarjeta
    no vuelve como «Ya se celebró» aunque su fecha ya haya pasado."""
    path = out.parent / 'data' / 'share_archive.json'
    try: archive = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError): archive = {}
    current = {k for records in cards.values() for k in records}
    for records in cards.values():
        for k, card in records.items(): archive[k] = card
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    limit = (today - dt.timedelta(days=PAST_KEEP_DAYS)).isoformat(); kept = 0
    for k, card in archive.items():
        if k in current or k in gone or k.split(':', 1)[0].startswith(PAST_SKIP_SOURCES): continue
        end = card.get('b') or card.get('a') or ''
        if not end or end >= today.isoformat() or end < limit: continue
        cards.setdefault(shard_of(k), {})[k] = {**card, 'x': 1, 'k': ''}   # sin «añadir al calendario»
        kept += 1
    return kept


URI_SAFE = "!'()*"   # lo que encodeURIComponent deja sin escapar, además de - _ . ~
SITEMAP_CHUNK = 40000   # Google admite 50.000 direcciones por fichero; margen por si crece


def write_sitemaps(out, site_url, events, cards, today, landing_paths=()):
    """Sitemap por partes (23-10-2026): un índice en /sitemap.xml, las páginas fijas y las fichas
    /e/<fuente>/<id> en ficheros de hasta SITEMAP_CHUNK direcciones, siempre con el dominio completo.
    lastmod es el día en que cambió lo que se ve de la ficha (título, cuándo, dónde, texto, imagen),
    no el de cada publicación: Google solo lo tiene en cuenta si es fiable. Se guarda fuera de la web,
    en data/sitemap_lastmod.json junto a la carpeta publicada, y nunca se borran entradas."""
    for old in out.glob('sitemap*.xml'): old.unlink()
    if not site_url:   # sin dominio un sitemap no es válido: solo uno vacío
        (out / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>', encoding='utf-8')
        return
    base = site_url.rstrip('/')
    state_path = out.parent / 'data' / 'sitemap_lastmod.json'
    try: state = json.loads(state_path.read_text(encoding='utf-8'))
    except (OSError, ValueError): state = {}
    seen = {}
    for name, records in cards.items():
        for k, card in records.items():
            digest = hashlib.sha256(json.dumps({x: card.get(x) for x in ('t', 'w', 'v', 'ad', 'd', 'p', 'i', 'a', 'b', 'tm', 'o')}, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()[:16]
            prev = state.get(k)
            if not prev or prev[0] != digest: state[k] = [digest, today.isoformat()]
            seen[k] = state[k][1]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    def urlset(rows):
        return ('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                + ''.join(f'<url><loc>{html.escape(u)}</loc>' + (f'<lastmod>{m}</lastmod>' if m else '') + '</url>' for u, m in rows) + '</urlset>')
    files = {'sitemap-paginas.xml': [(f'{base}/', today.isoformat()), (f'{base}/creditos', ''), (f'{base}/aviso-legal', ''), (f'{base}/privacidad', '')] + [(f'{base}{p}', today.isoformat()) for p in landing_paths]}
    def event_url(e):   # igual que eventPath() en public.js (encodeURIComponent)
        return f"{base}/e/{quote(e['source'], safe=URI_SAFE)}/{quote(str(e['id']), safe=URI_SAFE)}"
    rows = [(event_url(e), seen.get(e['key'], '')) for e in sorted(events, key=lambda e: (e['start'], e['key']))]
    for n in range(0, len(rows), SITEMAP_CHUNK): files[f'sitemap-fichas-{n // SITEMAP_CHUNK + 1}.xml'] = rows[n:n + SITEMAP_CHUNK]
    for name, part in files.items(): (out / name).write_text(urlset(part), encoding='utf-8')
    (out / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + ''.join(f'<sitemap><loc>{html.escape(base)}/{name}</loc></sitemap>' for name in files) + '</sitemapindex>', encoding='utf-8')


def export(conn, out_dir, *, media_root=ROOT / 'data' / 'media', static_dir=ROOT / 'static', today=None, registry_path=REGISTRY_PATH, thumbnailer=None, site_url='', link_fetcher=None, alerts=None):
    """Write the whole public site into ``out_dir`` and return an audit summary."""
    started = time.monotonic(); today = today or catalog.today(); out = Path(out_dir); registry = _registry(registry_path)
    out.mkdir(parents=True, exist_ok=True)
    for stale in ('data', 'v2', 'dia'):   # v2: la antigua dirección de prueba de la versión 2; dia: las fechas ya pasadas
        if (out / stale).exists(): shutil.rmtree(out / stale)
    phases = {}; mark = time.monotonic()
    def phase(name):
        nonlocal mark
        now = time.monotonic(); phases[name] = round(now - mark, 1); mark = now
    images = ImageExporter(conn, out, media_root, registry, thumbnailer)
    # Clasificación vigente de todas las fichas (también las pendientes y excluidas): tabla
    # event_classification + historial de cambios tras cada sincronización (src/taxonomy.py).
    from src import taxonomy
    try: classification_changes = taxonomy.record(conn, catalog.all_events(conn))
    except sqlite3.OperationalError: classification_changes = None  # base de solo lectura
    phase('clasificacion')
    events = public_events(conn, today)
    phase('fichas_publicas')
    details = {}
    for e in events:
        detail = catalog.event_detail(conn, e['source'], e['id'])
        if detail is not None: details[e['key']] = detail
    _SCHEDULE_TEXT.clear()
    _VERIFIED_VENUE.clear()
    try:
        for s, i, v in conn.execute("SELECT source,id,value_json FROM field_verifications WHERE field_name='venue'"):
            k = f'{s}:{i}'
            if k in details and isinstance(json.loads(v), str):
                _VERIFIED_VENUE[k] = json.loads(v); details[k]['venue_names'] = [_VERIFIED_VENUE[k]]; details[k]['coordinates'] = None
    except Exception: pass
    _SCHEDULE_TEXT.update({k: h for k, d in details.items() if (h := schedule_hint(d.get('time_text')))})
    # Otras fichas del mismo acto en otros días: solo las que también se publican (24-10-2026).
    for detail in details.values():
        detail['other_days'] = {d: k for d, k in (detail.get('other_days') or {}).items() if k in details} or None
    phase('detalle_de_fichas')
    # Inauguración ↔ exposición del mismo espacio, cuando tenemos las dos (src/milestones.py).
    from src.milestones import link as _link_milestones
    to_expo, to_act = _link_milestones(events)
    for k, v in to_expo.items():
        if k in details: details[k]['milestone_link'] = v
    for k, v in to_act.items():
        if k in details: details[k]['opening'] = v
    hidden, link_report = check_links(conn, list(details.values()), link_fetcher)
    phase('enlaces')
    catalogue = [compact(e, images, full=False) for e in events]
    _write_json(out / 'data' / 'taxonomy.json', taxonomy.public_labels(events))
    _write_json(out / 'data' / 'catalog.json', {'today': today.isoformat(), 'horizon_days': HORIZON_DAYS, 'items': catalogue})
    # One ranked first page per day in the horizon, so the first paint and any
    # day tap work before the catalogue has finished loading.
    days = {}
    for offset in range(HORIZON_DAYS + 1):
        day = (today + dt.timedelta(days=offset)).isoformat()
        page = catalog.query_events(conn, day=day, public=True, page_size=PAGE_SIZE, include_started=False)
        featured = featured_pool(conn, day, PICK_POOL_WEEK)
        # Una semana desde ese día: con imagen o descripción, los mejor puntuados.
        picks = [e for e in featured['items'] if e.get('media') or e.get('has_description')][:FEATURED_SIZE]
        # Selección de la semana elegida por la IA para ese día (src/ai_select.py): va primero, en su orden.
        from src.ai_select import picks_for
        chosen = picks_for(conn, day); ai_pick = False
        if chosen:
            pool = {e['key']: e for e in catalog.query_events(conn, day=day, featured=True, public=True, page_size=100)['items']}
            first = [pool[k] for k in chosen if k in pool]
            if len(first) >= 5:
                picks = first + [e for e in picks if e['key'] not in set(chosen)]
                picks = picks[:FEATURED_SIZE]; ai_pick = True
        # Más «Selección Ontoca» para la lista de ese día: los actos de ese día mejor
        # puntuados con las mismas reglas explicables de la portada (featured_score).
        whole = [e for e in events if e['start'] <= day <= e['end'] and (e['start'] == e['end'] or not e.get('hours_by_day') or day in e['hours_by_day'])]
        chosen_hl = day_highlights(whole, day); by_key = {e['key']: e for e in whole}
        highlight, highlight_media = chosen_hl, {}
        ranks_expo = expo_rank(whole, day)
        for k in [*chosen_hl, *sorted(ranks_expo, key=ranks_expo.get, reverse=True)[:60]]:  # imagen de la fuente para la fila destacada (si la hay)
            first = next((i for i in by_key[k].get('media', []) if not i.get('fallback')), None)
            exported = images.item(first) if first else None
            if exported: highlight_media[k] = exported['url']
        # «Selección Ontoca · Hoy» (25-10-2026): las mismas reglas, solo con lo de ese día.
        today_only = catalog.query_events(conn, day=day, featured=True, featured_days=1, public=True, page_size=PICK_POOL)
        picks_today = [e for e in today_only['items'] if e.get('media') or e.get('has_description')][:FEATURED_SIZE]
        # «Selección Ontoca» por tipo (28-10-2026, David): los mejor puntuados de cada categoría, de los mismos candidatos
        # (mismas reglas explicables, sin IA nueva). Fichero aparte, que solo pide la Selección: no pesa en la primera carga.
        _write_json(out / 'data' / 'picks' / f'{day}.json', {'w': picks_by_category(featured['items'], images, hidden),
                                                            't': picks_by_category(today_only['items'], images, hidden)})
        days[day] = {'day': day, 'total': page['total'], 'items': [compact(e, images, hidden=hidden) for e in page['items']],
                     'featured': [compact(e, images, hidden=hidden) for e in picks], 'featured_ai': ai_pick, 'featured_today': [compact(e, images, hidden=hidden) for e in picks_today], 'highlight': highlight, 'highlight_media': highlight_media, 'expo_rank': ranks_expo, 'districts': catalog.districts(conn, day)}
        _write_json(out / 'data' / 'day' / f'{day}.json', days[day])
    shards, cards = {}, {}
    for e in events:
        detail = details.get(e['key'])
        if detail is None: continue
        # El cartel ya agrupado de todas las fuentes del mismo acto.
        detail['lineup'] = e.get('lineup') or detail.get('lineup') or []
        detail['lineup_times'] = e.get('lineup_times') or detail.get('lineup_times') or []
        public = public_detail(detail, images, hidden)
        shards.setdefault(shard_of(e['key']), {})[e['key']] = public
        cards.setdefault(shard_of(e['key']), {})[e['key']] = share_card({**detail, 'media': public['media'], 'official_page': public.get('official_page')}, today)
    # Fichas que ahora son secundarias de otra (fusión de duplicados, prioridad de la web de la sala, 26-10-2026): su
    # dirección /e/<fuente>/<id>, los enlaces compartidos y los guardados siguen llevando a la ficha que manda.
    aliases = 0
    for e in events:
        for member in e.get('also_in') or []:
            if member == e['key'] or member in shards.get(shard_of(member), {}): continue
            shards.setdefault(shard_of(member), {})[member] = {'alias_of': e['key']}
            card = cards.get(shard_of(e['key']), {}).get(e['key'])
            if card: cards.setdefault(shard_of(member), {})[member] = card
            aliases += 1
    for name, records in shards.items(): _write_json(out / 'data' / 'detail' / f'{name}.json', records)
    translations = write_translations(conn, out, shards)
    # Tarjetas para compartir: las lee la función de /e/* para la vista previa (functions/e/[[path]].js).
    from src.event_status import statuses as _statuses
    keep_past_cards(out, cards, today, gone={f'{s}:{i}' for s, i in _statuses(conn)})
    alerts_new = write_alerts_feed(out, events, today, dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
    for name, records in cards.items(): _write_json(out / 'data' / 'share' / f'{name}.json', records)
    phase('dias_y_tarjetas')
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    counts = {'events': len(events), 'images': images.stats['exported'] + images.stats['reused'], 'days': len(days), 'detail_shards': len(shards), 'translations': translations['traducidas']}
    sources = {s: {'label': catalog.SOURCES.get(s, s), 'attribution': registry_entry(registry, s).get('attribution', ''), 'license_url': registry_entry(registry, s).get('license_url', '')} for s in sorted({e['source'] for e in events}) if registry_entry(registry, s).get('public_credit') is not False}
    _write_json(out / 'data' / 'meta.json', {'generated_at': generated_at, 'today': today.isoformat(), 'horizon_days': HORIZON_DAYS, 'counts': counts, 'sources': sources, 'site_url': site_url.rstrip('/') if site_url else ''})
    # Front end: the same files the local server serves, switched to static mode.
    index = (Path(static_dir) / 'index.html').read_text(encoding='utf-8').replace('<html lang="es"', '<html lang="es" data-static="1"', 1)
    if site_url: index = index.replace('</head>', f'<link rel="canonical" href="{html.escape(site_url.rstrip("/"))}/"></head>', 1)
    for name in STATIC_FILES:
        (out / name).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(Path(static_dir) / name, out / name)
    # Browsers keep /public.js and /public.css across deploys unless their address
    # changes: the shell references them by content version, so a new app is seen
    # on the next load, while the shell itself is always revalidated (_headers).
    versions = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()[:10] for name in ('public.css', 'public.js', 'public-v2.css')}
    for name in ('public.css', 'public.js'):
        index = index.replace(f'"/{name}"', f'"/{name}?v={versions[name]}"')
    if PUBLIC_SKIN == 'v2': index = v2_index(index, versions['public-v2.css'])
    # Avisos por correo (alertas/): el botón solo aparece con alerts.enabled y la clave pública de Turnstile
    # (config/automation.json, trabajo publicar-web). Apagado mientras no estén la privacidad y las claves.
    alerts = alerts or {}
    if alerts.get('enabled') and alerts.get('turnstile_site_key'):
        index = index.replace('<html lang="es"', f'<html lang="es" data-alerts="1" data-turnstile="{html.escape(str(alerts["turnstile_site_key"]))}"', 1)
    from src import landings   # las páginas de entrada ya no se enlazan en el pie (25-10-2026); siguen en el sitemap
    (out / 'index.html').write_text(index, encoding='utf-8')
    # Páginas de entrada (/hoy, /fin-de-semana, /con-ninos…): la app con su filtro y la lista en el HTML.
    landing_pages = landings.pages(today)
    for page in landing_pages:
        target = out / landings.file_for(page['path']); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(landings.render(index, page, days, site_url), encoding='utf-8')
    skin = f"/public-v2.css?v={versions['public-v2.css']}" if PUBLIC_SKIN == 'v2' else ''
    (out / 'creditos.html').write_text(credits_html(registry, generated_at, counts, skin_css=skin), encoding='utf-8')
    from src import legal_pages   # Aviso legal y Privacidad (25-10-2026); /privacidad la piden las alertas
    for slug in ('aviso-legal', 'privacidad'):
        (out / f'{slug}.html').write_text(legal_pages.page_html(slug, skin), encoding='utf-8')
    (out / '_headers').write_text(headers_file(), encoding='utf-8')
    # Every record has its own address (/e/<source>/<id>); the static host serves the app for it.
    # /e/* lo sirve la función functions/e/[[path]].js: la app con la vista previa para compartir
    # (título, foto, cuándo y dónde). Una regla de _redirects aquí le quitaría la ruta.
    # /v2/ fue la dirección de prueba de la versión 2: los enlaces antiguos van a la portada
    # (/v2/e/* lo redirige su función, functions/v2/e/[[path]].js).
    (out / '_redirects').write_text('/v2 / 301\n/v2/ / 301\n', encoding='utf-8')
    (out / 'robots.txt').write_text('User-agent: *\nAllow: /\nDisallow: /data/\nDisallow: /cal/\nDisallow: /alertas/\nDisallow: /api/\n' + (f'Sitemap: {site_url.rstrip("/")}/sitemap.xml\n' if site_url else ''), encoding='utf-8')
    write_sitemaps(out, site_url, events, cards, today, [pg['path'] for pg in landing_pages])
    file_count = sum(1 for p in out.rglob('*') if p.is_file())
    # Readiness gate: a thin or empty export must never replace a working site.
    soon = (today + dt.timedelta(days=14)).isoformat()
    upcoming = sum(1 for e in events if e['start'] <= soon)
    blockers = []
    if upcoming < GATE_MIN_EVENTS_14_DAYS: blockers.append(f'Solo {upcoming} fichas públicas en 14 días (mínimo {GATE_MIN_EVENTS_14_DAYS})')
    if not days[today.isoformat()]['items']: blockers.append('El día de hoy no tiene ninguna ficha')
    if file_count > MAX_FILES: blockers.append(f'{file_count} ficheros superan el límite de {MAX_FILES} de Cloudflare Pages')
    return {'status': 'completed' if not blockers else 'blocked', 'blockers': blockers, 'out_dir': str(out), 'generated_at': generated_at, 'today': today.isoformat(),
            'counts': {**counts, 'upcoming_14_days': upcoming, 'files': file_count}, 'images': images.stats, 'links': link_report, 'classification_changes': classification_changes, 'content_hash': _content_hash(out), 'seconds': round(time.monotonic() - started, 1), 'phases': phases}


def deploy(out_dir, command, *, env_file=None, runner=subprocess.run, timeout=1800):
    """Run the configured upload command (for example wrangler) from the project root."""
    env = dict(os.environ)
    env['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '/usr/bin:/bin')
    if env_file and Path(env_file).is_file():
        for line in Path(env_file).read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.strip().startswith('#'):
                k, v = line.split('=', 1); env[k.strip()] = v.strip().strip('"').strip("'")
    result = runner(command, shell=True, cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=timeout)
    tail = ((result.stdout or '') + '\n' + (result.stderr or '')).strip()[-1500:]
    return {'status': 'completed' if result.returncode == 0 else 'failed', 'returncode': result.returncode, 'command': command, 'output_tail': tail}


def last_published_hash(conn, job_name):
    row = conn.execute("SELECT result_json FROM automation_runs WHERE job_name=? AND status='completed' ORDER BY id DESC LIMIT 1", (job_name,)).fetchone()
    if not row: return None
    try: return json.loads(row[0]).get('content_hash')
    except (ValueError, AttributeError): return None


def publish(conn, job, *, media_root=ROOT / 'data' / 'media', runner=subprocess.run, today=None, thumbnailer=None, link_fetcher=None):
    """Export, gate, and deploy only when something changed. Used by the automation engine and --publish."""
    out_dir = ROOT / job.get('out_dir', 'dist')
    # Enlaces externos comprobados antes de publicar (src/link_check.py); «check_links»: false en el job lo desactiva.
    if job.get('check_links', True) and link_fetcher is None:
        from src.link_check import fetch_status as link_fetcher
    elif not job.get('check_links', True): link_fetcher = None
    report = export(conn, out_dir, media_root=media_root, today=today, thumbnailer=thumbnailer, site_url=job.get('site_url', ''), link_fetcher=link_fetcher, alerts=job.get('alerts'))
    report['deploy'] = None
    if report['status'] != 'completed': return report
    command = job.get('deploy_command', '')
    if not command: report['deploy'] = {'status': 'skipped', 'reason': 'deploy_command vacío: solo exportación'}; return report
    if not job.get('force') and last_published_hash(conn, job.get('name', 'publicar-web')) == report['content_hash']:
        report['deploy'] = {'status': 'skipped', 'reason': 'Sin cambios desde la última publicación'}; return report
    report['deploy'] = deploy(out_dir, command, env_file=job.get('env_file') or (ROOT / 'config' / 'publish.env'), runner=runner)
    if report['deploy']['status'] != 'completed': report['status'] = 'failed'
    return report
