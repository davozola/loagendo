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
import sqlite3
import os
import shutil
import subprocess
import time
from pathlib import Path

from mvp import catalog

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / 'docs' / 'source_registry.json'
HORIZON_DAYS = catalog.MAX_RANGE_DAYS
PAGE_SIZE = 50
FEATURED_SIZE = 12
DETAIL_SHARDS = 256
MAX_IMAGES_PER_EVENT = 3
MAX_ASSET_BYTES = 25 * 1024 * 1024  # Cloudflare Pages limit per file
MAX_FILES = 20000                   # Cloudflare Pages limit per deployment
THUMBNAIL_MAX_PX = 1200
GATE_MIN_EVENTS_14_DAYS = 300
STATIC_FILES = ('public.css', 'public.js', 'vendor/leaflet.css', 'vendor/leaflet.js', 'img/hero-light.webp', 'img/hero-light-m.webp', 'img/hero-dark.webp', 'img/hero-dark-m.webp')
PUBLIC_DETAIL_FIELDS = ('source', 'id', 'key', 'title', 'source_label', 'start', 'end', 'kind', 'kind_label', 'format', 'format_label', 'category', 'district',
                        'family_audience', 'has_description', 'summary', 'venue_names', 'coordinates', 'occurrences', 'has_candidate', 'date_precision',
                        'media', 'also_in', 'price_label', 'is_free', 'time', 'time_source', 'time_label', 'public_category', 'url', 'description',
                        'editorial_summary', 'time_text', 'schedule_days', 'schedule_note', 'registration_required', 'price_text', 'venues', 'organizers', 'links', 'link_label', 'confirmations', 'presentation', 'time_conflicts', 'hours_by_day', 'notes_by_day', 'lineup', 'lineup_times', 'channels', 'age_min', 'age_max', 'age_evidence', 'age_source', 'price_source', 'ai_quotes', 'ai_summary', 'venue_upcoming', 'description_credit')
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
    return [json.loads(json.dumps(e)) for e in catalog.all_events(conn) if catalog.is_public(e) and e['end'] >= start and e['start'] <= end]


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
                credit = {'source': source, 'source_label': catalog.SOURCES.get(source, source), 'attribution': entry.get('attribution') or catalog.SOURCES.get(source, source),
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


def compact(event, images, full=True):
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
    if event.get('hours_by_day'): out['hb'] = packed_hours(event)
    if event.get('notes_by_day'): out['nd'] = packed_hours(event, 'notes_by_day')  # actividad de cada día
    if event.get('age_source'): out['ag'] = [event['age_min'], 99 if event.get('age_max') is None else event['age_max']]  # franja de edad
    if event.get('series'): out['se'] = event['series']  # serie que la web agrupa en una fila
    if event.get('lineup'): out['lu'] = event['lineup'][:40]
    if event.get('featured_date'): out['fd'] = event['featured_date']  # para buscar por artista
    if not full: return out
    media = []
    for item in event.get('media', [])[:MAX_IMAGES_PER_EVENT]:
        exported = images.item(item)
        if exported: media.append({'u': exported['url'], 'alt': item.get('alt') or '', 'cr': exported['credit']['attribution'], **({'fb': 1} if item.get('fallback') else {})}); break
    out.update({'sl': event['source_label'], 'c': event['category'], 'su': (event['summary'] or '')[:200], 'pl': event['price_label'] or '', 'm': media, 'u': event['url'] or ''})
    return out


def public_detail(detail, images):
    out = {k: detail.get(k) for k in PUBLIC_DETAIL_FIELDS}
    out['hours_by_day'] = packed_hours(detail)
    out['notes_by_day'] = packed_hours(detail, 'notes_by_day')
    media = []
    for item in detail.get('media', [])[:MAX_IMAGES_PER_EVENT]:
        exported = images.item(item)
        if exported: media.append({'url': exported['url'], 'alt': item.get('alt') or '', 'credit': exported['credit'], **({'fallback': True} if item.get('fallback') else {})})
    out['media'] = media
    out['links'] = [{'label': l['label'], 'url': l['url']} for l in detail.get('links', []) if str(l.get('url', '')).startswith('https://')]
    # Descripción breve con IA: solo con config/ia.json → descripciones_publicas (tras revisar la muestra).
    from src.ai_describe import public_enabled
    if not public_enabled(): out['ai_summary'] = None
    return out


MONTHS_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
DAYS_ES = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']
GENERIC_TIME = {'Varios días', 'Exposición', 'Hora no indicada', ''}


def share_card(detail, today):
    """Lo que se ve al compartir el enlace (WhatsApp, Telegram, redes): título, cuándo, dónde,
    una frase de la descripción y la imagen. Solo datos que ya publica la ficha."""
    def day(d):
        x = dt.date.fromisoformat(d); return f"{DAYS_ES[x.weekday()]} {x.day} {MONTHS_ES[x.month - 1]}"
    start, end = detail.get('start') or '', detail.get('end') or ''
    label = detail.get('time_label') or ''
    hours = '' if label in GENERIC_TIME else str(label).replace('23:59', 'medianoche')
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
            'ad': ((detail.get('venues') or [{}])[0] or {}).get('address') or ''}


