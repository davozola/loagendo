import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from mvp import catalog
from run import make_handler

class TestCatalogAndApi(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'test.sqlite3'
        with sqlite3.connect(self.db) as c:
            c.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT,PRIMARY KEY(source,id));
            CREATE TABLE source_venues(source TEXT,id TEXT,seq INTEGER,venue TEXT,address TEXT,lat REAL,lon REAL,PRIMARY KEY(source,id,seq));
            CREATE TABLE source_organizers(source TEXT,id TEXT,seq INTEGER,name TEXT,PRIMARY KEY(source,id,seq));
            CREATE TABLE review_flags(source TEXT,id TEXT,issue TEXT,PRIMARY KEY(source,id,issue));
            CREATE TABLE candidate_occurrences(source TEXT,id TEXT,local_date TEXT,local_time TEXT,kind TEXT,evidence_field TEXT,PRIMARY KEY(source,id,local_date,local_time));
            ''')
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',('diba_bibliotecas','1','Hora del conte','2026-10-17','2026-10-17','single','review','api_raw_unverified','https://example.org','hash',json.dumps({'titol':'Hora del conte','grup_adreca':{'municipi_nom':'Barcelona - Nou Barris'},'tipus':['Hora del conte'],'acte_url':'https://example.org'},ensure_ascii=False)))
            c.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)',('diba_bibliotecas','1',0,'Biblioteca Nou Barris','Barcelona',41.1,2.1))
            c.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)',('diba_bibliotecas','1','2026-10-17','17:30','syntactic','data_inici'))
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',('diba_bibliotecas','3','Ciclo de prueba','2026-10-17','2026-10-19','program','review','api_raw_unverified','https://example.org/ciclo','hash3',json.dumps({'titol':'Ciclo de prueba','grup_adreca':{'municipi_nom':'Barcelona - Nou Barris'}},ensure_ascii=False)))
            c.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)',('diba_bibliotecas','3',0,'Biblioteca Nou Barris','Barcelona',41.1,2.1))
            c.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)',('diba_bibliotecas','3','2026-10-17','18:00','syntactic','data_inici'))
            c.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)',('diba_bibliotecas','3','2026-10-18','20:00','syntactic','data_inici'))
            c.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',('generalitat','2','Exposició','2026-09-01','2027-02-01','exhibition','review','api_raw_unverified','','hash',json.dumps({'localizaciones':[{'denominaci':'Exposició','tags_categor_es':'agenda:categories/exposicions','data_inici':'2026-09-01','data_fi':'2027-02-01'}]})))
            catalog.initialize(c)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.db))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close();self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self,method,path,body=None,headers=None,host=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        h={'Host':host or f'127.0.0.1:{self.server.server_port}',**(headers or {})}
        c.request(method,path,body=body,headers=h)
        r=c.getresponse();data=r.read();status=r.status;c.close()
        return status,json.loads(data) if path.startswith('/api/') else data

    def test_list_filter_date_not_daily_inflation(self):
        code,res=self.request('GET','/api/events?date=2026-10-17')
        self.assertEqual(code,200)
        self.assertEqual(res['total'],3)
        self.assertEqual([x['id'] for x in res['items']],['1','3','2'])  # by time, then the running exhibition
        self.assertEqual(sum(len(x['occurrences']) for x in res['items']),3)

    def test_source_and_district(self):
        code,res=self.request('GET','/api/events?district=Nou%20Barris')
        self.assertEqual(code,200);self.assertEqual(res['total'],2)
        self.assertEqual(res['items'][0]['district'],'Nou Barris')

    def test_readiness_endpoint_is_local_and_reports_coverage(self):
        code,res=self.request('GET','/api/readiness')
        self.assertEqual(code,200)
        self.assertEqual(res['events_next_days'],3)
        self.assertIn(res['release_status'],('not_ready','ready_for_manual_release'))

    def test_detail_does_not_validate_time(self):
        code,res=self.request('GET','/api/event?source=diba_bibliotecas&id=1')
        self.assertEqual(code,200);self.assertFalse(res['occurrences'][0]['verified']);self.assertFalse(res['published'])
        self.assertEqual(res['editorial_summary'],'Actividad literaria en Biblioteca Nou Barris el sábado 17 de octubre a las 17:30.')

    def test_structured_source_metadata_is_not_rendered_as_description(self):
        self.assertEqual(catalog.source_description({'observation':{'item':[{'label':'Web'}]}},'guiabcn'),'')
        self.assertEqual(catalog.source_description({'observation':'Quan: dissabte, 17 h'},'guiabcn'),'')

    def test_legacy_guiabcn_agenda_is_exposed_as_a_one_shot_format(self):
        self.assertEqual(catalog.effective_kind('guiabcn',{},'Agenda','Una charla puntual','2026-10-12','2026-10-12'),'single')
        self.assertEqual(catalog.format_of('single','Taller de cerámica','2026-10-12','2026-10-12'),'workshop')
        self.assertEqual(catalog.format_of('program','Espectacle de teatre','2026-10-01','2026-10-25'),'one_shot')
        self.assertEqual(catalog.format_of('program','Cicle de concerts','2026-10-01','2026-10-25'),'program')
        self.assertEqual(catalog.public_category('Música y vida nocturna','web_conciertos_club','Artista sin la palabra concierto'),'Conciertos')
        self.assertEqual(catalog.public_category('Música y vida nocturna','guiabcn','Concierto de jazz'),'Conciertos')

    def test_featured_ranking_prefers_a_scheduled_one_shot(self):
        base={'start':'2026-10-12','time':None,'has_candidate':False,'media':[],'venue_names':[],'coordinates':None}
        single={**base,'format':'one_shot','time':'19:00','venue_names':['Sala'], 'media':[{'url':'/media/1'}]}
        exhibition={**base,'format':'exhibition','start':'2026-09-01'}
        self.assertGreater(catalog.featured_score(single,'2026-10-12')[0],catalog.featured_score(exhibition,'2026-10-12')[0])

    def test_event_media_ignores_page_logo_but_keeps_activity_photo(self):
        with sqlite3.connect(self.db) as c:
            c.execute("""INSERT INTO media_assets(source,id,original_url,alt_text,rights_status,local_path,content_type)
                         VALUES(?,?,?,?,?,?,?)""",('diba_bibliotecas','1','https://www.barcelona.cat/assets/images/brand/banner/logo-ajbcn.svg','Logo Ajuntament de Barcelona','unknown','/tmp/logo.svg','image/svg+xml'))
            c.execute("""INSERT INTO media_assets(source,id,original_url,alt_text,rights_status,local_path,content_type)
                         VALUES(?,?,?,?,?,?,?)""",('diba_bibliotecas','1','https://images.example.org/activity.jpg','Cartel de la actividad','unknown','/tmp/activity.jpg','image/jpeg'))
            c.commit()
        code,event=self.request('GET','/api/event?source=diba_bibliotecas&id=1')
        self.assertEqual(code,200)
        self.assertEqual([(item['alt'],item['url']) for item in event['media']], [('Cartel de la actividad','/media/2')])

    def test_review_audit_and_no_publication(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','status':'needs_evidence','note':'Comprobar hora y aforo.'})
        h={'Content-Type':'application/json','X-Loagendo-Local':'1'}
        code,res=self.request('POST','/api/review',body,h)
        self.assertEqual(code,200);self.assertFalse(res['published']);self.assertEqual(res['status'],'needs_evidence')
        code,d=self.request('GET','/api/event?source=diba_bibliotecas&id=1');self.assertEqual(d['review_note'],'Comprobar hora y aforo.')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM editorial_review_log').fetchone()[0],1)

    def test_field_verification_requires_evidence_and_is_audited(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','field':'venue','value':'Biblioteca verificada','evidence_url':'https://example.org/ficha','checked_on':'2026-10-10','note':'Ficha oficial comprobada.'})
        h={'Content-Type':'application/json','X-Loagendo-Local':'1'}
        code,res=self.request('POST','/api/verification',body,h)
        self.assertEqual(code,200);self.assertEqual(res['field'],'venue')
        code,d=self.request('GET','/api/event?source=diba_bibliotecas&id=1')
        self.assertEqual(code,200);self.assertEqual(d['verified_fields'][0]['value'],'Biblioteca verificada')
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT count(*) FROM field_verification_log').fetchone()[0],1)

    def test_publication_decision_is_explicit_but_never_publishes(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','status':'approved','note':'Aprobación editorial registrada.'})
        code,res=self.request('POST','/api/publication',body,{'Content-Type':'application/json','X-Loagendo-Local':'1'})
        self.assertEqual(code,200);self.assertTrue(res['published'])
        code,d=self.request('GET','/api/event?source=diba_bibliotecas&id=1')
        self.assertEqual(code,200);self.assertEqual(d['publication_status'],'approved');self.assertTrue(d['published'])

    def test_no_cross_site_or_ambient_csrf(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','status':'reviewed','note':'Comprobado correctamente'})
        code,_=self.request('POST','/api/review',body,{'Content-Type':'application/json'})
        self.assertEqual(code,403)
        code,_=self.request('POST','/api/review',body,{'Content-Type':'application/json','X-Loagendo-Local':'1','Origin':'https://evil.example'})
        self.assertEqual(code,403)
        code,_=self.request('GET','/api/stats',host='evil.example')
        self.assertEqual(code,403)

    def test_exclusion_requires_note(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','status':'excluded','note':''})
        code,_=self.request('POST','/api/review',body,{'Content-Type':'application/json','X-Loagendo-Local':'1'})
        self.assertEqual(code,400)

    def test_invalid_inputs(self):
        code,_=self.request('GET','/api/events?date=notdate');self.assertEqual(code,400)
        code,_=self.request('GET','/api/events?hour_from=19&hour_to=18');self.assertEqual(code,400)
        code,_=self.request('GET','/api/event?source=diba_bibliotecas&id=notfound');self.assertEqual(code,404)

    def test_hour_range_uses_date_specific_occurrence(self):
        code,res=self.request('GET','/api/events?day=2026-10-17&hour_from=17&hour_to=17')
        self.assertEqual(code,200);self.assertEqual([item['id'] for item in res['items']],['1'])
        code,res=self.request('GET','/api/events?day=2026-10-17&hour_from=18&hour_to=18')
        self.assertEqual(code,200);self.assertEqual([item['id'] for item in res['items']],['3'])

    def test_detail_uses_the_hour_of_the_consulted_day_for_a_multi_day_event(self):
        code,event=self.request('GET','/api/event?source=diba_bibliotecas&id=3&day=2026-10-18')
        self.assertEqual(code,200);self.assertEqual(event['time'],'20:00')

    def test_no_external_js_or_images(self):
        code,page=self.request('GET','/')
        self.assertEqual(code,200)
        self.assertIn(b'/public.js',page)
        self.assertIn(b'/vendor/leaflet.js',page)
        self.assertNotIn(b'https://fonts.googleapis.com',page)
        code,leaflet=self.request('GET','/vendor/leaflet.js')
        self.assertEqual(code,200);self.assertIn(b'Leaflet',leaflet[:1000])
        code,admin=self.request('GET','/admin')
        self.assertEqual(code,200);self.assertIn(b'/admin/app.js',admin)

    def test_public_event_contract_day_category_free_and_curated(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE source_records SET raw_json=?,raw_sha256='hash-v2' WHERE source='diba_bibliotecas' AND id='1'",(json.dumps({'titol':'Hora del conte','grup_adreca':{'municipi_nom':'Barcelona - Nou Barris'},'tipus':['Hora del conte'],'preu':'Gratis'},ensure_ascii=False),))
            c.commit()
        catalog.invalidate_cache()  # an external writer changed the source row
        code,res=self.request('GET','/api/events?day=2026-10-17&public_category=Familia&free=1')
        self.assertEqual(code,200);self.assertEqual(res['total'],1)
        item=res['items'][0]
        self.assertEqual((item['public_category'],item['time'],item['url']),('Familia','17:30','https://example.org'))
        self.assertTrue(item['is_free']);self.assertEqual(item['price_label'],'Gratis')
        self.assertEqual(item['coordinates'],{'lat':41.1,'lon':2.1})
        body=json.dumps({'source':'diba_bibliotecas','id':'1','position':0,'week_start':'2026-10-17'})
        code,_=self.request('POST','/api/curate',body,{'Content-Type':'application/json','X-Loagendo-Local':'1'})
        self.assertEqual(code,200)
        code,res=self.request('GET','/api/events?day=2026-10-17&curated=1')
        self.assertEqual(code,200);self.assertEqual(res['total'],1)

if __name__=='__main__':unittest.main()
