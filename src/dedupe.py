"""Blocked duplicate-candidate detection across sources.

The snapshot pipeline compared every pair of records (O(n²)); with ~10.000
live records that is 50 million comparisons and it never ran after a sync, so
the ``match_candidates`` table stayed frozen at three rows. This module keeps
the same conservative decision rules but only compares records that share
title tokens and overlap in time. It never merges: it writes review-only
candidate pairs with the rule that produced them, so an editor (or a later
grouping step) can trace every suggestion back to its evidence.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import re
import sqlite3

from src.pipeline import day, delta, geo_meters, title_similarity, tokens

GENERATOR = "dedupe-blocked-v1"
MIN_TITLE_SIMILARITY = 0.79
MIN_TITLE_SIMILARITY_SAME_SLOT = 0.55
MIN_TITLE_SIMILARITY_RARE_TOKEN = 0.45
RARE_TOKEN_MAX_DOCS = 6
MAX_TOKEN_DOCUMENT_FREQUENCY = 400  # tokens shared by more records are not discriminative
# Normalised short names used by first-party agendas for venues GuiaBCN lists
# under their full name. Mapping names is venue metadata, not event data.
VENUE_ALIASES = {
    "cccb": "centre de cultura contemporania de barcelona cccb",
    "macba": "museu d art contemporani de barcelona macba",
    "l auditori": "l auditori de barcelona",
    "auditori": "l auditori de barcelona",
    "teatre lliure": "teatre lliure gracia montjuic",
    "gracia": "teatre lliure gracia",
    "montjuic": "teatre lliure montjuic",
}


def _venue_text(name):
    base = " ".join(str(name or "").casefold().replace("'", " ").split())
    # "Sala Upload Barcelona", "Upload" and "Sala Upload" are one hall, and the
    # directory's aliases map a hall's rooms ("Sala 1 Pau Casals") to its venue.
    from src.venue_directory import normalise, site_for
    entry = site_for(base)
    if entry: return "venue:" + entry["slug"]
    if base in VENUE_ALIASES: return VENUE_ALIASES[base]
    return normalise(base) or base


NUMBER_TOKEN = re.compile(r"\b(?:\d{1,3}|grup [a-z0-9]+|grupo [a-z0-9]+|nivell \w+|nivel \w+)\b")  # years (2026) are not distinguishing


def _distinguishing_numbers(a_title, b_title):
    """Titles that differ only in a number or group letter ("de 5 a 7 anys" /
    "de 7 a 9 anys", "grup A" / "grup B") are sibling records, never twins."""
    na = set(NUMBER_TOKEN.findall(str(a_title or "").casefold())); nb = set(NUMBER_TOKEN.findall(str(b_title or "").casefold()))
    return bool(na or nb) and na != nb


def _venue_similarity(a_venues, b_venues):
    return max((title_similarity(_venue_text(x), _venue_text(y)) for x in a_venues for y in b_venues), default=0)


def load_records(conn: sqlite3.Connection, *, since: str | None = None) -> list[dict]:
    """Records with their venues; ``since`` keeps only rows still active on that date."""
    venues: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for s, i, name, lat, lon in conn.execute("SELECT source,id,venue,lat,lon FROM source_venues ORDER BY source,id,seq"):
        venues[(s, i)].append({"name": name or "", "coords": (lat, lon) if lat is not None and lon is not None else None})
    where, params = "", ()
    if since:
        where, params = "WHERE end_date>=?", (since,)
    out = []
    for s, i, title, start, end, kind, eligibility in conn.execute(f"SELECT source,id,title,start_date,end_date,kind,eligibility FROM source_records {where}", params):
        out.append({"source": s, "id": i, "key": f"{s}:{i}", "title": title or "", "start": start or "", "end": end or "", "kind": kind, "eligibility": eligibility, "venues": venues.get((s, i), [])})
    return out


def candidate_pairs(records: list[dict]) -> list[dict]:
    """Review-only pairs. Same rules as the snapshot matcher, blocked by shared title tokens."""
    by_token: dict[str, list[int]] = collections.defaultdict(list)
    record_tokens = []
    for index, record in enumerate(records):
        toks = tokens(record["title"])
        record_tokens.append(toks)
        for token in toks:
            by_token[token].append(index)
    shared: dict[tuple[int, int], int] = collections.Counter()
    for token, members in by_token.items():
        if len(members) > MAX_TOKEN_DOCUMENT_FREQUENCY or len(members) < 2:
            continue
        for position, first in enumerate(members):
            for second in members[position + 1:]:
                shared[(first, second)] += 1
    out = []
    for (ia, ib), count in shared.items():
        a, b = records[ia], records[ib]
        smallest = min(len(record_tokens[ia]), len(record_tokens[ib]))
        if count < 2 and smallest > 2:
            continue
        if a["source"] == b["source"] and a["source"] != "diba_bibliotecas":
            continue
        a0, a1, b0, b1 = map(day, (a["start"], a["end"], b["start"], b["end"]))
        if None in (a0, a1, b0, b1) or a0 > b1 or b0 > a1:
            continue
        similarity = title_similarity(a["title"], b["title"])
        va = [v["coords"] for v in a["venues"] if v["coords"]]
        vb = [v["coords"] for v in b["venues"] if v["coords"]]
        distances = [geo_meters(x, y) for x in va for y in vb]
        dist = min(distances) if distances else None
        venue_sim = _venue_similarity([v["name"] for v in a["venues"]], [v["name"] for v in b["venues"]])
        same_place = (dist is not None and dist <= 200) or venue_sim >= 0.8
        strict_dates = a["start"] == b["start"] and a["end"] == b["end"]
        # Same day, same place and a one-day act: a lower title bar is enough
        # ('Gustavo Dudamel – Filharmònica' vs 'Concert "Gustavo Dudamel", amb la Filarmònica').
        threshold = MIN_TITLE_SIMILARITY if not (strict_dates and same_place and a["start"] == a["end"]) else MIN_TITLE_SIMILARITY_SAME_SLOT
        # Same dates, same place and a rare name in common ("MIRA Digital Arts
        # Festival" / "MIRA Festival 2026"): the name carries the identity even
        # when the rest of the title differs.
        rare_shared = [t for t in record_tokens[ia] & record_tokens[ib] if len(t) >= 4 and len(by_token[t]) <= RARE_TOKEN_MAX_DOCS]
        short_span = (delta(a["start"], a["end"]) or 0) <= 4
        if strict_dates and same_place and short_span and rare_shared:
            threshold = min(threshold, MIN_TITLE_SIMILARITY_RARE_TOKEN)
        # Same dates and place for a short act (up to four days): a lower bar,
        # as for one-day acts, so a two-day festival told two ways collapses.
        if strict_dates and same_place and short_span and not _distinguishing_numbers(a["title"], b["title"]):
            threshold = min(threshold, MIN_TITLE_SIMILARITY_SAME_SLOT)
        if similarity < threshold:
            continue
        if _distinguishing_numbers(a["title"], b["title"]) and similarity < 0.97:
            continue
        if dist is not None and dist > 200 and venue_sim < 0.8:
            continue
        if dist is None and venue_sim < 0.55:
            continue
        a_span, b_span = delta(a["start"], a["end"]), delta(b["start"], b["end"])
        if a["source"] == b["source"] and ((a_span or 0) > 7 or (b_span or 0) > 7):
            continue
        risks = ["TITLE_SIMILARITY_IS_NOT_IDENTITY"]
        if a["kind"] == "program" or b["kind"] == "program":
            risks.append("PROGRAM_CHILD_COLLISION_RISK")
        if not strict_dates:
            risks.append("DATE_RANGE_NOT_EQUAL")
        if same_place and strict_dates and (a["start"] == a["end"] or short_span):
            risks.append("SAME_DAY_SAME_PLACE")
        if strict_dates and same_place and short_span and rare_shared:
            risks.append("SAME_DATES_SAME_PLACE_RARE_TOKEN")
        if a["source"] == b["source"]:
            risks.append("SAME_SOURCE_REPEATED_RECORD")
        if dist is None:
            risks.append("VENUE_MATCHED_BY_NAME_ONLY")
        first, second = sorted((a, b), key=lambda r: r["key"])
        out.append({"a": first["key"], "b": second["key"], "title_a": first["title"], "title_b": second["title"], "similarity_heuristic": similarity,
                    "geo_meters": round(dist, 1) if dist is not None else None, "venue_similarity_heuristic": round(venue_sim, 4),
                    "start_a": first["start"], "start_b": second["start"], "review_only": True, "risks": risks})
    return sorted(out, key=lambda x: (-x["similarity_heuristic"], len(x["risks"]), x["a"], x["b"]))


def initialize(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS match_candidates(a TEXT,b TEXT,score REAL,reason TEXT,PRIMARY KEY(a,b))")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(match_candidates)")}
    if "generated_by" not in columns:
        conn.execute("ALTER TABLE match_candidates ADD COLUMN generated_by TEXT NOT NULL DEFAULT 'snapshot-pipeline'")
    if "generated_at" not in columns:
        conn.execute("ALTER TABLE match_candidates ADD COLUMN generated_at TEXT NOT NULL DEFAULT ''")
    if "evidence_json" not in columns:
        conn.execute("ALTER TABLE match_candidates ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")


def refresh_match_candidates(conn: sqlite3.Connection, *, since: str | None = None, now: str | None = None) -> dict:
    """Recompute candidates for records active from ``since`` (default: today).

    Existing rows are upserted by pair, never deleted, so a pair an editor is
    already looking at keeps its identity; ``generated_at`` tells which pairs
    the latest run still supports.
    """
    initialize(conn)
    since = since or dt.date.today().isoformat()
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    records = load_records(conn, since=since)
    pairs = candidate_pairs(records)
    with conn:
        for pair in pairs:
            evidence = {k: pair[k] for k in ("geo_meters", "venue_similarity_heuristic", "start_a", "start_b")}
            conn.execute("""INSERT INTO match_candidates(a,b,score,reason,generated_by,generated_at,evidence_json) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(a,b) DO UPDATE SET score=excluded.score,reason=excluded.reason,generated_by=excluded.generated_by,
                generated_at=excluded.generated_at,evidence_json=excluded.evidence_json""",
                (pair["a"], pair["b"], pair["similarity_heuristic"], ";".join(pair["risks"]), GENERATOR, now, json.dumps(evidence, ensure_ascii=False)))
    by_sources = collections.Counter(tuple(sorted((p["a"].split(":")[0], p["b"].split(":")[0]))) for p in pairs)
    return {"since": since, "records_compared": len(records), "pairs": len(pairs), "generated_by": GENERATOR,
            "by_source_pair": {" + ".join(k): v for k, v in sorted(by_sources.items(), key=lambda x: -x[1])},
            "top": pairs[:10]}


def duplicates_for(conn: sqlite3.Connection, source: str, record_id: str) -> list[dict]:
    """Candidate pairs involving one record, for the detail view."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_candidates'").fetchone():
        return []
    columns = {r[1] for r in conn.execute("PRAGMA table_info(match_candidates)")}
    extra = ",generated_by,generated_at" if {"generated_by", "generated_at"} <= columns else ",'snapshot-pipeline',''"
    key = f"{source}:{record_id}"
    out = []
    for a, b, score, reason, generated_by, generated_at in conn.execute(f"SELECT a,b,score,reason{extra} FROM match_candidates WHERE a=? OR b=? ORDER BY score DESC", (key, key)):
        other = b if a == key else a
        other_source, other_id = other.split(":", 1)
        title = conn.execute("SELECT title FROM source_records WHERE source=? AND id=?", (other_source, other_id)).fetchone()
        out.append({"key": other, "source": other_source, "id": other_id, "title": title[0] if title else "", "score": score,
                    "risks": reason.split(";") if reason else [], "generated_by": generated_by, "generated_at": generated_at, "review_only": True})
    return out


