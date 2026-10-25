"""Audited detail-page enrichment; media stays reference-only."""
from __future__ import annotations
import datetime as dt
import html
import sqlite3
import re
import time
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from src.media import is_event_image, register
from src.network import tls_context
from src import guia_schedule

# Also versions the description selection. GuiaBCN exposes a metadata-only
# meta description ("Quan / On") alongside the actual body copy.
SCHEDULE_PARSER_VERSION = 10  # 10 (25-10-2026): descripción con todos los párrafos del bloque .cos (antes solo el primero). 9 (20-10-2026): «Fecha y horario» y «Precios» de la información práctica del CCCB. 8 (20-10-2026): horario de la página del Lliure, «Quan?» de Barcelona és molt més (Diputació), «próximamente» del MACBA, «per determinar». 7 7 (18-10-2026): URL de la API con id_doc antes de xout (la v6 recibía 406), precio de respaldo y enlaces oficiales.
# 6: 6 (18-10-2026): horario de GuiaBCN desde la API de detalle, fila a fila y por día.
# 5: 5 (17-10-2026): la descripción sale solo del bloque .cos; nunca del menú de navegación

DESCRIPTION_MAX = 3000
NAVIGATION_TEXT = re.compile(r"^\s*(?:per districte|por distrito|by district)\b|selecciona el districte|selecciona el distrito", re.I)


def usable_description(text):
    """False for page chrome captured as if it were prose (district menu of
    GuiaBCN pages). Archived rows are kept as they are; readers use this."""
    return bool(text and text.strip()) and not NAVIGATION_TEXT.search(text)


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.meta={}; self.links=[]; self.images=[]; self._paragraphs=[]; self._content_paragraphs=[]; self._in_p=False; self._in_content_p=False; self._buffer=[]; self._content_depth=0; self._schedule_depth=0; self._schedule=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='meta':
            key=attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'): self.meta[key]=html.unescape(attrs['content'])
        elif tag=='a' and attrs.get('href'): self.links.append(attrs['href'])
        elif tag=='img':
            candidate=attrs.get('src') or attrs.get('data-src') or attrs.get('data-lazy-src')
            if candidate: self.images.append((candidate,attrs.get('alt','')))
        elif tag=='p':
            self._in_p=True; self._in_content_p=bool(self._content_depth); self._buffer=[]
        if self._content_depth:
            self._content_depth+=1
        elif tag=='div' and 'cos' in attrs.get('class','').split():
            # GuiaBCN wraps its prose in `.cos`; the generic paragraphs that
            # precede it belong to navigation and filters, not the event.
            self._content_depth=1
        if self._schedule_depth:
            self._schedule_depth+=1
        elif tag=='div' and attrs.get('id')=='horari':
            self._schedule_depth=1
    def handle_data(self, data):
        if self._in_p: self._buffer.append(data)
        if self._schedule_depth: self._schedule.append(data)
    def handle_endtag(self, tag):
        if tag=='p' and self._in_p:
            value=' '.join(''.join(self._buffer).split())
            if len(value)>=40: self._paragraphs.append(value)
            if len(value)>=40 and self._in_content_p:self._content_paragraphs.append(value)
            self._in_p=False; self._in_content_p=False; self._buffer=[]
        if self._content_depth:
            self._content_depth-=1
        if self._schedule_depth:
            self._schedule_depth-=1

    @property
    def description(self):
        meta=self.meta.get('description') or self.meta.get('og:description') or ''
        # GuiaBCN puts date, venue and telephone fields in the HTML meta tag.
        # That is useful provenance but not a readable event description;
        # favour the first substantive body paragraph instead.
        # Fuera de `.cos` solo hay navegación y filtros (p. ej. «Per districte
        # Selecciona el districte…»): sin bloque de contenido no hay descripción.
        # 10 (25-10-2026): todos los párrafos de `.cos`, no solo el primero, y por delante de la meta
        # descripción (un resumen de ~160 caracteres). Tope de 3.000 caracteres en el último párrafo entero.
        paragraphs=[p for p in self._content_paragraphs if usable_description(p)]
        body=''
        for p in paragraphs:
            if body and len(body)+2+len(p)>DESCRIPTION_MAX: break
            body=(body+'\n\n'+p) if body else p[:DESCRIPTION_MAX]
        if body: return body
        if re.match(r'^\s*Quan\s*:',meta,re.I) or not usable_description(meta):
            return ''
        return meta

    @property
    def schedule(self):
        """Return every explicit local time stated in the official schedule."""
        text=' '.join(''.join(self._schedule).split())
        matches=re.findall(r'\ba\s+les\s+(\d{1,2})[.:](\d{2})\s*(?:h\b)?',text,re.I)
        if not matches:
            matches=re.findall(r'\b(?:de\s+)?(\d{1,2})[.:](\d{2})\s*h\b',text,re.I)
        times=[]
        for hour,minute in matches:
            hour,minute=int(hour),int(minute)
            value=f'{hour:02d}:{minute:02d}'
            if hour<=23 and minute<=59 and value not in times:times.append(value)
        if not times:return ('','')
        return (' · '.join(times),' · '.join(f'{value.replace(":", ".")} h' for value in times))

