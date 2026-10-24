"""Lista de revisión de la limpieza de títulos (src/titles.py): fuente → se muestra, por regla.

Uso (en el Mac, sobre una copia de la base, nunca la base en vivo desde la máquina virtual):
    python3 scripts/muestra_titulos.py [ruta_de_la_base] → reports/titulos_normalizados_<fecha>.md
"""
import collections
import datetime as dt
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.titles import display_title  # noqa: E402

GENERIC = re.compile(r'(?i)^(concert|concierto|espectacle|espectáculo)\s')


def rule_of(t, d):
    letters = [ch for ch in t if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) / len(letters) >= 0.9: return '5 · Todo en mayúsculas'
    if GENERIC.match(t) and not GENERIC.match(d): return '4 · Prefijo genérico (la categoría ya lo dice)'
    if '*' in t: return '3 · Marcas «*NOU*», «*Ajornat»…'
    if d.count('"') != t.count('"') or t.count('«') != t.count('»') or "''" in t: return '2 · Comillas'
    return '1 · Espacios'


def main(db=ROOT / 'reports' / 'loagendo_v12.sqlite3'):
    today = dt.date.today()
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    rows = conn.execute("""SELECT r.title, c.category FROM source_records r JOIN event_classification c ON c.source=r.source AND c.id=r.id
        WHERE r.end_date>=? AND r.start_date<=? AND r.eligibility<>'exclude' AND c.status NOT IN ('pendiente','excluida') AND r.source<>'guiabcn'""",
                        (today.isoformat(), (today + dt.timedelta(days=183)).isoformat())).fetchall()
    groups = collections.defaultdict(set)
    for t, cat in rows:
        d = display_title(t, cat)
        if d != t: groups[rule_of(t, d)].add((t, d))
    out = [f'# Títulos normalizados · revisión ({today.strftime("%d-%m-%Y")})', '',
           'Fichas vivas en los próximos 6 meses, sin GuiaBCN. Solo cambia el título que se muestra; el de la fuente se conserva en `source_title` (src/titles.py).', '',
           'A mirar: en mayúsculas se usa «Cada Palabra Con Mayúscula» (no se pierde ningún nombre propio, pero en catalán y castellano queda menos natural que la frase normal); las siglas conocidas o sin vocales se quedan («DJ», «BCN»).', '']
    for k in sorted(groups):
        out += [f'## {k} ({len(groups[k])})', '', '| Fuente | Se muestra |', '|---|---|']
        out += [f'| {t.replace("|", "/")} | {d.replace("|", "/")} |' for t, d in sorted(groups[k])] + ['']
    path = ROOT / 'reports' / f'titulos_normalizados_{today.isoformat()}.md'
    path.write_text('\n'.join(out), encoding='utf-8')
    print(path, {k: len(v) for k, v in sorted(groups.items())})


if __name__ == '__main__':
    main(*(sys.argv[1:2] or []))
