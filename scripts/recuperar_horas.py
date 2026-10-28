"""Recuperación de horas, pasada única (28-10-2026, auditoría de actividades sin hora).

  1. Vuelve a leer, aunque sus páginas no hayan cambiado, las agendas de sala corregidas: Zumzeig (hora pegada a la fecha y
     enlace de otro acto) y Documenta (fecha y hora pegadas al limpiar). Usa la IA de siempre, con su comprobación.
  2. Relee con reglas (sin IA) la página propia de los actos de sala sin hora de los próximos 30 días (un día o una noche
     que acaba de madrugada) y de las obras en cartel sin días de función (El Maldà): franja única, bloque «Horaris» y
     excepciones. Lo que encuentra queda en official_pages, con la URL y el extracto como evidencia.

Uso: python3 scripts/recuperar_horas.py [--sin-ia]
"""
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import ai_agenda, ai_assist, official_dates  # noqa: E402
from src.venue_feeds import fetch, robots_allows  # noqa: E402

DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'
AGENDAS = ('zumzeig', 'documenta')


def main():
    conn = sqlite3.connect(DB, timeout=60)
    today = dt.date.today(); horizon = (today + dt.timedelta(days=30)).isoformat()
    if '--sin-ia' not in sys.argv:
        key = ai_assist.load_key()
        for a in ai_agenda.load_agendas():
            if a['slug'] in AGENDAS:
                r = ai_agenda.sync_agenda(conn, a, key, force=True)
                print('agenda', a['slug'], {k: r.get(k) for k in ('status', 'rows_received', 'rejected', 'error')})
                w = conn.execute("SELECT warning_json FROM sync_runs WHERE source=? ORDER BY id DESC LIMIT 1", ('venue_ia_' + a['slug'],)).fetchone()
                for line in json.loads((w or ['[]'])[0] or '[]')[:6]: print('   ', line)
    official_dates.initialize_pages(conn)
    rows = conn.execute("""SELECT r.source, r.id, r.title, substr(r.start_date,1,10), substr(r.end_date,1,10), r.source_url FROM source_records r
        WHERE r.source LIKE 'venue_ia_%' AND r.eligibility<>'exclude' AND r.kind<>'exhibition'
          AND substr(r.end_date,1,10)>=? AND substr(r.start_date,1,10)<=?
          AND NOT EXISTS (SELECT 1 FROM candidate_occurrences c WHERE c.source=r.source AND c.id=r.id AND c.local_time<>'')""",
                        (today.isoformat(), horizon)).fetchall()
    todo = []
    for source, rid, title, start, end, url in rows:
        a, b = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
        if (b - a).days > 1 and source != 'venue_ia_el_malda': continue
        if url and official_dates.usable(url) and official_dates.same_act(title, url.split('/', 3)[-1] if '//' in url else url):
            todo.append((source, rid, title, start, end, url))
    print('páginas de acto por releer:', len(todo))
    found = {}
    for source, rid, title, start, end, url in todo:
        try:
            res = {'status': 'robots'} if not robots_allows(url) else official_dates.read_page(url, title, start, end, fetch, 15)
        except Exception as error:
            res = {'status': 'error: ' + type(error).__name__}
        time.sleep(0.5)
        with conn:
            conn.execute("""INSERT INTO official_pages(source,id,url,times_json,price,free,excerpt,status,checked_at,sessions_json) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET url=excluded.url,times_json=excluded.times_json,price=excluded.price,free=excluded.free,
                excerpt=excluded.excerpt,status=excluded.status,checked_at=excluded.checked_at,sessions_json=excluded.sessions_json""",
                         (source, rid, url, json.dumps(res.get('times') or {}), res.get('price') or '', int(bool(res.get('free'))), res.get('excerpt') or '',
                          res['status'], dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'), json.dumps(res.get('sessions') or {})))
        if res.get('times'): found.setdefault(source, []).append((title[:50], res['times']))
    for source, items in sorted(found.items()):
        print(source, len(items))
        for t, h in items[:4]: print('   ', t, h)
    from mvp import catalog; catalog.invalidate_cache()


if __name__ == '__main__':
    main()
