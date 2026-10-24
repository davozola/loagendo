"""Fechas de la web oficial de cada exposición: manda la fuente original (21-10-2026).

Las agendas agregadas (Ajuntament, Generalitat, GRAF) a veces no dan las mismas fechas que el
museo: Perriand 6-10 → 28-3 en el Ajuntament y 9-10 → 28-2 en la Fundació Miró; «La força d'un
somni compartit» 19-9 → 1-12 en el Ajuntament y 18-9 → 31-12 en su web. Decisión de David: la
página oficial manda.

Para cada exposición en curso o próxima se buscan los enlaces a la web del propio centro que ya
traen sus fichas (nunca portadas, redes, ticketeras ni las propias agendas agregadas) y se lee esa
página:
  · la página tiene que ser de esa exposición: comparte palabras propias con el título;
  · fechas de schema.org (Event/ExhibitionEvent startDate/endDate) si las hay; si no, el primer
    rango de fechas del texto, mejor el que va tras «Fechas / Dates / Data»; con «a juny 2027»
    el final es el mes (se guarda el último día y la precisión «mes», y se muestra la cita);
  · el rango tiene que ser plausible para esa ficha (empieza a menos de cuatro meses de la fecha
    de la fuente o se solapa con ella).
Se guarda la cita literal y la URL. Nada se borra: la ficha conserva sus fechas de origen y la
pública muestra las de la web oficial con la cita. Se respeta robots.txt; cada exposición se
vuelve a mirar a los 7 días.
"""
from __future__ import annotations

import calendar
import datetime as dt
import html
import json
import re
import sqlite3
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlsplit

from src.organizer_text import SKIP_HOSTS, _words

RECHECK_DAYS = 7
FREE_FIX = "2026-10-24T10:00:00+00:00"   # antes, un precio 0 de schema.org se guardaba como «Gratis»
AGGREGATORS = re.compile(r"(?:^|\.)(?:gencat\.cat|graf\.cat|git\.io|barcelona\.cat|bcn\.cat|guia\.barcelona\.cat|agendaculturalbarcelona\.\w+|timeout\.\w+|songkick\.com|xceed\.me)$")
ASSET = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|pdf|css|js|ico|mp4|mp3)(?:\?|$)", re.I)

MONTHS = {}
for n, names in enumerate([("gener", "enero", "january", "gen", "ene", "jan"), ("febrer", "febrero", "february", "feb", "febr"),
                           ("marc", "marzo", "march", "mar"), ("abril", "april", "abr", "apr"), ("maig", "mayo", "may"),
                           ("juny", "junio", "june", "jun"), ("juliol", "julio", "july", "jul"), ("agost", "agosto", "august", "ago", "aug"),
                           ("setembre", "septiembre", "setiembre", "september", "set", "sep", "sept"), ("octubre", "october", "oct"),
                           ("novembre", "noviembre", "november", "nov"), ("desembre", "diciembre", "december", "des", "dic", "dec")], 1):
    for name in names: MONTHS[name] = n
MONTH_RE = r"(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
SEP = r"\s*(?:-|–|—|a|al|fins al|fins a|fins el|hasta el|hasta|to|until|till)\s*"
NUM = r"(\d{1,2})\s*[/.]\s*(\d{1,2})\s*[/.]\s*(\d{4})"
DAY = r"(\d{1,2})(?:\s+de\s+|\s+d'\s*|\s+del\s+|\s+)" + MONTH_RE + r"(?:\s*,?\s*(?:de\s+|del\s+)?(\d{4}))?"
R_NUM = re.compile(NUM + SEP + NUM)
R_TEXT = re.compile(r"(?:\b(?:del|des del|desde el|desde|from)\s+)?\b" + DAY + SEP + r"(?:el\s+)?" + DAY)
R_MONTH_END = re.compile(r"(?:\b(?:del|des del|desde el|desde|from)\s+)?\b" + DAY + SEP + r"(?:(?:de|d')\s*)?" + MONTH_RE + r"\s+(?:de\s+)?(\d{4})\b")
R_DAYS = re.compile(r"(?:\b(?:del|des del|desde el|desde|from)\s+)?\b(\d{1,2})" + SEP + r"(\d{1,2})(?:\s+de\s+|\s+d'\s*|\s+del\s+|\s+)" + MONTH_RE + r"\s*,?\s*(?:de\s+|del\s+)?(\d{4})")
LABEL = re.compile(r"(?:dates|data|fechas|fecha|dates i horaris|fechas y horarios|when|cuando|quan)\s*:?\s*$")