def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS source_enrichments (
      source TEXT NOT NULL,id TEXT NOT NULL, fetched_at TEXT NOT NULL, source_url TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '', links_json TEXT NOT NULL DEFAULT '[]', raw_html_sha256 TEXT NOT NULL,
      PRIMARY KEY(source,id), FOREIGN KEY(source,id) REFERENCES source_records(source,id))''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(source_enrichments)')}
    if 'schedule_time' not in columns: conn.execute('ALTER TABLE source_enrichments ADD COLUMN schedule_time TEXT NOT NULL DEFAULT \'\'')
    if 'schedule_text' not in columns: conn.execute('ALTER TABLE source_enrichments ADD COLUMN schedule_text TEXT NOT NULL DEFAULT \'\'')
    if 'schedule_checked_at' not in columns: conn.execute('ALTER TABLE source_enrichments ADD COLUMN schedule_checked_at TEXT NOT NULL DEFAULT \'\'')
    if 'schedule_parser_version' not in columns: conn.execute('ALTER TABLE source_enrichments ADD COLUMN schedule_parser_version INTEGER NOT NULL DEFAULT 0')
    conn.execute('''CREATE TABLE IF NOT EXISTS source_detail_facts (
      source TEXT NOT NULL,id TEXT NOT NULL,fetched_at TEXT NOT NULL,
      facts_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(source,id),
      FOREIGN KEY(source,id) REFERENCES source_records(source,id))''')


def _fetch_html(request, timeout):
    """Fetch a public detail page with bounded backoff for rate limiting."""
    for attempt in range(4):
        try:
            with urlopen(request,timeout=timeout,context=tls_context()) as response:
                return response.read(2_000_000).decode('utf-8','replace')
        except HTTPError as error:
            if error.code != 429 or attempt == 3:
                raise
            time.sleep(2 ** attempt)


def html_schedule_rows(content):
    """Respaldo si la API de detalle falla: días y horas de cada fila de la
    tabla «Horaris» de la página. Solo las dos primeras celdas, que son
    siempre días y horas; el precio ocupa varias filas y desplaza el resto."""
    table=re.search(r'<div\s+id=["\']horari["\'][^>]*>(.*?)</table>',content or '',re.I|re.S)
    rows=[]
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>',table.group(1) if table else '',re.I|re.S):
        cells=[_plain(x) for x in re.findall(r'<td[^>]*class=["\'][^"\']*content-info[^"\']*["\'][^>]*>(.*?)</td>',tr,re.I|re.S)]
        if len(cells)>=2 and (cells[0] or cells[1]):
            row={k:v for k,v in (('dies',cells[0]),('hores',cells[1])) if v}
            # El precio solo está en la primera fila (ocupa varias); en las
            # demás filas una tercera celda no se puede atribuir con seguridad.
            if not rows and len(cells)>=3 and cells[2]: row['preu']=cells[2]
            if not rows and len(cells)>=4 and cells[3]: row['observacions']=cells[3]
            rows.append(row)
    return rows