def shard_of(key):
    return hashlib.sha1(key.encode('utf-8')).hexdigest()[:2]


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')


def credits_html(registry, generated_at='', counts=None):
    """The public Fuentes y créditos page: who publishes each dataset, under what terms."""
    rows = []
    for source, entry in registry.items():
        if entry.get('public_credit') is False: continue  # discovery-only directories: facts only, never linked or named in public
        label = catalog.SOURCES.get(source) or {'venue_*': 'Recintos (config/venues.json)', 'ticketing_*': 'Ticketeras y agregadores'}.get(source, source)
        link = f'<a href="{html.escape(entry["catalog_url"])}" rel="noopener noreferrer" target="_blank">{html.escape(entry["catalog_url"])}</a>' if entry.get('catalog_url', '').startswith('https://') else ''
        licence = f'<a href="{html.escape(entry["license_url"])}" rel="noopener noreferrer" target="_blank">{html.escape(entry.get("data_reuse_status", ""))}</a>' if entry.get('license_url', '').startswith('https://') else html.escape(entry.get('data_reuse_status', ''))
        images = 'Sí — ' + html.escape(entry.get('image_reuse_basis', '')) if entry.get('image_reuse_confirmed') is True else 'No se publican imágenes de esta fuente'
        if entry.get('public_listing') is False:
            rows.append(f'<article class="credit credit-retired"><h2>{html.escape(label)}</h2><p><b>Fuente retirada{" el " + html.escape(entry["retired_on"]) if entry.get("retired_on") else ""}.</b> {html.escape(entry.get("public_listing_reason", ""))}</p></article>'); continue
        rows.append(f'<article class="credit"><h2>{html.escape(label)}</h2><p><b>Titular:</b> {html.escape(entry.get("owner", ""))}</p><p><b>Dataset:</b> {html.escape(entry.get("dataset", ""))} {link}</p>'
                    f'<p><b>Licencia / base de reutilización:</b> {licence}. {html.escape(entry.get("license_basis", ""))}</p><p><b>Atribución:</b> {html.escape(entry.get("attribution", ""))}</p><p><b>Imágenes:</b> {images}</p></article>')
    counts = counts or {}
    return ('<!DOCTYPE html><html lang="es" data-theme="dark"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Fuentes y créditos · Brollant</title>'
            '<meta name="description" content="De dónde salen los datos y las imágenes de Brollant, con qué licencia y cómo pedir una corrección o retirada."><link rel="stylesheet" href="/public.css"></head>'
            '<body class="credits-page"><main class="credits"><a class="back" href="/">← Volver a la agenda</a><h1>Fuentes y créditos</h1>'
            '<p>Brollant recoge automáticamente la programación cultural de Barcelona a partir de fuentes públicas y la enlaza siempre a la página oficial de cada actividad. '
            'Los textos descriptivos y las imágenes pertenecen a quien los publica: se muestran con su crédito y su enlace de origen, bajo la licencia o la política de cada fuente que se detalla abajo. '
            'Cada ficha conserva la URL original y la fecha de la última sincronización. Los horarios y precios se reproducen tal y como los publica la fuente; confirma siempre en la fuente antes de ir. '
            'Las fechas de conciertos se contrastan además con directorios de conciertos: esas fichas muestran sólo título, fecha, hora y sala, enlazan a la web de la sala o a la venta de entradas y no reproducen textos ni imágenes de terceros.</p>'
            f'<p class="credits-meta">Última generación: {html.escape(generated_at)}. Fichas públicas en los próximos seis meses: {counts.get("events", "")}. Imágenes publicadas: {counts.get("images", "")}.</p>'
            '<p><b>Retirada o corrección.</b> Si eres titular de un dato o una imagen y quieres que se corrija o se retire, escribe indicando el enlace de la ficha: se atiende en la siguiente actualización y el cambio queda registrado con fecha y motivo.</p>'
            + ''.join(rows) +
            '<p class="credits-meta">Mapa: © colaboradores de <a href="https://www.openstreetmap.org/copyright" rel="noopener noreferrer" target="_blank">OpenStreetMap</a>. Tipografías del sistema. Sin cookies de terceros ni rastreadores.</p>'
            '</main></body></html>')


