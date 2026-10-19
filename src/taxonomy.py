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
    'festivales': ('Festivales', 'Festivals'),
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
    ('musica', r"concert|concerts|concierto|conciertos|recital musical|recital de (?:piano|guitarra|cant|violi)|jam session|jam|dj set|dj|audicio|audicion|cantada|havaneres|opera concert|coral|orquestra|orquesta|vermut musical"),
    ('escena', r"espectacle|espectaculo|espectacles|teatre|teatro|dansa|danza|ballet|circ|circo|titelles|titeres|marionetes|opera|sarsuela|zarzuela|musical|monoleg|monologo|stand.up|comedia|cabaret|clown|magia|mag |impro|improvisacio|contacontes|cuentacuentos|conte|contes|narracio|hora del conte|lectura dramatitzada"),
    ('charlas', r"cafes? literaris?|cafe literari|xerrada|xerrades|charla|charlas|conferencia|conferencies|conferencias|debat|debate|col.loqui|coloquio|taula rodona|mesa redonda|presentacio|presentacion|club de lectura|tertulia|seminari|seminario|jornada|jornades|jornadas|simposi|congres|visita|visites|visitas|itinerari|itinerario|ruta|rutes|passejada|paseo|sortida|sortides|excursio|recorregut|tour|conversa|conversacio|dialeg|dialogo|entrevista|sessio informativa|lectura poetica|recital de poesia|poesia|podcast|trobada amb l'autor|tast literari|marato de lectura|lectura compartida"),
    ('talleres', r"taller|tallers|workshop|grup de conversa|grup obert|coaching|tastet|capsula|capsules|capsules formatives|pindola|pindoles|grup d'aprenentatge|aula oberta|sessio formativa|formacio|passatge del terror|tunel del terror|scape room|curs|curso|cursos|classe|clase|classes|masterclass|laboratori|laboratorio|bibliolab|tast|cata|degustacio|degustacion|escape room|gimcana|gincana|yincana|joc|jocs|juego|juegos|activitat familiar|activitat infantil|espai familiar|espai de joc|scape|hackato|hackaton|maker"),
    ('fiestas', r"festa|festes|fiesta|fiestas|fira|fires|feria|ferias|mercat|mercats|mercado|mercadillo|market|flea market|pop.up|castanyada|correfoc|cercavila|revetlla|carnaval|cavalcada|sardanes|sardana|ball de|gegants|castellers|diada|aplec|cagatio|tio|celebracio|celebracion|setmana gastronomica|shopping|vermut popular|calcotada"),
    ('deporte', r"cursa|carrera popular|carrera|marato|maraton|mitja marato|torneig|torneo|partit|partido|campionat|campeonato|triatlo|triatlon|bicicletada|caminada popular|futbol|basquet|handbol|waterpolo|regata|esport|deporte"),
]
LEAD_RE = [(cat, re.compile(r"^(?:" + pat + r")\b")) for cat, pat in LEAD]
# Palabras que no dicen el género: se saltan al buscar el género del principio.
SKIP_LEAD = re.compile(r"^(?:\d+[a-z]*\s+|(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xx|xxi|xxv)+\s+|nou |nova |gran |petit |mini |(?:la|el|les|els|l'|un|una|the) |activitat (?:adults|joves|infantil) - |(?:t'interessa|btj|nou!?|novetat|estrena|special|especial):?\s+)+")
PROGRAM_LEAD = re.compile(r"^(?:cicle|ciclo|festival|fest|mostra|muestra|temporada|programa|programacio|projecte|proyecto|jornades|semana|setmana|any|mes|dia|nit|tots sants|nadal|tardor|primavera|estiu|hivern)\b")

