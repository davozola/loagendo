"""Reproducible publication-readiness audit for the local catalogue.

It deliberately measures coverage, rather than claiming that a collection of
third-party and public agendas is exhaustive.  The result is suitable for a
release checklist and can be run before every deployment.
"""
from __future__ import annotations

import datetime as dt
import json

from mvp.catalog import source_description


def _table(conn, name):
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


from src.guia_detail import usable_description


def report(conn, *, today=None, horizon_days=30):
    today=today or dt.date.today()
    until=today + dt.timedelta(days=horizon_days)
    rows=conn.execute('''SELECT source,id,raw_json,start_date,end_date
      FROM source_records WHERE end_date>=? AND start_date<=?''', (today.isoformat(), until.isoformat())).fetchall()
    by_source={}
    raw_by_key={}
    description=0
    for source, record_id, raw_text, start, end in rows:
        try: raw=json.loads(raw_text)
        except (TypeError, json.JSONDecodeError): raw={}
        raw_by_key[(source,record_id)]=raw
        item=by_source.setdefault(source, {'events':0,'descriptions':0,'images':0,'scheduled_point_events':0,'point_events':0})
        item['events']+=1
        if source_description(raw,source).strip():
            description+=1; item['descriptions']+=1
        if start==end:
            item['point_events']+=1
    keys={(source,record_id) for source,record_id,_,_,_ in rows}
    if _table(conn,'source_enrichments'):
        for source,record_id,text,schedule in conn.execute("SELECT source,id,description,COALESCE(schedule_time,'') FROM source_enrichments"):
            if (source,record_id) not in keys: continue
            item=by_source[source]
            # An official page description upgrades coverage only if the API
            # did not already supply one.
            if text and len(text.strip()) >= 40 and usable_description(text):
                raw=raw_by_key.get((source,record_id),{})
                if not source_description(raw,source).strip(): description+=1; item['descriptions']+=1
            if schedule and item['point_events']:
                item['_scheduled_enrichment']=item.get('_scheduled_enrichment',0)+1
    candidate=set()
    if _table(conn,'candidate_occurrences'):
        candidate={(s,i) for s,i in conn.execute("SELECT DISTINCT source,id FROM candidate_occurrences WHERE local_time<>''")}
    media=set()
    if _table(conn,'media_assets'):
        media={(s,i) for s,i in conn.execute("SELECT DISTINCT source,id FROM media_assets WHERE local_path IS NOT NULL")}
    # «Imagen visible» = lo que publica la web: imagen propia autorizada y en disco,
    # o la foto del recinto como respaldo. with_local_image se mantiene igual.
    authorized=set()
    if _table(conn,'media_assets'):
        authorized={(s,i) for s,i in conn.execute("SELECT DISTINCT source,id FROM media_assets WHERE local_path IS NOT NULL AND rights_status='authorized'")}
    from src.place_images import local_place_images, place_of
    venue_photos=local_place_images(conn)
    point=scheduled=images=visible=0
    for source,record_id,_,start,end in rows:
        item=by_source[source]
        if (source,record_id) in media:
            images+=1; item['images']+=1
        place=place_of(raw_by_key.get((source,record_id),{}),source)
        if (source,record_id) in authorized or (place and place[0] in venue_photos):
            visible+=1; item['visible_images']=item.get('visible_images',0)+1
        if start==end: point+=1
    schedule_keys=set(candidate)
    if _table(conn,'source_enrichments'):
        schedule_keys.update((s,i) for s,i in conn.execute("SELECT source,id FROM source_enrichments WHERE COALESCE(schedule_time,'')<>''"))
    for source,record_id,_,start,end in rows:
        if start==end and (source,record_id) in schedule_keys:
            scheduled+=1; by_source[source]['scheduled_point_events']+=1
    for item in by_source.values(): item.pop('_scheduled_enrichment',None)
    total=len(rows)
    def coverage(value, denominator): return round(100*value/denominator,1) if denominator else 0.0
    health=[]
    if _table(conn,'source_health'):
        # A direct successful sync is also valid evidence of connector
        # recovery. Do not keep a historical automation error as a false
        # release blocker after an operator has proved the source works.
        health=[]
        for s,failed_at,status,fails,error in conn.execute("SELECT source,last_failure_at,last_status,consecutive_failures,last_error FROM source_health WHERE last_status<>'completed' ORDER BY source"):
            latest=conn.execute("SELECT MAX(finished_at) FROM sync_runs WHERE source=? AND status='completed'",(s,)).fetchone()[0]
            if latest and (not failed_at or latest>=failed_at): continue
            health.append({'source':s,'status':status,'consecutive_failures':fails,'error':error})
    duplicates=0
    if _table(conn,'match_candidates'):
        active={f'{s}:{i}' for s,i,_,_,_ in rows}
        duplicates=sum(1 for a,b in conn.execute('SELECT a,b FROM match_candidates') if a in active and b in active)
    excluded=conn.execute("SELECT COUNT(*) FROM source_records WHERE eligibility='exclude' AND end_date>=? AND start_date<=?",(today.isoformat(),until.isoformat())).fetchone()[0]
    metrics={
        'events_next_days':total,'excluded_from_public':excluded,'duplicate_candidate_pairs_in_window':duplicates, 'window':{'from':today.isoformat(),'to':until.isoformat(),'days':horizon_days},
        'with_description':description, 'description_coverage_percent':coverage(description,total),
        'with_local_image':images, 'local_image_coverage_percent':coverage(images,total),
        'with_visible_image':visible, 'visible_image_coverage_percent':coverage(visible,total),
        'point_events':point, 'point_events_with_time':scheduled,
        'point_time_coverage_percent':coverage(scheduled,point),
        'by_source':dict(sorted(by_source.items())), 'unhealthy_sources':health,
    }
    blockers=[]
    if health: blockers.append('Hay conectores con errores o volumen anómalo recientes; resuélvelos o exclúyelos explícitamente de la publicación.')
    if metrics['description_coverage_percent'] < 60: blockers.append('La cobertura de descripciones aún es inferior al 60 %.')
    if metrics['point_time_coverage_percent'] < 70: blockers.append('La cobertura de horarios de actos puntuales aún es inferior al 70 %.')
    metrics['release_status']='ready_for_manual_release' if not blockers else 'not_ready'
    metrics['blockers']=blockers
    return metrics
