"""Compara la Selección Ontoca guardada (criterio anterior) con la del criterio vigente de config/ia_seleccion.md, sin
guardar nada (30-10-2026, David: validar antes de publicar). Una llamada a la IA por día y alcance.

Uso: python3 scripts/comparar_seleccion.py [días, 7 por defecto]  → reports/seleccion_comparada.html
"""
import datetime as dt
import html
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import ai_assist, ai_select  # noqa: E402

DIAS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
conn = sqlite3.connect(f"file:{ROOT / 'reports' / 'loagendo_v12.sqlite3'}?mode=ro", uri=True, timeout=60)
key = ai_assist.load_key()
if not key: sys.exit('Falta ANTHROPIC_API_KEY en .env')
esc = lambda x: html.escape(str(x or ''))
today = catalog.today()
cases = [(today.isoformat(), 'week')] + [((today + dt.timedelta(days=i)).isoformat(), 'day') for i in range(DIAS)]
parts, usage = [], {}
for day, scope in cases:
    items = ai_select.candidates(conn, day, scope)
    by_key = {e['key']: e for e in items}
    row = conn.execute('SELECT picks_json FROM ai_selection WHERE day=? AND scope=?', (day, scope)).fetchone()
    old = json.loads(row[0]) if row else []
    message = ai_assist._request('POST', f'{ai_assist.API}/messages', key, ai_select.request_body(items, day, scope, ai_assist.MODEL), timeout=180)
    for k, v in (message.get('usage') or {}).items():
        if isinstance(v, int): usage[k] = usage.get(k, 0) + v
    chosen, popular = ai_select.parse(message, items)
    line = lambda e, why='': '<li>%s <span style="color:#777">· %s · %s%s</span>%s</li>' % (
        esc(e['title'][:80]), esc((e.get('venue_names') or [''])[0][:40]), esc(e.get('public_category')), (' · ' + esc(e.get('time'))) if e.get('time') else '',
        ('<br><i style="color:#555">%s</i>' % esc(why)) if why else '')
    old_html = ''.join('<li>%s <span style="color:#777">· %s</span></li>' % (esc(p['title'][:80]), esc(p.get('tipo'))) for p in old) or '<li>—</li>'
    parts.append('<h2>%s · %s</h2><table><tr><th>Antes (guardada)</th><th>Ahora: Selección (%d)</th><th>Ahora: Popular (%d)</th></tr>'
                 '<tr><td><ol>%s</ol></td><td><ol>%s</ol></td><td><ul>%s</ul></td></tr></table>' % (
        esc(day), 'semana' if scope == 'week' else 'día', len(chosen), len(popular), old_html,
        ''.join(line(e, why) for e, _, why in chosen) or '<li>—</li>', ''.join(line(e) for e in popular) or '<li>—</li>'))
    print(day, scope, 'antes', len(old), '· selección', len(chosen), '· populares', len(popular))
out = ROOT / 'reports' / 'seleccion_comparada.html'
out.write_text('<!doctype html><meta charset="utf-8"><title>Selección comparada</title><style>body{font:14px -apple-system,Helvetica,sans-serif;max-width:1200px;margin:20px auto;padding:0 16px}'
               'table{width:100%%;border-collapse:collapse}td,th{vertical-align:top;border:1px solid #ddd;padding:6px;width:33%%;text-align:left}li{margin:3px 0}</style>'
               '<h1>Selección Ontoca: criterio anterior y nuevo</h1><p>Generado el %s · criterio %s · tokens %s</p>%s' % (
                   dt.datetime.now().strftime('%d-%m-%Y %H:%M'), ai_select.version(), usage.get('input_tokens', 0) + usage.get('output_tokens', 0), ''.join(parts)), encoding='utf-8')
print('→', out)
