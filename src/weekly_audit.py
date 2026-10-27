"""Auditoría semanal con Claude (piloto 26-10-2026 → 16-11-2026, decisión de David).

Reutiliza lo que ya existe: la muestra de scripts/muestra_revision_llm.py (mismas columnas), el prompt del auditor
(docs/revision/prompt-revisor.md), la llamada a la API de src/ai_assist.py y el correo de src/mailer.py. No escribe
nada en las fichas: solo deja el informe en reports/auditorias/AAAA-MM-DD.(md|json), lo manda por correo y el parte
diario muestra sus errores graves durante 7 días.

Muestra de 80 fichas publicables de los próximos 60 días: la mitad al azar repartida por fuente y categoría, una
cuarta parte entre las que han entrado en los últimos 7 días y otra cuarta entre las sospechosas (sin descripción, sin
hora, sin precio, categoría de recinto o decidida por IA, ticketeras y agregadores). Semilla: la fecha.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT = ROOT / 'docs' / 'revision' / 'prompt-revisor.md'
OUT_DIR = ROOT / 'reports' / 'auditorias'
FIRST_SEEN = ROOT / 'data' / 'first_seen.json'
MODEL = 'claude-sonnet-5-5'
PREVIOUS_REPEAT = 25   # errores graves de la auditoría anterior que se vuelven a revisar
SIZE = 80
SOURCE_CAP = 8           # como mucho 8 fichas de una misma fuente (GuiaBCN y Open Data dominan el catálogo)
AHEAD_DAYS = 60
RISKY_SOURCES = {'guiabcn', 'venue_eventbrite', 'venue_dice', 'venue_songkick', 'venue_xceed', 'venue_ticketmaster_es', 'generalitat', 'web_conciertos_club'}
SUSPECT_METHODS = {'categoria_recinto', 'ia', 'ia_con_senal', 'sin_senal'}


def cut(s, n):
    s = ' '.join(str(s or '').split())
    return s if len(s) <= n else s[:n - 1] + '…'


def row(d):
    """Una ficha como la ve el auditor (las mismas columnas que describe el prompt)."""
    from src.taxonomy import CATEGORIES
    occ = [f"{o['date']} {o.get('time') or ''}".strip() for o in d.get('occurrences') or []]
    return {
        'ficha': f"https://ontoca.com/e/{d['source']}/{d['id']}",
        'titulo': d.get('title'),
        'fuente': d.get('source_label') or d['source'],
        'url_fuente': next((l['url'] for l in d.get('links') or [] if l.get('url')), d.get('url') or ''),
        'fechas': f"{d.get('start')} → {d.get('end')}",
        'tipo': d.get('kind_label') or d.get('kind'),
        'sesiones': occ[:8] + (['…'] if len(occ) > 8 else []),
        'hora_ficha': d.get('time') or d.get('time_label') or '',
        'horario_por_dia': dict(list((d.get('hours_by_day') or {}).items())[:4]),
        'texto_horario_fuente': cut(d.get('time_text'), 160),
        'categoria_ontoca': CATEGORIES.get(d.get('public_category'), (d.get('public_category'),))[0],
        'categoria_fuente': d.get('category') or '',
        'canales': d.get('channels') or [],
        'publico_familiar': bool(d.get('family_audience')),
        'lugar': ' · '.join((d.get('venue_names') or [])[:2]),
        'distrito': d.get('district') or '',
        'organiza': ', '.join(d.get('organizers') or []),
        'precio': d.get('price_label') or ('Gratis' if d.get('is_free') else '') or cut(d.get('price_text'), 80),
        'inscripcion': bool(d.get('registration_required')),
        'descripcion': cut(d.get('description') or d.get('summary'), 450),
        'origen_descripcion': str(d.get('description_credit') or ('fuente' if d.get('description') else '')),
        'tiene_imagen': bool(d.get('media')),
    }


def _pool(conn, today):
    """[(source, id, category, method)] publicables de los próximos 60 días que no son la copia de otra ficha."""
    from src.dedupe import canonical_groups
    groups = canonical_groups(conn)
    ahead = (today + dt.timedelta(days=AHEAD_DAYS)).isoformat()
    rows = conn.execute("""SELECT r.source, r.id, e.category, e.method FROM source_records r JOIN event_classification e ON e.source=r.source AND e.id=r.id
        WHERE r.eligibility<>'exclude' AND e.category NOT IN ('excluida','pendiente')
          AND substr(COALESCE(NULLIF(r.end_date,''),r.start_date),1,10)>=? AND substr(r.start_date,1,10)<=?""", (today.isoformat(), ahead)).fetchall()
    return [r for r in rows if f'{r[0]}:{r[1]}' not in groups]


def _recent(today, path=FIRST_SEEN):
    try: seen = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError): return set()
    since = (today - dt.timedelta(days=7)).isoformat()
    return {k for k, v in seen.items() if isinstance(v, str) and v[:10] >= since}


def sample(conn, today=None, size=SIZE, seed=None, repeat=()):
    """(filas para el auditor, composición). Fichas leídas con el motor (catalog.row_to_event + borrow_from_twins)."""
    from mvp import catalog
    today = today or dt.date.today()
    rnd = random.Random(seed or today.isoformat())
    pool = _pool(conn, today)
    rnd.shuffle(pool)
    recent = _recent(today)
    picked, seen, used, cats = [], set(), {}, {}
    # Fichas de una auditoría anterior que se vuelven a revisar tal como están hoy (27-10-2026, David): van
    # primero y no cuentan en el tamaño; las nuevas se eligen sin repetirlas.
    for k in repeat:
        s_, _, i_ = k.partition(':')
        if s_ and i_ and k not in seen: seen.add(k); picked.append(((s_, i_, None, None), 'repetida'))
    size_total = size + len(picked)
    def take(cands, n, why, cap=SOURCE_CAP, cat_cap=size // 4):
        for r in cands:
            if n <= 0: break
            k = f'{r[0]}:{r[1]}'
            # ninguna fuente ni categoría se come la muestra
            if k in seen or used.get(r[0], 0) >= cap or cats.get(r[2], 0) >= cat_cap: continue
            seen.add(k); picked.append((r, why)); n -= 1; used[r[0]] = used.get(r[0], 0) + 1; cats[r[2]] = cats.get(r[2], 0) + 1
    # 1) mitad al azar, repartida por fuente y categoría: como mucho 2 por pareja (fuente, categoría) y 4 por fuente
    per_pair, per_source, strat = {}, {}, []
    for r in pool:
        pair = (r[0], r[2])
        if per_pair.get(pair, 0) >= 2 or per_source.get(r[0], 0) >= 4: continue
        per_pair[pair] = per_pair.get(pair, 0) + 1; per_source[r[0]] = per_source.get(r[0], 0) + 1; strat.append(r)
    take(strat, size // 2, 'azar')
    # 2) recientes (últimos 7 días)
    take([r for r in pool if f'{r[0]}:{r[1]}' in recent], size // 4, 'reciente')
    # 3) sospechosas por cómo se decidieron o de dónde vienen
    take([r for r in pool if r[3] in SUSPECT_METHODS or r[0] in RISKY_SOURCES], size_total - len(picked), 'sospechosa')
    take(pool, size_total - len(picked), 'azar', cap=size, cat_cap=size)
    Q = '''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,r.evidence_level,r.source_url,r.raw_json,e.status,e.note,e.updated_at
           FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id WHERE r.source=? AND r.id=?'''
    rows, comp = [], {}
    for (s, i, _, _), why in picked:
        try:
            d = catalog.borrow_from_twins(conn, catalog.row_to_event(conn, conn.execute(Q, (s, i)).fetchone(), True, ''))
        except Exception:
            continue
        if d.get('public_category') in ('excluida', 'pendiente') or d.get('superseded_by'): continue   # ya no se publica
        r_ = row(d)
        if repeat: r_['muestra'] = why
        rows.append(r_); comp[why] = comp.get(why, 0) + 1
    return rows, comp


def _previous_note(name, prev):
    """Lo que el auditor necesita de la auditoría anterior para compararla con esta."""
    prev = prev or {}
    lines = ['', '', 'Auditoría anterior (%s). Patrones que encontró:' % (name or '?')]
    lines += ['- %s' % p.get('title', '') for p in prev.get('patterns') or []]
    if prev.get('serious'):
        lines.append('Errores graves que señaló (las fichas con "muestra": "repetida" son esas, leídas tal como están hoy):')
        lines += ['- %s | %s: %s' % (x.get('url', ''), x.get('type', ''), x.get('problem', '')) for x in prev['serious']]
    lines.append('Al final del informe añade «## Comparación con la auditoría anterior» con tres listas cortas: «Resuelto» (lo que ya no '
                 'aparece, con la ficha que lo prueba), «Sigue» y «Nuevo». Solo lo que puedas comprobar con estas fichas; lo demás, «sin datos».')
    return '\n'.join(lines)


def _prompt():
    text = PROMPT.read_text(encoding='utf-8')
    return text.split('\n---\n', 1)[1].strip() if '\n---\n' in text else text


def parse(report):
    """Patrones (## P<n>. título) e incidencias graves (líneas «URL | TIPO: problema | propuesta») del informe."""
    patterns = [{'title': m.group(1).strip()} for m in re.finditer(r'^##\s*P\d+\.\s*(.+)$', report, re.M)]
    top = re.search(r'(?is)las tres mejoras prioritarias(.*?)(?:^#{1,3}\s*3\.|incidencias individuales)', report, re.M)
    serious = []
    for m in re.finditer(r'^\s*(https://ontoca\.com/e/([^/\s]+)/(\S+?))\s*\|\s*([A-Z]+):\s*([^|]+)\|\s*(.+)$', report, re.M):
        cert = re.search(r'certeza:\s*(confirmado|sospecha|dato ausente)', m.group(6), re.I)
        serious.append({'url': m.group(1), 'key': f'{m.group(2)}:{m.group(3)}', 'type': m.group(4), 'problem': m.group(5).strip(), 'proposal': m.group(6).strip(), 'title': '',
                        'certainty': (cert.group(1).lower() if cert else 'sospecha')})
    return patterns, (top.group(1).strip() if top else ''), serious


def comparison(report):
    """La sección «Comparación con la auditoría anterior» del informe (texto), si la hay."""
    m = re.search(r'(?ims)^#{1,3}\s*\d*\.?\s*comparaci[oó]n con la auditor[ií]a anterior\s*$(.*?)(?=^#{1,3}\s|\Z)', report)
    return m.group(1).strip() if m else ''


def previous(out_dir, today):
    """(nombre, resumen) de la última auditoría anterior a hoy (reports/auditorias/*.json), o (None, None)."""
    for f in sorted(Path(out_dir).glob('*.json'), reverse=True):
        if f.stem[:10] >= today.isoformat(): continue
        try: return f.stem, json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError): continue
    return None, None


