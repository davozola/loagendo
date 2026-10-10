"""Read-only projections of the v1.2 normalized data, with explicit uncertainty."""
from __future__ import annotations
import datetime as dt
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

SOURCES = {'generalitat':'Generalitat de Catalunya','diba_bibliotecas':'Biblioteques — Diputació', 'diba_turismo':'Turisme — Diputació','guiabcn':'GuiaBCN (referencia manual)'}
KINDS = {'single':'Acto puntual','program':'Programa / ciclo','exhibition':'Exposición','course':'Curso','service':'Servicio'}
CATEGORIES = [
 'Música y vida nocturna','Artes escénicas','Cine y audiovisual','Arte y exposiciones',
 'Literatura y palabra','Ciencia y divulgación','Talleres y experiencias',
 'Cultura popular y fiestas','Ferias y mercados','Gastronomía','Deporte','Patrimonio y rutas','Comunidad y encuentros'
]
DISTRICTS = ['Ciutat Vella','Eixample','Gràcia','Horta-Guinardó','Les Corts','Nou Barris', 'Sant Andreu','Sant Martí','Sants-Montjuïc','Sarrià-Sant Gervasi']
STATUS = ('pending', 'needs_evidence', 'reviewed', 'excluded')


def clean(s):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(s or '').lower()) if not unicodedata.combining(c)).split())


def parse_date(v):
    try:return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):return None


def category_of(raw, source, kind):
    if kind == 'exhibition':return 'Arte y exposiciones'
    def string_of(x):
        if isinstance(x,dict):return ' '.join(str(y) for y in x.values() if isinstance(y,(str,int)))
        if isinstance(x,list):return ' '.join(map(str,x))
        return str(x or '')
    if source=='generalitat':
        b=(raw.get('localizaciones') or [{}])[0]
        txt=' '.join(map(string_of,(b.get('tags_categor_es'),b.get('tags_mbits'),b.get('denominaci'))))
    elif source=='guiabcn':
        txt=' '.join(map(string_of,(raw.get('type'),raw.get('title'))))
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
    if source=='generalitat':return str((raw.get('localizaciones') or [{}])[0].get('descripcio') or '')
    if source=='guiabcn':return str(raw.get('observation') or '')
    return str(raw.get('descripcio') or '')


def source_time(raw,source):
    if source=='generalitat':return str((raw.get('localizaciones') or [{}])[0].get('horari') or '')
    if source=='guiabcn':return ''
    return str(raw.get('observacions_horari') or '')


def source_price(raw,source):
    if source=='generalitat':
        a=(raw.get('localizaciones') or [{}])[0]
        return str(a.get('entrades') or ''),str(a.get('gratuita') or '')
    if source=='guiabcn':return '',''
    return str(raw.get('preu') or ''),''


def source_links(raw,source,url):
    links=[]
    if url:links.append({'label':'Página de la fuente','url':url,'verified':False})
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


