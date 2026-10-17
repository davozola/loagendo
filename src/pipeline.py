#!/usr/bin/env python3
"""Loagendo v1.2 - deterministic offline source-to-review pipeline.

This system deliberately DOES NOT publish; input snapshots are not independent
proof of dates or rights. No HTTP, credentials, scraping, AI or pip packages.
"""
from __future__ import annotations
import collections
import datetime as dt
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = dt.date(2026, 10, 10)
END = dt.date(2027, 1, 8)


def sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,default=str).encode('utf8')).hexdigest()


def norm(text):
    s=unicodedata.normalize('NFKD',str(text or '').casefold())
    s=''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.findall(r'[a-z0-9]+',s))


def tokens(text):
    skip={'el','la','l','de','del','d','a','en','i','y','and','amb','per','els','les','un','una','al','the','2026','exposicio','teatre','taller','concert','activitat'}
    return {s for s in norm(text).split() if s not in skip}


def title_similarity(a,b):
    x,y=tokens(a),tokens(b)
    jac=len(x&y)/len(x|y) if x and y else 0
    ratio=SequenceMatcher(None,norm(a),norm(b)).ratio() if a and b else 0
    return round(.7*jac+.3*ratio,4)


def day(t):
    try:return dt.date.fromisoformat(str(t)[:10])
    except (ValueError,TypeError):return None


def delta(start,end):
    s,e=day(start),day(end)
    return (e-s).days if s and e else None


def coor(x):
    try:
        a,b=map(float,str(x).split(','))
        if -90<=a<=90 and -180<=b<=180:return (a,b)
    except (ValueError,TypeError):pass
    return None


def coords_in_row(r):
    try:
        a=float(r['latitud']); b=float(r['longitud'])
        return (a,b) if -90<=a<=90 and -180<=b<=180 else None
    except (KeyError,ValueError,TypeError):return None


def geo_meters(a,b):
    if not a or not b:return None
    lat1,lon1=map(math.radians,a);lat2,lon2=map(math.radians,b)
    z=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000*2*math.atan2(math.sqrt(z),math.sqrt(max(0,1-z)))


WEEKDAYS=r'(?:dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)'


def strip_duration(text):
    """Drop trailing duration/notes clauses ('Durada aproximada: 90 minuts (sense pausa)')."""
    source=' '.join(str(text or '').split())
    source=re.split(r'\s*(?:\(|Durada|Duraci[oó]n?|Duración)\b',source,maxsplit=1,flags=re.I)[0]
    return source.strip(' .;,')


def dated_times(text, start, end):
    """Per-day start times stated as '<weekday> 23: 19 h <weekday> 24: 16 h i 17.15 h'.

    Every day number must map to exactly one date inside [start, end] and every
    segment must be nothing but times; otherwise nothing is returned.
    """
    source=strip_duration(text); s,e=day(start),day(end)
    if not source or s is None or e is None or e<s or (e-s).days>27:return []
    segments=re.split(r'(?:^|\s)(?:'+WEEKDAYS+r'\s+)?(\d{1,2})\s*:\s*',source,flags=re.I)
    if len(segments)<3 or segments[0].strip():return []
    dates={}
    cursor=s
    while cursor<=e:
        dates.setdefault(cursor.day,[]).append(cursor); cursor+=dt.timedelta(days=1)
    out=[]
    for number,times in zip(segments[1::2],segments[2::2]):
        candidates=dates.get(int(number),[])
        if len(candidates)!=1:return []
        parts=[p for p in re.split(r'\s*(?:,|\bi\b|\by\b|/)\s*',times.strip(' .,;')) if p]
        hits=[]
        for part in parts:
            m=re.fullmatch(r'(?:(?:a les|a las|a la)\s+)?(\d{1,2})(?:[.:](\d{2}))?\s*h(?:ores)?',part.strip(),flags=re.I)
            if not m or int(m.group(1))>23 or int(m.group(2) or 0)>59:return []
            hits.append(f'{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}')
        if not hits:return []
        out.extend((candidates[0].isoformat(),t) for t in sorted(set(hits)))
    return sorted(set(out))


