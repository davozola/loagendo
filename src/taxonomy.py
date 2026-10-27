"""Clasificación pública de Loagendo: 8 categorías y 5 canales (19-10-2026).

Una ficha tiene una sola categoría (su naturaleza) y puede estar en varios canales
(colecciones para descubrir). Todo se decide con reglas sobre metadatos de la fuente;
cada decisión guarda su método y su evidencia. Lo que no tiene señal suficiente queda
«pendiente» (no se publica y va a la cola de revisión): nunca se inventa una categoría.

Orden de las señales (de más a menos fiable):
  1. Corrección editorial (tabla classification_overrides): manda siempre.
  2. Formato estructural: una exposición es «Arte y exposiciones».
  3. Género con que empieza el título o una de sus partes («Concert …», «Cicle X: Xerrada …»):
     las fuentes municipales titulan así, el género va delante.
  4. Categoría que declara la fuente (o el tipo de sala: una sala de conciertos).
  5. Palabras de género dentro del título, solo si apuntan a una única categoría.
Si las señales fuertes se contradicen, gana la más fiable y la ficha se marca «ambigua»
para el informe (sigue publicada).
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata

CATEGORIES = {
    'musica': ('Música y conciertos', 'Música i concerts'),
    'escena': ('Teatro y danza', 'Teatre i dansa'),
    'cine': ('Cine', 'Cinema'),
    'arte': ('Arte y exposiciones', 'Art i exposicions'),
    'charlas': ('Charlas y visitas', 'Xerrades i visites'),
    'talleres': ('Talleres y experiencias', 'Tallers i experiències'),
    'fiestas': ('Fiestas y mercados', 'Festes i mercats'),
    'deporte': ('Deporte', 'Esport'),
}
CHANNELS = {
    'familia': ('En familia', 'En família'),
    'barrio': ('Vida de barrio', 'Vida de barri'),
    'aire': ('Al aire libre', "A l'aire lliure"),
    'galerias': ('Arte y galerías', 'Art i galeries'),
    'festivales': ('Festivales y fiestas', 'Festivals i festes'),
}
PENDING = 'pendiente'
# Fuera de la agenda cultural por decisión editorial (20-10-2026): no se publica ni va a la cola
# de revisión; el registro se conserva y una corrección editorial puede devolverlo.
EXCLUDED = 'excluida'
# Enlaces y parámetros antiguos (cat=Conciertos, kids=1…) siguen funcionando.
LEGACY_CATEGORY = {'Conciertos': 'musica', 'Música': 'musica', 'Teatro': 'escena', 'Cine': 'cine', 'Exposiciones': 'arte',
                   'Talleres': 'talleres', 'Deporte': 'deporte'}
LEGACY_CHANNEL = {'Familia': 'familia', 'Barrio': 'barrio'}


def legacy_filter(category='', channel=''):
    """(categoría, canal) a partir de un filtro nuevo o antiguo. Valores desconocidos → ValueError."""
    category = category or ''; channel = channel or ''
    if category in LEGACY_CHANNEL and not channel: category, channel = '', LEGACY_CHANNEL[category]
    category = LEGACY_CATEGORY.get(category, category)
    if category and category not in CATEGORIES: raise ValueError('Categoría no válida')
    if channel and channel not in CHANNELS: raise ValueError('Canal no válido')
    return category, channel


def norm(text):
    text = unicodedata.normalize('NFKD', str(text or '').replace('·', '.').replace("’", "'")).encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.sub(r"[^a-z0-9':/\-]+", ' ', text).split())


# Género al principio del título (o de una de sus partes tras «:» o « - »).
LEAD = [
    ('cine', r"cinema|cine|cineforum|cinefòrum|cineclub|projeccio|projeccions|proyeccion|curtmetratges?|cortometrajes?|documental|pel.licula|pelicula|film|sessio de cinema|filmoteca"),
    ('arte', r"exposicio|exposicion|exposicions|exposiciones|inauguracio|inauguracion|vernissage|finissage|instal.lacio|instalacion|videoart|performance|mostra d'art|mostra fotografica|art urba"),
    ('musica', r"presentacio (?:del? )?(?:lp|ep|disc|nou disc|album|l'album)|presentacion (?:del? )?(?:lp|ep|disco|album)|concert|concerts|concierto|conciertos|recital musical|recital de (?:piano|guitarra|cant|violi)|jam session|jam|dj set|dj|audicio|audicion|cantada|havaneres|opera concert|coral|orquestra|orquesta|vermut musical"),
    ('escena', r"espectacle|espectaculo|espectacles|teatre|teatro|dansa|danza|ballet|circ|circo|titelles|titeres|marionetes|opera|sarsuela|zarzuela|musical|monoleg|monologo|stand.up|comedia|cabaret|clown|magia|mag |impro|improvisacio|contacontes|cuentacuentos|conte|contes|sessio de contes|sessio de conte|marato de contes|narracio|hora del conte|lectura dramatitzada"),
    ('charlas', r"cafes? literaris?|cafe literari|xerrada|xerrades|charla|charlas|conferencia|conferencies|conferencias|debat|debate|col.loqui|coloquio|taula rodona|mesa redonda|presentacio|presentacion|club de lectura|tertulia|seminari|seminario|jornada|jornades|jornadas|simposi|congres|visita|visites|visitas|itinerari|itinerario|ruta|rutes|passejada|paseo|sortida|sortides|excursio|recorregut|tour|conversa|conversacio|dialeg|dialogo|entrevista|sessio informativa|lectura poetica|recital de poesia|poesia|podcast|trobada amb l'autor|tast literari|marato de lectura|lectura compartida"),
    ('talleres', r"torneig de (?:magic|escacs|jocs?|videojocs|cartes|rol)|torneo de (?:magic|ajedrez|juegos?|videojuegos|cartas)|taller|tallers|workshop|grup de conversa|grup obert|coaching|tastet|capsula|capsules|capsules formatives|pindola|pindoles|grup d'aprenentatge|aula oberta|sessio formativa|formacio|passatge del terror|tunel del terror|scape room|curs|curso|cursos|classe|clase|classes|masterclass|laboratori|laboratorio|bibliolab|tast|cata|degustacio|degustacion|escape room|gimcana|gincana|yincana|joc|jocs|juego|juegos|activitat familiar|activitat infantil|espai familiar|espai de joc|scape|hackato|hackaton|maker"),
    ('fiestas', r"festa|festes|fiesta|fiestas|fira|fires|feria|ferias|mercat|mercats|mercado|mercadillo|market|flea market|pop.up|castanyada|correfoc|cercavila|revetlla|carnaval|cavalcada|sardanes|sardana|ball de|gegants|castellers|diada|aplec|cagatio|tio|celebracio|celebracion|setmana gastronomica|shopping|vermut popular|calcotada"),
    ('deporte', r"cursa|carrera popular|carrera|marato(?! de (?:contes|lectura|poesia))|maraton(?! de (?:cuentos|lectura|poesia))|mitja marato|torneig|torneo|partit|partido|campionat|campeonato|triatlo|triatlon|bicicletada|caminada popular|futbol|basquet|handbol|waterpolo|regata|esport|deporte"),
]
LEAD_RE = [(cat, re.compile(r"^(?:" + pat + r")\b")) for cat, pat in LEAD]
# Palabras que no dicen el género: se saltan al buscar el género del principio.
SKIP_LEAD = re.compile(r"^(?:\d+[a-z]*\s+|(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xx|xxi|xxv)+\s+|nou |nova |gran |petit |mini |(?:la|el|les|els|l'|un|una|the) |activitat (?:adults|joves|infantil) - |(?:t'interessa|btj|nou!?|novetat|estrena|special|especial):?\s+)+")
PROGRAM_LEAD = re.compile(r"^(?:cicle|ciclo|festival|fest|mostra|muestra|temporada|programa|programacio|projecte|proyecto|jornades|semana|setmana|any|mes|dia|nit|tots sants|nadal|tardor|primavera|estiu|hivern)\b")

INNER = {
    'cine': r"\b(?:cinema|cine|cineforum|pel.licula|pelicula|curtmetratge|documental|film)\b",
    'arte': r"\b(?:exposicio|exposicion|inauguracio|instal.lacio|fotografi(?:a|c)|pintura|escultura|art contemporani|arts visuals|il.lustracio)\b",
    'musica': r"\b(?:concert|concierto|musica|canciones|cancons|jazz|rock|flamenc|flamenco|electronica|dj|orquestra|coral|piano|guitarra|hip hop|techno|house|indie|blues|soul|reggae|cumbia|salsa|bossa)\b",
    'escena': r"\b(?:teatre|teatro|dansa|danza|circ|circo|titelles|opera|monoleg|comedia|comedy|stand.?up|open mic|improv|espectacle|espectaculo|contacontes|musical)\b",
    'charlas': r"\b(?:xerrada|conferencia|debat|debate|presentacio|literatura|llibre|libro|poesia|lectura|book club|walking tour|visita|itinerari|ruta|patrimoni|historia|ciencia|divulgacio|talks?|simposi|simposio|symposium|cicle tematic)\b",
    'talleres': r"\b(?:taller|workshop|curs|curso|tast|cata|manualitats|cuina|cocina)\b",
    'fiestas': r"\b(?:festa|fiesta|fira|feria|mercat|mercado|market|castanyada|festa major|cultura popular|nadal|carnaval)\b",
    'deporte': r"\b(?:cursa|carrera|marato|torneig|torneo|esport|deporte|futbol|basquet|triatlo)\b",
}
INNER_RE = {cat: re.compile(pat) for cat, pat in INNER.items()}

# Eventbrite: formato y categoría que declara el organizador.
EVENTBRITE_FORMAT = {'class': 'talleres', 'workshop': 'talleres', 'training': 'talleres', 'conference': 'charlas', 'seminar': 'charlas',
                     'talk': 'charlas', 'tour': 'charlas', 'screening': 'cine', 'festival': None, 'fair': 'fiestas', 'expo': 'fiestas',
                     'race': 'deporte', 'endurance': 'deporte', 'tournament': 'deporte', 'game': 'talleres', 'attraction': 'talleres',
                     'concert': 'musica', 'performance': 'escena', 'gala': None, 'party': None, 'networking': None, 'meetup': None}
EVENTBRITE_CATEGORY = {'music': 'musica', 'film & media': 'cine', 'film, media & entertainment': 'cine', 'performing & visual arts': 'escena',
                       'sports & fitness': 'deporte', 'food & drink': 'talleres', 'science & technology': 'charlas'}
# Fuentes cuya categoría es la del recinto, no la del acto (auditoría 26-10-2026): todas sus fichas vigentes llevan la
# misma (Palau 351 «Música», Liceu, Jamboree, Apolo, Teatre Lliure «Artes escénicas»…). Las agendas de sala leídas con IA
# (venue_ia_*) toman la categoría del tipo de sala de config/agendas_ia.json, así que también lo son. Medido con
# event_classification + listing_projections (fuentes con ≥10 fichas y una sola categoría).
# También los agregadores de un solo género (conciertos.club, Songkick, Xceed: «Música» para todo, «Mamma mia» incluido).
RECINTO_SOURCES = {'web_conciertos_club', 'venue_songkick', 'venue_xceed', 'venue_heliogabal', 'venue_jamboree', 'venue_liceu', 'venue_mira_festival', 'venue_mozilla_festival', 'venue_palau_musica',
                   'venue_sala_apolo', 'venue_sala_vol', 'venue_sidecar', 'venue_teatre_poliorama', 'web_auditori', 'web_teatre_lliure'}


def recinto_source(source):
    return str(source or '').startswith('venue_ia_') or source in RECINTO_SOURCES


# Fuentes que son salas de cine: todo lo que publican es Cine, diga lo que diga el título
# («Escape Room 2» es una película). Decisión de David, 26-10-2026: «Espai Texas es un cine».
CINEMA_SOURCES = {'venue_ia_espai_texas'}
STAGE_AT_CINEMA = re.compile(r"(?i)\bl'espectacle\b|\bal teatre\b|\buna obra (?:de teatre|sobre)\b")
PROFESSIONAL_EVENTBRITE = {'business', 'science tech', 'science technology'}
TICKET_PRODUCT_DAYS = 60


def _span_days(ev):
    import datetime as _dt
    try: return (_dt.date.fromisoformat(str(ev.get('end'))[:10]) - _dt.date.fromisoformat(str(ev.get('start'))[:10])).days
    except ValueError: return 0


SOURCE_DEFAULT = {'venue_xceed': 'musica', 'venue_songkick': 'musica', 'web_conciertos_club': 'musica', 'venue_dice': 'musica'}
VENUE_GENRE = [('escena', re.compile(r"^(?:teatre|teatro)\b|\b(?:sala beckett|mercat de les flors|tnc|teatre nacional|gran teatre del liceu)\b")),
               ('cine', re.compile(r"\b(?:filmoteca|cinemes|cines|cinema (?!a la fresca))"))]
# Decisiones editoriales del 20-10-2026 (David):
#  - «Patis escolars oberts»: patios abiertos para jugar → Talleres y experiencias, canal En familia.
#  - Servicios y convocatorias: fuera de la agenda.
#  - Ocio social de ticketera (citas, intercambios, pub crawls, networking, empleo, congresos): fuera.
#  - Comunidad y cuidados (grupos de barrio, «El barri proposa», «Ens cuidem»): Talleres + Vida de barrio.
# Productos de ticketera que no son un acto (mejoras de entrada, aparcamiento, paquetes VIP).
TICKET_PRODUCT = re.compile(r"^(?:upgrade|vip package|paquete vip|parking|aparcament|aparcamiento|meet ?& ?greet)\b")
# Resúmenes y noticias de programación de la red de centres cívics (no son una actividad con fecha).
UMBRELLA_VENUE = re.compile(r"^(?:xarxa de centres civics|diversos centres civics|centres civics)\b")
PATIS = re.compile(r"\bpatis? escolars? oberts?\b")
TRADE_FAIR = re.compile(r"\b(?:wedding market|bridal|fira nupcial|salo nupcial|salon nupcial|feria de bodas|textile expo|real estate expo)\b")
SOCIAL = re.compile(r"\b(?:singles|single (?:night|party)|dating|citas|first dates|speed ?dating|language exchange|intercambio de idiomas|intercanvi d'idiomes|pub crawl|party tour|boat party|bar crawl|"
                    r"networking|meet people|new friends|nuevos amigos|afterwork|job fair|feria de empleo|employer|hackathon|womenhack|summit|congress|congres (?:mundial|internacional)|congreso (?:mundial|internacional)|"
                    r"conference|forum event|venture capital|real estate|inversion inmobiliaria|investment|pub quiz|trivia|casino barcelona|expansion playbook|evento anual)\b")
COMMUNITY = re.compile(r"(?:\bel barri proposa\b|\bens cuidem\b|\bgrup de cura\b|\bcura comunitaria\b|\bgrup (?:comunitari|de dones|de teixidores|obert)|"
                       r"\bactivitat comunitaria\b|\bespai de participacio\b|\btrobada 'repara)")
# Grupos de apoyo y cuidados (20-10-2026): son un servicio para quien lo necesita, no un plan de agenda.
SUPPORT = re.compile(r"(?:\bgrup (?:virtual )?de suport\b|\bgrupo de apoyo\b|\bgrup d'insomni\b|"
                     r"\bacompanyament al dol\b|\bespai de (?:pausa|cura|acompanyament)\b|\bdemencia\b|\balzheimer\b|\bpersones cuidadores\b)")
# Series de fichas casi iguales que la web agrupa en una sola fila (cada ficha se conserva entera).
SERIES = [("patis-escolars-oberts", PATIS)]


def series_of(title):
    t = norm(title)
    return next((key for key, rx in SERIES if rx.search(t)), '')
SERVICE = re.compile(r"\b(?:activitats laborals|busques feina|kit emprenedor|acces a l'habitatge|estudis a l'estranger|botiga solidaria|cibernarium|campanya|donacio de sang|taula informativa|canvi oficial d'horari|dispositiu de proves|servei punt tic|punt tic|servei d'|inscripcions? obertes|convocatoria|oberta la convocatoria|campanya de recollida|recollida solidaria|borsa de)\b")

SCHOOL_SUPPORT = re.compile(r"\b(?:reforc (?:educatiu|escolar)|refuerzo (?:educativo|escolar)|classes de repas|clases de repaso)\b")

# «Octubre al Marula Café», «Octubre a la Sala Apolo»… (Generalitat): la programación del mes de una sala,
# no un acto. Sus conciertos ya llegan uno a uno (DICE, Songkick, la propia sala) y la ficha del mes los
# duplicaba todos los días (David, 26-10-2026). Medido ese día: 23 fichas, todas con actos propios.
VENUE_MONTH = re.compile(r"^(?:gener|febrer|marc|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre|enero|febrero|marzo|mayo|junio|julio|septiembre|noviembre|diciembre) (?:al|als|a la|a l'|a) ")

SOURCE_CATEGORY = {
    'Música y vida nocturna': 'musica', 'Artes escénicas': 'escena', 'Cine y audiovisual': 'cine',
    'Arte y exposiciones': 'arte', 'Ciencia y divulgación': 'charlas', 'Literatura y palabra': 'charlas',
    'Patrimonio y rutas': 'charlas', 'Talleres y experiencias': 'talleres', 'Gastronomía': 'talleres',
    'Cultura popular y fiestas': 'fiestas', 'Ferias y mercados': 'fiestas', 'Deporte': 'deporte',
    # «Comunidad y encuentros» es el cajón por defecto de category_of: no es una señal.
}
OFFICIAL_TYPE = [  # Tipologia oficial (Open Data / GuiaBCN): tipo de actividad
    ('musica', re.compile(r"(?:tipologia ag|tipologies) >> concerts$")),
    ('talleres', re.compile(r"(?:tipologia ag|tipologies) >> cursos i tallers$")),
    ('arte', re.compile(r"(?:tipologia ag|tipologies) >> exposicions$")),
]


def segments(title):
    """El título entero y cada parte tras «:», «!», « - » o comillas de programa:
    «Tots Sants 2026: Castanyada a …», «Cicle 'Afins': Xerrada …», «Castanyada a la plaça! Espectacle …»."""
    t = norm(re.sub(r'!\s+', ': ', title or ''))
    parts = [t] + [p.strip(" '\"") for p in re.split(r":\s+|\s+-\s+|\s+–\s+", t)[1:]]
    out = []
    for p in parts:
        p = SKIP_LEAD.sub('', p.strip(" '\"«»")).strip(" '\"«»")
        if p and p not in out: out.append(p)
    return out


FIESTA_FRAME = re.compile(r"^(?:festa major|festes|fiestas? mayor|festa de barri|festes de|castanyada|castanada)\b")


def lead_category(title):
    """(categoría, palabra) del género con que empieza el título o alguna de sus partes.
    «Festa Major de X: Concert …» es un concierto dentro de la fiesta: manda la parte con género."""
    found = []
    for i, part in enumerate(segments(title)):
        for cat, rx in LEAD_RE:
            m = rx.match(part)
            if m: found.append((i, cat, m.group(0), part)); break
    if not found: return None, ''
    i, cat, word, part = found[0]
    if cat == 'fiestas' and FIESTA_FRAME.match(part):
        later = next((f for f in found[1:] if f[0] > i and f[1] != 'fiestas'), None)
        if later: return later[1], later[2]
    return cat, word


def inner_categories(title):
    t = norm(title)
    return sorted({cat for cat, rx in INNER_RE.items() if rx.search(t)})


def classify(ev, override=None, ai=None):
    """Reglas + (si la hay) la sugerencia de IA vigente. La IA solo decide cuando las reglas no son
    seguras (pendiente, ambigua o solo «probable») y su confianza es alta; nunca contra una
    corrección editorial ni contra una regla fuerte sin conflicto. Devuelve también el veredicto
    de las reglas (``rule_status``, ``rule_ambiguous``) para saber qué mandar a la IA."""
    rules = _classify_rules(ev, override)
    out = {**rules, 'rule_status': rules['status'], 'rule_ambiguous': rules['ambiguous'], 'ai_disagrees': ''}
    if not ai or rules['status'] == 'editorial': return out
    from src.ai_assist import APPLY_CATEGORY
    answer = ai.get('answer')
    if ai.get('confidence', 0) < APPLY_CATEGORY or answer == PENDING or (answer not in CATEGORIES and answer != EXCLUDED): return out
    # Medido el 20-10-2026 (scripts/evaluar_ia.py, 310 fichas): reglas 98,7 %, IA 92,6 %; en los casos
    # dudosos, reglas 95 % e IA 84 %. La IA solo decide donde las reglas no dan categoría (pendientes);
    # en el resto, si discrepa con confianza alta, se señala para revisión y manda la regla.
    # Categoría que solo es la del recinto (26-10-2026): la IA la corrige si, además de su confianza, lo respalda algo del
    # propio acto: otra señal de las reglas (título, tipo de sala, cartel, subtítulo de la página) o el género que nombra
    # el principio de su descripción. Validado contra la muestra etiquetada: la IA sola con confianza ≥ 0,85 acierta el
    # 94 %, y falla justo donde no hay nada más («Mañana musical para embarazadas» → taller). Nunca excluye por esta vía.
    if rules['method'] == 'categoria_recinto' and answer in CATEGORIES and answer != rules['category']:
        backed = answer in rules.get('other_categories', []) or answer in inner_categories(str(ev.get('description') or ev.get('source_text') or '')[:400])
        if backed:
            return {**out, 'category': answer, 'status': 'probable', 'method': 'ia_con_senal',
                    'evidence': f"IA ({ai.get('model', '')}, confianza {ai.get('confidence', 0):.2f}): {ai.get('reason', '')}. Respaldo: señal propia del acto. Reglas: {rules['evidence']}",
                    'ambiguous': False}
    if rules['status'] != 'pendiente':
        if answer != rules['category'] and rules['status'] != 'excluida':
            out['ai_disagrees'] = f"{answer} ({ai.get('confidence', 0):.2f}): {ai.get('reason', '')}"
        return out
    return {**out, 'category': answer, 'status': 'excluida' if answer == EXCLUDED else 'ia', 'method': 'ia',
            'evidence': f"IA ({ai.get('model', '')}, confianza {ai.get('confidence', 0):.2f}): {ai.get('reason', '')}. Reglas: {rules['evidence']}",
            'ambiguous': False}


def page_subtitle_category(ev):
    """(categoría, palabra, línea) del género con que empieza una de las tres líneas cortas que siguen al
    título en la página oficial del acto (texto que catalog añade tras «[Web oficial del acto]»)."""
    text = str(ev.get('source_text') or '')
    if '[Web oficial del acto]' not in text: return None, '', ''
    words = set(norm(ev.get('title')).split())
    lines = [l.strip() for l in text.split('[Web oficial del acto]', 1)[1].split('\n') if l.strip()]
    for line in lines[:4]:
        if len(line) > 90 or (words and set(norm(line).split()) <= words): continue
        cat, word = lead_category(line)
        if cat: return cat, word, line
    return None, '', ''


def _classify_rules(ev, override=None):
    """→ dict(category, status, method, evidence, ambiguous).

    status: 'editorial' | 'confirmada' | 'probable' | 'pendiente'."""
    if override and override.get('category') == EXCLUDED:
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'correccion_editorial',
                'evidence': override.get('note') or 'Excluida por corrección editorial', 'ambiguous': False}
    if override and override.get('category') in CATEGORIES:
        return {'category': override['category'], 'status': 'editorial', 'method': 'correccion_editorial',
                'evidence': override.get('note') or 'Corrección editorial', 'ambiguous': False}
    # …salvo cuando la propia sala dice que es teatro (27-10-2026: Espai Texas también tiene escenario; «compra les
    # teves entrades per l'espectacle AUTÓNOMOS EL MUSICAL al teatre de l'Espai Texas», «Rita, una obra sobre…»).
    if ev.get('source') in CINEMA_SOURCES and not STAGE_AT_CINEMA.search(str(ev.get('description') or ev.get('source_text') or '')[:600]):
        return {'category': 'cine', 'status': 'confirmada', 'method': 'sala_de_cine',
                'evidence': 'La fuente es una sala de cine (decisión editorial 26-10-2026)', 'ambiguous': False}
    title = ev.get('title') or ''
    source_cat = SOURCE_CATEGORY.get(ev.get('category') or '')
    lead, word = lead_category(title)
    official = next((cat for cat, rx in OFFICIAL_TYPE for p in ev.get('classification_paths') or [] if rx.search(norm(p))), None)
    signals = []
    # Una visita o un taller dentro de una exposición es esa actividad, no la exposición.
    activity_in_expo = lead in ('charlas', 'talleres') and re.match(r"(?:visita|visites|taller|tallers|itinerari)", word or '')
    if activity_in_expo:
        signals.append((lead, 'genero_titulo', f'El título empieza por «{word}»'))
    if ev.get('kind') == 'exhibition' or ev.get('format') == 'exhibition':
        signals.append(('arte', 'formato_exposicion', 'La fuente la publica como exposición'))
    if lead and not activity_in_expo:
        signals.append((lead, 'genero_titulo', f'El título empieza por «{word}»'))
    if ev.get('format') in ('workshop', 'course'):
        signals.append(('talleres', 'formato_taller', 'La fuente la publica como taller o curso'))
    if official:
        signals.append((official, 'tipologia_oficial', 'Tipología oficial de Open Data / GuiaBCN'))
    if source_cat:
        signals.append((source_cat, 'categoria_fuente', f'Categoría de la fuente: {ev.get("category")}'))
    fmt = norm(ev.get('hint_format')); gen = norm(ev.get('hint_category'))
    eb = next((v for k, v in EVENTBRITE_FORMAT.items() if v and k in fmt), None) or next((v for k, v in EVENTBRITE_CATEGORY.items() if k == gen), None)
    if eb: signals.append((eb, 'tipo_organizador', f'Tipo declarado en la ticketera: {ev.get("hint_format") or ev.get("hint_category")}'))
    if ev.get('lineup') and not source_cat:
        signals.append(('musica', 'cartel', 'Tiene cartel de artistas'))
    venue = norm(' '.join(ev.get('venue_names') or []))
    vg = next((cat for cat, rx in VENUE_GENRE if rx.search(venue)), None)
    if vg: signals.append((vg, 'tipo_de_sala', f'Se celebra en {(ev.get("venue_names") or [""])[0]}'))
    if ev.get('source') in SOURCE_DEFAULT and not source_cat:
        signals.append((SOURCE_DEFAULT[ev['source']], 'fuente_musical', 'Fuente de conciertos y clubs'))
    inner = inner_categories(title)
    if len(inner) == 1:
        signals.append((inner[0], 'palabra_titulo', 'El título menciona el género'))
    t = norm(title)
    if TICKET_PRODUCT.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'producto_de_ticketera',
                'evidence': 'Mejora de entrada o producto de la ticketera, no un acto', 'ambiguous': False}
    # Eventbrite (auditoría 27-10-2026): la categoría que declara el propio organizador separa la formación y los
    # encuentros profesionales («Business», «Science & Tech»: CEO's Night, conferencias de desarrolladores) del ocio
    # cultural. Es la decisión editorial del 20-10-2026 (ocio profesional, congresos: fuera) con el dato de la fuente.
    # Una fiesta, función o festival con esa categoría (una noche de arte y música en el Palau Dalmases) no se excluye
    # por ella: sigue las reglas de siempre.
    if ev.get('source') == 'venue_eventbrite' and gen in PROFESSIONAL_EVENTBRITE and not override and not any(k in fmt for k in ('party', 'performance', 'festival', 'concert', 'screening')):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'ocio_social_o_profesional',
                'evidence': f'Categoría declarada en Eventbrite: {ev.get("hint_category")} (formación o encuentro profesional; decisión editorial 20-10-2026)', 'ambiguous': False}
    # Lo que Eventbrite vende todo el año con una sola ficha (visita guiada al Park Güell, clase de paella del
    # 14-12-2025 al 15-12-2026) es un producto turístico, no un acto con fecha.
    if ev.get('source') == 'venue_eventbrite' and _span_days(ev) > TICKET_PRODUCT_DAYS:
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'producto_de_ticketera',
                'evidence': f'Producto que la ticketera vende todo el año ({ev.get("start")} → {ev.get("end")}), no un acto con fecha', 'ambiguous': False}
    # La web de centres cívics mezcla noticias con actividades: sin género ni fecha propia es una noticia.
    # Y en esa web, lo que va a nombre de la red entera («Xarxa de Centres Cívics», «Diversos centres
    # cívics») es siempre un artículo de recopilación («10 visites i itineraris…», «5 tallers per…»,
    # «Inscripcions als tallers de tardor»), aunque el título nombre un género (23-10-2026).
    umbrella = UMBRELLA_VENUE.search(norm(' '.join(ev.get('venue_names') or [])))
    if (not signals and (ev.get('source') == 'web_centres_civics' or umbrella)) or (ev.get('source') == 'web_centres_civics' and umbrella):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'resumen_de_programa',
                'evidence': 'Noticia o resumen de programación de la red de centres cívics, no una actividad', 'ambiguous': False}
    if ev.get('source') == 'generalitat' and VENUE_MONTH.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'resumen_de_programa',
                'evidence': 'Programación del mes de una sala: sus actos ya salen uno a uno (decisión 26-10-2026)', 'ambiguous': False}
    if PATIS.search(t):
        return {'category': 'talleres', 'status': 'confirmada', 'method': 'regla_editorial',
                'evidence': 'Patio escolar abierto para jugar en familia (decisión editorial 20-10-2026)', 'ambiguous': False}
    if TRADE_FAIR.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'feria_comercial',
                'evidence': 'Feria comercial del sector (bodas, textil, inmobiliaria…): fuera de la agenda cultural', 'ambiguous': False}
    if not lead and not inner_categories(title) and SOCIAL.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'ocio_social_o_profesional',
                'evidence': 'Ocio social, networking, empleo o congreso: fuera de la agenda cultural (decisión editorial 20-10-2026)', 'ambiguous': False}
    # Refuerzo escolar: servicio educativo aunque el título empiece por «classes» (David, 26-10-2026).
    if SCHOOL_SUPPORT.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'servicio_o_convocatoria',
                'evidence': 'Clases de refuerzo escolar: un servicio, no un plan de agenda (decisión 26-10-2026)', 'ambiguous': False}
    if SERVICE.search(t) and not (lead and lead in ('talleres', 'charlas', 'musica', 'escena', 'cine')):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'servicio_o_convocatoria',
                'evidence': 'Servicio, campaña o convocatoria, no una actividad programada (decisión editorial 20-10-2026)', 'ambiguous': False}
    if SUPPORT.search(t) and not (lead and lead in ('musica', 'escena', 'cine', 'arte')):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'grupo_de_apoyo',
                'evidence': 'Grupo de apoyo o de cuidados: un servicio, no un plan de agenda (decisión 20-10-2026)', 'ambiguous': False}
    if not lead and COMMUNITY.search(t):
        return {'category': 'talleres', 'status': 'probable', 'method': 'comunidad_y_cuidados',
                'evidence': 'Grupo o espacio comunitario del barrio (decisión editorial 20-10-2026)', 'ambiguous': False}
    if not signals:
        # Sin señal en el título: el subtítulo con que la página propia del acto lo presenta, justo debajo
        # del título («Concert familiar amb Ayako Okubo», «Taller d'arts plàstiques»), 24-10-2026. Solo las
        # líneas cortas que siguen al título en la página; queda como «probable» (la IA puede discrepar).
        cat, word, line = page_subtitle_category(ev)
        if cat: signals.append((cat, 'subtitulo_pagina', f'La página del acto lo presenta como «{line}»'))
    if not signals:
        return {'category': PENDING, 'status': 'pendiente', 'method': 'sin_senal',
                'evidence': 'Ni formato, ni género en el título, ni categoría de la fuente', 'ambiguous': False}
    first = signals[0]
    strong = {s[0] for s in signals if s[1] in ('formato_exposicion', 'genero_titulo', 'formato_taller', 'tipologia_oficial')}
    status = 'confirmada' if first[1] in ('formato_exposicion', 'genero_titulo', 'formato_taller') else 'probable'
    # Exposición + taller en el mismo registro, o género del título contra categoría de la fuente.
    ambiguous = len(strong) > 1 or (first[1] == 'genero_titulo' and source_cat and source_cat != first[0]
                                    and {first[0], source_cat} not in ({'charlas', 'talleres'}, {'escena', 'talleres'}))
    others = '; '.join(f'{CATEGORIES[c][0]} ({m})' for c, m, _ in signals[1:] if c != first[0])
    method, evidence = first[1], first[2]
    if method == 'categoria_fuente' and recinto_source(ev.get('source')):
        method, evidence = 'categoria_recinto', f'Categoría del recinto (la fuente la pone a todos sus actos): {ev.get("category")}'
    return {'category': first[0], 'status': status, 'method': method,
            'evidence': evidence + (f'. Otras señales: {others}' if others else ''), 'ambiguous': bool(ambiguous),
            'other_categories': sorted({c for c, _, _ in signals[1:] if c != first[0]})}


# ---------- canales ----------
BARRIO_VENUE = re.compile(r"\b(?:centre civic|centro civico|casal de barri|casal de gent gran|casal|ateneu|biblioteca|espai veinal|associacio de veins|asociacion de vecinos|casa de la barceloneta|centre cultural|cc )\b")
NEIGHBOUR_VENUE = re.compile(r"\b(?:casal de barri|casal comunitari|ateneu popular|ateneu (?:de|del) barri|associacio de veins|associacio veinal|asociacion de vecinos|espai veinal|centre social|casal popular)\b")
BARRIO_TITLE = re.compile(r"\b(?:festa major|festes majors|fiesta mayor|fiestas mayores|festa de barri|festes de barri|festes del barri|festes de (?:tardor|primavera|nadal) d[e']|patis oberts)\b")
VECINAL_TITLE = re.compile(r"\b(?:veinal|veinat|vecinal|comunitari|comunitaria|del barri|al barri|de barri)\b")
OUTDOOR_VENUE = re.compile(r"^(?:placa|plaza|parc|parque|jardi|jardins|jardines|platja|playa|passeig|paseo|rambla|carrer|calle|avinguda|av |muntanya|turo|park|mirador|moll|port vell|parc del forum|poble espanyol)\b|\b(?:a l'aire lliure|al aire libre|open air|exterior de|terrassa|terraza|rooftop|azotea)\b")
OUTDOOR_TITLE = re.compile(r"\b(?:a l'aire lliure|al aire libre|open air|correfoc|cercavila|cavalcada|castellers|bicicletada|cursa|carrera popular|caminada|cinema a la fresca|cine a la fresca|mercat al carrer|al carrer)\b")
ART_VENUE = re.compile(r"\b(?:galeria|galerie|gallery|macba|fundacio joan brossa|escola massana|centre d'art|arts santa monica|santa monica|la escocesa|fundacio sunol|museu tapies|fundacio antoni tapies|museu del disseny|disseny hub|virreina|nau bostik|piramidon|homesession|halfhouse|museu d'art|museo de arte|fundacio (?:joan )?miro|fundacio tapies|museu tapies|la virreina|fabra i coats|hangar|santa monica|caixaforum|kbr|la capella|cccb|meam|museu picasso|museu nacional d'art|mnac|fundacio vila casas|espai 13|bombon|etherton|chiquita room|ana mas|projecte sd|nogueras blanchard|joan prats|senda|marlborough|pigment gallery|parking gallery|la plataforma)\b")
ART_PATH = re.compile(r"(?:pintura|fotografia|escultura|art contemporani|arts visuals|il.lustracio|gravat|dibuix|art urba|instal.lacio|performance|videoart|disseny)")
ART_TITLE = re.compile(r"\b(?:inauguracio|inauguracion|vernissage|finissage|performance|instal.lacio|videoart|art contemporani|arte contemporaneo|visita comentada a l'exposicio|conversa amb l'artista|open studio|estudis oberts|gallery weekend|swab|loop)\b")
# Talleres y cursos de práctica artística (20-10-2026): también en «Arte y galerías».
ART_PRACTICE = re.compile(r"\b(?:pintura|dibuix|dibujo|aquarel.la|acuarela|ceramica|escultura|gravat|grabado|il.lustracio|ilustracion|urban sketch\w*|collage|"
                          r"fotografia|art contemporani|arts visuals|modelatge|modelado|serigrafia|linograbat|linograbado|estampacio|estampacion|retrat|retrato|"
                          r"llibre d'artista|libro de artista|art textil|cianotip\w*|enquadernacio|encuadernacion|calligrafia|caligrafia|torn de ceramica)\b")
NON_ART_EXPO = re.compile(r"\b(?:historia|historic|memoria|patrimoni|ciencia|cientific|natura|biodiversitat|medi ambient|salut|documental|arxiu)\b")
FESTIVAL_RE = re.compile(r"\b(?:festival|fest|biennal|bienal|mostra internacional|gallery weekend)\b")


# La fuente lo dice en su texto (20-10-2026): «per a famílies», «públic familiar», «edat recomanada:
# a partir de 3 anys», «adreçat a infants». No basta «totes les edats» ni «tots els públics», y un
# servicio de canguratge para los hijos de quien hace la actividad no la hace familiar.
FAMILY_TEXT = re.compile(r"(?:per a|para|dirigida a|dirigit a|dirigido a|pensada per a|pensat per a|adrecada a|adrecat a)\s+"
                         r"(?:tota la |toda la |les |las |los |els )?(?:families|familias|infants|nens i nenes|ninos y ninas|criatures|public familiar|public infantil|publico familiar|publico infantil)\b"
                         r"|\bpublic (?:familiar|infantil)\b|\bpublico (?:familiar|infantil)\b|\btaller (?:per a|para) famil"
                         r"|\bedat recomanada:?\s*(?:a partir de|de)\s*(?:[0-9]|1[0-2])\s*(?:anys|any|a)\b|\bedad recomendada:?\s*(?:a partir de|de)\s*(?:[0-9]|1[0-2])\s*(?:anos|ano|a)\b"
                         # El formato lo dice (24-10-2026): «Taller familiar», «Concert familiar amb…», «espectacle infantil».
                         r"|\b(?:taller|tallers|activitat|activitats|concert|concerts|espectacle|espectacles|visita|visites|ruta|itinerari|proposta|sessio|"
                         r"actividad|actividades|concierto|conciertos|espectaculo|espectaculos|sesion)\s+(?:familiar|familiars|familiares|infantil|infantils|infantiles|per a nadons|para bebes)\b")
NOT_FAMILY_TEXT = re.compile(r"per a infants i adults|para ninos y adultos|canguratge|cangur|servei de guarderia|servicio de guarderia|espai infantil mentre|ludoteca mentre")


def family_text(text):
    """Fragmento del texto de la fuente que declara público familiar o infantil, o ''."""
    t = norm(text)
    if NOT_FAMILY_TEXT.search(t): return ''
    m = FAMILY_TEXT.search(t)
    return t[max(0, m.start() - 30):m.end() + 20].strip() if m else ''


# La web de la sala publica el acto en su sección para familias (24-10-2026): un tramo de la ruta de la
# página del acto que es exactamente uno de estos (fmirobcn.org/ca/activitats/families/…).
FAMILY_PATH = {'families', 'familia', 'familias', 'familiar', 'infantil', 'infants', 'nens', 'ninos', 'petits', 'kids', 'canalla', 'en-familia'}


def family_path(url):
    from urllib.parse import urlsplit
    segments = {seg.lower() for seg in urlsplit(str(url or '')).path.split('/') if seg}
    return next((seg for seg in segments if seg in FAMILY_PATH), '')


def channels(ev, category, override=None):
    """{canal: evidencia}. Un evento puede estar en varios; sin canal sigue en la agenda."""
    out = {}
    title, venue = norm(ev.get('title')), norm(' '.join(ev.get('venue_names') or []))
    paths = [norm(p) for p in ev.get('classification_paths') or []]
    if ev.get('family_audience'):
        out['familia'] = 'La fuente la marca para público familiar o infantil'
    elif ev.get('age_max') is not None and ev['age_max'] <= 14:
        out['familia'] = f'Edad indicada: {ev.get("age_evidence") or ""}'.strip()
    elif ev.get('ai_family'):
        out['familia'] = f'IA, según el texto: «{ev["ai_family"].get("quote", "")}»'
    elif PATIS.search(title):
        out['familia'] = 'Patio escolar abierto para jugar en familia'
    elif family_text(' '.join((ev.get('title') or '', ev.get('source_text') or ''))):
        out['familia'] = f'La fuente lo indica en su texto: «…{family_text(" ".join((ev.get("title") or "", ev.get("source_text") or "")))}…»'
    elif str(ev.get('source') or '').startswith(('venue_', 'web_')) and family_path(ev.get('url')):
        out['familia'] = f'La web de la sala la publica en su sección para familias («/{family_path(ev.get("url"))}/»)'
    elif ev.get('ai_family_rec'):
        out['familia'] = f'Recomendación automática (IA): {ev["ai_family_rec"].get("es", "")}'
    # Vida de barrio (endurecido 20-10-2026): lo que hace el vecindario, no todo lo que pasa en un
    # equipamiento municipal. Entra: fiestas mayores y de barrio, actividad vecinal o comunitaria,
    # fiestas y mercados en la calle o en equipamientos de proximidad, y actividades puntuales de
    # casals de barri, ateneus populares y asociaciones de vecinos. No entran los cursos ni las
    # programaciones de varias semanas, ni lo de centres cívics y bibliotecas sin rasgo vecinal.
    import datetime as _dt
    try: span = (_dt.date.fromisoformat(str(ev.get('end'))[:10]) - _dt.date.fromisoformat(str(ev.get('start'))[:10])).days
    except ValueError: span = 0
    recurring = ev.get('kind') == 'course' or ev.get('format') == 'course' or (span > 7 and ev.get('kind') != 'single')
    if COMMUNITY.search(title):
        out['barrio'] = 'Grupo o espacio comunitario del barrio'
    elif BARRIO_TITLE.search(title):
        out['barrio'] = 'Fiesta mayor o de barrio según el título'
    elif not recurring and VECINAL_TITLE.search(title):
        out['barrio'] = 'Actividad vecinal o comunitaria según el título'
    elif not recurring and category == 'fiestas' and (BARRIO_VENUE.search(venue) or OUTDOOR_VENUE.search(venue)):
        out['barrio'] = 'Fiesta o mercado en la calle o en un equipamiento de proximidad'
    elif not recurring and NEIGHBOUR_VENUE.search(venue):
        out['barrio'] = f'Actividad puntual de una entidad vecinal: {(ev.get("venue_names") or [""])[0]}'
    if ev.get('ai_outdoor') and not (OUTDOOR_TITLE.search(title) or OUTDOOR_VENUE.search(venue)):
        out['aire'] = f'IA, según el texto: «{ev["ai_outdoor"].get("quote", "")}»'
    if OUTDOOR_TITLE.search(title):
        out['aire'] = 'La actividad es en la calle o al aire libre'
    elif OUTDOOR_VENUE.search(venue):
        out['aire'] = f'Espacio exterior: {(ev.get("venue_names") or [""])[0]}'
    is_art = (category == 'arte' and not NON_ART_EXPO.search(title) and (ART_VENUE.search(venue) or any(ART_PATH.search(p) for p in paths) or ART_TITLE.search(title)))
    art_workshop = category == 'talleres' and ART_PRACTICE.search(title)
    if art_workshop:
        out['galerias'] = 'Taller o curso de práctica artística'
    elif is_art or ART_TITLE.search(title) and (category in ('arte', 'charlas') or ART_VENUE.search(venue)):
        out['galerias'] = 'Arte: ' + ('lugar de arte' if ART_VENUE.search(venue) else 'disciplina artística según la fuente' if any(ART_PATH.search(p) for p in paths) else 'inauguración, performance o visita de exposición')
    if ev.get('source') == 'web_graf':
        out['galerias'] = 'Agenda GRAF de espacios de creación contemporánea'
    # Festivales: la ficha del festival, no cada función suelta «Festival X: Concert Y».
    if (ev.get('format') == 'festival' or FESTIVAL_RE.match(SKIP_LEAD.sub('', title)) or (FESTIVAL_RE.search(title) and ':' not in title)):
        out['festivales'] = 'Festival según la fuente o su nombre'
    if override:
        for ch in override.get('channels_add') or []:
            if ch in CHANNELS: out[ch] = 'Corrección editorial'
        for ch in override.get('channels_remove') or []: out.pop(ch, None)
    return out


def public_labels(events=()):
    """Etiquetas (es/ca) y recuentos para la web pública."""
    from collections import Counter
    cats = Counter(e.get('public_category') for e in events); chans = Counter(c for e in events for c in e.get('channels') or [])
    return {'categories': [{'key': k, 'es': es, 'ca': ca, 'count': cats.get(k, 0)} for k, (es, ca) in CATEGORIES.items()],
            'channels': [{'key': k, 'es': es, 'ca': ca, 'count': chans.get(k, 0)} for k, (es, ca) in CHANNELS.items()]}


# ---------- correcciones editoriales ----------
def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS classification_overrides (
      source TEXT NOT NULL, id TEXT NOT NULL, category TEXT, channels_add TEXT NOT NULL DEFAULT '[]',
      channels_remove TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
      PRIMARY KEY(source,id));
    CREATE TABLE IF NOT EXISTS classification_override_log (
      source TEXT NOT NULL, id TEXT NOT NULL, old_json TEXT, new_json TEXT, changed_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS event_classification (
      source TEXT NOT NULL, id TEXT NOT NULL, category TEXT NOT NULL, status TEXT NOT NULL, method TEXT NOT NULL,
      evidence TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0, channels TEXT NOT NULL DEFAULT '[]',
      computed_at TEXT NOT NULL, PRIMARY KEY(source,id));
    CREATE TABLE IF NOT EXISTS classification_changes (
      source TEXT NOT NULL, id TEXT NOT NULL, old_category TEXT, new_category TEXT, old_channels TEXT, new_channels TEXT,
      changed_at TEXT NOT NULL);
    """)


