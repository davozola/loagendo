"""Fallback photos of the venues (municipal "equipaments").

Most records without an image of their own are activities at civic centres,
libraries and casals; the municipal feed links each to the venue's page on
barcelona.cat, whose ``og:image`` is the venue's photo. One photo per venue
(a few hundred) illustrates thousands of records that would otherwise be
blank, labelled as the venue's image and credited to the city, never passed
off as a picture of the activity. Rights follow the ``place`` entry of
docs/source_registry.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from src.network import ascii_url, tls_context


def now_utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

RETRY_AFTER_DAYS = 30
FETCH_VERSION = 3  # bump when the page strategy changes: earlier failures are retried once
# v3 (17-10-2026): respeta robots.txt y añade la página por id de Barcelona Cultura (las canónicas espais-associacions dan 404).
PSEUDO_PLACE_WORDS = ("diferents espais", "diversos espais", "varios espacios", "diferentes espacios", "espais de la ciutat", "carrers del barri", "diversos llocs", "en línia", "online")
USER_AGENT = "Loagendo/1.3 venue photo (one request per venue page)"
ALLOWED_PAGE_HOSTS = ("barcelona.cat",)


def initialize(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS place_images (
      place_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '', page_url TEXT NOT NULL DEFAULT '',
      image_url TEXT, sha256 TEXT, local_path TEXT, content_type TEXT,
      fetched_at TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT ''
    );
    """)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(place_images)")}
    if "fetch_version" not in columns: conn.execute("ALTER TABLE place_images ADD COLUMN fetch_version INTEGER NOT NULL DEFAULT 1")


def place_of(raw, source):
    """(place_id, name, page_url) carried by an archived record, or None."""
    if not isinstance(raw, dict): return None
    if source == "opendatabcn_agenda":
        for rel in raw.get("from_relationships") or []:
            if isinstance(rel, dict) and rel.get("entity_core_type") == "place" and rel.get("entity_id"):
                return (str(rel["entity_id"]), str(rel.get("entity_name") or ""), str(rel.get("entity_canonical_url") or ""))
        return None
    if source == "guiabcn":
        item = raw.get("api_item") or {}
        if item.get("equipment_id"):
            return (str(item["equipment_id"]), str(item.get("institutionname") or ""), "")
    if source == "diba_bibliotecas":
        # Sin id de equipamiento: se enlaza por nombre exacto (normalizado) con un
        # equipamiento municipal que ya tenga foto; ver local_place_images.
        name = str((raw.get("grup_adreca") or {}).get("adreca_nom") or "").strip()
        if name: return (name_key(name), name, "")
    return None


def name_key(name):
    """Clave de recinto por nombre exacto, normalizado solo en mayúsculas, acentos y puntuación."""
    import unicodedata
    return "name:" + re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()).strip()


def candidate_pages(place_id, name, canonical_url):
    """Pages that may carry the venue's photo, most reliable first: the
    GuiaBCN equipment page (guia.barcelona.cat/ca/detall/<slug>_<id>.html,
    the same CMS that serves the events) and then the canonical city page."""
    out = []
    slug = ""
    if canonical_url:
        last = canonical_url.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"-?\d{6,}$", "", last)
    if not slug and name:
        import unicodedata
        slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")
    if slug: out.append(f"https://guia.barcelona.cat/ca/detall/{slug}_{place_id}.html")
    if canonical_url: out.append(canonical_url)
    if place_id: out.append(f"https://www.barcelona.cat/barcelonacultura/ca/detail/{place_id}")
    return out


def fetch_page(url, timeout=20):
    host = urlsplit(url).netloc.lower()
    if not any(host == h or host.endswith("." + h) for h in ALLOWED_PAGE_HOSTS): raise ValueError("Host no permitido para fotos de equipamiento")
    from src.venue_feeds import robots_allows
    if not robots_allows(url): raise PermissionError("robots.txt no permite esta página")
    request = urllib.request.Request(ascii_url(url), headers={"Accept": "text/html", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310: municipal venue pages only
        return response.geturl(), response.read(2_000_000).decode("utf-8", "replace")


def image_from_page(page, base_url):
    """The page's og:image, else its first content image on a municipal host."""
    match = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', page, re.I) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', page, re.I)
    if match: return urljoin(base_url, html.unescape(match.group(1)))
    for src in re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', page, re.I):
        url = urljoin(base_url, html.unescape(src))
        if re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)", url, re.I) and "logo" not in url.lower() and "icon" not in url.lower(): return url
    return None