def _fold(text):
    """Minúsculas sin acentos, carácter a carácter (las posiciones son las del original, para citarlo tal cual)."""
    out = []
    for ch in str(text or ""):
        if ch in "–—‐‑−": out.append("-"); continue
        if ch in "’`´": out.append("'"); continue
        base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()[:1]
        out.append(base.lower() if base else " ")
    return "".join(out)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "dt", "dd", "tr", "td", "span"}

    def __init__(self):
        super().__init__(convert_charrefs=True); self.out = []; self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP: self.skip += 1
        elif tag in self.BLOCK: self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip: self.skip -= 1
        elif tag in self.BLOCK: self.out.append("\n")

    def handle_data(self, data):
        if not self.skip: self.out.append(data)


def page_text(page):
    p = _Text()
    try: p.feed(page or "")
    except Exception: pass
    lines = [" ".join(l.split()) for l in "".join(p.out).split("\n")]
    return "\n".join(l for l in lines if l)


def _date(y, m, d):
    try: return dt.date(int(y), int(m), int(d))
    except (TypeError, ValueError): return None


def _year_ok(d):
    return d is not None and 2015 <= d.year <= 2040


def ranges(text):
    """[(inicio, fin, precisión, cita, posición)] de un texto. Precisión 'day' o 'month'."""
    folded = _fold(text)
    out = []
    for m in R_NUM.finditer(folded):
        a, b = _date(m[3], m[2], m[1]), _date(m[6], m[5], m[4])
        if _year_ok(a) and _year_ok(b) and a <= b: out.append((a, b, "day", m.start(), m.end()))
    for m in R_TEXT.finditer(folded):
        d1, m1, y1, d2, m2, y2 = m.groups()
        if not y2: continue
        y1 = y1 or (int(y2) - 1 if MONTHS[m1] > MONTHS[m2] else y2)
        a, b = _date(y1, MONTHS[m1], d1), _date(y2, MONTHS[m2], d2)
        if _year_ok(a) and _year_ok(b) and a <= b: out.append((a, b, "day", m.start(), m.end()))
    for m in R_DAYS.finditer(folded):
        d1, d2, mo, y = m.groups()
        a, b = _date(y, MONTHS[mo], d1), _date(y, MONTHS[mo], d2)
        if _year_ok(a) and _year_ok(b) and a <= b and not any(s <= m.start() < e for *_, s, e in out): out.append((a, b, "day", m.start(), m.end()))
    for m in R_MONTH_END.finditer(folded):
        d1, m1, y1, m2, y2 = m.groups()
        if not y1: continue
        a = _date(y1, MONTHS[m1], d1)
        b = _date(y2, MONTHS[m2], calendar.monthrange(int(y2), MONTHS[m2])[1]) if MONTHS.get(m2) else None
        if _year_ok(a) and _year_ok(b) and a <= b and not any(s <= m.start() < e for *_, s, e in out): out.append((a, b, "month", m.start(), m.end()))
    out.sort(key=lambda r: r[3])
    return [(a, b, p, " ".join(text[s:e].split()), s) for a, b, p, s, e in out]


def jsonld_dates(page):
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page or "", re.S | re.I):
        try: data = json.loads(html.unescape(block.strip()))
        except ValueError: continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                types = node.get("@type"); types = types if isinstance(types, list) else [types]
                if any(str(t).endswith("Event") for t in types) and node.get("startDate") and node.get("endDate"):
                    a, b = _date(*str(node["startDate"])[:10].split("-")), _date(*str(node["endDate"])[:10].split("-")) if len(str(node["endDate"])) >= 10 else None
                    if _year_ok(a) and _year_ok(b) and a <= b: return a, b, str(node.get("name") or "")
                stack += [v for v in node.values() if isinstance(v, (dict, list))]
            elif isinstance(node, list): stack += node
    return None


def choose(text, record_start, record_end):
    """El rango de la página que corresponde a la ficha, o None."""
    folded = _fold(text)
    plausible = [r for r in ranges(text) if abs((r[0] - record_start).days) <= 120 or (r[0] <= record_end and r[1] >= record_start)]
    if not plausible: return None
    labelled = [r for r in plausible if LABEL.search(folded[max(0, r[4] - 30):r[4]].strip())]
    return (labelled or plausible)[0]


