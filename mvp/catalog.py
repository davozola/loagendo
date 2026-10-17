"""Read-only projections of the v1.2 normalized data, with explicit uncertainty."""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from src.media import is_event_image

SOURCES = {'opendatabcn_agenda':'Ajuntament de Barcelona · Open Data (agenda cultural)','generalitat':'Generalitat de Catalunya','diba_bibliotecas':'Biblioteques — Diputació', 'diba_turismo':'Turisme — Diputació','guiabcn':'GuiaBCN','web_macba':'MACBA · agenda directa','web_cccb':'CCCB · agenda directa','web_teatre_lliure':'Teatre Lliure · agenda directa','web_auditori':"L'Auditori · agenda directa",'web_centres_civics':'Centres Cívics · agenda directa','web_conciertos_club':'Conciertos.Club · descubrimiento'}
VENUES_PATH = Path(__file__).resolve().parents[1] / 'config' / 'venues.json'
try:
    _VENUES={v['slug']:v for v in json.loads(VENUES_PATH.read_text(encoding='utf-8')).get('venues',[]) if v.get('slug')}
except (OSError,json.JSONDecodeError,ValueError): _VENUES={}
VENUE_CATEGORY={'music':'Música y vida nocturna','festival':'Música y vida nocturna','theatre':'Artes escénicas','cinema':'Cine y audiovisual','culture':'Arte y exposiciones'}
for _slug,_v in _VENUES.items(): SOURCES['venue_'+_slug]=_v.get('name',_slug)+' · agenda del recinto'
KINDS = {'single':'Acto puntual','program':'Programa / ciclo','exhibition':'Exposición','course':'Curso','service':'Servicio'}
FORMATS = {
    'one_shot':'Actos puntuales', 'workshop':'Talleres', 'course':'Cursos',
    'program':'Ciclos y programas', 'festival':'Festivales', 'exhibition':'Exposiciones', 'ongoing':'Actividades continuadas',
}
CATEGORIES = [
 'Música y vida nocturna','Artes escénicas','Cine y audiovisual','Arte y exposiciones',
 'Literatura y palabra','Ciencia y divulgación','Talleres y experiencias',
 'Cultura popular y fiestas','Ferias y mercados','Gastronomía','Deporte','Patrimonio y rutas','Comunidad y encuentros'
]
DISTRICTS = ['Ciutat Vella','Eixample','Gràcia','Horta-Guinardó','Les Corts','Nou Barris', 'Sant Andreu','Sant Martí','Sants-Montjuïc','Sarrià-Sant Gervasi']
STATUS = ('pending', 'needs_evidence', 'reviewed', 'excluded')
PUBLIC_CATEGORIES = ('Exposiciones','Familia','Cine','Teatro','Conciertos','Música','Barrio','Deporte','Talleres')
PUBLIC_CATEGORY_MAP = {
    'Arte y exposiciones':'Exposiciones',
    'Cine y audiovisual':'Cine', 'Artes escénicas':'Teatro',
    'Deporte':'Deporte', 'Música y vida nocturna':'Música',
    'Talleres y experiencias':'Talleres',
}
# "Familia" is an audience, not an activity type: a family concert is still a
# concert. The public filter therefore matches `family_audience`.
FAMILY_TOKENS = ('familiar','infantil','infantils','nens i nenes','hora del conte','en familia','per a infants','per a families','petita infancia','bebes','nadons','contacontes')


TAXONOMY_PATH = Path(__file__).resolve().parents[1] / 'config' / 'guiabcn_taxonomy.json'


def clean(s):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(s or '').lower()) if not unicodedata.combining(c)).split())


def parse_date(v):
    try:return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):return None


def today():
    return dt.date.today()


def load_taxonomy(path=TAXONOMY_PATH):
    """GuiaBCN activity-type codes → Loagendo category (see config file provenance)."""
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError): return {'activity_type_prefix':'0061901','priority':[],'codes':{}}


TAXONOMY = load_taxonomy()


def guiabcn_codes(raw):
    """Activity-type suffixes (e.g. '019') declared by GuiaBCN for a listing row."""
    item=(raw or {}).get('api_item') or {}
    prop=item.get('code_prop') or {}
    codes=prop.get('item') if isinstance(prop,dict) else prop
    if isinstance(codes,str): codes=[codes]
    prefix=TAXONOMY.get('activity_type_prefix','0061901')
    out=[]
    for code in codes or []:
        code=str(code)
        if code.startswith(prefix) and len(code)==len(prefix)+3 and code[len(prefix):] not in out:
            out.append(code[len(prefix):])
    return out


def guiabcn_taxonomy(raw):
    """Return (category or None, family_audience, exclude_reason or None) from source codes only."""
    codes=guiabcn_codes(raw); table=TAXONOMY.get('codes',{})
    category=next((table[c]['category'] for c in TAXONOMY.get('priority',[]) if c in codes and table.get(c,{}).get('category')),None)
    family=any(table.get(c,{}).get('audience')=='family' for c in codes)
    exclude=next((table[c]['exclude_reason'] for c in codes if table.get(c,{}).get('exclude_reason')),None)
    return category,family,exclude


def guiabcn_exclusion(raw, start='', end=''):
    """Reason to keep a GuiaBCN row out of the public agenda, or None.

    The search feed also lists metropolitan municipalities and year-long
    calendar notices (public holidays, clock changes). Nothing is deleted:
    the row stays archived with ``eligibility='exclude'`` and an explicit flag.
    """
    item=(raw or {}).get('api_item') or {}
    city=clean(item.get('city') or '')
    if city and not city.startswith('barcelona'): return 'OUTSIDE_BARCELONA_MUNICIPALITY'
    codes=guiabcn_codes(raw); table=TAXONOMY.get('codes',{})
    reasons=[table[c]['exclude_reason'] for c in codes if table.get(c,{}).get('exclude_reason')]
    span=(parse_date(end)-parse_date(start)).days if parse_date(start) and parse_date(end) else 0
    if reasons and len(reasons)==len(codes) and span>=180: return reasons[0]
    return None


def opendata_normalized(raw):
    """Fields the Open Data BCN connector derived from its source record."""
    return (raw or {}).get('loagendo') or {}


def category_of(raw, source, kind):
    if kind == 'exhibition':return 'Arte y exposiciones'
    if source=='web_conciertos_club':return 'Música y vida nocturna'
    if source=='opendatabcn_agenda':
        declared=opendata_normalized(raw).get('category')
        if declared: return declared
    if source.startswith('venue_'):
        venue=_VENUES.get(source[6:],{})
        declared=(raw.get('loagendo') or {}).get('category') or VENUE_CATEGORY.get(venue.get('type',''))
        if declared and kind!='exhibition': return declared
    if source=='guiabcn':
        declared,_,_=guiabcn_taxonomy(raw)
        if declared: return declared
    def string_of(x):
        if isinstance(x,dict):return ' '.join(str(y) for y in x.values() if isinstance(y,(str,int)))
        if isinstance(x,list):return ' '.join(map(str,x))
        return str(x or '')
    if source=='generalitat':
        b=(raw.get('localizaciones') or [{}])[0]
        txt=' '.join(map(string_of,(b.get('tags_categor_es'),b.get('tags_mbits'),b.get('denominaci'))))
    elif source=='guiabcn':
        txt=' '.join(map(string_of,(raw.get('type'),raw.get('title') or (raw.get('api_item') or {}).get('name'))))
    elif source=='opendatabcn_agenda':
        txt=' '.join(map(string_of,(raw.get('name'),[c.get('name') for c in raw.get('classifications_data') or []])))
    else:
        txt=' '.join(map(string_of,(raw.get('tipus'),raw.get('tags'),raw.get('titol'))))
    s=clean(txt)
    # Deliberately one conservative category. Source tags are not Loagendo taxonomy.
    rules=[
        ('Cine y audiovisual',('cinema','cinemat','pelicula','audiovisual','projeccio')),
        ('Ferias y mercados',('fira','fires','mercat','feria')),
        ('Deporte',('esport','esports','deporte','esportiu')),
        ('Gastronomía',('gastronomi','cuina','gastronomia','tast de')),
        ('Música y vida nocturna',('musica','concert','jazz','flamenc','dj ','discoteca')),
        ('Artes escénicas',('teatre','espectacle','dansa','circ','titelles','comedia','monoleg')),
        ('Literatura y palabra',('literatura','lectura','llibres','hora del conte','contes','escript')),
        ('Ciencia y divulgación',('ciencia','divulgac','conferencia','xerrada','astronomi')),
        ('Patrimonio y rutas',('visites','patrimoni','ruta','itinerari','arquitectura')),
        ('Cultura popular y fiestas',('festes','tradicional','nadal','castanyada','festa major')),
        ('Talleres y experiencias',('taller','workshop','biblio lab','bibliolab')),
        ('Comunidad y encuentros',('comunitat','trobada','associaci','club de lectura','participacio')),
        ('Arte y exposiciones',('arts visual','art','exposicio','exposicion','galeria')),
    ]
    for category, matches in rules:
        if any(t in s for t in matches):return category
    return 'Comunidad y encuentros'


