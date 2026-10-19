"""Private venues: census of structured data and a generic schema.org connector.

Why: the municipal and regional feeds cover public culture well; what a
reader misses is club concerts, commercial theatre and cinema. Many venues
already publish machine-readable programmes (``<script type="application/ld+json">``
with schema.org Event/MusicEvent/TheaterEvent, an iCal link or an RSS feed).
Reading a venue's own structured data is more robust than scraping its HTML
and is the format the venue itself publishes for reuse by search engines.

Two steps:
- ``census``: fetch each venue in config/venues.json once, record what it
  publishes (events found, iCal/RSS links, HTTP status, final URL) into
  reports/venue_census.json. No data is imported.
- ``sync_venue``: for venues with ``enabled: true``, import the schema.org
  events as ``venue_<slug>`` records with the same provenance rules as the
  first-party web collectors (no deletion inference, raw item archived,
  images with the source policy's rights).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib import robotparser

from src.media import register
from src.network import tls_context
from src.pipeline import delta, event_kind
from src.sync import _upsert_record, initialize, now_utc
from mvp.catalog import initialize as initialize_catalog

ROOT = Path(__file__).resolve().parents[1]
VENUES_PATH = ROOT / "config" / "venues.json"
CENSUS_PATH = ROOT / "reports" / "venue_census.json"
TYPE_CATEGORY = {"MusicEvent": "Música y vida nocturna", "Festival": "Música y vida nocturna", "TheaterEvent": "Artes escénicas", "DanceEvent": "Artes escénicas", "ComedyEvent": "Artes escénicas",
                 "ScreeningEvent": "Cine y audiovisual", "ExhibitionEvent": "Arte y exposiciones", "VisualArtsEvent": "Arte y exposiciones", "LiteraryEvent": "Literatura y palabra",
                 "EducationEvent": "Talleres y experiencias", "ChildrensEvent": "Talleres y experiencias", "SportsEvent": "Deporte", "FoodEvent": "Gastronomía"}
VENUE_CATEGORY = {"music": "Música y vida nocturna", "festival": "Música y vida nocturna", "theatre": "Artes escénicas", "cinema": "Cine y audiovisual", "culture": "Arte y exposiciones"}
EVENT_TYPES = {"Event", "MusicEvent", "TheaterEvent", "DanceEvent", "ComedyEvent", "ScreeningEvent", "Festival", "ExhibitionEvent", "VisualArtsEvent", "LiteraryEvent", "EducationEvent", "ChildrensEvent", "SocialEvent"}
USER_AGENT = "Brollant/1.3 (+https://brollant.com) venue census (reads published schema.org data)"


def load_venues(path=VENUES_PATH):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [v for v in data.get("venues", []) if v.get("slug") and v.get("url")]


_ROBOTS: dict[str, robotparser.RobotFileParser | None] = {}


def robots_allows(url, user_agent="Brollant", timeout=10):
    """Respect each host's robots.txt (ticketing sites in particular publish
    one). Unreachable robots.txt counts as allowed; a parse error too."""
    host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    if host not in _ROBOTS:
        parser = robotparser.RobotFileParser()
        try:
            request = Request(host + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310
                parser.parse(response.read(200_000).decode("utf-8", "replace").splitlines())
            _ROBOTS[host] = parser
        except Exception:
            _ROBOTS[host] = None
    parser = _ROBOTS[host]
    if parser is None: return True
    try: return parser.can_fetch(user_agent, url) and parser.can_fetch("*", url)
    except Exception: return True


def fetch(url, timeout=25):
    """Return (status, final_url, body). Never retries without TLS verification."""
    request = Request(url, headers={"Accept": "text/html,application/ld+json;q=0.9,*/*;q=0.5", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout, context=tls_context()) as response:  # nosec B310: operator-listed public agenda URLs
            return response.status, response.geturl(), response.read(4_000_000).decode("utf-8", "replace")
    except HTTPError as error:
        return error.code, url, ""
    except URLError as error:
        return 0, url, str(error.reason)
    except (TimeoutError, OSError, ValueError) as error:
        # A host that accepts the connection and then stalls raises a bare
        # TimeoutError (not URLError); a census must record it, not crash.
        return 0, url, f"{type(error).__name__}: {error}"[:200]


def jsonld_blocks(page):
    out = []
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        text = html.unescape(raw.strip())
        try: data = json.loads(text)
        except json.JSONDecodeError:
            # Some sites leave trailing commas or comments; skip rather than guess.
            continue
        out.append(data)
    return out


def _walk(node):
    """Yield every dict inside a JSON-LD document (handles @graph, lists, ItemList)."""
    if isinstance(node, dict):
        yield node
        for value in node.values(): yield from _walk(value)
    elif isinstance(node, list):
        for item in node: yield from _walk(item)


def jsonld_events(page):
    events = []
    for block in jsonld_blocks(page):
        for node in _walk(block):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(t).split("/")[-1] in EVENT_TYPES for t in types if t) and node.get("name") and node.get("startDate"):
                events.append(node)
    return events


def feed_links(page, base_url):
    links = {"ical": [], "rss": []}
    for href in re.findall(r'<(?:a|link)[^>]+href=["\']([^"\']+)["\']', page, re.I):
        absolute = urljoin(base_url, html.unescape(href))
        low = absolute.lower().split("?", 1)[0]
        # A real calendar feed: .ics file, webcal: scheme or an /ical path
        # segment. Plain substrings would match "musical" or "vertical".
        # "/calendar/" and "/calendari/" are HTML pages on most sites (CCCB,
        # Luz de Gas, Teatre Lliure's calendar.css), so only an explicit feed counts.
        if low.endswith(".ics") or low.startswith("webcal:") or re.search(r"/ical(?:/|$)", low) or "format=ical" in absolute.lower(): links["ical"].append(absolute)
    for href in re.findall(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)["\']', page, re.I):
        links["rss"].append(urljoin(base_url, html.unescape(href)))
    return {k: sorted(set(v))[:5] for k, v in links.items()}


def inspect(url, page, status, final_url):
    events = jsonld_events(page) if page else []
    sample = [{"name": str(e.get("name"))[:80], "startDate": str(e.get("startDate"))[:25], "type": e.get("@type")} for e in events[:3]]
    return {"url": url, "status": status, "final_url": final_url, "bytes": len(page or ""), "jsonld_events": len(events), "sample": sample,
            **feed_links(page or "", final_url or url), "checked_at": now_utc()}


AGENDA_WORDS = ("agenda", "programaci", "programa", "concert", "concierto", "espectacle", "espectaculo", "cartelera", "temporada", "calendari", "calendario", "events", "esdeveniments", "actividades", "activitats", "whats-on", "what-s-on", "sessions", "sesiones")


def agenda_candidates(page, base_url, limit=4):
    """Links on a homepage that look like the programme page, most promising first."""
    scored = {}
    for href, text in re.findall(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', page, re.I | re.S):
        absolute = urljoin(base_url, html.unescape(href)).split("#", 1)[0]
        if not absolute.startswith(("http://", "https://")) or absolute.rstrip("/") == base_url.rstrip("/"): continue
        if absolute.split("/", 3)[2] != base_url.split("/", 3)[2]: continue  # same host only
        # A programme section is shallow (/es/conciertos/, /ca/programacio);
        # deeper links are individual events, which the detail sampling covers.
        if absolute.split("/", 3)[3].rstrip("/").count("/") > 1: continue
        haystack = (absolute + " " + re.sub(r"<[^>]+>", " ", text)).lower()
        score = sum(2 if word in absolute.lower() else 1 for word in AGENDA_WORDS if word in haystack)
        if score: scored[absolute] = max(scored.get(absolute, 0), score)
    return [u for u, _ in sorted(scored.items(), key=lambda x: (-x[1], len(x[0])))[:limit]]


EVENT_LINK_WORDS = ("concert", "concierto", "espectacle", "espectaculo", "programaci", "event", "evento", "esdeveniment", "/e/", "agenda", "cartellera", "cartelera", "/obra", "/show", "pelicula", "pel-licula", "/film", "sessio", "sesion", "/entradas/", "/tickets/", "festival", "/d/")
DETAIL_SAMPLE = 3
DEFAULT_MAX_PAGES = 30


def event_links(page, base_url, limit=30, exclude=()):
    """Same-host links on a programme page that look like event pages, most
    promising first. Many sites only put schema.org/Event on the detail page,
    so the connector follows a bounded number of these."""
    host = base_url.split("/", 3)[2]
    scored = {}
    for href in re.findall(r'<a[^>]+href=["\']([^"\'#]+)', page, re.I):
        absolute = urljoin(base_url, html.unescape(href)).split("#", 1)[0]
        if not absolute.startswith(("http://", "https://")) or absolute.split("/", 3)[2] != host: continue
        path = absolute.split("/", 3)[3] if absolute.count("/") >= 3 else ""
        if not path or absolute.rstrip("/") == base_url.rstrip("/") or absolute in exclude: continue
        if re.search(r"\.(?:jpe?g|png|gif|webp|svg|pdf|css|js|ics|xml|zip)(?:\?|$)", path, re.I): continue
        score = sum(1 for word in EVENT_LINK_WORDS if word in absolute.lower())
        if score: scored[absolute] = max(scored.get(absolute, 0), score * 10 + min(path.rstrip("/").count("/"), 5))
    return [u for u, _ in sorted(scored.items(), key=lambda x: (-x[1], x[0]))[:limit]]


def probe(venue, fetcher, timeout):
    """Fetch the configured URL; if it is missing or carries no structured
    data, start from the site root and try the links that look like the
    programme. Returns the best entry and the URLs tried."""
    tried = []
    def attempt(url):
        if fetcher is fetch and not robots_allows(url):
            tried.append((url, 451)); entry = inspect(url, "", 451, url); entry["error"] = "robots.txt disallows this path"; return entry, ""
        status, final_url, body = fetcher(url, timeout); tried.append((url, status))
        entry = inspect(url, body if status == 200 else "", status, final_url)
        if status != 200: entry["error"] = body[:200] if status == 0 else ""
        return entry, body if status == 200 else ""
    best, body = attempt(venue["url"]); best_body = body
    if best["jsonld_events"] or best["ical"]: return best, tried
    root = "https://" + venue["url"].split("/", 3)[2] + "/"
    if root.rstrip("/") != venue["url"].rstrip("/"):
        home, home_body = attempt(root)
        if home["status"] == 200 and (home["jsonld_events"] or home["ical"]): return home, tried
        if home["status"] == 200 and best["status"] != 200: best, best_body = home, home_body
        body = home_body if home["status"] == 200 else body
    for candidate in agenda_candidates(body, root):
        if any(candidate == t[0] for t in tried): continue
        entry, candidate_body = attempt(candidate)
        if entry["jsonld_events"] or entry["ical"]: return entry, tried
        if entry["status"] == 200 and best["status"] != 200: best, best_body = entry, candidate_body
    # No structured data on any listing page: sample a few event links, since
    # schema.org/Event often lives only on the detail pages.
    best["jsonld_detail_events"] = 0; best["detail_sampled"] = []
    if best["status"] == 200 and best_body:
        for link in event_links(best_body, best["final_url"] or best["url"], DETAIL_SAMPLE):
            entry, _ = attempt(link); best["detail_sampled"].append(link)
            best["jsonld_detail_events"] += entry["jsonld_events"]
    return best, tried


def census(venues=None, fetcher=fetch, out_path=CENSUS_PATH, timeout=25):
    venues = venues if venues is not None else load_venues()
    results = []
    for venue in venues:
        probed, tried = probe(venue, fetcher, timeout)
        entry = {"slug": venue["slug"], "name": venue["name"], "type": venue.get("type", ""), **probed, "tried": [t[0] for t in tried]}
        status = entry["status"]
        entry["verdict"] = ("jsonld" if entry["jsonld_events"] else "jsonld_detail" if entry.get("jsonld_detail_events") else "ical" if entry["ical"] else "rss" if entry["rss"] else "html_only") if status == 200 else "robots_disallowed" if status == 451 else "unreachable"
        entry["suggested_url"] = entry["final_url"] if entry["verdict"] in ("jsonld", "jsonld_detail", "ical") and entry["final_url"] != venue["url"] else None
        results.append(entry)
    summary = {"checked_at": now_utc(), "venues": len(results), "by_verdict": {}, "results": results}
    for entry in results: summary["by_verdict"][entry["verdict"]] = summary["by_verdict"].get(entry["verdict"], 0) + 1
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _date(value):
    return str(value or "")[:10]


def _time(value):
    # «2026-10-22T19:30», y también «2026-10-22 CEST 19:30» o «2026-10-22 19:30» (Sala Apolo).
    match = re.match(r"\d{4}-\d{2}-\d{2}(?:T|\s+(?:[A-Z]{3,5}\s+)?)(\d{2}):(\d{2})", str(value or ""))
    return f"{match.group(1)}:{match.group(2)}" if match else ""


def _text(value):
    if isinstance(value, dict): value = value.get("name") or value.get("@value") or ""
    if isinstance(value, list): value = value[0] if value else ""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).split())


def clean_title(title, venue_name=""):
    """Directories append the hall to the name ("The Lemon Twigs @ Paral·lel 62",
    "X at Razzmatazz"); the public title is the act alone, the hall is a field."""
    cleaned = re.sub(r"\s+[@]\s+.+$", "", title).strip()
    if venue_name and cleaned.casefold().endswith(" at " + venue_name.casefold()): cleaned = cleaned[: -len(venue_name) - 4].strip()
    return cleaned or title


def record_id(slug, url, start, title):
    """Stable per concert page: a retitled listing must not become a second record."""
    basis = url if url and url.rstrip("/") != "" else title
    return hashlib.sha256((slug + "\0" + basis + "\0" + start).encode()).hexdigest()[:24]


def record_from_jsonld(venue, node, page_url):
    """Normalise one schema.org Event into Brollant's record shape."""
    title = _text(node.get("name"))
    start, end = _date(node.get("startDate")), _date(node.get("endDate")) or _date(node.get("startDate"))
    if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start): return None
    # Una sesión nocturna que acaba de madrugada («22:00 → 03:00 del día siguiente») es de un solo día.
    end_time = _time(node.get("endDate"))
    if end and end != start and end_time and end_time < "08:00":
        try:
            import datetime as _dt
            if (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days == 1: end = start
        except ValueError: pass
    url = str(node.get("url") or page_url)
    url = urljoin(page_url, url)
    location = node.get("location") or {}
    if isinstance(location, list): location = location[0] if location else {}
    address = location.get("address") if isinstance(location, dict) else None
    address_text = _text(address) if not isinstance(address, dict) else ", ".join(x for x in (_text(address.get("streetAddress")), _text(address.get("postalCode")), _text(address.get("addressLocality"))) if x)
    geo = location.get("geo") if isinstance(location, dict) else None
    coords = None
    try:
        if isinstance(geo, dict) and geo.get("latitude") is not None: coords = (float(geo["latitude"]), float(geo["longitude"]))
    except (TypeError, ValueError): coords = None
    venue_name = _text(location.get("name")) if isinstance(location, dict) else venue["name"]
    if venue.get("type") in ("ticketing", "aggregator"): title = clean_title(title, venue_name)
    locality = _text(address.get("addressLocality")) if isinstance(address, dict) else ""
    if venue.get("type") in ("ticketing", "aggregator") and locality and "barcelona" not in locality.casefold():
        return None  # a marketplace's city page can still list the metropolitan area
    offers = node.get("offers") or {}
    if isinstance(offers, list): offers = offers[0] if offers else {}
    price_text = ""
    if isinstance(offers, dict):
        price = offers.get("price"); currency = offers.get("priceCurrency") or ""
        if price not in (None, ""): price_text = f"{price} {currency}".strip()
        if str(offers.get("lowPrice") or "") and str(offers.get("highPrice") or ""):
            low, high = str(offers["lowPrice"]), str(offers["highPrice"])
            price_text = (f"{low} {currency}" if low == high else f"{low}–{high} {currency}").strip()
    tickets_url = urljoin(page_url, str(offers.get("url"))) if isinstance(offers, dict) and offers.get("url") else ""
    image = node.get("image")
    if isinstance(image, list): image = image[0] if image else ""
    if isinstance(image, dict): image = image.get("url") or ""
    image = urljoin(page_url, str(image)) if image else ""
    performers = node.get("performer") or []
    performers = performers if isinstance(performers, list) else [performers]
    organizers = [_text(o) for o in ([node.get("organizer")] if node.get("organizer") else []) if _text(o)]
    time_text = _time(node.get("startDate"))
    key = record_id(venue["slug"], url.split("?", 1)[0], start, title)
    kind, eligibility = event_kind(title, "", delta(start, end), "", "venue_" + venue["slug"])
    status = str(node.get("eventStatus") or "")
    alerts = ["VENUE_SCHEMA_ORG_EVENT", "SCHEDULE_FROM_STRUCTURED_DATA"] + (["THIRD_PARTY_TICKETING_LISTING"] if venue.get("type") in ("ticketing", "aggregator") else [])
    if "Cancelled" in status or "Postponed" in status:
        eligibility = "exclude"; alerts.append("EVENT_STATUS_" + status.split("/")[-1].upper())
    if is_online_event(node):
        eligibility = "exclude"; alerts.append(ONLINE_REASON)
    if not price_text: alerts.append("NO_PRICE_TEXT")
    description = _text(node.get("description"))
    types = node.get("@type"); types = [str(t).split("/")[-1] for t in (types if isinstance(types, list) else [types]) if t]
    category = venue.get("category") or VENUE_CATEGORY.get(venue.get("type", "")) or next((TYPE_CATEGORY[t] for t in types if t in TYPE_CATEGORY), None)
    if venue.get("type") in ("ticketing", "aggregator"):
        # A marketplace lists every kind of event: classify by the schema type, not the site.
        category = next((TYPE_CATEGORY[t] for t in types if t in TYPE_CATEGORY), None)
    label = venue["name"] + (" · ticketera" if venue.get("type") == "ticketing" else " · agregador" if venue.get("type") == "aggregator" else " · agenda del recinto")
    raw = {"source_page": page_url, "item": node, "image": image, "venue": venue["name"], "loagendo": {"description": description[:2000], "tickets_url": tickets_url, "performers": [_text(p) for p in performers][:10], "category": category, "source_label": label, "schema_types": types}}
    return {"source": "venue_" + venue["slug"], "id": key, "title": title, "start": start, "end": end or start, "time_text": time_text, "price_text": price_text,
            "kind": kind, "eligibility": eligibility, "start_timestamp": "", "frequency": "", "raw": raw,
            "venues": [{"name": venue_name or venue["name"], "address": address_text, "coords": coords}], "organizers": organizers or [venue["name"]], "url": url,
            "alerts": alerts, "evidence_level": "venue_structured_data_unverified", "time_evidence_field": "schema.org/startDate"}


FEED_HORIZON_DAYS = 180


def og_meta(page):
    """og:image / og:description of a page (what the site itself offers for sharing)."""
    out = {}
    for prop in ("og:image", "og:description"):
        m = re.search(r'<meta[^>]+property=["\']' + re.escape(prop) + r'["\'][^>]+content=["\']([^"\']+)["\']', page, re.I) or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']' + re.escape(prop) + r'["\']', page, re.I)
        if m: out[prop] = html.unescape(m.group(1))
    return out