def simple_times(s):
    """ONLY unambiguous standalone event start times, not opening hours or duration."""
    source=strip_duration(s)
    if not source:return []
    p=r'(\d{1,2})(?:[.:](\d{2}))?\s*h(?:ores)?\b'
    # Whole text must be nothing other than a punctual start or a function pair.
    if re.fullmatch(r'(?:(?:a les|a las|a la|ales)\s+)?'+p,source,flags=re.I):
        hits=re.findall(p,source,flags=re.I)
    elif re.fullmatch(r'(?:dues funcions|dos funciones|2 funcions)\s*:\s*'+p+r'(?:\s*(?:i|y|,|\/)\s*|\s+)'+p,source,flags=re.I):
        hits=re.findall(p,source,flags=re.I)
    else:return []
    result=[]
    for h,m in hits:
        if int(h)>23 or int(m or '0')>59:return []
        result.append(f'{int(h):02d}:{int(m or "0"):02d}')
    return sorted(set(result))


def event_kind(title,cat,span,freq,source):
    t=norm(title); c=norm(cat); f=norm(freq)
    if source=='diba_turismo' and t in {'esmorzacollserola','tastaelvidebarcelona','barcelonarchskylineprivatesailingtour'}:
        return 'service','exclude'
    if source=='diba_turismo' and (('esmorz' in t and 'collserola' in t) or 'tasta el vi de barcelona' in t or 'skyline private sailing' in t):
        return 'service','exclude'
    if (t.startswith('curs d escacs') or ('estas on' in t or 'estason' in t) and (span or 0)>60 and f=='setmanal') and source=='diba_bibliotecas':
        return 'course','exclude'
    if source=='guiabcn' and c=='course':return 'course','review'
    if 'curs' in t or 'curso' in t:return 'course','review'
    if 'exposic' in t or 'exposicions' in c or 'exposiciones' in c:return 'exhibition','review'
    if 'festivals' in c or 'cicles' in c or 'festival' in t or ('cicle' in t and (span or 0)>1):return 'program','review'
    if f=='setmanal' or f=='mensual' or (span is not None and span>2):return 'program','review'
    return 'single','review'