def district_of(raw, source):
    if source=='opendatabcn_agenda':
        d=opendata_normalized(raw).get('district','')
        return d if d in DISTRICTS else None
    if source=='guiabcn':
        d=raw.get('district','')
        return d if d in DISTRICTS else None
    if source.startswith('diba_'):
        location=(raw.get('grup_adreca') or {}).get('municipi_nom','')
        if location.startswith('Barcelona - '):
            d=location.split('Barcelona - ',1)[1].strip()
            return d if d in DISTRICTS else None
    return None


def source_description(raw,source):
    if source=='generalitat':
        loc=(raw.get('localizaciones') or [{}])[0]
        # The HTML version keeps the paragraphs the plain field flattens.
        from src.opendata_bcn import plain
        value=(plain(loc.get('descripcio_html')) if loc.get('descripcio_html') else '') or loc.get('descripcio') or ''
    # GuiaBCN's listing observation is itinerary metadata (often a compact
    # "Quan / On" string), not the event prose.  Prefer the archived official
    # detail-page description, which is both legible and auditable.
    elif source=='guiabcn':return ''
    elif source=='opendatabcn_agenda':
        from src.opendata_bcn import plain
        return plain(raw.get('body'))
    elif source.startswith('venue_'):
        return str((raw.get('loagendo') or {}).get('description') or '')
    else:value=raw.get('descripcio') or ''
    # GuiaBCN sometimes exposes a link-object here. It is source metadata, not
    # editorial prose, and rendering its Python/JSON representation is useless.
    return value.strip() if isinstance(value,str) else ''


def source_time(raw,source):
    if source=='generalitat':return str((raw.get('localizaciones') or [{}])[0].get('horari') or '')
    if source=='guiabcn':return ''
    if source=='opendatabcn_agenda':return str(opendata_normalized(raw).get('schedule_hours') or '')
    if source.startswith(('web_','venue_')):return str((raw.get('normalized') or {}).get('time_text') or '')
    return str(raw.get('observacions_horari') or '')


def hours_range(text):
    """'de 10.00 h a 20.00 h', 'd'11 a 19.30 h', 'De 8.30 h a 22.30 h' → '10:00–20:00'.

    Opening hours of an exhibition or venue, as printed by the source. Only
    the first range is returned; the full text stays in the detail view.
    """
    match=re.search(r"(?:\bde\s+|\bd'|\bd’)(\d{1,2})(?:[.:](\d{2}))?\s*(?:h\s*)?a\s+(?:les\s+|las\s+)?(\d{1,2})(?:[.:](\d{2}))?\s*h\b",str(text or ''),re.I)
    if not match: return None
    h1,m1,h2,m2=int(match.group(1)),int(match.group(2) or 0),int(match.group(3)),int(match.group(4) or 0)
    if max(h1,h2)>23 or max(m1,m2)>59: return None
    return f'{h1:02d}:{m1:02d}–{h2:02d}:{m2:02d}'


def first_clock_time(text):
    """First explicit clock time printed by the source ('a les 19.30 h', '20 h', '18:30').

    Used only as a display fallback for one-day acts whose session was not
    materialised as a candidate; the text itself stays visible in the detail.
    """
    for match in re.finditer(r'\b(\d{1,2})(?:[.:](\d{2}))?\s*h(?:ores)?\b|\b([01]?\d|2[0-3]):([0-5]\d)\b',str(text or ''),re.I):
        hour=int(match.group(1) or match.group(3)); minute=int(match.group(2) or match.group(4) or 0)
        if hour<=23 and minute<=59: return f'{hour:02d}:{minute:02d}'
    return None


def source_price(raw,source):
    if source=='generalitat':
        a=(raw.get('localizaciones') or [{}])[0]
        return str(a.get('entrades') or ''),str(a.get('gratuita') or '')
    if source=='guiabcn':return '',''
    if source=='opendatabcn_agenda':
        meta=opendata_normalized(raw)
        return str(meta.get('price_text') or ''),('Entrada lliure' if meta.get('is_free') else '')
    return str(raw.get('preu') or ''),''


def family_audience(raw, source, title):
    """True only when the source declares a family/children audience or the title says so."""
    if source=='guiabcn' and guiabcn_taxonomy(raw)[1]: return True
    if source=='opendatabcn_agenda' and opendata_normalized(raw).get('family_audience'): return True
    text=clean(title)
    if source.startswith('diba_'): text+=' '+clean(' '.join(map(str,raw.get('tipus') or [])))
    return any(token in text for token in FAMILY_TOKENS)


SUBTYPES_PATH = Path(__file__).resolve().parents[1] / 'config' / 'subtypes.json'


def _norm_path(value):
    return ' >> '.join(' '.join(part.split()) for part in str(value or '').split('>>') if part.strip())


def load_subtypes(path=SUBTYPES_PATH):
    """Second-level public classification (config/subtypes.json): per group,
    the ordered subtypes and the official Open Data BCN paths that map to
    them. Returns {public_category: {'group','labels','rules','unclassified'}}."""
    try: data=json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return {}
    unclassified=data.get('unclassified_label','Sin clasificar'); out={}
    for group,spec in (data.get('groups') or {}).items():
        rules=[(st['label'],[_norm_path(m) for m in st.get('match',[])]) for st in spec.get('subtypes',[])]
        labels=[label for label,_ in rules]+[unclassified]
        for public in spec.get('applies_to',[]): out[public]={'group':group,'labels':labels,'rules':rules,'unclassified':unclassified}
    return out


SUBTYPES=load_subtypes()


def subtype_groups():
    """What the front end renders: {public_category: [labels...]} (unclassified last)."""
    return {public:spec['labels'] for public,spec in SUBTYPES.items()}


def classification_paths(raw, source):
    """Official classification paths carried by the archived record (only the
    municipal Open Data feed publishes them); normalised, deduplicated."""
    if source!='opendatabcn_agenda' or not isinstance(raw,dict): return []
    paths=[]
    for item in list(raw.get('classifications_data') or [])+list(raw.get('secondary_filters_data') or []):
        path=_norm_path(item.get('full_path') or item.get('name')) if isinstance(item,dict) else ''
        if path and path not in paths: paths.append(path)
    return paths


def subtype_of(public, paths):
    """The first subtype (in config order) with a matching path; the
    unclassified label when the category has subtypes but no path matches;
    None when the category has no second level."""
    spec=SUBTYPES.get(public)
    if not spec: return None
    for label,patterns in spec['rules']:
        for path in paths:
            if any(path==pattern or path.startswith(pattern+' >> ') for pattern in patterns): return label
    return spec['unclassified']


def public_category(category, source='', title=''):
    # Concert listings deserve a direct route: otherwise an artist name such
    # as "Strawberry Guy" becomes a generic neighbourhood activity merely
    # because the title does not literally contain "concierto".
    title_text=clean(title)
    if source.startswith('venue_') and category=='Música y vida nocturna': return 'Conciertos'
    if source == 'web_conciertos_club' or (
        any(token in title_text for token in ('concert','concierto','recital','jam session'))
        and not any(token in title_text for token in ('taller','exposicio','exposicion','sessio informativa'))
    ):
        return 'Conciertos'
    return PUBLIC_CATEGORY_MAP.get(category,'Barrio')


def effective_kind(source, raw, stored_kind, title, start, end):
    """Repair legacy GuiaBCN rows whose feed type was the generic 'Agenda'."""
    if source!='guiabcn' or stored_kind!='Agenda': return stored_kind
    span=(parse_date(end)-parse_date(start)).days if parse_date(start) and parse_date(end) else 0
    text=clean(title)
    if 'exposic' in text:return 'exhibition'
    if 'curs' in text or 'curso' in text:return 'course'
    if 'cicle' in text or 'festival' in text or span>2:return 'program'
    return 'single'


def format_of(kind, title, start, end):
    text=clean(title)
    if kind=='exhibition':return 'exhibition'
    if 'taller' in text or 'workshop' in text:return 'workshop'
    if kind=='course' or 'curs' in text or 'curso' in text:return 'course'
    # A source interval does not necessarily mean a programme: theatres and
    # concert venues commonly publish one production or act with its whole
    # run. Keep those visible under the public "Actos y funciones" filter.
    # Actual cycles, festivals and season-wide programmes remain programmes.
    # A festival is its own thing, not a season cycle: a named multi-day
    # event (up to ten days) with "festival", "biennal" or "mostra" in the title.
    if is_festival({'title':title,'start':start,'end':end}):return 'festival'
    if any(token in text for token in ('cicle','ciclo','festival','temporada','programa')):return 'program'
    if any(token in text for token in (
        'concert','recital','espectacle','espectaculo','teatre','teatro',
        'musical','monoleg','monolog','dansa','danza','projeccio','proyeccion',
        'xerrada','conferencia','conferència','presentacio','presentació',
        'visita guiada','sessio','sessió','jam session',
    )):return 'one_shot'
    if kind=='program':return 'program'
    if start==end:return 'one_shot'
    return 'ongoing'


SHORT_SPAN_DAYS=4
FESTIVAL_WORDS=('festival','fest ','biennal','bienal','mostra ','muestra ')


def is_short_span(event):
    """A dated multi-day act (two to four days): a festival, a weekend cycle."""
    start,end=parse_date(event.get('start')),parse_date(event.get('end'))
    return bool(start and end and 0<(end-start).days<SHORT_SPAN_DAYS)


def is_festival(event):
    start,end=parse_date(event.get('start')),parse_date(event.get('end'))
    return bool(start and end and (end-start).days<=10) and any(word in clean(event.get('title',''))+' ' for word in FESTIVAL_WORDS)


