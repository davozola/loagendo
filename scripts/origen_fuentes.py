#!/usr/bin/env python3
"""¿De dónde salen los actos de Brollant? Uso: python3 scripts/origen_fuentes.py [--salas 25]

Cuenta los actos vigentes (una vez cada uno, tras juntar duplicados) según la mejor fuente que
tienen (src/data_origin.py) y lista las salas que aún dependen de agregadores o directorios.
Solo lee la base de datos.
"""
import argparse
import collections
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import data_origin, dedupe  # noqa: E402

LABEL = {"centro": "Web o feed del propio centro", "web_oficial": "Página oficial del acto (corrige al agregador)", "red_publica": "Red pública que lo organiza",
         "agenda": "Agenda pública de otros (Ajuntament, Generalitat, GRAF)", "eventbrite": "Eventbrite", "directorio": "Directorio o ticketera"}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", default=str(ROOT / "reports" / "loagendo_v12.sqlite3")); ap.add_argument("--salas", type=int, default=25)
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    today = dt.date.today().isoformat()
    recs = {f"{s}:{i}": s for s, i in conn.execute("SELECT source,id FROM source_records WHERE end_date>=? AND eligibility<>'exclude'", (today,))}
    venue = {f"{s}:{i}": v or "" for s, i, v in conn.execute("SELECT source,id,venue FROM source_venues WHERE seq=0")}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    official = set()
    if "official_dates" in tables: official |= {f"{s}:{i}" for s, i in conn.execute("SELECT source,id FROM official_dates WHERE status='ok'")}
    if "official_pages" in tables: official |= {f"{s}:{i}" for s, i in conn.execute("SELECT source,id FROM official_pages WHERE status='ok' AND (times_json<>'{}' OR price<>'')")}
    groups = dedupe.canonical_groups(conn); members = collections.defaultdict(list)
    for k in recs:
        s, i = k.split(":", 1)
        if s == "guiabcn" and f"opendatabcn_agenda:{i}" in recs: k2 = f"opendatabcn_agenda:{i}"
        else: k2 = k
        members[groups.get(k2, k2)].append(k)
    count = collections.Counter(); weak = collections.defaultdict(collections.Counter)
    for ms in members.values():
        origins = [data_origin.of_source(recs[m], venue.get(m, "")) for m in ms] + (["web_oficial"] if any(m in official for m in ms) else [])
        best = data_origin.best(origins); count[best] += 1
        if best in ("agenda", "directorio"): weak[best][next((venue[m] for m in ms if venue.get(m)), "(sin sala)")[:50]] += 1
    total = sum(count.values())
    print(f"Actos vigentes (una vez cada uno): {total}\n")
    for k in data_origin.RANK: print(f"  {LABEL[k]:<58} {count[k]:>6}  ({100 * count[k] / max(total, 1):.0f} %)")
    for k in ("agenda", "directorio"):
        print(f"\nSalas que dependen de «{LABEL[k]}»:")
        for v, n in weak[k].most_common(args.salas): print(f"  {n:>4}  {v}")


if __name__ == "__main__":
    main()
