"""Eventbrite: hora y precio de cada evento ya importado, vía la API oficial.

La búsqueda pública de la API se retiró en febrero de 2020, así que el
descubrimiento sigue siendo el listado público (venue_feeds, venue_eventbrite).
Aquí solo se completa cada evento ya archivado con GET /v3/events/{id}/.

Reglas: no se modifica el registro importado; la hora va a source_enrichments
(como la página oficial de GuiaBCN) y el precio a source_detail_facts, con la
URL consultada, la fecha y el hash de la respuesta. Si la fecha de la API no
coincide con la de la ficha, no se pone hora. El precio solo sale de campos
estructurados (is_free, ticket_availability); nunca de la descripción.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path

from src.network import tls_context

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "venue_eventbrite"
API_URL = "https://www.eventbriteapi.com/v3/events/{id}/?expand=ticket_availability"
PARSER_VERSION = 2  # 2: ids de URLs «-registration-»; reconsulta los 55 que fallaron
RECHECK_DAYS = 3
TZ = "Europe/Madrid"
USER_AGENT = "Brollant/1.3 (+https://brollant.com) eventbrite-api"
# El id es el número final de la ruta /e/…: «…-tickets-123», «…-registration-123» o «/e/123».
EVENT_ID = re.compile(r"/e/(?:[^/?#]*-)?(\d{9,})/?(?:[?#]|$)")


class AccessDenied(RuntimeError):
    """El token no es válido o la API no permite consultar el evento: se para la tanda."""


def load_token(env_path=None):
    if os.environ.get("EVENTBRITE_TOKEN"): return os.environ["EVENTBRITE_TOKEN"].strip()
    path = Path(env_path) if env_path else ROOT / ".env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "EVENTBRITE_TOKEN": return value.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def event_id(url):
    match = EVENT_ID.search(url or "")
    return match.group(1) if match else ""


def fetch_event(eid, token, timeout=20):
    request = urllib.request.Request(API_URL.format(id=eid), headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310: API oficial de Eventbrite
            return response.read(2_000_000).decode("utf-8")
    except urllib.error.HTTPError as err:
        if err.code in (401, 403): raise AccessDenied(f"API de Eventbrite: acceso denegado ({err.code})") from err
        raise


def _local(moment):
    """(fecha, HH:MM) en Europe/Madrid a partir de {'local','timezone','utc'}."""
    if not isinstance(moment, dict) or not moment.get("local"): return "", ""
    if (moment.get("timezone") or TZ) != TZ and moment.get("utc"):
        from zoneinfo import ZoneInfo
        when = dt.datetime.fromisoformat(moment["utc"].replace("Z", "+00:00")).astimezone(ZoneInfo(TZ))
        return when.date().isoformat(), when.strftime("%H:%M")
    local = moment["local"]
    return local[:10], local[11:16]


def _money(value):
    if not isinstance(value, dict) or value.get("major_value") in (None, ""): return None
    try: amount = float(value["major_value"])
    except (TypeError, ValueError): return None
    symbol = {"EUR": "€"}.get(value.get("currency") or "", value.get("currency") or "")
    text = (f"{amount:.0f}" if amount == int(amount) else f"{amount:.2f}").replace(".", ",")
    return amount, f"{text} {symbol}".strip()


def facts_from_event(event, expected_date):
    """Hora (si la fecha coincide) y precio estructurado de una respuesta de la API."""
    start_date, start_time = _local(event.get("start"))
    end_date, end_time = _local(event.get("end"))
    out = {"time": "", "time_text": "", "price_text": "", "price_basis": "", "date_matches": start_date == expected_date,
           "api_start_date": start_date, "event_status": event.get("status") or "", "timezone": (event.get("start") or {}).get("timezone") or ""}
    if out["date_matches"] and start_time:
        out["time"] = start_time
        out["time_text"] = f"{start_time}–{end_time}" if end_time and end_date == start_date and end_time != start_time else start_time
    if event.get("is_free") is True:
        out["price_text"], out["price_basis"] = "Gratis", "eventbrite_api.is_free"
    else:
        availability = event.get("ticket_availability") or {}
        low, high = _money(availability.get("minimum_ticket_price")), _money(availability.get("maximum_ticket_price"))
        if low and high and high[0] > low[0]: out["price_text"] = f"Desde {low[1]}"
        elif low: out["price_text"] = low[1]
        if out["price_text"]: out["price_basis"] = "eventbrite_api.ticket_availability"
    return out


def records_due(conn, today=None, limit=300):
    today = (today or dt.date.today()).isoformat()
    recheck = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec="seconds")
    return conn.execute("""SELECT r.id, r.source_url, r.start_date FROM source_records r
      LEFT JOIN source_enrichments e ON e.source=r.source AND e.id=r.id
      WHERE r.source=? AND r.end_date>=? AND r.source_url LIKE '%eventbrite.%' AND r.eligibility<>'exclude'
        AND (e.id IS NULL OR COALESCE(e.schedule_parser_version,0)<? OR COALESCE(e.schedule_checked_at,'')<?)
      ORDER BY r.start_date, r.id LIMIT ?""", (SOURCE, today, PARSER_VERSION, recheck, limit)).fetchall()


def enrich_eventbrite(conn, limit=300, *, token=None, fetcher=None, today=None, delay_seconds=0.3, timeout=20):
    from src.guia_detail import initialize as init_enrichments
    init_enrichments(conn)
    from src.venue_feeds import exclude_online_events
    online = exclude_online_events(conn)  # barato e idempotente: los eventos en línea no se consultan ni se publican
    token = token if token is not None else load_token()
    if not token: return {"status": "skipped", "reason": "Falta EVENTBRITE_TOKEN en .env"}
    fetch = fetcher or (lambda eid: fetch_event(eid, token, timeout))
    done = failed = timed = priced = mismatched = 0; errors = {}
    for n, (record_id, url, start_date) in enumerate(records_due(conn, today, limit)):
        eid = event_id(url)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            if not eid: raise ValueError("URL sin id de evento")
            if n and not fetcher: time.sleep(delay_seconds)
            body = fetch(eid)
            facts = facts_from_event(json.loads(body), start_date)
        except AccessDenied as err:
            return {"status": "failed", "error": str(err), "attempted": done + failed, "enriched": done, "with_time": timed, "with_price": priced}
        except Exception as err:  # el evento puede haber desaparecido: se anota y no se reintenta hasta RECHECK_DAYS
            failed += 1; key = f"{type(err).__name__}: {str(err)[:60]}"; errors[key] = errors.get(key, 0) + 1
            body, facts = "", {"time": "", "time_text": "", "price_text": "", "error": str(err)[:200]}
        api_url = API_URL.format(id=eid) if eid else url
        with conn:
            conn.execute("""INSERT INTO source_enrichments(source,id,fetched_at,source_url,description,links_json,raw_html_sha256,schedule_time,schedule_text,schedule_checked_at,schedule_parser_version)
              VALUES(?,?,?,?,'','[]',?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET fetched_at=excluded.fetched_at,source_url=excluded.source_url,
              raw_html_sha256=excluded.raw_html_sha256,schedule_time=excluded.schedule_time,schedule_text=excluded.schedule_text,
              schedule_checked_at=excluded.schedule_checked_at,schedule_parser_version=excluded.schedule_parser_version""",
              (SOURCE, record_id, now, api_url, hashlib.sha256(body.encode()).hexdigest(), facts["time"], facts["time_text"], now, PARSER_VERSION))
            stored = {k: v for k, v in facts.items() if k != "time"} | {"api_url": api_url, "fetched_at": now}
            conn.execute("""INSERT INTO source_detail_facts(source,id,fetched_at,facts_json) VALUES(?,?,?,?)
              ON CONFLICT(source,id) DO UPDATE SET fetched_at=excluded.fetched_at,facts_json=excluded.facts_json""",
              (SOURCE, record_id, now, json.dumps(stored, ensure_ascii=False)))
        if body: done += 1
        timed += bool(facts["time"]); priced += bool(facts["price_text"]); mismatched += facts.get("date_matches") is False
    return {"status": "completed", "online_excluded": online, "attempted": done + failed, "enriched": done, "failed": failed, "with_time": timed,
            "with_price": priced, "date_mismatch_no_time": mismatched, "errors": errors}