def _page_extras(node, event_url, fetcher, timeout):
    """Image and description from the event's own page: its og:image /
    og:description, plus any schema.org Event it carries."""
    st, _, page = fetcher(event_url, timeout)
    if st != 200: return node
    meta = og_meta(page)
    if meta.get("og:image") and not node.get("image"): node["image"] = meta["og:image"]
    if meta.get("og:description") and not node.get("description"): node["description"] = meta["og:description"]
    for ld in jsonld_blocks(page):
        for sub in _walk(ld):
            if str(sub.get("@type", "")).endswith("Event"): node = {**node, **{k: v for k, v in sub.items() if k in ("description", "image", "offers", "performer", "startDate", "endDate")}}
    return node


def html_agenda_nodes(venue, fetcher=fetch, timeout=25, today=None):
    """Venues that print their programme as repeated HTML blocks (src.html_agenda):
    the listing is read once; each block's own page adds image and text."""
    from src.html_agenda import events_from_html
    feed = dict(venue["feed"]); feed.setdefault("venue_name", venue["name"])
    status, final_url, body = fetcher(feed["url"], timeout)
    if status != 200: raise RuntimeError("HTTP %s en %s" % (status, feed["url"]))
    nodes, fetched = [], 1
    budget = int(venue.get("max_pages", DEFAULT_MAX_PAGES)) if feed.get("details", True) else 0
    for node in events_from_html(body, feed, final_url or feed["url"], today=today):
        event_url = node.get("url", "")
        if event_url.startswith("http") and event_url != final_url and fetched <= budget and (fetcher is not fetch or robots_allows(event_url)):
            node = _page_extras(node, event_url, fetcher, timeout); fetched += 1
        nodes.append((event_url or final_url, node))
    return nodes, fetched


