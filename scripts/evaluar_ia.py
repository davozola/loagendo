"""Prueba de la IA contra la muestra etiquetada (tests/fixtures/clasificacion_muestra_200.json).

Uso (en el Mac, con ANTHROPIC_API_KEY en .env):  python3 scripts/evaluar_ia.py
Llama a la API directamente (no por lotes; son ~320 fichas, unas pocas peticiones) y compara:
  · precisión de las reglas, de la IA y de la combinación que se aplica (IA solo en casos débiles
    y con confianza ≥ ai_assist.APPLY_CATEGORY);
  · tokens gastados.
No escribe nada en la base: es solo una medición.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402
from src import ai_assist  # noqa: E402


def main(db):
    conn = catalog.connect(Path(db)); sample = json.loads((ROOT / 'tests' / 'fixtures' / 'clasificacion_muestra_200.json').read_text())
    items = [i for i in sample['items'] + sample.get('stratified', {}).get('items', []) if not i['doubtful']]
    events = {}
    for i in items:
        e = catalog.event_detail(conn, i['source'], i['id'])
        if e: events[f"{i['source']}:{i['id']}"] = (i, e)
    usage = {}
    answers = ai_assist.ask_now('categoria', [(k, ai_assist.category_payload(e)) for k, (_, e) in events.items()], usage=usage)
    score = Counter(); weak = Counter(); misses = []
    for k, (item, e) in events.items():
        label = item['label']; rules = e.get('rule_status'); is_weak = rules in ('pendiente', 'probable') or e.get('rule_ambiguous')
        ai = answers.get(k); ai_cat = ai[0] if ai else None
        rule_cat = e['public_category'] if e.get('category_method') != 'ia' else None
        score['n'] += 1; score['reglas'] += rule_cat == label; score['ia'] += ai_cat == label
        # Política vigente: la IA solo decide si las reglas dejan la ficha pendiente.
        combined = ai_cat if (ai and rules == 'pendiente' and ai[1] >= ai_assist.APPLY_CATEGORY and ai_cat != 'pendiente') else rule_cat
        score['combinada'] += combined == label
        if is_weak:
            weak['n'] += 1; weak['reglas'] += rule_cat == label; weak['ia'] += ai_cat == label; weak['combinada'] += combined == label
        if ai_cat != label: misses.append((item['title'][:70], label, ai))
    pct = lambda c, k: f"{c[k]}/{c['n']} = {100 * c[k] / max(1, c['n']):.1f} %"
    print('Todas:      reglas', pct(score, 'reglas'), '| IA', pct(score, 'ia'), '| combinada', pct(score, 'combinada'))
    print('Casos débiles (donde actúa la IA):  reglas', pct(weak, 'reglas'), '| IA', pct(weak, 'ia'), '| combinada', pct(weak, 'combinada'))
    print('Fichas sin respuesta de la IA (cuentan como fallo):', usage.pop('sin_respuesta', 0), '· fin de respuesta:', usage.pop('stop_reasons', {}))
    print('Tokens:', usage)
    for m in misses[:40]: print('  ✗', m)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'reports' / 'loagendo_v12.sqlite3'))