def featured_score(event, day):
    """Explainable ranking for the public weekly selection."""
    score=0; reasons=[]
    if event['format']=='one_shot': score+=30; reasons.append('acto puntual')
    elif event['format']=='festival' or is_festival(event): score+=34; reasons.append('festival')  # a city festival is a headline, above a routine one-off
    elif event['format'] in ('exhibition','ongoing'): score-=14
    elif event['format']=='program': score-=10
    if event['start']==day: score+=16; reasons.append('empieza hoy')
    if event.get('time'): score+=14; reasons.append('horario publicado')
    if event.get('has_candidate') or (is_festival(event) and event.get('time')): score+=8; reasons.append('sesión fechada')
    if any(not m.get('fallback') for m in event.get('media') or []): score+=8; reasons.append('imagen de la fuente')
    if event.get('has_description'): score+=6; reasons.append('descripción disponible')
    if event.get('venue_names'): score+=4; reasons.append('lugar identificado')
    if event.get('coordinates'): score+=2
    # Editorial weight of the venue (config/venue_prestige.json): a headline
    # hall lifts an otherwise equal record above a routine one.
    from src.venue_prestige import prestige
    points,label=prestige(event.get('venue_names'))
    if points: score+=points; reasons.append(f'{label.lower()} (+{points})')
    confirmations=int(event.get('confirmations') or 0)
    if confirmations>1: score+=min(10,5*(confirmations-1)); reasons.append(f'coincide en {confirmations} fuentes')
    return score,reasons


def spread_venues(ranked, window=8):
    """Keep the order by score but let one venue take only one of the top
    places at a time: among the next ``window`` candidates the first whose
    venue is not yet shown goes first, so a hall with three events that day
    does not fill the whole selection."""
    from src.venue_directory import site_for
    def hall(e):
        name=(e.get('venue_names') or [''])[0]
        return (site_for(name) or {}).get('slug') or name.casefold()  # Sala 1 and Sala 2 are both L'Auditori
    out=[]; seen=set(); pool=list(ranked)
    while pool:
        pick=next((e for e in pool[:window] if hall(e) not in seen),pool[0])
        pool.remove(pick); out.append(pick); seen.add(hall(pick))
    return out


def featured_rotation(event, day):
    """Tie-breaker that changes every day: records with the same score take
    turns instead of the same one always winning on date and title."""
    import hashlib
    return hashlib.sha1(f"{day}|{event['source']}|{event['id']}".encode('utf-8')).hexdigest()


def is_free(price, free_label):
    """True only when the source says so: a 'gratuita' flag set to yes, or a
    price text that literally says free. 'No' is not a free label."""
    label=clean(free_label)
    if label in ('no','false','0','n'): return any(term in clean(price) for term in ('gratis','gratuit','gratuito','free'))
    if label in ('si','s','yes','true','1'): return True
    return any(term in clean(price+' '+free_label) for term in ('gratis','gratuit','gratuito','free','entrada lliure'))


def public_fields(event, projection, requested_day='', schedule_time=''):
    source=event['source']
    requested=[o['time'] for o in event['occurrences'] if (not requested_day or o['date']==requested_day) and o['time']]
    if requested: time,time_source=requested[0],'candidate_occurrence'
    elif schedule_time: time,time_source=schedule_time,'official_detail_page'
    elif event['start']==event['end'] and projection.get('schedule_text_time'): time,time_source=projection['schedule_text_time'],'source_schedule_text'
    # A festival or short programme (up to SHORT_SPAN_DAYS) that prints its
    # hours happens every one of its days: it is listed with that start time
    # instead of a bare "Varios días".
    elif is_short_span(event) and projection.get('schedule_text_time'): time,time_source=projection['schedule_text_time'],'source_schedule_text'
    else: time,time_source=None,None
    # What the listing prints in the time column. A dated act shows its start
    # time; an exhibition or programme shows its opening hours when the
    # source prints them, otherwise the kind of interval it is.
    conflict=(event.get('time_conflicts') or {}).get(requested_day or event['start'])
    if conflict: time_label=' / '.join(conflict)
    elif time: time_label=time
    elif projection.get('hours_label'): time_label=projection['hours_label']
    elif event['start']!=event['end'] and event['kind']=='exhibition': time_label='Exposición'
    elif event['start']!=event['end']: time_label='Varios días'
    else: time_label='Hora no indicada'
    public=(lambda pc:'Familia' if pc=='Barrio' and event.get('family_audience') else pc)(public_category(event['category'],source,event['title']))
    return {'price_label':projection['price_label'],'is_free':projection['is_free'],
            'time':time,'time_source':time_source,'time_label':time_label,
            'subtype':subtype_of(public,projection.get('classification_paths') or []),
            # A family activity with no stronger activity type is labelled
            # "Familia"; a family concert keeps "Conciertos" and is still found
            # by the Familia filter through `family_audience`.
            'public_category':public,
            'url':projection['url']}


CATEGORY_NOUN={'Música y vida nocturna':'Concierto','Artes escénicas':'Espectáculo','Cine y audiovisual':'Proyección','Arte y exposiciones':'Exposición',
    'Literatura y palabra':'Actividad literaria','Ciencia y divulgación':'Charla','Talleres y experiencias':'Taller','Cultura popular y fiestas':'Fiesta popular',
    'Ferias y mercados':'Feria','Gastronomía':'Actividad gastronómica','Deporte':'Actividad deportiva','Patrimonio y rutas':'Visita','Comunidad y encuentros':'Encuentro'}
WEEKDAYS_ES=['lunes','martes','miércoles','jueves','viernes','sábado','domingo']
MONTHS_ES=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre']


def _date_words(value):
    d=parse_date(value)
    return f'{WEEKDAYS_ES[d.weekday()]} {d.day} de {MONTHS_ES[d.month-1]}' if d else str(value)


def editorial_summary(event, price_text='', organizers=None, schedule_days='', registration=False):
    """One natural sentence from known fields, used only when the source
    gives no description. Nothing is asserted that the record does not state."""
    kind=event.get('kind'); category=event.get('category') or ''
    noun={'exhibition':'Exposición','course':'Curso','program':'Ciclo'}.get(kind) or CATEGORY_NOUN.get(category,'Actividad')
    venue=(event.get('venue_names') or [''])[0]; district=event.get('district')
    where=f' en {venue}' if venue else ''
    if district and district not in venue: where+=f' ({district})'
    start,end=event.get('start'),event.get('end')
    if start==end:
        when=f' el {_date_words(start)}'+(f' a las {event["time"]}' if event.get('time') else '')
    elif kind=='exhibition' or (parse_date(end) and parse_date(start) and (parse_date(end)-parse_date(start)).days>45):
        when=f', hasta el {_date_words(end)}'
        if schedule_days: when+=f' ({schedule_days.lower()})'
    else:
        when=f', del {_date_words(start)} al {_date_words(end)}'
    sentences=[f'{noun}{where}{when}.']
    if event.get('is_free'): sentences.append('Entrada gratuita.')
    elif price_text: sentences.append(f'Precio: {price_text}.')
    if registration: sentences.append('Requiere inscripción previa.')
    if organizers: sentences.append(f'Organiza {organizers[0]}.')
    return ' '.join(sentences)


def source_links(raw,source,url):
    links=[]
    if url:links.append({'label':'Página de la fuente','url':url,'verified':False})
    if source.startswith('venue_') and (raw.get('loagendo') or {}).get('tickets_url'):
        links.append({'label':'Entradas','url':raw['loagendo']['tickets_url'],'verified':False})
    if source=='opendatabcn_agenda':
        meta=opendata_normalized(raw)
        for label,key in (('Inscripciones','registration_url'),('Venta de entradas','tickets_url')):
            if meta.get(key): links.append({'label':label,'url':meta[key],'verified':False})
        for u in meta.get('links') or []: links.append({'label':'Web declarada por la fuente','url':u,'verified':False})
    if source=='generalitat':
        from html.parser import HTMLParser
        class AnchorParser(HTMLParser):
            def __init__(self):super().__init__();self.hrefs=[]
            def handle_starttag(self,tag,attrs):
                if tag=='a':
                    for name,val in attrs:
                        if name=='href':self.hrefs.append(val)
        p=AnchorParser()
        try:p.feed(str((raw.get('localizaciones') or [{}])[0].get('descripcio_html') or ''))
        except Exception:pass
        for u in p.hrefs[:6]:links.append({'label':'Enlace citado en la descripción','url':u,'verified':False})
    out=[];seen=set()
    for link in links:
        u=link['url'].strip()
        try:valid=urlsplit(u).scheme in ('http','https') and bool(urlsplit(u).netloc)
        except ValueError:valid=False
        if valid and u not in seen:out.append({**link,'url':u});seen.add(u)
    return out