def headers_file():
    return ('/*\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Referrer-Policy: strict-origin-when-cross-origin\n'
            "  Content-Security-Policy: default-src 'self'; connect-src 'self'; img-src 'self' https://tile.openstreetmap.org; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src https://www.openstreetmap.org; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'\n"
            '/img/*\n  Cache-Control: public, max-age=2592000, immutable\n/data/*\n  Cache-Control: public, max-age=600\n/vendor/*\n  Cache-Control: public, max-age=604800\n/public.js\n  Cache-Control: public, max-age=0, must-revalidate\n/public.css\n  Cache-Control: public, max-age=0, must-revalidate\n/\n  Cache-Control: public, max-age=0, must-revalidate\n/index.html\n  Cache-Control: public, max-age=0, must-revalidate\n/e/*\n  Cache-Control: public, max-age=0, must-revalidate\n')


def _content_hash(out):
    h = hashlib.sha256()
    for path in sorted(p for p in out.rglob('*') if p.is_file()):
        rel = path.relative_to(out).as_posix()
        if rel in ('data/meta.json', 'creditos.html'): continue  # carry the generation timestamp, not content
        if rel.startswith('img/'): h.update(f'{rel}:{path.stat().st_size}\n'.encode())
        else: h.update(rel.encode()); h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def export(conn, out_dir, *, media_root=ROOT / 'data' / 'media', static_dir=ROOT / 'static', today=None, registry_path=REGISTRY_PATH, thumbnailer=None, site_url=''):
    """Write the whole public site into ``out_dir`` and return an audit summary."""
    started = time.monotonic(); today = today or catalog.today(); out = Path(out_dir); registry = _registry(registry_path)
    out.mkdir(parents=True, exist_ok=True)
    for stale in ('data',):
        if (out / stale).exists(): shutil.rmtree(out / stale)
    images = ImageExporter(conn, out, media_root, registry, thumbnailer)
    # Clasificación vigente de todas las fichas (también las pendientes y excluidas): tabla
    # event_classification + historial de cambios tras cada sincronización (src/taxonomy.py).
    from src import taxonomy
    try: classification_changes = taxonomy.record(conn, catalog.all_events(conn))
    except sqlite3.OperationalError: classification_changes = None  # base de solo lectura
    events = public_events(conn, today)
    catalogue = [compact(e, images, full=False) for e in events]
    _write_json(out / 'data' / 'taxonomy.json', taxonomy.public_labels(events))
    _write_json(out / 'data' / 'catalog.json', {'today': today.isoformat(), 'horizon_days': HORIZON_DAYS, 'items': catalogue})
    # One ranked first page per day in the horizon, so the first paint and any
    # day tap work before the catalogue has finished loading.
    days = {}
    for offset in range(HORIZON_DAYS + 1):
        day = (today + dt.timedelta(days=offset)).isoformat()
        page = catalog.query_events(conn, day=day, public=True, page_size=PAGE_SIZE, include_started=False)
        featured = catalog.query_events(conn, day=day, featured=True, public=True, page_size=30)
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
        days[day] = {'day': day, 'total': page['total'], 'items': [compact(e, images) for e in page['items']],
                     'featured': [compact(e, images) for e in picks], 'featured_ai': ai_pick, 'districts': catalog.districts(conn, day)}
        _write_json(out / 'data' / 'day' / f'{day}.json', days[day])
    shards, cards = {}, {}
    for e in events:
        detail = catalog.event_detail(conn, e['source'], e['id'])
        if detail is None: continue
        # El cartel ya agrupado de todas las fuentes del mismo acto.
        detail['lineup'] = e.get('lineup') or detail.get('lineup') or []
        detail['lineup_times'] = e.get('lineup_times') or detail.get('lineup_times') or []
        public = public_detail(detail, images)
        shards.setdefault(shard_of(e['key']), {})[e['key']] = public
        cards.setdefault(shard_of(e['key']), {})[e['key']] = share_card({**detail, 'media': public['media']}, today)
    for name, records in shards.items(): _write_json(out / 'data' / 'detail' / f'{name}.json', records)
    # Tarjetas para compartir: las lee la función de /e/* para la vista previa (functions/e/[[path]].js).
    for name, records in cards.items(): _write_json(out / 'data' / 'share' / f'{name}.json', records)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    counts = {'events': len(events), 'images': images.stats['exported'] + images.stats['reused'], 'days': len(days), 'detail_shards': len(shards)}
    sources = {s: {'label': catalog.SOURCES.get(s, s), 'attribution': registry_entry(registry, s).get('attribution', ''), 'license_url': registry_entry(registry, s).get('license_url', '')} for s in sorted({e['source'] for e in events}) if registry_entry(registry, s).get('public_credit') is not False}
    _write_json(out / 'data' / 'meta.json', {'generated_at': generated_at, 'today': today.isoformat(), 'horizon_days': HORIZON_DAYS, 'counts': counts, 'sources': sources})
    # Front end: the same files the local server serves, switched to static mode.
    index = (Path(static_dir) / 'index.html').read_text(encoding='utf-8').replace('<html lang="es"', '<html lang="es" data-static="1"', 1)
    if site_url: index = index.replace('</head>', f'<link rel="canonical" href="{html.escape(site_url.rstrip("/"))}/"></head>', 1)
    for name in STATIC_FILES:
        (out / name).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(Path(static_dir) / name, out / name)
    # Browsers keep /public.js and /public.css across deploys unless their address
    # changes: the shell references them by content version, so a new app is seen
    # on the next load, while the shell itself is always revalidated (_headers).
    for name in ('public.css', 'public.js'):
        version = hashlib.sha256((out / name).read_bytes()).hexdigest()[:10]
        index = index.replace(f'"/{name}"', f'"/{name}?v={version}"')
    (out / 'index.html').write_text(index, encoding='utf-8')
    (out / 'creditos.html').write_text(credits_html(registry, generated_at, counts), encoding='utf-8')
    (out / '_headers').write_text(headers_file(), encoding='utf-8')
    # Every record has its own address (/e/<source>/<id>); the static host serves the app for it.
    # /e/* lo sirve la función functions/e/[[path]].js: la app con la vista previa para compartir
    # (título, foto, cuándo y dónde). Una regla de _redirects aquí le quitaría la ruta.
    (out / '_redirects').write_text('', encoding='utf-8')
    (out / 'robots.txt').write_text('User-agent: *\nAllow: /\nDisallow: /data/\n' + (f'Sitemap: {site_url.rstrip("/")}/sitemap.xml\n' if site_url else ''), encoding='utf-8')
    base = site_url.rstrip('/') if site_url else ''
    soon_sitemap = (today + dt.timedelta(days=45)).isoformat()
    urls = [f'{base}/', f'{base}/creditos.html'] + [f'{base}/?day={day}' for day in list(days)[:60]] + [f'{base}/e/{e["source"]}/{e["id"]}' for e in events if e['start'] <= soon_sitemap]
    (out / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{html.escape(u)}</loc></url>' for u in urls) + '</urlset>', encoding='utf-8')
    file_count = sum(1 for p in out.rglob('*') if p.is_file())
    # Readiness gate: a thin or empty export must never replace a working site.
    soon = (today + dt.timedelta(days=14)).isoformat()
    upcoming = sum(1 for e in events if e['start'] <= soon)
    blockers = []
    if upcoming < GATE_MIN_EVENTS_14_DAYS: blockers.append(f'Solo {upcoming} fichas públicas en 14 días (mínimo {GATE_MIN_EVENTS_14_DAYS})')
    if not days[today.isoformat()]['items']: blockers.append('El día de hoy no tiene ninguna ficha')
    if file_count > MAX_FILES: blockers.append(f'{file_count} ficheros superan el límite de {MAX_FILES} de Cloudflare Pages')
    return {'status': 'completed' if not blockers else 'blocked', 'blockers': blockers, 'out_dir': str(out), 'generated_at': generated_at, 'today': today.isoformat(),
            'counts': {**counts, 'upcoming_14_days': upcoming, 'files': file_count}, 'images': images.stats, 'classification_changes': classification_changes, 'content_hash': _content_hash(out), 'seconds': round(time.monotonic() - started, 1)}


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


def publish(conn, job, *, media_root=ROOT / 'data' / 'media', runner=subprocess.run, today=None, thumbnailer=None):
    """Export, gate, and deploy only when something changed. Used by the automation engine and --publish."""
    out_dir = ROOT / job.get('out_dir', 'dist')
    report = export(conn, out_dir, media_root=media_root, today=today, thumbnailer=thumbnailer, site_url=job.get('site_url', ''))
    report['deploy'] = None
    if report['status'] != 'completed': return report
    command = job.get('deploy_command', '')
    if not command: report['deploy'] = {'status': 'skipped', 'reason': 'deploy_command vacío: solo exportación'}; return report
    if not job.get('force') and last_published_hash(conn, job.get('name', 'publicar-web')) == report['content_hash']:
        report['deploy'] = {'status': 'skipped', 'reason': 'Sin cambios desde la última publicación'}; return report
    report['deploy'] = deploy(out_dir, command, env_file=job.get('env_file') or (ROOT / 'config' / 'publish.env'), runner=runner)
    if report['deploy']['status'] != 'completed': report['status'] = 'failed'
    return report
