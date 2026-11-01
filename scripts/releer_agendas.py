"""Vuelve a leer ya, aunque su página no haya cambiado, las agendas de sala indicadas (1-11-2026: para traer las
imágenes con las reglas nuevas sin esperar a la lectura diaria). Toma el candado del motor: si el motor está en
marcha, no hace nada y lo dice.

    python3 scripts/releer_agendas.py filmoteca phenomena espai_texas santa_monica disseny_hub
"""
import datetime as dt
import json
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(slugs):
    from mvp import catalog
    from src import ai_agenda, ai_assist
    from src.automation import initialize
    key = ai_assist.load_key()
    if not key: sys.exit('Falta ANTHROPIC_API_KEY en .env')
    agendas = {a['slug']: a for a in ai_agenda.load_agendas()}
    unknown = [s for s in slugs if s not in agendas]
    if unknown: sys.exit('No existen estas agendas: ' + ', '.join(unknown))
    with closing(catalog.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3')) as conn:
        catalog.initialize(conn); initialize(conn)
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
        with conn:
            got = conn.execute("INSERT OR IGNORE INTO automation_locks(name,held_at) VALUES ('engine',?)", (now,)).rowcount
        if not got: sys.exit('El motor está en marcha: espera a que acabe la pasada y vuelve a lanzarlo.')
        try:
            for slug in slugs:
                res = ai_agenda.sync_agenda(conn, agendas[slug], key, force=True)
                print(json.dumps({k: res.get(k) for k in ('source', 'status', 'rows_received', 'images_fetched', 'held', 'error') if res.get(k) is not None}, ensure_ascii=False), flush=True)
            catalog.invalidate_cache()
        finally:
            with conn: conn.execute("DELETE FROM automation_locks WHERE name='engine'")


if __name__ == '__main__':
    if len(sys.argv) < 2: sys.exit(__doc__)
    main(sys.argv[1:])