SOURCE_PRIORITY = ("opendatabcn_agenda", "generalitat", "diba_bibliotecas", "diba_turismo", "guiabcn", "web_macba", "web_cccb", "web_auditori", "web_teatre_lliure", "web_centres_civics", "web_conciertos_club")


def source_rank(source):
    """Lower is more authoritative: licensed open data, then the venue's own
    structured data, first-party web agendas, ticketing sites, and last the
    private concert directories (used to discover and cross-check only)."""
    if source in SOURCE_PRIORITY and source != "web_conciertos_club": return SOURCE_PRIORITY.index(source)
    base = len(SOURCE_PRIORITY)
    if source.startswith("venue_"):
        from src.venue_directory import venue_type
        kind = venue_type(source[6:])
        return base + {"ticketing": 20, "aggregator": 30}.get(kind, 5)
    if source == "web_conciertos_club": return base + 31
    return base + 10


def first_party(source):
    """La sala o el centro publicando su propia agenda (lectura de su web o su feed), no una ticketera ni un directorio."""
    if source.startswith("venue_ia_"): return True
    # Las webs propias que se leen aparte (L'Auditori, Teatre Lliure, MACBA, CCCB) también son la sala (26-10-2026).
    from src.data_origin import OWN_WEB
    if source in OWN_WEB: return True
    if source.startswith("venue_"):
        from src.venue_directory import venue_type
        return venue_type(source[6:]) not in ("ticketing", "aggregator")
    return False


DIRECTORY_RANK = len(SOURCE_PRIORITY) + 20  # ticketing sites and private directories rank here or below
COLLAPSE_MIN_SCORE = 0.95
COLLAPSE_MIN_SCORE_SAME_SLOT = 0.6


def _collapsible(score, risks):
    if "DATE_RANGE_NOT_EQUAL" in risks or "SAME_SOURCE_REPEATED_RECORD" in risks:
        return False
    return score >= COLLAPSE_MIN_SCORE or (score >= COLLAPSE_MIN_SCORE_SAME_SLOT and "SAME_DAY_SAME_PLACE" in risks) or (score >= MIN_TITLE_SIMILARITY_RARE_TOKEN and "SAME_DATES_SAME_PLACE_RARE_TOKEN" in risks)


KIDS_MARK = re.compile(r"^(?:kids|infantil|infantils|nens|nenes|ninos|ninas|petits|peques|canalla|nadons|bebes)$")


def _distinct_sessions(conn, a, b):
    """Dos fichas del mismo día y sitio que son sesiones distintas: cada título tiene una palabra que el otro no, y la
    de uno es de público infantil («Monumental Kids Halloween» / «Monumental Club Halloween»). Un prefijo de ciclo
    («Tardes en família: Taller…») no cuenta: ahí uno de los dos títulos no tiene palabras propias."""
    words = {}
    for key in (a, b):
        source, _, rid = key.partition(":")
        row = conn.execute("SELECT title FROM source_records WHERE source=? AND id=?", (source, rid)).fetchone()
        # «Espectacle infantil "X"» y «X – Tour» son lo mismo: el género infantil de la obra no distingue sesiones.
        words[key] = set(re.sub(r"\b(?:espectacle|espectaculo|teatre|teatro|concert|concierto|taller|cinema|musical|activitat) (?:infantil|infantils|familiar)\b", " ", _clean(row[0] if row else "")).split())
    only_a, only_b = words[a] - words[b], words[b] - words[a]
    if not only_a or not only_b: return False
    kids_a, kids_b = any(KIDS_MARK.match(w) for w in only_a), any(KIDS_MARK.match(w) for w in only_b)
    return kids_a != kids_b


def canonical_groups(conn: sqlite3.Connection) -> dict[str, str]:
    """Map every collapsed record key to its canonical twin's key.

    Only near-identical pairs collapse (same dates, and either an almost equal
    title or same day + same place with a clearly similar title). The
    canonical row is chosen by source priority (licensed open data first,
    third-party listings last). Reversible: nothing is written.
    """
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_candidates'").fetchone():
        return {}
    parent: dict[str, str] = {}
    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x]); x = parent[x]
        return x
    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry: parent[rx] = ry
    weak = []
    for a, b, score, reason in conn.execute("SELECT a,b,score,reason FROM match_candidates"):
        risks = (reason or "").split(";")
        if _collapsible(score or 0, risks) and score < COLLAPSE_MIN_SCORE and "SAME_DAY_SAME_PLACE" in risks:
            weak.append((a, b)); continue   # se comprueba abajo: mismo sitio y día, títulos solo parecidos
        if _collapsible(score or 0, risks):
            parent.setdefault(a, a); parent.setdefault(b, b); union(a, b)
    # Mismo día y sitio con títulos solo parecidos (28-10-2026, David): «Monumental Kids Halloween» (12:00, DICE) no es
    # «Monumental Club Halloween» (15:00, Open Data): no se juntan si solo una se dirige al público infantil.
    for a, b in weak:
        if _distinct_sessions(conn, a, b): continue
        parent.setdefault(a, a); parent.setdefault(b, b); union(a, b)
    # Un festival es una sola ficha: sus fichas en otras fuentes y los
    # conciertos sueltos de artistas de su cartel se agrupan en él.
    # Pares que la IA da por el mismo acto con confianza alta (src/ai_assist.py, trazado en ai_suggestions).
    from src.ai_assist import same_pairs
    for a, b in same_pairs(conn):
        parent.setdefault(a, a); parent.setdefault(b, b); union(a, b)
    for a, b in festival_pairs(conn) + act_pairs(conn) + title_pairs(conn) + run_pairs(conn) + contained_pairs(conn) + exhibition_pairs(conn) + umbrella_pairs(conn) + slot_and_session_pairs(conn) + nested_pairs(conn) + same_day_pairs(conn):
        parent.setdefault(a, a); parent.setdefault(b, b); union(a, b)
    groups: dict[str, list[str]] = {}
    for key in list(parent):
        groups.setdefault(find(key), []).append(key)
    # Misma fuente con dos fichas del mismo acto: manda la que cubre más días (no se pierde ninguna fecha).
    spans = {}; dates = {}   # dates: (inicio, días, fin normalizado) — el fin sin la medianoche de las ticketeras
    try:
        members = [k for k in parent]
        for i in range(0, len(members), 500):
            chunk = members[i:i + 500]
            for src, rid, a, b in conn.execute(f"SELECT source,id,start_date,end_date FROM source_records WHERE source||':'||id IN ({','.join('?' * len(chunk))})", chunk):
                try:
                    d0, d1 = dt.date.fromisoformat(str(a)[:10]), dt.date.fromisoformat(_end_of(src, str(a)[:10], str(b)[:10]))
                    spans[f"{src}:{rid}"] = (dt.date.fromisoformat(str(b)[:10]) - d0).days
                    dates[f"{src}:{rid}"] = (d0, (d1 - d0).days, d1)
                except ValueError: pass
    except sqlite3.DatabaseError: pass
    # Manda la fuente original: si el propio centro publica el acto, su ficha es la canónica (fechas,
    # horas, sala) y las demás solo rellenan lo que le falte (texto, imagen, distrito…; borrow_from_twins).
    def rank(key):
        src = key.split(":", 1)[0]
        return (0 if first_party(src) else 1, source_rank(src), -spans.get(key, 0), key)
    out = {}
    for members in groups.values():
        canonical = min(members, key=rank)
        # Que no se pierda ninguna fecha (24-10-2026): si la ficha elegida es una función o un fin de semana (hasta 6
        # días) y otras del grupo tienen fechas fuera de ella («Concert per a nadons»: L'Auditori publica cada función,
        # la Generalitat cada fin de semana y Open Data la temporada), manda la que cubre todas; sus días y horas
        # salen de las funciones (catalog.row_to_event).
        if canonical in dates and dates[canonical][1] <= 6:
            # Las ticketeras no cuentan: alargan las fechas por la medianoche («MIRA» en DICE del 6 al 8).
            pool = [m for m in members if m in dates and m.split(":", 1)[0] not in SINGLE_ACT_SOURCES] or [m for m in members if m in dates]
            known = [dates[m] for m in pool]
            lo, hi = min(d[0] for d in known), max(d[2] for d in known)
            if dates[canonical][0] > lo or dates[canonical][2] < hi:
                covering = [m for m in pool if dates[m][0] <= lo and dates[m][2] >= hi]
                if covering: canonical = min(covering, key=rank)
        for member in members:
            if member != canonical: out[member] = canonical
    return out


