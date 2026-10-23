"""Muestra de traducción automática al inglés para evaluar calidad y coste (23-10-2026).

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):  python3 scripts/muestra_traduccion.py [n]
Traduce n descripciones (200 por defecto) de fichas publicadas al azar, repartidas por fuente, las
pasa por la comprobación de src/ai_translate.py y escribe reports/muestra_traduccion.html con el
original al lado, más el consumo de tokens medido y su proyección a todo el catálogo y a las fichas
nuevas de cada día. No escribe nada en la base ni publica nada.
"""
import collections
import datetime as dt
import html
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import ai_assist, ai_translate, taxonomy  # noqa: E402


def main(n=200, db=None):
    conn = catalog.connect(Path(db or ROOT / 'reports' / 'loagendo_v12.sqlite3'))
    today = catalog.today().isoformat()
    public = [e for e in catalog.all_events(conn) if taxonomy.eligible(e, today) and catalog.is_public(e) and e.get('has_description')]
    # Reparto por fuente, proporcional pero con un mínimo, para ver todos los tipos de texto.
    random.seed('traduccion-' + today)
    by_source = collections.defaultdict(list)
    for e in public: by_source[e['source']].append(e)
    picks = []
    for source, events in by_source.items():
        share = max(2, round(n * len(events) / max(1, len(public))))
        picks += random.sample(events, min(share, len(events)))
    random.shuffle(picks)
    details = []
    for e in picks:
        d = catalog.event_detail(conn, e['source'], e['id'])
        if d and ai_translate.needs(d.get('description')): details.append(d)
        if len(details) >= n: break
    items = [(d['key'], ai_translate.payload(d)) for d in details]
    chars = sum(len(p['text']) for _, p in items)
    usage = {}; answers = ai_assist.ask_now('traduccion', items, usage=usage)
    rows, ok, langs = [], 0, collections.Counter()
    for d, (key, payload) in zip(details, items):
        answer = answers.get(key)
        r = json.loads(answer[0]) if answer else {'en': '', 'source_lang': '', 'ok': False, 'problems': ['sin respuesta']}
        ok += r['ok']; langs[r['source_lang'] or '?'] += 1
        rows.append(f"""<tr class="{'ok' if r['ok'] else 'ko'}"><td><b>{html.escape(d['title'])}</b><br><small>{html.escape(d['source'])} · {html.escape(r['source_lang'])} · {html.escape((d.get('venue_names') or [''])[0])}</small></td>
          <td><p>{html.escape(payload['text'])}</p></td><td><p>{html.escape(r['en'])}</p></td><td>{'✓' if r['ok'] else '✗ ' + html.escape('; '.join(r['problems']))}</td></tr>""")
    # Proyección: tokens por carácter medidos aquí × caracteres de todo el catálogo y de lo nuevo de cada día.
    total_chars = sum(min(len((e.get('source_text') or '')), ai_translate.MAX_TEXT) for e in public)
    week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    # Fichas publicadas que aparecieron por primera vez en la última semana (primera versión archivada).
    fresh = {f'{s}:{i}' for s, i in conn.execute("SELECT source, external_id FROM source_record_versions GROUP BY source, external_id HAVING MIN(substr(observed_at,1,10))>=?", (week_ago,))}
    new_per_day = sum(1 for e in public if e['key'] in fresh) / 7
    tin, tout = usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0) + usage.get('cache_creation_input_tokens', 0), usage.get('output_tokens', 0)
    per_char_in, per_char_out = tin / max(1, chars), tout / max(1, chars)
    proj_all = {'input_tokens': round(per_char_in * total_chars), 'output_tokens': round(per_char_out * total_chars)}
    avg_chars = chars / max(1, len(items))
    proj_day = {'fichas': round(new_per_day) if new_per_day else 'sin dato', 'input_tokens': round(per_char_in * avg_chars * new_per_day) if new_per_day else None,
                'output_tokens': round(per_char_out * avg_chars * new_per_day) if new_per_day else None}
    page = f"""<!doctype html><meta charset="utf-8"><title>Muestra de traducción al inglés</title>
<style>body{{font:14px system-ui;margin:24px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px;vertical-align:top}}td p{{white-space:pre-wrap;margin:0}}tr.ko{{background:#fff3f3}}</style>
<h1>Traducción automática al inglés · muestra de {len(rows)}</h1>
<p>Modelo {ai_assist.MODEL} · prompt v{ai_translate.PROMPT_VERSION} · {dt.datetime.now().strftime('%d-%m-%Y %H:%M')}. Aceptadas por la comprobación automática: <b>{ok}/{len(rows)}</b>.
Idioma de origen detectado: {html.escape(json.dumps(dict(langs)))}.</p>
<p>Tokens de esta muestra: {html.escape(json.dumps(usage))}. Caracteres traducidos: {chars:,}.</p>
<p><b>Proyección</b> (mismos tokens por carácter): todo el catálogo publicado ({len(public):,} fichas con descripción, {total_chars:,} caracteres) ≈ {proj_all['input_tokens']:,} tokens de entrada y {proj_all['output_tokens']:,} de salida, una sola vez.
Fichas nuevas al día ≈ {proj_day['fichas']} → ≈ {proj_day['input_tokens']} tokens de entrada y {proj_day['output_tokens']} de salida al día. Multiplica por el precio vigente del modelo para el coste.</p>
<p>Qué revisar: que no añada ni quite nada, que los nombres de obras, artistas y salas sigan igual y que el inglés suene natural.</p>
<table><tr><th>Ficha</th><th>Original</th><th>English</th><th>Comprobación</th></tr>{''.join(rows)}</table>"""
    out = ROOT / 'reports' / 'muestra_traduccion.html'; out.write_text(page, encoding='utf-8')
    print(f'{ok}/{len(rows)} aceptadas · tokens {usage} · {out}')


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