_OVERRIDES = {'stamp': None, 'map': {}}


def overrides(conn):
    """{(source,id): override} — se recarga solo si cambia la tabla."""
    import json
    try:
        stamp = conn.execute("SELECT COUNT(*), MAX(updated_at) FROM classification_overrides").fetchone()
    except sqlite3.DatabaseError:
        return {}
    if stamp != _OVERRIDES['stamp']:
        rows = conn.execute("SELECT source,id,category,channels_add,channels_remove,note FROM classification_overrides").fetchall()
        _OVERRIDES.update(stamp=stamp, map={(s, i): {'category': c, 'channels_add': json.loads(a or '[]'), 'channels_remove': json.loads(r or '[]'), 'note': n}
                                            for s, i, c, a, r, n in rows})
    return _OVERRIDES['map']


def set_override(conn, source, record_id, category=None, channels_add=(), channels_remove=(), note='', now=None):
    """Corrección editorial: sobrevive a cualquier sincronización (tabla aparte del registro importado)."""
    import json, datetime as dt
    initialize(conn)
    if category is not None and category not in CATEGORIES and category != EXCLUDED: raise ValueError('Categoría no válida')
    if any(ch not in CHANNELS for ch in list(channels_add) + list(channels_remove)): raise ValueError('Canal no válido')
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    old = conn.execute("SELECT category,channels_add,channels_remove,note FROM classification_overrides WHERE source=? AND id=?", (source, record_id)).fetchone()
    new = {'category': category, 'channels_add': sorted(set(channels_add)), 'channels_remove': sorted(set(channels_remove)), 'note': note}
    with conn:
        conn.execute("""INSERT INTO classification_overrides(source,id,category,channels_add,channels_remove,note,updated_at) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(source,id) DO UPDATE SET category=excluded.category,channels_add=excluded.channels_add,
            channels_remove=excluded.channels_remove,note=excluded.note,updated_at=excluded.updated_at""",
                     (source, record_id, category, json.dumps(new['channels_add']), json.dumps(new['channels_remove']), note, now))
        conn.execute("INSERT INTO classification_override_log(source,id,old_json,new_json,changed_at) VALUES(?,?,?,?,?)",
                     (source, record_id, json.dumps(dict(zip(('category', 'channels_add', 'channels_remove', 'note'), old))) if old else None, json.dumps(new), now))
    return new