class Prefetch:
    """One round of bulk queries for every per-record relation used by the
    listing. Replaces the per-event N+1 pattern (six queries per record, which
    cost ~7 s per request on a 9.500-record catalogue)."""

    def __init__(self, conn):
        tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.occurrences={}; self.venues={}; self.media={}; self.publication={}; self.enrichment={}; self.facts={}
        from src.place_images import local_place_images
        self.place_media=local_place_images(conn)
        # Same municipal register id in the licensed Open Data feed and in the
        # scraped GuiaBCN feed: identity, not similarity.
        self.opendata_ids={r[0] for r in conn.execute("SELECT id FROM source_records WHERE source='opendatabcn_agenda'")}
        self.guiabcn_ids={r[0] for r in conn.execute("SELECT id FROM source_records WHERE source='guiabcn'")}
        from src.dedupe import canonical_groups
        try: self.collapsed=canonical_groups(conn)
        except sqlite3.DatabaseError: self.collapsed={}
        self.collapsed_members={}
        for member,canonical in self.collapsed.items(): self.collapsed_members.setdefault(canonical,[]).append(member)
        for s,i,d,t,f in conn.execute('SELECT source,id,local_date,local_time,evidence_field FROM candidate_occurrences ORDER BY source,id,local_date,local_time'):
            self.occurrences.setdefault((s,i),[]).append({'date':d,'time':t,'evidence_field':f,'verified':False})
        for s,i,v,a,lat,lon in conn.execute('SELECT source,id,venue,address,lat,lon FROM source_venues ORDER BY source,id,seq'):
            self.venues.setdefault((s,i),[]).append((v,a,lat,lon))
        if 'media_assets' in tables:
            # Local previews first; an authorised asset not yet on disk is still
            # listed, and /media/<id> fetches it on first use.
            for s,i,asset_id,alt,rights,url,ctype in conn.execute("SELECT source,id,asset_id,alt_text,rights_status,original_url,content_type FROM media_assets WHERE (local_path IS NOT NULL OR rights_status='authorized') AND download_failed_at IS NULL ORDER BY (local_path IS NULL), asset_id"):
                if is_event_image(url,alt,ctype or ''):
                    self.media.setdefault((s,i),[]).append({'asset_id':asset_id,'url':'/media/'+str(asset_id),'alt':alt,'rights_status':rights})
        if 'publication_decisions' in tables:
            self.publication=dict(((s,i),st) for s,i,st in conn.execute('SELECT source,id,status FROM publication_decisions'))
        if 'source_enrichments' in tables:
            columns={r[1] for r in conn.execute('PRAGMA table_info(source_enrichments)')}
            schedules='schedule_time,schedule_text,' if {'schedule_time','schedule_text'} <= columns else "'', '',"
            for s,i,desc,st,stx,links in conn.execute(f'SELECT source,id,description,{schedules}links_json FROM source_enrichments'):
                try: parsed=json.loads(links)
                except (TypeError,json.JSONDecodeError): parsed=[]
                self.enrichment[(s,i)]=(desc or '',st or '',stx or '',parsed if isinstance(parsed,list) else [])
        if 'source_detail_facts' in tables:
            for s,i,facts in conn.execute('SELECT source,id,facts_json FROM source_detail_facts'):
                try: self.facts[(s,i)]=json.loads(facts) or {}
                except (TypeError,json.JSONDecodeError): self.facts[(s,i)]={}


def enrichment(conn, source, record_id, prefetch=None):
    if prefetch is not None: return prefetch.enrichment.get((source,record_id),('','','',[]))
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_enrichments'").fetchone(): return ('','','',[])
    columns={r[1] for r in conn.execute('PRAGMA table_info(source_enrichments)')}
    schedules='schedule_time,schedule_text,' if {'schedule_time','schedule_text'} <= columns else "'', '',"
    row=conn.execute(f'SELECT description,{schedules}links_json FROM source_enrichments WHERE source=? AND id=?',(source,record_id)).fetchone()
    if not row:return ('','','',[])
    # links is always the final selected column; the schema fallback above also
    # permits opening a pre-migration database safely.
    try: links=json.loads(row[-1])
    except (TypeError,json.JSONDecodeError): links=[]
    return (row[0] or '',row[1] or '',row[2] or '',links if isinstance(links,list) else [])


def detail_facts(conn, source, record_id, prefetch=None):
    if prefetch is not None: return prefetch.facts.get((source,record_id),{})
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_detail_facts'").fetchone(): return {}
    row=conn.execute('SELECT facts_json FROM source_detail_facts WHERE source=? AND id=?',(source,record_id)).fetchone()
    try: return json.loads(row[0]) if row else {}
    except (TypeError,json.JSONDecodeError): return {}


def _register_twin(conn, source, record_id, prefetch=None):
    if source=='guiabcn':
        other='opendatabcn_agenda'
        known=prefetch.opendata_ids if prefetch is not None else None
    elif source=='opendatabcn_agenda':
        other='guiabcn'
        known=prefetch.guiabcn_ids if prefetch is not None else None
    else: return None
    if known is None:
        known={record_id} if conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(other,record_id)).fetchone() else set()
    return other+':'+record_id if record_id in known else None


def _possible_duplicates(conn, source, record_id):
    from src.dedupe import duplicates_for
    try: return duplicates_for(conn,source,record_id)
    except sqlite3.DatabaseError: return []


PROJECTION_VERSION=7  # 7: place_id por nombre para diba_bibliotecas (17-10-2026)


def project_raw(source, id, title, start, end, kind, url, raw):
    """Everything the listing needs from the archived raw JSON, computed once
    per raw hash and stored in ``listing_projections``. Parsing 110 MB of
    Open Data records on every request was the remaining cold-start cost."""
    kind=effective_kind(source,raw,kind,title,start,end)
    price,free_label=source_price(raw,source)
    links=source_links(raw,source,url)
    description=source_description(raw,source)
    return {'v':PROJECTION_VERSION,'kind':kind,'category':category_of(raw,source,kind),'district':district_of(raw,source),
            'family_audience':family_audience(raw,source,title),'price_label':price or None,'is_free':is_free(price,free_label),
            'schedule_text_time':first_clock_time(source_time(raw,source)),'hours_label':hours_range(source_time(raw,source)),'url':links[0]['url'] if links else None,
            'has_description':bool(description.strip()),'summary':description.strip()[:220],
            'source_label':(raw.get('loagendo') or {}).get('source_label') if source.startswith('venue_') else None,
            'classification_paths':classification_paths(raw,source),
            'place_id':(lambda place:place[0] if place else None)(__import__('src.place_images',fromlist=['place_of']).place_of(raw,source))}


