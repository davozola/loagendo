"""Ticketmaster Discovery API v2: todos los eventos de Barcelona con sus datos.

Sustituye a la lectura del JSON-LD de la página de ciudad de Ticketmaster
(`venue_ticketmaster_es`), que solo daba la veintena de eventos de esa página.
Los registros usan la misma fuente y el mismo identificador (sala/URL/fecha),
así que todo lo que el catálogo ya hace con las ticketeras (categoría por
tipo, enlace a la compra, agrupación con la fuente primaria) sigue igual.

Condiciones (revisadas el 18-10-2026, developer.ticketmaster.com):
- 5.000 llamadas al día y unas 2-5 por segundo; no se puede pedir más allá
  del resultado 1.000 de una búsqueda (``size * page < 1000``): se pide por
  tramos de fechas y un tramo con más de 1.000 eventos se parte en dos.
- Solo se puede guardar el contenido «durante periodos razonables»: por
  decisión de David (18-10-2026) los eventos de Ticketmaster ya pasados se
  borran de la base (excepción explícita a la regla de no borrar).
- La clave va en ``TICKETMASTER_API_KEY`` (entorno o ``.env``) y nunca se
  guarda en la base ni en los registros de sincronización.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.network import tls_context

ROOT = Path(__file__).resolve().parents[1]
SLUG = "ticketmaster_es"
SOURCE = "venue_" + SLUG
ENDPOINT = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200          # máximo que admite la API
DEEP_PAGING_LIMIT = 1000  # size * page < 1000
HORIZON_DAYS = 180
PAUSE_SECONDS = 0.6       # ~2 peticiones por segundo, el límite más bajo publicado
MAX_CALLS_PER_RUN = 400   # muy por debajo de las 5.000 diarias
SLOT_THRESHOLD = 10       # más pases que esto con el mismo nombre y recinto = producto por franjas
USER_AGENT = "Ontoca/1.4 (+https://ontoca.com; hola@ontoca.com) Ticketmaster Discovery API"

# Por identificador: con locale=es los nombres llegan traducidos («Música»,
# «Arte y Teatro»), así que el nombre solo sirve de respaldo (en ambos idiomas).
SEGMENT_TYPE = {"KZFzniwnSyZfZ7v7nJ": "MusicEvent", "KZFzniwnSyZfZ7v7na": "TheaterEvent", "KZFzniwnSyZfZ7v7nE": "SportsEvent", "KZFzniwnSyZfZ7v7nn": "ScreeningEvent",
                "Music": "MusicEvent", "Música": "MusicEvent", "Arts & Theatre": "TheaterEvent", "Arte y Teatro": "TheaterEvent",
                "Sports": "SportsEvent", "Deportes": "SportsEvent", "Film": "ScreeningEvent", "Cine": "ScreeningEvent"}
GENRE_TYPE = {"KnvZfZ7vAe1": "ComedyEvent", "KnvZfZ7v7nI": "DanceEvent", "Comedy": "ComedyEvent", "Comedia": "ComedyEvent", "Dance": "DanceEvent", "Danza": "DanceEvent",
              "Children's Theatre": "ChildrensEvent", "Teatro infantil": "ChildrensEvent", "Family": "ChildrensEvent", "Familia": "ChildrensEvent",
              "Fine Art": "VisualArtsEvent", "Bellas Artes": "VisualArtsEvent", "Literary": "LiteraryEvent"}
# Productos que no son un evento: mejoras de entrada, aparcamiento, paquetes.
NOT_AN_EVENT = re.compile(r"^\s*test\s+\d{5,}\b|^\s*upgrade\b|meet\s*(?:&|and|y)\s*greet|\bparking\b|aparcamiento|vip\s+package|paquete\s+vip|hospitality", re.I)
STATUS_TYPE = {"cancelled": "https://schema.org/EventCancelled", "canceled": "https://schema.org/EventCancelled",
               "postponed": "https://schema.org/EventPostponed", "rescheduled": "https://schema.org/EventRescheduled"}


class KeyRejected(RuntimeError):
    """La API no acepta la clave: se para la sincronización."""


def load_key(env_path=None):
    if os.environ.get("TICKETMASTER_API_KEY"): return os.environ["TICKETMASTER_API_KEY"].strip()
    path = Path(env_path) if env_path else ROOT / ".env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "TICKETMASTER_API_KEY": return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def http_get(params, timeout=20):
    """GET a la Discovery API. Devuelve el JSON; reintenta un 429 con espera."""
    url = ENDPOINT + "?" + urlencode(params)
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}), timeout=timeout, context=tls_context()) as response:  # nosec B310: endpoint fijo HTTPS
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code in (401, 403): raise KeyRejected("HTTP %s: la API no acepta la clave" % error.code) from None
            if error.code != 429 or attempt == 3: raise RuntimeError("HTTP %s en la Discovery API" % error.code) from None
            time.sleep(2 ** attempt)


def _stamp(day):
    return day.strftime("%Y-%m-%dT00:00:00Z")


def fetch_window(key, start, end, getter=http_get, pause=PAUSE_SECONDS, budget=None):
    """Eventos de Barcelona entre ``start`` y ``end`` (fechas). Parte el tramo si
    tiene más eventos de los que la API deja recorrer. Devuelve (eventos, llamadas)."""
    budget = budget if budget is not None else [MAX_CALLS_PER_RUN]
    events, calls, page = [], 0, 0
    while True:
        if budget[0] <= 0: raise RuntimeError("Límite de llamadas por pasada alcanzado (%s)" % MAX_CALLS_PER_RUN)
        params = {"apikey": key, "countryCode": "ES", "city": "Barcelona", "locale": "es,*", "size": PAGE_SIZE, "page": page,
                  "sort": "date,asc", "startDateTime": _stamp(start), "endDateTime": _stamp(end)}
        if calls or page: time.sleep(pause)
        body = getter(params); calls += 1; budget[0] -= 1
        info = body.get("page") or {}
        total = int(info.get("totalElements") or 0)
        if page == 0 and total > DEEP_PAGING_LIMIT and (end - start).days > 1:
            middle = start + dt.timedelta(days=(end - start).days // 2)
            first, a = fetch_window(key, start, middle, getter, pause, budget)
            second, b = fetch_window(key, middle, end, getter, pause, budget)
            return first + second, calls + a + b
        events.extend((body.get("_embedded") or {}).get("events") or [])
        page += 1
        if page >= int(info.get("totalPages") or 0) or (page + 1) * PAGE_SIZE > DEEP_PAGING_LIMIT:
            return events, calls


def _best_image(images):
    usable = [i for i in images or [] if isinstance(i, dict) and str(i.get("url", "")).startswith("https://")]
    usable.sort(key=lambda i: (bool(i.get("fallback")), i.get("ratio") != "16_9", -int(i.get("width") or 0)))
    return usable[0] if usable else None


def _primary(classifications):
    items = [c for c in classifications or [] if isinstance(c, dict)]
    return next((c for c in items if c.get("primary")), items[0] if items else {})


def _name(value):
    name = (value or {}).get("name") if isinstance(value, dict) else ""
    return "" if not name or name in ("Undefined", "Indefinido") else str(name)


def event_node(event):
    """Un evento de la API en forma de schema.org/Event, para reutilizar el
    mismo normalizador que el resto de ticketeras y salas."""
    dates = event.get("dates") or {}
    start = dates.get("start") or {}
    end = dates.get("end") or {}
    local_date = start.get("localDate") or ""
    timed = start.get("localTime") and not (start.get("timeTBA") or start.get("noSpecificTime") or start.get("dateTBD"))
    venues = (event.get("_embedded") or {}).get("venues") or []
    venue = venues[0] if venues else {}
    address = {"streetAddress": (venue.get("address") or {}).get("line1", ""), "postalCode": venue.get("postalCode", ""),
               "addressLocality": (venue.get("city") or {}).get("name", "")}
    geo = venue.get("location") or {}
    location = {"@type": "Place", "name": venue.get("name", ""), "address": address}
    if geo.get("latitude") and geo.get("longitude"): location["geo"] = {"latitude": geo["latitude"], "longitude": geo["longitude"]}
    primary = _primary(event.get("classifications"))
    segment, genre = primary.get("segment") or {}, primary.get("genre") or {}
    kind = (GENRE_TYPE.get(genre.get("id")) or GENRE_TYPE.get(_name(genre)) or SEGMENT_TYPE.get(segment.get("id")) or SEGMENT_TYPE.get(_name(segment)) or "Event")
    node = {"@type": kind, "name": event.get("name", ""), "url": event.get("url", ""),
            "startDate": local_date + ("T" + str(start["localTime"])[:8] if timed else ""),
            "location": location, "description": "\n\n".join(x for x in (event.get("info"), event.get("pleaseNote")) if x)}
    if end.get("localDate"): node["endDate"] = end["localDate"] + ("T" + str(end["localTime"])[:8] if end.get("localTime") else "")
    status = STATUS_TYPE.get(str((dates.get("status") or {}).get("code") or "").casefold())
    if status: node["eventStatus"] = status
    prices = [p for p in event.get("priceRanges") or [] if isinstance(p, dict) and p.get("min") is not None]
    if prices:
        tidy = lambda v: int(v) if float(v).is_integer() else round(float(v), 2)  # 35.0 → 35
        low, high = tidy(min(p["min"] for p in prices)), tidy(max(p.get("max", p["min"]) for p in prices))
        node["offers"] = {"@type": "AggregateOffer", "url": event.get("url", ""), "priceCurrency": prices[0].get("currency", ""),
                          **({"lowPrice": low, "highPrice": high} if high != low else {"price": low})}
    elif event.get("url"):
        node["offers"] = {"@type": "Offer", "url": event["url"]}
    image = _best_image(event.get("images"))
    if image: node["image"] = image["url"]
    attractions = (event.get("_embedded") or {}).get("attractions") or []
    if attractions: node["performer"] = [{"@type": "PerformingGroup", "name": a.get("name", "")} for a in attractions if a.get("name")]
    promoter = event.get("promoter") or {}
    if promoter.get("name"): node["organizer"] = {"@type": "Organization", "name": promoter["name"]}
    return node


def extra_facts(event):
    """Lo que la API da y el formato schema.org no recoge: se guarda tal cual."""
    primary = _primary(event.get("classifications"))
    sales = event.get("sales") or {}
    facts = {
        "ticketmaster_id": event.get("id", ""),
        "classification": {k: _name(primary.get(k)) for k in ("segment", "genre", "subGenre", "type", "subType") if _name(primary.get(k))},
        "family": bool(primary.get("family")),
        "status": str(((event.get("dates") or {}).get("status") or {}).get("code") or ""),
        "time_tba": bool(((event.get("dates") or {}).get("start") or {}).get("timeTBA") or ((event.get("dates") or {}).get("start") or {}).get("noSpecificTime")),
        "public_sale": {k: v for k, v in (sales.get("public") or {}).items() if k in ("startDateTime", "endDateTime", "startTBD")},
        "presales": [{k: p.get(k) for k in ("name", "startDateTime", "endDateTime")} for p in sales.get("presales") or [] if isinstance(p, dict)],
        "price_ranges": event.get("priceRanges") or [],
        "age_restrictions": event.get("ageRestrictions") or {},
        "accessibility": (event.get("accessibility") or {}).get("info", ""),
        "ticket_limit": (event.get("ticketLimit") or {}).get("info", ""),
        "seatmap": (event.get("seatmap") or {}).get("staticUrl", ""),
        "venue_ticketmaster_id": (((event.get("_embedded") or {}).get("venues") or [{}])[0]).get("id", ""),
        "attractions": [{"name": a.get("name", ""), "id": a.get("id", ""), "url": a.get("url", "")} for a in (event.get("_embedded") or {}).get("attractions") or []],
    }
    return {k: v for k, v in facts.items() if v not in ("", [], {}, None)}


def collapse_slots(events, threshold=SLOT_THRESHOLD):
    """Universe (plataforma de Ticketmaster) vende atracciones por franjas
    horarias: el 18-10-2026, 1.801 de los 1.916 «eventos» de Barcelona eran
    pases de un mismo museo. Cada producto así se queda en un solo registro
    de su primer a su último día, sin hora; los conciertos no se tocan."""
    groups = {}
    for e in events:
        venue = (((e.get("_embedded") or {}).get("venues") or [{}])[0]).get("id") or ""
        groups.setdefault((e.get("name", ""), venue), []).append(e)
    out = []
    for items in groups.values():
        if len(items) <= threshold:
            out.extend(items); continue
        days = sorted(((i.get("dates") or {}).get("start") or {}).get("localDate") or "" for i in items)
        days = [d for d in days if d]
        first = json.loads(json.dumps(items[0]))
        first["dates"] = {**(first.get("dates") or {}), "start": {"localDate": days[0], "noSpecificTime": True}, "end": {"localDate": days[-1]}}
        first["loagendo_collapsed_slots"] = len(items)
        out.append(first)
    return out


def record_from_event(event, venue):
    from src.venue_feeds import record_from_jsonld
    node = event_node(event)
    record = record_from_jsonld(venue, node, event.get("url") or "https://www.ticketmaster.es/")
    if record is None: return None
    record["raw"]["api_event"] = event
    record["raw"]["loagendo"]["ticketmaster"] = extra_facts(event)
    record["raw"]["loagendo"]["source_label"] = venue["name"] + " · ticketera"
    record["alerts"] = [a for a in record["alerts"] if a != "VENUE_SCHEMA_ORG_EVENT"] + ["TICKETMASTER_DISCOVERY_API"]
    if extra_facts(event).get("time_tba"): record["alerts"].append("TIME_TO_BE_ANNOUNCED")
    if event.get("loagendo_collapsed_slots"):
        record["alerts"].append("TIME_SLOT_PRODUCT_COLLAPSED")
        record["raw"]["loagendo"]["ticketmaster"]["collapsed_slots"] = event["loagendo_collapsed_slots"]
    record["evidence_level"] = "ticketing_api_unverified"
    record["time_evidence_field"] = "dates.start.localTime"
    # Sin hora de inicio («timeTBA») pero con apertura de puertas: se da como tal, nunca como inicio.
    doors = ((event.get("dates") or {}).get("access") or {}).get("startDateTime")
    if not record.get("time_text") and doors:
        from zoneinfo import ZoneInfo
        try: local = dt.datetime.fromisoformat(str(doors).replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Madrid"))
        except ValueError: local = None
        if local and local.date().isoformat() == record["start"]:
            label = f"{local:%H:%M} (apertura de puertas)"
            record["time_text"] = label; record["raw"].setdefault("normalized", {})["time_text"] = label
            record["time_evidence_field"] = "dates.access.startDateTime"
    return record


def images_of(event, limit=3):
    """Hasta tres imágenes distintas (la mejor de cada proporción)."""
    out, seen = [], set()
    for image in sorted([i for i in event.get("images") or [] if isinstance(i, dict) and str(i.get("url", "")).startswith("https://") and not i.get("fallback")],
                        key=lambda i: -int(i.get("width") or 0)):
        if image.get("ratio") in seen: continue
        seen.add(image.get("ratio")); out.append(image["url"])
        if len(out) == limit: break
    return out


# Tablas con datos de un registro: al borrar un evento pasado no queda nada de él.
RECORD_TABLES = ("source_venues", "source_organizers", "review_flags", "candidate_occurrences", "publication_approved", "editorial_reviews",
                 "editorial_review_log", "field_verifications", "field_verification_log", "publication_decisions", "source_enrichments",
                 "curated_picks", "source_detail_facts", "listing_projections")


def delete_past(conn, today=None, source=SOURCE):
    """Borra los eventos ya terminados de una ticketera (y sus imágenes locales).
    Solo para fuentes cuyas condiciones piden no guardar más de lo razonable."""
    today = (today or dt.date.today()).isoformat()
    ids = [r[0] for r in conn.execute("SELECT id FROM source_records WHERE source=? AND end_date<?", (source, today))]
    if not ids: return 0
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    with conn:
        for chunk in (ids[i:i + 500] for i in range(0, len(ids), 500)):
            marks = ",".join("?" for _ in chunk)
            if "media_assets" in tables:
                for (path,) in conn.execute(f"SELECT local_path FROM media_assets WHERE source=? AND id IN ({marks}) AND local_path IS NOT NULL", (source, *chunk)):
                    try: Path(path).unlink(missing_ok=True)
                    except OSError: pass
                conn.execute(f"DELETE FROM media_assets WHERE source=? AND id IN ({marks})", (source, *chunk))
            for table in RECORD_TABLES:
                if table in tables: conn.execute(f"DELETE FROM {table} WHERE source=? AND id IN ({marks})", (source, *chunk))
            if "source_record_versions" in tables: conn.execute(f"DELETE FROM source_record_versions WHERE source=? AND external_id IN ({marks})", (source, *chunk))
            if "editorial_review_invalidations" in tables: conn.execute(f"DELETE FROM editorial_review_invalidations WHERE source=? AND record_id IN ({marks})", (source, *chunk))
            conn.execute(f"DELETE FROM source_records WHERE source=? AND id IN ({marks})", (source, *chunk))
    return len(ids)


def sync(conn, key=None, getter=http_get, today=None, pause=PAUSE_SECONDS, horizon_days=HORIZON_DAYS):
    """Descarga los eventos de Barcelona de los próximos ``horizon_days`` días."""
    from src.media import register
    from src.sync import _upsert_record, initialize, now_utc
    from src.venue_feeds import load_venues
    from mvp.catalog import initialize as initialize_catalog
    key = key if key is not None else load_key()
    if not key:
        return {"status": "skipped", "source": SOURCE, "reason": "Falta TICKETMASTER_API_KEY en .env"}
    initialize(conn); initialize_catalog(conn)
    venue = next((v for v in load_venues() if v.get("slug") == SLUG), {"slug": SLUG, "name": "Ticketmaster España", "type": "ticketing"})
    today = today or dt.date.today()
    with conn:
        run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (SOURCE, now_utc(), "running", "0")).lastrowid
    try:
        events, calls = fetch_window(key, today, today + dt.timedelta(days=horizon_days), getter, pause)
        events = collapse_slots([e for e in events if not e.get("test") and not NOT_AN_EVENT.search(str(e.get("name") or ""))])
        records, seen = [], set()
        for event in events:
            record = record_from_event(event, venue)
            if record and record["id"] not in seen:
                seen.add(record["id"]); records.append((record, event))
        mutated = images = 0
        with conn:
            for record, event in records:
                mutated += int(_upsert_record(conn, run_id, record)[0])
                for url in images_of(event):
                    register(conn, SOURCE, record["id"], url, alt=record["title"], credit=venue["name"]); images += 1
        deleted = delete_past(conn, today)
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_rejected=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now_utc(), calls, len(events), len(events) - len(records), mutated, json.dumps(["PAST_EVENTS_DELETED:%d" % deleted]), run_id))
        return {"id": run_id, "source": SOURCE, "status": "completed", "api_calls": calls, "rows_received": len(events), "records": len(records),
                "rows_mutated": mutated, "image_references": images, "past_events_deleted": deleted}
    except Exception as error:
        message = str(error).replace(key, "***") if key else str(error)
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',error=? WHERE id=?", (now_utc(), message[:1000], run_id))
        return {"id": run_id, "source": SOURCE, "status": "failed", "error": message}
