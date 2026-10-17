"""Connector for «Agenda cultural de la ciutat de Barcelona» (Open Data BCN).

Why this source: it is the licensed (CC BY 4.0, daily) bulk channel for the
same municipal agenda that ``guiabcn`` scrapes from a search endpoint whose
``robots.txt`` forbids crawlers. Records carry the same ``register_id`` as
GuiaBCN, so both can be linked by identity rather than by title similarity.

What it ingests, without inventing anything:
- title, dates, venue, address, district, neighbourhood, coordinates, the
  official detail URL (``guia.barcelona.cat/ca/detall/agenda_<id>.html``);
- description from ``body`` (HTML archived verbatim in ``raw``);
- the timetable table (days / hours / prices / notes) as source text;
- explicit sessions from the embedded iCalendar (``DTSTART``) as *candidate*
  occurrences. The feed labels wall-clock Europe/Madrid times with a ``Z``
  suffix (a 19:00 concert appears as ``190000Z`` and the timetable says
  «a les 19.00 h»), so the suffix is ignored and the timetable text is used
  as a cross-check;
- ticket type (``Lliure`` = free, ``Inscripcions``), registration and ticket
  URLs, organiser and venue relationships, image references with
  ``rights_status='unknown'`` (``type_license`` is null in the dataset).

The 170 MB JSON resource is streamed to ``data/cache`` with its SHA-256 and
parsed object by object, so memory stays bounded. ``event_status`` other
than ``ok`` (suspended / deferred) is archived with ``eligibility='exclude'``
and an explicit flag, never dropped.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
from pathlib import Path
from urllib.request import Request, urlopen

from src.media import register
from src.network import tls_context
from src.pipeline import delta
from src.sync import _upsert_record, initialize, now_utc
from mvp.catalog import initialize as initialize_catalog

SOURCE = "opendatabcn_agenda"
CKAN_PACKAGE = "https://opendata-ajuntament.barcelona.cat/data/api/3/action/package_show?id=agenda-cultural"
RESOURCE_URL = "https://opendata-ajuntament.barcelona.cat/data/dataset/2767159c-1c98-46b8-a686-2b25b40cb053/resource/59b9c807-f6c1-4c10-ac51-1ace65485079/download"
DETAIL_URL = "https://guia.barcelona.cat/ca/detall/agenda_{id}.html"
TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "config" / "opendatabcn_taxonomy.json"
MAX_OCCURRENCES_PER_RECORD = 60
OCCURRENCE_HORIZON_DAYS = 200
USER_AGENT = "Loagendo/1.3 open-data connector (CC BY 4.0 dataset; contact in README)"


def load_taxonomy(path=TAXONOMY_PATH):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {"priority": [], "typology": {}, "specialty": {}, "family_markers": []}


TAXONOMY = load_taxonomy()


def plain(markup):
    """HTML → readable text that keeps paragraph breaks (one blank line between blocks)."""
    text = re.sub(r"(?i)</(?:p|div|li|h[1-6]|blockquote|tr)>|<br\s*/?>", "\n", markup or "")
    text = html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out = []
    for line in lines:
        if line: out.append(line)
        elif out and out[-1] != "": out.append("")
    return "\n".join(out).strip()


def _date(value):
    return str(value or "")[:10]


def classification_names(item):
    out = {"typology": [], "specialty": [], "collective": [], "other": []}
    for entry in item.get("classifications_data") or []:
        path = str(entry.get("full_path") or "")
        name = str(entry.get("name") or "").strip()
        if path.startswith("Tipologia AG"): out["typology"].append(name)
        elif path.startswith("Especialitats AG"): out["specialty"].append(path.split(">>")[1].strip() if ">>" in path else name)
        elif path.startswith("Col·lectius AG"): out["collective"].append(name)
        else: out["other"].append(name)
    return out


def category_for(item):
    names = classification_names(item)
    typology = TAXONOMY.get("typology", {}); specialty = TAXONOMY.get("specialty", {})
    for name in TAXONOMY.get("priority", []):
        if name in names["typology"] and typology.get(name): return typology[name]
    for name in names["typology"]:
        if typology.get(name): return typology[name]
    for name in names["specialty"]:
        if specialty.get(name): return specialty[name]
    return None


def family_audience(item):
    markers = TAXONOMY.get("family_markers", [])
    names = classification_names(item)
    return any(marker in name for name in names["collective"] + names["other"] for marker in markers)


def kind_for(item, span):
    names = classification_names(item)["typology"]
    if "Exposicions" in names: return "exhibition"
    # A one-day workshop, fair or annual festival edition is a dated act for
    # the agenda even if the source types it as a course or a repeating event.
    if (span or 0) == 0 and item.get("type") != "permanent": return "single"
    if "Cursos i tallers" in names: return "course"
    if item.get("type") == "permanent": return "service"
    if item.get("type") == "repetitive" or (span or 0) > 2: return "program"
    return "single"


def timetable_facts(item):
    table = (item.get("timetable") or {}).get("html") or ""
    rows = re.findall(r"<tr>(.*?)</tr>", table, re.S | re.I)
    facts = {"schedule_days": [], "schedule_hours": [], "price_text": [], "schedule_note": []}
    for row in rows:
        cells = {m.group(1): plain(m.group(2)) for m in re.finditer(r'<td class="timetable-(day|hour|price|description)"[^>]*>(.*?)</td>', row, re.S | re.I)}
        for key, target in (("day", "schedule_days"), ("hour", "schedule_hours"), ("price", "price_text"), ("description", "schedule_note")):
            if cells.get(key) and cells[key] not in facts[target]: facts[target].append(cells[key])
    return {key: " · ".join(value) for key, value in facts.items() if value}


def timetable_hours(hours_text):
    """Explicit clock times in the timetable (e.g. 'a les 19.00 h', 'de 10.00 h a 12.00 h' → 10:00)."""
    found = []
    for hour, minute in re.findall(r"\b(\d{1,2})[.:](\d{2})\s*h", hours_text or ""):
        value = f"{int(hour):02d}:{int(minute):02d}"
        if int(hour) <= 23 and int(minute) <= 59 and value not in found: found.append(value)
    return found


def ical_sessions(ical_text):
    """(date, time) pairs from DTSTART lines; the 'Z' is a labelling artefact (see module doc)."""
    out = []
    for match in re.finditer(r"DTSTART(?:;[^:]*)?:(\d{8})T(\d{2})(\d{2})(\d{2})?Z?", ical_text or ""):
        day, hour, minute = match.group(1), match.group(2), match.group(3)
        date = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        if (date, f"{hour}:{minute}") not in out: out.append((date, f"{hour}:{minute}"))
    return sorted(out)


def occurrences_for(item, kind, today=None):
    """Explicit iCal sessions as candidates. Exhibitions and permanent services
    keep their interval (their iCal lists opening days, not sessions); a course
    or cycle keeps its own dated sessions when the source enumerates them."""
    if kind in ("exhibition", "service"): return []
    today = today or dt.date.today()
    horizon = (today + dt.timedelta(days=OCCURRENCE_HORIZON_DAYS)).isoformat()
    sessions = [s for s in ical_sessions(item.get("ical")) if today.isoformat() <= s[0] <= horizon]
    if not sessions or len(sessions) > MAX_OCCURRENCES_PER_RECORD: return []
    hours = set(timetable_hours(timetable_facts(item).get("schedule_hours", "")))
    out = []
    for date, time in sessions:
        out.append({"local_date": date, "local_time": time, "time_zone": "Europe/Madrid",
                    "type": "open_data_ical_wallclock_candidate" + ("_confirmed_by_timetable" if time in hours else ""),
                    "evidence_field": "ical.DTSTART", "end_time": None})
    return out


def slim_raw(item):
    """Archive the record minus redundant geometry variants and the attribute catalogue copy."""
    raw = dict(item)
    raw.pop("attribute_categories", None)
    raw["addresses"] = [{k: v for k, v in (address or {}).items() if not (k.startswith("location") and k != "location_4326")} for address in item.get("addresses") or []]
    raw["from_relationships"] = [{k: v for k, v in (rel or {}).items() if k != "addresses"} for rel in item.get("from_relationships") or []]
    if raw.get("image_data"): raw["image_data"] = {k: v for k, v in raw["image_data"].items() if k != "cuts"}
    raw["gallery_data"] = [{k: v for k, v in (g or {}).items() if k != "cuts"} for g in item.get("gallery_data") or []]
    return raw


def record_from_item(item, today=None):
    """Normalise one dataset object into the record shape used by ``_upsert_record``; None if not an event."""
    register_id = str(item.get("register_id") or "")
    title = str(item.get("name") or "").strip()
    if not register_id or not title or item.get("core_type") != "event" or item.get("status") != "published": return None
    address = (item.get("addresses") or [{}])[0] or {}
    start, end = _date(item.get("start_date")), _date(item.get("end_date")) or _date(item.get("start_date"))
    span = delta(start, end)
    kind = kind_for(item, span)
    facts = timetable_facts(item)
    tickets = {str(t.get("name") or "") for t in item.get("tickets_data") or []}
    values = {}
    for value in item.get("values") or []:
        name = str(value.get("attribute_name") or ""); val = value.get("value")
        if name and val and name not in values: values[name] = str(val)
    links = [values[k] for k in ("Web", "Web inscripcions", "Web venda d'entrades", "Web preinscripcions") if values.get(k, "").startswith("http")]
    organizers = [str(r.get("entity_name") or "").strip() for r in item.get("from_relationships") or [] if str(r.get("name") or "").strip().casefold() in ("organitzat per", "coordinat per", "impulsat per", "produït per") and r.get("entity_name")]
    venue_entity = next((str(r.get("entity_name") or "") for r in item.get("from_relationships") or [] if str(r.get("name") or "").strip() == "se celebra a"), "")
    geo = item.get("geo_epgs_4326_latlon") or {}
    coords = (float(geo["lat"]), float(geo["lon"])) if geo.get("lat") is not None and geo.get("lon") is not None else None
    street = " ".join(x for x in (str(address.get("address_name") or ""), str(address.get("street_number_1") or "")) if x)
    full_address = ", ".join(x for x in (street, " ".join(y for y in (str(address.get("zip_code") or ""), str(address.get("town") or "")) if y)) if x)
    town = str(address.get("town") or "").strip().casefold()
    flags = ["OPEN_DATA_BCN_CC_BY_4_0", "DETAIL_URL_DERIVED_FROM_REGISTER_ID"]
    eligibility = "review"
    if town and town != "barcelona":
        eligibility = "exclude"; flags.append("OUTSIDE_BARCELONA_MUNICIPALITY")
    if item.get("event_status") not in (None, "", "ok"):
        eligibility = "exclude"; flags.append("EVENT_STATUS_" + str(item.get("event_status")).upper())
    if kind == "program": flags.append("PROGRAM_MAY_CONTAIN_CHILD_EVENTS")
    if not facts.get("schedule_hours"): flags.append("NO_SCHEDULE_SOURCE")
    if not facts.get("price_text") and "Lliure" not in tickets: flags.append("NO_PRICE_TEXT")
    if not plain(item.get("body")): flags.append("DESCRIPTION_MISSING")
    if item.get("warnings"): flags.append("SOURCE_WARNING_PRESENT")
    record = {"source": SOURCE, "id": register_id, "title": title, "start": start, "end": end,
              "time_text": facts.get("schedule_hours", ""), "price_text": "Entrada lliure" if "Lliure" in tickets and not facts.get("price_text") else facts.get("price_text", ""),
              "kind": kind, "eligibility": eligibility, "start_timestamp": "", "frequency": str(item.get("period_name") or ""),
              "raw": slim_raw(item), "venues": [{"name": str(address.get("place") or venue_entity or ""), "address": full_address, "coords": coords}],
              "organizers": sorted(set(organizers)), "url": DETAIL_URL.format(id=register_id), "alerts": flags, "evidence_level": "open_data_cc_by_unverified",
              "occurrences": occurrences_for(item, kind, today), "links": links, "images": [], "family_audience": family_audience(item),
              "category": category_for(item), "district": str(address.get("district_name") or ""), "neighborhood": str(address.get("neighborhood_name") or ""),
              "is_free": "Lliure" in tickets, "registration_required": "Inscripcions" in tickets or bool(values.get("Web inscripcions")),
              "registration_url": values.get("Web inscripcions", ""), "tickets_url": values.get("Web venda d'entrades", "")}
    # Derived fields travel with the archived raw so the catalogue can read
    # them without re-parsing the dataset object.
    record["raw"]["loagendo"] = {key: record[key] for key in ("category", "district", "neighborhood", "family_audience", "is_free", "registration_required", "registration_url", "tickets_url", "links")}
    record["raw"]["loagendo"].update({"schedule_days": facts.get("schedule_days", ""), "schedule_hours": facts.get("schedule_hours", ""), "price_text": facts.get("price_text", ""), "schedule_note": facts.get("schedule_note", "")})
    for image in ([item.get("image_data")] if item.get("image_data") else []) + list(item.get("gallery_data") or []):
        url = str(image.get("image_optimized") or image.get("image") or "")
        if url.startswith("https://"): record["images"].append({"url": url, "alt": str(image.get("alt") or image.get("title") or ""), "license": image.get("type_license")})
    return record


def iter_items(text):
    """Yield top-level objects of a JSON array without materialising the whole list."""
    decoder = json.JSONDecoder()
    index = text.find("[")
    if index < 0: return
    index += 1
    length = len(text)
    while index < length:
        while index < length and text[index] in " \r\n\t,": index += 1
        if index >= length or text[index] == "]": return
        item, index = decoder.raw_decode(text, index)
        yield item


def download(url, destination: Path, timeout=600):
    """Stream the resource to disk and return (path, sha256, bytes)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    digest = hashlib.sha256(); size = 0; partial = destination.with_suffix(destination.suffix + ".part")
    with urlopen(request, timeout=timeout, context=tls_context()) as response, partial.open("wb") as handle:  # nosec B310: fixed open-data URL
        if not 200 <= response.status < 300: raise RuntimeError("HTTP %s" % response.status)
        content_type = response.headers.get_content_type()
        while True:
            chunk = response.read(1 << 20)
            if not chunk: break
            handle.write(chunk); digest.update(chunk); size += len(chunk)
    if size < 1024 or content_type not in ("application/json", "text/json", "application/octet-stream"):
        partial.unlink(missing_ok=True)
        raise RuntimeError("La descarga no es JSON (%s, %s bytes): la web puede estar bloqueando clientes automáticos; descarga el recurso desde el navegador y usa --opendata-file" % (content_type, size))
    partial.replace(destination)
    return destination, digest.hexdigest(), size


