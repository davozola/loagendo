"""Valoración «para ir en familia» de las exposiciones, para revisar antes de publicarla.

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):  python3 scripts/muestra_familia.py [n]
Pide a la IA la valoración de n exposiciones (todas por defecto) que hoy no están en «En familia»,
aplica la misma comprobación que el trabajo automático y escribe reports/muestra_familia.html,
agrupado en «sí (entraría)», «sí pero no pasa la comprobación», «dudoso» y «no». No escribe nada
en la base. Si te convence: config/ia.json → "familia_ia_publica": true.
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
from src import ai_assist, ai_family, taxonomy  # noqa: E402


def main(n=0, db=None):
    conn = catalog.connect(Path(db or ROOT / 'reports' / 'loagendo_v12.sqlite3'))
    today = catalog.today().isoformat()
    pool = [e for e in catalog.all_events(conn) if taxonomy.eligible(e, today) and ai_family.needs(e)]
    random.seed(dt.date.today().isoformat())
    sample = random.sample(pool, min(n, len(pool))) if n else pool
    items = [(e['key'], ai_family.payload(e)) for e in sample]
    usage = {}; answers = ai_assist.ask_now('familia', items, usage=usage)
    groups = {'entra': [], 'si_rechazado': [], 'dudoso': [], 'no': [], 'sin_respuesta': []}
    for e, (key, payload) in zip(sample, items):
        got = answers.get(key)
        if not got: groups['sin_respuesta'].append((e, None, 0)); continue
        a = json.loads(got[0]); conf = got[1]
        group = 'entra' if ai_family.accepted(a, conf) else 'si_rechazado' if a['valoracion'] == 'si' else a['valoracion']
        groups[group].append((e, a, conf))
    names = {'entra': 'Sí: entraría en «En familia»', 'si_rechazado': 'Sí, pero no entra (confianza < 80 % o motivo que no pasa la comprobación)',
             'dudoso': 'Dudoso (no entra)', 'no': 'No (no entra)', 'sin_respuesta': 'Sin respuesta'}
    parts = []
    for g, rows in groups.items():
        if not rows: continue
        trs = ''.join(f"""<tr><td><b>{html.escape(e['title'])}</b><br><small>{html.escape((e.get('venue_names') or [''])[0])}</small>
          <details><summary>Texto de la fuente</summary><p>{html.escape(e.get('source_text') or '(sin texto)')}</p></details></td>
          <td>{html.escape(a['es']) if a else ''}<br><small>{html.escape(a['ca']) if a else ''}</small>{('<br><small class=ko>' + html.escape('; '.join(a['problems'])) + '</small>') if a and a['problems'] else ''}</td>
          <td>{round(conf * 100)} %</td></tr>""" for e, a, conf in sorted(rows, key=lambda r: -r[2]))
        parts.append(f"<h2>{names[g]} · {len(rows)}</h2><table><tr><th>Exposición</th><th>Motivo</th><th>Confianza</th></tr>{trs}</table>")
    page = f"""<!doctype html><meta charset="utf-8"><title>Muestra familia IA</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%;margin-bottom:24px}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top}}td:last-child{{width:80px}}.ko{{color:#b00}}details p{{white-space:pre-wrap;color:#555}}</style>
<h1>Exposiciones «para ir en familia» según la IA · {len(sample)}</h1><p>Tokens: {html.escape(json.dumps(usage))}.
Revisa sobre todo el primer grupo (lo que se publicaría) y si en «dudoso» o «no» falta algo claro.
Para publicarlo: config/ia.json → "familia_ia_publica": true.</p>{''.join(parts)}"""
    out = ROOT / 'reports' / 'muestra_familia.html'; out.write_text(page, encoding='utf-8')
    print(' · '.join(f'{names[g].split(":")[0].split(" (")[0]}: {len(r)}' for g, r in groups.items()), '·', out)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
