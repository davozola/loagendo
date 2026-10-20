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
    # charlas. Solo se guarda lo factual (título, fecha, hora, espacio, tipo, enlace); ni textos
    # ni imágenes. La ciudad se comprueba en la ficha de cada acto: solo Barcelona.
    'web_graf': {'url': 'https://graf.cat/agenda/', 'venue': 'GRAF', 'address': 'Catalunya'},
}

MONTHS = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12,
          'gener':1,'febrer':2,'març':3,'abril':4,'maig':5,'juny':6,'juliol':7,'agost':8,'setembre':9,'octubre':10,'novembre':11,'desembre':12}

def fetch(url, timeout=30):
    request=Request(url,headers={'Accept':'text/html','User-Agent':'Brollant/1.3 (+https://brollant.com) agenda collector'})
    try:
        with urlopen(request,timeout=timeout,context=tls_context()) as response:  # nosec B310: fixed first-party URLs above
            if not 200 <= response.status < 300: raise RuntimeError('HTTP %s' % response.status)
            return response.read(4_000_000).decode('utf-8','replace')
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
        return result.stdout[:4_000_000].decode('utf-8','replace')

def fetch_pages(cfg, fetcher, timeout):
    """Fetch the configured pages, stopping early when a page has no current item."""
    first=cfg.get('first_page',1); count=cfg.get('pages',1); marker=cfg.get('continue_marker')
    out=[]
    for index in range(first,first+count):
        url=cfg['url'] if index==first and 'page_url' in cfg else cfg.get('page_url',cfg['url']).format(page=index)
        body=fetcher(url,timeout); out.append((url,body))
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

GRAF_ITEM = re.compile(r'<div class="agenda-grid-item">(.*?)(?=<div class="agenda-grid-item">|</section>|$)', re.S)


def _graf_dates(text, today=None):
    """«20.10.2026» → (2026-10-20, 2026-10-20); «04.07 – 13.12» → del año en curso (o el que cuadre)."""
    today = today or dt.date.today()
    m = re.fullmatch(r'(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s*[–-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4}))?', text)
    if m:
        a = dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        b = dt.date(int(m.group(6)), int(m.group(5)), int(m.group(4))) if m.group(4) else a
        return a.isoformat(), b.isoformat()
    m = re.fullmatch(r'(\d{1,2})\.(\d{1,2})\s*[–-]\s*(\d{1,2})\.(\d{1,2})', text)
    if not m: return None
    a = dt.date(today.year, int(m.group(2)), int(m.group(1)))
    if a > today + dt.timedelta(days=200): a = a.replace(year=a.year - 1)
    b = dt.date(a.year, int(m.group(4)), int(m.group(3)))
    if b < a: b = b.replace(year=b.year + 1)
    return a.isoformat(), b.isoformat()


def _graf_text(fragment):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', fragment or '')).split())


