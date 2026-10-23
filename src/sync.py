"""Incremental, auditable import for the approved API families.

The module intentionally has no dependency on the HTTP server.  It can be
called by the local CLI or with a fake transport in tests.  A failed or
truncated run never interprets absence from a page as deletion.
"""
from __future__ import annotations

import datetime as dt
import json
import re as _re
import sqlite3
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from src.pipeline import candidate_sessions, coor, coords_in_row, delta, event_kind, sha
from src.network import tls_context
from mvp.catalog import guiabcn_exclusion
from src import known_times as _known_times

BARCELONA_INE = "08019"
GENCAT_BARCELONA = "agenda:ubicacions/barcelona/barcelones/barcelona"
TIME_ZONE = "Europe/Madrid"
GUIABCN_ENDPOINT = "https://apinasia.bcn.cat/services/asia/retroapiguiabcn/"
RETRYABLE = {429, 500, 502, 503, 504}


class SyncError(RuntimeError):
    pass


class PartialSync(SyncError):
    """A run that must be retained but must not infer removals."""


@dataclass
class HttpResponse:
    status: int
    body: object
    headers: Mapping[str, str]


def urllib_transport(url: str, params: Mapping[str, object], timeout: float) -> HttpResponse:
    # GuiaBCN's public search grammar uses literal `*` and comma-separated
    # taxonomy prefixes; encoding them changes their meaning on that service.
    query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True, safe="*,:", quote_via=quote)
    request = Request(url + (("&" if "?" in url else "?") + query if query else ""),
                      headers={"Accept": "*/*", "User-Agent": "Brollant/1.3 (+https://brollant.com) sync"})
    try:
        with urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310: explicit public API endpoint supplied by operator
            return HttpResponse(response.status, json.loads(response.read().decode("utf-8")), dict(response.headers.items()))
    except HTTPError as error:
        # Keep the server's explanation (Socrata and do.diba.cat return a JSON
        # message for 400s) so a failed run is diagnosable from the audit row.
        try: detail = error.read(2000).decode("utf-8", "replace")
        except Exception: detail = ""
        return HttpResponse(error.code, {"error": detail[:500]} if detail else None, dict(error.headers.items()))
    except URLError as error:
        raise SyncError("Error de red: %s" % error.reason) from error


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _changed_fields(old: Optional[dict], new: dict) -> list[str]:
    if old is None:
        return []
    names = ("title", "start", "end", "time_text", "price_text", "venues", "organizers", "url", "kind", "eligibility")
    return [name for name in names if old.get(name) != new.get(name)]


GENCAT_MEDIA_BASE = "https://agenda.cultura.gencat.cat"


def generalitat_image_urls(raw: dict) -> list[str]:
    """Image references of a Generalitat record: ``imatges`` (comma-separated
    site paths) and ``imgapp``, resolved against the agenda's own host."""
    from urllib.parse import quote
    location = (raw.get("localizaciones") or [{}])[0] if isinstance(raw, dict) else {}
    urls: list[str] = []
    for field in ("imatges", "imgapp"):
        for part in str(location.get(field) or "").split(","):
            path = part.strip()
            if not path: continue
            url = path if path.startswith(("https://", "http://")) else GENCAT_MEDIA_BASE + quote(path, safe="/()-_.,") if path.startswith("/") else ""
            if url and url not in urls: urls.append(url)
    return urls[:4]


def register_generalitat_images(conn: sqlite3.Connection) -> int:
    """Register every Generalitat record's images as media assets (idempotent;
    rights follow the source policy in docs/source_registry.json)."""
    from src.media import register
    registered = 0
    for record_id, title, raw_text in conn.execute("SELECT id,title,raw_json FROM source_records WHERE source='generalitat'").fetchall():
        try: raw = json.loads(raw_text)
        except ValueError: continue
        for url in generalitat_image_urls(raw):
            register(conn, "generalitat", record_id, url, alt=title or "", credit="Generalitat de Catalunya. Departament de Cultura"); registered += 1
    return registered


