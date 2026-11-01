"""Páginas de entrada para buscadores (23-10-2026): /hoy, /manana, /fin-de-semana, /dia/<fecha>, las categorías,
/con-ninos, /gratis, los distritos y sus combinaciones con hoy, fin de semana y mes.

Cada una es la app de siempre (index.html) que arranca con ese filtro puesto (data-landing, lo lee
public.js) y que lleva en el HTML su título, una frase y la lista de actos con enlace a cada ficha,
para que se lea sin JavaScript. La app retira esa lista (#seoLista) cuando ha pintado la suya.
La lista sale de los ficheros de día ya publicados (data/day/*.json): no se inventa nada.

1-11-2026 (SEO): en castellano (/…), catalán (/ca/…) e inglés (/en/…), con su dirección propia y hreflang entre
ellas; páginas de mes (/conciertos/noviembre-2026). Los textos de la página (títulos, frases, menú) son de Ontoca;
los títulos y textos de los actos, los de su fuente."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from urllib.parse import quote

URI_SAFE = "!'()*"
LANGS = ('es', 'ca', 'en')
PREFIX = {'es': '', 'ca': '/ca', 'en': '/en'}
DAYS = {'es': ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'],
        'ca': ['dilluns', 'dimarts', 'dimecres', 'dijous', 'divendres', 'dissabte', 'diumenge'],
        'en': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']}
MONTHS = {'es': ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'],
          'ca': ['gener', 'febrer', 'març', 'abril', 'maig', 'juny', 'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre'],
          'en': ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']}
DAYS_ES, MONTHS_ES = DAYS['es'], MONTHS['es']
MONTH_SLUGS = {'es': list(MONTHS['es']),
               'ca': ['gener', 'febrer', 'marc', 'abril', 'maig', 'juny', 'juliol', 'agost', 'setembre', 'octubre', 'novembre', 'desembre'],
               'en': [m.lower() for m in MONTHS['en']]}
CATS = {'musica': ('Conciertos y música', 'Concerts i música', 'Concerts and music'),
        'escena': ('Teatro, danza y circo', 'Teatre, dansa i circ', 'Theatre, dance and circus'),
        'cine': ('Cine', 'Cinema', 'Cinema'),
        'arte': ('Exposiciones y arte', 'Exposicions i art', 'Exhibitions and art'),
        'visitas': ('Visitas y rutas', 'Visites i rutes', 'Tours and walks'),
        'charlas': ('Charlas y libros', 'Xerrades i llibres', 'Talks and books'),
        'talleres': ('Talleres y cursos', 'Tallers i cursos', 'Workshops and courses'),
        'fiestas': ('Fiestas, ferias y mercados', 'Festes, fires i mercats', 'Festivals, fairs and markets')}
CAT_ES = {k: v[0] for k, v in CATS.items()}   # 1-11-2026: categorías B
DAY_PAGES = 60          # /dia/<fecha> para los próximos 60 días
MAX_PER_DAY = 40        # filas por día en la lista del HTML (la app muestra el resto)
MAX_ROWS = 150
MONTH_PAGES = 2         # mes en curso y el siguiente
MONTH_PER_DAY = 8       # en las de mes, menos por día para que la lista cubra el mes

# Trozos de dirección traducidos (catalán, inglés).
SLUGS = {'hoy': ('avui', 'today'), 'manana': ('dema', 'tomorrow'), 'fin-de-semana': ('cap-de-setmana', 'weekend'), 'dia': ('dia', 'day'),
         'con-ninos': ('amb-nens', 'with-kids'), 'conciertos': ('concerts', 'concerts'), 'teatro': ('teatre', 'theatre'), 'cine': ('cinema', 'cinema'),
         'exposiciones': ('exposicions', 'exhibitions'), 'visitas-guiadas': ('visites-guiades', 'guided-tours'), 'charlas': ('xerrades', 'talks'),
         'talleres': ('tallers', 'workshops'), 'fiestas-y-mercados': ('festes-i-mercats', 'festivals-and-markets'), 'gratis': ('gratis', 'free'),
         'distrito': ('districte', 'district'), 'sala': ('sala', 'venue')}

# Temas: filtro de la app (cats = public_category, chans = canales, free), periodo por defecto y textos (es, ca, en).
TOPICS = {
    'con-ninos': {'chans': ['familia'], 'range': '7',
                  'name': ('planes con niños', 'plans amb nens', 'plans with kids'),
                  'title': ('Planes con niños en Barcelona', 'Plans amb nens a Barcelona', 'Things to do with kids in Barcelona'),
                  'lead': ('Actividades para hacer en familia en Barcelona: teatro infantil, cuentacuentos, talleres, conciertos y visitas, con horario y enlace a la fuente oficial.',
                           'Activitats per fer en família a Barcelona: teatre infantil, contes, tallers, concerts i visites, amb horari i enllaç a la font oficial.',
                           'Family activities in Barcelona: children’s theatre, storytelling, workshops, concerts and visits, with times and a link to the official source.')},
    'conciertos': {'cats': ['musica'], 'range': '7',
                   'name': ('conciertos', 'concerts', 'concerts'),
                   'title': ('Conciertos en Barcelona', 'Concerts a Barcelona', 'Concerts in Barcelona'),
                   'lead': ('Conciertos en Barcelona: jazz, clásica, pop, rock, electrónica y músicas del mundo, con hora, sala y enlace a la entrada o a la web oficial.',
                            'Concerts a Barcelona: jazz, clàssica, pop, rock, electrònica i músiques del món, amb hora, sala i enllaç a l’entrada o a la web oficial.',
                            'Concerts in Barcelona: jazz, classical, pop, rock, electronic and world music, with time, venue and a link to tickets or the official website.')},
    'teatro': {'cats': ['escena'], 'range': '7',
               'name': ('teatro, danza y circo', 'teatre, dansa i circ', 'theatre, dance and circus'),
               'title': ('Teatro, danza y circo en Barcelona', 'Teatre, dansa i circ a Barcelona', 'Theatre, dance and circus in Barcelona'),
               'lead': ('Teatro, danza, circo y comedia en Barcelona, con hora, sala y enlace a la web oficial de cada función.',
                        'Teatre, dansa, circ i comèdia a Barcelona, amb hora, sala i enllaç a la web oficial de cada funció.',
                        'Theatre, dance, circus and comedy in Barcelona, with time, venue and a link to the official website of each show.')},
    'visitas-guiadas': {'cats': ['visitas'], 'range': '7',
                        'name': ('visitas guiadas y rutas', 'visites guiades i rutes', 'guided tours and walks'),
                        'title': ('Visitas guiadas y rutas en Barcelona', 'Visites guiades i rutes a Barcelona', 'Guided tours and walks in Barcelona'),
                        'lead': ('Visitas guiadas, rutas e itinerarios por Barcelona: museos, patrimonio, barrios y edificios singulares, con hora, punto de encuentro y enlace a la fuente oficial.',
                                 'Visites guiades, rutes i itineraris per Barcelona: museus, patrimoni, barris i edificis singulars, amb hora, punt de trobada i enllaç a la font oficial.',
                                 'Guided tours, walks and routes around Barcelona: museums, heritage, neighbourhoods and landmark buildings, with time, meeting point and a link to the official source.')},
    'exposiciones': {'cats': ['arte'], 'range': '30',
                     'name': ('exposiciones', 'exposicions', 'exhibitions'),
                     'title': ('Exposiciones en Barcelona', 'Exposicions a Barcelona', 'Exhibitions in Barcelona'),
                     'lead': ('Exposiciones abiertas en museos, centros culturales y galerías de Barcelona, con fechas, horario y enlace a la fuente oficial.',
                              'Exposicions obertes a museus, centres culturals i galeries de Barcelona, amb dates, horari i enllaç a la font oficial.',
                              'Exhibitions open in Barcelona’s museums, cultural centres and galleries, with dates, opening hours and a link to the official source.')},
    # 1-11-2026 (SEO): las categorías que no tenían página y «gratis».
    'cine': {'cats': ['cine'], 'range': '7',
             'name': ('cine', 'cinema', 'cinema'),
             'title': ('Cine en Barcelona', 'Cinema a Barcelona', 'Cinema in Barcelona'),
             'lead': ('Cine en Barcelona: estrenos, versión original, ciclos, filmotecas y proyecciones al aire libre, con hora, sala y enlace a la fuente oficial.',
                      'Cinema a Barcelona: estrenes, versió original, cicles, filmoteques i projeccions a l’aire lliure, amb hora, sala i enllaç a la font oficial.',
                      'Cinema in Barcelona: new releases, original-language screenings, film seasons and open-air screenings, with time, venue and a link to the official source.')},
    'charlas': {'cats': ['charlas'], 'range': '7',
                'name': ('charlas y presentaciones de libros', 'xerrades i presentacions de llibres', 'talks and book presentations'),
                'title': ('Charlas, conferencias y libros en Barcelona', 'Xerrades, conferències i llibres a Barcelona', 'Talks, lectures and books in Barcelona'),
                'lead': ('Charlas, conferencias, debates, presentaciones de libros y clubes de lectura en Barcelona, con hora, lugar y enlace a la fuente oficial.',
                         'Xerrades, conferències, debats, presentacions de llibres i clubs de lectura a Barcelona, amb hora, lloc i enllaç a la font oficial.',
                         'Talks, lectures, debates, book presentations and reading clubs in Barcelona, with time, place and a link to the official source.')},
    'talleres': {'cats': ['talleres'], 'range': '7',
                 'name': ('talleres y cursos', 'tallers i cursos', 'workshops and courses'),
                 'title': ('Talleres y cursos en Barcelona', 'Tallers i cursos a Barcelona', 'Workshops and courses in Barcelona'),
                 'lead': ('Talleres y cursos en Barcelona: arte, cocina, idiomas, tecnología, bienestar y actividades en familia, con hora, lugar y enlace a la inscripción.',
                          'Tallers i cursos a Barcelona: art, cuina, idiomes, tecnologia, benestar i activitats en família, amb hora, lloc i enllaç a la inscripció.',
                          'Workshops and courses in Barcelona: art, cooking, languages, technology, wellbeing and family activities, with time, place and a link to sign up.')},
    'fiestas-y-mercados': {'cats': ['fiestas'], 'range': '7',
                           'name': ('fiestas, ferias y mercados', 'festes, fires i mercats', 'festivals, fairs and markets'),
                           'title': ('Fiestas, ferias y mercados en Barcelona', 'Festes, fires i mercats a Barcelona', 'Festivals, fairs and markets in Barcelona'),
                           'lead': ('Fiestas mayores, ferias, mercados, mercadillos y celebraciones populares en Barcelona, con fechas, lugar y enlace a la fuente oficial.',
                                    'Festes majors, fires, mercats, mercadets i celebracions populars a Barcelona, amb dates, lloc i enllaç a la font oficial.',
                                    'Neighbourhood festivals, fairs, markets, flea markets and popular celebrations in Barcelona, with dates, place and a link to the official source.')},
    'gratis': {'free': True, 'range': '7',
               'name': ('planes gratis', 'plans gratis', 'free things to do'),
               'title': ('Planes gratis en Barcelona', 'Plans gratis a Barcelona', 'Free things to do in Barcelona'),
               'lead': ('Qué hacer gratis en Barcelona: conciertos, exposiciones, visitas, charlas y actividades con niños de entrada libre, con horario y enlace a la fuente oficial.',
                        'Què fer gratis a Barcelona: concerts, exposicions, visites, xerrades i activitats amb nens d’entrada lliure, amb horari i enllaç a la font oficial.',
                        'Free things to do in Barcelona: concerts, exhibitions, tours, talks and kids’ activities with free entry, with times and a link to the official source.')},
}
MONTH_TOPICS = ('conciertos', 'teatro', 'exposiciones', 'con-ninos', 'cine', 'gratis', 'fiestas-y-mercados')
# Distritos (1-11-2026, SEO): /distrito/<slug>. El nombre es el que publica la ficha (campo d), el mismo en los tres idiomas.
DISTRICTS = {'ciutat-vella': 'Ciutat Vella', 'eixample': 'Eixample', 'sants-montjuic': 'Sants-Montjuïc', 'les-corts': 'Les Corts',
             'sarria-sant-gervasi': 'Sarrià-Sant Gervasi', 'gracia': 'Gràcia', 'horta-guinardo': 'Horta-Guinardó', 'nou-barris': 'Nou Barris',
             'sant-andreu': 'Sant Andreu', 'sant-marti': 'Sant Martí'}
# Página de cada categoría (la ficha enlaza con la suya; public.js CAT_LANDING).
CAT_PAGE = {'musica': '/conciertos', 'escena': '/teatro', 'cine': '/cine', 'arte': '/exposiciones', 'visitas': '/visitas-guiadas',
            'charlas': '/charlas', 'talleres': '/talleres', 'fiestas': '/fiestas-y-mercados'}

# Frases de las páginas generales, por idioma.
TEXT = {
    'es': {'today': 'hoy', 'tomorrow': 'mañana', 'weekend': 'este fin de semana',
           'hoy_t': 'Qué hacer hoy en Barcelona', 'manana_t': 'Qué hacer mañana en Barcelona', 'finde_t': 'Qué hacer este fin de semana en Barcelona',
           'gen_desc': 'conciertos, teatro, exposiciones, cine y planes con niños, con horario y enlace a la fuente oficial.',
           'plans_for': 'Planes para {when}, {date}, en Barcelona.', 'from_to': 'Del {a} al {b}.', 'day_t': 'Qué hacer en Barcelona el {date}',
           'day_desc': 'Agenda de Barcelona para el {date} de {year}: conciertos, teatro, exposiciones, cine y planes con niños.',
           'day_lead': 'Planes en Barcelona para el {date} de {year}.', 'month_t': 'Qué hacer en Barcelona en {month} de {year}',
           'month_desc': 'Agenda de Barcelona de {month} de {year}: conciertos, teatro, exposiciones, cine, fiestas y planes con niños, con fechas y enlace a la fuente oficial.',
           'month_lead': 'Planes en Barcelona en {month} de {year}.', 'topic_month_t': '{title} en {month} de {year}',
           'topic_month_desc': '{title} en {month} de {year}, con fechas, horario y enlace a la fuente oficial.',
           'topic_month_lead': '{Name} en {month} de {year}.', 'topic_today_lead': '{Name} para hoy, {date}.', 'topic_finde_lead': '{Name} del {a} al {b}.',
           'topic_finde_desc': '{title} este fin de semana, del {a} al {b}, con horario y enlace a la fuente oficial.',
           'dist_t': 'Qué hacer en {d}', 'dist_title': 'Qué hacer en {d}, Barcelona',
           'dist_desc': 'Agenda de {d} (Barcelona): conciertos, teatro, exposiciones, talleres y planes de barrio de los próximos días, con horario y enlace a la fuente oficial.',
           'dist_lead': 'Planes en el distrito de {d} para los próximos 7 días.', 'dist_finde_t': 'Qué hacer en {d} este fin de semana',
           'dist_finde_desc': 'Planes en {d} (Barcelona) este fin de semana, del {a} al {b}, con horario y enlace a la fuente oficial.', 'dist_finde_lead': 'Del {a} al {b} en {d}.',
           'several': 'Varios días', 'free': 'Gratis', 'none': 'No hay actos publicados para estas fechas con este filtro.', 'more': 'Ver toda la agenda de Barcelona',
           'nav': 'Más planes en Barcelona', 'g_when': 'Cuándo', 'g_what': 'Qué', 'g_finde': 'Este finde', 'g_where': 'Dónde', 'g_month': 'Por meses',
           'home_h': 'Planes para hoy, {date}, en Barcelona',
           'home_title': 'Ontoca · Qué hacer en Barcelona, cada día',
           'home_desc': 'Qué hacer hoy en Barcelona: conciertos, teatro, exposiciones, cine, planes de barrio y actividades familiares, con horarios y enlaces a la fuente oficial.',
           'home_og': 'Mil maneras de vivir la ciudad. Conciertos, teatro, exposiciones, cine y planes de barrio en Barcelona, cada día.',
           'n_hoy': 'Hoy', 'n_manana': 'Mañana', 'n_finde': 'Este fin de semana'},
    'ca': {'today': 'avui', 'tomorrow': 'demà', 'weekend': 'aquest cap de setmana',
           'hoy_t': 'Què fer avui a Barcelona', 'manana_t': 'Què fer demà a Barcelona', 'finde_t': 'Què fer aquest cap de setmana a Barcelona',
           'gen_desc': 'concerts, teatre, exposicions, cinema i plans amb nens, amb horari i enllaç a la font oficial.',
           'plans_for': 'Plans per a {when}, {date}, a Barcelona.', 'from_to': 'Del {a} al {b}.', 'day_t': 'Què fer a Barcelona el {date}',
           'day_desc': 'Agenda de Barcelona per al {date} de {year}: concerts, teatre, exposicions, cinema i plans amb nens.',
           'day_lead': 'Plans a Barcelona per al {date} de {year}.', 'month_t': 'Què fer a Barcelona el mes {ofmonth} {year}',
           'month_desc': 'Agenda de Barcelona del mes {ofmonth} {year}: concerts, teatre, exposicions, cinema, festes i plans amb nens, amb dates i enllaç a la font oficial.',
           'month_lead': 'Plans a Barcelona el mes {ofmonth} {year}.', 'topic_month_t': '{title} el mes {ofmonth} {year}',
           'topic_month_desc': '{title} el mes {ofmonth} {year}, amb dates, horari i enllaç a la font oficial.',
           'topic_month_lead': '{Name} el mes {ofmonth} {year}.', 'topic_today_lead': '{Name} per a avui, {date}.', 'topic_finde_lead': '{Name} del {a} al {b}.',
           'topic_finde_desc': '{title} aquest cap de setmana, del {a} al {b}, amb horari i enllaç a la font oficial.',
           'dist_t': 'Què fer a {d}', 'dist_title': 'Què fer a {d}, Barcelona',
           'dist_desc': 'Agenda de {d} (Barcelona): concerts, teatre, exposicions, tallers i plans de barri dels propers dies, amb horari i enllaç a la font oficial.',
           'dist_lead': 'Plans al districte de {d} per als propers 7 dies.', 'dist_finde_t': 'Què fer a {d} aquest cap de setmana',
           'dist_finde_desc': 'Plans a {d} (Barcelona) aquest cap de setmana, del {a} al {b}, amb horari i enllaç a la font oficial.', 'dist_finde_lead': 'Del {a} al {b} a {d}.',
           'several': 'Diversos dies', 'free': 'Gratis', 'none': 'No hi ha actes publicats per a aquestes dates amb aquest filtre.', 'more': 'Veure tota l’agenda de Barcelona',
           'nav': 'Més plans a Barcelona', 'g_when': 'Quan', 'g_what': 'Què', 'g_finde': 'Aquest cap de setmana', 'g_where': 'On', 'g_month': 'Per mesos',
           'home_h': 'Plans per a avui, {date}, a Barcelona',
           'home_title': 'Ontoca · Què fer a Barcelona, cada dia',
           'home_desc': 'Què fer avui a Barcelona: concerts, teatre, exposicions, cinema, plans de barri i activitats familiars, amb horaris i enllaços a la font oficial.',
           'home_og': 'Mil maneres de viure la ciutat. Concerts, teatre, exposicions, cinema i plans de barri a Barcelona, cada dia.',
           'n_hoy': 'Avui', 'n_manana': 'Demà', 'n_finde': 'Aquest cap de setmana'},
    'en': {'today': 'today', 'tomorrow': 'tomorrow', 'weekend': 'this weekend',
           'hoy_t': 'Things to do in Barcelona today', 'manana_t': 'Things to do in Barcelona tomorrow', 'finde_t': 'Things to do in Barcelona this weekend',
           'gen_desc': 'concerts, theatre, exhibitions, cinema and plans with kids, with times and a link to the official source.',
           'plans_for': 'What’s on {when}, {date}, in Barcelona.', 'from_to': 'From {a} to {b}.', 'day_t': 'Things to do in Barcelona on {date}',
           'day_desc': 'What’s on in Barcelona on {date} {year}: concerts, theatre, exhibitions, cinema and plans with kids.',
           'day_lead': 'What’s on in Barcelona on {date} {year}.', 'month_t': 'Things to do in Barcelona in {month} {year}',
           'month_desc': 'What’s on in Barcelona in {month} {year}: concerts, theatre, exhibitions, cinema, festivals and plans with kids, with dates and a link to the official source.',
           'month_lead': 'What’s on in Barcelona in {month} {year}.', 'topic_month_t': '{title} in {month} {year}',
           'topic_month_desc': '{title} in {month} {year}, with dates, times and a link to the official source.',
           'topic_month_lead': '{Name} in {month} {year}.', 'topic_today_lead': '{Name} today, {date}.', 'topic_finde_lead': '{Name} from {a} to {b}.',
           'topic_finde_desc': '{title} this weekend, from {a} to {b}, with times and a link to the official source.',
           'dist_t': 'Things to do in {d}', 'dist_title': 'Things to do in {d}, Barcelona',
           'dist_desc': 'What’s on in {d} (Barcelona): concerts, theatre, exhibitions, workshops and neighbourhood plans for the coming days, with times and a link to the official source.',
           'dist_lead': 'What’s on in the {d} district over the next 7 days.', 'dist_finde_t': 'Things to do in {d} this weekend',
           'dist_finde_desc': 'What’s on in {d} (Barcelona) this weekend, from {a} to {b}, with times and a link to the official source.', 'dist_finde_lead': 'From {a} to {b} in {d}.',
           'several': 'Several days', 'free': 'Free', 'none': 'Nothing published for these dates with this filter.', 'more': 'See all of Barcelona’s listings',
           'nav': 'More things to do in Barcelona', 'g_when': 'When', 'g_what': 'What', 'g_finde': 'This weekend', 'g_where': 'Where', 'g_month': 'By month',
           'home_h': 'What’s on today, {date}, in Barcelona',
           'home_title': 'Ontoca · Things to do in Barcelona, every day',
           'home_desc': 'Things to do in Barcelona today: concerts, theatre, exhibitions, cinema, neighbourhood plans and family activities, with times and links to the official source.',
           'home_og': 'A thousand ways to live the city. Concerts, theatre, exhibitions, cinema and neighbourhood plans in Barcelona, every day.',
           'n_hoy': 'Today', 'n_manana': 'Tomorrow', 'n_finde': 'This weekend'},
}
SHORT = {'conciertos': ('Conciertos', 'Concerts', 'Concerts'), 'teatro': ('Teatro, danza y circo', 'Teatre, dansa i circ', 'Theatre and dance'),
         'cine': ('Cine', 'Cinema', 'Cinema'), 'exposiciones': ('Exposiciones', 'Exposicions', 'Exhibitions'),
         'visitas-guiadas': ('Visitas guiadas', 'Visites guiades', 'Guided tours'), 'charlas': ('Charlas y libros', 'Xerrades i llibres', 'Talks and books'),
         'talleres': ('Talleres y cursos', 'Tallers i cursos', 'Workshops'), 'fiestas-y-mercados': ('Fiestas y mercados', 'Festes i mercats', 'Festivals and markets'),
         'con-ninos': ('Con niños', 'Amb nens', 'With kids'), 'gratis': ('Gratis', 'Gratis', 'Free')}


def ix(lang):
    return LANGS.index(lang)


def localize(path, lang):
    """/conciertos/fin-de-semana → /ca/concerts/cap-de-setmana; /noviembre-2026 → /en/november-2026; / → /ca/."""
    if lang == 'es': return path
    out = []
    for seg in path.strip('/').split('/'):
        if not seg: continue
        m = re.fullmatch(r'([a-z]+)-(\d{4})', seg)
        if seg in SLUGS: out.append(SLUGS[seg][ix(lang) - 1])
        elif m and m.group(1) in MONTH_SLUGS['es']: out.append(f"{MONTH_SLUGS[lang][MONTH_SLUGS['es'].index(m.group(1))]}-{m.group(2)}")
        else: out.append(seg)
    return PREFIX[lang] + ('/' + '/'.join(out) if out else '/')


def weekend(today):
    """Fin de semana: de lunes a jueves, del viernes al domingo de esa semana; de viernes a domingo,
    de hoy al domingo (igual que rangeWindow('finde') en public.js)."""
    wd = today.weekday()
    start = today + dt.timedelta(days=4 - wd) if wd < 4 else today
    return start, today + dt.timedelta(days=6 - wd)


def _of_month(month):   # catalán: «d’octubre», «de novembre»
    return f"d’{month}" if month[0] in 'aeiou' else f'de {month}'


def long_date(d, lang='es'):
    if lang == 'en': return f'{DAYS["en"][d.weekday()]} {d.day} {MONTHS["en"][d.month - 1]}'
    if lang == 'ca': return f'{DAYS["ca"][d.weekday()]} {d.day} {_of_month(MONTHS["ca"][d.month - 1])}'
    return f'{DAYS_ES[d.weekday()]} {d.day} de {MONTHS_ES[d.month - 1]}'


def _cap(s):
    return s[:1].upper() + s[1:]


def month_starts(today):
    first = today.replace(day=1); out = [first]
    for _ in range(MONTH_PAGES - 1):
        first = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1); out.append(first)
    return out


def month_end(first):
    return (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)


def month_slug(first):
    return f"{MONTH_SLUGS['es'][first.month - 1]}-{first.year}"


def pages(today, lang='es'):
    """Páginas de entrada en un idioma: ruta, filtro para la app, días que lista, título, descripción, h1, frase y
    direcciones de las otras dos versiones (alts)."""
    T = TEXT[lang]; i = ix(lang); L = lambda d: long_date(d, lang)
    tomorrow = today + dt.timedelta(days=1); w0, w1 = weekend(today)
    span = lambda a, b: [a + dt.timedelta(days=n) for n in range((b - a).days + 1)]
    out = []

    one = L(w0) if w0 == w1 else ''   # domingo: el «fin de semana» es un solo día
    def single(text):
        if not one: return text
        for a, b in ((f'Del {one} al {one}', f'El {one}'), (f'del {one} al {one}', f'el {one}'), (f'From {one} to {one}', f'On {one}'), (f'from {one} to {one}', f'on {one}')):
            text = text.replace(a, b)
        return text

    def add(path, landing, days, title, desc, h1, lead, per_day=MAX_PER_DAY, canon=None):
        title, desc, h1, lead = single(title), single(desc), single(h1), single(lead)
        local = localize(path, lang)
        # canon (1-11-2026): /dia/<hoy> es /hoy y /dia/<mañana> es /manana; la canónica y los hreflang, los de esas.
        out.append({'path': local, 'base': path, 'lang': lang, 'landing': {**landing, 'path': local}, 'days': days, 'title': title,
                    'desc': desc, 'h1': h1, 'lead': lead, 'per_day': per_day, 'alts': {l: localize(canon or path, l) for l in LANGS},
                    'canonical': localize(canon, lang) if canon else local})

    add('/hoy', {'day': 'today'}, [today], f'{T["hoy_t"]} · Ontoca', f'{T["hoy_t"]}: {T["gen_desc"]}', T['hoy_t'],
        T['plans_for'].format(when=T['today'], date=L(today)))
    add('/manana', {'day': 'tomorrow'}, [tomorrow], f'{T["manana_t"]} · Ontoca', f'{T["manana_t"]}: {T["gen_desc"]}', T['manana_t'],
        T['plans_for'].format(when=T['tomorrow'], date=L(tomorrow)))
    add('/fin-de-semana', {'range': 'finde'}, span(w0, w1), f'{T["finde_t"]} · Ontoca', f'{T["finde_t"]}: {T["gen_desc"]}', T['finde_t'],
        T['from_to'].format(a=L(w0), b=L(w1)))
    for n in range(DAY_PAGES):
        d = today + dt.timedelta(days=n)
        add(f'/dia/{d.isoformat()}', {'day': d.isoformat()}, [d], f'{T["day_t"].format(date=L(d))} · Ontoca',
            T['day_desc'].format(date=L(d), year=d.year), T['day_t'].format(date=L(d)), T['day_lead'].format(date=L(d), year=d.year),
            canon='/hoy' if n == 0 else '/manana' if n == 1 else None)
    months = []
    for first in month_starts(today):
        a, b = max(first, today), month_end(first); name = MONTHS[lang][first.month - 1]
        fmt = {'month': name, 'ofmonth': _of_month(name), 'year': first.year}
        months.append((first, a, b, fmt))
        add(f'/{month_slug(first)}', {'range': f'm{first.isoformat()[:7]}'}, span(a, b), f'{T["month_t"].format(**fmt)} · Ontoca',
            T['month_desc'].format(**fmt), T['month_t'].format(**fmt), T['month_lead'].format(**fmt), per_day=MONTH_PER_DAY)
    for slug, t in TOPICS.items():
        base = {k: t[k] for k in ('cats', 'chans', 'free') if k in t}
        title, name, lead = t['title'][i], t['name'][i], t['lead'][i]
        n = int(t['range'])
        add(f'/{slug}', {**base, 'range': t['range']}, span(today, today + dt.timedelta(days=min(n, 7) - 1)), f'{title} · Ontoca', lead, title, lead)
        add(f'/{slug}/hoy', {**base, 'day': 'today'}, [today], f'{title} {T["today"]} · Ontoca',
            f'{title} {T["today"]}, {L(today)}: {lead[0].lower() + lead[1:]}', f'{title} {T["today"]}',
            T['topic_today_lead'].format(Name=_cap(name), date=L(today)))
        add(f'/{slug}/fin-de-semana', {**base, 'range': 'finde'}, span(w0, w1), f'{title} {T["weekend"]} · Ontoca',
            T['topic_finde_desc'].format(title=title, a=L(w0), b=L(w1)), f'{title} {T["weekend"]}',
            T['topic_finde_lead'].format(Name=_cap(name), a=L(w0), b=L(w1)))
        if slug in MONTH_TOPICS:
            for first, a, b, fmt in months:
                f2 = {**fmt, 'title': title, 'Name': _cap(name)}
                add(f'/{slug}/{month_slug(first)}', {**base, 'range': f'm{first.isoformat()[:7]}'}, span(a, b),
                    f'{T["topic_month_t"].format(**f2)} · Ontoca', T['topic_month_desc'].format(**f2), T['topic_month_t'].format(**f2),
                    T['topic_month_lead'].format(**f2), per_day=MONTH_PER_DAY)
    for slug, d in DISTRICTS.items():
        base = {'district': d}
        add(f'/distrito/{slug}', {**base, 'range': '7'}, span(today, today + dt.timedelta(days=6)), f'{T["dist_title"].format(d=d)} · Ontoca',
            T['dist_desc'].format(d=d), T['dist_t'].format(d=d), T['dist_lead'].format(d=d))
        add(f'/distrito/{slug}/fin-de-semana', {**base, 'range': 'finde'}, span(w0, w1), f'{T["dist_finde_t"].format(d=d)} · Ontoca',
            T['dist_finde_desc'].format(d=d, a=L(w0), b=L(w1)), T['dist_finde_t'].format(d=d), T['dist_finde_lead'].format(d=d, a=L(w0), b=L(w1)))
    return out


# Piloto de páginas de sala (1-11-2026, encargo del consultor): 15 recintos variados. Nombre tal como lo publican las fichas
# (sus salas «Nombre · Sala X» cuentan como el recinto) y web oficial solo si ya está en config/venues.json o agendas_ia.json.
VENUES = [
    ('palau-de-la-musica', 'Palau de la Música Catalana', 'https://www.palaumusica.cat/ca/agenda'),
    ('liceu', 'Gran Teatre del Liceu', 'https://www.liceubarcelona.cat/ca/programacio'),
    ('auditori', "L'Auditori de Barcelona", ''),
    ('cccb', 'CCCB', 'https://www.cccb.org/es/calendario'),
    ('mnac', "Museu Nacional d'Art de Catalunya", 'https://www.museunacional.cat/es/actividades'),
    ('caixaforum', 'CaixaForum Barcelona', 'https://caixaforum.org/es/barcelona/actividades'),
    ('filmoteca', 'Filmoteca de Catalunya', 'https://www.filmoteca.cat/web/ca/programacio'),
    ('zumzeig', 'Zumzeig Cinecooperativa', 'https://zumzeigcine.coop/cinema/sessions/'),
    ('phenomena', 'Phenomena Experience', 'https://phenomena-experience.com/index?pag=cartelera'),
    ('sala-apolo', 'Sala Apolo', 'https://www.sala-apolo.com/'),
    ('jamboree', 'Jamboree Jazz Club', 'https://jamboreejazz.com/'),
    ('razzmatazz', 'Razzmatazz', 'https://www.salarazzmatazz.com/agenda/'),
    ('espai-texas', 'Espai Texas', 'https://espaitexas.cat/cartellera-cinema/'),
    ('casa-orlandai', 'Centre Cívic Casa Orlandai', ''),
    ('fabra-i-coats', 'Fabra i Coats - Fàbrica de Creació', 'https://ajuntament.barcelona.cat/fabraicoats/'),
]
VENUE_MIN = 5   # con menos actos publicados, la página no va al índice
VTEXT = {'es': {'title': 'Programación de {v} · Ontoca', 'h1': 'Programación de {v}',
                'desc': 'Próximos actos en {v} ({d}, Barcelona): {n} planes publicados, con fecha, hora y enlace a la fuente oficial.',
                'mostly': 'Sobre todo {c} ({k} de {n} actos publicados).', 'where': 'Dirección: {a}.', 'web': 'Programación oficial de {v}',
                'until': 'Hasta el {d}', 'none': 'Ahora mismo no hay actos publicados en esta sala.'},
         'ca': {'title': 'Programació de {v} · Ontoca', 'h1': 'Programació de {v}',
                'desc': 'Propers actes a {v} ({d}, Barcelona): {n} plans publicats, amb data, hora i enllaç a la font oficial.',
                'mostly': 'Sobretot {c} ({k} de {n} actes publicats).', 'where': 'Adreça: {a}.', 'web': 'Programació oficial de {v}',
                'until': 'Fins al {d}', 'none': 'Ara mateix no hi ha actes publicats en aquesta sala.'},
         'en': {'title': '{v}: what’s on · Ontoca', 'h1': '{v}: what’s on',
                'desc': 'Upcoming events at {v} ({d}, Barcelona): {n} listings with date, time and a link to the official source.',
                'mostly': 'Mostly {c} ({k} of {n} listings).', 'where': 'Address: {a}.', 'web': 'Official programme of {v}',
                'until': 'Until {d}', 'none': 'There are no events listed at this venue right now.'}}


def _at_venue(item, name):
    v = (item.get('v') or [''])[0] or ''
    return v == name or v.startswith(name + ' · ') or (name == 'Razzmatazz' and v.startswith('Razzmatazz'))


def venue_items(name, catalog_items, today):
    t = today.isoformat()
    items = [i for i in catalog_items if (i.get('b') or i.get('a') or '') >= t and _at_venue(i, name)]
    items.sort(key=lambda i: (max(i.get('a') or t, t), i.get('tm') or '', i.get('t') or ''))
    return items


def _venue_info(items, details_dir):
    """Dirección, coordenadas y distrito tal como los publica la primera ficha que los trae."""
    import hashlib
    from pathlib import Path
    info = {'district': next((i.get('d') for i in items if i.get('d')), '')}
    if not details_dir: return info
    for it in items[:8]:
        key = f"{it['s']}:{it['i']}"; shard = hashlib.sha1(key.encode('utf-8')).hexdigest()[:2]
        try: d = json.loads((Path(details_dir) / f'{shard}.json').read_text(encoding='utf-8')).get(key) or {}
        except (OSError, ValueError): continue
        ven = (d.get('venues') or [{}])[0] or {}
        if ven.get('address') and not info.get('address'): info['address'] = ven['address']
        if ven.get('lat') and ven.get('lon') and not info.get('geo'): info['geo'] = (ven['lat'], ven['lon'])
        if info.get('address') and info.get('geo'): break
    return info


def venue_pages(today, catalog_items, details_dir=None):
    out = []
    for slug, name, web in VENUES:
        items = venue_items(name, catalog_items or [], today)
        info = _venue_info(items, details_dir)
        cats = {}
        for i in items: cats[i.get('pc')] = cats.get(i.get('pc'), 0) + 1
        top = max(cats.items(), key=lambda kv: kv[1]) if cats else (None, 0)
        for lang in LANGS:
            V = VTEXT[lang]; i = ix(lang); path = f'/sala/{slug}'; local = localize(path, lang)
            lead = []
            if top[0] in CATS and items: lead.append(V['mostly'].format(c=CATS[top[0]][i].lower(), k=top[1], n=len(items)))
            if info.get('address'): lead.append(V['where'].format(a=info['address'] + (f", {info['district']}" if info.get('district') else '')))
            rows = []
            for it in items[:80]:
                one = it.get('a') == it.get('b')
                d = dt.date.fromisoformat(max(it.get('a') or today.isoformat(), today.isoformat()))
                when = (_cap(long_date(d, lang)) + (f" · {it['tm']}" if it.get('tm') else '')) if one else V['until'].format(d=long_date(dt.date.fromisoformat(it['b']), lang))
                cat = CATS.get(it.get('pc') or '', ('', '', ''))[i]
                rows.append(f'<li><a href="{html.escape(event_path(it, lang))}"><b>{html.escape(when)}</b> {html.escape(it.get("t") or "")}</a>'
                            + (f' <span>{html.escape(cat)}</span>' if cat else '') + '</li>')
            body = ('<ul>' + ''.join(rows) + '</ul>') if rows else f'<p>{html.escape(V["none"])}</p>'
            if web: body += f'<p class="seo-lista-more"><a href="{html.escape(web)}" rel="noopener" target="_blank">{html.escape(V["web"].format(v=name))}</a></p>'
            place = {'@context': 'https://schema.org', '@type': 'Place', 'name': name,
                     **({'address': {'@type': 'PostalAddress', 'streetAddress': info['address'], 'addressLocality': 'Barcelona', 'addressCountry': 'ES'}} if info.get('address') else {}),
                     **({'geo': {'@type': 'GeoCoordinates', 'latitude': info['geo'][0], 'longitude': info['geo'][1]}} if info.get('geo') else {}),
                     **({'url': web} if web else {})}
            out.append({'path': local, 'base': path, 'lang': lang, 'landing': {'q': name, 'range': '183', 'path': local}, 'days': [],
                        'title': V['title'].format(v=name), 'desc': V['desc'].format(v=name, d=info.get('district') or 'Barcelona', n=len(items)),
                        'h1': V['h1'].format(v=name), 'lead': ' '.join(lead), 'alts': {l: localize(path, l) for l in LANGS}, 'canonical': local,
                        'rows_html': body, 'count': len(items), 'jsonld': place})
    return out


def indexable_paths(today, days_data, catalog_items=None):
    """Las páginas de entrada que van al sitemap: las que son su propia canónica y tienen al menos un acto."""
    data = with_catalog(days_data, catalog_items) if catalog_items else days_data
    entries = [p['path'] for p in all_pages(today) if p.get('canonical', p['path']) == p['path'] and '<li>' in listing(p, data)]
    return entries + [p['path'] for p in venue_pages(today, catalog_items or []) if p['count'] >= VENUE_MIN]


def all_pages(today):
    """Las de los tres idiomas."""
    return [p for lang in LANGS for p in pages(today, lang)]


def nav_groups(lang='es', today=None):
    T = TEXT[lang]; i = ix(lang); loc = lambda p: localize(p, lang)
    groups = [
        (T['g_when'], [(loc('/hoy'), T['n_hoy']), (loc('/manana'), T['n_manana']), (loc('/fin-de-semana'), T['n_finde'])]),
        (T['g_what'], [(loc(f'/{s}'), SHORT[s][i]) for s in ('conciertos', 'teatro', 'cine', 'exposiciones', 'visitas-guiadas', 'charlas',
                                                              'talleres', 'fiestas-y-mercados', 'con-ninos', 'gratis')]),
        (T['g_finde'], [(loc(f'/{s}/fin-de-semana'), SHORT[s][i]) for s in ('conciertos', 'teatro', 'con-ninos', 'gratis', 'exposiciones')]),
        (T['g_where'], [(loc(f'/distrito/{k}'), v) for k, v in DISTRICTS.items()]),
    ]
    if today:
        groups.append((T['g_month'], [(loc(f'/{month_slug(f)}'), f'{_cap(MONTHS[lang][f.month - 1])} {f.year}') for f in month_starts(today)]))
    return groups


NAV_GROUPS = nav_groups('es')
NAV = [link for _, links in NAV_GROUPS for link in links]


def nav_html(skip='', lang='es', today=None):
    """Enlaces a las demás páginas de entrada. Desde el 25-10-2026 no van en el pie: se ponen en la lista en HTML
    de cada página de entrada (la que leen los buscadores). 1-11-2026: por grupos (cuándo, qué, este finde, dónde,
    meses), también en la portada, y en el idioma de la página."""
    groups = ''.join(f'<p><span>{html.escape(name)}:</span> ' + ' '.join(f'<a href="{p}">{html.escape(l)}</a>' for p, l in links if p != skip) + '</p>'
                     for name, links in nav_groups(lang, today))
    label = html.escape(TEXT[lang]['nav'])
    return f'<nav class="seo-nav" aria-label="{label}"><span>{label}</span>{groups}</nav>'


def _matches(item, landing):
    if landing.get('cats') and item.get('pc') not in landing['cats']: return False
    if landing.get('chans') and not set(landing['chans']) & set(item.get('ch') or []): return False
    if landing.get('free') and not item.get('fr'): return False
    if landing.get('district') and item.get('d') != landing['district']: return False
    return True


# Nombre público de la fuente en las direcciones (1-11-2026): las agendas de sala salen como «sala_<slug>», no con el
# nombre interno; functions/e, functions/cal y public.js lo traducen de vuelta.
INTERNAL_PREFIX, PUBLIC_PREFIX = 'venue_ia_', 'sala_'


def public_source(source):
    return PUBLIC_PREFIX + source[len(INTERNAL_PREFIX):] if source.startswith(INTERNAL_PREFIX) else source


def event_path(item, lang='es'):
    return f"{PREFIX[lang]}/e/{quote(public_source(item['s']), safe=URI_SAFE)}/{quote(str(item['i']), safe=URI_SAFE)}"


def _row(item, day, lang='es'):
    url = event_path(item, lang)
    time = item.get('tm') or ''
    if not time and item.get('a') != item.get('b'):
        time = TEXT[lang]['several']
    venue = (item.get('v') or [''])[0] or ''
    cat = CATS.get(item.get('pc') or '', ('', '', ''))[ix(lang)]
    meta = ' · '.join(x for x in (cat, venue, TEXT[lang]['free'] if item.get('fr') else '') if x)
    return (f'<li><a href="{html.escape(url)}">{f"<b>{html.escape(time)}</b> " if time else ""}{html.escape(item.get("t") or "")}</a>'
            + (f' <span>{html.escape(meta)}</span>' if meta else '') + '</li>')


def listing(page, days_data):
    """La lista del HTML: por día, los actos con hora primero (como la app) y luego los de varios días."""
    lang = page.get('lang', 'es')
    parts, total, seen = [], 0, set()
    landing = page['landing']; is_art = 'arte' in (landing.get('cats') or [])
    per_day = page.get('per_day', MAX_PER_DAY)
    for d in page['days']:
        data = days_data.get(d.isoformat())
        if not data: continue
        pool = data.get('items', [])
        if any(landing.get(k) for k in ('cats', 'chans', 'free', 'district')):   # con filtro: también el resto del día
            pool = pool + data.get('_extra', [])
        items = [i for i in pool if _matches(i, landing)]
        # Exposiciones y programas largos solo en las páginas de arte; en el resto, la app los agrupa aparte.
        if not is_art: items = [i for i in items if i.get('a') == i.get('b') or i.get('kd') not in ('exhibition', 'program')]
        items = [i for i in items if (i['s'], i['i']) not in seen]
        items.sort(key=lambda i: (0 if i.get('tm') else 1, i.get('tm') or '', i.get('t') or ''))
        rows = items[:min(per_day, MAX_ROWS - total)]
        if not rows: continue
        seen.update((i['s'], i['i']) for i in rows); total += len(rows)
        heading = f'<h2>{html.escape(_cap(long_date(d, lang)))}</h2>' if len(page['days']) > 1 else ''
        parts.append(heading + '<ul>' + ''.join(_row(i, d, lang) for i in rows) + '</ul>')
        if total >= MAX_ROWS: break
    if not parts: parts.append(f'<p>{html.escape(TEXT[lang]["none"])}</p>')
    return ''.join(parts)


def with_catalog(days_data, catalog_items):
    """Añade a cada día, aparte de su primera página (las 50 mejor puntuadas, data/day), los actos del catálogo que son
    seguro de ese día: los de un solo día y las exposiciones abiertas. Los programas y cursos largos no, porque el
    catálogo no dice qué días tienen sesión. Solo se usa en las páginas con filtro (_extra)."""
    single, expos = {}, []
    for it in catalog_items:
        if it.get('a') and it.get('a') == it.get('b'): single.setdefault(it['a'], []).append(it)
        elif it.get('kd') == 'exhibition': expos.append(it)
    out = {}
    for day, data in days_data.items():
        extra = single.get(day, []) + [e for e in expos if (e.get('a') or '') <= day <= (e.get('b') or '')]
        out[day] = {**data, '_extra': extra}
    return out


def alternates(alts, base):
    """<link rel="alternate" hreflang> a las tres versiones; x-default, la castellana."""
    if not base: return ''
    links = ''.join(f'<link rel="alternate" hreflang="{l}" href="{html.escape(base + alts[l])}">' for l in LANGS)
    return links + f'<link rel="alternate" hreflang="x-default" href="{html.escape(base + alts["es"])}">'


def _lang_attrs(doc, lang, extra=''):
    attrs = extra + (f' data-lang="{lang}" data-base="{PREFIX[lang]}"' if lang != 'es' else '')
    doc = doc.replace('<html lang="es"', f'<html lang="{lang}"{attrs}', 1)
    if lang != 'es': doc = doc.replace('class="logo" href="/"', f'class="logo" href="{PREFIX[lang]}/"', 1)
    return doc


def localize_index(index, lang, site_url):
    """La portada en un idioma: lang, título, descripción, Open Graph, canonical, hreflang, data-lang y data-base
    (public.js arranca en ese idioma y con las direcciones de ese idioma)."""
    T = TEXT[lang]; base = site_url.rstrip('/') if site_url else ''
    doc = re.sub(r'<title>.*?</title>', f'<title>{html.escape(T["home_title"])}</title>', index, count=1, flags=re.S)
    doc = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{html.escape(T["home_desc"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{html.escape(T["home_title"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{html.escape(T["home_og"])}">', doc, count=1)
    doc = re.sub(r'<link rel="canonical" href="[^"]*">', '', doc)
    if base:
        doc = doc.replace('</head>', f'<link rel="canonical" href="{html.escape(base + localize("/", lang))}">'
                          + alternates({l: localize('/', l) for l in LANGS}, base) + '</head>', 1)
    return _lang_attrs(doc, lang)


def render(index, page, days_data, site_url):
    """El HTML de una página de entrada a partir de la portada ya generada (sin el bloque de la portada)."""
    lang = page.get('lang', 'es')
    base = site_url.rstrip('/') if site_url else ''
    canonical = f'{base}{page.get("canonical") or page["path"]}'
    doc = index
    doc = re.sub(r'<title>.*?</title>', f'<title>{html.escape(page["title"])}</title>', doc, count=1, flags=re.S)
    doc = re.sub(r'<meta name="description" content="[^"]*">', f'<meta name="description" content="{html.escape(page["desc"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:title" content="[^"]*">', f'<meta property="og:title" content="{html.escape(page["title"])}">', doc, count=1)
    doc = re.sub(r'<meta property="og:description" content="[^"]*">', f'<meta property="og:description" content="{html.escape(page["desc"])}">', doc, count=1)
    doc = re.sub(r'<link rel="canonical" href="[^"]*">', '', doc)
    doc = re.sub(r'<link rel="alternate" hreflang="[^"]*" href="[^"]*">', '', doc)
    if base:
        doc = doc.replace('</head>', f'<link rel="canonical" href="{html.escape(canonical)}"><meta property="og:url" content="{html.escape(canonical)}">'
                          + alternates(page.get('alts') or {l: page['path'] for l in LANGS}, base) + '</head>', 1)
    landing = json.dumps(page['landing'], ensure_ascii=False, separators=(',', ':'))
    doc = _lang_attrs(doc, lang, f" data-landing='{html.escape(landing, quote=False).replace(chr(39), '&#39;')}'")
    rows = page['rows_html'] if 'rows_html' in page else listing(page, days_data)
    # Sin ningún acto (1-11-2026): fuera del índice, pero se siguen sus enlaces. Una sala, con menos de VENUE_MIN.
    thin = page.get('count', 99) < VENUE_MIN if 'rows_html' in page else '<li>' not in rows
    if thin: doc = doc.replace('</head>', '<meta name="robots" content="noindex,follow"></head>', 1)
    if page.get('jsonld'): doc = doc.replace('</head>', '<script type="application/ld+json">' + json.dumps(page['jsonld'], ensure_ascii=False).replace('<', '\\u003c') + '</script></head>', 1)
    block = (f'<section id="seoLista" class="seo-lista" lang="{lang}"><h1>{html.escape(page["h1"])}</h1><p>{html.escape(page["lead"])}</p>'
             + rows + nav_html(skip=page['path'], lang=lang)
             + f'<p class="seo-lista-more"><a href="{PREFIX[lang]}/">{html.escape(TEXT[lang]["more"])}</a></p></section>')
    return doc.replace('<main>', '<main>' + block, 1)


def home_block(today, days_data, lang='es'):
    """La portada para buscadores (1-11-2026): los planes de hoy en HTML y los enlaces a todas las páginas de entrada.
    Sin h1 (el de la portada ya está en la cabecera). La app lo retira al pintar su agenda, como en las demás."""
    page = {'path': localize('/', lang), 'lang': lang, 'landing': {}, 'days': [today], 'h1': '', 'lead': ''}
    return (f'<section id="seoLista" class="seo-lista" lang="{lang}">'
            f'<h2>{html.escape(TEXT[lang]["home_h"].format(date=long_date(today, lang)))}</h2>' + listing(page, days_data)
            + nav_html(skip=localize('/', lang), lang=lang, today=today) + '</section>')


def file_for(path):
    """/hoy → hoy.html, /con-ninos/hoy → con-ninos/hoy.html, /ca/ → ca/index.html (Pages las sirve sin .html)."""
    p = path.strip('/')
    if not p: return 'index.html'
    return (p + '/index.html') if p in ('ca', 'en') else p + '.html'


def write_all(out, index, days_data, site_url, today, catalog_items=None):
    """Escribe las tres portadas (/, /ca/, /en/) con su bloque para buscadores y todas las páginas de entrada.
    La usan la publicación completa y las rápidas. Devuelve las rutas escritas (para el sitemap)."""
    from pathlib import Path
    out = Path(out); paths = []
    if catalog_items: days_data = with_catalog(days_data, catalog_items)
    for lang in LANGS:
        doc = localize_index(index, lang, site_url)
        doc = doc.replace('</main>', home_block(today, days_data, lang) + '</main>', 1) if '</main>' in doc else doc
        target = out / file_for(localize('/', lang)); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding='utf-8')
        if lang != 'es': paths.append(localize('/', lang))
    for page in all_pages(today):
        target = out / file_for(page['path']); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(index, page, days_data, site_url), encoding='utf-8')
        paths.append(page['path'])
    for page in venue_pages(today, catalog_items or [], out / 'data' / 'detail'):   # piloto de salas (1-11-2026)
        target = out / file_for(page['path']); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(index, page, days_data, site_url), encoding='utf-8')
        paths.append(page['path'])
    (out / '404.html').write_text(not_found(index, today), encoding='utf-8')
    return paths


def not_found(index, today):
    """404.html (1-11-2026, SEO): sin ella, Cloudflare Pages servía la portada con 200 en cualquier dirección que no
    existe (días ya pasados, páginas retiradas): «404 falsos» para Google. Con ella, responde 404, fuera del índice,
    con la app (la agenda de hoy) y los enlaces a las páginas de entrada."""
    doc = re.sub(r'<title>.*?</title>', '<title>Página no encontrada · Ontoca</title>', index, count=1, flags=re.S)
    doc = re.sub(r'<link rel="canonical" href="[^"]*">', '', doc)
    doc = re.sub(r'<link rel="alternate" hreflang="[^"]*" href="[^"]*">', '', doc)
    doc = doc.replace('</head>', '<meta name="robots" content="noindex"></head>', 1)
    block = ('<section id="seoLista" class="seo-lista" lang="es"><h1>Esta página ya no existe</h1>'
             '<p>Puede que fuera la agenda de un día que ya pasó o un acto que ya no está publicado. Aquí tienes los planes de ahora.</p>'
             + nav_html(lang='es', today=today) + '<p class="seo-lista-more"><a href="/">Ver toda la agenda de Barcelona</a></p></section>')
    return doc.replace('<main>', '<main>' + block, 1)