def record(conn, events, now=None):
    """Guarda la clasificación vigente de cada ficha y anota los cambios respecto a la anterior.
    Idempotente: con los mismos datos no escribe cambios."""
    import json, datetime as dt
    initialize(conn)
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    old = {(s, i): (c, ch, st, m, ev, a) for s, i, c, ch, st, m, ev, a in
           conn.execute("SELECT source,id,category,channels,status,method,evidence,ambiguous FROM event_classification")}
    changes = 0
    with conn:
        for e in events:
            key = (e['source'], e['id']); chans = json.dumps(sorted(e.get('channels') or []))
            prev = old.get(key)
            row = (e['public_category'], chans, e.get('category_status', ''), e.get('category_method', ''), e.get('category_evidence', ''), int(bool(e.get('category_ambiguous'))))
            if prev == row: continue
            if prev and prev[:2] != row[:2]:
                conn.execute("INSERT INTO classification_changes(source,id,old_category,new_category,old_channels,new_channels,changed_at) VALUES(?,?,?,?,?,?,?)",
                             (key[0], key[1], prev[0], e['public_category'], prev[1], chans, now)); changes += 1
            conn.execute("""INSERT INTO event_classification(source,id,category,status,method,evidence,ambiguous,channels,computed_at) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET category=excluded.category,status=excluded.status,method=excluded.method,
                evidence=excluded.evidence,ambiguous=excluded.ambiguous,channels=excluded.channels,computed_at=excluded.computed_at""",
                         (key[0], key[1], e['public_category'], e.get('category_status', ''), e.get('category_method', ''), e.get('category_evidence', ''),
                          int(bool(e.get('category_ambiguous'))), chans, now))
    return changes


