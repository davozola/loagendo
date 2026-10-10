"""Incremental, auditable import for the approved API families.

The module intentionally has no dependency on the HTTP server.  It can be
called by the local CLI or with a fake transport in tests.  A failed or
truncated run never interprets absence from a page as deletion.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Callable, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.pipeline import candidate_sessions, coor, coords_in_row, delta, event_kind, sha

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
    query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True, safe="*,:" )
    request = Request(url + ("&" if "?" in url else "?") + query,
                      headers={"Accept": "*/*", "User-Agent": "Loagendo/1.3 local sync"})
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310: explicit public API endpoint supplied by operator
            return HttpResponse(response.status, json.loads(response.read().decode("utf-8")), dict(response.headers.items()))
    except HTTPError as error:
        return HttpResponse(error.code, None, dict(error.headers.items()))
    except URLError as error:
        raise SyncError("Error de red: %s" % error.reason) from error


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _changed_fields(old: Optional[dict], new: dict) -> list[str]:
    if old is None:
        return []
    names = ("title", "start", "end", "time_text", "price_text", "venues", "organizers", "url", "kind", "eligibility")
    return [name for name in names if old.get(name) != new.get(name)]


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
        result.append({"source": "guiabcn", "id": external_id, "title": title, "start": date(start), "end": end,
            "time_text": "", "price_text": "", "kind": kind, "eligibility": eligibility,
            "start_timestamp": "", "frequency": "", "raw": {"id": external_id, "title": title, "type": row.get("type", ""), "district": row.get("district", ""), "venue": row.get("institutionname", ""), "observation": row.get("interestinfo", ""), "api_item": row},
            "venues": [{"name": str(row.get("institutionname") or ""), "address": str(row.get("address") or ""), "coords": coor("%s,%s" % (row.get("gmapx", ""), row.get("gmapy", "")))}], "organizers": [], "url": url,
            "alerts": ["GUIABCN_EXPERIMENTAL_FEED", "NO_IMAGE_INGESTION", "NO_PRIMARY_DETAIL_FETCH"], "evidence_level": "api_raw_unverified"})
    return result


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
            else: old = _record_diba(record["source"], [raw])[0]
        except (ValueError, IndexError, TypeError, KeyError):
            old = None
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
    for flag in sorted(set(record["alerts"])):
        conn.execute("INSERT INTO review_flags VALUES (?,?,?)", (record["source"], record["id"], flag))
    for occurrence in candidate_sessions(record):
        conn.execute("INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)", (record["source"], record["id"], occurrence["local_date"], occurrence["local_time"], occurrence["type"], occurrence["evidence_field"]))
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

    def run(self, source: str, endpoint: str, *, page_size: int = 100, max_rows: int = 1000, timeout_seconds: float = 30, max_retries: int = 2) -> dict:
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
                if source == "generalitat":
                    # Socrata pagination is deliberately explicit.  The
                    # server-side predicate is repeated by _record_generalitat.
                    params = {"$limit": limit, "$offset": cursor, "$where": "municipi='%s'" % GENCAT_BARCELONA, "timezone": TIME_ZONE}
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
                    params = {"limit": limit, "offset": cursor, "municipi_ine": BARCELONA_INE, "timezone": TIME_ZONE}
                response = None
                for attempt in range(max_retries + 1):
                    response = self.transport(endpoint, params, max(1, deadline - self.clock()))
                    last_status = response.status
                    if response.status not in RETRYABLE: break
                    if attempt == max_retries: raise PartialSync("HTTP %s tras reintentos" % response.status)
                    self.sleeper(min(2 ** attempt, max(0, deadline - self.clock())))
                if response is None or response.status < 200 or response.status >= 300:
                    raise PartialSync("HTTP %s" % (last_status or "sin respuesta"))
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
                pages += 1; received += raw_count; rejected += raw_count - len(records)
                with self.conn:
                    for record in records:
                        did_mutate, _ = _upsert_record(self.conn, run_id, record)
                        mutated += int(did_mutate)
                if raw_count < limit: break
                cursor += raw_count
                with self.conn:
                    self.conn.execute("UPDATE sync_runs SET http_status=?,cursor=?,pages=?,rows_received=?,rows_rejected=?,rows_mutated=? WHERE id=?", (last_status,str(cursor),pages,received,rejected,mutated,run_id))
            if source == "generalitat":
                with self.conn:
                    for record in _record_generalitat(generalitat_locations, generalitat_organizers):
                        did_mutate, _ = _upsert_record(self.conn, run_id, record)
                        mutated += int(did_mutate)
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
