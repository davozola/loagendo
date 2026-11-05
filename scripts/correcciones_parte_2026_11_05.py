"""Correcciones del parte del 5-11-2026 (auditoría del 3-11, errores graves que seguían): pasada única, reversible.
Quedan como correcciones editoriales (classification_overrides + su registro), que sobreviven a las sincronizaciones.
Para deshacer una: taxonomy.set_override(conn, fuente, id, category=None, note='…') o borrar su fila de classification_overrides
(el registro, classification_override_log, se queda)."""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import taxonomy  # noqa: E402

TEXAS = 'venue_ia_espai_texas'
L_ESTIUEIG = "RITA: en la cartelera de Espai Texas hace funciones del 6/11 al 13/12; las del %s son de L'ESTIUEIG (la IA las tomó del bloque de otro día; auditoría 3-11-2026)"
FIXES = [
    ('venue_ia_festival_42', '09b448c42a798a21e9ee2f1e', 'charlas', "50 anys de 'Carrie': charla sobre la película, no una proyección (auditoría 3-11-2026)"),
    ('venue_eventbrite', '0e283bcfca2e37746891c085', taxonomy.EXCLUDED, 'Taller de mascarilla facial en una tienda LUSH: actividad comercial de una marca, no un plan cultural (auditoría 3-11-2026, decisión 5-11-2026)'),
    (TEXAS, 'f53b311e7cebfdfbff4b2fc7', taxonomy.EXCLUDED, L_ESTIUEIG % '16-12'),
    (TEXAS, 'c3f6611271aa0226883e86fc', taxonomy.EXCLUDED, L_ESTIUEIG % '17-12'),
    (TEXAS, '778436b3a4b6f7a3923deb92', taxonomy.EXCLUDED, L_ESTIUEIG % '18-12'),
    (TEXAS, 'dc8eaa3c5ad92823fe68b97b', taxonomy.EXCLUDED, L_ESTIUEIG % '19-12'),
    (TEXAS, '62931e35310e06bc887f9414', taxonomy.EXCLUDED, L_ESTIUEIG % '20-12'),
    (TEXAS, '758baa7e5a054b06b6f39cc8', taxonomy.EXCLUDED, L_ESTIUEIG % '23-12'),
    (TEXAS, 'd586f29cb19e7c22d7fed385', taxonomy.EXCLUDED, 'RITA del 18/09/26 al 29/01/27: ese periodo es el de BIOPIC, la obra siguiente en la cartelera (auditoría 3-11-2026)'),
]

conn = sqlite3.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3', timeout=60)
for source, rid, cat, note in FIXES:
    if conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?', (source, rid)).fetchone():
        taxonomy.set_override(conn, source, rid, category=cat, note=note); print('corregido', source, rid, '→', cat)
    else:
        print('no encontrado', source, rid)
