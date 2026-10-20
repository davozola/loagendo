"""Muestra de 50 descripciones breves con IA para revisar antes de publicarlas.

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):  python3 scripts/muestra_descripciones.py [n]
Genera n descripciones (50 por defecto) de fichas al azar con texto de la fuente, las pasa por la
misma comprobación que el trabajo automático y escribe reports/muestra_descripciones.html con el
texto original al lado. No escribe nada en la base. Si te convencen: config/ia.json →
"descripciones_publicas": true.
"""
import datetime as dt
import html
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import ai_assist, ai_describe, taxonomy  # noqa: E402


def main(n=50, db=None):
    conn = catalog.connect(Path(db or ROOT / 'reports' / 'loagendo_v12.sqlite3'))
    today = catalog.today().isoformat()
    pool = [e for e in catalog.all_events(conn) if taxonomy.eligible(e, today) and ai_describe.needs(e) and e['public_category'] not in ('pendiente', 'excluida')]
    random.seed(dt.date.today().isoformat()); sample = random.sample(pool, min(n, len(pool)))
    items = [(e['key'], ai_describe.payload(e)) for e in sample]
    usage = {}; answers = ai_assist.ask_now('descripcion', items, usage=usage)
    rows = []; ok = 0
    for e, (key, payload) in zip(sample, items):
        answer = answers.get(key)
        result = json.loads(answer[0]) if answer else {'es': '', 'ca': '', 'ok': False, 'problems': ['sin respuesta']}
        ok += result['ok']
        rows.append(f"""<tr class="{'ok' if result['ok'] else 'ko'}"><td><b>{html.escape(e['title'])}</b><br><small>{html.escape(e['source'])} · {html.escape((e.get('venue_names') or [''])[0])}</small>
          <details><summary>Texto original</summary><p>{html.escape(payload['texto'])}</p></details></td>
          <td>{html.escape(result['es'])}</td><td>{html.escape(result['ca'])}</td><td>{'✓' if result['ok'] else '✗ ' + html.escape('; '.join(result['problems']))}</td></tr>""")
    page = f"""<!doctype html><meta charset="utf-8"><title>Muestra de descripciones IA</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top}}tr.ko{{background:#fff3f3}}details p{{white-space:pre-wrap;color:#555}}</style>
<h1>Descripciones breves con IA · muestra de {len(rows)}</h1><p>Aceptadas por la comprobación automática: {ok}/{len(rows)}. Tokens: {html.escape(json.dumps(usage))}.
Revisa sobre todo que no añadan nada que el original no diga. Para publicarlas: config/ia.json → "descripciones_publicas": true.</p>
<table><tr><th>Ficha y texto original</th><th>Castellano</th><th>Català</th><th>Comprobación</th></tr>{''.join(rows)}</table>"""
    out = ROOT / 'reports' / 'muestra_descripciones.html'; out.write_text(page, encoding='utf-8')
    print(f'{ok}/{len(rows)} aceptadas · {out}')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 50)