def _record_generalitat(rows: list[dict], organizers: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        # Do not trust a remote filter as the sole geographic control.
        municipality = row.get("municipi") or row.get("comarca_i_municipi")
        if municipality != GENCAT_BARCELONA:
            continue
        code = str(row.get("codi") or "")
        if code:
            grouped.setdefault(code, []).append(row)
    by_organizer: dict[str, list[dict]] = {}
    for row in organizers:
        code = str(row.get("codi") or "")
        if code:
            by_organizer.setdefault(code, []).append(row)
    result = []
    for code, locations in grouped.items():
        base = locations[0]
        span = delta(base.get("data_inici"), base.get("data_fi"))
        kind, eligibility = event_kind(base.get("denominaci", ""), base.get("tags_categor_es", ""), span, base.get("horari", ""), "generalitat")
        venues, seen = [], set()
        for row in locations:
            key = (row.get("espai", ""), row.get("adre_a", ""), row.get("latitud", ""), row.get("longitud", ""))
            if key not in seen:
                seen.add(key)
                venues.append({"name": row.get("espai", ""), "address": row.get("adre_a", ""), "coords": coords_in_row(row)})
        orgs = sorted({str(row.get("nom_organitzador", "")).strip() for row in by_organizer.get(code, []) if str(row.get("nom_organitzador", "")).strip()})
        flags = []
        if len(venues) > 1: flags.append("MULTI_VENUE_SESSION_NOT_RESOLVED")
        if base.get("data_fi_aproximada") == "true": flags.append("END_DATE_APPROXIMATE")
        if not str(base.get("horari") or "").strip(): flags.append("NO_SCHEDULE_SOURCE")
        if not str(base.get("entrades") or "").strip(): flags.append("NO_PRICE_TEXT")
        if kind == "program": flags.append("PROGRAM_MAY_CONTAIN_CHILD_EVENTS")
        if not orgs: flags.append("ORGANIZER_NAME_MISSING")
        url = base.get("urlactivitat") or base.get("url") or ""
        if not str(url).strip(): flags.append("DIRECT_ACTIVITY_URL_MISSING")
        if str(base.get("data_inici", "")).startswith("9999") or str(base.get("data_fi", "")).startswith("9999"):
            # Permanent/virtual resources carry a 9999-09-09 placeholder: not a dated activity.
            flags.append("PLACEHOLDER_DATE_NOT_AN_EVENT"); eligibility = "exclude"
        result.append({"source": "generalitat", "id": code, "title": base.get("denominaci", ""), "start": str(base.get("data_inici", ""))[:10], "end": str(base.get("data_fi", ""))[:10], "time_text": base.get("horari", ""), "price_text": base.get("entrades", ""), "kind": kind, "eligibility": eligibility, "start_timestamp": "", "frequency": "", "raw": {"localizaciones": locations, "organizadores": by_organizer.get(code, [])}, "venues": venues, "organizers": orgs, "url": url, "alerts": flags, "evidence_level": "api_raw_unverified"})
    return result


def _record_diba(source: str, rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        external_id = str(row.get("acte_id") or "")
        municipality = str((row.get("rel_municipis") or {}).get("ine") or "")
        if not external_id or municipality != BARCELONA_INE:
            continue
        place = row.get("grup_adreca") or {}
        span = delta(row.get("data_inici"), row.get("data_fi"))
        kind, eligibility = event_kind(row.get("titol", ""), " ".join(row.get("tipus") or []), span, row.get("observacions_horari", ""), source)
        flags = []
        if str(row.get("data_fi", "")).endswith("23:59:59"): flags.append("ADMINISTRATIVE_DAY_END_NOT_SESSION_TIME")
        if span is not None and span > 1: flags.append("LONG_RANGE_DO_NOT_EXPAND")
        if span == 1: flags.append("NEXT_DAY_END_REVIEW")
        if not str(row.get("preu") or "").strip(): flags.append("UNKNOWN_PRICE_NOT_FREE")
        if not str(row.get("descripcio") or "").strip(): flags.append("DESCRIPTION_MISSING")
        if row.get("observacions_horari") in ("Setmanal", "Mensual"): flags.append("RECURRING_FREQUENCY_NOT_DATES")
        if str(row.get("data_inici", ""))[11:16] == "00:00": flags.append("MIDNIGHT_PLACEHOLDER_NOT_START_TIME")
        result.append({"source": source, "id": external_id, "title": row.get("titol", ""), "start": str(row.get("data_inici", ""))[:10], "end": str(row.get("data_fi", ""))[:10], "time_text": row.get("observacions_horari", ""), "price_text": row.get("preu", ""), "kind": kind, "eligibility": eligibility, "start_timestamp": row.get("data_inici", ""), "frequency": row.get("observacions_horari", ""), "raw": row, "venues": [{"name": str(place.get("adreca_nom", "")).strip(), "address": place.get("adreca", ""), "coords": coor(place.get("localitzacio"))}], "organizers": [str(row.get("acte_organitzadors", "")).strip()] if str(row.get("acte_organitzadors", "")).strip() else [], "url": row.get("acte_url", ""), "alerts": flags, "evidence_level": "api_raw_unverified"})
    return result


def _guia_items(body):
    """Extract list rows from the JSON explicitly declared by GuiaBCN's UI."""
    try:
        rows = body["page"]["central"]["search"]["queryresponse"]["list"]["list_items"]["row"]
    except (TypeError, KeyError):
        return []
    if not isinstance(rows, list): rows = [rows] if rows else []
    return [r.get("item", r) for r in rows if isinstance(r, dict)]


def _record_guiabcn(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        external_id, start = str(row.get("id") or ""), str(row.get("begindate") or "")
        # The endpoint also exposes facilities.  Only rows with source dates are
        # treated as agenda records; everything else remains outside this feed.
        if not external_id or not start:
            continue
        def date(value):
            bits = str(value or "").split("/")
            return "-".join((bits[2], bits[1], bits[0])) if len(bits) == 3 else str(value)[:10]
        attrs = row.get("@attributes") or {}
        href = str(attrs.get("href") or "")
        url = "https://guia.barcelona.cat/ca/detall/" + href.lstrip("/") if href else ""
        title, end = str(row.get("name") or ""), date(row.get("enddate") or start)
        kind, eligibility = event_kind(title, str(row.get("type") or ""), delta(date(start), end), "", "guiabcn")
        raw = {"id": external_id, "title": title, "type": row.get("type", ""), "district": row.get("district", ""), "venue": row.get("institutionname", ""), "observation": row.get("interestinfo", ""), "api_item": row}
        alerts = ["GUIABCN_EXPERIMENTAL_FEED", "NO_IMAGE_INGESTION", "NO_PRIMARY_DETAIL_FETCH"]
        # The feed is wider than the city: metropolitan rows and calendar
        # notices are archived but flagged out of the public agenda.
        exclusion = guiabcn_exclusion(raw, date(start), end)
        if exclusion:
            eligibility = "exclude"; alerts.append(exclusion)
        result.append({"source": "guiabcn", "id": external_id, "title": title, "start": date(start), "end": end,
            "time_text": "", "price_text": "", "kind": kind, "eligibility": eligibility,
            "start_timestamp": "", "frequency": "", "raw": raw,
            "venues": [{"name": str(row.get("institutionname") or ""), "address": str(row.get("address") or ""), "coords": coor("%s,%s" % (row.get("gmapx", ""), row.get("gmapy", "")))}], "organizers": [], "url": url,
            "alerts": alerts, "evidence_level": "api_raw_unverified"})
    return result


def reclassify_guiabcn(conn: sqlite3.Connection) -> dict:
    """Re-derive eligibility flags for archived GuiaBCN rows without touching
    their raw JSON, versions, reviews or enrichments. Idempotent."""
    initialize(conn)
    changed = 0; reasons: dict[str, int] = {}
    rows = conn.execute("SELECT id,raw_json,start_date,end_date,eligibility FROM source_records WHERE source='guiabcn'").fetchall()
    with conn:
        for record_id, raw_text, start, end, eligibility in rows:
            try: raw = json.loads(raw_text)
            except (TypeError, ValueError): continue
            reason = guiabcn_exclusion(raw, start, end)
            if not reason:
                continue
            reasons[reason] = reasons.get(reason, 0) + 1
            if eligibility != "exclude":
                conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source='guiabcn' AND id=?", (record_id,)); changed += 1
            conn.execute("INSERT OR IGNORE INTO review_flags VALUES ('guiabcn',?,?)", (record_id, reason))
    return {"source": "guiabcn", "scanned": len(rows), "newly_excluded": changed, "flagged_by_reason": reasons}


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS sync_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
      status TEXT NOT NULL, http_status INTEGER, cursor TEXT, pages INTEGER NOT NULL DEFAULT 0,
      rows_received INTEGER NOT NULL DEFAULT 0, rows_rejected INTEGER NOT NULL DEFAULT 0,
      rows_mutated INTEGER NOT NULL DEFAULT 0, warning_json TEXT NOT NULL DEFAULT '[]', error TEXT
    );
    CREATE TABLE IF NOT EXISTS source_record_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, external_id TEXT NOT NULL, run_id INTEGER NOT NULL,
      raw_sha256 TEXT NOT NULL, normalized_sha256 TEXT NOT NULL, raw_json TEXT NOT NULL, changed_fields_json TEXT NOT NULL,
      observed_at TEXT NOT NULL, UNIQUE(source, external_id, run_id, raw_sha256), FOREIGN KEY(run_id) REFERENCES sync_runs(id)
    );
    CREATE TABLE IF NOT EXISTS editorial_review_invalidations (
      invalidation_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, record_id TEXT NOT NULL, run_id INTEGER NOT NULL,
      field_name TEXT NOT NULL, previous_value_sha256 TEXT, current_value_sha256 TEXT NOT NULL, invalidated_at TEXT NOT NULL,
      FOREIGN KEY(run_id) REFERENCES sync_runs(id)
    );
    CREATE TABLE IF NOT EXISTS editorial_reviews (
      source TEXT NOT NULL, id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL, PRIMARY KEY(source,id)
    );
    CREATE TABLE IF NOT EXISTS editorial_review_log (
      seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,id TEXT NOT NULL,
      old_status TEXT, new_status TEXT NOT NULL, old_note TEXT, new_note TEXT, changed_at TEXT NOT NULL
    );
    """)
    # Old databases from v1.3 retain their primary key; source/id remains the
    # stable source identity and is therefore the external id for this MVP.


def _upsert_record(conn: sqlite3.Connection, run_id: int, record: dict) -> tuple[bool, list[str]]:
    old_row = conn.execute("SELECT raw_json FROM source_records WHERE source=? AND id=?", (record["source"], record["id"])).fetchone()
    old = None
    if old_row:
        try:
            raw = json.loads(old_row[0])
            # Only needed for comparison; preserve unknown original JSON.
            if record["source"] == "generalitat": old = _record_generalitat(raw.get("localizaciones", []), raw.get("organizadores", []))[0]
            elif record["source"] in ("diba_bibliotecas", "diba_turismo"): old = _record_diba(record["source"], [raw])[0]
            elif raw.get("normalized"): old = raw["normalized"]
        except (ValueError, IndexError, TypeError, KeyError):
            old = None
    record["raw"].setdefault("normalized", {key: record[key] for key in ("title", "start", "end", "time_text", "price_text", "kind", "eligibility", "venues", "organizers", "url")})
    raw_hash = sha(record["raw"])
    normalized_hash = sha({key: record[key] for key in ("title", "start", "end", "time_text", "price_text", "kind", "eligibility", "venues", "organizers", "url")})
    existing = conn.execute("SELECT raw_sha256 FROM source_records WHERE source=? AND id=?", (record["source"], record["id"])).fetchone()
    if existing and existing[0] == raw_hash:
        # Snapshots predate the version table.  The first live observation of
        # an unchanged snapshot is still its auditable baseline, but later
        # identical runs remain idempotent.
        seen = conn.execute("SELECT 1 FROM source_record_versions WHERE source=? AND external_id=? AND raw_sha256=?", (record["source"], record["id"], raw_hash)).fetchone()
        if not seen:
            conn.execute("INSERT INTO source_record_versions(source,external_id,run_id,raw_sha256,normalized_sha256,raw_json,changed_fields_json,observed_at) VALUES(?,?,?,?,?,?,?,?)", (record["source"], record["id"], run_id, raw_hash, normalized_hash, json.dumps(record["raw"], ensure_ascii=False, sort_keys=True), "[]", now_utc()))
        return False, []
    changed = _changed_fields(old, record)
    conn.execute("""INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source,id) DO UPDATE SET title=excluded.title,start_date=excluded.start_date,end_date=excluded.end_date,
        kind=excluded.kind,eligibility=excluded.eligibility,evidence_level=excluded.evidence_level,source_url=excluded.source_url,
        raw_sha256=excluded.raw_sha256,raw_json=excluded.raw_json""",
        (record["source"], record["id"], record["title"], record["start"], record["end"], record["kind"], record["eligibility"], record["evidence_level"], record["url"], raw_hash, json.dumps(record["raw"], ensure_ascii=False, sort_keys=True)))
    for table in ("source_venues", "source_organizers", "review_flags", "candidate_occurrences"):
        conn.execute("DELETE FROM %s WHERE source=? AND id=?" % table, (record["source"], record["id"]))
    for seq, venue in enumerate(record["venues"]):
        coords = venue.get("coords")
        conn.execute("INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)", (record["source"], record["id"], seq, venue.get("name", ""), venue.get("address", ""), coords[0] if coords else None, coords[1] if coords else None))
    for seq, name in enumerate(record["organizers"]):
        conn.execute("INSERT INTO source_organizers VALUES (?,?,?,?)", (record["source"], record["id"], seq, name))
    # Una lectura que funciona pero ya no trae la hora que traía la anterior es una anomalía (maqueta nueva,
    # cita de hora que la IA no copió…), no algo normal: queda marcada para revisar (23-10-2026).
    if old and _re.match(r"\d{2}:\d{2}", str(old.get("time_text") or "")) and not _re.match(r"\d{2}:\d{2}", str(record.get("time_text") or "")) \
            and str(old.get("start") or "")[:10] == str(record.get("start") or "")[:10]:
        record["alerts"] = list(record["alerts"]) + ["TIME_LOST_IN_NEW_READ"]
    for flag in sorted(set(record["alerts"])):
        conn.execute("INSERT INTO review_flags VALUES (?,?,?)", (record["source"], record["id"], flag))
    sessions = candidate_sessions(record)
    for occurrence in sessions:
        conn.execute("INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)", (record["source"], record["id"], occurrence["local_date"], occurrence["local_time"], occurrence["type"], occurrence["evidence_field"]))
    # Toda hora que dé una lectura queda guardada: si otra pasada la pierde, la ficha muestra la última conocida.
    _known_times.remember(conn, record["source"], record["id"], sessions, now_utc())
    conn.execute("""INSERT OR IGNORE INTO source_record_versions(source,external_id,run_id,raw_sha256,normalized_sha256,raw_json,changed_fields_json,observed_at)
        VALUES(?,?,?,?,?,?,?,?)""", (record["source"], record["id"], run_id, raw_hash, normalized_hash, json.dumps(record["raw"], ensure_ascii=False, sort_keys=True), json.dumps(changed), now_utc()))
    for field in changed:
        before = sha(old.get(field)) if old else None
        after = sha(record.get(field))
        conn.execute("INSERT INTO editorial_review_invalidations(source,record_id,run_id,field_name,previous_value_sha256,current_value_sha256,invalidated_at) VALUES(?,?,?,?,?,?,?)", (record["source"], record["id"], run_id, field, before, after, now_utc()))
    if changed:
        review = conn.execute("SELECT status,note FROM editorial_reviews WHERE source=? AND id=?", (record["source"], record["id"])).fetchone()
        if review and review[0] == "reviewed":
            when = now_utc()
            conn.execute("UPDATE editorial_reviews SET status='needs_evidence',updated_at=? WHERE source=? AND id=?", (when, record["source"], record["id"]))
            conn.execute("INSERT INTO editorial_review_log(source,id,old_status,new_status,old_note,new_note,changed_at) VALUES(?,?,?,?,?,?,?)", (record["source"], record["id"], "reviewed", "needs_evidence", review[1], review[1], when))
    return True, changed


class IncrementalSync:
    def __init__(self, conn: sqlite3.Connection, transport: Callable = urllib_transport, sleeper: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.conn, self.transport, self.sleeper, self.clock = conn, transport, sleeper, clock
        initialize(conn)

    def run(self, source: str, endpoint: str, *, page_size: int = 100, max_rows: int = 1000, timeout_seconds: float = 30, max_retries: int = 2, organizers_endpoint: str = "", since_days: int = 0, today=None) -> dict:
        """``organizers_endpoint`` (Generalitat) fetches the organiser rows for the
        imported codes; ``since_days`` lets Diputació runs stop once a page only
        holds rows that ended more than that many days ago (the API is sorted
        by start date descending and includes its whole history)."""
        today = today or dt.date.today()
        if source not in ("generalitat", "diba_bibliotecas", "diba_turismo", "guiabcn"):
            raise ValueError("Fuente no sincronizable")
        if not endpoint.startswith("https://"):
            raise ValueError("La API debe usar HTTPS")
        if not (1 <= page_size <= 1000 and 1 <= max_rows <= 10000 and 1 <= timeout_seconds <= 300):
            raise ValueError("Límites de sincronización no permitidos")
        started, warnings, received, rejected, mutated, pages, cursor, last_status = now_utc(), [], 0, 0, 0, 0, 0, None
        # Generalitat exposes locations and organisers as separate rows.  Keep
        # all successful pages together so a record split across pages retains
        # every venue and organiser before its relations are replaced.
        generalitat_locations: list[dict] = []
        generalitat_organizers: list[dict] = []
        with self.conn:
            # A process can be interrupted between pages. Preserve its audit
            # trail and let the next run start safely rather than treating it
            # as a successful fetch.
            self.conn.execute("UPDATE sync_runs SET status='partial',finished_at=?,error='Proceso interrumpido antes de finalizar' WHERE source=? AND status='running'", (started, source))
            previous=self.conn.execute("SELECT cursor FROM sync_runs WHERE source=? AND (status='partial' OR warning_json LIKE '%ROW_LIMIT_REACHED%') AND cursor NOT IN ('', '0') ORDER BY id DESC LIMIT 1",(source,)).fetchone()
            if previous:
                try: cursor=max(cursor,int(previous[0]))
                except ValueError: pass
            run_id = self.conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (source, started, "running", str(cursor))).lastrowid
        deadline = self.clock() + timeout_seconds
        try:
            while received < max_rows:
                if self.clock() >= deadline: raise PartialSync("Límite de tiempo alcanzado")
                limit = min(page_size, max_rows - received)
                request_url = endpoint
                if source == "generalitat":
                    # Socrata pagination is deliberately explicit and ordered
                    # (unordered $offset pages are not stable).  The
                    # server-side predicate is repeated by _record_generalitat.
                    where = "municipi='%s'" % GENCAT_BARCELONA
                    if since_days: where += " AND data_fi >= '%s'" % (today - dt.timedelta(days=since_days)).isoformat()
                    # SODA 2.1 rejects unknown arguments (a stray `timezone` yields HTTP 400).
                    params = {"$limit": limit, "$offset": cursor, "$where": where, "$order": "codi"}
                elif source == "guiabcn":
                    # Public agenda taxonomy used by GuiaBCN's own links.  It
                    # excludes the equipment/directory universe returned by an
                    # unfiltered query. No media endpoints are queried.
                    params = {"pg": "search", "xout": "json", "nr": limit, "idma": "ca", "cerca": "*:*", "c": "00618*,00619*,00620*"}
                    # GuiaBCN's own public list JavaScript uses `from` as the
                    # zero-based result offset for incremental pagination.
                    if cursor:
                        params["from"] = cursor
                else:
                    # do.diba.cat takes its parameters as path segments:
                    # /pag-ini/N/pag-fi/M/camp-rel_municipis/08019/ord-data_inici/desc
                    request_url = "%s/pag-ini/%d/pag-fi/%d/camp-rel_municipis/%s/ord-data_inici/desc" % (endpoint.rstrip("/"), cursor + 1, cursor + limit, BARCELONA_INE)
                    params = {}
                response = None
                for attempt in range(max_retries + 1):
                    response = self.transport(request_url, params, max(1, deadline - self.clock()))
                    last_status = response.status
                    if response.status not in RETRYABLE: break
                    if attempt == max_retries: raise PartialSync("HTTP %s tras reintentos" % response.status)
                    self.sleeper(min(2 ** attempt, max(0, deadline - self.clock())))
                if response is None or response.status < 200 or response.status >= 300:
                    detail = response.body.get("error") if response is not None and isinstance(response.body, dict) else ""
                    raise PartialSync("HTTP %s%s" % (last_status or "sin respuesta", (": " + str(detail)[:300]) if detail else ""))
                body = response.body
                if source == "generalitat":
                    if isinstance(body, dict):
                        locations, organizers = body.get("localizaciones", []), body.get("organizadores", [])
                    else:
                        locations, organizers = body, []
                    if not isinstance(locations, list) or not isinstance(organizers, list): raise PartialSync("Respuesta Generalitat inválida")
                    generalitat_locations.extend(locations)
                    generalitat_organizers.extend(organizers)
                    records = []
                    raw_count = len(locations)
                elif source == "guiabcn":
                    rows = _guia_items(body)
                    records = _record_guiabcn(rows)
                    raw_count = len(rows)
                else:
                    rows = body.get("elements", []) if isinstance(body, dict) else body
                    if not isinstance(rows, list): raise PartialSync("Respuesta Diputació inválida")
                    records = _record_diba(source, rows)
                    raw_count = len(rows)
                    if since_days and rows and all(str(r.get("data_fi") or "")[:10] < (today - dt.timedelta(days=since_days)).isoformat() for r in rows if isinstance(r, dict)):
                        # Everything on this page ended long ago; the feed is
                        # sorted by start date descending, so stop here.
                        pages += 1; received += raw_count; rejected += raw_count - len(records)
                        with self.conn:
                            for record in records:
                                did_mutate, _ = _upsert_record(self.conn, run_id, record); mutated += int(did_mutate)
                        warnings.append("STOPPED_AT_ARCHIVED_ROWS: no se han inferido bajas")
                        break
                pages += 1; received += raw_count; rejected += raw_count - len(records)
                with self.conn:
                    for record in records:
                        did_mutate, _ = _upsert_record(self.conn, run_id, record)
                        mutated += int(did_mutate)
                if raw_count < limit: break
                cursor += raw_count
                with self.conn:
                    self.conn.execute("UPDATE sync_runs SET http_status=?,cursor=?,pages=?,rows_received=?,rows_rejected=?,rows_mutated=? WHERE id=?", (last_status,str(cursor),pages,received,rejected,mutated,run_id))
            if source == "generalitat" and organizers_endpoint and generalitat_locations:
                codes = sorted({str(row.get("codi") or "") for row in generalitat_locations if row.get("codi")})
                for start in range(0, len(codes), 50):
                    if self.clock() >= deadline: raise PartialSync("Límite de tiempo alcanzado al cargar organizadores")
                    chunk = codes[start:start + 50]
                    response = self.transport(organizers_endpoint, {"$limit": 1000, "$where": "codi in(%s)" % ",".join("'%s'" % c.replace("'", "") for c in chunk)}, max(1, deadline - self.clock()))
                    if response.status < 200 or response.status >= 300 or not isinstance(response.body, list): raise PartialSync("HTTP %s al cargar organizadores" % response.status)
                    generalitat_organizers.extend(response.body); pages += 1
            if source == "generalitat":
                with self.conn:
                    for record in _record_generalitat(generalitat_locations, generalitat_organizers):
                        did_mutate, _ = _upsert_record(self.conn, run_id, record)
                        mutated += int(did_mutate)
                    register_generalitat_images(self.conn)
            if received >= max_rows:
                warnings.append("ROW_LIMIT_REACHED: no se han inferido bajas")
                status = "partial"
            else:
                status = "completed"
        except PartialSync as error:
            status = "partial"; warnings.append(str(error))
        except Exception as error:
            status = "failed"; warnings.append(str(error))
        with self.conn:
            self.conn.execute("UPDATE sync_runs SET finished_at=?,status=?,http_status=?,cursor=?,pages=?,rows_received=?,rows_rejected=?,rows_mutated=?,warning_json=?,error=? WHERE id=?", (now_utc(), status, last_status, str(cursor), pages, received, rejected, mutated, json.dumps(warnings, ensure_ascii=False), warnings[-1] if status != "completed" else None, run_id))
        return {"id": run_id, "source": source, "status": status, "http_status": last_status, "cursor": str(cursor), "pages": pages, "rows_received": received, "rows_rejected": rejected, "rows_mutated": mutated, "warnings": warnings}


def record_from_stored(source, record_id, raw, start, end, kind, eligibility, today=None):
    """La ficha (forma de conector) que da un raw_json guardado, para volver a sacar sus sesiones sin red.
    La usan ``rebuild_candidates`` y el historial de horas (src/known_times.py)."""
    from src.opendata_bcn import record_from_item
    try:
        if source == "generalitat": record = _record_generalitat(raw.get("localizaciones", []), raw.get("organizadores", []))[0]
        elif source in ("diba_bibliotecas", "diba_turismo"): record = _record_diba(source, [raw])[0]
        elif source == "opendatabcn_agenda": record = record_from_item(raw, today)
        elif source.startswith(("web_", "venue_")):
            normalized = raw.get("normalized") or {}
            record = {"source": source, "id": record_id, "start": start, "end": end, "kind": kind, "eligibility": eligibility,
                      "time_text": normalized.get("time_text", ""), "venues": normalized.get("venues", []),
                      "time_evidence_field": "event_next_date" if source == "web_auditori" else "schema.org/startDate" if source.startswith("venue_") else "listing_time"}
        else: return None
    except (IndexError, KeyError, TypeError, ValueError, AttributeError):
        return None
    if record is not None: record["eligibility"] = eligibility
    return record


def rebuild_candidates(conn: sqlite3.Connection, *, today=None) -> dict:
    """Recompute candidate occurrences for every archived record from its stored
    raw JSON, without any network call. Needed after a parser improvement:
    ``_upsert_record`` only re-derives candidates when the source row changes.
    Idempotent; GuiaBCN keeps its detail-page schedule path."""
    from src.opendata_bcn import record_from_item
    counts: dict[str, dict[str, int]] = {}
    rows = conn.execute("SELECT source,id,raw_json,start_date,end_date,kind,eligibility FROM source_records WHERE source<>'guiabcn'").fetchall()
    with conn:
        for source, record_id, raw_text, start, end, kind, eligibility in rows:
            stat = counts.setdefault(source, {"records": 0, "with_candidates": 0, "changed": 0, "unparsed": 0})
            stat["records"] += 1
            try: raw = json.loads(raw_text)
            except (TypeError, ValueError): stat["unparsed"] += 1; continue
            record = record_from_stored(source, record_id, raw, start, end, kind, eligibility, today)  # editorial/derived state already stored wins
            if record is None: stat["unparsed"] += 1; continue
            wanted = sorted({(o["local_date"], o["local_time"], o["type"], o["evidence_field"]) for o in candidate_sessions(record)})
            _known_times.remember(conn, source, record_id, [{"local_date": d, "local_time": t, "evidence_field": f} for d, t, _, f in wanted], now_utc())
            current = sorted(conn.execute("SELECT local_date,local_time,kind,evidence_field FROM candidate_occurrences WHERE source=? AND id=?", (source, record_id)).fetchall())
            if wanted: stat["with_candidates"] += 1
            if [tuple(c) for c in current] != wanted:
                stat["changed"] += 1
                conn.execute("DELETE FROM candidate_occurrences WHERE source=? AND id=?", (source, record_id))
                for local_date, local_time, kind_name, evidence in wanted:
                    conn.execute("INSERT OR IGNORE INTO candidate_occurrences VALUES (?,?,?,?,?,?)", (source, record_id, local_date, local_time, kind_name, evidence))
    return {"by_source": counts, "total_candidates": conn.execute("SELECT COUNT(*) FROM candidate_occurrences").fetchone()[0]}