def initialize_projections(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS listing_projections(
      source TEXT NOT NULL, id TEXT NOT NULL, raw_sha256 TEXT NOT NULL, projection_json TEXT NOT NULL,
      PRIMARY KEY(source,id))''')


_COLLAPSE_CACHE={'stamp':None,'groups':{}}


def _collapse_groups(conn):
    """canonical_groups for a detail call, cached until match_candidates changes."""
    try:
        stamp=conn.execute("SELECT COUNT(*),MAX(generated_at) FROM match_candidates").fetchone()
        if stamp!=_COLLAPSE_CACHE['stamp']:
            from src.dedupe import canonical_groups
            _COLLAPSE_CACHE.update(stamp=stamp,groups=canonical_groups(conn))
        return _COLLAPSE_CACHE['groups']
    except sqlite3.DatabaseError: return {}


def borrow_from_twins(conn, event):
    """Fill a canonical detail with what its collapsed twins (other sources
    describing the same act) carry and it lacks: description, hours, price,
    image, links. Each borrowed field names the record it came from."""
    borrowed={}
    for member in event.get('also_in') or []:
        ms,mi=member.split(':',1)
        row=conn.execute('''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,r.evidence_level,r.source_url,r.raw_json,e.status,e.note,e.updated_at
                            FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id WHERE r.source=? AND r.id=?''',(ms,mi)).fetchone()
        if not row: continue
        twin=row_to_event(conn,row,True,'')
        if twin.get('presentation')=='venue_link_only': continue
        for field in ('description','time_text','price_text','schedule_days','schedule_note'):
            if not event.get(field) and twin.get(field):
                event[field]=twin[field]; borrowed[field]=member
                if field=='description': event['description_credit']=twin['source_label']
        if not event.get('media') and twin.get('media'): event['media']=[dict(m,borrowed_from=member) for m in twin['media']]; borrowed['media']=member
        if not event.get('organizers') and twin.get('organizers'): event['organizers']=twin['organizers']; borrowed['organizers']=member
        seen={l['url'] for l in event.get('links',[])}
        for link in twin.get('links',[]):
            if link['url'] not in seen: event.setdefault('links',[]).append({**link,'label':('Enlace' if link.get('label')=='Página de la fuente' else link['label'])+' · '+twin['source_label']}); seen.add(link['url'])
    if event.get('description') and borrowed.get('description'): event['description_source']=borrowed['description']
    event['borrowed']=borrowed
    return event


def place_media_item(place):
    """A venue photo standing in for a record without its own image: shown as
    such, never as a picture of the activity."""
    return {'asset_id':None,'place_id':place['place_id'],'url':'/media/place/'+str(place['place_id']),'alt':'Imagen del equipamiento: '+(place.get('name') or ''),
            'rights_status':'authorized','fallback':True,'credit':'Ajuntament de Barcelona'}


def row_to_event(conn, row, detail=False, requested_day='', prefetch=None, projection=None):
    source,id,title,start,end,kind,eligibility,evidence_level,url,raw_text,status,note,updated = row
    if projection is None:
        raw=json.loads(raw_text)
        projection=project_raw(source,id,title,start,end,kind,url,raw)
    else:
        raw=None
    kind=projection['kind']
    event_format=format_of(kind,title,start,end)
    if prefetch is not None:
        occurrences=[dict(o) for o in prefetch.occurrences.get((source,id),[])]
        place=prefetch.venues.get((source,id),[])
        media=list(prefetch.media.get((source,id),[]))
        # A canonical record borrows what its collapsed twins carry and it
        # lacks: the municipal twin's image on a Generalitat card, and so on.
        for member in prefetch.collapsed_members.get(source+':'+id,[]):
            if media: break
            ms,mi=member.split(':',1); media=[dict(m,borrowed_from=member) for m in prefetch.media.get((ms,mi),[])]
        if not media and projection.get('place_id') in prefetch.place_media: media=[place_media_item(prefetch.place_media[projection['place_id']])]
        publication=prefetch.publication.get((source,id),'draft')
    else:
        occurrences=[{'date':x[0], 'time':x[1],'evidence_field':x[2],'verified':False} for x in conn.execute('SELECT local_date,local_time,evidence_field FROM candidate_occurrences WHERE source=? AND id=? ORDER BY local_date,local_time',(source,id))]
        place=conn.execute('SELECT venue,address,lat,lon FROM source_venues WHERE source=? AND id=? ORDER BY seq',(source,id)).fetchall()
        media=[]
        for asset_id, alt_text, rights_status, original_url, content_type in conn.execute(
            '''SELECT asset_id,alt_text,rights_status,original_url,content_type
               FROM media_assets WHERE source=? AND id=? AND (local_path IS NOT NULL OR rights_status='authorized') AND download_failed_at IS NULL
               ORDER BY (local_path IS NULL), asset_id''', (source,id)
        ):
            if is_event_image(original_url,alt_text,content_type or ''):
                media.append({'asset_id':asset_id,'url':'/media/'+str(asset_id),'alt':alt_text,'rights_status':rights_status})
        publication=(conn.execute('SELECT status FROM publication_decisions WHERE source=? AND id=?',(source,id)).fetchone() or ('draft',))[0]
        if not media and projection.get('place_id'):
            from src.place_images import local_place_images
            venue_photo=local_place_images(conn).get(projection['place_id'])
            if venue_photo: media=[place_media_item(venue_photo)]
    archived_description,schedule_time,_,_=enrichment(conn,source,id,prefetch)
    # GuiaBCN's listing never carries prose: its description lives in the
    # archived official page, so the listing must look there too.
    has_description=projection['has_description'] or len((archived_description or '').strip())>=40
    summary=projection['summary'] or (archived_description or '').strip()[:220]
    twin=_register_twin(conn,source,id,prefetch)
    key=source+':'+id
    if prefetch is not None: collapsed_into=prefetch.collapsed.get(key); collapsed_members=prefetch.collapsed_members.get(key,[])
    else:
        groups=_collapse_groups(conn); collapsed_into=groups.get(key); collapsed_members=[m for m,c in groups.items() if c==key]
    # Two directories often publish different times for the same concert
    # (doors vs. show, or a plain error). When the canonical record is itself a
    # directory, every published time is shown and the reader is told to
    # confirm with the hall; a hall's or the city's own time is never doubted.
    time_conflicts={}
    if prefetch is not None and collapsed_members:
        from src.dedupe import source_rank, DIRECTORY_RANK
        if source_rank(source)>=DIRECTORY_RANK:
            for date in sorted({o['date'] for o in occurrences}):
                times={o['time'] for o in occurrences if o['date']==date and o['time']}
                for member in collapsed_members:
                    ms,mi=member.split(':',1)
                    times|={o['time'] for o in prefetch.occurrences.get((ms,mi),[]) if o['date']==date and o['time']}
                if len(times)>1: time_conflicts[date]=sorted(times)
    events={
        'source':source,'id':id,'key':source+':'+id, 'title':title,
        'source_label':SOURCES.get(source) or projection.get('source_label') or source,'start':start,'end':end,
        'kind':kind,'kind_label':KINDS.get(kind,kind),'format':event_format,'format_label':FORMATS[event_format],'eligibility':eligibility,
        'category':projection['category'],'district':projection['district'],
        'family_audience':projection['family_audience'],'has_description':has_description,'summary':summary,
        'status':status or 'pending','review_note':note or '', 'review_updated_at':updated,
        'venue_names':[v[0] for v in place if v[0]],
        'coordinates':next(({'lat':v[2],'lon':v[3]} for v in place if v[2] is not None and v[3] is not None),None),
        'occurrences':occurrences,'has_candidate':bool(occurrences),
        'date_precision':'point' if start==end else 'range',
        'evidence_level':evidence_level,
        'published':publication=='approved',
        'media':media,
        # A GuiaBCN row whose register id also exists in the licensed Open
        # Data feed is superseded by it in public listings (same event, same
        # municipal id); the archived row and its history stay untouched.
        'time_conflicts':time_conflicts,
        'superseded_by':(twin if source=='guiabcn' else None) or collapsed_into,
        'also_in':([twin] if source=='opendatabcn_agenda' and twin else [])+[m for m in collapsed_members if m!=twin],
    }
    # A record whose source names no district (Generalitat, the halls' own feeds,
    # aggregators) takes the district the municipal feeds give the same venue, or
    # the district of its nearest labelled neighbours when it carries coordinates.
    if not events['district'] or not events['coordinates']:
        from src.gazetteer import gazetteer
        district,coords,how=gazetteer(conn).resolve(events['venue_names'],events['coordinates'])
        if district and not events['district']: events['district']=district; events['district_evidence']=how
        if coords and not events['coordinates']: events['coordinates']=coords
    events.update(public_fields(events,projection,requested_day=requested_day,schedule_time=schedule_time))
    # How many independent sources carry this record (twins collapsed into it).
    events['confirmations']=1+len(events['also_in'])
    policy=presentation_of(source)
    if policy=='venue_link_only': apply_venue_link_policy(events)
    if detail:
        if raw is None: raw=json.loads(raw_text)
        price,free=source_price(raw,source)
        archived_description,schedule_time,schedule_text,archived_links=enrichment(conn,source,id,prefetch)
        archived_facts=detail_facts(conn,source,id,prefetch)
        links=source_links(raw,source,url)
        for link in archived_links:
            if isinstance(link,str): links.append({'label':'Enlace detectado en la fuente','url':link,'verified':False})
        seen=set(); links=[link for link in links if not (link['url'] in seen or seen.add(link['url']))]
        events.update({
            'description':source_description(raw,source) or archived_description,
            'editorial_summary':editorial_summary(events,price_text=price or archived_facts.get('price_text',''),organizers=[r[0] for r in conn.execute('SELECT name FROM source_organizers WHERE source=? AND id=? ORDER BY seq',(source,id))] or ([archived_facts['organizer']] if archived_facts.get('organizer') else []),schedule_days=archived_facts.get('schedule_days') or (opendata_normalized(raw).get('schedule_days') if source=='opendatabcn_agenda' else ''),registration=bool(archived_facts.get('registration_required') or (opendata_normalized(raw).get('registration_required') if source=='opendatabcn_agenda' else False))),
            'time_text':schedule_text or archived_facts.get('schedule_hours') or source_time(raw,source),
            'schedule_days':archived_facts.get('schedule_days') or (opendata_normalized(raw).get('schedule_days','') if source=='opendatabcn_agenda' else ''),
            'schedule_note':archived_facts.get('schedule_note') or (opendata_normalized(raw).get('schedule_note','') if source=='opendatabcn_agenda' else ''),
            'registration_required':bool(archived_facts.get('registration_required') or (opendata_normalized(raw).get('registration_required') if source=='opendatabcn_agenda' else False)),
            'price_text':price or archived_facts.get('price_text',''),'source_free_label':free,
            'price_status':'unknown' if not (price or archived_facts.get('price_text') or free) else 'source_claim_unverified',
            'venues':[{'name':v[0], 'address':v[1], 'lat':v[2],'lon':v[3]} for v in place] or ([{'name':archived_facts.get('venue',''), 'address':archived_facts.get('address',''), **archived_facts.get('coordinates',{})}] if archived_facts.get('venue') else []),
            'organizers':[r[0] for r in conn.execute('SELECT name FROM source_organizers WHERE source=? AND id=? ORDER BY seq',(source,id))] or ([archived_facts['organizer']] if archived_facts.get('organizer') else []),
            'alerts':[r[0] for r in conn.execute('SELECT issue FROM review_flags WHERE source=? AND id=? ORDER BY issue',(source,id))],
            'links':links,
            'raw_sha256':conn.execute('SELECT raw_sha256 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone()[0],
            'evidence':{'level':evidence_level,'date_is_verified':False,'schedule_is_verified':False,'rights_for_media_verified':False},
            'verified_fields':[{'field':r[0],'value':json.loads(r[1]),'evidence_url':r[2],'checked_on':r[3],'note':r[4],'updated_at':r[5]} for r in conn.execute('SELECT field_name,value_json,evidence_url,checked_on,note,updated_at FROM field_verifications WHERE source=? AND id=? ORDER BY field_name',(source,id))],
            'publication_status':publication,
            'source_taxonomy':{'guiabcn_activity_codes':guiabcn_codes(raw)} if source=='guiabcn' else {},
            'possible_duplicates':_possible_duplicates(conn,source,id),
        })
        if policy=='venue_link_only': apply_venue_link_policy(events,detail=True,source_url=url)
        else: borrow_from_twins(conn,events)
    return events


def initialize(conn):
    conn.execute('PRAGMA foreign_keys=ON')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS editorial_reviews (
       source TEXT NOT NULL, id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
       note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
       PRIMARY KEY(source,id),FOREIGN KEY(source,id) REFERENCES source_records(source,id)
    );
    CREATE TABLE IF NOT EXISTS editorial_review_log (
       seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,id TEXT NOT NULL,
       old_status TEXT, new_status TEXT NOT NULL, old_note TEXT, new_note TEXT,
       changed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS field_verifications (
       source TEXT NOT NULL, id TEXT NOT NULL, field_name TEXT NOT NULL, value_json TEXT NOT NULL,
       evidence_url TEXT NOT NULL, checked_on TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL,
       PRIMARY KEY(source,id,field_name), FOREIGN KEY(source,id) REFERENCES source_records(source,id)
    );
    CREATE TABLE IF NOT EXISTS field_verification_log (
       seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, id TEXT NOT NULL, field_name TEXT NOT NULL,
       old_value_json TEXT, new_value_json TEXT NOT NULL, evidence_url TEXT NOT NULL, checked_on TEXT NOT NULL, changed_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS publication_decisions (
       source TEXT NOT NULL, id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', note TEXT NOT NULL DEFAULT '', decided_at TEXT NOT NULL,
       PRIMARY KEY(source,id), FOREIGN KEY(source,id) REFERENCES source_records(source,id)
    );
    CREATE TABLE IF NOT EXISTS media_assets (
       asset_id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, id TEXT NOT NULL, original_url TEXT NOT NULL,
       alt_text TEXT NOT NULL DEFAULT '', credit TEXT NOT NULL DEFAULT '', rights_status TEXT NOT NULL DEFAULT 'unknown',
       sha256 TEXT, local_path TEXT, UNIQUE(source,id,original_url), FOREIGN KEY(source,id) REFERENCES source_records(source,id)
    );
    CREATE TABLE IF NOT EXISTS curated_picks (
       source TEXT NOT NULL, id TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0,
       week_start TEXT NOT NULL, created_at TEXT NOT NULL,
       PRIMARY KEY(source,id,week_start), FOREIGN KEY(source,id) REFERENCES source_records(source,id)
    );
    ''')
    conn.execute('CREATE INDEX IF NOT EXISTS match_candidates_b ON match_candidates(b)') if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='match_candidates'").fetchone() else None
    columns={r[1] for r in conn.execute('PRAGMA table_info(media_assets)')}
    if 'content_type' not in columns: conn.execute('ALTER TABLE media_assets ADD COLUMN content_type TEXT')
    if 'download_failed_at' not in columns: conn.execute('ALTER TABLE media_assets ADD COLUMN download_failed_at TEXT')
    if 'download_error' not in columns: conn.execute('ALTER TABLE media_assets ADD COLUMN download_error TEXT')


