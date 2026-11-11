"""Correcciones del parte del 10-11-2026 (auditoría del 10-11): pasada única, reversible (classification_overrides + registro).
Para deshacer: taxonomy.set_override(conn, fuente, id, category=None, note='…')."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import taxonomy  # noqa: E402

FIXES = [
    ('venue_eventbrite', '60446ff39aaea0b3dec9de42', taxonomy.EXCLUDED,
     'Taller gratuito sobre Registros Akáshicos: captación de servicios esotéricos, no un plan cultural (auditoría 10-11-2026; mismo criterio que el taller de LUSH del 5-11)'),
]

conn = sqlite3.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3', timeout=60)
for source, rid, cat, note in FIXES:
    if conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?', (source, rid)).fetchone():
        taxonomy.set_override(conn, source, rid, category=cat, note=note); print('corregido', source, rid, '→', cat)
    else:
        print('no encontrado', source, rid)
