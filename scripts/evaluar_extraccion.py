"""Prueba de la extracción con IA contra datos que ya conocemos (sin escribir nada en la base).

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):  python3 scripts/evaluar_extraccion.py [n]

  · Horas y precios: fichas cuya fuente ya da la hora o el precio de forma estructurada y que tienen
    texto propio. La IA lee solo el texto; se compara lo que extrae (tras la comprobación de cita)
    con el dato estructurado.
  · Edades: fichas donde las reglas ya encontraron la edad; se compara con lo que lee la IA.
  · Duplicados: pares que las reglas fusionan con seguridad (deberían ser «mismo») y pares del mismo
    día en salas distintas (deberían ser «distinto»).
"""
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import ai_assist, ai_extract, dedupe, taxonomy  # noqa: E402

KNOWN_TIME = ('official_schedule_by_day', 'official_detail_page', 'source_schedule_text')


def nums(label):
    return {float(x.replace(',', '.')) for x in re.findall(r'\d+(?:[.,]\d+)?', label or '')}


def main(n=120, db=None):
    conn = catalog.connect(Path(db) if db else ROOT / 'reports' / 'loagendo_v12.sqlite3'); today = catalog.today().isoformat()
    events = [e for e in catalog.all_events(conn) if taxonomy.eligible(e, today) and e['public_category'] not in ('pendiente', 'excluida')]
    random.seed(20261020)
    with_text = [e for e in events if len(e.get('source_text') or '') >= 40]
    timed = [e for e in with_text if e['start'] == e['end'] and e.get('time') and e.get('time_source') in KNOWN_TIME + ('candidate_occurrence',)]
    priced = [e for e in with_text if e.get('is_free') or e.get('price_label')]
    aged = [e for e in with_text if e.get('age_source') == 'fuente']
    sample = {e['key']: e for e in random.sample(timed, min(n, len(timed))) + random.sample(priced, min(n, len(priced))) + random.sample(aged, min(40, len(aged)))}
    usage = {}
    answers = ai_assist.ask_now('datos', [(k, ai_extract.payload(e)) for k, e in sample.items()], usage=usage)
    t = Counter(); p = Counter(); a = Counter(); misses = []; timed_keys = {e['key'] for e in timed}
    import json
    for k, e in sample.items():
        got = json.loads(answers[k][0]) if k in answers else None
        if got is None: t['sin_respuesta'] += 1; continue
        if k in timed_keys:
            t['n'] += 1; times = {s['time'] for s in got.get('sessions', []) if s.get('time')}
            if not times: t['no_extrae'] += 1
            elif e['time'] in times: t['ok'] += 1
            else: t['distinta'] += 1; misses.append(('hora', e['title'][:60], e['time'], sorted(times)[:3], got['sessions'][0]['quote'][:80]))
        if e.get('is_free') or e.get('price_label'):
            p['n'] += 1; price = got.get('price')
            if not price: p['no_extrae'] += 1
            elif price['free'] == bool(e.get('is_free')) and (price['free'] or nums(price['label']) & nums(e.get('price_label'))): p['ok'] += 1
            else: p['distinto'] += 1; misses.append(('precio', e['title'][:60], 'gratis' if e.get('is_free') else e.get('price_label'), price['label'], price['quote'][:80]))
        if e.get('age_source') == 'fuente':
            a['n'] += 1; ages = got.get('ages')
            if not ages: a['no_extrae'] += 1
            elif ages['min'] == e['age_min'] and ages['max'] == e['age_max']: a['ok'] += 1
            else: a['distinta'] += 1; misses.append(('edad', e['title'][:60], (e['age_min'], e['age_max']), (ages['min'], ages['max']), ages['quote'][:80]))
    # Duplicados
    by_key = {e['key']: e for e in catalog.all_events(conn)}
    groups = dedupe.canonical_groups(conn)
    same = [(m, c) for m, c in groups.items() if m in by_key and c in by_key and by_key[m]['end'] >= today][:400]
    same = random.sample(same, min(40, len(same)))
    by_day = {}
    for e in events:
        if e['start'] == e['end']: by_day.setdefault(e['start'], []).append(e)
    diff = []
    for day, items in by_day.items():
        if len(items) > 1:
            x, y = random.sample(items, 2)
            if (x.get('venue_names') or [''])[0] != (y.get('venue_names') or [''])[0]: diff.append((x['key'], y['key']))
    diff = random.sample(diff, min(40, len(diff)))
    pairs = [(f'{a_}|{b_}', ai_assist.pair_payload(by_key[a_], by_key[b_])) for a_, b_ in same + diff]
    verdicts = ai_assist.ask_now('duplicado', pairs, usage=usage)
    d = Counter()
    for i, (item, _) in enumerate(pairs):
        want = 'mismo' if i < len(same) else 'distinto'; v = verdicts.get(item)
        if not v: d['sin_respuesta'] += 1; continue
        applied = 'mismo' if v[0] == 'mismo' and v[1] >= ai_assist.APPLY_DUPLICATE else 'no'
        d[f'{want}→{v[0]}'] += 1
        if want == 'distinto' and applied == 'mismo': d['FUSIÓN ERRÓNEA'] += 1; misses.append(('dup', item, v))
        if want == 'mismo' and applied == 'mismo': d['fusiones correctas'] += 1
    pct = lambda c: f"{c['ok']}/{c['n']} correctos · {c['no_extrae']} sin extraer · {c.get('distinta', 0) + c.get('distinto', 0)} distintos"
    print('Horas:   ', pct(t), f"· sin respuesta {t['sin_respuesta']}")
    print('Precios: ', pct(p))
    print('Edades:  ', pct(a))
    print('Duplicados:', dict(d))
    print('Tokens:', usage)
    for m in misses[:40]: print('  ✗', m)


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