def wp_fullcalendar_nodes(venue, fetcher=fetch, timeout=25, today=None):
    """WordPress sites running the WP FullCalendar plugin (Events Manager and
    friends) answer ``admin-ajax.php?action=WP_FullCalendar&start=…&end=…``
    with a JSON list of {title,start,end,url}. Each item becomes a
    schema.org-shaped Event node so the usual record pipeline applies; the
    event page's own og:image / og:description (what the venue publishes for
    sharing) fill image and description when ``feed.details`` is not false."""
    feed = venue["feed"]; base = feed["url"]
    start = (today or dt.date.today()); end = start + dt.timedelta(days=int(feed.get("horizon_days", FEED_HORIZON_DAYS)))
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}start={start.isoformat()}&end={end.isoformat()}"
    status, final_url, body = fetcher(url, timeout)
    if status != 200: raise RuntimeError("HTTP %s en %s" % (status, url))
    try: items = json.loads(body)
    except json.JSONDecodeError: raise RuntimeError("La respuesta de %s no es JSON" % url)
    if not isinstance(items, list): raise RuntimeError("Respuesta inesperada de %s" % url)
    nodes, fetched = [], 1
    budget = int(venue.get("max_pages", DEFAULT_MAX_PAGES)) if feed.get("details", True) else 0
    for item in items:
        if not isinstance(item, dict) or not item.get("title") or not item.get("start"): continue
        event_url = urljoin(final_url or base, str(item.get("url") or ""))
        node = {"@type": "Event", "name": html.unescape(str(item["title"])), "startDate": str(item["start"]), "endDate": str(item.get("end") or item["start"]), "url": event_url,
                "location": {"@type": "Place", "name": venue["name"], "address": {"@type": "PostalAddress", "addressLocality": "Barcelona"}}}
        if event_url.startswith("http") and fetched <= budget and (fetcher is not fetch or robots_allows(event_url)):
            node = _page_extras(node, event_url, fetcher, timeout); fetched += 1
        nodes.append((event_url, node))
    return nodes, fetched