def build_records(data):
    loc=json.loads((data/'localizaciones_barcelona.json').read_text())
    org=json.loads((data/'organizadores_barcelona.json').read_text())
    byloc=collections.defaultdict(list);byorg=collections.defaultdict(list)
    for r in loc:byloc[str(r['codi'])].append(r)
    for r in org:byorg[str(r['codi'])].append(r)
    records=[]
    for code, rs in sorted(byloc.items()):
        base=rs[0]
        span=delta(base.get('data_inici'),base.get('data_fi'))
        kind,eligibility=event_kind(base.get('denominaci',''),base.get('tags_categor_es',''),span,base.get('horari',''),'generalitat')
        venues=[]
        for r in rs:
            key=(r.get('espai',''),r.get('adre_a',''),r.get('latitud',''),r.get('longitud',''))
            if key not in [(v['name'],v['address'],v['lat'],v['long']) for v in venues]:
                venues.append({'name':r.get('espai',''),'address':r.get('adre_a',''),'lat':r.get('latitud',''),'long':r.get('longitud',''),'coords':coords_in_row(r)})
        organizers=sorted({r.get('nom_organitzador','').strip() for r in byorg.get(code,[]) if r.get('nom_organitzador','').strip()})
        flags=[]
        if len(venues)>1:flags.append('MULTI_VENUE_SESSION_NOT_RESOLVED')
        if base.get('data_fi_aproximada')=='true':flags.append('END_DATE_APPROXIMATE')
        if not (base.get('horari') or '').strip():flags.append('NO_SCHEDULE_SOURCE')
        if not (base.get('entrades') or '').strip():flags.append('NO_PRICE_TEXT')
        if kind=='program':flags.append('PROGRAM_MAY_CONTAIN_CHILD_EVENTS')
        if not organizers:flags.append('ORGANIZER_NAME_MISSING')
        if not (base.get('urlactivitat') or '').strip():flags.append('DIRECT_ACTIVITY_URL_MISSING')
        records.append({'source':'generalitat','id':code,'title':base.get('denominaci',''),'start':str(base.get('data_inici',''))[:10], 'end':str(base.get('data_fi',''))[:10], 'time_text':base.get('horari',''), 'price_text':base.get('entrades',''), 'free_label':base.get('gratuita',''), 'kind':kind,'eligibility':eligibility,'start_timestamp':'','frequency':'','raw':{'localizaciones':rs,'organizadores':byorg.get(code,[])}, 'venues':venues, 'organizers':organizers,'url':base.get('urlactivitat',''), 'alerts':flags,'evidence_level':'api_raw_unverified'})
    for source,filename in (('diba_bibliotecas','actesbiblioteques_ca_filtrado.json'),('diba_turismo','actesturisme_ca_filtrado.json')):
        api=json.loads((data/filename).read_text())
        for r in api.get('elements',[]):
            place=r.get('grup_adreca') or {}
            span=delta(r.get('data_inici'),r.get('data_fi'))
            kind,status=event_kind(r.get('titol',''),' '.join(r.get('tipus') or []),span,r.get('observacions_horari',''),source)
            flags=[]
            if r.get('data_fi','').endswith('23:59:59'):flags.append('ADMINISTRATIVE_DAY_END_NOT_SESSION_TIME')
            if span is not None and span>1:flags.append('LONG_RANGE_DO_NOT_EXPAND')
            if span==1:flags.append('NEXT_DAY_END_REVIEW')
            if not (r.get('preu') or '').strip():flags.append('UNKNOWN_PRICE_NOT_FREE')
            if not (r.get('descripcio') or '').strip():flags.append('DESCRIPTION_MISSING')
            if r.get('observacions_horari') in ('Setmanal','Mensual'):flags.append('RECURRING_FREQUENCY_NOT_DATES')
            if (r.get('data_inici') or '')[11:16]=='00:00':flags.append('MIDNIGHT_PLACEHOLDER_NOT_START_TIME')
            records.append({'source':source,'id':r['acte_id'],'title':r.get('titol',''),'start':r.get('data_inici','')[:10],'end':r.get('data_fi','')[:10], 'time_text':r.get('observacions_horari',''), 'price_text':r.get('preu',''), 'free_label':'', 'kind':kind,'eligibility':status,'start_timestamp':r.get('data_inici',''), 'frequency':r.get('observacions_horari',''), 'raw':r,'venues':[{'name':place.get('adreca_nom','').strip(),'address':place.get('adreca',''), 'coords':coor(place.get('localitzacio',''))}], 'organizers':[r.get('acte_organitzadors','').strip()] if r.get('acte_organitzadors','').strip() else [], 'url':r.get('acte_url',''), 'alerts':flags,'evidence_level':'api_raw_unverified'})
    for r in json.loads((ROOT/'benchmarks/benchmark_guiabcn_45.json').read_text()):
        kind,status=event_kind(r.get('title',''),r.get('type',''),delta(r.get('start'),r.get('end')),'','guiabcn')
        records.append({'source':'guiabcn','id':r['id'],'title':r['title'],'start':r['start'],'end':r['end'], 'time_text':'','price_text':'', 'free_label':'','kind':kind,'eligibility':status,'start_timestamp':'','frequency':'','raw':r,'venues':[{'name':r.get('venue',''),'address':'','coords':None}],'organizers':[],'url':r.get('url',''), 'alerts':['NO_PRIMARY_PAGE_SNAPSHOT','BENCHMARK_INTENTIONAL_NONRANDOM'] + ([r['warning']] if r.get('warning') else []), 'evidence_level':'manually_indexed_not_archived'})
    return records


