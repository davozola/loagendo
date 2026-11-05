"""Radar semanal de música con Mood (2-11-2026, David).

Mood (events.musicofourdesire.com) es un agregador privado de conciertos y fiestas. No se publica nada de él
(regla del proyecto: los agregadores solo sirven para descubrir y contrastar). Una vez por semana se leen sus
páginas públicas por día de Barcelona (JSON-LD Event; su robots.txt permite /events/ y prohíbe /api/, que no se
toca), se cruzan con lo que publica Ontoca y se anota qué conciertos no tenemos y en qué salas.

Lo que sale: reports/radar/mood-AAAA-MM-DD.json y .md, y una línea en el parte diario de esa semana (salas
que más se nos escapan). El trabajo de conectar una sala nueva sigue siendo a mano (config/venues.json o
config/agendas_ia.json), con su propia web o ticketera, nunca con Mood.

Prueba del 2-11-2026 (117 eventos del 3 al 9-11): 56 ya los teníamos; de los 61 que no, ~15 eran conciertos de
verdad (Sigur Rós en el Fòrum, Archspire en Salamandra, flamenco diario en 23 Robadors…), ~35 ocio nocturno
comercial (tardeos, rooftops, Pacha, Ku…) y ~10 turísticos (Candlelight). El radar separa esos tres grupos.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports' / 'radar'
BASE = 'https://events.musicofourdesire.com/events/Barcelona'
DAYS = 14
LISTS = ('concerts', 'gigs', 'festivals', 'free', 'trending')

# Ocio nocturno comercial y turístico: se cuentan aparte, no piden trabajo.
NIGHTLIFE = re.compile(r"\b(?:tardeo|tardet|afterwork|rooftop|after ?party|opening sabados|money mondays|monday madness|fucking monday|karmela|"
                       r"paripe|wine wednesday|prescription|inner circle|bingo|concurso|dobles de|brunch|sunset|secret rooftop|ladies night|"
                       r"open bar|party|fiesta|reggaeton|perreo|nu bcn|ku barcelona|pacha|opium|shoko|otto zutz|safestay|generator|hostel|"
                       r"jaleo|negresco|azul rooftop|w barcelona|noxe|madame tuset|la biblio)\b")
TOURIST = re.compile(r"\b(?:candlelight|vivaldi|four seasons|basilica of our lady|classical music concert|flamenco show|tablao|"
                     r"sound immersive|la habitacion sonora|aude)\b")
STOP = set('de la el les els los las del i y and the a en at amb with live concert concierto festival barcelona sala ft feat pres presents '
           'w x vs'.split())


def fold(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', str(s or '').lower()) if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s).split())


def words(s):
    return {w for w in fold(s).split() if len(w) > 2 and w not in STOP and not w.isdigit()}


class _LD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.blocks = []; self._in = False; self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('type') == 'application/ld+json': self._in = True; self._buf = []

    def handle_endtag(self, tag):
        if tag == 'script' and self._in: self._in = False; self.blocks.append(''.join(self._buf))

    def handle_data(self, data):
        if self._in: self._buf.append(data)


def events_in(body):
    """Eventos (JSON-LD) de una página de Mood: [{name, start, venue, performers}]."""
    p = _LD(); p.feed(body or ''); out = []
    def walk(x):
        if isinstance(x, list):
            for y in x: walk(y)
        elif isinstance(x, dict):
            types = x.get('@type'); types = types if isinstance(types, list) else [types]
            if any('Event' in str(t) for t in types) and x.get('startDate') and x.get('name'):
                loc = x.get('location') or {}; loc = loc[0] if isinstance(loc, list) and loc else loc
                perf = x.get('performer') or []; perf = perf if isinstance(perf, list) else [perf]
                out.append({'name': str(x['name']).strip(), 'start': str(x['startDate']), 'venue': str((loc or {}).get('name') or '').strip(),
                            'performers': [str(q.get('name') or '').strip() for q in perf if isinstance(q, dict) and q.get('name')][:8]})
            for v in x.values(): walk(v)
    for block in p.blocks:
        try: walk(json.loads(block))
        except ValueError: continue
    return out


def kind_of(ev):
    t = fold(ev['name'] + ' ' + ev['venue'])
    if TOURIST.search(t): return 'turistico'
    if NIGHTLIFE.search(t): return 'ocio_nocturno'
    return 'musica'


def ours_by_day(events):
    """{día: [fichas públicas]} con las de un día y las de varios días que lo cubren."""
    out = {}
    for e in events:
        days = {o.get('date') for o in e.get('occurrences') or [] if o.get('date')}
        if not days and e.get('start') == e.get('end'): days = {e['start']}
        for d in days: out.setdefault(d, []).append(e)
    return out


def match(ev, candidates):
    """La ficha nuestra que es ese evento: mismo día y la mitad o más de las palabras (título o cartel) en común."""
    want = words(ev['name']) | {w for p in ev['performers'] for w in words(p)}
    if not want: return None
    for e in candidates:
        have = words((e.get('source_title') or e.get('title') or '') + ' ' + ' '.join(e.get('lineup') or []))
        common = want & have
        if common and len(common) / min(len(want), len(have) or 1) >= 0.5: return e
    return None


def run(conn, job=None, fetcher=None, today=None, out=OUT, events=None):
    from mvp import catalog
    from src.venue_feeds import fetch, robots_allows
    job = job or {}; fetcher = fetcher or fetch; today = today or catalog.today()
    days = int(job.get('dias') or DAYS)
    urls = [f'{BASE}/date/{(today + dt.timedelta(days=n)).isoformat()}' for n in range(days)] + [f'{BASE}/{x}' for x in LISTS]
    if fetcher is fetch and not robots_allows(urls[0]): return {'status': 'skipped', 'reason': 'robots.txt de Mood no lo permite'}
    seen, errors = {}, []
    for url in urls:
        status, _, body = fetcher(url)
        if status != 200: errors.append(f'{url}: HTTP {status}'); continue
        for ev in events_in(body):
            day = ev['start'][:10]
            if today.isoformat() <= day <= (today + dt.timedelta(days=days)).isoformat(): seen.setdefault((fold(ev['name']), day), ev)
    if not seen: return {'status': 'failed', 'error': '; '.join(errors[:3]) or 'Mood no devolvió eventos'}
    pub = [e for e in (events if events is not None else catalog.all_events(conn)) if catalog.is_public(e)]
    by_day = ours_by_day(pub)
    long_ = [e for e in pub if e.get('start') != e.get('end')]
    have, missing = 0, []
    for (_, day), ev in sorted(seen.items(), key=lambda kv: kv[1]['start']):
        hit = match(ev, by_day.get(day, [])) or match(ev, [e for e in long_ if e['start'] <= day <= e['end']])
        if hit: have += 1; continue
        missing.append({**ev, 'day': day, 'time': ev['start'][11:16], 'kind': kind_of(ev)})
    music = [m for m in missing if m['kind'] == 'musica']
    venues = {}
    for m in music:
        v = m['venue'] if fold(m['venue']) not in ('barcelona', '') else '(sin sala)'
        venues.setdefault(v, []).append(m)
    top = sorted(venues.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    report = {'day': today.isoformat(), 'window_days': days, 'mood_events': len(seen), 'we_have': have, 'missing': len(missing),
              'by_kind': {k: sum(1 for m in missing if m['kind'] == k) for k in ('musica', 'ocio_nocturno', 'turistico')},
              'venues': [{'venue': v, 'count': len(l), 'examples': [f"{x['day'][8:10]}/{x['day'][5:7]} {x['time']} {x['name'][:70]}" for x in l[:4]]} for v, l in top[:25]],
              'missing_music': [{k: m[k] for k in ('day', 'time', 'name', 'venue', 'performers')} for m in music],
              'errors': errors[:10]}
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    (out / f"mood-{today.isoformat()}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    lines = [f"# Radar Mood · {today.isoformat()}", '',
             f"Eventos de Mood en {days} días: {len(seen)} · ya los tenemos: {have} ({round(100 * have / len(seen))} %) · no: {len(missing)} "
             f"(música {report['by_kind']['musica']}, ocio nocturno {report['by_kind']['ocio_nocturno']}, turístico {report['by_kind']['turistico']}).", '',
             'Mood es un agregador privado: no se publica nada de él. Para cubrir un hueco se conecta la sala con su web o su ticketera.', '',
             '## Salas con música que se nos escapa', '']
    lines += [f"- **{v['venue']}** ({v['count']}): " + ' · '.join(v['examples']) for v in report['venues']]
    lines += ['', '## Todos los conciertos que no tenemos', ''] + [f"- {m['day']} {m['time']} · {m['name']} · {m['venue']}" for m in music]
    (out / f"mood-{today.isoformat()}.md").write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'status': 'completed' if not errors else 'partial', 'mood_events': len(seen), 'we_have': have, 'missing': len(missing),
            'by_kind': report['by_kind'], 'top_venues': [f"{v['venue']} ({v['count']})" for v in report['venues'][:8]], 'report': str(out / f"mood-{today.isoformat()}.md"),
            **({'error': '; '.join(errors[:3])} if errors else {})}


def latest(today, out=OUT):
    """El último informe del radar de los últimos 7 días (para el parte diario) o None."""
    try: files = sorted(Path(out).glob('mood-*.json'))
    except OSError: return None
    for f in reversed(files):
        day = f.stem[5:]
        if (today - dt.timedelta(days=7)).isoformat() <= day <= today.isoformat():
            try: return json.loads(f.read_text(encoding='utf-8'))
            except ValueError: return None
    return None
