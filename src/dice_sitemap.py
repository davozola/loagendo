"""DICE: eventos de Barcelona a partir de su sitemap público.

DICE no tiene catálogo abierto (su API de partners solo da a cada promotor
sus propias ventas). Su web sí publica, en cada ficha de evento, un
schema.org/MusicEvent completo: fecha y hora (apertura de puertas), sala con
dirección y coordenadas, artistas, promotor, precio e imágenes. Las fichas se
encuentran en ``dice.fm/sitemaps/sitemap*.xml``; las de Barcelona acaban en
``-barcelona-tickets`` (457 el 18-10-2026).

Condiciones (robots.txt, 18-10-2026): ``Allow: /`` para todos salvo ``/api/``
y una señal de contenido ``search=yes, ai-train=no, use=reference`` (indexar
y enlazar con extractos cortos sí; entrenar IA no). Por eso de la descripción
solo se guarda un extracto corto y la ficha siempre enlaza a DICE para leer
más y comprar. Se respeta robots.txt en cada petición, se pide como mucho
``MAX_PAGES_PER_RUN`` fichas por pasada con pausa entre ellas, y una ficha
ya leída solo se vuelve a pedir cada ``REFRESH_DAYS``. Los eventos ya pasados
se borran, como en las demás ticketeras (decisión de David, 18-10-2026).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time

SLUG = "dice"
SOURCE = "venue_" + SLUG
SITEMAP_INDEX = "https://dice.fm/sitemaps/sitemap.xml"
CITY_SUFFIX = re.compile(r"^https://dice\.fm/event/[a-z0-9]+-[^/?#]*-barcelona-tickets$")
MAX_PAGES_PER_RUN = 200
REFRESH_DAYS = 3
PAUSE_SECONDS = 1.5
EXCERPT_CHARS = 280
# Fichas leídas antes de esta fecha se releen una vez (18-10-2026: cartel completo).
PARSER_SINCE = "2026-10-18T21:00:00+00:00"


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS dice_pages(
      url TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL, fetched_at TEXT NOT NULL DEFAULT '',
      http_status INTEGER, start_date TEXT NOT NULL DEFAULT '', record_id TEXT NOT NULL DEFAULT '')""")


def sitemap_urls(fetcher, pause=PAUSE_SECONDS):
    """URLs de fichas de Barcelona de todos los sitemaps de DICE."""
    status, _, index = fetcher(SITEMAP_INDEX, 30)
    if status != 200: raise RuntimeError("HTTP %s en el índice de sitemaps de DICE" % status)
    urls, maps = [], re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", index)
    for sitemap in maps:
        time.sleep(pause)
        status, _, body = fetcher(sitemap, 60)
        if status != 200: raise RuntimeError("HTTP %s en %s" % (status, sitemap))
        urls.extend(u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body) if CITY_SUFFIX.match(u))
    return sorted(set(urls)), len(maps) + 1


def pages_to_fetch(conn, urls, today, limit=MAX_PAGES_PER_RUN):
    """Primero las nuevas; después las de eventos futuros leídas hace más de
    REFRESH_DAYS. Las de eventos ya pasados no se vuelven a pedir."""
    known = {u: (f, s) for u, f, s in conn.execute("SELECT url,fetched_at,start_date FROM dice_pages")}
    stale_before = max((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=REFRESH_DAYS)).isoformat(timespec="seconds"), PARSER_SINCE)
    new = [u for u in urls if u not in known or not known[u][0]]
    stale = sorted((u for u in urls if u in known and known[u][0] and known[u][0] < stale_before and (not known[u][1] or known[u][1] >= today.isoformat())),
                   key=lambda u: known[u][1] or "9999")
    return (new + stale)[:limit]


def page_lineup(page):
    """Cartel completo de la ficha de DICE (sus datos estructurados solo traen
    los primeros artistas): `initialState.event.lineup` de __NEXT_DATA__, con
    `performing_time` cuando DICE publica la hora de cada artista."""
    m = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page or '', re.S)
    if not m: return [], []
    try:
        props = json.loads(m.group(1)).get('props', {}).get('pageProps', {})
        state = props.get('initialState')
        state = json.loads(state) if isinstance(state, str) else (state or {})
        lineup = ((state.get('event') or {}).get('lineup')) or []
    except (ValueError, AttributeError, TypeError):
        return [], []
    names, times = [], []
    for item in lineup:
        if not isinstance(item, dict) or not item.get('name'): continue
        names.append(str(item['name']))
        when = str(item.get('performing_time') or '')
        hour = re.search(r'T(\d{2}:\d{2})', when) or re.fullmatch(r'(\d{2}:\d{2})(?::\d{2})?', when)
        if hour: times.append({'name': str(item['name']), 'time': hour.group(1), 'raw': when})
    return names, times


