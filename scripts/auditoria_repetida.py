"""Auditoría puntual: vuelve a revisar las fichas de una auditoría anterior y añade otras nuevas (27-10-2026).

Uso: python3 scripts/auditoria_repetida.py 2026-10-27 [nuevas=80]
Deja el informe en reports/auditorias/<hoy>-repetida.(md|json|jsonl) y lo manda por correo como la semanal.
No escribe en las fichas ni en la base."""
import json, sys
from contextlib import closing
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from mvp import catalog
from src import weekly_audit
from src.automation import load_config

previous = sys.argv[1]; new = int(sys.argv[2]) if len(sys.argv) > 2 else 80
job = next(j for j in load_config(ROOT / 'config' / 'automation.json')['jobs'] if j['name'] == 'auditoria-semanal')
job = {**job, 'repeat': previous, 'size': new, 'suffix': '-repetida', 'max_tokens': 24000}
with closing(catalog.connect(ROOT / 'reports' / 'loagendo_v12.sqlite3')) as conn:
    print(json.dumps(weekly_audit.run(conn, job), ensure_ascii=False, indent=2))