INNER = {
    'cine': r"\b(?:cinema|cine|cineforum|pel.licula|pelicula|curtmetratge|documental|film)\b",
    'arte': r"\b(?:exposicio|exposicion|inauguracio|instal.lacio|fotografi(?:a|c)|pintura|escultura|art contemporani|arts visuals|il.lustracio)\b",
    'musica': r"\b(?:concert|concierto|musica|jazz|rock|flamenc|flamenco|electronica|dj|orquestra|coral|piano|guitarra|hip hop|techno|house|indie|blues|soul|reggae|cumbia|salsa|bossa)\b",
    'escena': r"\b(?:teatre|teatro|dansa|danza|circ|circo|titelles|opera|monoleg|comedia|comedy|stand.?up|open mic|improv|espectacle|espectaculo|contacontes|musical)\b",
    'charlas': r"\b(?:xerrada|conferencia|debat|debate|presentacio|literatura|llibre|libro|poesia|lectura|book club|walking tour|visita|itinerari|ruta|patrimoni|historia|ciencia|divulgacio|talks?)\b",
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
SOURCE_DEFAULT = {'venue_xceed': 'musica', 'venue_songkick': 'musica', 'web_conciertos_club': 'musica', 'venue_dice': 'musica'}
VENUE_GENRE = [('escena', re.compile(r"^(?:teatre|teatro)\b|\b(?:sala beckett|mercat de les flors|tnc|teatre nacional|gran teatre del liceu)\b")),
               ('cine', re.compile(r"\b(?:filmoteca|cinemes|cines|cinema (?!a la fresca))"))]
# Decisiones editoriales del 20-10-2026 (David):
#  - «Patis escolars oberts»: patios abiertos para jugar → Talleres y experiencias, canal En familia.
#  - Servicios y convocatorias: fuera de la agenda.
#  - Ocio social de ticketera (citas, intercambios, pub crawls, networking, empleo, congresos): fuera.
#  - Comunidad y cuidados (grupos de barrio, «El barri proposa», «Ens cuidem»): Talleres + Vida de barrio.
PATIS = re.compile(r"\bpatis? escolars? oberts?\b")
SOCIAL = re.compile(r"\b(?:singles|single (?:night|party)|dating|citas|first dates|speed ?dating|language exchange|intercambio de idiomas|intercanvi d'idiomes|pub crawl|party tour|boat party|bar crawl|"
                    r"networking|meet people|new friends|nuevos amigos|afterwork|job fair|feria de empleo|employer|hackathon|womenhack|summit|congress|congres (?:mundial|internacional)|congreso (?:mundial|internacional)|"
                    r"conference|forum event|venture capital|real estate|inversion inmobiliaria|investment|pub quiz|trivia|casino barcelona|expansion playbook|evento anual)\b")
COMMUNITY = re.compile(r"(?:\bel barri proposa\b|\bens cuidem\b|\bgrup (?:comunitari|de suport|virtual de suport|de dones|de teixidores|de cura|d'insomni)|"
                       r"\bactivitat comunitaria\b|\bcura comunitaria\b|\bespai de (?:participacio|pausa|cura|acompanyament)\b|\btrobada 'repara)")
SERVICE = re.compile(r"\b(?:campanya|donacio de sang|taula informativa|canvi oficial d'horari|dispositiu de proves|servei punt tic|punt tic|servei d'|inscripcions? obertes|convocatoria|oberta la convocatoria|campanya de recollida|recollida solidaria|borsa de)\b")

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
    """El título entero y cada parte tras «:», « - » o comillas de programa:
    «Tots Sants 2026: Castanyada a …», «Cicle 'Afins': Xerrada …»."""
    t = norm(title)
    parts = [t] + [p.strip(" '\"") for p in re.split(r":\s+|\s+-\s+|\s+–\s+", t)[1:]]
    out = []
    for p in parts:
        p = SKIP_LEAD.sub('', p.strip(" '\"«»")).strip(" '\"«»")
        if p and p not in out: out.append(p)
    return out


def lead_category(title):
    """(categoría, palabra) del género con que empieza el título o alguna de sus partes."""
    for part in segments(title):
        for cat, rx in LEAD_RE:
            m = rx.match(part)
            if m: return cat, m.group(0)
    return None, ''


def inner_categories(title):
    t = norm(title)
    return sorted({cat for cat, rx in INNER_RE.items() if rx.search(t)})


def classify(ev, override=None):
    """→ dict(category, status, method, evidence, ambiguous).

    status: 'editorial' | 'confirmada' | 'probable' | 'pendiente'."""
    if override and override.get('category') in CATEGORIES:
        return {'category': override['category'], 'status': 'editorial', 'method': 'correccion_editorial',
                'evidence': override.get('note') or 'Corrección editorial', 'ambiguous': False}
    title = ev.get('title') or ''
    source_cat = SOURCE_CATEGORY.get(ev.get('category') or '')
    lead, word = lead_category(title)
    official = next((cat for cat, rx in OFFICIAL_TYPE for p in ev.get('classification_paths') or [] if rx.search(norm(p))), None)
    signals = []
    if ev.get('kind') == 'exhibition' or ev.get('format') == 'exhibition':
        signals.append(('arte', 'formato_exposicion', 'La fuente la publica como exposición'))
    if lead:
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
    if PATIS.search(t):
        return {'category': 'talleres', 'status': 'confirmada', 'method': 'regla_editorial',
                'evidence': 'Patio escolar abierto para jugar en familia (decisión editorial 20-10-2026)', 'ambiguous': False}
    if not lead and not inner_categories(title) and SOCIAL.search(t):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'ocio_social_o_profesional',
                'evidence': 'Ocio social, networking, empleo o congreso: fuera de la agenda cultural (decisión editorial 20-10-2026)', 'ambiguous': False}
    if SERVICE.search(t) and not (lead and lead in ('talleres', 'charlas', 'musica', 'escena', 'cine')):
        return {'category': EXCLUDED, 'status': 'excluida', 'method': 'servicio_o_convocatoria',
                'evidence': 'Servicio, campaña o convocatoria, no una actividad programada (decisión editorial 20-10-2026)', 'ambiguous': False}
    if not lead and COMMUNITY.search(t):
        return {'category': 'talleres', 'status': 'probable', 'method': 'comunidad_y_cuidados',
                'evidence': 'Grupo o espacio comunitario del barrio (decisión editorial 20-10-2026)', 'ambiguous': False}
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
    return {'category': first[0], 'status': status, 'method': first[1],
            'evidence': first[2] + (f'. Otras señales: {others}' if others else ''), 'ambiguous': bool(ambiguous)}