def initialize_source(conn):
    initialize(conn); initialize_catalog(conn)
    conn.execute("""CREATE TABLE IF NOT EXISTS source_snapshots(
        source TEXT NOT NULL, run_id INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(source, run_id))""")


def sync(conn: sqlite3.Connection, *, url=RESOURCE_URL, file: Path | None = None, cache_dir: Path | None = None, today=None, timeout=600, max_records=None):
    """Import the dataset. ``file`` skips the download (manual browser download)."""
    initialize_source(conn)
    started = now_utc()
    with conn:
        run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (SOURCE, started, "running", "0")).lastrowid
    received = rejected = mutated = excluded = occurrences = images = 0
    try:
        if file:
            path = Path(file); data = path.read_bytes(); sha = hashlib.sha256(data).hexdigest(); size = len(data)
        else:
            cache_dir = cache_dir or Path(__file__).resolve().parents[1] / "data" / "cache"
            path, sha, size = download(url, cache_dir / "opendatabcn_agenda.json", timeout=timeout)
            data = path.read_bytes()
        text = data.decode("utf-8")
        del data
        with conn:
            conn.execute("INSERT OR REPLACE INTO source_snapshots(source,run_id,path,sha256,bytes,fetched_at) VALUES(?,?,?,?,?,?)", (SOURCE, run_id, str(path), sha, size, now_utc()))
        batch = []
        for item in iter_items(text):
            received += 1
            if max_records and received > max_records: break
            record = record_from_item(item, today)
            if record is None:
                rejected += 1; continue
            batch.append(record)
            if len(batch) >= 200:
                mutated, excluded, occurrences, images = _flush(conn, run_id, batch, mutated, excluded, occurrences, images); batch = []
        mutated, excluded, occurrences, images = _flush(conn, run_id, batch, mutated, excluded, occurrences, images)
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=1,rows_received=?,rows_rejected=?,rows_mutated=?,warning_json=? WHERE id=?",
                         (now_utc(), received, rejected, mutated, json.dumps(["NO_DELETION_INFERRED"]), run_id))
        return {"id": run_id, "source": SOURCE, "status": "completed", "rows_received": received, "rows_rejected": rejected, "rows_mutated": mutated,
                "rows_excluded": excluded, "candidate_occurrences": occurrences, "image_references": images, "snapshot_sha256": sha, "snapshot_bytes": size}
    except Exception as error:
        with conn:
            conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',rows_received=?,rows_mutated=?,warning_json=?,error=? WHERE id=?", (now_utc(), received, mutated, json.dumps([str(error)]), str(error)[:1000], run_id))
        return {"id": run_id, "source": SOURCE, "status": "failed", "rows_received": received, "rows_mutated": mutated, "error": str(error)}


def _flush(conn, run_id, batch, mutated, excluded, occurrences, images):
    with conn:
        for record in batch:
            did_mutate, _ = _upsert_record(conn, run_id, record)
            mutated += int(did_mutate)
            excluded += int(record["eligibility"] == "exclude")
            occurrences += len(record["occurrences"]) if record["eligibility"] != "exclude" else 0
            for image in record["images"]:
                register(conn, SOURCE, record["id"], image["url"], alt=image["alt"], credit="Ajuntament de Barcelona — Agenda cultural (Open Data BCN)", rights_status="unknown"); images += 1
    return mutated, excluded, occurrences, images