# --- Festivales (19-10-2026) -------------------------------------------------
FESTIVAL_WORDS = ("festival", "fest", "biennal", "bienal", "mostra", "muestra")
CORE_STOP = {"festival", "fest", "barcelona", "bcn", "edicio", "edicion", "edition", "de", "del", "la", "el", "les", "los", "i", "y", "and", "the", "a", "en"}
SINGLE_ACT_SOURCES = ("venue_songkick", "web_conciertos_club", "venue_dice", "venue_ticketmaster_es", "venue_xceed")
FESTIVAL_MAX_DAYS = 10
NEAR_KM = 1.5


def _clean(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _core(title):
    """Nombre del festival sin año, edición ni palabras genéricas («MIRA Festival 2026» → {mira})."""
    return {t for t in _clean(title).split() if t not in CORE_STOP and not t.isdigit() and not re.fullmatch(r"\d+(?:a|e|o|th|st|nd|rd)", t)}


def _km(a, b):
    import math
    if None in (a[0], a[1], b[0], b[1]): return None
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


PLACE_STOP = {"sala", "espai", "parc", "placa", "plaza", "carrer", "calle", "barcelona", "bcn", "centre", "centro", "teatre", "teatro", "club", "auditori", "museu", "the", "festival"}


def _same_place(a, b):
    # Las coordenadas de las fuentes de venta a veces son aproximadas (Songkick sitúa
    # «Fira Montjuic» a 2 km del recinto): basta con que coincida el nombre del recinto.
    va, vb = set(_clean(a["venue"]).split()) - CORE_STOP - PLACE_STOP, set(_clean(b["venue"]).split()) - CORE_STOP - PLACE_STOP
    if va & vb: return True
    d = _km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    return d is not None and d <= NEAR_KM


def festival_pairs(conn):
    """Parejas (miembro, festival) que deben ser una sola ficha.

    - Fichas del mismo festival en varias fuentes: mismo nombre esencial
      («MIRA Festival 2026» = «MIRA 2026»), fechas que se solapan y mismo sitio.
    - Conciertos sueltos de un artista del cartel (Songkick, DICE…) dentro de las
      fechas del festival y en su recinto: forman parte del festival.
    Solo se usa el cartel que declaran las fuentes; nada se deduce del título.
    """
    import datetime as dt
    from mvp.catalog import lineup_of
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, r.start_date, r.end_date, v.venue, v.lat, v.lon,
              CASE WHEN r.source IN (%s) THEN r.raw_json ELSE NULL END
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude'""" % ",".join("?" * len(SINGLE_ACT_SOURCES)), (*SINGLE_ACT_SOURCES, today)).fetchall()
    except sqlite3.DatabaseError:
        return []
    def date(v):
        try: return dt.date.fromisoformat(str(v)[:10])
        except ValueError: return None
    records = []
    for source, rid, title, start, end, venue, lat, lon, raw_text in rows:
        a, b = date(start), date(end)
        if not a or not b: continue
        lineup = []
        if raw_text:
            try: lineup = lineup_of(json.loads(raw_text))[0]
            except (ValueError, TypeError): lineup = []
        records.append({"key": f"{source}:{rid}", "source": source, "title": title or "", "start": a, "end": b, "venue": venue or "",
                        "lat": lat, "lon": lon, "lineup": lineup, "clean": _clean(title)})
    festivals = [r for r in records if 0 <= (r["end"] - r["start"]).days <= FESTIVAL_MAX_DAYS
                 and (any(w in r["clean"].split() for w in FESTIVAL_WORDS) or len(r["lineup"]) >= 8) and _core(r["title"])
                 # «Festival X: Espectacle Y» es una función del festival con su hora y su entrada: no se absorbe.
                 and not re.search(r"\S:\s+\S", r["title"])
                 # Fiestas con entrada propia dentro de un festival («X [Balla Festival]», «Fury pres. …», «CLOSA w/ MRAK»).
                 and not re.search(r"\[|\bw/|\bpres\.|\bpresenta\b|presentaci[oó]", r["title"], re.I)
                 # Songkick anuncia festivales con el nombre del cabeza de cartel («Anthony Rother» con
                 # todo el cartel de MIRA): eso es un concierto suelto a absorber, no un festival.
                 and r["clean"] not in {_clean(n) for n in r["lineup"]}]
    # Programa oficial del festival leído de su web (fuentes de tipo «festival», p. ej. los horarios de MIRA): cada
    # actuación tiene su ficha; el anuncio suelto del mismo artista se une a esa actuación (act_pairs, title_pairs), no
    # a la ficha general del festival (24-10-2026).
    from src.venue_directory import venue_type
    official = [r for r in records if r["source"].startswith("venue_") and venue_type(r["source"][6:]) == "festival"]
    def has_official_set(r):
        return any(abs((o["start"] - r["start"]).days) <= 1 and (o["clean"] == r["clean"] or f" {r['clean']} " in f" {o['clean']} ") for o in official)
    pairs = []
    # 1) El mismo festival en varias fuentes.
    for i, f in enumerate(festivals):
        for g in festivals[i + 1:]:
            if f["start"] > g["end"] or g["start"] > f["end"]: continue
            cf, cg = _core(f["title"]), _core(g["title"])
            if (cf <= cg or cg <= cf) and len(cf ^ cg) <= 2 and _same_place(f, g): pairs.append((f["key"], g["key"]))
    # 2) Conciertos sueltos de artistas del cartel, dentro del festival.
    for f in festivals:
        names = {_clean(n) for g in festivals if g is f or (g["key"], f["key"]) in pairs or (f["key"], g["key"]) in pairs for n in g["lineup"]}
        if len(names) < 2: continue
        for r in records:
            if r is f or r["source"] not in SINGLE_ACT_SOURCES or r in festivals: continue
            if not (f["start"] <= r["start"] and r["end"] <= f["end"]): continue
            artists = {_clean(n) for n in r["lineup"]} | {r["clean"]}
            if artists & names and _same_place(r, f) and not has_official_set(r): pairs.append((r["key"], f["key"]))
    return pairs


def act_pairs(conn):
    """Parejas (anuncio de artista, concierto) del mismo día y sala.

    Songkick, DICE o las ticketeras anuncian a menudo solo el nombre del artista
    («Melendi», «Perico Sambeat») de un concierto que otra fuente publica con su título
    completo («Concert "Melendi"», «Albert Vila Quartet feat Perico Sambeat») y, muchas
    veces, con la hora. Mismo día, mismo recinto y el nombre del artista entero dentro del
    otro título: es el mismo concierto. Nombres que son el de la sala («Jamboree Jazz») no cuentan."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, r.start_date, r.end_date, v.venue, v.lat, v.lon
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND julianday(substr(r.end_date,1,10))-julianday(substr(r.start_date,1,10)) BETWEEN 0 AND 3
                AND r.eligibility<>'exclude'""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    # Anuncios de un solo día frente a conciertos de hasta 4 días seguidos («Melendi» 1 y 2 de noviembre en una ficha).
    by_day = {}
    for source, rid, title, start, end, venue, lat, lon in rows:
        a, b = dt.date.fromisoformat(str(start)[:10]), dt.date.fromisoformat(str(end)[:10])
        item = {"key": f"{source}:{rid}", "source": source, "clean": _clean(title), "venue": venue or "", "lat": lat, "lon": lon, "single": a == b}
        for n in range((b - a).days + 1):
            by_day.setdefault((a + dt.timedelta(days=n)).isoformat(), []).append(item)
    pairs = []
    for day, items in by_day.items():
        for r in items:
            if r["source"] not in SINGLE_ACT_SOURCES or not r["single"] or len(r["clean"]) < 4: continue
            words = set(r["clean"].split())
            if words <= set(_clean(r["venue"]).split()) | CORE_STOP | PLACE_STOP:
                # «Jamboree Jazz» en el Jamboree Jazz Club: Songkick anuncia la sala, no un concierto.
                # Si otra fuente publica lo que hay esa noche en la sala, el anuncio se une a su primer concierto.
                # Sin nombre de artista que comparar, «mismo sitio» es la misma sala (nombre propio o <150 m), no el radio de
                # 1,5 km de las ticketeras: con él, «Jamboree Jazz» se unía a conciertos del Palau y del Poliorama y encadenaba
                # «Gran Gala Flamenc» (Palau) con «Gran Gala Flamenco» (Poliorama) en un solo grupo (26-10-2026).
                same = sorted((g for g in items if g is not r and g["source"] not in SINGLE_ACT_SOURCES and g["single"] and _same_site(r, g, km=0.15)), key=lambda g: g["key"])
                if same: pairs.append((r["key"], same[0]["key"]))
                continue
            pattern = re.compile(r"(?:^| )" + re.escape(r["clean"]) + r"(?: |$)")
            for g in items:
                if g is r or g["source"] == r["source"] or g["clean"] == r["clean"]: continue
                if pattern.search(g["clean"]) and _same_place(r, g): pairs.append((r["key"], g["key"]))
    return list(dict.fromkeys(pairs))


TITLE_PREFIX = re.compile(r"^(?:concert|concierto|espectacle|espectaculo|teatre|teatro|exposicio|exposicion|musical|"
                          r"activitat familiar|activitat|visita guiada|visita|obra de teatre|cinema|projeccio|recital|xerrada|conferencia)\s+", re.I)


# Título de la obra entre comillas tras un prefijo genérico, con créditos detrás (24-10-2026):
# «Teatre "Alejandra", a càrrec de Martín Rechimuzzi», «Espectacle "Viejóvenes", amb Raquel Ramos i Borja Calvo»,
# «Espectacle "Manual para follarse a un macho con vagina", de i amb Pablo Alamá». La sala lo publica solo como
# «ALEJANDRA», «Viejóvenes»… La clave es la obra; lo que va detrás (créditos) no cuenta.
QUOTED_WORK = re.compile(r'^\s*(?:(?:concert|concierto|espectacle|espectáculo|espectaculo|teatre|teatro|musical|obra de teatre|obra de teatro|recital|'
                         r'dansa|danza|circ|circo|opera|òpera|monòleg|monologo|monólogo|comèdia|comedia|humor|màgia|magia)(?:\s+(?:familiar|infantil))?\s+)*'
                         r'["«“]([^"»”]{3,})["»”]\s*(?:$|[,.;]|-\s|–\s|\s(?:amb|con|de|a c[aà]rrec|per|por|dirigit|dirigida|dirigido)\b)', re.I)


def _title_key(title):
    t = _clean(title)
    for _ in range(2): t = TITLE_PREFIX.sub("", t)
    return t


# Palabras genéricas de títulos en castellano → su forma catalana (24-10-2026): la misma sala publica a veces su
# web en castellano («Concierto para bebés», L'Auditori) y la agenda municipal en catalán («Concert per a nadons»).
# Solo para comparar títulos; no cambia nada de lo que se publica.
LEX = {"concierto": "concert", "conciertos": "concerts", "para": "per a", "bebes": "nadons", "bebe": "nado", "ninos": "infants", "ninas": "nenes",
       "familias": "families", "espectaculo": "espectacle", "espectaculos": "espectacles", "ciclo": "cicle", "exposicion": "exposicio",
       "danza": "dansa", "teatro": "teatre", "cuento": "conte", "cuentos": "contes", "cuentacuentos": "contacontes", "y": "i", "los": "els",
       "las": "les", "con": "amb", "sin": "sense", "noche": "nit", "navidad": "nadal", "ano": "any", "nuevo": "nou", "otono": "tardor",
       "verano": "estiu", "invierno": "hivern", "jovenes": "joves", "abuelos": "avis", "mujeres": "dones", "fiesta": "festa", "mercado": "mercat",
       "feria": "fira", "presentacion": "presentacio", "charla": "xerrada", "cine": "cinema", "sesion": "sessio", "paseo": "passejada",
       "coro": "cor", "orquesta": "orquestra", "sinfonica": "simfonica", "voz": "veu", "canciones": "cancons", "cancion": "canco",
       "musica": "musica", "taller": "taller", "talleres": "tallers", "visita": "visita", "visitas": "visites", "guiada": "guiada", "guiadas": "guiades",
       "familiar": "familiar", "infantil": "infantil", "concierto-vermut": "concert vermut", "domingo": "diumenge", "sabado": "dissabte",
       "matinal": "matinal", "primera": "primera", "infancia": "infancia", "semana": "setmana", "magia": "magia", "humor": "humor"}


def _lex(key):
    return " ".join(LEX.get(w, w) for w in key.split())


def _title_keys_typed(title):
    """[(clave, tipo)] para comparar títulos. Tipos: «full» la de siempre; «quoted» la obra sola si el título es
    «Prefijo "Obra", créditos»; «sub» la parte tras «:» si es un título propio («Magia Kids: La biblioteca secreta» →
    «la biblioteca secreta»). Cada una también con las palabras genéricas del castellano pasadas al catalán
    («Concierto para bebés» = «Concert per a nadons»)."""
    out = [(_title_key(title), "full")]
    m = QUOTED_WORK.match(str(title or ''))
    if m: out.append((_clean(m.group(1)), "quoted"))
    # La obra entre comillas tras el nombre del ciclo o festival (26-10-2026): GuiaBCN titula «Flaix de Tardor: Teatre
    # "Navegar por el Neva", a partir de…» y el Lliure «Navegar por el Neva»; «Cicle Simfònics al Palau: Concert "Requiem
    # de Mozart"» y el Palau «Requiem de Mozart». Misma regla que sin ciclo; las fechas y el sitio se siguen exigiendo.
    elif ':' in str(title or ''):
        m = QUOTED_WORK.match(str(title).split(':', 1)[1])
        if m: out.append((_clean(m.group(1)), "quoted"))
    # «Palms Trax all night long / POGO: …» junta dos actos: la parte tras «:» no es el título de la ficha entera.
    if ':' in str(title or '') and not str(title).lstrip().startswith(('"', '«', '“', "'")) and '/' not in str(title).split(':', 1)[0]:
        after = _clean(str(title).split(':', 1)[1])
        for _ in range(2): after = TITLE_PREFIX.sub("", after)
        if len(after) >= 8 and len(after.split()) >= 2 and after not in CONTAINED_GENERIC: out.append((after, "sub"))
    out += [(_lex(k), t) for k, t in out]
    seen, res = set(), []
    for k, t in out:
        if k and k not in seen: seen.add(k); res.append((k, t))
    return res


def _title_keys(title):
    return [k for k, _ in _title_keys_typed(title)]


# Las ticketeras alargan al día siguiente las sesiones que pasan de medianoche (DICE «Irieix» 5 → 6-3, la sala el 5-3).
def _end_of(source, start, end):
    try:
        # Biblioteques de la Diputació (27-10-2026): cada sesión llega con el fin al día siguiente a las 23:59:59
        # («Presentació de llibre» 18-12 18:30 → 19-12): es una sesión de un día, como la medianoche de las ticketeras.
        if (source in SINGLE_ACT_SOURCES or source == 'diba_bibliotecas') and (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days == 1: return start
    except (TypeError, ValueError): pass
    return end


STREET_GENERIC = {"carrer", "c", "calle", "cl", "avinguda", "avenida", "av", "avda", "passeig", "paseo", "pg", "placa", "plaza", "pl",
                  "ronda", "via", "travessera", "gran", "de", "del", "dels", "la", "el", "les", "els", "d", "l", "barcelona", "bcn", "s", "n"}


def _address_col(conn):
    """«v.address» si la tabla de lugares la tiene (bases de prueba antiguas: no)."""
    try: return "v.address" if "address" in {r[1] for r in conn.execute("PRAGMA table_info(source_venues)")} else "''"
    except sqlite3.DatabaseError: return "''"


def _address_key(address):
    """(calle, número) de una dirección: «Carrer de Lepant, 150» = «C. de Lepant, 150» = «Lepant 150, 08013 BARCELONA»."""
    words = _clean(address).split()
    for i, w in enumerate(words):
        if w.isdigit() or w in STREET_GENERIC or len(w) < 3: continue
        num = next((x for x in words[i + 1:i + 4] if x.isdigit() and len(x) <= 4), None)
        return (w, num) if num else None
    return None


def title_pairs(conn):
    """Parejas con el mismo título (quitando «Concert», «Espectacle», comillas…), las mismas
    fechas y el mismo sitio: «Espectacle "El Mago Pop"» (GuiaBCN) y «El Mago Pop» (Generalitat)
    en el Victòria; «Exposició Jardí interior» en «Casa Elizalde» y en «Centre Cultural La Casa
    Elizalde»; o dos ticketeras con la misma fiesta. Mismo título en otro centro no es el mismo
    evento (cada centre cívic tiene su «Taller de ioga»)."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute(f"""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon, {_address_col(conn)}
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude'""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    groups = {}
    for source, rid, title, start, end, venue, lat, lon, address in rows:
        quoted = QUOTED_WORK.match(str(title or ''))
        for key, kind in _title_keys_typed(title):
            # Títulos cortos («Bien», «RITA»): solo si una de las dos fichas lo pone entre comillas tras «Monòleg», «Espectacle»…
            short_ok = len(key) >= 3 and (bool(quoted) and key in (_clean(quoted.group(1)), _lex(_clean(quoted.group(1)))) or key == _clean(title))
            if len(key) < 6 and not short_ok: continue
            groups.setdefault((start, _end_of(source, start, end), key), []).append({"key": f"{source}:{rid}", "source": source, "id": rid, "venue": venue or "", "lat": lat, "lon": lon,
                                                             "address": address or "", "route": bool(ROUTE.match(_clean(title))), "short": len(key) < 6,
                                                             "quoted": bool(quoted), "kind": kind, "multi": (venue or "").count(",") >= 2})
    pairs = []
    times = {}
    def first_time(item):
        k = item["key"]
        if k not in times:
            row = conn.execute("SELECT MIN(local_time) FROM candidate_occurrences WHERE source=? AND id=? AND local_time IS NOT NULL", (item["source"], item["id"])).fetchone()
            t = row[0] if row else None
            if not t:
                try: row = conn.execute("SELECT schedule_time FROM source_enrichments WHERE source=? AND id=?", (item["source"], item["id"])).fetchone()
                except sqlite3.DatabaseError: row = None
                t = (re.search(r"\d{1,2}:\d{2}", row[0] or "") or [None])[0] if row and row[0] else None
            times[k] = t
        return times[k]
    for items in groups.values():
        if len(items) < 2: continue
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if (a["short"] or b["short"]) and not ((a["quoted"] != b["quoted"]) and _same_site(a, b) and a["source"] != b["source"]): continue
                # Una ficha en varios centros a la vez («CC La Casa Elizalde, Auditori Sant Martí, CC Vil·la Urània…»): solo con el
                # título entero, no con la parte tras «:» (si no, la de un solo centro se comería la de los cinco).
                if (a["multi"] or b["multi"]) and "sub" in (a["kind"], b["kind"]): continue
                if _same_site(a, b) or _generic_site(a) or _generic_site(b):
                    pairs.append((a["key"], b["key"]))
                # Itinerarios y visitas: el «lugar» es el centro que lo organiza; misma salida a la misma hora = mismo itinerario.
                elif a["route"] and b["route"] and first_time(a) and first_time(a) == first_time(b):
                    pairs.append((a["key"], b["key"]))
    return pairs


COURSE_TITLE = re.compile(r"^(?:taller|tallers|curs|cursos|curso|classe|classes|clase|clases|grup|grupo|iniciacio|iniciacion|conversa|conversacion)\b")
RUN_MIN_DAYS = 7          # una «temporada»: obra en cartel, exposición
RUN_MIN_OVERLAP = 0.5     # dos temporadas son la misma si se solapan al menos la mitad de la más corta


def run_pairs(conn):
    """La misma obra o exposición en cartel con fechas que no coinciden del todo (23-10-2026):
    «El Mago Pop» en el Victòria (Generalitat 14-10 → 31-1, la sala 14-10 → 28-2), «Mamma Mia!» en el
    Tívoli (Generalitat y Balañà), la expo de Sant Pau (4-7 y 7-7 → 15-11). Mismo título (sin «Espectacle»,
    comillas…), mismo sitio, las dos de una semana o más y solapadas al menos la mitad de la más corta.
    Y las funciones sueltas del mismo título y sitio que caen dentro de la temporada (Conciertos.Club publica
    cada función de «Mamma Mia!» por separado) son esa temporada: pasan a ser sus días con hora."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute(f"""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon, {_address_col(conn)}
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude'""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    by_key = {}
    for source, rid, title, start, end, venue, lat, lon, address in rows:
        # Talleres y cursos fuera: un centro tiene varios grupos con el mismo título («Taller de pilates» de lunes y de
        # jueves) y unirlos de dos en dos entre fuentes acabaría juntando grupos distintos.
        if COURSE_TITLE.match(_clean(title)): continue
        try: a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(_end_of(source, start, end))
        except (TypeError, ValueError): continue
        for key, kind in _title_keys_typed(title):
            if len(key) < 5 or key in CONTAINED_GENERIC or ROUTE.match(key): continue
            by_key.setdefault(key, []).append({"key": f"{source}:{rid}", "source": source, "start": a, "end": b, "days": (b - a).days,
                                               "venue": venue or "", "lat": lat, "lon": lon, "address": address or "", "kind": kind})
    pairs = []
    for items in by_key.values():
        if len(items) < 2: continue
        runs = [x for x in items if x["days"] >= RUN_MIN_DAYS and not _generic_site(x)]
        for i, a in enumerate(runs):
            for b in runs[i + 1:]:
                overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"])).days
                # Solo entre fuentes distintas: dos fichas de la misma fuente con el mismo título en el mismo centro
                # suelen ser grupos distintos de un curso («Taller de ioga» de mañana y de tarde).
                if a["source"] != b["source"] and overlap >= 0 and overlap >= RUN_MIN_OVERLAP * min(a["days"], b["days"]) and _same_site(a, b):
                    pairs.append((a["key"], b["key"]))
        # Funciones y fines de semana sueltos (hasta 6 días) dentro de la temporada de otra fuente (24-10-2026: Generalitat
        # publica cada fin de semana de «Concert per a nadons», L'Auditori cada función y Open Data la temporada).
        # Y funciones de un día dentro de un periodo corto (2 a 6 días) de otra fuente: el Liceu publica «Miralls» el 21 y
        # el 22-11, la Generalitat del 21 al 22.
        shorts = [x for x in items if 1 <= x["days"] <= 6 and not _generic_site(x)]
        for x in items:
            # «Activitat complementària a l'exposició: Juntes i visibles» no es la exposición: dentro de un periodo
            # solo cuenta el título entero o la obra entre comillas, no la parte tras «:».
            if x["days"] > 6 or _generic_site(x) or x.get("kind") == "sub": continue
            host = next((r for r in runs if r["source"] != x["source"] and r.get("kind") != "sub" and r["start"] <= x["start"] and x["end"] <= r["end"] and _same_site(r, x)), None)
            if not host and x["days"] == 0:
                host = next((r for r in shorts if r["source"] != x["source"] and r.get("kind") != "sub" and r["start"] <= x["start"] <= r["end"] and _same_site(r, x)), None)
            if host: pairs.append((x["key"], host["key"]))
    return list(dict.fromkeys(pairs))


def contained_pairs(conn):
    """La misma función con dos títulos, uno dentro del otro, en el mismo sitio y a la misma hora un
    día que comparten: «Calderada» (20 y 27 de octubre, 19 h) y «"Calderada". El meu clàssic: Pere
    Calders» (20 de octubre, 19 h) en el TNC, aunque sean de la misma fuente (20-10-2026)."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude' AND julianday(substr(r.end_date,1,10))-julianday(substr(r.start_date,1,10)) <= 60""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    items, by_word = [], {}
    for source, rid, title, start, end, venue, lat, lon in rows:
        key = _title_key(title)
        it = {"key": f"{source}:{rid}", "source": source, "id": rid, "title_key": key, "start": start, "end": end, "venue": venue or "", "lat": lat, "lon": lon}
        items.append(it)
        for w in set(key.split()):
            if len(w) >= 5: by_word.setdefault(w, []).append(it)
    def times(item):
        return {(d, t) for d, t in conn.execute("SELECT local_date, local_time FROM candidate_occurrences WHERE source=? AND id=? AND local_time IS NOT NULL", (item["source"], item["id"]))}
    def text_times(item):
        """Horario en texto de la fuente («Dimarts 20: 19 h Dimarts 27: 19 h») cuando no hay sesiones."""
        row = conn.execute("SELECT json_extract(raw_json,'$.normalized.time_text') FROM source_records WHERE source=? AND id=?", (item["source"], item["id"])).fetchone()
        text = _clean(row[0] if row and row[0] else "")
        clock = {f"{int(h):02d}:{int(m or 0):02d}" for h, m in re.findall(r"\b([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*h\b", text)}
        clock |= {f"{int(h):02d}:{m}" for h, m in re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)}
        days = {int(d) for d in re.findall(r"\b(?:dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+(\d{1,2})\b", text)}
        return clock, days
    def same_session(a, b):
        ta, tb = times(a), times(b)
        if ta & tb: return True
        for x, y, tx in ((a, b, ta), (b, a, tb)):
            if tx: continue  # x tiene sesiones propias; ya se compararon
            clock, days = text_times(x)
            if any(t in clock and x["start"] <= d <= x["end"] and (not days or int(d[8:10]) in days) for d, t in (times(y))): return True
        return False
    pairs = []
    for a in items:
        ka = a["title_key"]
        if len(ka) < 6 or len(ka.split()) > 6 or ka in CONTAINED_GENERIC or _generic_site(a): continue
        longest = max(ka.split(), key=len)
        if len(longest) < 5: continue
        for b in by_word.get(longest, []):
            kb = b["title_key"]
            if b is a or kb == ka or f" {ka} " not in f" {kb} " or not _same_site(a, b): continue
            if a["end"] < b["start"] or b["end"] < a["start"]: continue
            if same_session(a, b): pairs.append((a["key"], b["key"]))
    return list(dict.fromkeys(pairs))



# Actividad sobre otra (inauguración, salida en grupo, ensayo abierto) y títulos de formato demasiado genéricos.
NESTED_SKIP = re.compile(r"inaugur|\bsortid[ae]s?\b|tast d.?orquestra")  # sin \b delante: _clean une «d’inauguració» en «dinauguracio»
NESTED_GENERIC = {"stand up comedy", "concerts", "castaween", "concert solidari"}


def nested_pairs(conn):
    """El mismo acto con un título que contiene al otro, en el mismo sitio y en las mismas fechas (28-10-2026, auditoría
    de usabilidad): «Ópera – Carmen» (la sala) y «Òpera "Carmen", de Georges Bizet» (Open Data), Apolo, 28-10 a las 19:30;
    «Galder Varas» (Balañá) y «Monòleg "Esto No Es Una Prueba", amb Galder Varas» (GuiaBCN), Borràs, 28-10 → 1-11;
    «Exposició "Vuit"» y «Exposició 'Vuit', de Frederic Amat» (Virreina); «Codi Gaudí» y «Experiència immersiva "Codi
    Gaudí, l'experiència inèdita"» (Espai Imagina / Imagina Centre Audiovisual, a 20 m).
    Entre fuentes distintas, el título corto (entero o la obra entre comillas) como frase dentro del largo; el mismo sitio;
    el periodo del uno dentro del otro con duraciones parecidas (±3 días) o el mismo día de inicio; dos palabras o más en
    el título corto, salvo que las fechas sean idénticas. Nunca una actividad sobre la obra (visita, presentación, taller,
    inauguración…) ni cursos."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute(f"""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon, {_address_col(conn)}
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude'""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    items, by_word = [], {}
    for source, rid, title, start, end, venue, lat, lon, address in rows:
        clean = _clean(title)
        if COURSE_TITLE.match(clean) or EXHIBITION_ACTIVITY.match(clean) or NESTED_SKIP.search(clean): continue
        try: a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(_end_of(source, start, end))
        except (TypeError, ValueError): continue
        keys = [k for k, kind in _title_keys_typed(title) if kind in ("full", "quoted")]
        it = {"key": f"{source}:{rid}", "source": source, "start": a, "end": b, "days": (b - a).days, "keys": keys, "clean": clean,
              "venue": venue or "", "lat": lat, "lon": lon, "address": address or ""}
        if _generic_site(it): continue
        items.append(it)
        for k in keys:
            for w in set(k.split()):
                if len(w) >= 4: by_word.setdefault(w, []).append(it)
    pairs = []
    for a in items:
        for ks in a["keys"]:
            words = ks.split()
            if not words or ks in CONTAINED_GENERIC or ks in NESTED_GENERIC or ROUTE.match(ks): continue
            longest = max(words, key=len)
            if len(longest) < 4: continue
            for b in by_word.get(longest, []):
                if b is a: continue
                if b["source"] == a["source"]:
                    # La misma fuente con la obra dos veces (GuiaBCN: «Bons i dolents» y «Teatre "Bons i Dolents"», Condal): solo con
                    # el mismo título exacto (entero u obra entre comillas), temporadas de una semana o más solapadas y el mismo sitio.
                    overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"])).days
                    if a["key"] < b["key"] and a["clean"] != b["clean"] and ks in b["keys"] and len(ks) >= 8 and min(a["days"], b["days"]) >= 7 and overlap >= 0.5 * min(a["days"], b["days"]) and _same_site(a, b, km=0.15):
                        pairs.append((a["key"], b["key"]))
                    continue
                same_dates = a["start"] == b["start"] and a["end"] == b["end"]
                if len(words) < 2 and not same_dates: continue
                if len(ks) < 8 and not same_dates: continue
                if not any(kl != ks and f" {ks} " in f" {kl} " for kl in b["keys"]): continue
                inside = (a["start"] >= b["start"] and a["end"] <= b["end"]) or (b["start"] >= a["start"] and b["end"] <= a["end"])
                if not inside or not (abs(a["days"] - b["days"]) <= 3 or a["start"] == b["start"]): continue
                if _same_site(a, b, km=0.15): pairs.append((a["key"], b["key"]))
    return list(dict.fromkeys(pairs))

# Actividades sobre una exposición (visitas, inauguraciones): no son la exposición.
def umbrella_pairs(conn):
    """La ficha paraguas de un mismo festival en varias fuentes es una sola: «Festival 48h Open House BCN»
    (Generalitat) y «Festival d'Arquitectura "48h Open House BCN". Cap de setmana de visites…» (GuiaBCN),
    las dos en «diferents espais» (src/festivals.py, 21-10-2026). Fechas que se solapan."""
    import datetime as dt
    from src.festivals import for_conn
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude'""", (today,)).fetchall()
    except sqlite3.DatabaseError:
        return []
    fest = for_conn(conn); by = {}
    for source, rid, title, start, end, venue in rows:
        # Con fechas (28-10-2026): la ficha general suelta de un festival sin actividades («Asian Film Festival Barcelona»,
        # Generalitat, y «14è Asian Film Festival Barcelona», GuiaBCN) solo se reconoce como festival si dura más de un día.
        f = fest.of(title, venue=venue or "", start=start, end=end)
        if f and f["umbrella"]: by.setdefault(f["slug"], []).append((f"{source}:{rid}", start, end, _edition(title)))
    pairs = []
    for items in by.values():
        for i, (ka, a1, a2, ea) in enumerate(items):
            for kb, b1, b2, eb in items[i + 1:]:
                # Ediciones distintas («Lens Dans #3» de 2025 y «4t Lens Dans Festival»): dos fichas.
                if ea and eb and ea != eb: continue
                if a1 <= b2 and b1 <= a2: pairs.append((ka, kb))
    return pairs


_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def _edition(title):
    """Número de edición del título («14è», «4t», «#3», «XXXIV», «9a edició») o 0."""
    t = str(title or "").lower()
    m = re.search(r"(?:^|\s|#)(\d{1,3})\s*(?:è|é|e|a|o|r|n|t|ª|º)?\b(?!\s*(?:nov|oct|des|gen|feb|mar|abr|mai|jun|jul|ago|set|sep|d'|de\b|h\b|:))|#\s*(\d{1,3})", t)
    if m: return int(m.group(1) or m.group(2))
    m = re.match(r"\s*([ivxlc]{1,7})\b", t)
    if m:
        total, prev = 0, 0
        for ch in reversed(m.group(1)):
            v = _ROMAN[ch]; total += -v if v < prev else v; prev = max(prev, v)
        return total
    return 0


EXHIBITION_ACTIVITY = re.compile(r"^(?:.*\b)?(?:visita|visites|visitas|inaugur\w*|presentacio|presentacion|taller|tallers|conferencia|xerrada)\b")
EXHIBITION_GENERIC = re.compile(r"^(?:col.leccio|coleccion|collection|exposicio permanent|exposicion permanente|fons|obres|obra|retrats?|fotografies|pintura|escultura)\b")


def exhibition_pairs(conn):
    """La misma exposición en dos fuentes con fechas que no cuadran: «Exposició "Charlotte Perriand"»
    (Ajuntament, 6-10 → 28-3) y «Exposició "Charlotte Perriand. La llibertat de repensar el món"»
    (Generalitat, 9-10 → 28-2) en la Fundació Miró (21-10-2026). Un título dentro del otro (al menos dos
    palabras propias), el mismo sitio, las dos de varias semanas, que empiezan con menos de un mes de
    diferencia y se solapan. Las fechas que se muestran son las de la ficha canónica."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude' AND r.kind='exhibition' AND julianday(substr(r.end_date,1,10))-julianday(substr(r.start_date,1,10)) >= 14""", (today,)).fetchall()
        # Exposiciones que la agenda de la sala publica como «programa» (27-10-2026): las mismas pruebas que la ficha
        # (sección de exposiciones de su página, título; mvp/catalog.effective_kind).
        from mvp.catalog import effective_kind
        try: extra = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), v.venue, v.lat, v.lon, r.raw_json
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE r.end_date>=? AND r.eligibility<>'exclude' AND r.kind IN ('program','single') AND (r.source LIKE 'venue_%' OR r.source LIKE 'web_%')
                AND julianday(substr(r.end_date,1,10))-julianday(substr(r.start_date,1,10)) >= 14""", (today,)).fetchall()
        except sqlite3.DatabaseError: extra = []   # base sin raw_json (pruebas)
        for source, rid, title, start, end, venue, lat, lon, raw in extra:
            try: data = json.loads(raw or '{}')
            except ValueError: continue
            if effective_kind(source, data, 'program', title, start, end) == 'exhibition': rows.append((source, rid, title, start, end, venue, lat, lon))
    except sqlite3.DatabaseError:
        return []
    def day(v):
        try: return dt.date.fromisoformat(v)
        except (TypeError, ValueError): return None
    items, by_word = [], {}
    for source, rid, title, start, end, venue, lat, lon in rows:
        key = _title_key(title)
        a, b = day(start), day(end)
        if not a or not b: continue
        if EXHIBITION_ACTIVITY.match(_clean(title)): continue
        it = {"key": f"{source}:{rid}", "source": source, "title_key": key, "start": a, "end": b, "venue": venue or "", "lat": lat, "lon": lon}
        items.append(it)
        for w in set(key.split()):
            if len(w) >= 5: by_word.setdefault(w, []).append(it)
    pairs = []
    for a in items:
        ka = a["title_key"]; words = [w for w in ka.split() if w not in CORE_STOP]
        if len(words) < 2 or len(ka) < 10 or EXHIBITION_GENERIC.match(ka) or _generic_site(a): continue
        if any(w in ka.split() for w in FESTIVAL_WORDS): continue
        found = []
        for b in by_word.get(max(words, key=len), []):
            kb = b["title_key"]
            if b is a or b["source"] == a["source"] or f" {ka} " not in f" {kb} " or len(kb.split()) > len(ka.split()) + 8: continue
            # Mismas fechas exactas y un título dentro del otro (27-10-2026): basta aunque una de las dos no tenga
            # coordenadas o su lugar sea genérico («World Press Photo 2026», CCCB sin coordenadas; «Unfunny Paintings»,
            # Poblenou Urban District «Diversos espais»).
            exact = a["start"] == b["start"] and a["end"] == b["end"] and (a["lat"] is None or b["lat"] is None or _generic_site(b))
            if not exact and not _same_site(a, b, km=0.12): continue
            if abs((a["start"] - b["start"]).days) > 31 or a["end"] < b["start"] or b["end"] < a["start"]: continue
            found.append(b)
        # «Aurèlia Muñoz» dentro de dos títulos distintos: ambiguo, no se junta con ninguno.
        if len({b["title_key"] for b in found if b["title_key"] != ka}) > 1: continue
        pairs += [(a["key"], b["key"]) for b in found]
    return list(dict.fromkeys(pairs))


CONTAINED_GENERIC = {"concert", "concierto", "taller", "visita guiada", "jam session", "club de lectura", "hora del conte", "contacontes", "espectacle familiar", "dj session"}


ROUTE = re.compile(r"^(?:itinerari|itinerario|ruta|visita|passejada|paseo|recorregut|excursio|sortida)\b")
GENERIC_SITE = re.compile(r"^(?:diversos|diverses|diferents|varios|varias|barcelona|barcelona mar|tota la ciutat|la ciutat|online)\b", re.I)


def _generic_site(item):
    """«Diversos carrers del districte», «Barcelona»: no es un sitio con el que comparar."""
    return bool(GENERIC_SITE.match(_clean(item["venue"]))) or not item["venue"]


SITE_GENERIC = {"centre", "centro", "civic", "cultural", "casal", "barri", "comunitari", "gent", "gran", "biblioteca", "ateneu",
                "espai", "auditori", "museu", "museo", "teatre", "teatro", "sala", "parc", "placa", "mercat", "escola", "institut",
                "cc", "casa", "can", "club", "jardins", "jardi", "districte", "seu", "exposicions", "exposicio", "fundacio",
                "barcelona", "bcn", "de", "del", "la", "el", "les", "els", "i", "d", "l"}


def _same_site(a, b, km=0.4):
    """Mismo lugar para dos fichas con el mismo título: con coordenadas, a menos de 400 m; sin ellas,
    un nombre que comparte algo propio («Elizalde», «Razzmatazz»), no «Centre Cívic» ni «Casal de Barri»."""
    d = _km((a["lat"], a["lon"]), (b["lat"], b["lon"]))
    if d is not None: return d <= km
    va, vb = set(_clean(a["venue"]).split()) - SITE_GENERIC, set(_clean(b["venue"]).split()) - SITE_GENERIC
    if va & vb: return True
    # Sin coordenadas y con nombres que no comparten nada propio («L'Auditori» y «Sala 3 Tete Montoliu»): la misma
    # calle y número en las dos direcciones (24-10-2026).
    ka, kb = _address_key(a.get("address")), _address_key(b.get("address"))
    return bool(ka and ka == kb)


def unconfirmed_by_venue(conn, groups, venues=None, today=None):
    """Anuncios de terceros (Songkick, DICE, Xceed…) en una sala cuya agenda propia damos por
    completa («agenda_completa» en config/venues.json) que no casan con ningún acto de esa
    agenda, en una fecha que la agenda ya cubre (20-10-2026). No se oculta nada: la ficha
    lleva la marca «Fecha no confirmada por la sala». {clave: nombre de la sala}."""
    import datetime as dt, json
    from pathlib import Path
    if venues is None:
        try: venues = json.loads((Path(__file__).resolve().parent.parent / "config" / "venues.json").read_text(encoding="utf-8"))["venues"]
        except (OSError, ValueError, KeyError): return {}
    today = (today or dt.date.today()).isoformat()
    complete = [v for v in venues if v.get("enabled") and v.get("agenda_completa")]
    if not complete: return {}
    root = lambda k: groups.get(k, k)
    out = {}
    for venue in complete:
        own = "venue_" + venue["slug"]
        names = [_clean(n) for n in [venue["name"]] + list(venue.get("aliases") or []) if len(_clean(n)) >= 6]
        try:
            last = conn.execute("SELECT MAX(end_date) FROM source_records WHERE source=? AND eligibility<>'exclude'", (own,)).fetchone()[0]
            own_roots = {root(f"{own}:{i}") for (i,) in conn.execute("SELECT id FROM source_records WHERE source=? AND end_date>=?", (own, today))}
            rows = conn.execute(f"""SELECT r.source, r.id, v.venue FROM source_records r
                  JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
                  WHERE r.source IN ({','.join('?' * len(SINGLE_ACT_SOURCES))}) AND r.eligibility<>'exclude'
                    AND r.start_date=r.end_date AND r.start_date>=? AND r.start_date<=?""", (*SINGLE_ACT_SOURCES, today, last or "")).fetchall()
        except sqlite3.DatabaseError:
            continue
        if not last or not own_roots: continue
        for source, rid, place in rows:
            clean = " %s " % _clean(place)
            if not any(" %s " % n in clean for n in names): continue
            key = f"{source}:{rid}"
            if root(key) not in own_roots: out[key] = venue["name"]
    return out


# --- Mismo pase con otro título y sesiones partidas (26-10-2026, revisión de David) -----------------
def _single_day_items(conn):
    """Fichas de un solo día desde hoy, con sala y sus horas (candidate_occurrences)."""
    import datetime as dt
    today = dt.date.today().isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), v.venue, v.lat, v.lon, v.address
              FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
              WHERE substr(r.start_date,1,10)>=? AND substr(r.end_date,1,10)<=date(substr(r.start_date,1,10),'+1 day')
              AND r.eligibility<>'exclude'""", (today,)).fetchall()
        occ = {}
        for s, i, d, t in conn.execute("SELECT source,id,local_date,local_time FROM candidate_occurrences WHERE local_date>=? AND local_time IS NOT NULL AND local_time<>''", (today,)):
            occ.setdefault((s, i), set()).add((d, t))
    except sqlite3.DatabaseError:
        return []
    items = []
    for source, rid, title, day, venue, lat, lon, address in rows:
        items.append({"key": f"{source}:{rid}", "source": source, "id": rid, "title_key": _title_key(title), "full_title": re.sub(r"[^a-z0-9]+", " ", _clean(title)).strip(), "day": day,
                      "venue": venue or "", "lat": lat, "lon": lon, "address": address or "", "slots": occ.get((source, rid), set())})
    return items