def guia_schedule_facts(record_id, content, start, end, fetch, timeout):
    """Horario de un registro de GuiaBCN: API de detalle y, si falla, la página.

    Devuelve (schedule_time, schedule_text, facts). Las filas se guardan tal
    como vienen (sin HTML) junto con la URL y el hash de la respuesta."""
    import hashlib,json
    api_url=guia_schedule.DETAIL_API.format(id=quote(str(record_id),safe=''))
    rows=None; evidence={}
    try:
        body=fetch(api_url,timeout)
        detail=json.loads(body)
        rows=guia_schedule.api_rows(detail)
        if rows is not None:
            evidence={'schedule_source':'guiabcn_api_detall','schedule_api_url':api_url,'schedule_api_sha256':hashlib.sha256(body.encode()).hexdigest()}
            links=guia_schedule.api_links(detail)
            if links: evidence['official_links']=links
    except Exception as error:  # la página sigue siendo una fuente válida
        evidence={'schedule_api_error':type(error).__name__+(': %s'%getattr(error,'code','') if getattr(error,'code',None) else ''),'schedule_api_url':api_url}
    if rows is None:
        rows=html_schedule_rows(content); evidence['schedule_source']='guiabcn_detail_page'
    result=guia_schedule.summary(rows,start,end)
    facts={**result['facts'],**evidence,'schedule_rows':rows}
    if result['by_day']: facts['hours_by_day']=result['by_day']
    return result['schedule_time'],result['schedule_text'],facts


def relevant_links(page_url, links):
    """Keep useful links from a detail page, not its navigation chrome."""
    page=urlsplit(page_url)
    out=[]; seen=set()
    generic_paths={'','/','/ca','/es','/en','/ca/','/es/','/en/','/contacte','/contacto'}
    for link in links:
        if not link: continue
        absolute=urljoin(page_url,link)
        parsed=urlsplit(absolute)
        if parsed.scheme not in ('http','https') or not parsed.netloc: continue
        if parsed.netloc==page.netloc and (parsed.path in generic_paths or parsed.path==page.path): continue
        normalized=absolute.split('#',1)[0]
        if normalized and normalized not in seen:
            out.append(normalized); seen.add(normalized)
    return out


def _plain(markup):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>',' ',markup or '')).replace('\xa0',' ').split())


def detail_facts(content):
    """Extract labelled facts from a GuiaBCN detail page without guessing.

    These facts remain in the enrichment layer because the source feed did
    not provide them. The raw page hash in ``source_enrichments`` makes every
    imported value traceable to the exact fetch.
    """
    facts={}
    schedule=re.search(r'<div\s+id=["\']horari["\'][^>]*>(.*?)</table>',content,re.I|re.S)
    if schedule:
        cells=[_plain(x) for x in re.findall(r'<td[^>]*class=["\'][^"\']*content-info[^"\']*["\'][^>]*>(.*?)</td>',schedule.group(1),re.I|re.S)]
        if len(cells)>=3:
            facts.update({'schedule_days':cells[0], 'schedule_hours':cells[1], 'price_text':cells[2]})
            if len(cells)>=4: facts['schedule_note']=cells[3]
    for label,key in ((r'Se celebra a:', 'venue'),(r'Organitzat per:', 'organizer')):
        match=re.search(r'<dt[^>]*>\s*'+label+r'\s*</dt>\s*<dd[^>]*>(.*?)</dd>',content,re.I|re.S)
        if match: facts[key]=_plain(match.group(1)).rstrip('.').strip()
    address=re.search(r'Adreça:\s*</dt>\s*<dd[^>]*>(.*?)</dd>',content,re.I|re.S)
    if address: facts['address']=_plain(address.group(1))
    coords=re.search(r'loadmapdetall\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)',content)
    if coords: facts['coordinates']={'lat':float(coords.group(1)),'lon':float(coords.group(2))}
    note=facts.get('schedule_note','').casefold()
    facts['registration_required']=bool(re.search(r'inscripci',note))
    return {key:value for key,value in facts.items() if value not in ('',None,False)}