def parse_graf(page, today=None):
    source = 'web_graf'; result = []
    for block in GRAF_ITEM.findall(page):
        url = re.search(r'<a[^>]+href="(https://graf\.cat/(?:es/|en/)?events/event/[^"]+)"', block)
        date = re.search(r'<div class="entry-date">(.*?)</div>', block, re.S)
        space = re.search(r'<h3 class="entry-author">(.*?)</h3>', block, re.S)
        titles = re.findall(r'<h4 class="entry-title">(.*?)</h4>', block, re.S)
        if not (url and date and space and titles): continue
        dates = _graf_dates(_graf_text(date.group(1)), today)
        if not dates: continue
        title = _graf_text(titles[0]); place = ''
        for extra in titles[1:]:
            m = re.search(r'Lloc\s*:\s*(.+)', _graf_text(extra))
            if m: place = m.group(1).strip()
        t_start = re.search(r'<span class="time-start">\s*([\d:]+)\s*</span>', block)
        t_end = re.search(r'<span class="time_end">\s*([\d:]+)\s*</span>', block)
        clock = lambda v: (f'{int(v.split(":")[0]):02d}:{(v.split(":") + ["00"])[1]:0>2}' if v and re.fullmatch(r'\d{1,2}(?::\d{2})?', v) else '')
        start_time = clock(t_start.group(1)) if t_start else ''
        end_time = clock(t_end.group(1)) if t_end else ''
        price = re.search(r'<div class="entry-price[^"]*">(.*?)</div>', block, re.S)
        category = re.search(r'<div class="entry-terms">.*?>([^<]+)</a>', block, re.S)
        cat = html.unescape(category.group(1)).strip() if category else ''
        venue = place or _graf_text(space.group(1))
        record = _record(source, title, dates[0], dates[1], html.unescape(url.group(1)), venue, '', {
            'parser_version': 'graf-v1', 'graf_space': _graf_text(space.group(1)), 'graf_place': place, 'graf_category': cat,
            'time_end': end_time, 'price_label': _graf_text(price.group(1)) if price else ''}, start_time)
        if cat.lower().startswith('exposici') and dates[0] != dates[1]: record['kind'] = 'exhibition'
        price_text = record['raw']['item']['price_label']
        if price_text: record['price_text'] = price_text
        record['organizers'] = [_graf_text(space.group(1))]
        record['evidence_level'] = 'third_party_listing_unverified'
        record['alerts'] = ['THIRD_PARTY_DISCOVERY_LISTING', 'SCHEDULE_UNVERIFIED', 'NO_COPIED_DESCRIPTION']
        result.append(record)
    return result


def graf_address(page):
    """Dirección de la ficha de GRAF («La Rambla, 7 08002 Barcelona») y su web propia."""
    address = re.search(r'<div class="entry-venue-address[^"]*">(.*?)</div>', page, re.S)
    web = re.search(r'<a href="(https?://[^"]+)"[^>]*class="entry-website', page)
    return (_graf_text(address.group(1)) if address else ''), (html.unescape(web.group(1)) if web else '')


def in_barcelona(address):
    a = (address or '').lower()
    return bool(re.search(r'\b080\d\d\b', a)) or bool(re.search(r'\bbarcelona\s*$', a)) and not re.search(r'\b08[1-9]\d\d\b', a)


def _add_graf_places(conn, records, fetcher, timeout, budget=220):
    """Dirección de cada acto (una lectura por ficha nueva; las ya conocidas se reaprovechan).
    Fuera de Barcelona → no elegible (se conserva, no se publica). Sin dirección todavía → no elegible."""
    for record in records:
        prev = conn.execute('SELECT raw_json FROM source_records WHERE source=? AND id=?', (record['source'], record['id'])).fetchone()
        item = (json.loads(prev[0]).get('item') or {}) if prev else {}
        if 'graf_address' in item:
            address, web = item['graf_address'], item.get('graf_web', '')
        elif budget > 0:
            try: address, web = graf_address(fetcher(record['url'], timeout))
            except Exception: address, web = None, ''
            budget -= 1
            if fetcher is fetch: time.sleep(1)
        else:
            address, web = None, ''
        if address is not None: record['raw']['item'].update({'graf_address': address, 'graf_web': web})
        if address: record['venues'][0]['address'] = address
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
        if source=='web_graf': _add_graf_places(conn,records,fetcher,timeout)
        with conn:
            for record in records:
                mutated+=int(_upsert_record(conn,run_id,record)[0])
                image=record['raw'].get('image','')
                if image.startswith(('https://','http://')):
                    register(conn,source,record['id'],image,alt=record['title'],credit=SOURCES[source]['venue'],rights_status='unknown')
            conn.execute("UPDATE sync_runs SET finished_at=?,status='completed',http_status=200,pages=?,rows_received=?,rows_mutated=?,warning_json=? WHERE id=?",(now_utc(),len(urls),len(records),mutated,'[]',run_id))
        return {'id':run_id,'source':source,'status':'completed','rows_received':len(records),'rows_mutated':mutated}
    except Exception as error:
        with conn: conn.execute("UPDATE sync_runs SET finished_at=?,status='failed',warning_json=?,error=? WHERE id=?",(now_utc(),json.dumps([str(error)]),str(error),run_id))
        return {'id':run_id,'source':source,'status':'failed','rows_received':0,'rows_mutated':0,'error':str(error)}