def slot_pairs(conn, items=None):
    """El mismo pase en dos ticketeras con títulos distintos, uno contenido en el otro: «MÜV» (Songkick) y
    «MUV: Anti-Mondays Jam» (DICE), Marula Café, 26-10 a las 22:00. Distinta fuente, mismo sitio, misma
    fecha y hora, y todas las palabras del título corto en el largo (aunque sea corto: «muv»)."""
    items = _single_day_items(conn) if items is None else items
    by_slot = {}
    for it in items:
        if not it["title_key"] or _generic_site(it): continue
        for slot in it["slots"]: by_slot.setdefault(slot, []).append(it)
    pairs = []
    for group in by_slot.values():
        if len(group) < 2 or len(group) > 40: continue
        for n, a in enumerate(group):
            for b in group[n + 1:]:
                if a["source"] == b["source"] or a["title_key"] == b["title_key"]: continue
                short, long_ = sorted((a["title_key"], b["title_key"]), key=len)
                if len(short) < 3 or short in CONTAINED_GENERIC or not set(short.split()) <= set(long_.split()): continue
                if _same_site(a, b, km=0.15): pairs.append((a["key"], b["key"]))
    return list(dict.fromkeys(pairs))


def session_pairs(conn, items=None):
    """Una película con varios pases el mismo día en la misma sala es una sola ficha (David, 26-10-2026):
    las salas que publican una página por pase (Espai Texas en Koobin) daban una ficha por sesión. Misma
    fuente, mismo título, mismo sitio y mismo día; la ficha que queda reúne todas las horas (catalog)."""
    items = _single_day_items(conn) if items is None else items
    by = {}
    for it in items:
        if it["title_key"] and not _generic_site(it):
            by.setdefault((it["source"], it["title_key"], it["day"]), []).append(it)
    pairs = []
    for group in by.values():
        for n, a in enumerate(group):
            for b in group[n + 1:]:
                if _same_site(a, b, km=0.1): pairs.append((a["key"], b["key"]))
    return pairs