def usable(url):
    parts = urlsplit(str(url or ""))
    host = parts.netloc.lower().split(":")[0]
    if parts.scheme not in ("http", "https") or not host or SKIP_HOSTS.search(host) or AGGREGATORS.search(host) or ASSET.search(parts.path): return False
    return parts.path.strip("/") != ""


def links_of(raw_json, title):
    """Enlaces de la ficha a una página propia de la exposición, los que comparten palabras con el título primero."""
    urls = []
    for u in re.findall(r'https?://[^"\'\s<>\\]+', raw_json or ""):
        u = html.unescape(u).rstrip(".,);")
        if usable(u) and u not in urls: urls.append(u)
    words = _words(title)
    scored = sorted(urls, key=lambda u: -len(words & _words(urlsplit(u).path.replace("-", " ").replace("_", " "))))
    return [u for u in scored if words & _words(urlsplit(u).path.replace("-", " ").replace("_", " "))][:2] or scored[:1]


def initialize(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS official_dates (source TEXT NOT NULL, id TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
      start_date TEXT NOT NULL DEFAULT '', end_date TEXT NOT NULL DEFAULT '', end_precision TEXT NOT NULL DEFAULT 'day',
      quote TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY(source, id))""")


def candidates(conn, limit, today=None):
    today = (today or dt.date.today()).isoformat()
    retry = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec="seconds")
    return conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), r.raw_json FROM source_records r
        LEFT JOIN official_dates o ON o.source=r.source AND o.id=r.id
        WHERE r.kind='exhibition' AND r.end_date>=? AND r.eligibility<>'exclude' AND r.source NOT LIKE 'venue_ia_%'
          AND (o.id IS NULL OR o.checked_at<?)
        ORDER BY (o.id IS NOT NULL), r.start_date LIMIT ?""", (today, retry, limit)).fetchall()


def read(url, title, start, end, fetcher, timeout):
    """(estado, inicio, fin, precisión, cita)."""
    status, final, page = fetcher(url, timeout)
    if status != 200: return f"http_{status}", None, None, "", ""
    text = page_text(page)
    m = re.search(r"<title>(.*?)</title>", page or "", re.I | re.S)
    ptitle = html.unescape(m.group(1)) if m else ""
    if not (_words(title) & (_words(ptitle) | _words(urlsplit(final or url).path.replace("-", " ")) | _words(text[:600]))): return "no_es_de_la_exposicion", None, None, "", ""
    rs, re_ = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    ld = jsonld_dates(page)
    if ld and (abs((ld[0] - rs).days) <= 120 or (ld[0] <= re_ and ld[1] >= rs)) and (not ld[2] or _words(title) & _words(ld[2])):
        return "ok", ld[0], ld[1], "day", f"schema.org: {ld[0].isoformat()} – {ld[1].isoformat()}"
    pick = choose(text, rs, re_)
    if not pick: return "sin_fechas", None, None, "", ""
    return "ok", pick[0], pick[1], pick[2], pick[3]


