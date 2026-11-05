"""Espera a que termine la publicación completa en marcha (job publicar-web) y lanza después la rápida.

    python3 scripts/esperar_publicacion.py          # mira cada 5 minutos, como mucho 2 horas

Solo lee la base (modo ro). Si la completa falla o pasan 2 horas, se para y lo dice sin publicar nada.
"""
import datetime as dt
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'
EVERY, LIMIT = 300, 2 * 3600


def last_run():
    conn = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
    try: return conn.execute("SELECT id, started_at, finished_at, status, coalesce(error,'') FROM automation_runs WHERE job_name='publicar-web' ORDER BY id DESC LIMIT 1").fetchone()
    finally: conn.close()


start = time.time()
while True:
    rid, started, finished, status, error = last_run()
    now = dt.datetime.now().strftime('%H:%M')
    if status != 'running':
        print(f'{now} · publicación completa n.º {rid}: {status}' + (f' · {error[:200]}' if error else ''))
        if status != 'completed': sys.exit('No lanzo la rápida: la completa no terminó bien. Pásame este mensaje.')
        if not (ROOT / 'dist' / 'data').is_dir(): sys.exit('La completa terminó pero no hay dist/data. Pásame este mensaje.')
        break
    mins = int((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(started)).total_seconds() // 60)
    print(f'{now} · la publicación completa sigue en marcha ({mins} min); vuelvo a mirar en 5 minutos', flush=True)
    if time.time() - start > LIMIT: sys.exit('Llevo 2 horas esperando y sigue en marcha. Pásame este mensaje.')
    time.sleep(EVERY)
print('Lanzo la publicación rápida…')
sys.exit(subprocess.call([sys.executable, str(ROOT / 'scripts' / 'publicar_web.py')], cwd=ROOT))
