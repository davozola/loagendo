#!/usr/bin/env python3
"""Diagnóstico compacto de fichas para la revisión de contenido.

Uso:
  python3 scripts/revisar_fichas.py                 # lee docs/revision/pendientes.txt
  python3 scripts/revisar_fichas.py URL|source:id ...  # fichas sueltas

Solo lectura (abre la base en modo ro, consultas por clave primaria).
Escribe también docs/revision/diagnostico.txt.
"""
import json, re, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'
PEND = ROOT / 'docs' / 'revision' / 'pendientes.txt'
OUT = ROOT / 'docs' / 'revision' / 'diagnostico.txt'
MAX = 160


def cut(v, n=MAX):
    s = ' '.join(str(v).split()) if v is not None else ''
    return s if len(s) <= n else s[:n - 1] + '…'


def parse_ref(ref):
    ref = ref.strip()
    m = re.search(r'/e/([^/\s]+)/([^/\s?#]+)', ref)
    if m:
        return m.group(1), m.group(2)
    if ':' in ref and not ref.startswith('http'):
        s, i = ref.split(':', 1)
        return s.strip(), i.strip()
    return None


def read_cases(args):
    if args:
        return [(a, '', '') for a in args]
    cases = []
    for line in PEND.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = [p.strip() for p in line.split('|')] + ['', '']
        cases.append((parts[0], parts[1], parts[2]))
    return cases


def one(c, q, *a):
    try:
        return c.execute(q, a).fetchone()
    except sqlite3.Error as e:
        return ('ERR', str(e))


def many(c, q, *a):
    try:
        return c.execute(q, a).fetchall()
    except sqlite3.Error as e:
        return [('ERR', str(e))]


def diagnose(c, s, i):
    L = []
    r = one(c, 'select title,start_date,end_date,kind,eligibility,evidence_level,source_url from source_records where source=? and id=?', s, i)
    if not r:
        return ['  NO ENCONTRADA en source_records']
    t, sd, ed, kind, elig, evl, url = r
    L.append(f'  título: {cut(t)}')
    L.append(f'  fechas: {sd} → {ed} · kind={kind} · elig={elig} · evid={evl}')
    L.append(f'  origen: {cut(url, 200)}')
    v = many(c, 'select venue,address from source_venues where source=? and id=? order by seq', s, i)
    if v:
        L.append('  lugar: ' + ' ; '.join(cut(f'{a} ({b})', 90) for a, b in v[:3]))
    o = many(c, 'select name from source_organizers where source=? and id=? order by seq', s, i)
    if o:
        L.append('  organiza: ' + cut(', '.join(x[0] for x in o if x[0]), 120))
    ec = one(c, 'select category,status,method,evidence,ambiguous,channels from event_classification where source=? and id=?', s, i)
    if ec:
        L.append(f'  clasif: {ec[0]} [{ec[1]}] método={ec[2]} amb={ec[4]} canales={ec[5]}')
        L.append(f'          evidencia: {cut(ec[3], 140)}')
    ov = one(c, 'select category,channels_add,channels_remove,note,updated_at from classification_overrides where source=? and id=?', s, i)
    if ov:
        L.append(f'  OVERRIDE: cat={ov[0]} +{ov[1]} -{ov[2]} nota={cut(ov[3], 80)} ({ov[4]})')
    pd = one(c, 'select status,note,decided_at from publication_decisions where source=? and id=?', s, i)
    if pd:
        L.append(f'  publicación: {pd[0]} {cut(pd[1], 80)} ({pd[2]})')
    er = one(c, 'select status,note from editorial_reviews where source=? and id=?', s, i)
    if er:
        L.append(f'  revisión: {er[0]} {cut(er[1], 80)}')
    fl = many(c, 'select issue from review_flags where source=? and id=?', s, i)
    if fl:
        L.append('  flags: ' + ', '.join(x[0] for x in fl))
    fv = many(c, 'select field_name,value_json from field_verifications where source=? and id=?', s, i)
    for f, val in fv:
        L.append(f'  verificado {f}: {cut(val, 80)}')
    pj = one(c, 'select projection_json from listing_projections where source=? and id=?', s, i)
    if pj and pj[0] != 'ERR':
        p = json.loads(pj[0])
        L.append(f"  proyección (no es la ficha publicada): cat={p.get('category')} desc={'sí' if p.get('has_description') else 'NO'} "
                 f"hora={cut(p.get('hours_label') or p.get('schedule_text_time') or '—', 40)} "
                 f"precio={cut(p.get('price_label') or ('gratis' if p.get('is_free') else '—'), 40)} "
                 f"idiomas={p.get('languages') or '—'} familia={p.get('family_audience')}")
        if p.get('summary'):
            L.append(f"  resumen: {cut(p.get('summary'), 140)}")
    item = f'{s}:{i}'
    for task, ans, conf, reason in many(c, 'select task,answer,confidence,reason from ai_suggestions where item=? and task in ("categoria","familia","duplicado","datos")', item):
        L.append(f'  IA {task}: {cut(ans, 60)} ({conf:.2f}) {cut(reason, 80)}')
    op = one(c, 'select status,price,url from official_pages where source=? and id=?', s, i)
    if op:
        L.append(f'  web oficial: {op[0]} precio={cut(op[1], 30)} {cut(op[2], 90)}')
    dup = one(c, 'select count(*) from match_candidates where a=? or b=?', item, item)
    if dup and dup[0]:
        L.append(f'  posibles duplicados: {dup[0]}')
    return L


def main():
    cases = read_cases(sys.argv[1:])
    c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
    out = []
    for n, (ref, prob, dato) in enumerate(cases, 1):
        key = parse_ref(ref)
        out.append(f'#{n} {ref}')
        if prob:
            out.append(f'  PROBLEMA: {prob}' + (f' · DATO: {dato}' if dato else ''))
        out += diagnose(c, *key) if key else ['  referencia no reconocida']
        out.append('')
    text = '\n'.join(out)
    print(text)
    if not sys.argv[1:]:
        OUT.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
