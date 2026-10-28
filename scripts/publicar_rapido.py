"""Publicación rápida de la web (28-10-2026, Selección por tipo): sin recalcular fichas, días ni tarjetas.

Copia a dist/ lo de static/ (JS, CSS y la portada con sus páginas de entrada, igual que publish_static.export), escribe
las selecciones por tipo (dist/data/picks/<día>.json) de los próximos DIAS días con las mismas reglas que la publicación
completa y sube dist/ con el mismo comando. Lo demás (datos del día, fichas, imágenes) se queda como estaba en dist/.
La siguiente publicación completa lo rehace todo. Uso: python3 scripts/publicar_rapido.py [días, 14 por defecto]
"""
import datetime as dt
import hashlib
import html
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import publish_static as ps, landings  # noqa: E402

DIAS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
OUT, STATIC = ROOT / 'dist', ROOT / 'static'
job = next(j for j in json.loads((ROOT / 'config' / 'automation.json').read_text(encoding='utf-8'))['jobs'] if j['name'] == 'publicar-web')
site_url, alerts = job.get('site_url', ''), job.get('alerts') or {}
if not (OUT / 'index.html').exists(): sys.exit('No hay dist/: hace falta una publicación completa antes.')
conn = sqlite3.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3', timeout=60)
today = catalog.today()

# 1. Selecciones por tipo de los próximos días (mismas funciones que la publicación completa).
images = ps.ImageExporter(conn, OUT, ROOT / 'data' / 'media', ps._registry())
try:
    for s, i, v in conn.execute("SELECT source,id,value_json FROM field_verifications WHERE field_name='venue'"):
        if isinstance(json.loads(v), str): ps._VERIFIED_VENUE[f'{s}:{i}'] = json.loads(v)
except sqlite3.Error:
    pass
resumen = {}
for n in range(DIAS + 1):
    day = (today + dt.timedelta(days=n)).isoformat()
    week = ps.featured_pool(conn, day, ps.PICK_POOL_WEEK)['items']
    one = catalog.query_events(conn, day=day, featured=True, featured_days=1, public=True, page_size=ps.PICK_POOL)['items']
    data = {'w': ps.picks_by_category(week, images), 't': ps.picks_by_category(one, images)}
    ps._write_json(OUT / 'data' / 'picks' / f'{day}.json', data)
    resumen[day] = {'7 días': {c: len(v) for c, v in data['w'].items()}, 'hoy': {c: len(v) for c, v in data['t'].items()}}
    print(day, json.dumps(resumen[day], ensure_ascii=False), flush=True)

# 2. JS, CSS y portada con sus páginas de entrada (lo mismo que export).
index = (STATIC / 'index.html').read_text(encoding='utf-8').replace('<html lang="es"', '<html lang="es" data-static="1"', 1)
if site_url: index = index.replace('</head>', f'<link rel="canonical" href="{html.escape(site_url.rstrip("/"))}/"></head>', 1)
for name in ps.STATIC_FILES:
    (OUT / name).parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(STATIC / name, OUT / name)
versions = {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest()[:10] for name in ('public.css', 'public.js', 'public-v2.css')}
for name in ('public.css', 'public.js'):
    index = index.replace(f'"/{name}"', f'"/{name}?v={versions[name]}"')
if ps.PUBLIC_SKIN == 'v2': index = ps.v2_index(index, versions['public-v2.css'])
if alerts.get('enabled') and alerts.get('turnstile_site_key'):
    index = index.replace('<html lang="es"', f'<html lang="es" data-alerts="1" data-turnstile="{html.escape(str(alerts["turnstile_site_key"]))}"', 1)
(OUT / 'index.html').write_text(index, encoding='utf-8')
days = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (OUT / 'data' / 'day').glob('*.json')}
for page in landings.pages(today):
    target = OUT / landings.file_for(page['path']); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(landings.render(index, page, days, site_url), encoding='utf-8')
print('portada y páginas de entrada al día')

# 3. Subida.
res = ps.deploy(OUT, job['deploy_command'], env_file=job.get('env_file') or (ROOT / 'config' / 'publish.env'))
print(json.dumps({'deploy': res['status'], 'returncode': res['returncode'], 'salida': res['output_tail'][-400:]}, ensure_ascii=False, indent=1))