# Fuentes de cine: una película en días distintos son pases distintos de la cartelera (solo se juntan los del mismo
# día, session_pairs). Las agregadoras municipales publican cada sesión de talleres o lecturas por separado con el
# mismo título genérico: tampoco se juntan entre días.
SERIES_SKIP = ('venue_ia_filmoteca', 'venue_ia_phenomena', 'venue_ia_zumzeig', 'venue_cinemes_girona', 'venue_ia_espai_texas',
               'venue_ia_cinema_malda', 'venue_ia_documenta', 'guiabcn', 'opendatabcn_agenda', 'generalitat', 'diba_bibliotecas',
               'diba_turismo', 'web_centres_civics')
SERIES_GAP_DAYS = 7          # días seguidos o semanales: el mismo espectáculo, la misma sesión de club
SERIES_COURSE_GAP_DAYS = 35  # sesiones mensuales de un curso del CCCB
SERIES_MAX = 40


def series_pairs(conn, items=None):
    """El mismo acto de una sala en una ficha por día (27-10-2026, auditoría conjunta 4.1: 194 títulos en 695 fichas):
    misma fuente, mismo título, mismo sitio, fichas de un día que se suceden con menos de una semana entre una y
    otra (un curso del CCCB, menos de cinco). La ficha que queda va del primer al último día con todas sus sesiones
    (mvp/catalog). Fuera: cine entre días distintos y agregadoras con títulos genéricos; títulos genéricos."""
    import datetime as dt
    items = _single_day_items(conn) if items is None else items
    by = {}
    for it in items:
        if it["source"] in SERIES_SKIP or not it["title_key"] or _generic_site(it): continue
        # El título entero, no la clave recortada: «Cicle John Coltrane: Bruce Barth» y «Cicle John Coltrane: Dion
        # Hoorn» son conciertos distintos del mismo ciclo (27-10-2026).
        k = it.get("full_title") or it["title_key"]
        if it["title_key"] in CONTAINED_GENERIC or k in CONTAINED_GENERIC or len(k) < 5: continue
        # Título que es el nombre de la sala («Jamboree Jazz», «Hal9000» en Songkick): no dice qué acto es.
        if set(k.split()) <= set(re.sub(r"[^a-z0-9]+", " ", _clean(it["venue"])).split()) | {"club", "sala", "jazz", "bcn", "barcelona"}: continue
        by.setdefault((it["source"], k), []).append(it)
    pairs = []
    for (source, _), group in by.items():
        if len(group) < 2: continue
        group.sort(key=lambda it: it["day"])
        gap = SERIES_COURSE_GAP_DAYS if source == 'web_cccb' else SERIES_GAP_DAYS
        chain = [group[0]]
        def close():
            if 2 <= len(chain) <= SERIES_MAX:
                head = chain[0]
                pairs.extend((head["key"], it["key"]) for it in chain[1:] if _same_site(head, it, km=0.1) or (head["venue"] and head["venue"] == it["venue"]))
        for it in group[1:]:
            d0, d1 = dt.date.fromisoformat(chain[-1]["day"]), dt.date.fromisoformat(it["day"])
            if (d1 - d0).days <= gap: chain.append(it)
            else: close(); chain = [it]
        close()
    return pairs