def connect(db):
    # A reader must never wait behind the engine's commits: WAL lets the web
    # server read while a sync writes, and busy_timeout covers the rest.
    conn=sqlite3.connect(str(db),timeout=10)
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=10000')
    return conn


def _database_fingerprint(conn):
    """Cheap change detector: file path, size and mtime of the main database
    (and its WAL when present). Every commit from the engine or the local
    console touches the file, so the listing cache is invalidated safely."""
    parts=[]
    for _,name,path in conn.execute('PRAGMA database_list'):
        if name!='main' or not path: return None
        for candidate in (path,path+'-wal'):
            try:
                st=os.stat(candidate); parts.append((candidate,st.st_size,st.st_mtime_ns))
            except OSError: parts.append((candidate,0,0))
    return tuple(parts) or None


_LISTING_CACHE={'fingerprint':None,'events':[],'built_at':0.0}
_LISTING_LOCK=threading.Lock()
# The engine commits every few seconds while enriching; rebuilding the listing
# on each commit would make every click pay the full cost. A listing up to this
# many seconds old is served while the file keeps changing.
REBUILD_MIN_INTERVAL_SECONDS=20.0


def build_events(conn):
    prefetch=Prefetch(conn)
    initialize_projections(conn)
    rows=conn.execute('''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,
               r.evidence_level,r.source_url,r.raw_sha256, e.status,e.note,e.updated_at, p.raw_sha256, p.projection_json
               FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id
               LEFT JOIN listing_projections p ON p.source=r.source AND p.id=r.id''').fetchall()
    events=[]; fresh=[]
    for row in rows:
        source,id,title,start,end,kind,eligibility,evidence_level,url,raw_sha,status,note,updated,proj_sha,proj_json=row
        projection=None
        if proj_json and proj_sha==raw_sha:
            try: projection=json.loads(proj_json)
            except (TypeError,json.JSONDecodeError): projection=None
            if projection is not None and projection.get('v')!=PROJECTION_VERSION: projection=None
        if projection is None:
            raw_text=conn.execute('SELECT raw_json FROM source_records WHERE source=? AND id=?',(source,id)).fetchone()[0]
            try: raw=json.loads(raw_text)
            except (TypeError,json.JSONDecodeError): raw={}
            projection=project_raw(source,id,title,start,end,kind,url,raw)
            fresh.append((source,id,raw_sha or '',json.dumps(projection,ensure_ascii=False)))
        events.append(row_to_event(conn,(source,id,title,start,end,kind,eligibility,evidence_level,url,None,status,note,updated),prefetch=prefetch,projection=projection))
    if fresh:
        # Persist in small batches so a concurrent engine run only delays, never
        # blocks, the write; what cannot be written is recomputed next time.
        try:
            conn.execute('PRAGMA busy_timeout=10000')
            for start in range(0,len(fresh),500):
                with conn:
                    conn.executemany('INSERT OR REPLACE INTO listing_projections(source,id,raw_sha256,projection_json) VALUES(?,?,?,?)',fresh[start:start+500])
        except sqlite3.OperationalError as err:
            print('Aviso: proyecciones del listado no guardadas (base ocupada):',err)
    return events


def _database_path(conn):
    for _,name,path in conn.execute('PRAGMA database_list'):
        if name=='main': return path or None
    return None


_REBUILD_STATE={'running':False}


def _rebuild_in_background(path):
    """Stale-while-revalidate: a request never waits for a rebuild once a
    listing exists. The engine's commits only schedule a refresh."""
    def worker():
        try:
            conn=connect(path)
            try:
                fingerprint=_database_fingerprint(conn)
                events=build_events(conn)
                with _LISTING_LOCK:
                    _LISTING_CACHE.update(fingerprint=fingerprint,events=events,built_at=time.monotonic())
            finally: conn.close()
        except Exception as err:
            print('Aviso: no se pudo refrescar el listado en segundo plano:',repr(err))
        finally:
            with _LISTING_LOCK: _REBUILD_STATE['running']=False
    threading.Thread(target=worker,name='loagendo-listing-refresh',daemon=True).start()


def all_events(conn):
    """Listing projection of every record. Built in bulk and cached per
    database fingerprint; callers receive shallow copies so per-request
    adjustments (times for a day, featured scores) never leak between
    requests. When the file changed, the cached listing is served and a
    background refresh is scheduled (at most one at a time, and not more
    often than REBUILD_MIN_INTERVAL_SECONDS)."""
    fingerprint=_database_fingerprint(conn)
    now=time.monotonic()
    with _LISTING_LOCK:
        cached=_LISTING_CACHE['fingerprint'] is not None and fingerprint is not None
        if cached:
            events=_LISTING_CACHE['events']
            stale=_LISTING_CACHE['fingerprint']!=fingerprint and now-_LISTING_CACHE['built_at']>=REBUILD_MIN_INTERVAL_SECONDS
            path=_database_path(conn)
            if stale and not _REBUILD_STATE['running'] and path and path!=':memory:':
                _REBUILD_STATE['running']=True
                _rebuild_in_background(path)
        else:
            events=build_events(conn)
            if fingerprint is not None: _LISTING_CACHE.update(fingerprint=fingerprint,events=events,built_at=now)
    return [dict(e) for e in events]


def invalidate_cache():
    with _LISTING_LOCK: _LISTING_CACHE.update(fingerprint=None,events=[],built_at=0.0)


def _reverse_date(value):
    """Sort key that puts the most recent ISO date first."""
    return ''.join(chr(0x7f-ord(c)) for c in str(value))


def event_hours(value):
    """Return every whole-hour start found in a source schedule.

    Schedules can contain more than one session (for example, 10:00 and
    18:30). Keeping each time lets the public hour range include the event if
    at least one advertised session falls inside it.
    """
    return [int(hour) for hour in re.findall(r'\b([01]\d|2[0-3]):[0-5]\d\b', str(value or ''))]


MAX_RANGE_DAYS=183  # six months: the public horizon
STARTED_GRACE_DAYS=7  # a course that began within a week is still listed as joinable