def sync_venue(conn: sqlite3.Connection, venue, fetcher=fetch, timeout=25):
    source = "venue_" + venue["slug"]
    initialize(conn); initialize_catalog(conn); started = now_utc()
    with conn:
        run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)", (source, started, "running", "0")).lastrowid
    try:
        urls = venue.get("urls") or [venue.get("agenda_url") or venue["url"]]
        pages = []
        kind = (venue.get("feed") or {}).get("kind")
        if kind in ("wp_fullcalendar", "html"):
            if fetcher is fetch and not robots_allows(venue["feed"]["url"]): raise RuntimeError("robots.txt no permite leer %s" % venue["feed"]["url"])
            nodes, fetched = (wp_fullcalendar_nodes if kind == "wp_fullcalendar" else html_agenda_nodes)(venue, fetcher, timeout); urls = []
        for agenda_url in urls:
            if fetcher is fetch and not robots_allows(agenda_url): raise RuntimeError("robots.txt no permite leer %s" % agenda_url)
            status, final_url, body = fetcher(agenda_url, timeout)
            if status != 200: raise RuntimeError("HTTP %s en %s" % (status, agenda_url))
            pages.append((final_url or agenda_url, body))
        if pages: nodes = [(page_url, node) for page_url, body in pages for node in jsonld_events(body)]; fetched = len(pages)
        # Follow a bounded number of event links from each listing page: the
        # listing often carries one or two events (or none) while every detail
        # page carries its full schema.org/Event with sessions, price and image.
        budget = int(venue.get("max_pages", DEFAULT_MAX_PAGES))
        if pages and venue.get("follow_links", True):
            known = {urljoin(page_url, str(node.get("url") or "")) for page_url, node in nodes}
            for listing_url, body in pages:
                for link in event_links(body, listing_url, budget, exclude=known):
                    if fetched >= len(pages) + budget: break
                    if fetcher is fetch and not robots_allows(link): continue
                    status, final_url, detail = fetcher(link, timeout); fetched += 1
                    if status == 200: nodes.extend((final_url or link, node) for node in jsonld_events(detail))
        # Listados que dan solo la fecha (Eventbrite): la página del evento trae la hora y, a veces,
        # una fecha corregida. Solo si la sala lo pide en config («time_details»: máximo de páginas).
        budget_time = int(venue.get("time_details", 0)); moved = []
        for n, (page_url, node) in enumerate(nodes):
            if budget_time <= 0: break
            event_url = str(node.get("url") or "")
            if len(str(node.get("startDate") or "")) != 10 or not event_url.startswith("http"): continue
            if fetcher is fetch and not robots_allows(event_url): continue
            detailed = _page_extras(dict(node), event_url, fetcher, timeout); fetched += 1; budget_time -= 1
            if str(detailed.get("startDate") or "")[:10] != str(node.get("startDate")):
                moved.append((event_url, str(node.get("startDate"))))   # la página dice otra fecha: manda la página
            nodes[n] = (page_url, detailed)
        if not nodes: raise RuntimeError("Ni la página ni sus enlaces de evento contienen JSON-LD schema.org/Event; revisa la URL con --venue-census" if pages else "El feed no devolvió eventos")
        records = [r for r in (record_from_jsonld(venue, node, page_url) for page_url, node in nodes) if r]
        seen = set(); records = [r for r in records if not (r["id"] in seen or seen.add(r["id"]))]
        mutated = 0
        with conn:
            # Evento trasladado según su propia página: la ficha con la fecha vieja del listado no se
            # borra (historial), pero deja de publicarse.
            for event_url, old_start in moved:
                old_id = record_id(venue["slug"], event_url.split("?", 1)[0], old_start, "")
                if old_id not in seen:
                    conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source=? AND id=?", (source, old_id))
            for record in records:
                mutated += int(_upsert_record(conn, run_id, record)[0])
                if record["raw"]["image"].startswith(("https://", "http://")):
                    register(conn, source, record["id"], record["raw"]["image"], alt=record["title"], credit=venue["name"])
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_mutated=?,warning_json='[]' WHERE id=?", (now_utc(), fetched, len(records), mutated, run_id))
        return {"id": run_id, "source": source, "status": "completed", "rows_received": len(records), "rows_mutated": mutated, "pages": fetched}
    except Exception as error:
        with conn: conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',warning_json=?,error=? WHERE id=?", (now_utc(), json.dumps([str(error)]), str(error)[:500], run_id))
        return {"id": run_id, "source": source, "status": "failed", "rows_received": 0, "rows_mutated": 0, "error": str(error)}