# ---------- canales ----------
BARRIO_VENUE = re.compile(r"\b(?:centre civic|centro civico|casal de barri|casal de gent gran|casal|ateneu|biblioteca|espai veinal|associacio de veins|asociacion de vecinos|casa de la barceloneta|centre cultural|cc )\b")
BARRIO_TITLE = re.compile(r"\b(?:festa major|festes de|fiesta mayor|barri|barrio|veinal|veinat|vecinal|comunitari|comunitaria|districte cultural|patis oberts)\b")
OUTDOOR_VENUE = re.compile(r"^(?:placa|plaza|parc|parque|jardi|jardins|jardines|platja|playa|passeig|paseo|rambla|carrer|calle|avinguda|av |muntanya|turo|park|mirador|moll|port vell|parc del forum|poble espanyol)\b|\b(?:a l'aire lliure|al aire libre|open air|exterior de|terrassa|terraza|rooftop|azotea)\b")
OUTDOOR_TITLE = re.compile(r"\b(?:a l'aire lliure|al aire libre|open air|correfoc|cercavila|cavalcada|castellers|bicicletada|cursa|carrera popular|caminada|cinema a la fresca|cine a la fresca|mercat al carrer|al carrer)\b")
ART_VENUE = re.compile(r"\b(?:galeria|galerie|gallery|macba|museu d'art|museo de arte|fundacio (?:joan )?miro|fundacio tapies|museu tapies|la virreina|fabra i coats|hangar|santa monica|caixaforum|kbr|la capella|cccb|meam|museu picasso|museu nacional d'art|mnac|fundacio vila casas|espai 13|bombon|etherton|chiquita room|ana mas|projecte sd|nogueras blanchard|joan prats|senda|marlborough|pigment gallery|parking gallery|la plataforma)\b")
ART_PATH = re.compile(r"(?:pintura|fotografia|escultura|art contemporani|arts visuals|il.lustracio|gravat|dibuix|art urba|instal.lacio|performance|videoart|disseny)")
ART_TITLE = re.compile(r"\b(?:inauguracio|inauguracion|vernissage|finissage|performance|instal.lacio|videoart|art contemporani|arte contemporaneo|visita comentada a l'exposicio|conversa amb l'artista|open studio|estudis oberts|gallery weekend|swab|loop)\b")
NON_ART_EXPO = re.compile(r"\b(?:historia|historic|memoria|patrimoni|ciencia|cientific|natura|biodiversitat|medi ambient|salut|documental|arxiu)\b")
FESTIVAL_RE = re.compile(r"\b(?:festival|fest|biennal|bienal|mostra internacional|gallery weekend)\b")


