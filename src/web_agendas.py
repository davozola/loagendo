"""Small, auditable collectors for public cultural agendas.

These collectors deliberately target published agenda pages, never infer a
deletion from a page and preserve source metadata for each record. Discovery
sources are explicitly marked as such and can only contribute local-preview
references whose rights status remains unknown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import time
import re
import ssl
import subprocess
from urllib.parse import parse_qs, urlparse, unquote
from urllib.error import URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from src.pipeline import delta, event_kind
from src.media import register
from src.network import tls_context
from mvp.catalog import initialize as initialize_catalog
from src.sync import _upsert_record, initialize, now_utc

SOURCES = {
    'web_macba': {'url': 'https://www.macba.cat/es/agenda/', 'venue': 'MACBA', 'address': 'Plaça dels Àngels, 1, 08001 Barcelona'},
    'web_cccb': {'url': 'https://www.cccb.org/es/calendario', 'venue': 'CCCB', 'address': 'Carrer de Montalegre, 5, 08001 Barcelona'},
    'web_teatre_lliure': {'url': 'https://www.teatrelliure.com/es/temporada-26-27', 'venue': 'Teatre Lliure', 'address': 'Barcelona'},
    'web_auditori': {'url': 'https://www.auditori.cat/es/lauditori-temporada-2026-2027/', 'venue': "L'Auditori", 'address': 'Carrer de Lepant, 150, 08013 Barcelona'},
    # Drupal pager: page 0 is the base URL, later pages are /p/page/N. The list
    # is ordered by publication and quickly turns into an archive, so the
    # collector stops at the first page without any item marked `vigent`.
    'web_centres_civics': {'url': 'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural', 'page_url': 'https://ajuntament.barcelona.cat/centrescivics/ca/programacio-cultural/p/page/{page}', 'venue': 'Xarxa de Centres Cívics de Barcelona', 'address': 'Barcelona', 'pages': 8, 'first_page': 0, 'continue_marker': 'vigent'},
    'web_conciertos_club': {'url': 'https://conciertos.club/barcelona', 'venue': 'Barcelona', 'address': 'Barcelona'},
    # GRAF (graf.cat): agenda común de ~130 espacios de creación contemporánea de Catalunya
    # (galerías, centros de arte, festivales). Inauguraciones, performances, proyecciones,
    # charlas. Feed iCal completo (fechas, horas, espacio, coordenadas, imagen) + ficha de cada
    # acto (dirección, texto, precio, web propia). Decisión de David (20-10-2026): se usa todo,
    # con crédito a GRAF y al espacio. La ciudad se comprueba en la ficha: solo Barcelona.
    'web_graf': {'url': 'https://graf.cat/feed/eo-events/', 'venue': 'GRAF', 'address': 'Catalunya', 'max_bytes': 16_000_000, 'timeout': 120, 'retries': 1},
}

MONTHS = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12,
          'gener':1,'febrer':2,'març':3,'abril':4,'maig':5,'juny':6,'juliol':7,'agost':8,'setembre':9,'octubre':10,'novembre':11,'desembre':12}

def fetch(url, timeout=30, max_bytes=4_000_000):
    request=Request(url,headers={'Accept':'text/html','User-Agent':'Brollant/1.3 (+https://brollant.com) agenda collector'})
    try:
        with urlopen(request,timeout=timeout,context=tls_context()) as response:  # nosec B310: fixed first-party URLs above
            if not 200 <= response.status < 300: raise RuntimeError('HTTP %s' % response.status)
            return response.read(max_bytes).decode('utf-8','replace')
    except URLError as error:
        # Some macOS Python distributions ship a CA bundle that does not yet
        # include a valid issuer used by a first-party cultural site.  The
        # system curl uses the OS trust store and still verifies TLS by
        # default; it is a narrow fallback, never an insecure retry.
        if not isinstance(error.reason, ssl.SSLCertVerificationError): raise
        result=subprocess.run(
            ['/usr/bin/curl','--fail','--silent','--show-error','--location',
             '--max-time',str(timeout),url], check=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout+5,
        )
        return result.stdout[:max_bytes].decode('utf-8','replace')

def fetch_pages(cfg, fetcher, timeout):
    """Fetch the configured pages, stopping early when a page has no current item."""
    first=cfg.get('first_page',1); count=cfg.get('pages',1); marker=cfg.get('continue_marker')
    out=[]
    for index in range(first,first+count):
        url=cfg['url'] if index==first and 'page_url' in cfg else cfg.get('page_url',cfg['url']).format(page=index)
        if fetcher is fetch:
            # Feed grande y lento de generar (GRAF, 16 MB): más margen y un reintento si el servidor se queda callado.
            wait=max(timeout,cfg.get('timeout',0))
            for attempt in range(1+cfg.get('retries',0)):
                try: body=fetcher(url,wait,cfg['max_bytes']) if 'max_bytes' in cfg else fetcher(url,wait); break
                except (TimeoutError,OSError) as error:
                    if attempt>=cfg.get('retries',0): raise
                    time.sleep(10)
        else: body=fetcher(url,timeout)
        out.append((url,body))
        if marker and marker not in body: break
        if out and len(out)>1 and body==out[-2][1]: break  # identical page: pagination not effective
    return out


def _iso(value):
    """Normalise a source date to YYYY-MM-DD.

    Google Calendar links (MACBA) use the compact ``20261012T180000Z`` form,
    which ``datetime.fromisoformat`` only accepts from Python 3.11. Parse it
    explicitly so the collector behaves the same on every interpreter.
    """
    value=(value or '').strip()
    compact=re.fullmatch(r'(\d{4})(\d{2})(\d{2})(?:T\d{2}\d{2}(?:\d{2})?Z?)?',value)
    if compact:return '-'.join(compact.groups())
    value=value.replace('Z','+00:00')
    try:return dt.datetime.fromisoformat(value).date().isoformat()
    except ValueError:return value[:10]

def _record(source, title, start, end, url, venue, address, raw, time_text='', image=''):
    key=hashlib.sha256((source+'\0'+url+'\0'+start+'\0'+title).encode()).hexdigest()[:24]
    kind, eligibility=event_kind(title,'',delta(start,end),time_text,source)
    return {'source':source,'id':key,'title':title.strip(),'start':start,'end':end or start,
      'time_text':time_text,'price_text':'','kind':kind,'eligibility':eligibility,
      'start_timestamp':'','frequency':'','raw':{'source_page':SOURCES[source]['url'],'item':raw,'image':image},
      'venues':[{'name':venue,'address':address,'coords':None}], 'organizers':[venue], 'url':url,
      'alerts':['DIRECT_FIRST_PARTY_WEB_PAGE','SCHEDULE_UNVERIFIED','NO_PRICE_TEXT'],
      'evidence_level':'first_party_web_page_unverified'}

def parse_macba(page):
    source='web_macba'; cfg=SOURCES[source]; result=[]
    for block in re.split(r'<div class="w-100 macba-fitxa[^>]*activitat-card[^>]*>',page)[1:]:
        block=block[:block.find('<div class="w-100 macba-fitxa')] if '<div class="w-100 macba-fitxa' in block else block
        calendar=re.search(r'href="(https://calendar\.google\.com/calendar/render\?[^"]+)"',block)
        title=re.search(r'aria-label="([^"]+)"',block)
        link=re.search(r'<a href="(https://www\.macba\.cat/[^"]+)" class="text-decoration-none"',block)
        if not (calendar and title and link): continue
        query=parse_qs(urlparse(html.unescape(calendar.group(1))).query); dates=query.get('dates',['/'])[0].split('/')
        if len(dates)!=2: continue
        start,end=_iso(dates[0]),_iso(dates[1])
        image=re.search(r'<img[^>]+src="([^"]+)"',block)
        result.append(_record(source,html.unescape(title.group(1)),start,end,html.unescape(link.group(1)),cfg['venue'],cfg['address'],{'calendar':query},image=html.unescape(image.group(1)) if image else ''))
    return result

def parse_cccb(page):
    source='web_cccb'; cfg=SOURCES[source]; result=[]; month=dt.date.today().month; year=dt.date.today().year
    tokens=re.split(r'(<h2[^>]*>\s*[^<]+\s+20\d\d\s*</h2>|<div class="mp-component mp-component-agenda-card[^>]*>)',page,flags=re.I)
    for token in tokens:
        heading=re.search(r'>\s*([A-Za-zÀ-ÿ]+)\s+(20\d\d)\s*<',token)
        if heading and heading.group(1).casefold() in MONTHS: month,year=MONTHS[heading.group(1).casefold()],int(heading.group(2)); continue
        day=re.search(r'agenda-card-date-num">\s*(\d{1,2})',token)
        if not day: continue
        date=f'{year:04d}-{month:02d}-{int(day.group(1)):02d}'
        for item in re.split(r'<li class="agenda-card-item[^>]*>',token)[1:]:
            link=re.search(r'<a href="([^"]+)" title="([^"]+)"',item); title=re.search(r'agenda-card-title">\s*(.*?)\s*</p>',item,re.S); time=re.search(r'agenda-card-date-time">\s*([^<]+)',item)
            if not link or not title: continue
            image=re.search(r'<img[^>]+src="([^"]+)"',item)
            name=html.unescape(re.sub('<[^>]+>',' ',title.group(1))).strip()
            # Disciplina que el CCCB pone sobre el título («Audiovisuales», «Debates», «Escena»…).
            pretitle=re.search(r'agenda-card-pretitle[^"]*">\s*<span>([^<]*)</span>\s*([^<]*)',item)
            discipline=html.unescape(pretitle.group(1)).strip() if pretitle else ''
            series=html.unescape(pretitle.group(2)).strip() if pretitle else ''
            when=html.unescape(time.group(1)).strip() if time else ''; start=end=date
            # Exposiciones: en el lugar de la hora el CCCB pone su periodo («23 octubre - 1 diciembre 2026»).
            span=re.match(r'(\d{1,2})\s+([a-zà-ÿ]+)\s*[-–]\s*(\d{1,2})\s+([a-zà-ÿ]+)\s+(20\d\d)$',when.casefold())
            if span and span.group(2) in MONTHS and span.group(4) in MONTHS:
                m1,m2,y2=MONTHS[span.group(2)],MONTHS[span.group(4)],int(span.group(5))
                start=f'{(y2 if m1<=m2 else y2-1):04d}-{m1:02d}-{int(span.group(1)):02d}'; end=f'{y2:04d}-{m2:02d}-{int(span.group(3)):02d}'; when=''
            result.append(_record(source,name,start,end,html.unescape(link.group(1)),cfg['venue'],cfg['address'],{'page_title':html.unescape(link.group(2)),'discipline':discipline,'series':series},when,html.unescape(image.group(1)) if image else ''))
    return result

def parse_teatre_lliure(page):
    source='web_teatre_lliure'; cfg=SOURCES[source]; result=[]
    blocks=re.split(r'(?=<li class="\s*filter-show-)',page)
    for block in blocks[1:]:
        title=re.search(r'<h3[^>]*>\s*<a href="([^"]+)" title="([^"]+)"',block,re.S)
        period=re.search(r'<dd class="outcome">\s*(\d{1,2}/\d{1,2})\s*[—-]\s*(\d{1,2}/\d{1,2}/\d{2,4})',block)
        room=re.search(r'##general\.room##:</dt>\s*<dd class="outcome">\s*([^<]+)',block,re.S)
        image=re.search(r"<img src='([^']+)'",block)
        if not (title and period): continue
        start_day,end_full=period.groups(); day,month=map(int,start_day.split('/')); end_day,end_month,end_year=map(int,end_full.split('/'))
        if end_year<100: end_year+=2000
        start_year=end_year if month<=end_month else end_year-1
        start=f'{start_year:04d}-{month:02d}-{day:02d}'; end=f'{end_year:04d}-{end_month:02d}-{end_day:02d}'
        url='https://www.teatrelliure.com'+html.unescape(title.group(1))
        result.append(_record(source,html.unescape(title.group(2)),start,end,url,html.unescape(room.group(1)).strip() if room else cfg['venue'],cfg['address'],{'period':period.group(0)},image='https:'+html.unescape(image.group(1)) if image else ''))
    return result

def parse_auditori(page):
    source='web_auditori'; cfg=SOURCES[source]; result=[]
    match=re.search(r'window\.aPnextevents\s*=\s*JSON\.parse\(decodeURIComponent\(\'([^\']+)\'\)\)',page)
    if not match: return result
    try: events=json.loads(unquote(match.group(1))).get('events',[])
    except (ValueError,TypeError): return result
    for event in events:
        title=(event.get('wp_post') or {}).get('post_title',''); stamp=event.get('event_next_date')
        if not title or not stamp: continue
        # The embedded JSON gives the next session as a Unix timestamp; the
        # local wall-clock time in Europe/Madrid is the published start time.
        moment=dt.datetime.fromtimestamp(int(stamp),dt.timezone.utc).astimezone(ZoneInfo('Europe/Madrid'))
        start=moment.date().isoformat(); hall=((event.get('hall_obj') or {}).get('wp_post') or {}).get('post_title') or cfg['venue']
        time_text=moment.strftime('%H:%M') if moment.strftime('%H:%M')!='00:00' else ''
        image=re.search(r'src="([^"]+)"',event.get('image_html',''))
        record=_record(source,title,start,start,event.get('link',''),hall,cfg['address'],event,time_text,html.unescape(image.group(1)) if image else '')
        record['time_evidence_field']='event_next_date'
        record['price_text']=html.unescape(event.get('price_text',''))
        result.append(record)
    return result

def parse_centres_civics(page):
    source='web_centres_civics'; cfg=SOURCES[source]; result=[]
    for block in re.split(r'(?=<li class="views-row)',page)[1:]:
        link=re.search(r'views-field-title-field.*?<a href="([^"]+)"[^>]*>(.*?)</a>',block,re.S)
        venue=re.search(r'views-field-field-activitat-on.*?field-content">\s*(.*?)\s*</div>',block,re.S)
        when=re.search(r'views-field-field-activitat-quan.*?field-content">\s*(.*?)\s*</div>',block,re.S)
        if not (link and when): continue
        text=html.unescape(re.sub('<[^>]+>',' ',when.group(1))).strip(); dates=re.findall(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?',text)
        if not dates: continue
        year=next((int(y) for _,_,y in reversed(dates) if y),dt.date.today().year)
        first,last=dates[0],dates[-1]
        start=f'{year:04d}-{int(first[1]):02d}-{int(first[0]):02d}'; end=f'{year:04d}-{int(last[1]):02d}-{int(last[0]):02d}'
        if end < start: end=f'{year+1:04d}-{int(last[1]):02d}-{int(last[0]):02d}'
        # «Fins al 31/10/2026» states only the end: the activity is already
        # running, so the start is the collection date, never a guessed one.
        if re.match(r'\s*fins',text,re.I) and len(dates)==1: start=min(dt.date.today().isoformat(),end)
        url='https://ajuntament.barcelona.cat'+html.unescape(link.group(1))
        image=re.search(r'<img[^>]+src="([^"]+)"',block)
        record=_record(source,html.unescape(re.sub('<[^>]+>',' ',link.group(2))).strip(),start,end,url,html.unescape(re.sub('<[^>]+>',' ',venue.group(1))).strip() if venue else cfg['venue'],cfg['address'],{'when':text},image=html.unescape(image.group(1)) if image else '')
        if 'vigent' not in block: record['alerts'].append('SOURCE_PAGE_NOT_MARKED_CURRENT')
        result.append(record)
    return result

def parse_conciertos_club(page):
    """Read schema.org MusicEvent blocks, keeping only Barcelona city.

    It remains a discovery listing.  Its artwork is retained only as an
    auditable *local preview reference* (with unknown rights); no prose or
    ticket affiliate URL is copied (the ticket link is unwrapped to the vendor's own page) and it
    must not be promoted for publishing.
    """
    source='web_conciertos_club'; result=[]
    for block in re.split(r'<div\s+itemscope\s+itemprop="item"\s+itemtype="http://schema\.org/MusicEvent">',page,flags=re.I)[1:]:
        start=re.search(r'<meta\s+itemprop="startDate"\s+content="([^"]+)"',block,re.I)
        end=re.search(r'<meta\s+itemprop="endDate"\s+content="([^"]+)"',block,re.I)
        displayed=re.search(r'<div\s+class="time">\s*[A-ZÁÉÍÓÚÜ]?(\d{1,2})/(\d{1,2})/(\d{2,4})\s*<br\s*/?>\s*(\d{2}:\d{2})',block,re.I)
        locality=re.search(r'<meta\s+itemprop="addressLocality"\s+content="([^"]+)"',block,re.I)
        location=re.search(r'<div\s+itemprop="location".*?<meta\s+itemprop="name"\s+content="([^"]+)"',block,re.I|re.S)
        event_name=re.search(r'<meta\s+itemprop="name"\s+content="([^"]+)"\s*/?>\s*<meta\s+itemprop="url"',block,re.I)
        image=re.search(r'<meta\s+itemprop="image"\s+content="([^"]+)"',block,re.I)
        urls=re.findall(r'<meta\s+itemprop="url"\s+content="([^"]+)"',block,re.I)
        if not (start and displayed and locality and location and event_name and urls):continue
        # The page's Barcelona section also includes metropolitan municipalities.
        if not locality.group(1).strip().casefold().startswith('barcelona,'):continue
        stamp=start.group(1); day,month,year,time=displayed.groups(); year=int(year)+(2000 if len(year)==2 else 0); date=f'{year:04d}-{int(month):02d}-{int(day):02d}'
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):continue
        title=html.unescape(event_name.group(1)).strip().rstrip('.').strip(); url=html.unescape(urls[0])
        image_url=html.unescape(image.group(1)).strip() if image else ''
        # Precio («Precio entrada desde 20€») y entradas: la ticketera de verdad, sin el enlace de
        # afiliado del directorio (fever.pxf.io/…?u=https://feverup.com/m/…) ni su tienda propia.
        price=re.search(r'class="precio"\s+title="Precio entrada (desde\s+)?([\d.,]+)\s*(?:€|&euro;|&#8364;)"',block,re.I)
        buy=re.search(r'class="comprarentradas"\s+href="([^"]+)"',block,re.I); ticket=''
        if buy:
            target=html.unescape(buy.group(1)); q=parse_qs(urlparse(target).query).get('u',[''])[0]
            ticket=q if q.startswith('https://') else (target if 'conciertos.club' not in urlparse(target).netloc and 'pxf.io' not in urlparse(target).netloc else '')
        record=_record(source,title,date,date,url,html.unescape(location.group(1)),html.unescape(locality.group(1)),{'parser_version':'conciertos-club-v4','schema_startDate':stamp,'schema_endDate':end.group(1) if end else '', 'schema_url':url, 'displayed_session_date':date,'ticket_url':ticket},time,image_url)
        if price: record['price_text']=('Desde ' if price.group(1) else '')+price.group(2)+' €'
        record['evidence_level']='third_party_listing_unverified'; record['alerts']=['THIRD_PARTY_DISCOVERY_LISTING','SCHEDULE_UNVERIFIED','LOCAL_MEDIA_RIGHTS_UNVERIFIED','NO_COPIED_DESCRIPTION']
        result.append(record)
    return result

MADRID = ZoneInfo('Europe/Madrid')


def _graf_text(fragment):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', fragment or '')).split())


def _ics_events(text):
    """VEVENTs del iCal como dicts {CAMPO: (parámetros, valor)}; desdobla líneas y escapes."""
    text = re.sub(r'\r?\n[ \t]', '', text.replace('\r\n', '\n'))
    out = []
    for block in text.split('BEGIN:VEVENT')[1:]:
        block = block.split('END:VEVENT')[0]; ev = {}
        for line in block.split('\n'):
            m = re.match(r'([A-Z-]+)((?:;[^:]*)?):(.*)', line)
            if not m: continue
            value = m.group(3).replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\').strip()
            ev.setdefault(m.group(1), []).append((m.group(2), value))
        out.append(ev)
    return out


def _ics_moment(params, value):
    """(fecha local, hora local 'HH:MM' o '') de un DTSTART/DTEND/RDATE."""
    if 'VALUE=DATE' in params or re.fullmatch(r'\d{8}', value):
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8])), ''
    m = re.fullmatch(r'(\d{8})T(\d{2})(\d{2})(\d{2})(Z?)', value)
    if not m: return None, ''
    moment = dt.datetime(int(value[:4]), int(value[4:6]), int(value[6:8]), int(m.group(2)), int(m.group(3)))
    moment = moment.replace(tzinfo=dt.timezone.utc).astimezone(MADRID) if m.group(5) else moment
    return moment.date(), moment.strftime('%H:%M')


def parse_graf(page, today=None, horizon_days=183):
    """Feed iCal de GRAF (Event Organiser: https://graf.cat/feed/eo-events/). Una ficha por
    sesión (las RDATE son sesiones adicionales); exposiciones y periodos, una ficha con su rango.
    Solo lo vigente: termina desde ayer y empieza en los próximos ``horizon_days`` días."""
    source = 'web_graf'; today = today or dt.date.today(); result = []
    first, last = today - dt.timedelta(days=1), today + dt.timedelta(days=horizon_days)
    for ev in _ics_events(page):
        get = lambda k: (ev.get(k) or [('', '')])[0]
        url = get('URL')[1]; title = get('SUMMARY')[1].strip()
        start, start_time = _ics_moment(*get('DTSTART')); end, end_time = _ics_moment(*get('DTEND'))
        if not (url and title and start): continue
        all_day = not start_time
        if end is None: end = start
        if all_day and end > start: end -= dt.timedelta(days=1)  # DTEND de día completo es exclusivo
        rrule = get('RRULE')[1]
        if rrule:
            until = re.search(r'UNTIL=(\d{8})', rrule)
            if until: end = max(end, dt.date(int(until.group(1)[:4]), int(until.group(1)[4:6]), int(until.group(1)[6:8])))
        sessions = [(start, end, start_time, end_time)]
        for params, value in ev.get('RDATE', []):
            for one in value.split(','):
                day, at = _ics_moment(params, one)
                if day and day != start: sessions.append((day, day, at or start_time, end_time))
        geo = get('GEO')[1]; coords = None
        if re.fullmatch(r'-?[\d.]+;-?[\d.]+', geo or ''):
            lat, lon = (float(x) for x in geo.split(';')); coords = (lat, lon)
        organizer = re.search(r'CN="?([^":]+)"?', get('ORGANIZER')[0] or '')
        organizer = organizer.group(1).strip() if organizer else ''
        location = get('LOCATION')[1].strip() or organizer
        category = get('CATEGORIES')[1].split(',')[0].strip()
        image = get('ATTACH')[1] if get('ATTACH')[1].startswith('https://') else ''
        uid = get('UID')[1]
        for day, until, at, until_time in sessions:
            if until < first or day > last: continue
            record = _record(source, title, day.isoformat(), until.isoformat(), url, location, '', {
                'parser_version': 'graf-ical-v1', 'graf_uid': uid, 'graf_category': category, 'graf_organizer': organizer,
                'time_end': until_time if until_time != at else '', 'rrule': rrule}, at, image)
            record['venues'][0]['coords'] = coords
            record['organizers'] = [organizer] if organizer else []
            if category.lower().startswith('exposici') and until > day: record['kind'] = 'exhibition'
            if category.lower().startswith('convocat'): record['eligibility'] = 'exclude'  # convocatorias para artistas
            record['evidence_level'] = 'third_party_listing_unverified'
            record['alerts'] = ['THIRD_PARTY_LISTING', 'SCHEDULE_UNVERIFIED']
            result.append(record)
    return result


def graf_detail(page):
    """De la ficha de GRAF: dirección, web propia del acto, precio, texto e imagen."""
    address = re.search(r'<div class="entry-venue-address[^"]*">(.*?)</div>', page, re.S)
    web = re.search(r'<a href="(https?://[^"]+)"[^>]*class="entry-website', page)
    price = re.search(r'<div class="entry-price[^"]*">\s*(?:Preu|Precio|Price)\s*:\s*(.*?)</div>', page, re.S)
    body = re.search(r'<div class="detail-section-main">(.*?)</div>\s*<div class="detail-section-image-col">', page, re.S) \
        or re.search(r'<div class="detail-section-main">(.*?)</div>', page, re.S)
    paragraphs = []
    if body:
        for chunk in re.split(r'(?i)</p>|<br\s*/?>|</li>|</h\d>', body.group(1)):
            line = _graf_text(chunk)
            if line: paragraphs.append(line)
    image = re.search(r'<meta property="og:image" content="([^"]+)"', page)
    return {'address': _graf_text(address.group(1)) if address else '', 'web': html.unescape(web.group(1)) if web else '',
            'price': _graf_text(price.group(1)) if price else '', 'description': '\n\n'.join(paragraphs)[:6000],
            'image': html.unescape(image.group(1)) if image else ''}


GRAF_SPACES_URL = 'https://graf.cat/espais/'


def graf_spaces(page):
    """Directorio de espacios de GRAF (/espais/ lleva «var venues = [...]»): nombre, dirección y
    horario de apertura tal como lo publica cada espacio. {nombre normalizado: espacio}."""
    m = re.search(r'var venues\s*=\s*(\[.*?\]);\s*\n', page or '', re.S)
    if not m: return {}
    try: items = json.loads(m.group(1))
    except json.JSONDecodeError: return {}
    out = {}
    for item in items:
        name = re.search(r'<h5>(.*?)</h5>', str(item.get('address') or ''), re.S)
        opening = '\n'.join(x.strip() for x in str((item.get('opening') or [''])[0] or '').replace('\u2028', '\n').splitlines() if x.strip())
        if not name or not opening: continue
        name = _graf_text(name.group(1))
        out[_space_key(name)] = {'name': name, 'slug': item.get('slug', ''), 'opening': opening[:600], 'source_url': GRAF_SPACES_URL}
    return out


def _space_key(name):
    import unicodedata
    text = unicodedata.normalize('NFKD', str(name or '')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def _match_space(spaces, name):
    """El espacio por su nombre; si no es idéntico, uno solo cuyo nombre (≥8 letras) esté
    contenido en el del lugar («Centre de les Arts Lliures - Fundació Joan Brossa»)."""
    key = _space_key(name)
    if not spaces or not key: return None
    if key in spaces: return spaces[key]
    found = [v for k, v in spaces.items() if len(k) >= 8 and (' %s ' % k) in (' %s ' % key)]
    return found[0] if len(found) == 1 else None


def in_barcelona(address):
    a = (address or '').lower()
    return bool(re.search(r'\b080\d\d\b', a)) or bool(re.search(r'\bbarcelona\s*$', a)) and not re.search(r'\b08[1-9]\d\d\b', a)


def _add_graf_details(conn, records, fetcher, timeout, budget=400, spaces=None):
    """Ficha de cada acto (una lectura por URL y pasada; lo ya leído se reaprovecha): dirección,
    texto, precio, web propia e imagen. Fuera de Barcelona o sin dirección → no elegible."""
    cache = {}
    for record in records:
        prev = conn.execute('SELECT raw_json FROM source_records WHERE source=? AND id=?', (record['source'], record['id'])).fetchone()
        item = (json.loads(prev[0]).get('item') or {}) if prev else {}
        detail = item.get('graf_detail') or cache.get(record['url'])
        if detail is None and budget > 0:
            try: detail = graf_detail(fetcher(record['url'], timeout))
            except Exception: detail = None
            budget -= 1
            if fetcher is fetch: time.sleep(1)
        if detail is not None:
            cache[record['url']] = detail
            record['raw']['item']['graf_detail'] = detail
            record['raw']['descripcio'] = detail['description']
            if detail['address']: record['venues'][0]['address'] = detail['address']
            if detail['price']: record['price_text'] = detail['price']
            if not record['raw'].get('image') and detail['image']: record['raw']['image'] = detail['image']
            if detail['web']: record['raw']['item']['event_web'] = detail['web']
        # Exposición de varios días en un espacio del directorio de GRAF: su horario de apertura,
        # tal cual y con su procedencia (20-10-2026). Un acto de un día no lo hereda.
        space = _match_space(spaces, record['venues'][0].get('name'))
        if space and record['start'] != record['end']:
            record['raw']['item']['space_opening'] = space
        address = (detail or {}).get('address', '')
        if not address or not in_barcelona(address):
            record['eligibility'] = 'exclude'; record['alerts'] = record['alerts'] + ['OUTSIDE_BARCELONA' if address else 'ADDRESS_UNKNOWN']


PARSERS={'web_graf':parse_graf,'web_macba':parse_macba,'web_cccb':parse_cccb,'web_teatre_lliure':parse_teatre_lliure,'web_auditori':parse_auditori,'web_centres_civics':parse_centres_civics,'web_conciertos_club':parse_conciertos_club}

SESSION_LINE = re.compile(r'^(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*(?:[–-]|,|a\s+les)\s*(\d{1,2})(?:[.:](\d{2}))?\s*h\b')


def centres_sessions(page):
    """Sesiones de la página de una actividad de centres cívics: «30/10 – 19.30 h» bajo el
    nombre de cada artista o película. Solo lo que la página escribe así; nada se deduce."""
    body = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', page)
    body = re.split(r'(?i)activitats\s+relacionades', body)[0]
    lines = [' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', x)).split()) for x in re.split(r'(?i)<br\s*/?>|</p>|</h\d>|</div>|</li>', body)]
    lines = [x for x in lines if x]
    out = []
    for n, line in enumerate(lines):
        m = SESSION_LINE.match(line)
        if not m: continue
        title = lines[n - 1] if n and len(lines[n - 1]) <= 90 and not SESSION_LINE.match(lines[n - 1]) else ''
        out.append({'day': int(m.group(1)), 'month': int(m.group(2)), 'year': int(m.group(3)) if m.group(3) else None,
                    'time': f'{int(m.group(4)):02d}:{m.group(5) or "00"}', 'title': title})
    return out


def _add_centres_sessions(conn, records, fetcher, timeout, budget=60):
    """Lee la página de cada actividad vigente (máx. ``budget`` por pasada; se reaprovecha
    lo leído en los últimos 3 días) para tener la hora y el nombre de cada sesión."""
    today = dt.date.today(); fresh = (today - dt.timedelta(days=3)).isoformat()
    for record in records:
        if record['end'] < today.isoformat(): continue
        prev = conn.execute('SELECT raw_json FROM source_records WHERE source=? AND id=?', (record['source'], record['id'])).fetchone()
        item = (json.loads(prev[0]).get('item') or {}) if prev else {}
        if item.get('sessions_checked', '') >= fresh:
            record['raw']['item'].update({k: item[k] for k in ('sessions', 'sessions_checked') if k in item}); continue
        if budget <= 0: continue
        try: page = fetcher(record['url'], timeout)
        except Exception: continue
        budget -= 1
        record['raw']['item'].update({'sessions': centres_sessions(page), 'sessions_checked': today.isoformat()})
        if fetcher is fetch: time.sleep(1)


def sync(conn, source, fetcher=fetch, timeout=30):
    if source not in SOURCES: raise ValueError('Fuente web no permitida')
    initialize(conn); initialize_catalog(conn); started=now_utc()
    with conn:
        run_id=conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES(?,?,?,?)",(source,started,'running','0')).lastrowid
    try:
        cfg=SOURCES[source]; pages=fetch_pages(cfg,fetcher,timeout); urls=[u for u,_ in pages]
        page='\n'.join(body for _,body in pages); records=PARSERS[source](page); mutated=0
        seen=set(); records=[r for r in records if not (r['id'] in seen or seen.add(r['id']))]
        if source=='web_centres_civics': _add_centres_sessions(conn,records,fetcher,timeout)
        if source=='web_graf':
            try: spaces=graf_spaces(fetcher(GRAF_SPACES_URL,timeout))
            except Exception: spaces={}
            _add_graf_details(conn,records,fetcher,timeout,spaces=spaces)
        with conn:
            for record in records:
                mutated+=int(_upsert_record(conn,run_id,record)[0])
                image=record['raw'].get('image','')
                if image.startswith(('https://','http://')):
                    if source=='web_graf':  # política de la fuente (registro): imagen autorizada por decisión editorial, crédito al espacio
                        organizer=(record['organizers'] or [''])[0]
                        register(conn,source,record['id'],image,alt=record['title'],credit=f"{organizer} · vía GRAF" if organizer else 'GRAF')
                    else:
                        register(conn,source,record['id'],image,alt=record['title'],credit=SOURCES[source]['venue'],rights_status='unknown')
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_mutated=?,warning_json=? WHERE id=?",(now_utc(),len(urls),len(records),mutated,'[]',run_id))
        return {'id':run_id,'source':source,'status':'completed','rows_received':len(records),'rows_mutated':mutated}
    except Exception as error:
        with conn: conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',warning_json=?,error=? WHERE id=?",(now_utc(),json.dumps([str(error)]),str(error),run_id))
        return {'id':run_id,'source':source,'status':'failed','rows_received':0,'rows_mutated':0,'error':str(error)}
