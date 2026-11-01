"""Publicación extrarrápida (1-11-2026, David): solo la web (JS, CSS, portada y páginas de entrada), sin tocar datos.

Para cambios de diseño o de comportamiento de la página. Copia a dist/ lo de static/ con publish_static.refresh_shell
(los mismos pasos que la publicación completa para esa parte) y sube dist/ con el mismo comando. No recalcula fichas,
días ni la Selección: eso lo hacen publicar_rapido.py (Selección) y la publicación completa. Menos de un minuto.
Uso: python3 scripts/publicar_web.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import publish_static as ps  # noqa: E402

OUT = ROOT / 'dist'
if not (OUT / 'data' / 'meta.json').exists(): sys.exit('No hay dist/data: hay una publicación completa en marcha o falta una. Espera a que termine.')
job = next(j for j in json.loads((ROOT / 'config' / 'automation.json').read_text(encoding='utf-8'))['jobs'] if j['name'] == 'publicar-web')
res = ps.refresh_shell(OUT, ROOT / 'static', job.get('site_url'), job.get('alerts'))
print('web al día:', json.dumps(res.get('versions'), ensure_ascii=False))
dep = ps.deploy(OUT, job['deploy_command'], env_file=job.get('env_file') or (ROOT / 'config' / 'publish.env'))
print(json.dumps({'subida': dep['status'], 'salida': dep['output_tail'][-300:]}, ensure_ascii=False, indent=1))
