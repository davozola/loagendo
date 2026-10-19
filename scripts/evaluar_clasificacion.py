"""Precisión de la clasificación pública contra la muestra etiquetada (tests/fixtures/clasificacion_muestra_200.json).

Uso: python3 scripts/evaluar_clasificacion.py [ruta.sqlite3]
Reclasifica cada ficha de la muestra con las reglas actuales y la compara con su etiqueta.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp import catalog  # noqa: E402


def evaluate(conn, sample):
    per = defaultdict(Counter); misses = []
    for item in sample['items']:
        e = catalog.event_detail(conn, item['source'], item['id'])
        if e is None: per['(desaparecida)']['n'] += 1; continue
        got = e['public_category']
        if item['doubtful']: per[got]['dudosas'] += 1; continue
        per[got]['n'] += 1
        if got == item['label']: per[got]['ok'] += 1
        else: misses.append((item['title'], got, item['label'], item['note']))
    n = sum(c['n'] for k, c in per.items() if k != '(desaparecida)'); ok = sum(c['ok'] for c in per.values())
    return {'n': n, 'ok': ok, 'precision': round(100 * ok / n, 1) if n else None,
            'by_category': {k: dict(v) for k, v in sorted(per.items())}, 'misses': misses}


if __name__ == '__main__':
    db = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / 'reports' / 'loagendo_v12.sqlite3')
    sample = json.loads((ROOT / 'tests' / 'fixtures' / 'clasificacion_muestra_200.json').read_text())
    conn = catalog.connect(Path(db))
    for name, part in (('Muestra aleatoria (200)', sample), ('Muestra por categoría (6 × 20)', sample.get('stratified', {'items': []}))):
        out = evaluate(conn, part)
        print(f"{name} — precisión estricta: {out['ok']}/{out['n']} = {out['precision']} %")
        for k, v in out['by_category'].items(): print(f"  {k:12} {v}")
        for m in out['misses']: print('  ✗', m)