def _lines(fragment):
    parts=re.split(r'(?i)<br\s*/?>|</p>|</li>|</div>',fragment or '')
    return [' '.join(html.unescape(re.sub(r'<[^>]+>',' ',x)).split()) for x in parts if re.sub(r'<[^>]+>','',x).strip()]


def page_schedule(source, content, start='', end=''):
    """Horario escrito en la página de la propia fuente (20-10-2026), tal cual:
      · Teatre Lliure: bloque «Horario/Horari» («De miércoles a viernes a las 19.30 h …»), y su precio.
      · Barcelona és molt més (Diputació): bloque «Quan?» («22/10/2026 · 18:30 - 20:00»).
      · CCCB: «Fecha y horario» y «Precios» de la información práctica.
      · MACBA: aviso «próximamente» cuando aún no hay horario.
    Devuelve (hora si es única, texto del horario, hechos)."""
    facts={}
    if source=='web_teatre_lliure':
        block=re.search(r'<h3 class="tit">\s*(?:Horario|Horari|Schedule)\s*</h3>\s*<p class="text">(.*?)</p>',content,re.S|re.I)
        price=re.search(r'<h3 class="tit">\s*(?:Precio|Preu|Price)\s*</h3>\s*<p class="text">(.*?)</p>',content,re.S|re.I)
        if price: facts['price_text']=' '.join(_lines(price.group(1)))
        if block:
            text='\n'.join(_lines(block.group(1)))
            if re.search(r'\b(?:a determinar|per determinar|por determinar|properament|próximamente)\b',text,re.I): return '','Por determinar',facts
            return '',text,facts
    if source=='diba_turismo':
        block=re.search(r'<h4[^>]*>\s*Quan\?\s*</h4>(.*?)<h4',content,re.S|re.I)
        if block:
            lines=_lines(block.group(1)); text=' · '.join(lines)
            times=re.findall(r'\b(\d{1,2}):(\d{2})\b',text)
            one=start and start==end
            return (f'{int(times[0][0]):02d}:{times[0][1]}' if times and one else ''),text,facts
    if source=='web_cccb':
        # «Información práctica»: <h3 class="component-heading">Fecha y horario</h3> seguido de
        # párrafos («23 octubre 2026», «10.00 – 22.00») hasta el siguiente encabezado.
        def cccb_block(names):
            m=re.search(r'<h3[^>]*component-heading[^>]*>\s*(?:%s)\s*</h3>(.*?)(?=<h3[^>]*component-heading|<footer|$)'%names,content,re.S|re.I)
            return _lines(m.group(1))[:6] if m else []
        price=cccb_block('Precios?|Preus?|Prices?')
        if price:
            facts['price_text']=' · '.join(price)
            if re.search(r'reserva|inscripci',facts['price_text'],re.I): facts['registration_required']=True
        lines=cccb_block('Fecha y horario|Data i horari|Date and time|Horario|Horari')
        if lines:
            text=' · '.join(lines)
            times=re.findall(r'\b(\d{1,2})[.:](\d{2})\b',text)
            one=start and start==end
            return (f'{int(times[0][0]):02d}:{times[0][1]}' if times and one and int(times[0][0])<24 else ''),text,facts
    if source=='web_macba' and re.search(r'button-secondary[^>]*>\s*pr(?:ó|&oacute;|o)ximament',content,re.I):
        return '','Próximamente',facts
    return '','',facts