def migrate_record_ids(conn, venues=None):
    """One-off, idempotent: rename venue_* rows whose id predates ``record_id``
    (title-dependent) and clean directory titles in place. Nothing is deleted:
    an old id whose new id already exists is excluded with an alert."""
    venues = {v["slug"]: v for v in (venues if venues is not None else load_venues())}
    renamed = excluded = retitled = 0
    tables = ("source_venues", "source_organizers", "review_flags", "candidate_occurrences", "media_assets", "source_record_versions", "editorial_reviews", "source_enrichments", "source_detail_facts", "publication_decisions", "field_verifications", "curated_picks")
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.execute("PRAGMA foreign_keys=OFF")
    with conn:
        for source, old_id, title, start, url in conn.execute("SELECT source,id,title,start_date,source_url FROM source_records WHERE source LIKE 'venue_%'").fetchall():
            venue = venues.get(source[6:])
            if not venue: continue
            new_title = clean_title(title, "") if venue.get("type") in ("ticketing", "aggregator") else title
            new_id = record_id(venue["slug"], (url or "").split("?", 1)[0], start, new_title)
            if new_title != title:
                conn.execute("UPDATE source_records SET title=? WHERE source=? AND id=?", (new_title, source, old_id)); retitled += 1
            if new_id == old_id: continue
            if conn.execute("SELECT 1 FROM source_records WHERE source=? AND id=?", (source, new_id)).fetchone():
                conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source=? AND id=?", (source, old_id))
                conn.execute("INSERT OR IGNORE INTO review_flags VALUES (?,?,?)", (source, old_id, "SUPERSEDED_BY_ID_MIGRATION")); excluded += 1; continue
            for table in tables:
                if table not in existing: continue
                column = "external_id" if table == "source_record_versions" else "id"
                conn.execute(f"UPDATE {table} SET {column}=? WHERE source=? AND {column}=?", (new_id, source, old_id))
            conn.execute("UPDATE source_records SET id=? WHERE source=? AND id=?", (new_id, source, old_id)); renamed += 1
    conn.execute("PRAGMA foreign_keys=ON")
    return {"renamed": renamed, "excluded_duplicates": excluded, "retitled": retitled}