def channels(ev, category, override=None):
    """{canal: evidencia}. Un evento puede estar en varios; sin canal sigue en la agenda."""
    out = {}
    title, venue = norm(ev.get('title')), norm(' '.join(ev.get('venue_names') or []))
    paths = [norm(p) for p in ev.get('classification_paths') or []]
    if ev.get('family_audience'):
        out['familia'] = 'La fuente la marca para público familiar o infantil'
    elif PATIS.search(title):
        out['familia'] = 'Patio escolar abierto para jugar en familia'
    # Vida de barrio: lo que programa el tejido de proximidad, no las clases de cada semana
    # (el taller de pilates de un centre cívic es un curso, no vida de barrio).
    import datetime as _dt
    try: span = (_dt.date.fromisoformat(str(ev.get('end'))[:10]) - _dt.date.fromisoformat(str(ev.get('start'))[:10])).days
    except ValueError: span = 0
    recurring = category == 'talleres' and (span > 7 or ev.get('format') == 'course')
    if COMMUNITY.search(title):
        out['barrio'] = 'Grupo o espacio comunitario del barrio'
    elif not recurring and BARRIO_TITLE.search(title):
        out['barrio'] = 'Fiesta o actividad vecinal según el título'
    elif not recurring and BARRIO_VENUE.search(venue):
        out['barrio'] = f'Equipamiento de proximidad: {(ev.get("venue_names") or [""])[0]}'
    elif not recurring and any('centres civics' in p or 'festes de barri' in p for p in paths):
        out['barrio'] = 'Programación de los centres cívics según la fuente'
    if OUTDOOR_TITLE.search(title):
        out['aire'] = 'La actividad es en la calle o al aire libre'
    elif OUTDOOR_VENUE.search(venue):
        out['aire'] = f'Espacio exterior: {(ev.get("venue_names") or [""])[0]}'
    is_art = (category == 'arte' and not NON_ART_EXPO.search(title) and (ART_VENUE.search(venue) or any(ART_PATH.search(p) for p in paths) or ART_TITLE.search(title)))
    if is_art or ART_TITLE.search(title) and (category in ('arte', 'charlas') or ART_VENUE.search(venue)):
        out['galerias'] = 'Arte: ' + ('lugar de arte' if ART_VENUE.search(venue) else 'disciplina artística según la fuente' if any(ART_PATH.search(p) for p in paths) else 'inauguración, performance o visita de exposición')
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
    if category is not None and category not in CATEGORIES: raise ValueError('Categoría no válida')
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
        'categories': {k: {'label': v[0], 'count': sum(1 for e in pub if e['public_category'] == k)} for k, v in CATEGORIES.items()},
        'channels': {k: {'label': v[0], 'count': sum(1 for e in pub if k in (e.get('channels') or []))} for k, v in CHANNELS.items()},
        'status': dict(Counter(e.get('category_status') for e in base)),
        'methods': dict(Counter(e.get('category_method') for e in base).most_common()),
        'ambiguous': {'count': len(amb), 'examples': [brief(e) for e in amb[:examples]]},
        'probable': {'count': len(weak), 'examples': [brief(e) for e in weak[:examples]]},
        'pending_by_source': dict(Counter(e['source'] for e in pending).most_common()),
        'pending_reasons': dict(Counter(e.get('category_method') for e in pending).most_common()),
        'queue': [brief(e) for e in sorted(pending, key=lambda e: (e['start'], e['title']))[:queue_limit]],
        'recurring': [{'pattern': k, 'count': n} for k, n in recurring.most_common(25) if n > 1],
        'coverage': coverage, 'changes': changes, 'overrides': ov,
    }
