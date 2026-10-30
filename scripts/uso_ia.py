"""Dónde se gastan los tokens de la IA (30-10-2026, David). Lee reports/ia_uso.jsonl (una línea por llamada o lote,
escrita por src/ai_assist.py) y resume por tarea, por día y, con --detalle, por lo que se pidió (día y alcance de la
Selección, sala de la agenda, festival…).

Uso: python3 scripts/uso_ia.py [días, 7 por defecto] [--detalle TAREA]
"""
import collections
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / 'reports' / 'ia_uso.jsonl'
args = [a for a in sys.argv[1:] if not a.startswith('--')]
days = int(args[0]) if args else 7
detail = sys.argv[sys.argv.index('--detalle') + 1] if '--detalle' in sys.argv else ''
since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
KEYS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
rows = []
try:
    for line in LOG.read_text(encoding='utf-8').splitlines():
        try: r = json.loads(line)
        except ValueError: continue
        if r.get('at', '') >= since: rows.append(r)
except OSError: sys.exit(f'Aún no hay registro de uso ({LOG}).')
tot = lambda rs, k: sum(int(r.get(k) or 0) for r in rs)
web = lambda rs: sum(int((r.get('server_tool_use') or {}).get('web_search_requests') or 0) for r in rs)
fmt = lambda n: f'{n:,}'.replace(',', '.')


def table(groups, title):
    print(f'\n{title}')
    print(f"{'':38} {'llamadas':>8} {'entrada':>12} {'salida':>10} {'caché leída':>12} {'caché escrita':>13} {'búsq. web':>9}")
    for name, rs in sorted(groups.items(), key=lambda kv: -(tot(kv[1], 'input_tokens') + 5 * tot(kv[1], 'output_tokens'))):
        print(f"{str(name)[:38]:38} {len(rs):>8} {fmt(tot(rs, KEYS[0])):>12} {fmt(tot(rs, KEYS[1])):>10} {fmt(tot(rs, KEYS[2])):>12} {fmt(tot(rs, KEYS[3])):>13} {web(rs):>9}")


print(f'Uso de la IA en los últimos {days} días ({len(rows)} llamadas o lotes desde {since[:10]})')
by = collections.defaultdict(list)
for r in rows: by[r.get('tarea') or '?'].append(r)
table(by, 'Por tarea (ordenado por peso: entrada + 5 × salida)')
byday = collections.defaultdict(list)
for r in rows: byday[r['at'][:10]].append(r)
table(dict(sorted(byday.items())), 'Por día')
if detail:
    sub = collections.defaultdict(list)
    for r in rows:
        if r.get('tarea') == detail: sub[r.get('detalle') or '—'].append(r)
    table(sub, f'Detalle de «{detail}»')