def run(conn, job=None, today=None, requester=None, send=None, out_dir=OUT_DIR):
    from src import ai_assist
    job = job or {}
    today = today or dt.date.today()
    key = ai_assist.load_key()
    if not key: return {'status': 'skipped', 'reason': 'Falta ANTHROPIC_API_KEY en .env'}
    repeat = []
    if job.get('repeat'):
        # «repeat»: informe anterior (AAAA-MM-DD[...]) cuyas fichas se vuelven a auditar además de las nuevas.
        prev = Path(out_dir) / f"{job['repeat']}.jsonl"
        for line in prev.read_text(encoding='utf-8').splitlines():
            m = re.match(r'https://ontoca\.com/e/([^/]+)/(.+)$', json.loads(line).get('ficha', ''))
            if m: repeat.append(f'{m.group(1)}:{m.group(2)}')
    # Comparación automática con la auditoría anterior (27-10-2026, David): sus errores graves se vuelven a revisar
    # tal como están hoy y el informe dice qué se ha resuelto, qué sigue y qué es nuevo.
    prev_name, prev = previous(out_dir, today)
    if prev and not repeat:
        repeat = [x['key'] for x in prev.get('serious') or [] if x.get('key')][:PREVIOUS_REPEAT]
    rows, comp = sample(conn, today, job.get('size', SIZE), repeat=repeat)
    if not rows: return {'status': 'failed', 'error': 'Muestra vacía'}
    # Sin razonamiento extendido: con él, el 26-10 los 8.000 tokens se fueron en pensar y el informe salió vacío.
    # Sin razonamiento previo (27-10-2026): Sonnet 5.5 no admite «disabled» ni «enabled» con presupuesto; su forma de
    # no pensar antes de escribir es «between_tools» (sin herramientas, no piensa), con esfuerzo medio. Con razonamiento
    # adaptativo, la auditoría de 159 fichas gastó los 24.000 tokens en pensar y el informe salió vacío.
    body = {'model': job.get('model', MODEL), 'max_tokens': job.get('max_tokens', 16000), 'thinking': {'type': 'between_tools'},
            'output_config': {'effort': job.get('effort', 'medium')}, 'system': _prompt(),
            'messages': [{'role': 'user', 'content': 'Muestra de %d fichas publicadas (%s), una línea JSON por ficha:\n\n%s%s' % (
                len(rows), ', '.join('%d %s' % (n, k) for k, n in comp.items()), '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows),
                _previous_note(job.get('repeat') or prev_name, prev) if repeat or prev else '')}]}
    import urllib.error
    call = requester or ai_assist._request
    try:
        message = call('POST', f'{ai_assist.API}/messages', key, body, timeout=600)
    except urllib.error.HTTPError as error:
        detail = error.read().decode('utf-8', 'replace')[:400] if hasattr(error, 'read') else ''
        if error.code != 400 or 'thinking' not in body: return {'status': 'failed', 'error': f'HTTP {error.code}: {detail}'}
        # El modelo no admite ese modo: razonamiento adaptativo con esfuerzo bajo y margen de sobra para pensar y escribir.
        body.pop('thinking'); body['output_config'] = {'effort': 'low'}; body['max_tokens'] = max(body['max_tokens'], 32000)
        try: message = call('POST', f'{ai_assist.API}/messages', key, body, timeout=600)
        except urllib.error.HTTPError as again:
            return {'status': 'failed', 'error': f'HTTP {again.code}: ' + (again.read().decode('utf-8', 'replace')[:400] if hasattr(again, 'read') else '') + f' (antes: {detail[:200]})'}
    report = ''.join(b.get('text', '') for b in message.get('content') or [] if b.get('type') == 'text')
    if not report.strip():
        return {'status': 'failed', 'error': 'Informe vacío (stop_reason %s; bloques %s)' % (message.get('stop_reason'), [b.get('type') for b in message.get('content') or []]),
                'usage': message.get('usage')}
    patterns, top, serious = parse(report)
    titles = {r['ficha']: r['titulo'] for r in rows}
    for s in serious: s['title'] = titles.get(s['url'], s['key'])
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    stem = today.isoformat() + (job.get('suffix') or '')
    (out / f'{stem}.md').write_text(report, encoding='utf-8')
    (out / f'{stem}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    usage = message.get('usage') or {}
    summary = {'day': today.isoformat(), 'file': stem, 'model': body['model'], 'sample_size': len(rows), 'composition': comp, 'patterns': patterns, 'serious': serious,
               'usage': {k: v for k, v in usage.items() if isinstance(v, int)}, 'stop_reason': message.get('stop_reason'),
               'previous': prev_name, 'comparison': comparison(report), 'top': top}
    (out / f'{stem}.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    mail = {'status': 'skipped', 'reason': 'send=false'}
    if job.get('send', True):
        subject, html_body, text = render(summary, report)
        if send is None:
            from src.mailer import send
        mail = send(subject, html_body, text, job.get('to') or 'hola@ontoca.com')
    return {'status': 'completed', 'file': str(out / f'{stem}.md'), 'patterns': len(patterns), 'serious': len(serious), 'usage': summary['usage'], 'email': mail}


def render(summary, report):
    """(asunto, html, texto) del correo: corto (27-10-2026, David). Errores graves verificados y sospechas por
    separado, las tres mejoras prioritarias y la comparación con la auditoría anterior. El informe completo (todos
    los patrones) se queda en reports/auditorias/ y no va en el correo."""
    import html
    esc = lambda v: html.escape(str(v or ''))
    day = dt.date.fromisoformat(summary['day'])
    serious = summary['serious']
    verified = [x for x in serious if x.get('certainty') == 'confirmado']
    suspected = [x for x in serious if x.get('certainty') != 'confirmado']
    subject = 'Ontoca · auditoría %s · %s' % (day.strftime('%d-%m'), ('%d errores verificados, %d sospechas' % (len(verified), len(suspected))) if serious else 'sin errores graves')
    u = summary.get('usage') or {}
    file = summary.get('file') or summary['day']
    item = lambda x: '<li><a href="%s">%s</a> · <b>%s</b>: %s<br><span style="color:#555">%s</span></li>' % (esc(x['url']), esc(x['title']), esc(x['type']), esc(x['problem']), esc(x['proposal']))
    block = lambda title, text: '<h2 style="font-size:15px;margin:16px 0 6px">%s</h2><div style="white-space:pre-wrap;font-size:13px">%s</div>' % (title, esc(text))
    parts = ['<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;color:#222;max-width:720px">',
             '<p style="font-size:18px;margin:0 0 4px">Auditoría del %s</p>' % day.strftime('%d-%m-%Y'),
             '<p style="color:#666;margin:0 0 12px">%d fichas (%s) · %d patrones · %s · %s tokens</p>' % (
                 summary['sample_size'], esc(', '.join('%d %s' % (n, k) for k, n in summary['composition'].items())), len(summary['patterns']),
                 esc(summary['model']), f"{u.get('input_tokens', 0) + u.get('output_tokens', 0):,}".replace(',', '.'))]
    if verified: parts.append('<h2 style="font-size:15px;margin:16px 0 6px;color:#b42318">Errores graves verificados</h2><ul style="padding-left:18px">%s</ul>' % ''.join(map(item, verified)))
    if suspected: parts.append('<h2 style="font-size:15px;margin:16px 0 6px">Sospechas (comprobar en la fuente)</h2><ul style="padding-left:18px">%s</ul>' % ''.join(map(item, suspected)))
    if summary.get('top'): parts.append(block('Tres mejoras prioritarias', summary['top']))
    elif summary['patterns']: parts.append('<h2 style="font-size:15px;margin:16px 0 6px">Patrones principales</h2><ol>%s</ol>' % ''.join('<li>%s</li>' % esc(p['title']) for p in summary['patterns'][:3]))
    if summary.get('comparison'): parts.append(block('Comparación con la auditoría anterior (%s)' % esc(summary.get('previous') or ''), summary['comparison']))
    parts.append('<p style="color:#999;font-size:12px">Informe completo: reports/auditorias/%s.md. Nada se cambia en las fichas: es solo el informe.</p></div>' % esc(file))
    line = lambda x: '- %s · %s: %s (%s)' % (x['title'], x['type'], x['problem'], x['url'])
    text = '\n'.join([subject, ''] + (['Errores graves verificados:'] + [line(x) for x in verified] + [''] if verified else [])
                     + (['Sospechas:'] + [line(x) for x in suspected] + [''] if suspected else [])
                     + (['Tres mejoras prioritarias:', summary['top'], ''] if summary.get('top') else [])
                     + (['Comparación con la auditoría anterior:', summary['comparison'], ''] if summary.get('comparison') else [])
                     + ['Informe completo: reports/auditorias/%s.md' % file])
    return subject, ''.join(parts), text