def run(conn, limit=200, fetcher=None, timeout=15, today=None):
    from src.venue_feeds import fetch, robots_allows
    import time
    initialize(conn); fetcher = fetcher or fetch
    seen, done, ok = {}, 0, 0
    for source, rid, title, start, end, raw in candidates(conn, limit, today):
        result = ("sin_enlace", None, None, "", ""); used = ""
        for url in links_of(raw, title):
            used = url
            try:
                if url in seen: result = seen[url]
                elif fetcher is fetch and not robots_allows(url): result = ("robots", None, None, "", "")
                else:
                    result = read(url, title, start, end, fetcher, timeout); seen[url] = result
                    if fetcher is fetch: time.sleep(0.5)
            except Exception as error:
                result = ("error: " + type(error).__name__, None, None, "", "")
            if result[0] == "ok": break
        status, a, b, precision, quote = result
        done += 1; ok += status == "ok"
        with conn:
            conn.execute("""INSERT INTO official_dates(source,id,url,start_date,end_date,end_precision,quote,status,checked_at) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET url=excluded.url,start_date=excluded.start_date,end_date=excluded.end_date,end_precision=excluded.end_precision,
                quote=excluded.quote,status=excluded.status,checked_at=excluded.checked_at""",
                         (source, rid, used, a.isoformat() if a else "", b.isoformat() if b else "", precision or "day", quote[:200], status,
                          dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
    return {"status": "completed", "checked": done, "with_dates": ok}


def official(conn):
    """{(source, id): {start, end, end_precision, url, quote}} con fechas aceptadas."""
    try:
        return {(s, i): {"start": a, "end": b, "end_precision": p, "url": u, "quote": q}
                for s, i, a, b, p, u, q in conn.execute("SELECT source,id,start_date,end_date,end_precision,url,quote FROM official_dates WHERE status='ok' AND start_date<>''")}
    except sqlite3.DatabaseError:
        return {}


# ---------- página oficial de cada acto (hora y precio), 21-10-2026 ----------
# Para los actos que solo llegan por agregadores (Ajuntament, Generalitat, GRAF) y traen el enlace a la
# página del propio acto: de esa página se toman con reglas la hora y el precio que publica en schema.org
# (mandan sobre los del agregador) y un extracto del texto, que se añade al texto de la ficha para que la
# extracción con IA (src/ai_extract.py, cita literal comprobada) complete lo que falte.
AGGREGATOR_SOURCES = ("opendatabcn_agenda", "guiabcn", "generalitat", "web_graf", "diba_turismo")
AHEAD_DAYS = 60
EXCERPT = 1800


def initialize_pages(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS official_pages (source TEXT NOT NULL, id TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
      times_json TEXT NOT NULL DEFAULT '{}', price TEXT NOT NULL DEFAULT '', free INTEGER NOT NULL DEFAULT 0, excerpt TEXT NOT NULL DEFAULT '',
      status TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY(source, id))""")
    # Pases del día que la página enumera («Tres passis: 12-12.30h / 16-16.30h / 17-17.30h»), 24-10-2026.
    if "sessions_json" not in {r[1] for r in conn.execute("PRAGMA table_info(official_pages)")}:
        conn.execute("ALTER TABLE official_pages ADD COLUMN sessions_json TEXT NOT NULL DEFAULT '{}'")


def page_candidates(conn, limit, today=None):
    today = today or dt.date.today()
    retry = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RECHECK_DAYS)).isoformat(timespec="seconds")
    marks = ",".join("?" * len(AGGREGATOR_SOURCES))
    rows = conn.execute(f"""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), r.raw_json FROM source_records r
        LEFT JOIN official_pages o ON o.source=r.source AND o.id=r.id
        WHERE r.source IN ({marks}) AND r.kind<>'exhibition' AND r.end_date>=? AND r.start_date<=? AND r.eligibility<>'exclude'
          AND NOT (r.source='guiabcn' AND EXISTS (SELECT 1 FROM source_records t WHERE t.source='opendatabcn_agenda' AND t.id=r.id))
          AND (o.id IS NULL OR o.checked_at<? OR (o.price='Gratis' AND o.checked_at<'2026-10-24T10:00:00+00:00'))
        ORDER BY (o.id IS NOT NULL), r.start_date LIMIT ?""", (*AGGREGATOR_SOURCES, today.isoformat(), (today + dt.timedelta(days=AHEAD_DAYS)).isoformat(), retry, limit * 3)).fetchall()
    # Agendas de sala leídas con IA (23-10-2026): la página propia del acto suele traer la hora en schema.org
    # (Marula: «Bex + Ay Trick» 21:00). Primero estas: son de la propia sala. Desde el 24-10-2026 también las
    # que ya tienen hora (después de las que no): la página trae además la edad, el precio y los demás pases
    # («Tres passis: 12-12.30h / 16-16.30h / 17-17.30h», Arts Santa Mònica), que el listado no da.
    try: own = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), r.source_url FROM source_records r
        LEFT JOIN official_pages o ON o.source=r.source AND o.id=r.id
        WHERE r.source LIKE 'venue_ia_%' AND r.end_date>=? AND r.start_date<=? AND r.eligibility<>'exclude' AND r.kind<>'exhibition'
          AND (o.id IS NULL OR o.checked_at<? OR (o.price='Gratis' AND o.checked_at<'2026-10-24T10:00:00+00:00'))
        ORDER BY (o.id IS NOT NULL),
                 EXISTS (SELECT 1 FROM candidate_occurrences c WHERE c.source=r.source AND c.id=r.id AND c.local_time<>''),
                 r.start_date LIMIT ?""", (today.isoformat(), (today + dt.timedelta(days=AHEAD_DAYS)).isoformat(), retry, limit)).fetchall()
    except sqlite3.OperationalError: own = []  # base sin tabla de sesiones (pruebas antiguas)
    out = []
    for source, rid, title, start, end, url in own:
        if url and usable(url) and _words(title) & _words(urlsplit(url).path.replace("-", " ").replace("_", " ")):
            out.append((source, rid, title, start, end, url))
        if len(out) >= limit: return out
    for source, rid, title, start, end, raw in rows:
        words = _words(title)
        # Solo un enlace a la página de ESTE acto: su ruta comparte palabras propias con el título.
        url = next((u for u in links_of(raw, title) if words & _words(urlsplit(u).path.replace("-", " ").replace("_", " "))), "")
        if url: out.append((source, rid, title, start, end, url))
        if len(out) >= limit: break
    return out


def _price_of(offers):
    offers = offers if isinstance(offers, list) else [offers]
    values = []
    for o in offers:
        if not isinstance(o, dict): continue
        for k in ("price", "lowPrice", "highPrice"):
            try:
                v = float(str(o.get(k)).replace(",", "."))
                values.append(v)
            except (TypeError, ValueError): pass
    if not values: return "", False
    lo, hi = min(values), max(values)
    # Un precio 0 en schema.org no es «gratis» (24-10-2026): muchas webs lo dejan a 0 cuando no lo rellenan
    # (Poliorama, «Gran Gala Flamenco», con entradas de pago). Gratis solo con isAccessibleForFree.
    if hi == 0: return "", False
    fmt = lambda v: (f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")) + " €"
    return (fmt(lo) if lo == hi else f"{fmt(lo)} – {fmt(hi)}"), False


def page_facts(page, title, start, end):
    """Hora por día y precio de los actos schema.org de la página que son este acto."""
    from src.venue_feeds import jsonld_events, _date, _time
    words = _words(title); times, price, free = {}, "", False
    for node in jsonld_events(page or ""):
        if not (words & _words(str(node.get("name") or ""))): continue
        day, hour = _date(node.get("startDate")), _time(node.get("startDate"))
        if day and start <= day <= end and hour and hour != "00:00": times.setdefault(day, hour)
        if not price and node.get("offers"): price, free = _price_of(node.get("offers"))
        if node.get("isAccessibleForFree") in (True, "true", "True", "1") and not price: price, free = "Gratis", True
    # Calendario de funciones impreso en la página (Balañà: cada día un bloque data-calendar-sessions con sus
    # pases, 23-10-2026). Solo completa los días que schema.org no da.
    for day, block in re.findall(r'data-calendar-sessions="(\d{4}-\d{2}-\d{2})"(.*?)(?=data-calendar-sessions=|</section>|$)', page or "", re.S):
        hours = re.findall(r'sessionTime[^>]*>\s*(?:<span>)?\s*(\d{1,2}):(\d{2})', block)
        if hours and start <= day <= end and day not in times:
            times[day] = f"{int(hours[0][0]):02d}:{hours[0][1]}"
    return times, price, free


def excerpt_of(text, title):
    """El trozo del texto de la página que habla del acto: desde la primera línea que comparte palabras con el título."""
    words = _words(title); lines = text.split("\n")
    first = next((i for i, l in enumerate(lines) if words & _words(l)), None)
    return "\n".join(lines[first:])[:EXCERPT] if first is not None else ""


PASSES_RX = re.compile(r"\b(?:\w+\s+)?(?:passis|passi|passades|pases|pase|sessions|sessio|sesiones|sesion|funcions|funciones)\s*:\s*([^\n]{4,160})")


def passes_of(text):
    """Horas de inicio de los pases que la página enumera en una línea con su nombre («Tres passis:
    12-12.30h / 16-16.30h / 17-17.30h» → 12:00, 16:00, 17:00). Solo si son dos o más: una sola hora ya la
    da el resto del lector. De cada rango («16-16.30h») cuenta el inicio."""
    for m in PASSES_RX.finditer(_fold(text)):
        line = m.group(1)
        if not re.search(r"\d", line): continue
        starts = []
        for part in re.split(r"\s*(?:/|,|;|\||\bi\b|\by\b|\band\b)\s*", line):
            part = part.strip()
            mm = re.match(r"([01]?\d|2[0-3])(?:[:.h]([0-5]\d))?\s*h?(?:\s*(?:-|–|a)\s*([01]?\d|2[0-3])(?:[:.h]([0-5]\d))?\s*h?)?$", part)
            if not mm: continue
            if not (mm.group(2) or mm.group(3) or re.search(r"h", part)): continue  # «3» suelto no es una hora
            starts.append(f"{int(mm.group(1)):02d}:{mm.group(2) or '00'}")
        starts = sorted(set(starts))
        if len(starts) >= 2: return starts
    return []


def read_page(url, title, start, end, fetcher, timeout):
    status, final, page = fetcher(url, timeout)
    if status != 200: return {"status": f"http_{status}"}
    m = re.search(r"<title>(.*?)</title>", page or "", re.I | re.S)
    ptitle = html.unescape(m.group(1)) if m else ""
    words = _words(title)
    if not (words & (_words(ptitle) | _words(urlsplit(final or url).path.replace("-", " ")))): return {"status": "no_es_del_acto"}
    times, price, free = page_facts(page, title, start, end)
    text = page_text(page)
    if not times and start == end:
        # Página propia de un acto de un solo día sin schema.org (Sala Upload, 23-10-2026): si en todo su texto
        # hay una sola hora escrita, es la del acto. Con dos o más (puertas y concierto, horario de taquilla…) no se elige.
        clocks = {f"{int(h):02d}:{m}" for h, m in re.findall(r"(?<![\d:.])([01]?\d|2[0-3])[:.]([0-5]\d)(?![\d:])\s*h?", text)}
        if len(clocks) == 1 and clocks != {"00:00"}: times = {start: clocks.pop()}
    sessions = {}
    if start == end:
        passes = passes_of(text)
        if passes: sessions = {start: passes}
    return {"status": "ok", "times": times, "price": price, "free": free, "excerpt": excerpt_of(text, title), "sessions": sessions}


def run_pages(conn, limit=300, fetcher=None, timeout=15, today=None):
    from src.venue_feeds import fetch, robots_allows
    import time
    initialize_pages(conn); fetcher = fetcher or fetch
    done = ok = facts = 0
    for source, rid, title, start, end, url in page_candidates(conn, limit, today):
        try:
            if fetcher is fetch and not robots_allows(url): res = {"status": "robots"}
            else:
                res = read_page(url, title, start, end, fetcher, timeout)
                if fetcher is fetch: time.sleep(0.5)
        except Exception as error:
            res = {"status": "error: " + type(error).__name__}
        done += 1; ok += res["status"] == "ok"; facts += bool(res.get("times") or res.get("price"))
        with conn:
            conn.execute("""INSERT INTO official_pages(source,id,url,times_json,price,free,excerpt,status,checked_at,sessions_json) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET url=excluded.url,times_json=excluded.times_json,price=excluded.price,free=excluded.free,
                excerpt=excluded.excerpt,status=excluded.status,checked_at=excluded.checked_at,sessions_json=excluded.sessions_json""",
                         (source, rid, url, json.dumps(res.get("times") or {}), res.get("price") or "", int(bool(res.get("free"))), res.get("excerpt") or "",
                          res["status"], dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), json.dumps(res.get("sessions") or {})))
    return {"checked": done, "pages_ok": ok, "with_time_or_price": facts}


def pages(conn):
    """{(source, id): {url, times, price, free, excerpt}} de páginas oficiales leídas."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(official_pages)")}
        sess = "sessions_json" if "sessions_json" in cols else "'{}'"
        out = {}
        for s, i, u, t, p, f, x, ss, at in conn.execute(f"SELECT source,id,url,times_json,price,free,excerpt,{sess},checked_at FROM official_pages WHERE status='ok'"):
            if p == "Gratis" and at < FREE_FIX: p, f = "", 0   # «Gratis» por un precio 0, leído antes del arreglo
            out[(s, i)] = {"url": u, "times": json.loads(t or "{}"), "price": p, "free": bool(f), "excerpt": x, "sessions": json.loads(ss or "{}")}
        return out
    except sqlite3.DatabaseError:
        return {}


def run_all(conn, job=None, fetcher=None, today=None):
    job = job or {}
    dates = run(conn, job.get("limit", 300), fetcher=fetcher, timeout=job.get("timeout_seconds", 15), today=today)
    acts = run_pages(conn, job.get("limit_pages", 300), fetcher=fetcher, timeout=job.get("timeout_seconds", 15), today=today)
    return {"status": "completed", "exposiciones": dates, "actos": acts}
