"""Prueba (2-11-2026): estructura de fichas largas con IA, sin tocar la base.

Casos difíciles: una ficha de varios días que en realidad es una exposición o instalación
(«By the stream», clasificada como espectáculo) y que además anuncia actos con fecha y hora
dentro del texto (performance, taller, inauguración, visita guiada). El extractor actual
(ai_extract) solo pregunta por fichas de 4 días o menos, así que esos actos no salen nunca.

Qué hace: lee las fichas publicadas en dist/data/detail (no abre la base en vivo), elige hasta
30 candidatas por reglas, pide a Haiku formato, categoría y sesiones, cada dato con cita literal,
y lo comprueba sin IA con las mismas funciones que ai_extract (la cita está en el texto; la
fecha y la hora se leen en la cita; la fecha cae dentro de la ficha). No escribe en la base:
deja un informe en reports/prueba_estructura_ia.md y las respuestas en bruto en
reports/prueba_estructura_ia_raw.json (con --replay se recomprueban sin llamar a la API).

Uso en el Mac:  python3 scripts/prueba_estructura_ia.py          (≈30 fichas, céntimos; Haiku)
                python3 scripts/prueba_estructura_ia.py --model claude-sonnet-5-5
                python3 scripts/prueba_estructura_ia.py --replay (solo recomprueba)
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import re
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import ai_assist  # noqa: E402
from src.ai_extract import fold, quote_in, day_ok, time_ok  # noqa: E402

PROMPT_VERSION = 2   # 2 (2-11-2026): el título manda sobre el formato; recital y lectura; títulos sin fecha; reglas de aplicación
RAW_V1 = ROOT / 'reports' / 'prueba_estructura_ia_raw.json'
FORMATS = ['exhibition', 'program', 'one_shot', 'workshop', 'course', 'festival', 'ongoing']
CATEGORIES = ['musica', 'escena', 'cine', 'arte', 'visitas', 'charlas', 'talleres', 'fiestas']
SESSION_TYPES = ['inauguracion', 'performance', 'taller', 'charla', 'visita', 'concierto', 'proyeccion', 'espectaculo', 'presentacion', 'recital', 'lectura', 'clausura', 'otro']
TYPE_LABEL = {'inauguracion': 'Inauguració', 'performance': 'Performance', 'taller': 'Taller', 'charla': 'Xerrada', 'visita': 'Visita guiada',
              'concierto': 'Concert', 'proyeccion': 'Projecció', 'espectaculo': 'Espectacle', 'presentacion': 'Presentació', 'recital': 'Recital',
              'lectura': 'Lectura', 'clausura': 'Cloenda', 'otro': 'Activitat'}
# Títulos de ficha que nombran la actividad: la ficha ES esa actividad aunque pase en una exposición.
ACTIVITY_TITLE_RX = re.compile(r"^\W*(visita|visites|itinerari|itinerario|ruta|taller|tallers|curs|cursos|curso|presentacio|presentacion|xerrada|charla|conferencia|cicle|ciclo|concert|concierto|espectacle|projeccio)\b")


EXPO_RX = re.compile(r"\b(instal[.·l]*acio|instalacion|exposicio|exposicion|mostra|muestra)\b")
SESS_RX = re.compile(r"\b(performance|inauguracio|inauguracion|taller|xerrada|charla|conferencia|visita (guiada|comentada)|concert|concierto|presentacio|presentacion|taula rodona|mesa redonda|espectacle|projeccio|recital|clausura|cloenda)\b")
HOUR_RX = re.compile(r"\b([01]?\d|2[0-3])([:.]\d{2})?\s*h\b|\b([01]?\d|2[0-3]):\d{2}\b|\ba (les|las) \d")

SYSTEM = """Ordenas fichas de actividades culturales de Barcelona que duran varios días. Recibes título, fechas (inicio y fin), sala, el formato y la categoría que tiene ahora y el texto de la fuente.
Devuelve, para cada ficha (n):
- formato: qué es la ficha en su conjunto, uno de exhibition (exposición o instalación que se puede visitar en horario de sala), program (ciclo o temporada de sesiones, visitas que se repiten), one_shot (acto o función), workshop (taller), course (curso de varias sesiones), festival (muestra o festival con varias compañías o artistas), ongoing (actividad continuada). Con cita literal del texto que lo justifica.
  · REGLA 1: si el título nombra una actividad (Visita, Visites guiades, Itinerari, Taller, Curs, Presentació, Xerrada, Cicle, Concert…), la ficha ES esa actividad aunque se haga dentro de una exposición: «Visites guiades a l'exposició X» es program/visitas, no exhibition/arte.
  · REGLA 2: si el texto dice que hay una instal·lació o exposició visitable durante un periodo («Instal·lació: del 22 d'octubre al 10 de novembre», «es pot visitar fins al…»), la ficha es exhibition aunque además tenga una performance o un taller: confianza alta, y cita esa frase.
  · Si dudas entre el formato actual y otro, deja el actual.
- categoria: una de musica, escena (teatro, danza, circo), cine, arte (exposiciones y arte), visitas, charlas (charlas, presentaciones, libros y lectura), talleres (talleres y cursos), fiestas. Es la de la ficha en su conjunto: una exposición es arte aunque incluya una performance; un curso es talleres aunque trate de literatura. Si dudas, deja la actual.
- sesiones: SOLO los actos sueltos que el texto anuncia con un día concreto dentro de las fechas de la ficha (inauguración, performance, taller, charla, visita guiada, concierto, recital, lectura…). Para cada uno: tipo; titulo: el nombre del acto copiado LITERAL del texto, SIN la fecha ni la hora (p. ej. «Taller-conversa amb Heidi Ramírez», «Lectura compartida de Naixem de dona, d'Adrienne Rich», «Inauguració»); fecha (AAAA-MM-DD); inicio y fin (HH:MM) si constan; y cita LITERAL donde se leen el día y la hora. No incluyas el horario general de apertura ni rangos de días; no deduzcas una fecha que no esté escrita.
- confianza: alta, media o baja; motivo: una frase.
Todo con citas copiadas literalmente del texto, sin cambiar nada: se comprueban automáticamente. Si algo no aparece, omítelo. No deduzcas ni completes. Responde SIEMPRE llamando a la herramienta estructura, con una entrada por ficha; no escribas texto aparte."""

_q = {'type': 'string'}
TOOL = {'name': 'estructura', 'description': 'Formato, categoría y sesiones de cada ficha, con citas literales.',
        'input_schema': {'type': 'object', 'required': ['fichas'], 'properties': {'fichas': {'type': 'array', 'items': {
            'type': 'object', 'required': ['n', 'formato', 'categoria', 'confianza'], 'properties': {
                'n': {'type': 'integer'},
                'formato': {'type': 'object', 'properties': {'valor': {'type': 'string', 'enum': FORMATS}, 'cita': _q}},
                'categoria': {'type': 'string', 'enum': CATEGORIES},
                'sesiones': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'tipo': {'type': 'string', 'enum': SESSION_TYPES}, 'titulo': _q, 'fecha': _q, 'inicio': _q, 'fin': _q, 'cita': _q}}},
                'confianza': {'type': 'string', 'enum': ['alta', 'media', 'baja']},
                'motivo': {'type': 'string'}}}}}}}


def load_events():
    ev = {}
    for f in glob.glob(str(ROOT / 'dist' / 'data' / 'detail' / '*.json')):
        ev.update(json.load(open(f, encoding='utf-8')))
    return ev


def candidates(ev, today, limit):
    """Fichas vigentes de 7 días o más que hablan de exposición o instalación, o que anuncian
    actos con hora dentro. Se reparte la muestra entre los dos casos."""
    a, b = [], []
    for k, e in sorted(ev.items()):
        try: s, en = dt.date.fromisoformat(e['start']), dt.date.fromisoformat(e['end'])
        except (KeyError, TypeError, ValueError): continue
        if en < today or (en - s).days < 7 or len(e.get('description') or '') < 80: continue
        txt = fold((e.get('title') or '') + '\n' + (e.get('description') or ''))
        mixed = bool(SESS_RX.search(txt) and HOUR_RX.search(txt))
        if e.get('format') != 'exhibition' and EXPO_RX.search(txt): a.append((k, e, 'A' + ('+B' if mixed else '')))
        elif mixed and (e.get('format') == 'exhibition' or EXPO_RX.search(txt)): b.append((k, e, 'B'))
    seed = [x for x in a if x[0] == 'opendatabcn_agenda:99400762348']
    pick = seed + [x for x in a if x not in seed][::max(1, len(a) // (limit // 2))][:limit // 2 - len(seed)]
    pick += b[::max(1, len(b) // (limit - len(pick)))][:limit - len(pick)]
    return pick


def payload(e):
    return {'titulo': (e.get('title') or '')[:200], 'fechas': [e['start'], e['end']], 'sala': ((e.get('venue_names') or [''])[0] or '')[:100],
            'formato_actual': e.get('format'), 'categoria_actual': e.get('public_category'), 'texto': (e.get('description') or '')[:3000]}


def call(key, body):
    """Haiku admite forzar la herramienta. Sonnet 5.5 razona por defecto y entonces la API no deja
    forzarla (400): se reintenta como en weekly_audit, primero sin razonamiento previo
    («between_tools») y la herramienta en «auto», y si tampoco, razonamiento adaptativo con
    esfuerzo bajo y más margen de salida."""
    tries = [body,
             {**body, 'tool_choice': {'type': 'auto'}, 'thinking': {'type': 'between_tools'}, 'output_config': {'effort': 'low'}},
             {**body, 'tool_choice': {'type': 'auto'}, 'output_config': {'effort': 'low'}, 'max_tokens': max(body['max_tokens'], 16000)}]
    errors = []
    for attempt in tries:
        try:
            with ai_assist.usage_label('prueba_estructura', attempt['model']):
                return ai_assist._request('POST', f'{ai_assist.API}/messages', key, attempt, timeout=300)
        except urllib.error.HTTPError as err:
            errors.append(f'{err.code}: {err.read().decode("utf-8", "replace")[:300]}')
            if err.code != 400: break
    sys.exit('La API no aceptó la petición:\n  ' + '\n  '.join(errors))


def ask(items, model):
    key = ai_assist.load_key()
    if not key: sys.exit('Falta ANTHROPIC_API_KEY en .env')
    out, usage = {}, {}
    for i in range(0, len(items), 8):
        chunk = items[i:i + 8]
        body = {'model': model, 'max_tokens': 900 * len(chunk),
                'system': [{'type': 'text', 'text': SYSTEM, 'cache_control': {'type': 'ephemeral'}}],
                'tools': [TOOL], 'tool_choice': {'type': 'tool', 'name': 'estructura'},
                'messages': [{'role': 'user', 'content': json.dumps([{'n': n, **payload(e)} for n, (_, e, _) in enumerate(chunk)], ensure_ascii=False)}]}
        msg = call(key, body)
        for k, v in (msg.get('usage') or {}).items():
            if isinstance(v, int): usage[k] = usage.get(k, 0) + v
        for block in msg.get('content') or []:
            if block.get('type') == 'tool_use':
                for row in (block.get('input') or {}).get('fichas') or []:
                    try: out[chunk[int(row['n'])][0]] = row
                    except (KeyError, ValueError, IndexError, TypeError): pass
    return out, usage


MONTHS = r"(gener|febrer|marc|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre|enero|febrero|marzo|mayo|junio|julio|agosto|septiembre|noviembre|diciembre)"
DATE_IN_TITLE_RX = re.compile(r"[\s:,.\-–(]*\b((el|la|els|les|dia|day)\s+)?((dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b|\d{1,2}\s+(de\s+|d')?" + MONTHS + r"\b|a les \d|a las \d|\d{1,2}([:.]\d{2})?\s*h\b).*$")
LEAD_DATE_RX = re.compile(r"^\W*((dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo),?\s+)?\d{1,2}\s+(de\s+|d')?" + MONTHS + r"(\s+de\s+\d{4})?[\s.:,\-–]*")
GENERIC_TITLES = {'inauguracio', 'inauguracion', 'performance', 'taller', 'visita guiada', 'visita', 'recital', 'presentacio', 'presentacion', 'xerrada', 'charla', 'lectura', 'concert', 'cloenda', 'clausura'}


def fold_keep(text):
    """Como fold, pero letra a letra y sin cambiar la longitud: las posiciones valen para el original."""
    return ''.join((fold(c) or ' ')[:1] if c.strip() else ' ' for c in str(text or ''))


def session_title(raw, kind, parent):
    """Nombre del acto sin fecha ni hora, y si queda genérico, «Tipo · Ficha». Nada redactado: sale
    del texto o del tipo y el título de la ficha."""
    lead = LEAD_DATE_RX.match(fold_keep(raw))
    if lead: raw = raw[lead.end():]                      # «13 d'abril de 2026. Cants I–IV» → «Cants I–IV»
    m = DATE_IN_TITLE_RX.search(fold_keep(raw))
    cut = raw[:m.start()] if m and m.start() > 0 else ('' if m else raw)
    cut = cut.strip(' :,.-–')
    for a, b in (('"', '"'), ("'", "'"), ('«', '»'), ('“', '”')):   # cierra la comilla que la fecha dejó abierta
        if cut.count(a) + cut.count(b) == 1 and cut.startswith(a) is False and a in cut: cut += b
    if len(cut) < 3: cut = TYPE_LABEL.get(kind, 'Activitat')
    if fold(cut) in GENERIC_TITLES: cut = f"{cut[0].upper()}{cut[1:]} · {parent}"
    return cut


def applies(got, row, e):
    """Qué se aplicaría solo: sesiones comprobadas siempre; formato y categoría solo con confianza
    alta, sin contradecir un título que nombra la actividad, y pasar a exposición solo si la cita
    habla de exposición o instalación."""
    out = {'sessions': bool(got.get('sessions'))}
    high = row.get('confianza') == 'alta'
    activity_title = bool(ACTIVITY_TITLE_RX.search(fold(e.get('title') or '')))
    f = got.get('format')
    if f and f != e.get('format'):
        quote = fold((row.get('formato') or {}).get('cita') or '')
        ok = high and not (activity_title and f == 'exhibition') and (f != 'exhibition' or EXPO_RX.search(quote))
        out['format'] = 'aplica' if ok else 'sugerencia'
    c = got.get('category')
    if c and c != e.get('public_category'):
        out['category'] = 'aplica' if high and not (activity_title and c == 'arte') else 'sugerencia'
    return out


def verify(row, e):
    """Lo que queda tras la comprobación sin IA, y lo descartado con su motivo."""
    text = (e.get('title') or '') + '\n' + (e.get('description') or '')
    got, dropped = {}, []
    f = row.get('formato') or {}
    if f.get('valor') in FORMATS and quote_in(f.get('cita') or '', text): got['format'] = f['valor']
    elif f.get('valor'): dropped.append(f"formato {f.get('valor')}: la cita no está en el texto")
    if row.get('categoria') in CATEGORIES: got['category'] = row['categoria']
    sessions = []
    for s in row.get('sesiones') or []:
        q, date, title = s.get('cita') or '', s.get('fecha') or '', s.get('titulo') or ''
        why = ('cita no está en el texto' if not quote_in(q, text) else
               'título no es literal' if not quote_in(title, text) else
               'fecha fuera de la ficha' if not (e['start'] <= date <= e['end']) else
               'el día no se lee en la cita' if not day_ok(date, q) else
               'la hora no se lee en la cita' if s.get('inicio') and not time_ok(s['inicio'], q) else '')
        if why: dropped.append(f"sesión «{title[:50]}» {date} {s.get('inicio') or ''}: {why}"); continue
        sessions.append({'type': s.get('tipo') or 'otro', 'title': session_title(title.strip(), s.get('tipo') or 'otro', e.get('title') or ''), 'raw_title': title.strip(), 'date': date, 'time': s.get('inicio') or '',
                         'end': s.get('fin') if s.get('fin') and time_ok(s['fin'], q) else '', 'quote': q})
    got['sessions'] = sessions
    return got, dropped


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--replay', action='store_true'); ap.add_argument('--limit', type=int, default=30); ap.add_argument('--model', default=ai_assist.MODEL)
    args = ap.parse_args()
    tag = args.model.replace('claude-', '')
    REPORT = ROOT / 'reports' / f'prueba_estructura_ia_v{PROMPT_VERSION}_{tag}.md'
    RAW = ROOT / 'reports' / f'prueba_estructura_ia_raw_v{PROMPT_VERSION}_{tag}.json'
    today = dt.date.today(); ev = load_events(); pick = candidates(ev, today, args.limit)
    v1 = json.loads(RAW_V1.read_text(encoding='utf-8')) if RAW_V1.exists() else None
    if v1 and not args.replay: pick = [(k, ev[k], g) for k, g in v1['picked'] if k in ev]   # mismas fichas que la v1
    if args.replay:
        saved = json.loads(RAW.read_text(encoding='utf-8')); rows, usage = saved['answers'], saved['usage']
        pick = [(k, ev[k], g) for k, g in saved['picked'] if k in ev]
    else:
        rows, usage = ask(pick, args.model)
        RAW.write_text(json.dumps({'at': dt.datetime.now().isoformat(timespec='seconds'), 'model': args.model, 'prompt_version': PROMPT_VERSION,
                                   'picked': [(k, g) for k, _, g in pick], 'answers': rows, 'usage': usage}, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = [f'# Prueba de estructura con IA · {today.isoformat()}', '',
             f'Modelo {args.model}, instrucciones v{PROMPT_VERSION}. Fichas: {len(pick)}; respondidas: {len(rows)}. Uso: {json.dumps(usage)}', '']
    totals = {'formato cambia': 0, 'categoría cambia': 0, 'formato se aplicaría': 0, 'categoría se aplicaría': 0, 'sesiones aceptadas': 0, 'descartes': 0, 'alta': 0}
    old = (v1 or {}).get('answers') or {}
    for k, e, group in pick:
        row = rows.get(k)
        lines += [f'## {e["title"][:110]}', f'`{k}` · grupo {group} · {e["start"]} → {e["end"]} · https://ontoca.com/e/{k.replace(":", "/")}']
        if not row: lines += ['- **sin respuesta**', '']; continue
        got, dropped = verify(row, e)
        fc = got.get('format') and got['format'] != e.get('format'); cc = got.get('category') and got['category'] != e.get('public_category')
        totals['formato cambia'] += bool(fc); totals['categoría cambia'] += bool(cc); totals['sesiones aceptadas'] += len(got['sessions'])
        totals['descartes'] += len(dropped); totals['alta'] += row.get('confianza') == 'alta'
        ap = applies(got, row, e); totals['formato se aplicaría'] += ap.get('format') == 'aplica'; totals['categoría se aplicaría'] += ap.get('category') == 'aplica'
        tag = lambda x: f" (cambia: {ap[x]})" if x in ap else ''
        prev = old.get(k) or {}
        was = f" · v1: {(prev.get('formato') or {}).get('valor', '—')}/{prev.get('categoria', '—')} ({prev.get('confianza', '—')})" if prev else ''
        lines.append(f"- formato: {e.get('format')} → **{got.get('format', '—')}**{tag('format')} · categoría: {e.get('public_category')} → **{got.get('category', '—')}**{tag('category')} · confianza {row.get('confianza')}{was} · {row.get('motivo', '')}")
        for s in got['sessions']:
            lines.append(f"- ✓ sesión {s['type']}: «{s['title']}»{' (de «' + s['raw_title'][:60] + '»)' if s['title'] != s['raw_title'] else ''} · {s['date']} {s['time']}{'–' + s['end'] if s['end'] else ''} · cita: «{s['quote'][:120]}»")
        for d in dropped: lines.append(f'- ✗ {d}')
        lines.append('')
    lines[3:3] = ['**Resumen:** ' + ' · '.join(f'{k}: {v}' for k, v in totals.items()), '']
    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    print(REPORT, '\n' + lines[3])


if __name__ == '__main__':
    main()