def candidate_sessions(r):
    """Conservative syntactic candidates; always unverified. No recurrence expansion."""
    if r['eligibility']=='exclude' or r['source']=='guiabcn' or r['kind']!='single':return []
    # Connectors that already resolved explicit, source-stated sessions (iCal
    # entries of the Open Data BCN agenda) hand them over verbatim.
    if r.get('occurrences') is not None and r['source']=='opendatabcn_agenda':
        return list(r['occurrences'])
    s=day(r['start']); e=day(r['end']); span=delta(r['start'],r['end'])
    if r['source'].startswith(('web_','venue_')) and r['source']!='web_conciertos_club':
        # First-party agenda pages that print an exact start time next to a
        # single dated act (CCCB listing, L'Auditori event timestamp).
        if s is not None and span==0 and re.fullmatch(r'\d{2}:\d{2}',str(r['time_text'])):
            return [{'local_date':str(s),'local_time':str(r['time_text']),'time_zone':'Europe/Madrid','type':'first_party_listing_time_candidate','evidence_field':r.get('time_evidence_field','listing_time'),'end_time':None}]
        return []
    # The laboratory snapshot froze a window; live connectors must not. Only a
    # dated start is required (candidates stay unverified either way).
    if s is None or e is None:return []
    if r['source']=='generalitat':
        if len(r['venues'])!=1:return []
        if span!=0:
            return [{'local_date':d,'local_time':t,'time_zone':'Europe/Madrid','type':'unverified_dated_time_candidate','evidence_field':'horari','end_time':None} for d,t in dated_times(r['time_text'],r['start'],r['end'])]
        times=simple_times(r['time_text'])
        return [{'local_date':str(s),'local_time':t,'time_zone':'Europe/Madrid','type':'unverified_time_candidate','evidence_field':'horari','end_time':None} for t in times]
    if r['source']=='diba_bibliotecas':
        t=str(r['start_timestamp'])[11:16]
        if span not in (0,1) or not re.fullmatch(r'\d\d:\d\d',t) or t=='00:00' or r['frequency'] in ('Setmanal','Mensual'):
            return []
        return [{'local_date':str(s),'local_time':t,'time_zone':'Europe/Madrid','type':'unverified_start_timestamp_candidate','evidence_field':'data_inici','end_time':None}]
    if r['source']=='web_conciertos_club':
        times=[r['time_text']] if re.fullmatch(r'\d{2}:\d{2}',str(r['time_text'])) else []
        return [{'local_date':str(s),'local_time':t,'time_zone':'Europe/Madrid','type':'third_party_listing_time_candidate','evidence_field':'schema_startDate','end_time':None} for t in times]
    return []


def match_pairs(records):
    """Candidates only: no auto merge. Avoid broad-range event/program false positives."""
    out=[]
    for i,a in enumerate(records):
        for b in records[i+1:]:
            if a['source']==b['source'] and a['source']!='diba_bibliotecas':continue
            s=title_similarity(a['title'],b['title'])
            if s<.79:continue
            a0,a1,b0,b1=map(day,(a['start'],a['end'],b['start'],b['end']))
            if None in (a0,a1,b0,b1) or a0>b1 or b0>a1:continue
            va=[v.get('coords') for v in a['venues'] if v.get('coords')]
            vb=[v.get('coords') for v in b['venues'] if v.get('coords')]
            distances=[geo_meters(x,y) for x in va for y in vb]
            dist=min(distances) if distances else None
            venue_sim=max((title_similarity(x.get('name',''),y.get('name','')) for x in a['venues'] for y in b['venues']),default=0)
            if dist is not None and dist>200 and venue_sim<.8:continue
            if dist is None and venue_sim<.55:continue
            a_span=delta(a['start'],a['end']);b_span=delta(b['start'],b['end'])
            # A club / seasonal programme and an individual meeting with the same
            # generic title are related, NOT duplicate events. Exclude from merge queue.
            if a['source']==b['source'] and ((a_span or 0)>7 or (b_span or 0)>7):continue
            strict_dates=(a['start']==b['start'] and a['end']==b['end'])
            risk=['TITLE_SIMILARITY_IS_NOT_IDENTITY']
            if a['kind']=='program' or b['kind']=='program':risk.append('PROGRAM_CHILD_COLLISION_RISK')
            if not strict_dates:risk.append('DATE_RANGE_NOT_EQUAL')
            if a['source']=='guiabcn' or b['source']=='guiabcn':risk.append('MUNICIPAL_NO_ARCHIVED_RAW_EVIDENCE')
            if a['source']==b['source']:risk.append('SAME_SOURCE_REPEATED_RECORD')
            out.append({'a':a['source']+':'+a['id'],'b':b['source']+':'+b['id'],'title_a':a['title'],'title_b':b['title'],'similarity_heuristic':s,'geo_meters':round(dist,1) if dist is not None else None,'venue_similarity_heuristic':venue_sim,'start_a':a['start'],'start_b':b['start'],'review_only':True,'risks':risk})
    return sorted(out,key=lambda x:(-x['similarity_heuristic'],len(x['risks']),x['a'],x['b']))