def enrich_sources(conn, limit=10, timeout=20, sources=None, refresh=False, fetcher=None, record_ids=None, delay_seconds=0.5):
    """Archive presentation metadata without modifying imported source records."""
    initialize(conn)
    if sources is None:
        sources=('guiabcn','web_macba','web_cccb','web_teatre_lliure','web_auditori','web_centres_civics','diba_turismo')
    if not sources: return {'attempted':0,'enriched':0,'failed':0,'media_references':0}
    marks=','.join('?' for _ in sources)
    record_ids=tuple(record_ids or ())
    id_filter='' if not record_ids else f" AND id IN ({','.join('?' for _ in record_ids)})"
    retry_before=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=7)).isoformat(timespec='seconds')
    today=dt.date.today()
    priority_until=(today+dt.timedelta(days=14)).isoformat()
    # The API listing for GuiaBCN has no schedule.  Old enrichment rows must
    # therefore be revisited once after this field was introduced, then only
    # periodically when no explicit hour was found.
    missing='' if refresh else """AND (
      NOT EXISTS (SELECT 1 FROM source_enrichments x WHERE x.source=source_records.source AND x.id=source_records.id)
      OR (source_records.source<>'guiabcn' AND EXISTS (
        SELECT 1 FROM source_enrichments x WHERE x.source=source_records.source AND x.id=source_records.id
          AND COALESCE(x.schedule_parser_version,0)<? AND source_records.end_date>=date('now')))
      OR (source_records.source='guiabcn' AND EXISTS (
        SELECT 1 FROM source_enrichments x WHERE x.source=source_records.source AND x.id=source_records.id
          AND (COALESCE(x.schedule_parser_version,0)<? OR (COALESCE(x.schedule_time,'')='' AND (COALESCE(x.schedule_checked_at,'')='' OR x.schedule_checked_at<?)))
      ))
    )"""
    missing_params=() if refresh else (SCHEDULE_PARSER_VERSION,SCHEDULE_PARSER_VERSION,retry_before)
    # Un registro de GuiaBCN que también está en Open Data BCN no se publica
    # (gana Open Data, que ya trae su horario): no se pide su detalle salvo
    # que se pida explícitamente (refresh, --enrich-event).
    if not refresh:
        missing+=""" AND NOT (source_records.source='guiabcn' AND EXISTS (
          SELECT 1 FROM source_records twin WHERE twin.source='opendatabcn_agenda' AND twin.id=source_records.id))"""
    rows=conn.execute(f"""SELECT id,source,source_url,start_date,end_date FROM source_records
      WHERE source IN ({marks}) AND source_url<>'' {id_filter} {missing}
      ORDER BY CASE
                 WHEN source='guiabcn' AND start_date=end_date AND start_date>=? AND start_date<=? THEN 0
                 WHEN source='guiabcn' AND start_date=end_date AND start_date>=? THEN 1
                 WHEN source='guiabcn' AND end_date>=? THEN 2
                 ELSE 3 END,
               start_date, id LIMIT ?""",(*sources,*record_ids,*missing_params,today.isoformat(),priority_until,today.isoformat(),today.isoformat(),limit)).fetchall(); done=failed=media=resolved=0
    import hashlib,json
    errors={}
    for record_id,source,url,start_date,end_date in rows:
        try:
            # GuiaBCN is a public service, not a bulk-download endpoint. A
            # small, deterministic pause avoids the burst that previously
            # caused later detail pages to fail without a schedule.
            if done or failed:
                time.sleep(delay_seconds if not fetcher else 0)
            req=Request(url,headers={'Accept':'text/html','User-Agent':'Brollant/1.3 (+https://brollant.com) enrichment'})
            if fetcher: content=fetcher(url,timeout)
            else: content=_fetch_html(req,timeout)
            parser=MetaParser();parser.feed(content);description=parser.description; schedule_time,schedule_text=parser.schedule; facts=detail_facts(content)
            page_time,page_text,page_facts=page_schedule(source,content,start_date,end_date)
            if page_text: schedule_time,schedule_text=page_time,page_text
            facts.update(page_facts)
            if source=='guiabcn':
                # El horario sale de la API de detalle (filas con días y horas
                # separados); la página solo aporta descripción, enlaces e imagen.
                def fetch_api(api_url,api_timeout):
                    if fetcher: return fetcher(api_url,api_timeout)
                    time.sleep(delay_seconds)
                    # Mismas cabeceras que el listado de esta API, que sí responde
                    # desde el motor; con otras, el detalle devolvía 406.
                    headers={'Accept':'*/*','User-Agent':'Brollant/1.3 (+https://brollant.com) sync'}
                    try:
                        return _fetch_html(Request(api_url,headers=headers),api_timeout)
                    except HTTPError as error:
                        if error.code!=406: raise
                        # Variante sin idioma ni formato al final, por si el servidor negocia distinto.
                        return _fetch_html(Request(api_url.replace('&xout=json&idma=ca','&idma=ca&xout=json'),headers=headers),api_timeout)
                for key in ('schedule_days','schedule_hours','price_text','schedule_note','registration_required'): facts.pop(key,None)
                schedule_time,schedule_text,schedule_facts=guia_schedule_facts(record_id,content,start_date,end_date,fetch_api,timeout)
                facts.update(schedule_facts)
                text=' '.join((facts.get('schedule_note',''),facts.get('price_text','')))
                if re.search(r'inscripci',text,re.I) and not re.search(r'\bno\s+cal\s+inscripci',text,re.I): facts['registration_required']=True
            now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
            resolved+=bool(schedule_time or facts.get('hours_by_day'))
            with conn:
                links=relevant_links(url,parser.links)
                if source=='guiabcn':
                    # Solo los enlaces que declara la ficha (web del evento,
                    # inscripciones, entradas); los de la página son menú del Ajuntament.
                    links=facts.get('official_links') or [l for l in links if not urlsplit(l).netloc.endswith('barcelona.cat')]
                conn.execute('''INSERT INTO source_detail_facts(source,id,fetched_at,facts_json) VALUES(?,?,?,?)
                  ON CONFLICT(source,id) DO UPDATE SET fetched_at=excluded.fetched_at,facts_json=excluded.facts_json''',(source,record_id,now,json.dumps(facts,ensure_ascii=False,sort_keys=True)))
                conn.execute('''INSERT INTO source_enrichments(source,id,fetched_at,source_url,description,links_json,raw_html_sha256,schedule_time,schedule_text,schedule_checked_at,schedule_parser_version)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET fetched_at=excluded.fetched_at,source_url=excluded.source_url,description=excluded.description,links_json=excluded.links_json,raw_html_sha256=excluded.raw_html_sha256,schedule_time=excluded.schedule_time,schedule_text=excluded.schedule_text,schedule_checked_at=excluded.schedule_checked_at,schedule_parser_version=excluded.schedule_parser_version''',(source,record_id,now,url,description,json.dumps(links[:20]),hashlib.sha256(content.encode()).hexdigest(),schedule_time,schedule_text,now,SCHEDULE_PARSER_VERSION))
                image=parser.meta.get('og:image')
                candidates=[]
                if image: candidates.append((image,parser.meta.get('og:image:alt','')))
                candidates.extend(parser.images)
                seen=set()
                for image,alt in candidates:
                    image=urljoin(url,image)
                    if image in seen or not image.startswith(('https://','http://')) or not is_event_image(image,alt): continue
                    seen.add(image); register(conn,source,record_id,image,alt=alt,rights_status='unknown');media+=1
            done+=1
        except Exception as error:
            failed+=1; kind=type(error).__name__+': '+str(error)[:80]; errors[kind]=errors.get(kind,0)+1
    return {'attempted':len(rows),'enriched':done,'failed':failed,'media_references':media,'schedules_resolved':resolved,'errors':dict(sorted(errors.items(),key=lambda x:-x[1])[:5])}


def enrich(conn, limit=10, timeout=20):
    """Compatibility entry point for the original GuiaBCN-only command."""
    return enrich_sources(conn,limit,timeout,sources=('guiabcn',))
