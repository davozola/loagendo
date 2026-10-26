#!/usr/bin/env python3
"""Muestra de fichas para el auditor (prompt: docs/revision/prompt-revisor.md), la misma que usa la auditoría
semanal (src/weekly_audit.py): mitad al azar por fuente y categoría, un cuarto recientes y un cuarto sospechosas.

Uso: python3 scripts/muestra_revision_llm.py [N=80] [semilla=fecha de hoy]
Solo lectura. Escribe docs/revision/muestra-AAAA-MM-DD.jsonl.
"""
import datetime as dt, json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.weekly_audit import sample  # noqa: E402

n = int(sys.argv[1]) if len(sys.argv) > 1 else 80
conn = sqlite3.connect(f"file:{ROOT / 'reports' / 'loagendo_v12.sqlite3'}?mode=ro", uri=True)
rows, comp = sample(conn, size=n, seed=sys.argv[2] if len(sys.argv) > 2 else None)
out = ROOT / 'docs' / 'revision' / f'muestra-{dt.date.today().isoformat()}.jsonl'
out.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
print(f'{len(rows)} fichas ({comp}) → {out.relative_to(ROOT)}')