ONLINE_REASON = "ONLINE_EVENT_NOT_IN_BARCELONA"


def is_online_event(node):
    """Evento solo en línea según sus datos schema.org: eventAttendanceMode Online
    o lugar VirtualLocation. Los mixtos (MixedEventAttendanceMode) no se excluyen."""
    if not isinstance(node, dict): return False
    mode = str(node.get("eventAttendanceMode") or "")
    locations = node.get("location"); locations = locations if isinstance(locations, list) else [locations]
    types = {str(l.get("@type") or "") for l in locations if isinstance(l, dict)}
    return mode.endswith("OnlineEventAttendanceMode") or (bool(types) and types <= {"VirtualLocation"})


def exclude_online_events(conn):
    """Marca como excluidos (sin borrar nada) los registros venue_* ya archivados
    que son eventos solo en línea, y anota el motivo en review_flags. Idempotente;
    no toca registros que un editor haya publicado expresamente."""
    changed = flagged = 0
    with conn:
        for source, record_id, raw_text, eligibility in conn.execute("SELECT source,id,raw_json,eligibility FROM source_records WHERE source LIKE 'venue_%'").fetchall():
            try: node = (json.loads(raw_text) or {}).get("item")
            except (TypeError, ValueError): continue
            if not is_online_event(node): continue
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_decisions'").fetchone() and \
               (conn.execute("SELECT status FROM publication_decisions WHERE source=? AND id=?", (source, record_id)).fetchone() or ("",))[0] == "published":
                continue
            flagged += conn.execute("INSERT OR IGNORE INTO review_flags VALUES (?,?,?)", (source, record_id, ONLINE_REASON)).rowcount
            if eligibility != "exclude":
                conn.execute("UPDATE source_records SET eligibility='exclude' WHERE source=? AND id=?", (source, record_id)); changed += 1
    return {"newly_excluded": changed, "flagged": flagged}