# ---------- informe para el panel de administración ----------
def eligible(event, today):
    """Fichas que entrarían en la web si tuvieran categoría: vigentes y no excluidas por otros motivos."""
    from mvp import catalog
    return event['end'] >= today and catalog.is_public({**event, 'public_category': 'x'})


def _head(title):
    words = norm(title).replace('"', ' ').replace("'", ' ').split()
    return ' '.join(words[:2]) if words else '(sin título)'


def _recurring(e):
    import datetime as _dt
    try: span = (_dt.date.fromisoformat(e['end'][:10]) - _dt.date.fromisoformat(e['start'][:10])).days
    except (ValueError, TypeError, KeyError): span = 0
    return e.get('kind') == 'course' or (span > 7 and e.get('format') in ('course', 'workshop', 'program') and e.get('kind') != 'exhibition')


def report(conn, events, today, examples=8, queue_limit=300):
    """Recuentos y colas de la clasificación pública. ``events``: catalog.all_events(conn)."""
    import json
    from collections import Counter, defaultdict
    initialize(conn)
    base = [e for e in events if eligible(e, today)]
    pub = [e for e in base if e['public_category'] not in (PENDING, EXCLUDED)]
    pending = [e for e in base if e['public_category'] == PENDING]
    excluded = [e for e in base if e['public_category'] == EXCLUDED]
    amb = [e for e in pub if e.get('category_ambiguous')]
    weak = [e for e in pub if e.get('category_status') == 'probable']
    brief = lambda e: {'source': e['source'], 'id': e['id'], 'title': e['title'], 'start': e['start'], 'end': e['end'], 'category': e['public_category'],
                       'status': e.get('category_status'), 'method': e.get('category_method'), 'evidence': e.get('category_evidence'),
                       'channels': e.get('channels') or [], 'venue': (e.get('venue_names') or [''])[0], 'url': e.get('url') or ''}
    by_source = defaultdict(Counter)
    for e in base:
        c = by_source[e['source']]; c['total'] += 1
        c[{PENDING: 'pendiente', EXCLUDED: 'excluidas'}.get(e['public_category'], 'clasificadas')] += 1
        if e.get('category_status') == 'confirmada' or e.get('category_status') == 'editorial': c['confirmadas'] += 1
        if e.get('category_ambiguous'): c['ambiguas'] += 1
    coverage = sorted(({'source': s, **dict(c), 'pct': round(100 * c['clasificadas'] / max(1, c['total'] - c['excluidas']), 1)} for s, c in by_source.items()), key=lambda r: -r['total'])
    recurring = Counter(_head(e['title']) for e in pending + amb)
    changes = [dict(zip(('source', 'id', 'old_category', 'new_category', 'old_channels', 'new_channels', 'changed_at'), r)) for r in
               conn.execute("SELECT source,id,old_category,new_category,old_channels,new_channels,changed_at FROM classification_changes ORDER BY changed_at DESC, rowid DESC LIMIT 100")]
    ov = [dict(zip(('source', 'id', 'category', 'channels_add', 'channels_remove', 'note', 'updated_at'), r)) for r in
          conn.execute("SELECT source,id,category,channels_add,channels_remove,note,updated_at FROM classification_overrides ORDER BY updated_at DESC")]
    for o in ov: o['channels_add'] = json.loads(o['channels_add']); o['channels_remove'] = json.loads(o['channels_remove'])
    return {
        'today': today, 'eligible': len(base), 'published': len(pub), 'pending': len(pending), 'excluded': len(excluded),
        'excluded_reasons': dict(Counter(e.get('category_method') for e in excluded).most_common()),
        'excluded_examples': [brief(e) for e in excluded[:examples]],
        # «recurrentes»: cursos y programas de más de una semana; la web los muestra aparte (botón «Talleres y cursos»)
        # y oculta los ya empezados, así que no compiten con los planes puntuales del día.
        'categories': {k: {'label': v[0], 'count': sum(1 for e in pub if e['public_category'] == k),
                           'recurrentes': sum(1 for e in pub if e['public_category'] == k and _recurring(e))} for k, v in CATEGORIES.items()},
        'channels': {k: {'label': v[0], 'count': sum(1 for e in pub if k in (e.get('channels') or []))} for k, v in CHANNELS.items()},
        'status': dict(Counter(e.get('category_status') for e in base)),
        'methods': dict(Counter(e.get('category_method') for e in base).most_common()),
        'ambiguous': {'count': len(amb), 'examples': [brief(e) for e in amb[:examples]]},
        'probable': {'count': len(weak), 'examples': [brief(e) for e in weak[:examples]]},
        'pending_by_source': dict(Counter(e['source'] for e in pending).most_common()),
        'pending_reasons': dict(Counter(e.get('category_method') for e in pending).most_common()),
        'queue': [brief(e) for e in sorted(pending, key=lambda e: (e['start'], e['title']))[:queue_limit]],
        'ai_disagreements': [{**brief(e), 'ai': e.get('ai_disagrees')} for e in pub if e.get('ai_disagrees')][:queue_limit],
        'recurring': [{'pattern': k, 'count': n} for k, n in recurring.most_common(25) if n > 1],
        'coverage': coverage, 'changes': changes, 'overrides': ov, 'ai': _ai_stats(conn, base),
    }


