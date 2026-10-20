"""Muestra de las agendas de sala leídas con IA, para revisarlas antes de publicarlas.

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):
    python3 scripts/muestra_agendas_ia.py            # las 20 agendas de config/agendas_ia.json
    python3 scripts/muestra_agendas_ia.py marula filmoteca
Lee cada página, pide los actos a la IA, aplica la misma comprobación que el trabajo automático y
escribe reports/muestra_agendas_ia.html: por sala, lo que entraría (con sus citas) y lo descartado
(con el motivo). No escribe nada en la base. Para publicar una sala: "activa": true en
config/agendas_ia.json.
"""
import datetime as dt
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import ai_agenda, ai_assist  # noqa: E402


def main(slugs=()):
    key = ai_assist.load_key()
    if not key: sys.exit('Falta ANTHROPIC_API_KEY en .env')
    today = dt.date.today(); usage = {}; parts = []; summary = []
    for agenda in ai_agenda.load_agendas():
        if slugs and agenda['slug'] not in slugs: continue
        # Reutiliza lo leído hoy (si una ejecución anterior se cortó) en lugar de volver a pagar la IA.
        try: cached = json.loads((ROOT / 'reports' / 'muestra_agendas_ia.json').read_text(encoding='utf-8')).get(agenda['slug'])
        except (OSError, ValueError): cached = None
        if cached and cached.get('day') == today.isoformat() and '--de-nuevo' not in sys.argv:
            res = cached['result']
            for a in res['accepted']: a['sesiones'] = [tuple(x) for x in a['sesiones']]
        else:
          try: res = ai_agenda.read_agenda(agenda, today, key, usage=usage)
          except Exception as error: res = {'pages': [{'url': '', 'error': str(error)}], 'accepted': [], 'rejected': []}
        try:
            cache_path = ROOT / 'reports' / 'muestra_agendas_ia.json'
            cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
            cache[agenda['slug']] = {'day': today.isoformat(), 'result': res}
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, default=list), encoding='utf-8')
        except (OSError, ValueError): pass
        errors = [p['error'] for p in res['pages'] if p.get('error')]
        summary.append(f"{agenda['name']}: {len(res['accepted'])} actos" + (f" · {len(res['rejected'])} descartados" if res['rejected'] else '') + (f" · ERROR {errors[0]}" if errors else ''))
        rows = ''.join(
            f"<tr><td><b>{html.escape(a['titulo'])}</b>{'<br><small>' + html.escape(a['sala']['name']) + '</small>' if a.get('sala') else ''}"
            f"{'<br><a href=' + json.dumps(a['url']) + ' target=_blank>ficha</a>' if a.get('url') else ''}</td>"
            f"<td>{'<br>'.join(html.escape(d + (' ' + h if h else '')) for d, h in a['sesiones'][:12])}{'…' if len(a['sesiones']) > 12 else ''}"
            f"{html.escape(' → '.join(a['periodo'])) if a.get('periodo') else ''}</td><td>{html.escape(a.get('precio') or '')}</td>"
            f"<td><small>{'<br>'.join(html.escape(k + ': «' + v + '»') for k, v in a['quotes'].items())}</small>"
            f"{'<br><small class=ko>' + html.escape('; '.join(a['why_partial'])) + '</small>' if a.get('why_partial') else ''}</td></tr>"
            for a in sorted(res['accepted'], key=lambda a: a['sesiones'][0][0] if a['sesiones'] else (a.get('periodo') or ('',))[0]))
        bad = ''.join(f"<li><b>{html.escape(str(r['item'].get('titulo')))}</b> — {html.escape('; '.join(r['why']))}</li>" for r in res['rejected'])
        pages = ' · '.join(html.escape(f"{p['url']} ({p.get('chars', 0)} car.)" + (f" ERROR {p['error']}" if p.get('error') else '')) for p in res['pages'])
        parts.append(f"<h2>{html.escape(agenda['name'])} · {len(res['accepted'])} actos</h2><p class=msg>{pages}</p>"
                     f"<table><tr><th>Acto</th><th>Fechas y horas</th><th>Precio</th><th>Citas</th></tr>{rows}</table>"
                     + (f"<details><summary>Descartados ({len(res['rejected'])})</summary><ul>{bad}</ul></details>" if bad else ''))
    page = f"""<!doctype html><meta charset="utf-8"><title>Muestra agendas IA</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%;margin-bottom:12px}}td,th{{border:1px solid #ddd;padding:6px;vertical-align:top}}.msg{{color:#666;font-size:12px}}.ko{{color:#b00}}</style>
<h1>Agendas de sala leídas con IA · {today.isoformat()}</h1><p>{'<br>'.join(html.escape(s) for s in summary)}</p><p class=msg>Tokens: {html.escape(json.dumps(usage))}</p>
<p>Revisa que cada acto, fecha, hora y precio estén bien. Para publicar una sala: "activa": true en config/agendas_ia.json.</p>{''.join(parts)}"""
    out = ROOT / 'reports' / 'muestra_agendas_ia.html'; out.write_text(page, encoding='utf-8')
    print('\n'.join(summary)); print('Tokens:', json.dumps(usage)); print(out)


if __name__ == '__main__':
    main(tuple(a for a in sys.argv[1:] if not a.startswith('--')))
