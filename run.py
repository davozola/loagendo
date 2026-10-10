#!/usr/bin/env python3
"""Private local-only Loagendo prototype; standard library, never a public web server."""
from __future__ import annotations
import argparse
import json
import sqlite3
from pathlib import Path
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from mvp import catalog

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'reports' / 'loagendo_v12.sqlite3'
STATIC = ROOT / 'static'


def bootstrap(db=DB, import_snapshot=True):
    db.parent.mkdir(parents=True,exist_ok=True)
    if import_snapshot and not db.exists():
        from src.pipeline import run
        # The bundled snapshot and derived tables remain unverified.
        run(out=db.parent)
    if not db.exists():raise RuntimeError('No hay base de datos. Ejecuta: python3 run.py --rebuild-snapshot')
    with closing(catalog.connect(db)) as conn:
        catalog.initialize(conn)
        conn.commit()
    return db


def make_handler(db):
    class Handler(BaseHTTPRequestHandler):
        def _allowed_host(self):
            host=self.headers.get('Host','')
            return host in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        server_version = 'LoagendoLocal/0.13'
        def log_message(self, fmt,*args):
            print('[LOCAL]',fmt%args)
        def _json(self, data,status=200):
            raw=json.dumps(data,ensure_ascii=False,default=str).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'")
            self.end_headers(); self.wfile.write(raw)
        def _file(self,name,ctype):
            path=STATIC/name
            if not path.is_file():return self._json({'error':'No encontrado'},404)
            raw=path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(raw)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self'; font-src 'self'; style-src 'self'; script-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path=='/':return self._file('index.html','text/html; charset=utf-8')
            if url.path=='/app.css':return self._file('app.css','text/css; charset=utf-8')
            if url.path=='/app.js':return self._file('app.js','application/javascript; charset=utf-8')
            if url.path not in ('/api/stats','/api/events','/api/event','/api/health','/api/options'):
                return self._json({'error':'No encontrado'},404)
            args={k:v[0] for k,v in parse_qs(url.query,keep_blank_values=True).items()}
            try:
                with closing(catalog.connect(db)) as conn:
                    if url.path=='/api/health':out={'status':'ok','mode':'private_local','publication_enabled':False}
                    elif url.path=='/api/options':out={'categories':catalog.CATEGORIES,'districts':catalog.DISTRICTS,'sources':catalog.SOURCES,'kinds':catalog.KINDS,'statuses':catalog.STATUS}
                    elif url.path=='/api/stats':out=catalog.stats(conn)
                    elif url.path=='/api/event':
                        out=catalog.event_detail(conn,args.get('source',''),args.get('id',''))
                        if out is None:return self._json({'error':'No encontrado'},404)
                    else:
                        out=catalog.query_events(conn,query=args.get('query',''),date=args.get('date',''),category=args.get('category',''),district=args.get('district',''),source=args.get('source',''),status=args.get('status',''),kind=args.get('kind',''),only_sessions=args.get('only_sessions','')=='1',page=int(args.get('page','1')),page_size=int(args.get('page_size','24')))
                return self._json(out)
            except (ValueError,OverflowError) as err:return self._json({'error':str(err)},400)
            except Exception as err:
                print('Error del servidor:',repr(err))
                return self._json({'error':'Error interno. Consulta el terminal.'},500)
        def do_POST(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path!='/api/review':return self._json({'error':'No encontrado'},404)
            # Only local browsers, no external form submission and no ambient-auth CSRF.
            if self.headers.get('X-Loagendo-Local')!='1':return self._json({'error':'Cabecera local requerida'},403)
            origin=self.headers.get('Origin','')
            host=f'http://{self.headers.get("Host", "")}';
            if origin and origin!=host:return self._json({'error':'Origen no permitido'},403)
            if 'application/json' not in self.headers.get('Content-Type',''):return self._json({'error':'Se requiere JSON'},415)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if size<1 or size>8192:return self._json({'error':'Tamaño no permitido'},413)
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('JSON objeto requerido')
                source=data.get('source','');id=data.get('id','');status=data.get('status','');note=data.get('note','')
                if not all(isinstance(x,str) for x in (source,id,status,note)):
                    raise ValueError('Campos de texto requeridos')
                with closing(catalog.connect(db)) as conn:
                    out=catalog.save_review(conn,source,id,status,note)
                self._json(out)
            except (ValueError,json.JSONDecodeError) as err:return self._json({'error':str(err)},400)
            except LookupError as err:return self._json({'error':str(err)},404)
    return Handler


def main():
    parser=argparse.ArgumentParser(description='Loagendo MVP privado (localhost)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--rebuild-snapshot',action='store_true',help='Reimporta los snapshots (conserva revisiones)')
    a=parser.parse_args()
    if not (1<=a.port<=65535):parser.error('Puerto inválido')
    if a.rebuild_snapshot:
        from src.pipeline import run
        run(out=DB.parent)
    bootstrap()
    server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(DB))
    print(f'Loagendo local: http://127.0.0.1:{a.port}')
    print('Solo en este Mac. Sin publicación, imágenes externas ni llamadas a IA. Ctrl+C para detenerlo.')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
