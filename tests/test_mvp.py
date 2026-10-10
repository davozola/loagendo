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
        self.assertEqual(res['total'],2)
        self.assertEqual(res['items'][0]['id'],'1')
        self.assertEqual(sum(len(x['occurrences']) for x in res['items']),1)

    def test_source_and_district(self):
        code,res=self.request('GET','/api/events?district=Nou%20Barris')
        self.assertEqual(code,200);self.assertEqual(res['total'],1)
        self.assertEqual(res['items'][0]['district'],'Nou Barris')

    def test_detail_does_not_validate_time(self):
        code,res=self.request('GET','/api/event?source=diba_bibliotecas&id=1')
        self.assertEqual(code,200);self.assertFalse(res['occurrences'][0]['verified']);self.assertFalse(res['published'])

    def test_review_audit_and_no_publication(self):
        body=json.dumps({'source':'diba_bibliotecas','id':'1','status':'needs_evidence','note':'Comprobar hora y aforo.'})
        h={'Content-Type':'application/json','X-Loagendo-Local':'1'}
        code,res=self.request('POST','/api/review',body,h)
        self.assertEqual(code,200);self.assertFalse(res['published']);self.assertEqual(res['status'],'needs_evidence')
        code,d=self.request('GET','/api/event?source=diba_bibliotecas&id=1');self.assertEqual(d['review_note'],'Comprobar hora y aforo.')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM editorial_review_log').fetchone()[0],1)

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
        code,_=self.request('GET','/api/event?source=diba_bibliotecas&id=notfound');self.assertEqual(code,404)

    def test_no_external_js_or_images(self):
        code,page=self.request('GET','/')
        self.assertEqual(code,200)
        self.assertIn(b'/app.js',page)
        self.assertNotIn(b'https://fonts.googleapis.com',page)

if __name__=='__main__':unittest.main()