def hidden_public_sources(registry_path=Path(__file__).resolve().parents[1]/'docs'/'source_registry.json'):
    """Sources retired from the public site (``public_listing: false`` in the
    registry). Their archived rows, history and admin visibility stay intact."""
    try: registry=json.loads(Path(registry_path).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return frozenset()
    return frozenset(source for source,entry in registry.items() if isinstance(entry,dict) and entry.get('public_listing') is False)


HIDDEN_PUBLIC_SOURCES=hidden_public_sources()


def public_presentations(registry_path=Path(__file__).resolve().parents[1]/'docs'/'source_registry.json'):
    """Per-source presentation policy from the registry. ``venue_link_only``:
    the public card links to the hall's own website (config/venues.json) and
    to a ticket seller, never to the listing it was discovered on, and carries
    no third-party text or image. Provenance stays complete in the archive."""
    try: registry=json.loads(Path(registry_path).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError): return {}
    return {source:entry['public_presentation'] for source,entry in registry.items() if isinstance(entry,dict) and entry.get('public_presentation')}


PUBLIC_PRESENTATION=public_presentations()
VENUE_LINK_LABEL='Programación de salas'


def presentation_of(source):
    if source in PUBLIC_PRESENTATION: return PUBLIC_PRESENTATION[source]
    if source.startswith('venue_'):
        from src.venue_directory import venue_type
        kind=venue_type(source[6:])
        return PUBLIC_PRESENTATION.get('aggregator_*' if kind=='aggregator' else 'ticketing_*' if kind=='ticketing' else 'venue_*')
    return None


def _host(url):
    try: return (urlsplit(url).netloc or '').lower().removeprefix('www.')
    except ValueError: return ''


def apply_venue_link_policy(event, detail=False, source_url=''):
    """Rewrite a discovered concert for the public: link to the hall, neutral
    source label, no third-party media, prose or links back to the listing."""
    from src.venue_directory import site_for
    site=next((s for s in (site_for(name) for name in event.get('venue_names',[])) if s),None)
    if not event.get('provenance_url'): event['provenance_url']=source_url or event.get('url') or ''
    event['url']=site['url'] if site else ''
    event['link_label']='Web de la sala' if site else ''
    event['source_label']=VENUE_LINK_LABEL
    event['media']=[]
    event['presentation']='venue_link_only'
    if detail:
        listing_host=_host(event['provenance_url'])
        event['description']=''
        links=[l for l in event.get('links',[]) if l.get('label')!='Página de la fuente' and _host(l.get('url',''))!=listing_host and 'Enlace detectado' not in l.get('label','')]
        if site: links.insert(0,{'label':'Web de la sala','url':site['url'],'verified':False})
        event['links']=links
    return event


def is_public(event):
    """What the public site may show: not excluded by the source or the editors,
    not collapsed into a canonical twin, and not from a retired source."""
    return not (event['eligibility']=='exclude' or event['status']=='excluded' or event.get('superseded_by') or event['source'] in HIDDEN_PUBLIC_SOURCES)


def query_events(conn, *, query='', date='', day='', date_from='', date_to='', category='', public_category='', format='', free=False, district='', source='', status='', kind='', only_sessions=False,featured=False,curated=False,hour_from=None,hour_to=None,page=1,page_size=24,public=False,include_started=True,subtype=''):
    """``public`` hides records the sources or the editors excluded (services,
    out-of-town rows, calendar notices, editorial exclusions). The admin console
    keeps seeing everything. ``date_from``/``date_to`` select a window (at most
    MAX_RANGE_DAYS) instead of one day: dated sessions inside the window come
    first, ordered by date, then one-day acts, then programmes and exhibitions."""
    date=day or date
    if date and not parse_date(date):raise ValueError('Fecha no válida')
    window=None
    if date_from or date_to:
        if date: raise ValueError('Usa day o date_from/date_to, no ambos')
        start=parse_date(date_from) or today(); end=parse_date(date_to) or (start+dt.timedelta(days=MAX_RANGE_DAYS))
        if (date_from and not parse_date(date_from)) or (date_to and not parse_date(date_to)): raise ValueError('Fecha no válida')
        if end<start: raise ValueError('Rango de fechas no válido')
        if (end-start).days>MAX_RANGE_DAYS: raise ValueError('El rango máximo es de %d días' % MAX_RANGE_DAYS)
        window=(start.isoformat(),end.isoformat())
    if hour_from is not None and not 0<=hour_from<=23:raise ValueError('Hora inicial no válida')
    if hour_to is not None and not 0<=hour_to<=23:raise ValueError('Hora final no válida')
    if hour_from is not None and hour_to is not None and hour_from>hour_to:raise ValueError('Rango horario no válido')
    if page<1 or page>9999:raise ValueError('Página no válida')
    if page_size<1 or page_size>100:raise ValueError('Tamaño de página no válido')
    events=all_events(conn)
    # A candidate occurrence is date-specific, so make it the listing time
    # before applying the hour filter (rather than only after matching).
    if date:
        for event in events:
            times=[o['time'] for o in event['occurrences'] if o['date']==date and o['time']]
            event['time']=times[0] if times else event.get('time')
    elif window:
        for event in events:
            inside=[o for o in event['occurrences'] if window[0]<=o['date']<=window[1]]
            event['occurrence_date']=inside[0]['date'] if inside else None
            if inside and inside[0]['time']: event['time']=inside[0]['time']
    match=[]; term=clean(query)
    started_cutoff=(today()-dt.timedelta(days=STARTED_GRACE_DAYS)).isoformat()
    earliest_hour=0 if hour_from is None else hour_from
    latest_hour=23 if hour_to is None else hour_to
    has_hour_filter=hour_from is not None or hour_to is not None
    for e in events:
        if term and term not in clean(e['title']+' '+' '.join(e['venue_names'])):continue
        if date and not (e['start']<=date<=e['end']):continue
        if window and not (e['start']<=window[1] and e['end']>=window[0]):continue
        if category and e['category']!=category:continue
        if public and not is_public(e):continue
        if public_category=='Familia':
            if not e['family_audience']:continue
        elif public_category and e['public_category']!=public_category:continue
        if subtype and e.get('subtype')!=subtype:continue
        if format and e['format']!=format:continue
        if free and not e['is_free']:continue
        if district and e['district']!=district:continue
        if source and e['source']!=source:continue
        if status and e['status']!=status:continue
        if kind and e['kind']!=kind:continue
        if has_hour_filter:
            hours=event_hours(e.get('time'))
            if not hours or not any(earliest_hour<=hour<=latest_hour for hour in hours):continue
        # A course or programme that began more than STARTED_GRACE_DAYS ago
        # usually cannot be joined any more; the public default hides it and a
        # switch brings it back. Exhibitions and one-day acts are unaffected.
        if not include_started and e['kind'] in ('course','program') and e['start']<started_cutoff:continue
        if only_sessions:
            if not e['occurrences']:
                continue
            if date and not any(occ['date']==date for occ in e['occurrences']):
                continue
        match.append(e)
    # Featured cards deliberately prioritize imminent records with a local image.
    if curated:
        week_start=(parse_date(date) or today()).isoformat()
        positions={(r[0],r[1]):r[2] for r in conn.execute('SELECT source,id,position FROM curated_picks WHERE week_start=?',(week_start,))}
        if positions:
            match=[e for e in match if (e['source'],e['id']) in positions]
            match.sort(key=lambda e:(positions[(e['source'],e['id'])],e['title'].casefold()))
            match=match[:5]
        else:
            featured=True
    if featured:
        baseline=(parse_date(date) or today()).isoformat()
        horizon=(parse_date(baseline)+dt.timedelta(days=13)).isoformat()
        match=[e for e in match if e['end']>=baseline and e['start']<=horizon and e['eligibility']!='exclude']
        for event in match:
            event['featured_score'],event['featured_reasons']=featured_score(event,baseline)
        match.sort(key=lambda e:(-e['featured_score'],featured_rotation(e,baseline)))
        match=spread_venues(match)
    # Show useful upcoming items first. A long program spanning the selected
    # day is weaker evidence than an explicit dated candidate or a one-day act.
    elif window:
        def rank(e):
            if e.get('occurrence_date'):return 0
            if e['start']==e['end'] or (is_short_span(e) and e.get('time')):return 1
            if e['kind']=='program':return 2
            if e['kind']=='exhibition':return 3
            return 4
        def when(e): return e.get('occurrence_date') or max(e['start'],window[0])
        # Chronological by start (or session) date for everything that starts
        # inside the period; what was already running before it comes after,
        # newest first, so a 30-day view opens with what is about to happen.
        def running_before(e): return not e.get('occurrence_date') and e['start']<window[0]
        match.sort(key=lambda x:(1 if running_before(x) else 0,_reverse_date(x['start']) if running_before(x) else when(x),rank(x),x['title'].casefold()))
    elif date:
        def rank(e):
            has_time=any(o['date']==date for o in e['occurrences']) or (is_short_span(e) and bool(e.get('time')))
            if has_time:return 0
            if e['start']==e['end']==date:return 1
            if e['kind']=='exhibition':return 2
            if e['kind']=='program':return 3
            return 4
        # Timed sessions by time; among running items, the most recently
        # started first (what opened this week before what opened in spring).
        match.sort(key=lambda x:(rank(x),(x.get('time') or '99:99') if rank(x)==0 else '',_reverse_date(x['start']) if rank(x)>=2 else '',x['title'].casefold()))
    else:
        baseline=today().isoformat()
        def rank(e):
            if e['eligibility']=='exclude':return 4
            if e['kind']=='single':return 0
            if e['kind']=='exhibition':return 2
            return 3
        match.sort(key=lambda x:(max(x['start'],baseline),rank(x),x['title'].casefold()))
    start_idx=(page-1)*page_size
    return {'items':match[start_idx:start_idx+page_size], 'total':len(match),'page':page, 'page_size':page_size, 'pages':(len(match)+page_size-1)//page_size,'limitations':{'date_filter':'Los intervalos de programas y exposiciones no acreditan sesión en el día.','district_filter':'Solo distritos indicados explícitamente por la fuente, sin geocodificación inferida.','sources':'Datos recogidos automáticamente de fuentes públicas; confirma horarios y condiciones en la fuente.','public_filter':'Con public=1 se ocultan registros excluidos por la fuente o por la redacción.'}}


def districts(conn, day=''):
    start=parse_date(day) or today()
    until=(start+dt.timedelta(days=13)).isoformat(); counts={}
    for event in all_events(conn):
        if not is_public(event): continue
        if event['district'] and event['district']!='Varios distritos' and event['end']>=start.isoformat() and event['start']<=until:
            counts[event['district']]=counts.get(event['district'],0)+1
    return [{'name':name,'count':count} for name,count in sorted(counts.items(),key=lambda x:(-x[1],x[0]))]


def save_curated_pick(conn, source, record_id, position, week_start):
    if not isinstance(position,int) or not 0<=position<=99:raise ValueError('Posición de selección no válida')
    if not parse_date(week_start):raise ValueError('Inicio de semana no válido')
    if not conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(source,record_id)).fetchone():raise LookupError('Actividad no encontrada')
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute('''INSERT INTO curated_picks(source,id,position,week_start,created_at) VALUES(?,?,?,?,?)
          ON CONFLICT(source,id,week_start) DO UPDATE SET position=excluded.position,created_at=excluded.created_at''',(source,record_id,position,week_start,now))
    invalidate_cache()
    return {'source':source,'id':record_id,'position':position,'week_start':week_start,'updated_at':now}


_VENUE_INDEX={'fingerprint':None,'by_hall':{}}


def _venue_index(conn):
    """{hall key: [events]} over the public listing, rebuilt only when the
    listing changes; exporting 9.000 details must not scan 15.000 records each."""
    from src.venue_directory import normalise, site_for
    events=all_events(conn); stamp=(_LISTING_CACHE['fingerprint'],_LISTING_CACHE['built_at'],len(events))
    if _VENUE_INDEX['fingerprint']!=stamp:
        by_hall={}
        for e in events:
            if not is_public(e): continue
            for n in e['venue_names']:
                key=(site_for(n) or {}).get('slug') or normalise(n)
                if key: by_hall.setdefault(key,[]).append(e)
        _VENUE_INDEX.update(fingerprint=stamp,by_hall=by_hall)
    return _VENUE_INDEX['by_hall']


def venue_upcoming(conn, event, limit=6):
    """Other public records at the same hall from today on, soonest first:
    what the detail sheet shows under "Próximamente en <sala>"."""
    from src.venue_directory import normalise, site_for
    hall=lambda n:(site_for(n) or {}).get('slug') or normalise(n)
    names={hall(n) for n in event.get('venue_names',[]) if normalise(n)}
    if not names: return []
    index=_venue_index(conn); baseline=today().isoformat(); out=[]; seen=set()
    for name in names:
        for other in index.get(name,[]):
            if other['key']==event['key'] or other['key'] in seen or other['end']<baseline: continue
            seen.add(other['key'])
            dated=[o['date'] for o in other['occurrences'] if o['date']>=baseline]
            when=min(dated) if dated else max(other['start'],baseline)
            out.append((when,0 if dated or other['start']==other['end'] else 1,other))
    out.sort(key=lambda x:(x[0],x[1],x[2]['title'].casefold()))
    return [{'key':o['key'],'source':o['source'],'id':o['id'],'title':o['title'],'date':when,'time':next((x['time'] for x in o['occurrences'] if x['date']==when and x['time']),None) or (o.get('time') if o['start']==o['end'] else None),
             'public_category':o['public_category'],'subtype':o.get('subtype'),'is_free':o['is_free'],'kind':o['kind'],'start':o['start'],'end':o['end']} for when,_,o in out[:limit]]


def event_detail(conn,source,id,day=''):
    row=conn.execute('''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,
               r.evidence_level,r.source_url,r.raw_json, e.status,e.note,e.updated_at
               FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id
               WHERE r.source=? AND r.id=?''',(source,id)).fetchone()
    if not row:return None
    if day and not parse_date(day): raise ValueError('Fecha no válida')
    event=row_to_event(conn,row,True,day)
    event['venue_upcoming']=venue_upcoming(conn,event)
    return event


def stats(conn):
    items=all_events(conn)
    def grouped(key):
        d={}
        for e in items:d[e[key]]=d.get(e[key],0)+1
        return d
    has_sync=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_runs'").fetchone()
    sync=[]
    if has_sync:
        sync=[{'source':r[0],'status':r[1],'finished_at':r[2],'rows_received':r[3],'rows_mutated':r[4]} for r in conn.execute('''SELECT source,status,finished_at,rows_received,rows_mutated FROM sync_runs
          WHERE id IN (SELECT MAX(id) FROM sync_runs GROUP BY source) ORDER BY source''')]
    return {'total':len(items),'candidate_occurrences':sum(len(x['occurrences']) for x in items),'published':sum(1 for x in items if x['published']),
            'sources':grouped('source'),'kinds':grouped('kind'),'statuses':grouped('status'),
            'district_known':sum(bool(x['district']) for x in items),'district_unknown':sum(not x['district'] for x in items),
            'by_category':grouped('category'),'source_date_start':min((x['start'] for x in items),default=None),'source_date_end':max((x['end'] for x in items),default=None),
            'excluded_by_source':sum(1 for x in items if x['eligibility']=='exclude'),'family_audience':sum(1 for x in items if x['family_audience']),
            'provisional_taxonomy':True,'sync_runs':sync}


def save_review(conn, source, id, status, note):
    if status not in STATUS:raise ValueError('Estado de revisión no permitido')
    note=note.strip()
    if len(note)>2000:raise ValueError('Nota demasiado larga (máx. 2.000 caracteres)')
    if status in ('reviewed','excluded') and len(note)<8:raise ValueError('Añade una nota explicando la decisión (mín. 8 caracteres)')
    if not conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone():raise LookupError('Actividad no encontrada')
    old=conn.execute('SELECT status,note FROM editorial_reviews WHERE source=? AND id=?',(source,id)).fetchone()
    prev=old or ('pending','')
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute('''INSERT INTO editorial_reviews(source,id,status,note,updated_at) VALUES(?,?,?,?,?)
            ON CONFLICT(source,id) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=excluded.updated_at''',(source,id,status,note,now))
        conn.execute('INSERT INTO editorial_review_log(source,id,old_status,new_status,old_note,new_note,changed_at) VALUES(?,?,?,?,?,?,?)',
            (source,id,prev[0],status,prev[1],note,now))
    invalidate_cache()
    return {'status':status,'note':note,'updated_at':now,'published':False}


def save_field_verification(conn, source, id, field_name, value, evidence_url, checked_on, note=''):
    allowed={'title','start','end','time_text','price_text','venue','organizer','category','district','neighborhood','occurrence'}
    if field_name not in allowed:raise ValueError('Campo verificable no permitido')
    if not isinstance(value,(str,int,float,bool,dict,list)) or value in ('',None):raise ValueError('Valor verificado requerido')
    if not isinstance(evidence_url,str) or not evidence_url.startswith('https://'):raise ValueError('URL HTTPS de evidencia requerida')
    if not parse_date(checked_on):raise ValueError('Fecha de comprobación no válida')
    note=note.strip()
    if len(note)>2000:raise ValueError('Nota demasiado larga (máx. 2.000 caracteres)')
    if not conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone():raise LookupError('Actividad no encontrada')
    encoded=json.dumps(value,ensure_ascii=False,sort_keys=True);now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    old=conn.execute('SELECT value_json FROM field_verifications WHERE source=? AND id=? AND field_name=?',(source,id,field_name)).fetchone()
    with conn:
        conn.execute('''INSERT INTO field_verifications(source,id,field_name,value_json,evidence_url,checked_on,note,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source,id,field_name) DO UPDATE SET value_json=excluded.value_json,evidence_url=excluded.evidence_url,checked_on=excluded.checked_on,note=excluded.note,updated_at=excluded.updated_at''',(source,id,field_name,encoded,evidence_url,checked_on,note,now))
        conn.execute('INSERT INTO field_verification_log(source,id,field_name,old_value_json,new_value_json,evidence_url,checked_on,changed_at) VALUES(?,?,?,?,?,?,?,?)',(source,id,field_name,old[0] if old else None,encoded,evidence_url,checked_on,now))
    invalidate_cache()
    return {'field':field_name,'value':value,'evidence_url':evidence_url,'checked_on':checked_on,'updated_at':now}


def save_publication_decision(conn, source, id, status, note):
    if status not in ('draft','blocked','approved'):raise ValueError('Estado de publicación no permitido')
    if not conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone():raise LookupError('Actividad no encontrada')
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute('''INSERT INTO publication_decisions(source,id,status,note,decided_at) VALUES(?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET status=excluded.status,note=excluded.note,decided_at=excluded.decided_at''',(source,id,status,note.strip(),now))
    # `published` is a local API flag. The HTTP server remains bound to 127.0.0.1.
    invalidate_cache()
    return {'status':status,'note':note.strip(),'updated_at':now,'published':status=='approved'}