def row_to_event(conn, row, detail=False):
    source,id,title,start,end,kind,eligibility,evidence_level,url,raw_text,status,note,updated = row
    raw=json.loads(raw_text)
    occurrences=[{'date':x[0], 'time':x[1],'evidence_field':x[2],'verified':False} for x in conn.execute('SELECT local_date,local_time,evidence_field FROM candidate_occurrences WHERE source=? AND id=? ORDER BY local_date,local_time',(source,id))]
    place=conn.execute('SELECT venue,address,lat,lon FROM source_venues WHERE source=? AND id=? ORDER BY seq',(source,id)).fetchall()
    events={
        'source':source,'id':id,'key':source+':'+id, 'title':title,
        'source_label':SOURCES.get(source,source),'start':start,'end':end,
        'kind':kind,'kind_label':KINDS.get(kind,kind),'eligibility':eligibility,
        'category':category_of(raw,source,kind),'district':district_of(raw,source),
        'status':status or 'pending','review_note':note or '', 'review_updated_at':updated,
        'venue_names':[v[0] for v in place if v[0]],
        'occurrences':occurrences,'has_candidate':bool(occurrences),
        'date_precision':'point' if start==end else 'range',
        'evidence_level':evidence_level,
        'published':(conn.execute('SELECT status FROM publication_decisions WHERE source=? AND id=?',(source,id)).fetchone() or ('draft',))[0]=='approved',
        'media':[{'asset_id':r[0],'url':'/media/'+str(r[0]),'alt':r[1],'rights_status':r[2]} for r in conn.execute('SELECT asset_id,alt_text,rights_status FROM media_assets WHERE source=? AND id=? AND local_path IS NOT NULL ORDER BY asset_id',(source,id))]
    }
    if detail:
        price,free=source_price(raw,source)
        events.update({
            'description':source_description(raw,source),
            'time_text':source_time(raw,source),
            'price_text':price,'source_free_label':free,
            'price_status':'unknown' if not price and not free else 'source_claim_unverified',
            'venues':[{'name':v[0], 'address':v[1], 'lat':v[2],'lon':v[3]} for v in place],
            'organizers':[r[0] for r in conn.execute('SELECT name FROM source_organizers WHERE source=? AND id=? ORDER BY seq',(source,id))],
            'alerts':[r[0] for r in conn.execute('SELECT issue FROM review_flags WHERE source=? AND id=? ORDER BY issue',(source,id))],
            'links':source_links(raw,source,url),
            'raw_sha256':conn.execute('SELECT raw_sha256 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone()[0],
            'evidence':{'level':evidence_level,'date_is_verified':False,'schedule_is_verified':False,'rights_for_media_verified':False},
            'verified_fields':[{'field':r[0],'value':json.loads(r[1]),'evidence_url':r[2],'checked_on':r[3],'note':r[4],'updated_at':r[5]} for r in conn.execute('SELECT field_name,value_json,evidence_url,checked_on,note,updated_at FROM field_verifications WHERE source=? AND id=? ORDER BY field_name',(source,id))],
            'publication_status':(conn.execute('SELECT status FROM publication_decisions WHERE source=? AND id=?',(source,id)).fetchone() or ('draft',))[0],
        })
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
    ''')
    columns={r[1] for r in conn.execute('PRAGMA table_info(media_assets)')}
    if 'content_type' not in columns: conn.execute('ALTER TABLE media_assets ADD COLUMN content_type TEXT')


def connect(db):
    conn=sqlite3.connect(str(db))
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def all_events(conn):
    rows=conn.execute('''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,
               r.evidence_level,r.source_url,r.raw_json, e.status,e.note,e.updated_at
               FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id''').fetchall()
    return [row_to_event(conn,r) for r in rows]


def query_events(conn, *, query='', date='', category='', district='', source='', status='', kind='', only_sessions=False,featured=False,page=1,page_size=24):
    if date and not parse_date(date):raise ValueError('Fecha no válida')
    if page<1 or page>9999:raise ValueError('Página no válida')
    if page_size<1 or page_size>100:raise ValueError('Tamaño de página no válido')
    match=[]; term=clean(query)
    for e in all_events(conn):
        if term and term not in clean(e['title']+' '+' '.join(e['venue_names'])):continue
        if date and not (e['start']<=date<=e['end']):continue
        if category and e['category']!=category:continue
        if district and e['district']!=district:continue
        if source and e['source']!=source:continue
        if status and e['status']!=status:continue
        if kind and e['kind']!=kind:continue
        if only_sessions:
            if not e['occurrences']:
                continue
            if date and not any(occ['date']==date for occ in e['occurrences']):
                continue
        match.append(e)
    # Featured cards deliberately prioritize imminent records with a local image.
    if featured:
        baseline='2026-10-10'; horizon='2026-10-24'
        match=[e for e in match if e['end']>=baseline and e['start']<=horizon and e['eligibility']!='exclude']
        match.sort(key=lambda e:(not bool(e['media']),max(e['start'],baseline),e['title'].casefold()))
    # Show useful upcoming items first. A long program spanning the selected
    # day is weaker evidence than an explicit dated candidate or a one-day act.
    elif date:
        def rank(e):
            has_time=any(o['date']==date for o in e['occurrences'])
            if has_time:return 0
            if e['start']==e['end']==date:return 1
            if e['kind']=='exhibition':return 2
            if e['kind']=='program':return 3
            return 4
        match.sort(key=lambda x:(rank(x),x['start'],x['title'].casefold()))
    else:
        baseline='2026-10-10'
        def rank(e):
            if e['eligibility']=='exclude':return 4
            if e['kind']=='single':return 0
            if e['kind']=='exhibition':return 2
            return 3
        match.sort(key=lambda x:(max(x['start'],baseline),rank(x),x['title'].casefold()))
    start_idx=(page-1)*page_size
    return {'items':match[start_idx:start_idx+page_size], 'total':len(match),'page':page, 'page_size':page_size, 'pages':(len(match)+page_size-1)//page_size,'limitations':{'date_filter':'Los intervalos de programas y exposiciones no acreditan sesión en el día.','district_filter':'Solo distritos indicados explícitamente por la fuente, sin geocodificación inferida.','sources':'Instantánea de octubre de 2026; no se ha actualizado automáticamente.'}}


def event_detail(conn,source,id):
    row=conn.execute('''SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,
               r.evidence_level,r.source_url,r.raw_json, e.status,e.note,e.updated_at
               FROM source_records r LEFT JOIN editorial_reviews e ON e.source=r.source AND e.id=r.id
               WHERE r.source=? AND r.id=?''',(source,id)).fetchone()
    if not row:return None
    return row_to_event(conn,row,True)


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
            'by_category':grouped('category'),'source_date_start':'2026-10-10','source_date_end':'2027-01-07',
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
    return {'field':field_name,'value':value,'evidence_url':evidence_url,'checked_on':checked_on,'updated_at':now}


def save_publication_decision(conn, source, id, status, note):
    if status not in ('draft','blocked','approved'):raise ValueError('Estado de publicación no permitido')
    if not conn.execute('SELECT 1 FROM source_records WHERE source=? AND id=?',(source,id)).fetchone():raise LookupError('Actividad no encontrada')
    now=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    with conn:
        conn.execute('''INSERT INTO publication_decisions(source,id,status,note,decided_at) VALUES(?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET status=excluded.status,note=excluded.note,decided_at=excluded.decided_at''',(source,id,status,note.strip(),now))
    # `published` is a local API flag. The HTTP server remains bound to 127.0.0.1.
    return {'status':status,'note':note.strip(),'updated_at':now,'published':status=='approved'}