def slot_and_session_pairs(conn):
    items = _single_day_items(conn)
    return slot_pairs(conn, items) + session_pairs(conn, items) + series_pairs(conn, items)


def _named_site_match(a, b):
    """Los dos nombres de sitio comparten algo propio («Sala Apolo»/«SALA APOLO», «Museu del Disseny»/«Disseny Hub»), o
    uno no es un nombre (dirección, coordenadas). Dos centros con nombre propio distinto («Casa Elizalde» y «Tomasa Cuevas»)
    no son el mismo sitio aunque sus coordenadas caigan cerca (28-10-2026)."""
    va, vb = set(_clean(a["venue"]).split()) - SITE_GENERIC, set(_clean(b["venue"]).split()) - SITE_GENERIC
    va, vb = {w for w in va if len(w) >= 4 and not w.isdigit()}, {w for w in vb if len(w) >= 4 and not w.isdigit()}
    return bool(va & vb)


_GENRE = {'jazz', 'blues', 'soul', 'funk', 'rock', 'punk', 'metal', 'techno', 'house', 'reggaeton', 'salsa', 'flamenco', 'halloween', 'castanyada',
          'tribute', 'tribut', 'homenatge', 'homenaje', 'showcase', 'night', 'nit', 'noche', 'edition', 'edicion', 'especial', 'special'}


