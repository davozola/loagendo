"""Xceed (ticketera de ocio nocturno): «Open Event API», sin clave.

Probada el 18-10-2026: ``events.xceed.me/v1/events?cities=barcelona`` (filtro
por ciudad que funciona aunque no está documentado), detalle con texto en
castellano (``?lang=es``) y entradas con precio en ``offer.xceed.me``. Xceed no
publica términos de uso; su documentación solo pide un uso responsable, así
que las pausas son generosas y se hacen pocas llamadas.

Filtro exigente (config/xceed.json): solo recintos de una lista blanca; los
recintos nuevos quedan fuera hasta que David los añade. Como en Ticketmaster,
los eventos ya pasados se borran (decisión de David, 18-10-2026).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.network import tls_context

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "xceed.json"
SLUG = "xceed"
SOURCE = "venue_" + SLUG
EVENTS = "https://events.xceed.me/v1/events"
OFFERS = "https://offer.xceed.me/v1/events/{id}/admissions"
EVENT_PAGE = "https://xceed.me/es/barcelona/event/{slug}/{legacy}"
MADRID = ZoneInfo("Europe/Madrid")
PAGE = 100
HORIZON_DAYS = 180
PAUSE_SECONDS = 0.5
USER_AGENT = "Brollant/1.3 (+https://brollant.com) agenda cultural de Barcelona"


def load_config(path=CONFIG_PATH):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {"allowed_venues": {}, "deny_title_patterns": []}


def http_get(url, params=None, timeout=20):
    full = url + ("?" + urlencode(params) if params else "")
    for attempt in range(3):
        try:
            with urlopen(Request(full, headers={"Accept": "application/json", "User-Agent": USER_AGENT}), timeout=timeout, context=tls_context()) as response:  # nosec B310: dominios fijos HTTPS
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code not in (429, 502, 503, 504) or attempt == 2: raise RuntimeError("HTTP %s en %s" % (error.code, url)) from None
            time.sleep(2 ** (attempt + 1))


def fetch_events(getter=http_get, today=None, pause=PAUSE_SECONDS, horizon_days=HORIZON_DAYS):
    today = today or dt.date.today()
    start = int(dt.datetime.combine(today, dt.time(), MADRID).timestamp())
    end = int(dt.datetime.combine(today + dt.timedelta(days=horizon_days), dt.time(), MADRID).timestamp())
    events, calls = [], 0
    for offset in range(0, 5000, PAGE):
        if calls: time.sleep(pause)
        body = getter(EVENTS, {"cities": "barcelona", "limit": PAGE, "offset": offset, "startTime": start, "endTime": end}); calls += 1
        page = body.get("data") or []
        events.extend(page)
        if len(page) < PAGE: break
    return events, calls


def allowed(event, config):
    """(True, '') o (False, motivo). Recinto en lista blanca y título limpio."""
    venue = event.get("venue") or {}
    if ((venue.get("city") or {}).get("slug") or "") != "barcelona": return False, "fuera de Barcelona"
    if event.get("venueIsSecret"): return False, "recinto secreto"
    if venue.get("slug") not in (config.get("allowed_venues") or {}): return False, "recinto no admitido: %s" % (venue.get("slug") or "?")
    title = str(event.get("name") or "")
    for pattern in config.get("deny_title_patterns") or []:
        if re.search(pattern, title, re.I): return False, "título excluido: %s" % pattern
    return True, ""


def _local(ts):
    return dt.datetime.fromtimestamp(int(ts), MADRID) if ts else None


def offers_summary(admissions):
    """Entradas a la venta → texto de precio ('15–25 EUR') y detalle archivado."""
    tickets = [t for t in ((admissions or {}).get("ticket") or []) if isinstance(t, dict)]
    rows = [{"name": t.get("name", ""), "price": (t.get("price") or {}).get("amount"), "currency": (t.get("price") or {}).get("currency", ""),
             "fee": (t.get("commissions") or {}).get("transactionFee"), "status": t.get("status", ""),
             "sold_out": bool((t.get("salesStatus") or {}).get("isSoldOut")), "closed": bool((t.get("salesStatus") or {}).get("isSalesClosed"))} for t in tickets]
    live = [r for r in rows if r["price"] is not None and not r["sold_out"] and not r["closed"] and r["status"] in ("on_sale", "")]
    if not live: return "", rows
    tidy = lambda v: int(v) if float(v).is_integer() else round(float(v), 2)
    low, high, currency = tidy(min(r["price"] for r in live)), tidy(max(r["price"] for r in live)), live[0]["currency"]
    if high == 0: return "Gratis", rows
    return (f"{low}–{high} {currency}" if low != high else f"{low} {currency}"), rows


def event_node(event, detail=None):
    detail = detail or {}
    venue = event.get("venue") or {}
    start, end = _local(event.get("startingTime")), _local(event.get("endingTime"))
    coords = venue.get("coordinates") or {}
    node = {"@type": "Festival" if detail.get("isFestival") else "MusicEvent", "name": event.get("name", ""),
            "url": EVENT_PAGE.format(slug=event.get("slug", ""), legacy=event.get("legacyId", "")),
            "startDate": start.strftime("%Y-%m-%dT%H:%M:%S") if start else "",
            "location": {"@type": "Place", "name": venue.get("name", ""), "address": {"streetAddress": venue.get("address", ""), "addressLocality": "Barcelona"}},
            "description": str(detail.get("about") or "")}
    if coords.get("latitude") is not None: node["location"]["geo"] = {"latitude": coords["latitude"], "longitude": coords.get("longitude")}
    # Una sesión de noche que acaba de madrugada sigue siendo del día en que empieza.
    if end and start and (end.date() - start.date()).days > 1: node["endDate"] = end.strftime("%Y-%m-%dT%H:%M:%S")
    lineup = [a.get("name") for a in event.get("lineup") or [] if a.get("name") and not a.get("isGeneric")]
    if lineup: node["performer"] = [{"@type": "MusicGroup", "name": n} for n in lineup]
    company = (detail.get("company") or {}).get("name") if isinstance(detail.get("company"), dict) else ""
    if company: node["organizer"] = {"@type": "Organization", "name": company}
    if event.get("coverUrl"): node["image"] = event["coverUrl"]
    return node


def record_from_event(event, venue_entry, detail=None, admissions=None):
    from src.venue_feeds import record_from_jsonld
    node = event_node(event, detail)
    price_text, tickets = offers_summary(admissions)
    if price_text: node["offers"] = {"@type": "Offer", "url": node["url"], **({"price": 0} if price_text == "Gratis" else {})}
    record = record_from_jsonld(venue_entry, node, node["url"])
    if record is None: return None
    if price_text: record["price_text"] = price_text
    detail = detail or {}
    record["raw"]["api_event"] = event
    record["raw"]["api_detail"] = detail
    record["raw"]["loagendo"]["source_label"] = venue_entry["name"] + " · ticketera"
    record["raw"]["loagendo"]["tickets_url"] = node["url"]
    record["raw"]["loagendo"]["xceed"] = {k: v for k, v in {
        "id": event.get("id"), "legacy_id": event.get("legacyId"), "venue_slug": (event.get("venue") or {}).get("slug"),
        "genres": [g.get("name") for g in event.get("musicGenres") or [] if g.get("name")],
        "lineup": [a.get("name") for a in event.get("lineup") or [] if a.get("name")],
        "ends_at": _local(event.get("endingTime")).isoformat() if event.get("endingTime") else "",
        "doors_open": _local(detail.get("doorsOpening")).isoformat() if detail.get("doorsOpening") else "",
        "age_policy": detail.get("agePolicy"), "dress_code": detail.get("dressCode"), "vibes": detail.get("vibes"),
        "policy_text": detail.get("policyText"), "tickets": tickets, "festival": detail.get("isFestival")}.items() if v not in (None, "", [], {})}
    record["alerts"] = [a for a in record["alerts"] if a != "VENUE_SCHEMA_ORG_EVENT"] + ["XCEED_OPEN_EVENT_API"]
    if not price_text and "NO_PRICE_TEXT" not in record["alerts"]: record["alerts"].append("NO_PRICE_TEXT")
    if price_text and "NO_PRICE_TEXT" in record["alerts"]: record["alerts"].remove("NO_PRICE_TEXT")
    record["evidence_level"] = "ticketing_api_unverified"
    record["time_evidence_field"] = "startingTime"
    return record


def sync(conn, getter=http_get, today=None, pause=PAUSE_SECONDS, config=None):
    from src.media import register
    from src.sync import _upsert_record, initialize, now_utc
    from src.ticketmaster_api import delete_past
    from src.venue_feeds import load_venues
    from mvp.catalog import initialize as initialize_catalog
    initialize(conn); initialize_catalog(conn)
    config = config if config is not None else load_config()
    venue_entry = next((v for v in load_venues() if v.get("slug") == SLUG), {"slug": SLUG, "name": "Xceed", "type": "ticketing"})
    today = today or dt.date.today()
    with conn:
        run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (SOURCE, now_utc(), "running", "0")).lastrowid
    try:
        events, calls = fetch_events(getter, today, pause)
        kept, rejected = [], {}
        for event in events:
            ok, reason = allowed(event, config)
            if ok: kept.append(event)
            else: rejected[reason] = rejected.get(reason, 0) + 1
        records = []
        for event in kept:
            detail = admissions = None
            try:
                time.sleep(pause); detail = (getter(EVENTS + "/" + str(event["id"]), {"lang": "es"}) or {}).get("data"); calls += 1
                time.sleep(pause); admissions = (getter(OFFERS.format(id=event["id"]), {"lang": "es"}) or {}).get("data"); calls += 1
            except Exception:
                pass  # el listado basta: fecha, hora, recinto y cartel
            record = record_from_event(event, venue_entry, detail, admissions)
            if record: records.append((record, event))
        mutated = images = 0
        with conn:
            for record, event in records:
                mutated += int(_upsert_record(conn, run_id, record)[0])
                if str(event.get("coverUrl") or "").startswith("https://"):
                    register(conn, SOURCE, record["id"], event["coverUrl"], alt=record["title"], credit=venue_entry["name"]); images += 1
        deleted = delete_past(conn, today, SOURCE)
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_rejected=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now_utc(), calls, len(events), len(events) - len(records), mutated, json.dumps({"rejected": rejected, "past_events_deleted": deleted}, ensure_ascii=False), run_id))
        return {"id": run_id, "source": SOURCE, "status": "completed", "api_calls": calls, "rows_received": len(events), "records": len(records),
                "rows_mutated": mutated, "image_references": images, "past_events_deleted": deleted,
                "rejected": dict(sorted(rejected.items(), key=lambda x: -x[1]))}
    except Exception as error:
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',error=? WHERE id=?", (now_utc(), str(error)[:1000], run_id))
        return {"id": run_id, "source": SOURCE, "status": "failed", "error": str(error)}