def sync_enabled(conn, venues=None, fetcher=fetch, timeout=25, census_path=CENSUS_PATH):
    venues = venues if venues is not None else load_venues()
    # The census may have found the real programme page; use it unless the
    # operator pinned an agenda_url explicitly.
    try: suggested = {r["slug"]: r.get("suggested_url") for r in json.loads(Path(census_path).read_text(encoding="utf-8")).get("results", [])}
    except (OSError, json.JSONDecodeError, TypeError): suggested = {}
    venues = [{**v, "agenda_url": v.get("agenda_url") or suggested.get(v["slug"]) or v["url"]} for v in venues]
    migration = migrate_record_ids(conn, venues)
    # Una ticketera con API propia configurada (clave en .env) ya no se lee
    # por su JSON-LD: lo hace su conector (p. ej. src/ticketmaster_api.py).
    from src.ticketmaster_api import load_key as ticketmaster_key
    api_ready = {"ticketmaster": bool(ticketmaster_key())}
    results = [sync_venue(conn, venue, fetcher, timeout) for venue in venues if venue.get("enabled") and not api_ready.get(venue.get("api", ""), False)]
    status = "completed" if all(r["status"] == "completed" for r in results) else "failed"
    online = exclude_online_events(conn)
    return {"status": status, "venues": results, "rows_received": sum(r["rows_received"] for r in results), "rows_mutated": sum(r["rows_mutated"] for r in results), "id_migration": migration, "online_excluded": online}