def download(url, directory, timeout=20):
    request = urllib.request.Request(ascii_url(url), headers={"Accept": "image/*", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310: image named by the municipal page
        content = response.read(10_000_000); content_type = response.headers.get_content_type()
    if not content_type.startswith("image/") or len(content) > 10_000_000: raise ValueError("Contenido de imagen no permitido")
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "img")
    digest = hashlib.sha256(content).hexdigest(); path = Path(directory) / "places" / f"{digest}.{extension}"; path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists(): path.write_bytes(content)
    return str(path), digest, content_type


def places_needing_images(conn, today=None, limit=60):
    """Venues of upcoming public records that have no image of their own and no
    usable venue photo yet (or a failure older than RETRY_AFTER_DAYS)."""
    initialize(conn)
    today = (today or dt.date.today()).isoformat()
    retry_before = (dt.date.fromisoformat(today) - dt.timedelta(days=RETRY_AFTER_DAYS)).isoformat()
    known = {r[0]: (r[1], r[2], r[3]) for r in conn.execute("SELECT place_id,status,fetched_at,fetch_version FROM place_images")}
    with_media = {(r[0], r[1]) for r in conn.execute("SELECT DISTINCT source,id FROM media_assets WHERE download_failed_at IS NULL")}
    wanted = {}
    for source, record_id, raw_text in conn.execute("SELECT source,id,raw_json FROM source_records WHERE source IN ('opendatabcn_agenda','guiabcn') AND end_date>=? AND eligibility<>'exclude'", (today,)):
        if (source, record_id) in with_media: continue
        try: place = place_of(json.loads(raw_text), source)
        except ValueError: place = None
        if not place: continue
        place_id, name, page_url = place
        if any(word in (name or "").casefold() for word in PSEUDO_PLACE_WORDS): continue  # "diferents espais de la ciutat" is not a venue
        status = known.get(place_id)
        if status and (status[0] == "ok" or ((status[1] or "") >= retry_before and (status[2] or 1) >= FETCH_VERSION)): continue
        entry = wanted.setdefault(place_id, {"place_id": place_id, "name": name, "page_url": page_url, "records": 0})
        entry["records"] += 1
        if page_url and not entry["page_url"]: entry["page_url"] = page_url
        if name and not entry["name"]: entry["name"] = name
    # Most records served first; GuiaBCN ids alone are enough to build a page.
    ranked = sorted(wanted.values(), key=lambda p: -p["records"])
    return ranked[:limit]


def fetch_place_images(conn, media_root, *, limit=60, today=None, fetcher=fetch_page, downloader=download, timeout=20):
    """Automation job: fetch up to ``limit`` venue photos; failures are recorded and retried a month later."""
    initialize(conn)
    done = failed = 0; outcomes = []
    for place in places_needing_images(conn, today, limit):
        now = now_utc()
        try:
            image_url = None; last_error = None; used_page = ""
            for page_url in candidate_pages(place["place_id"], place["name"], place["page_url"]):
                try:
                    final_url, page = fetcher(page_url, timeout)
                    image_url = image_from_page(page, final_url); used_page = page_url
                    if image_url: break
                    last_error = LookupError("La página del equipamiento no tiene imagen")
                except Exception as error: last_error = error
            if not image_url: raise last_error or LookupError("Sin página de equipamiento")
            place = {**place, "page_url": used_page}
            local_path, digest, content_type = downloader(image_url, media_root, timeout)
            conn.execute("""INSERT INTO place_images(place_id,name,page_url,image_url,sha256,local_path,content_type,fetched_at,status,error,fetch_version) VALUES(?,?,?,?,?,?,?,?,'ok','',?)
              ON CONFLICT(place_id) DO UPDATE SET name=excluded.name,page_url=excluded.page_url,image_url=excluded.image_url,sha256=excluded.sha256,local_path=excluded.local_path,content_type=excluded.content_type,fetched_at=excluded.fetched_at,status='ok',error='',fetch_version=excluded.fetch_version""",
              (place["place_id"], place["name"], place["page_url"], image_url, digest, local_path, content_type, now, FETCH_VERSION))
            done += 1; outcomes.append({"place": place["name"], "status": "ok", "records": place["records"]})
        except Exception as error:
            conn.execute("""INSERT INTO place_images(place_id,name,page_url,fetched_at,status,error,fetch_version) VALUES(?,?,?,?,'failed',?,?)
              ON CONFLICT(place_id) DO UPDATE SET fetched_at=excluded.fetched_at,status='failed',error=excluded.error,fetch_version=excluded.fetch_version""", (place["place_id"], place["name"], place["page_url"], now, str(error)[:300], FETCH_VERSION))
            failed += 1; outcomes.append({"place": place["name"], "status": "failed", "error": str(error)[:120]})
        conn.commit()
    return {"status": "completed", "fetched": done, "failed": failed, "outcomes": outcomes[:20]}


def local_place_images(conn):
    """{place_id: {...}} for every venue photo on disk."""
    initialize(conn)
    places = {r[0]: {"place_id": r[0], "name": r[1], "page_url": r[2], "image_url": r[3], "local_path": r[4], "content_type": r[5], "sha256": r[6]}
              for r in conn.execute("SELECT place_id,name,page_url,image_url,local_path,content_type,sha256 FROM place_images WHERE status='ok' AND local_path IS NOT NULL")}
    # Alias por nombre exacto para fuentes sin id de equipamiento (bibliotecas de la
    # Diputació). Solo nombres únicos: si dos equipamientos se llaman igual, no hay alias.
    by_name = {}
    for place in places.values():
        if place["name"]: by_name.setdefault(name_key(place["name"]), []).append(place)
    places.update({key: found[0] for key, found in by_name.items() if len(found) == 1 and key != "name:"})
    return places
