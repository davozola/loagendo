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
        def _media(self, asset_id):
            if not asset_id.isdigit(): return self._json({'error':'No encontrado'},404)
            with closing(catalog.connect(db)) as conn:
                row=conn.execute('SELECT local_path,content_type FROM media_assets WHERE asset_id=?',(int(asset_id),)).fetchone()
            if not row or not row[0]: return self._json({'error':'No encontrado'},404)
            media_root=(ROOT/'data'/'media').resolve(); path=Path(row[0]).resolve()
            if media_root not in path.parents or not path.is_file(): return self._json({'error':'No encontrado'},404)
            raw=path.read_bytes(); self.send_response(200); self.send_header('Content-Type',row[1] or 'application/octet-stream'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','private, max-age=86400'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path=='/':return self._file('index.html','text/html; charset=utf-8')
            if url.path=='/app.css':return self._file('app.css','text/css; charset=utf-8')
            if url.path=='/revamp.css':return self._file('revamp.css','text/css; charset=utf-8')
            if url.path=='/app.js':return self._file('app.js','application/javascript; charset=utf-8')
            if url.path.startswith('/media/'):return self._media(url.path.removeprefix('/media/'))
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
                        out=catalog.query_events(conn,query=args.get('query',''),date=args.get('date',''),category=args.get('category',''),district=args.get('district',''),source=args.get('source',''),status=args.get('status',''),kind=args.get('kind',''),only_sessions=args.get('only_sessions','')=='1',featured=args.get('featured','')=='1',page=int(args.get('page','1')),page_size=int(args.get('page_size','24')))
                return self._json(out)
            except (ValueError,OverflowError) as err:return self._json({'error':str(err)},400)
            except Exception as err:
                print('Error del servidor:',repr(err))
                return self._json({'error':'Error interno. Consulta el terminal.'},500)
        def do_POST(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path not in ('/api/review','/api/verification','/api/publication'):return self._json({'error':'No encontrado'},404)
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
                source=data.get('source','');id=data.get('id','');note=data.get('note','')
                if not all(isinstance(x,str) for x in (source,id,note)):raise ValueError('Campos de texto requeridos')
                with closing(catalog.connect(db)) as conn:
                    catalog.initialize(conn)
                    if url.path=='/api/review':
                        out=catalog.save_review(conn,source,id,data.get('status',''),note)
                    elif url.path=='/api/publication':
                        out=catalog.save_publication_decision(conn,source,id,data.get('status',''),note)
                    else:
                        out=catalog.save_field_verification(conn,source,id,data.get('field',''),data.get('value'),data.get('evidence_url',''),data.get('checked_on',''),note)
                self._json(out)
            except (ValueError,json.JSONDecodeError) as err:return self._json({'error':str(err)},400)
            except LookupError as err:return self._json({'error':str(err)},404)
    return Handler


def main():
    parser=argparse.ArgumentParser(description='Loagendo MVP privado (localhost)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--rebuild-snapshot',action='store_true',help='Reimporta los snapshots (conserva revisiones)')
    parser.add_argument('--sync',choices=('generalitat','diba_bibliotecas','diba_turismo','guiabcn'),help='Sincroniza una API autorizada y termina; no inicia el servidor')
    parser.add_argument('--endpoint',help='Endpoint HTTPS de la API para --sync')
    parser.add_argument('--page-size',type=int,default=100,help='Filas por página (1–1000)')
    parser.add_argument('--max-rows',type=int,default=1000,help='Máximo explícito de filas (1–10000)')
    parser.add_argument('--sync-timeout',type=int,default=30,help='Límite total de segundos (1–300)')
    parser.add_argument('--enrich-guiabcn',type=int,metavar='MAX',help='Enriquece hasta MAX fichas de detalle GuiaBCN y registra referencias de imagen')
    parser.add_argument('--download-local-media',type=int,metavar='MAX',help='Descarga referencias de imagen para esta copia local; no cambia sus derechos')
    a=parser.parse_args()
    if not (1<=a.port<=65535):parser.error('Puerto inválido')
    if a.rebuild_snapshot:
        from src.pipeline import run
        run(out=DB.parent)
    bootstrap()
    if a.enrich_guiabcn is not None:
        if not 1<=a.enrich_guiabcn<=100:parser.error('MAX debe estar entre 1 y 100')
        from src.guia_detail import enrich
        with closing(sqlite3.connect(DB)) as conn:
            print(json.dumps(enrich(conn,a.enrich_guiabcn),ensure_ascii=False,indent=2))
        return 0
    if a.download_local_media is not None:
        if not 1<=a.download_local_media<=100:parser.error('MAX debe estar entre 1 y 100')
        from src.media import download_local_previews
        with closing(sqlite3.connect(DB)) as conn:
            catalog.initialize(conn)
            print(json.dumps(download_local_previews(conn,ROOT/'data'/'media',a.download_local_media),ensure_ascii=False,indent=2))
        return 0
    if a.sync:
        if not a.endpoint and a.sync!='guiabcn':
            parser.error('--endpoint HTTPS es obligatorio con --sync; no hay endpoint implícito ni scraping')
        from src.sync import GUIABCN_ENDPOINT, IncrementalSync
        with closing(sqlite3.connect(DB)) as conn:
            result=IncrementalSync(conn).run(a.sync,a.endpoint or GUIABCN_ENDPOINT,page_size=a.page_size,max_rows=a.max_rows,timeout_seconds=a.sync_timeout)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='completed' else 2
    server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(DB))
    print(f'Loagendo local: http://127.0.0.1:{a.port}')
    print('Solo en este Mac. Las imágenes locales pueden estar pendientes de derechos. Ctrl+C para detenerlo.')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':raise SystemExit(main() or 0)