def _ai_stats(conn, base):
    """Uso y efecto de la IA: sugerencias, aplicadas, lotes y tokens (para vigilar el gasto)."""
    import json
    try:
        rows = conn.execute("""SELECT task, CASE WHEN task IN ('categoria','duplicado') THEN answer
              WHEN task='descripcion' THEN CASE WHEN answer LIKE '%"ok": true%' THEN 'aceptada' ELSE 'rechazada' END
              ELSE CASE WHEN answer='{}' THEN 'sin datos comprobados' ELSE 'con datos comprobados' END END, COUNT(*) FROM ai_suggestions GROUP BY 1,2""").fetchall()
        batches = conn.execute("SELECT status, usage_json FROM ai_batches").fetchall()
    except sqlite3.DatabaseError:
        return {'enabled': False}
    usage = {}
    for _, u in batches:
        for k, v in json.loads(u or '{}').items(): usage[k] = usage.get(k, 0) + v
    try:
        sel = conn.execute('SELECT day, model, picks_json FROM ai_selection ORDER BY day DESC LIMIT 1').fetchone()
        selection = {'day': sel[0], 'model': sel[1], 'picks': json.loads(sel[2])} if sel else None
    except sqlite3.DatabaseError:
        selection = None
    return {'enabled': True, 'selection': selection, 'suggestions': [{'task': t, 'answer': a, 'count': n} for t, a, n in rows],
            'applied_categories': sum(1 for e in base if e.get('category_method') == 'ia'),
            'batches': {'total': len(batches), 'in_progress': sum(1 for b in batches if b[0] == 'in_progress')}, 'tokens': usage}