def same_day_pairs(conn, today=None, days=60):
    """Mismo acto de un día publicado por dos fuentes con títulos distintos (28-10-2026, parte diario: «Concert "Hermeto's
    Mothership"» de Open Data y «Hermeto’s Mothership – A 100% Hermeto Pascoal tribute…» de Jamboree; las sesiones de City
    Hall en Xceed y en su web; «1968: París i Praga» en CaixaForum y en la agenda municipal). Mismo día, mismo sitio con nombre
    propio en común (y a menos de 150 m si hay coordenadas), las palabras propias del título más corto todas en el otro (o
    dos o más en común) y horas compatibles: la misma o una de las dos sin hora. Nunca en sitios genéricos (recorridos,
    «diversos espais») ni entre dos fichas de la misma fuente."""
    import datetime as _dt
    from src.daily_report import DUP_GENERIC
    today = today or _dt.date.today()
    end = (today + _dt.timedelta(days=days)).isoformat()
    try:
        rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), v.venue, v.lat, v.lon,
                (SELECT GROUP_CONCAT(local_time) FROM candidate_occurrences o WHERE o.source=r.source AND o.id=r.id AND COALESCE(o.local_time,'')<>'')
                FROM source_records r LEFT JOIN source_venues v ON v.source=r.source AND v.id=r.id AND v.seq=0
                WHERE r.eligibility<>'exclude' AND substr(r.start_date,1,10) BETWEEN ? AND ?
                  AND substr(r.start_date,1,10)=substr(COALESCE(NULLIF(r.end_date,''),r.start_date),1,10)""", (today.isoformat(), end)).fetchall()
    except sqlite3.DatabaseError:
        return []
    by_day = {}
    for s, i, title, day, venue, lat, lon, times in rows:
        item = {'key': f'{s}:{i}', 'source': s, 'title': title or '', 'venue': venue or '', 'lat': lat, 'lon': lon, 'address': '',
                'times': {'00:00' if t == '23:59' else t for t in (times or '').split(',') if t}}
        if _generic_site(item) or re.match(r"^(?:recorregut|recorrido|ruta|inici|sortida|diferents|diversos|varis)\b", _clean(item['venue'])): continue
        # Varios sitios en uno («CC La Casa Elizalde, Auditori Sant Martí, CC Vil·la Urània… i CC Tomasa Cuevas»): no es un sitio.
        if len(re.findall(r",|;|\s(?:i|y)\s", item['venue'])) >= 2: continue
        item['words'] = {w for k in _title_keys(title or '') for w in k.split() if len(w) >= 4 and w not in DUP_GENERIC and w not in _GENRE} - set(_clean(venue or '').split())
        if item['words']: by_day.setdefault(day, []).append(item)
    pairs = []
    for day, items in by_day.items():
        for n, a in enumerate(items):
            for b in items[n + 1:]:
                if a['source'] == b['source']: continue
                if {a['source'], b['source']} == {'guiabcn', 'opendatabcn_agenda'} and a['key'].split(':')[1] == b['key'].split(':')[1]: continue
                common, least = a['words'] & b['words'], min(len(a['words']), len(b['words']))
                if not (len(common) >= 2 or (common and len(common) == least)) or len(common) < 0.6 * least: continue
                if a['times'] and b['times'] and not (a['times'] & b['times']): continue
                if not _named_site_match(a, b) or not _same_site(a, b, km=0.15): continue
                pairs.append((a['key'], b['key']))
    return pairs