def connect(db):
    con=sqlite3.connect(db)
    con.execute('PRAGMA foreign_keys=ON')
    con.executescript('''
    CREATE TABLE IF NOT EXISTS source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT,PRIMARY KEY(source,id));
    CREATE TABLE IF NOT EXISTS source_venues(source TEXT,id TEXT,seq INTEGER,venue TEXT,address TEXT,lat REAL,lon REAL,PRIMARY KEY(source,id,seq),FOREIGN KEY(source,id) REFERENCES source_records(source,id));
    CREATE TABLE IF NOT EXISTS source_organizers(source TEXT,id TEXT,seq INTEGER,name TEXT,PRIMARY KEY(source,id,seq),FOREIGN KEY(source,id) REFERENCES source_records(source,id));
    CREATE TABLE IF NOT EXISTS review_flags(source TEXT,id TEXT,issue TEXT,PRIMARY KEY(source,id,issue),FOREIGN KEY(source,id) REFERENCES source_records(source,id));
    CREATE TABLE IF NOT EXISTS candidate_occurrences(source TEXT,id TEXT,local_date TEXT,local_time TEXT,kind TEXT,evidence_field TEXT,PRIMARY KEY(source,id,local_date,local_time),FOREIGN KEY(source,id) REFERENCES source_records(source,id));
    CREATE TABLE IF NOT EXISTS match_candidates(a TEXT,b TEXT,score REAL,reason TEXT,PRIMARY KEY(a,b));
    CREATE TABLE IF NOT EXISTS publication_approved(source TEXT,id TEXT,approved_on TEXT,PRIMARY KEY(source,id));
    ''')
    return con


