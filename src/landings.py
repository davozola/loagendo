"""Páginas de entrada para buscadores (23-10-2026): /hoy, /manana, /fin-de-semana, /dia/<fecha>,
/con-ninos, /conciertos, /teatro, /exposiciones y sus combinaciones con hoy y fin de semana.

Cada una es la app de siempre (index.html) que arranca con ese filtro puesto (data-landing, lo lee
public.js) y que lleva en el HTML su título, una frase y la lista de actos con enlace a cada ficha,
para que se lea sin JavaScript. La app retira esa lista (#seoLista) cuando ha pintado la suya.
La lista sale de los ficheros de día ya publicados (data/day/*.json): no se inventa nada."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from urllib.parse import quote

URI_SAFE = "!'()*"
DAYS_ES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
MONTHS_ES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
CAT_ES = {'musica': 'Música', 'escena': 'Teatro y danza', 'cine': 'Cine', 'arte': 'Arte y exposiciones', 'charlas': 'Charlas y visitas',
          'talleres': 'Talleres', 'fiestas': 'Fiestas y mercados', 'deporte': 'Deporte'}
DAY_PAGES = 60          # /dia/<fecha> para los próximos 60 días
MAX_PER_DAY = 40        # filas por día en la lista del HTML (la app muestra el resto)
MAX_ROWS = 150

# Temas: filtro de la app (cats = public_category, chans = canales) y periodo por defecto.
TOPICS = {
    'con-ninos': {'chans': ['familia'], 'range': '7', 'name': 'planes con niños', 'title': 'Planes con niños en Barcelona',
                  'lead': 'Actividades para hacer en familia en Barcelona: teatro infantil, cuentacuentos, talleres, conciertos y visitas, con horario y enlace a la fuente oficial.'},
    'conciertos': {'cats': ['musica'], 'range': '7', 'name': 'conciertos', 'title': 'Conciertos en Barcelona',
                   'lead': 'Conciertos en Barcelona: jazz, clásica, pop, rock, electrónica y músicas del mundo, con hora, sala y enlace a la entrada o a la web oficial.'},
    'teatro': {'cats': ['escena'], 'range': '7', 'name': 'teatro y danza', 'title': 'Teatro y danza en Barcelona',
               'lead': 'Teatro, danza, circo y comedia en Barcelona, con hora, sala y enlace a la web oficial de cada función.'},
    'exposiciones': {'cats': ['arte'], 'range': '30', 'name': 'exposiciones', 'title': 'Exposiciones en Barcelona',
                     'lead': 'Exposiciones abiertas en museos, centros culturales y galerías de Barcelona, con fechas, horario y enlace a la fuente oficial.'},
}


def weekend(today):
    """Fin de semana: de lunes a jueves, del viernes al domingo de esa semana; de viernes a domingo,
    de hoy al domingo (igual que rangeWindow('finde') en public.js)."""
    wd = today.weekday()
    start = today + dt.timedelta(days=4 - wd) if wd < 4 else today
    return start, today + dt.timedelta(days=6 - wd)


def long_date(d):
    return f'{DAYS_ES[d.weekday()]} {d.day} de {MONTHS_ES[d.month - 1]}'


def pages(today):
    """[(ruta, landing para la app, días que lista, título, descripción, h1, frase)]."""
    tomorrow = today + dt.timedelta(days=1); w0, w1 = weekend(today)
    span = lambda a, b: [a + dt.timedelta(days=n) for n in range((b - a).days + 1)]
    out = []
    def add(path, landing, days, title, desc, h1, lead):
        out.append({'path': path, 'landing': {**landing, 'path': path}, 'days': days, 'title': title, 'desc': desc, 'h1': h1, 'lead': lead})
    add('/hoy', {'day': 'today'}, [today], 'Qué hacer hoy en Barcelona · Ontoca', 'Qué hacer hoy en Barcelona: conciertos, teatro, exposiciones, cine y planes con niños, con horario y enlace a la fuente oficial.',
        'Qué hacer hoy en Barcelona', f'Planes para hoy, {long_date(today)}, en Barcelona.')
    add('/manana', {'day': 'tomorrow'}, [tomorrow], 'Qué hacer mañana en Barcelona · Ontoca', 'Qué hacer mañana en Barcelona: conciertos, teatro, exposiciones, cine y planes con niños, con horario y enlace a la fuente oficial.',
        'Qué hacer mañana en Barcelona', f'Planes para mañana, {long_date(tomorrow)}, en Barcelona.')
    add('/fin-de-semana', {'range': 'finde'}, span(w0, w1), 'Qué hacer este fin de semana en Barcelona · Ontoca', 'Planes para este fin de semana en Barcelona: conciertos, teatro, exposiciones y actividades para niños, con horario y enlace a la fuente oficial.',
        'Qué hacer este fin de semana en Barcelona', f'Del {long_date(w0)} al {long_date(w1)}.')
    for n in range(DAY_PAGES):
        d = today + dt.timedelta(days=n)
        add(f'/dia/{d.isoformat()}', {'day': d.isoformat()}, [d], f'Qué hacer en Barcelona el {long_date(d)} · Ontoca',
            f'Agenda de Barcelona para el {long_date(d)} de {d.year}: conciertos, teatro, exposiciones, cine y planes con niños.',
            f'Qué hacer en Barcelona el {long_date(d)}', f'Planes en Barcelona para el {long_date(d)} de {d.year}.')
    for slug, t in TOPICS.items():
        base = {k: t[k] for k in ('cats', 'chans') if k in t}
        n = int(t['range'])
        add(f'/{slug}', {**base, 'range': t['range']}, span(today, today + dt.timedelta(days=min(n, 7) - 1)), f'{t["title"]} · Ontoca', t['lead'], t['title'], t['lead'])
        add(f'/{slug}/hoy', {**base, 'day': 'today'}, [today], f'{t["title"]} hoy · Ontoca', f'{t["title"]} hoy, {long_date(today)}: {t["lead"][0].lower() + t["lead"][1:]}',
            f'{t["title"]} hoy', f'{t["name"][0].upper() + t["name"][1:]} para hoy, {long_date(today)}.')
        add(f'/{slug}/fin-de-semana', {**base, 'range': 'finde'}, span(w0, w1), f'{t["title"]} este fin de semana · Ontoca',
            f'{t["title"]} este fin de semana, del {long_date(w0)} al {long_date(w1)}, con horario y enlace a la fuente oficial.',
            f'{t["title"]} este fin de semana', f'{t["name"][0].upper() + t["name"][1:]} del {long_date(w0)} al {long_date(w1)}.')
    return out


NAV = [('/hoy', 'Hoy'), ('/manana', 'Mañana'), ('/fin-de-semana', 'Este fin de semana'), ('/con-ninos', 'Con niños'),
       ('/con-ninos/fin-de-semana', 'Con niños este finde'), ('/conciertos', 'Conciertos'), ('/teatro', 'Teatro y danza'), ('/exposiciones', 'Exposiciones')]


def nav_html(skip=''):
    """Enlaces a las demás páginas de entrada. Desde el 25-10-2026 no van en el pie: se ponen en la lista en HTML
    de cada página de entrada (la que leen los buscadores), y la portada enlaza con la barra de categorías y «Hoy»."""
    return ('<nav class="seo-nav" aria-label="Planes en Barcelona"><span>Más planes en Barcelona:</span> '
            + ' '.join(f'<a href="{p}">{html.escape(l)}</a>' for p, l in NAV if p != skip) + '</nav>')


def _matches(item, landing):
    if landing.get('cats') and item.get('pc') not in landing['cats']: return False
    if landing.get('chans') and not set(landing['chans']) & set(item.get('ch') or []): return False
    return True


def _row(item, day):
    url = f"/e/{quote(item['s'], safe=URI_SAFE)}/{quote(str(item['i']), safe=URI_SAFE)}"
    time = item.get('tm') or ''
    if not time and item.get('a') != item.get('b'):
        time = 'Varios días'
    venue = (item.get('v') or [''])[0] or ''
    cat = CAT_ES.get(item.get('pc') or '', '')
    meta = ' · '.join(x for x in (cat, venue, 'Gratis' if item.get('fr') else '') if x)
    return (f'<li><a href="{html.escape(url)}">{f"<b>{html.escape(time)}</b> " if time else ""}{html.escape(item.get("t") or "")}</a>'
            + (f' <span>{html.escape(meta)}</span>' if meta else '') + '</li>')


def listing(page, days_data):
    """La lista del HTML: por día, los actos con hora primero (como la app) y luego los de varios días."""
    parts, total, seen = [], 0, set()
    landing = page['landing']; is_art = 'arte' in (landing.get('cats') or [])
    for d in page['days']:
        data = days_data.get(d.isoformat())
        if not data: continue
        items = [i for i in data.get('items', []) if _matches(i, landing)]
        # Exposiciones y programas largos solo en las páginas de arte; en el resto, la app los agrupa aparte.
        if not is_art: items = [i for i in items if i.get('a') == i.get('b') or i.get('kd') not in ('exhibition', 'program')]
        items = [i for i in items if (i['s'], i['i']) not in seen]
        items.sort(key=lambda i: (0 if i.get('tm') else 1, i.get('tm') or '', i.get('t') or ''))
        rows = items[:min(MAX_PER_DAY, MAX_ROWS - total)]
        if not rows: continue
        seen.update((i['s'], i['i']) for i in rows); total += len(rows)
        heading = f'<h2>{html.escape(long_date(d)[0].upper() + long_date(d)[1:])}</h2>' if len(page['days']) > 1 else ''
        parts.append(heading + '<ul>' + ''.join(_row(i, d) for i in rows) + '</ul>')
        if total >= MAX_ROWS: break
    if not parts: parts.append('<p>No hay actos publicados para estas fechas con este filtro.</p>')
    return ''.join(parts)


def render(index, page, days_data, site_url):
    """El HTML de una página de entrada a partir de la portada ya generada."""
    base = site_url.rstrip('/') if site_url else ''
    canonical = f'{base}{page["path"]}'
    doc = index
    doc = re.sub(r'<title>.*?</title>', f'<title>{html.escape(page["title"])}</title>', doc, count=1, flags=re.S)
    doc = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{html.escape(page["desc"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{html.escape(page["title"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{html.escape(page["desc"])}">', doc, count=1)
    doc = re.sub(r'<link rel="canonical" href="[^"]*">', '', doc)
    if base: doc = doc.replace('</head>', f'<link rel="canonical" href="{html.escape(canonical)}"><meta property="og:url" content="{html.escape(canonical)}"></head>', 1)
    landing = json.dumps(page['landing'], ensure_ascii=False, separators=(',', ':'))
    doc = doc.replace('<html lang="es"', f"<html lang=\"es\" data-landing='{html.escape(landing, quote=False).replace(chr(39), '&#39;')}'", 1)
    block = (f'<section id="seoLista" class="seo-lista" lang="es"><h1>{html.escape(page["h1"])}</h1><p>{html.escape(page["lead"])}</p>'
             + listing(page, days_data) + nav_html(skip=page['path']) + '<p class="seo-lista-more"><a href="/">Ver toda la agenda de Barcelona</a></p></section>')
    return doc.replace('<main>', '<main>' + block, 1)


def file_for(path):
    """/hoy → hoy.html, /con-ninos/hoy → con-ninos/hoy.html (Pages las sirve sin .html)."""
    return path.strip('/') + '.html'
