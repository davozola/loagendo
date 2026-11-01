"""Imagen propia para las fichas que no la tienen (1-11-2026): la busca en la página del propio acto.

Muchas fichas de las agendas municipales (GuiaBCN, Open Data BCN) llegan sin imagen y salen con la foto genérica
de la sala. Casi todas enlazan a una página del acto: la web del evento, la página oficial detectada o la ficha de
la fuente en barcelona.cat. Este trabajo mira esas páginas, por orden, con las mismas reglas que las agendas de sala
(src.ai_agenda._image: og:image o twitter:image; si no, la imagen de contenido cuyo texto alternativo o nombre de
fichero coincide con el título). La imagen se registra con el crédito de la web de donde sale.

Salvaguardas: respeta robots.txt; descarta logos e iconos; una imagen que aparece en tres o más páginas distintas
es la genérica del sitio y no se usa; las páginas ya miradas no se vuelven a pedir (caché ai_agenda_images, que
vuelve a mirar cada semana las que no tenían imagen); como mucho «limit» páginas por pasada.

Lee las fichas publicadas (dist/data/detail), así que solo trabaja sobre lo que de verdad está en la web.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
GENERIC_PAGES = 3          # la misma imagen en 3 páginas distintas = imagen por defecto del sitio
LINK_ORDER = ('web del evento', 'web oficial', 'página de la fuente', 'ficha en guiabcn', 'ficha en')
SKIP_HOSTS = re.compile(r'(?:^|\.)(?:instagram\.com|facebook\.com|twitter\.com|x\.com|youtube\.com|tiktok\.com|linkedin\.com|google\.[a-z.]+|goo\.gl|bit\.ly|wa\.me)$', re.I)
# Páginas que se montan con JavaScript y no traen la imagen en el HTML (GuiaBCN: su imagen ya la trae enriquecer-fichas).
NO_IMAGE_HOSTS = {'guia.barcelona.cat'}
SKIP_IMAGE = re.compile(r'logo|icon|sprite|favicon|avatar|placeholder|no-image|noimage|share-default|og-default|default-og|banner-app', re.I)   # «/sites/default/files» (Drupal) sí vale


def candidates(detail):
    """Páginas del acto, en orden de preferencia: web del evento, página oficial, ficha de la fuente."""
    out, seen = [], set()
    def add(url):
        url = str(url or '')
        if not url.startswith('https://') or url in seen: return
        parts = urlsplit(url); host = parts.netloc.lower()
        if SKIP_HOSTS.search(host) or host in NO_IMAGE_HOSTS: return
        # Portada de una web («https://clotcampdelarpa.cat/»): daría la imagen del sitio, no la del acto.
        if not [p for p in parts.path.split('/') if p] and not parts.query: return
        seen.add(url); out.append(url)
    links = [l for l in detail.get('links') or [] if l.get('url')]
    for wanted in LINK_ORDER[:2]:
        for l in links:
            if str(l.get('label') or '').lower().startswith(wanted): add(l['url'])
    add((detail.get('official_page') or {}).get('url'))
    for wanted in LINK_ORDER[2:]:
        for l in links:
            if str(l.get('label') or '').lower().startswith(wanted): add(l['url'])
    add(detail.get('url'))
    return out


def needs_image(detail):
    from src.media import is_site_default
    media = detail.get('media') or []
    own = media and not media[0].get('fallback') and not is_site_default((media[0].get('credit') or {}).get('original_url', ''))
    return 'title' in detail and not own


def _generic(conn, image):
    n = conn.execute("SELECT COUNT(DISTINCT url) FROM ai_agenda_images WHERE image=?", (image,)).fetchone()[0]
    return n >= GENERIC_PAGES


def pending(out_dir, today):
    """Fichas publicadas sin imagen propia, las más próximas primero."""
    rows = []
    for f in glob.glob(str(Path(out_dir) / 'data' / 'detail' / '*.json')):
        try: shard = json.loads(Path(f).read_text(encoding='utf-8'))
        except (OSError, ValueError): continue
        for key, d in shard.items():
            if not needs_image(d): continue
            urls = candidates(d)
            if not urls: continue
            soon = max(str(d.get('start') or ''), today)
            rows.append((soon, key, d, urls))
    # Una dirección que comparten varias fichas es un listado o la web de la sala: su imagen no es la de cada acto.
    # Varias sesiones del mismo acto (misma película en dos días) sí comparten página: se cuentan títulos distintos.
    shared = {}
    for _, _, d, urls in rows:
        for u in urls: shared.setdefault(u, set()).add(' '.join(str(d.get('title') or '').lower().split()))
    rows = [(soon, key, d, [u for u in urls if len(shared[u]) == 1]) for soon, key, d, urls in rows]
    rows = [r for r in rows if r[3]]
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


def run(conn, limit=120, timeout=10, out_dir=None, fetcher=None, today=None):
    from src import ai_agenda
    from src.media import register, source_rights_policy
    from src.venue_feeds import fetch, robots_allows
    fetcher = fetcher or fetch
    ai_agenda.initialize(conn)
    today = (today or dt.date.today()).isoformat()
    out_dir = Path(out_dir or ROOT / 'dist')
    rights = source_rights_policy('venue_web')   # la web del propio acto o de su sala: misma decisión que venue_*
    stats = {'fichas_sin_imagen': 0, 'paginas_pedidas': 0, 'imagenes': 0, 'genericas': 0, 'robots': 0}
    todo = pending(out_dir, today); stats['fichas_sin_imagen'] = len(todo)
    for _, key, d, urls in todo:
        if stats['paginas_pedidas'] >= limit: break
        source, rid = d.get('source'), d.get('id')
        if not source or rid is None: continue
        for url in urls:
            if stats['paginas_pedidas'] >= limit: break
            if fetcher is fetch and not robots_allows(url): stats['robots'] += 1; continue
            image, fetched = ai_agenda._image(conn, url, fetcher, timeout, d.get('title') or '')
            stats['paginas_pedidas'] += int(fetched)
            if not image or SKIP_IMAGE.search(urlsplit(image).path): continue
            if _generic(conn, image): stats['genericas'] += 1; continue
            host = re.sub(r'^www\.', '', urlsplit(url).netloc)
            with conn: register(conn, source, str(rid), image, alt=d.get('title') or '', credit=host, rights_status=rights)
            stats['imagenes'] += 1
            break
    return {'status': 'completed', **stats}