def run(data=None,out=None):
    data=data or ROOT/'data';out=out or ROOT/'reports'
    out.mkdir(exist_ok=True,parents=True)
    records=build_records(data)
    pairs=match_pairs(records)
    db=out/'loagendo_v12.sqlite3'
    con=connect(db)
    with con:
        # Idempotent snapshot refresh: remove stale candidates and flags, do not touch approvals.
        for table in ('source_venues','source_organizers','review_flags','candidate_occurrences','match_candidates'):
            con.execute(f'DELETE FROM {table}')
        # Replace known records without breaking any future verified approvals.
        # This is a frozen-window snapshot, not a live incremental deletion feed.
        for r in records:
            con.execute('''INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,id) DO UPDATE SET title=excluded.title,start_date=excluded.start_date,
                end_date=excluded.end_date,kind=excluded.kind,eligibility=excluded.eligibility,
                evidence_level=excluded.evidence_level,source_url=excluded.source_url,
                raw_sha256=excluded.raw_sha256,raw_json=excluded.raw_json''',
                (r['source'],r['id'],r['title'],r['start'],r['end'],r['kind'],r['eligibility'],r['evidence_level'],r['url'],sha(r['raw']),json.dumps(r['raw'],ensure_ascii=False,sort_keys=True)))
            for k,v in enumerate(r['venues']):
                c=v.get('coords')
                con.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)',(r['source'],r['id'],k,v.get('name',''),v.get('address',''),c[0] if c else None,c[1] if c else None))
            for k,v in enumerate(r['organizers']):
                con.execute('INSERT INTO source_organizers VALUES (?,?,?,?)',(r['source'],r['id'],k,v))
            for flag in sorted(set(r['alerts'])):
                con.execute('INSERT INTO review_flags VALUES (?,?,?)',(r['source'],r['id'],flag))
            for v in candidate_sessions(r):
                con.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)',(r['source'],r['id'],v['local_date'],v['local_time'],v['type'],v['evidence_field']))
        for p in pairs:
            con.execute('INSERT INTO match_candidates VALUES (?,?,?,?)',(p['a'],p['b'],p['similarity_heuristic'],';'.join(p['risks'])))
    counts={t:con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('source_records','source_venues','source_organizers','review_flags','candidate_occurrences','match_candidates','publication_approved')}
    per_source=dict(con.execute('SELECT source, COUNT(*) FROM source_records GROUP BY source'))
    eligibility=dict(con.execute('SELECT eligibility, COUNT(*) FROM source_records GROUP BY eligibility'))
    kind=dict(con.execute('SELECT kind, COUNT(*) FROM source_records GROUP BY kind'))
    candidates_by_source=dict(con.execute('SELECT source, COUNT(*) FROM candidate_occurrences GROUP BY source'))
    flag_summary=dict(con.execute('SELECT issue, COUNT(*) FROM review_flags GROUP BY issue ORDER BY COUNT(*) DESC'))
    con.close()
    reference=json.loads((ROOT/'benchmarks/referencia_17_sesiones.json').read_text())
    m={'project':'Loagendo','version':'1.2','window_inclusive_start':str(START),'window_exclusive_end':str(END),'source_record_counts':per_source,'eligibility_preliminary':eligibility,'kind_preliminary':kind,'database_row_counts':counts,'unverified_syntactic_candidates_by_source':candidates_by_source,'flag_counts':flag_summary,'municipal_reference_sessions':len(reference),'pair_candidates_for_manual_review':len(pairs),'limitations':['No representative city coverage estimate','No automatic deduplication or publication','Timestamp candidate is not verified occurrence','GuiaBCN reference is curated metadata, not original page snapshots','No API model tested and no token costs measured','Licenses for municipal HTML/images not established'],'source_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.glob('*.json'))}}
    (out/'metricas_v12.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'correspondencias_candidatas.json').write_text(json.dumps(pairs,ensure_ascii=False,indent=2),encoding='utf8')
    # Actionable review backlog, score by risk of erroneous automatic publication.
    backlog=[]
    for r in records:
        priority=0
        flag=set(r['alerts'])
        if 'MULTI_VENUE_SESSION_NOT_RESOLVED' in flag:priority+=4
        if 'END_DATE_APPROXIMATE' in flag:priority+=4
        if 'LONG_RANGE_DO_NOT_EXPAND' in flag:priority+=3
        if 'NO_SCHEDULE_SOURCE' in flag or 'MIDNIGHT_PLACEHOLDER_NOT_START_TIME' in flag:priority+=3
        if r['kind']=='program':priority+=3
        if r['eligibility']=='exclude':priority=-1
        if r['source']=='guiabcn':priority+=2
        backlog.append({'id':r['source']+':'+r['id'],'title':r['title'],'source':r['source'],'kind':r['kind'],'eligibility':r['eligibility'],'priority_score_not_probability':priority,'start':r['start'],'end':r['end'],'venue_count':len(r['venues']),'flags':sorted(flag),'source_url':r['url']})
    backlog.sort(key=lambda r:(-r['priority_score_not_probability'],r['source'],r['id']))
    (out/'cola_revision_v12.json').write_text(json.dumps(backlog,ensure_ascii=False,indent=2),encoding='utf8')
    return m

if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=False,indent=2))