def record_from_page(page, url, venue_entry):
    from src.venue_feeds import jsonld_events, record_from_jsonld
    nodes = [n for n in jsonld_events(page) if str(n.get("url") or url).split("?")[0] == url] or jsonld_events(page)[:1]
    if not nodes: return None
    node = dict(nodes[0])
    full = str(node.get("description") or "")
    if len(full) > EXCERPT_CHARS:  # señal de contenido «use=reference»: extracto, no el texto entero
        cut = full[:EXCERPT_CHARS].rsplit(" ", 1)[0].rstrip(" ,.;:")
        node["description"] = cut + "…"
    record = record_from_jsonld(venue_entry, node, url)
    if record is None: return None
    record["raw"]["loagendo"]["source_label"] = venue_entry["name"] + " · ticketera"
    record["raw"]["loagendo"]["tickets_url"] = url
    names, times = page_lineup(page)
    if names: record["raw"]["loagendo"]["performers"] = names[:80]
    record["raw"]["loagendo"]["dice"] = {k: v for k, v in {
        "lineup_times": times[:80], "lineup_total": len(names) or None,
        "door_time": node.get("doorTime"), "end": node.get("endDate"),
        "organizer_url": (node.get("organizer") or {}).get("url") if isinstance(node.get("organizer"), dict) else None,
        "performers": [{"name": p.get("name"), "url": p.get("url")} for p in (node.get("performer") or []) if isinstance(p, dict)],
        "description_truncated": len(full) > EXCERPT_CHARS}.items() if v not in (None, "", [], False)}
    record["raw"]["item"] = node  # el nodo archivado lleva el extracto, no el texto completo
    record["alerts"] = [a for a in record["alerts"] if a != "VENUE_SCHEMA_ORG_EVENT"] + ["DICE_EVENT_PAGE_SCHEMA_ORG"]
    return record


def sync(conn, fetcher=None, today=None, pause=PAUSE_SECONDS, limit=MAX_PAGES_PER_RUN, robots=None):
    from src.media import register
    from src.sync import _upsert_record, initialize as initialize_sync, now_utc
    from src.ticketmaster_api import delete_past
    from src.venue_feeds import fetch, load_venues, robots_allows
    from mvp.catalog import initialize as initialize_catalog
    fetcher = fetcher or fetch
    robots = robots or (robots_allows if fetcher is fetch else (lambda url: True))
    initialize_sync(conn); initialize_catalog(conn); initialize(conn)
    venue_entry = next((v for v in load_venues() if v.get("slug") == SLUG), {"slug": SLUG, "name": "DICE", "type": "ticketing"})
    today = today or dt.date.today()
    with conn:
        run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (SOURCE, now_utc(), "running", "0")).lastrowid
    try:
        if not robots(SITEMAP_INDEX): raise RuntimeError("robots.txt de dice.fm no permite leer el sitemap")
        urls, calls = sitemap_urls(fetcher, pause)
        now = now_utc()
        with conn:
            conn.executemany("INSERT OR IGNORE INTO dice_pages(url,first_seen_at) VALUES(?,?)", [(u, now) for u in urls])
        todo = pages_to_fetch(conn, urls, today, limit)
        mutated = images = failed = skipped = 0; records = 0
        for url in todo:
            if not robots(url): skipped += 1; continue
            time.sleep(pause)
            status, final_url, page = fetcher(url, 25); calls += 1
            record = record_from_page(page, url, venue_entry) if status == 200 else None
            with conn:
                conn.execute("UPDATE dice_pages SET fetched_at=?,http_status=?,start_date=?,record_id=? WHERE url=?",
                             (now_utc(), status, record["start"] if record else "", record["id"] if record else "", url))
                if status != 200: failed += 1; continue
                if record is None: continue
                records += 1
                mutated += int(_upsert_record(conn, run_id, record)[0])
                image = record["raw"].get("image") or ""
                if image.startswith("https://"):
                    register(conn, SOURCE, record["id"], image, alt=record["title"], credit=venue_entry["name"]); images += 1
        deleted = delete_past(conn, today, SOURCE)
        status = "completed" if failed <= max(5, len(todo) // 5) else "failed"
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status=?,http_status=200,pages=?,rows_received=?,rows_rejected=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now_utc(), status, calls, len(urls), len(todo) - records, mutated, json.dumps({"barcelona_urls": len(urls), "http_failures": failed, "robots_skipped": skipped, "past_events_deleted": deleted}), run_id))
        return {"id": run_id, "source": SOURCE, "status": status, "requests": calls, "barcelona_urls": len(urls), "pages_fetched": len(todo),
                "records": records, "rows_received": len(urls), "rows_mutated": mutated, "image_references": images, "http_failures": failed,
                "robots_skipped": skipped, "past_events_deleted": deleted,
                "never_fetched": conn.execute("SELECT COUNT(*) FROM dice_pages WHERE fetched_at=''").fetchone()[0]}
    except Exception as error:
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',error=? WHERE id=?", (now_utc(), str(error)[:1000], run_id))
        return {"id": run_id, "source": SOURCE, "status": "failed", "error": str(error)}
