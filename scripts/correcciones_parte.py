"""Correcciones del parte del 28-10-2026 (auditoría del 27-10, errores graves que seguían): pasada única, reversible.
Quedan como correcciones editoriales (classification_overrides + su registro), que sobreviven a las sincronizaciones."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import taxonomy  # noqa: E402

FIXES = [
    ('venue_ia_balana', '3abaa14b1c6d02f39a654db6', 'charlas', 'Victor Küppers: charla motivacional, no teatro (auditoría 27-10-2026)'),
    ('venue_ticketmaster_es', '44bb6c00c471c0f45a6c14c4', 'musica', 'Love Actually en Concierto: película con orquesta sinfónica en directo (auditoría 27-10-2026)'),
    ('generalitat', '2026100900024', 'escena', 'Sâlmon: festival de artes vivas (danza y performance), no cine (auditoría 27-10-2026)'),
]

conn = sqlite3.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3', timeout=60)
for source, rid, cat, note in FIXES:
    if conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?', (source, rid)).fetchone():
        taxonomy.set_override(conn, source, rid, category=cat, note=note); print('corregido', source, rid, '→', cat)
    else:
        print('no encontrado', source, rid)
