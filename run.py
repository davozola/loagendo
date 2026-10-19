#!/usr/bin/env python3
"""Private local-only Brollant (antes Loagendo) prototype; standard library, never a public web server."""
from __future__ import annotations
import argparse
import json
import sqlite3
import time
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
        # Readers (the web server) and the writer (the engine) coexist only in
        # WAL mode; the setting is persistent in the file.
        try: conn.execute('PRAGMA journal_mode=WAL')
        except sqlite3.OperationalError as err: print('Aviso: no se pudo activar WAL:',err)
        # Image rights follow the per-source editorial policy in docs/source_registry.json.
        from src.media import apply_rights_policy
        applied=apply_rights_policy(conn)
        if applied: print('Derechos de imagen aplicados por política de fuente:',applied)
    return db


def warm_listing(db=DB):
    """Build the listing before the server accepts its first request."""
    started=time.monotonic()
    with closing(catalog.connect(db)) as conn:
        try: count=len(catalog.all_events(conn))
        except Exception as err: print('Aviso: no se pudo precalentar el listado:',repr(err)); return
    print(f'Listado precalentado: {count} fichas en {time.monotonic()-started:.2f} s')


def make_handler(db):
    class Handler(BaseHTTPRequestHandler):
        def _allowed_host(self):
            host=self.headers.get('Host','')
            return host in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        server_version = 'BrollantLocal/0.13'
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
            # Leaflet positions its canvas and controls with runtime style
            # attributes; scripts remain restricted to local bundled files.
            self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; img-src 'self' https://tile.openstreetmap.org; font-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-src https://www.openstreetmap.org; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers();self.wfile.write(raw)
        def _place_media(self, place_id):
            if not place_id.isdigit(): return self._json({'error':'No encontrado'},404)
            from src.place_images import local_place_images
            with closing(catalog.connect(db)) as conn: place=local_place_images(conn).get(place_id)
            if not place or not place.get('local_path'): return self._json({'error':'No encontrado'},404)
            media_root=(ROOT/'data'/'media').resolve(); path=Path(place['local_path']).resolve()
            if media_root not in path.parents or not path.is_file(): return self._json({'error':'No encontrado'},404)
            raw=path.read_bytes(); self.send_response(200); self.send_header('Content-Type',place.get('content_type') or 'application/octet-stream'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','private, max-age=86400'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
        def _media(self, asset_id):
            if asset_id.startswith('place/'): return self._place_media(asset_id[6:])
            if not asset_id.isdigit(): return self._json({'error':'No encontrado'},404)
            from src.media import ensure_local
            with closing(catalog.connect(db)) as conn:
                row=ensure_local(conn,int(asset_id),ROOT/'data'/'media')
            if not row or not row[0]: return self._json({'error':'No encontrado'},404)
            media_root=(ROOT/'data'/'media').resolve(); path=Path(row[0]).resolve()
            if media_root not in path.parents or not path.is_file(): return self._json({'error':'No encontrado'},404)
            raw=path.read_bytes(); self.send_response(200); self.send_header('Content-Type',row[1] or 'application/octet-stream'); self.send_header('Content-Length',str(len(raw))); self.send_header('Cache-Control','private, max-age=86400'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path=='/' or url.path.startswith('/e/'):return self._file('index.html','text/html; charset=utf-8')
            if url.path in ('/admin','/admin/'):return self._file('admin/index.html','text/html; charset=utf-8')
            if url.path in ('/creditos','/creditos.html'):
                from src.publish_static import credits_html,_registry
                raw=credits_html(_registry()).encode('utf-8'); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.send_header('X-Frame-Options','DENY'); self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"); self.end_headers(); return self.wfile.write(raw)
            if url.path=='/public.css':return self._file('public.css','text/css; charset=utf-8')
            if url.path=='/public.js':return self._file('public.js','application/javascript; charset=utf-8')
            if url.path=='/vendor/leaflet.css':return self._file('vendor/leaflet.css','text/css; charset=utf-8')
            if url.path=='/vendor/leaflet.js':return self._file('vendor/leaflet.js','application/javascript; charset=utf-8')
            if url.path.startswith('/img/hero-') and url.path.endswith('.webp') and '/' not in url.path[5:]:return self._file(url.path[1:],'image/webp')
            if url.path=='/admin/app.css':return self._file('admin/app.css','text/css; charset=utf-8')
            if url.path=='/admin/app.js':return self._file('admin/app.js','application/javascript; charset=utf-8')
            if url.path.startswith('/media/'):return self._media(url.path.removeprefix('/media/'))
            if url.path not in ('/api/stats','/api/events','/api/event','/api/health','/api/options','/api/districts','/api/readiness','/api/subtypes','/api/classification'):
                return self._json({'error':'No encontrado'},404)
            args={k:v[0] for k,v in parse_qs(url.query,keep_blank_values=True).items()}
            started=time.monotonic()
            try:
                with closing(catalog.connect(db)) as conn:
                    if url.path=='/api/health':out={'status':'ok','mode':'private_local','publication_enabled':False}
                    elif url.path=='/api/readiness':
                        from src.readiness import report
                        out=report(conn)
                    elif url.path=='/api/subtypes':out=catalog.subtype_groups()
                    elif url.path=='/api/classification':
                        from src import taxonomy
                        out=taxonomy.report(conn,catalog.all_events(conn),catalog.today().isoformat())
                    elif url.path=='/api/options':out={'categories':catalog.CATEGORIES,'districts':catalog.DISTRICTS,'sources':catalog.SOURCES,'kinds':catalog.KINDS,'formats':catalog.FORMATS,'statuses':catalog.STATUS}
                    elif url.path=='/api/stats':out=catalog.stats(conn)
                    elif url.path=='/api/districts':out=catalog.districts(conn,args.get('day',''))
                    elif url.path=='/api/event':
                        out=catalog.event_detail(conn,args.get('source',''),args.get('id',''),args.get('day',''))
                        if out is None:return self._json({'error':'No encontrado'},404)
                    else:
                        hour_from=args.get('hour_from',''); hour_to=args.get('hour_to','')
                        out=catalog.query_events(conn,query=args.get('query',''),date=args.get('date',''),day=args.get('day',''),date_from=args.get('date_from',''),date_to=args.get('date_to',''),category=args.get('category',''),public_category=args.get('public_category',''),format=args.get('format',''),free=args.get('free','')=='1',district=args.get('district',''),source=args.get('source',''),status=args.get('status',''),kind=args.get('kind',''),only_sessions=args.get('only_sessions','')=='1',featured=args.get('featured','')=='1',curated=args.get('curated','')=='1',hour_from=int(hour_from) if hour_from else None,hour_to=int(hour_to) if hour_to else None,page=int(args.get('page','1')),page_size=int(args.get('page_size','24')),public=args.get('public','')=='1',include_started=args.get('started','')!='0',subtype=args.get('subtype',''),channel=args.get('channel',''))
                elapsed=(time.monotonic()-started)*1000
                if elapsed>250: print(f'[LENTO] {url.path}?{url.query} {elapsed:.0f} ms')
                return self._json(out)
            except (ValueError,OverflowError) as err:return self._json({'error':str(err)},400)
            except Exception as err:
                print('Error del servidor:',repr(err))
                return self._json({'error':'Error interno. Consulta el terminal.'},500)
        def do_POST(self):
            if not self._allowed_host():return self._json({'error':'Host local requerido'},403)
            url=urlsplit(self.path)
            if url.path not in ('/api/review','/api/verification','/api/publication','/api/curate','/api/classification'):return self._json({'error':'No encontrado'},404)
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
                    elif url.path=='/api/classification':
                        from src import taxonomy
                        if catalog.event_detail(conn,source,id) is None: raise LookupError('Ficha no encontrada')
                        category=data.get('category') or None
                        adds=data.get('channels_add') or []; removes=data.get('channels_remove') or []
                        if not (isinstance(adds,list) and isinstance(removes,list)): raise ValueError('Canales: lista requerida')
                        out=taxonomy.set_override(conn,source,id,category,adds,removes,note); catalog.invalidate_cache()
                    elif url.path=='/api/curate':
                        out=catalog.save_curated_pick(conn,source,id,data.get('position',0),data.get('week_start',''))
                    else:
                        out=catalog.save_field_verification(conn,source,id,data.get('field',''),data.get('value'),data.get('evidence_url',''),data.get('checked_on',''),note)
                self._json(out)
            except (ValueError,json.JSONDecodeError) as err:return self._json({'error':str(err)},400)
            except LookupError as err:return self._json({'error':str(err)},404)
    return Handler


def main():
    parser=argparse.ArgumentParser(description='Brollant MVP privado (localhost)')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--rebuild-snapshot',action='store_true',help='Reimporta los snapshots (conserva revisiones)')
    parser.add_argument('--sync',choices=('generalitat','diba_bibliotecas','diba_turismo','guiabcn'),help='Sincroniza una API autorizada y termina; no inicia el servidor')
    parser.add_argument('--endpoint',help='Endpoint HTTPS de la API para --sync')
    parser.add_argument('--organizers-endpoint',default='',help='Con --sync generalitat: dataset Socrata de organizadores (2n2k-gg9s)')
    parser.add_argument('--since-days',type=int,default=0,help='Con --sync: ignora/detiene en filas terminadas hace más de N días (0 = sin filtro)')
    parser.add_argument('--sync-opendata',action='store_true',help='Importa el dataset «Agenda cultural» de Open Data BCN (CC BY 4.0) y termina')
    parser.add_argument('--opendata-file',help='Con --sync-opendata: usa un JSON ya descargado desde el navegador en lugar de descargarlo')
    parser.add_argument('--page-size',type=int,default=100,help='Filas por página (1–1000)')
    parser.add_argument('--max-rows',type=int,default=1000,help='Máximo explícito de filas (1–10000)')
    parser.add_argument('--sync-timeout',type=int,default=30,help='Límite total de segundos (1–300)')
    parser.add_argument('--enrich-guiabcn',type=int,metavar='MAX',help='Enriquece hasta MAX fichas de detalle GuiaBCN y registra referencias de imagen')
    parser.add_argument('--enrich-details',type=int,metavar='MAX',help='Enriquece hasta MAX fichas de detalle de todas las fuentes conectadas')
    parser.add_argument('--enrich-event',metavar='SOURCE:ID',help='Reconsulta una ficha concreta para recuperar horario, texto e imagen de su fuente')
    parser.add_argument('--download-local-media',type=int,metavar='MAX',help='Descarga referencias de imagen para esta copia local; no cambia sus derechos')
    parser.add_argument('--media-source',help='Limita --download-local-media a una fuente concreta')
    parser.add_argument('--sync-web',choices=('web_macba','web_cccb','web_teatre_lliure','web_auditori','web_centres_civics','web_conciertos_club'),help='Sincroniza una agenda pública permitida')
    parser.add_argument('--run-jobs',action='store_true',help='Ejecuta trabajos de automatización que estén vencidos y termina')
    parser.add_argument('--force-jobs',action='store_true',help='Con --run-jobs, ejecuta también los trabajos aún no vencidos')
    parser.add_argument('--run-job',metavar='NOMBRE',help='Ejecuta un solo trabajo de config/automation.json ahora mismo (p. ej. fotos-equipamientos)')
    parser.add_argument('--automation-status',action='store_true',help='Muestra salud y últimas ejecuciones del motor automático')
    parser.add_argument('--readiness-report',action='store_true',help='Audita cobertura de fichas, horarios, imágenes y conectores antes de publicar')
    parser.add_argument('--match-candidates',action='store_true',help='Recalcula pares candidatos a duplicado (sólo revisión, nunca fusiona)')
    parser.add_argument('--venue-census',action='store_true',help='Comprueba qué recintos de config/venues.json publican datos estructurados (JSON-LD, iCal, RSS); no importa nada')
    parser.add_argument('--sync-venues',action='store_true',help='Importa los recintos con enabled=true en config/venues.json a partir de su JSON-LD schema.org')
    parser.add_argument('--register-images',action='store_true',help='Registra las referencias de imagen de las fichas archivadas que aún no las tenían (Generalitat); no descarga nada')
    parser.add_argument('--retry-failed-media',action='store_true',help='Vuelve a encolar las descargas de imagen que fallaron por red (TLS, timeout, 5xx); los 404 se mantienen')
    parser.add_argument('--rebuild-candidates',action='store_true',help='Recalcula las horas candidatas de todas las fichas a partir del JSON archivado (sin red)')
    parser.add_argument('--reclassify-guiabcn',action='store_true',help='Marca como excluidas las filas GuiaBCN fuera de Barcelona o avisos de calendario; no borra nada')
    parser.add_argument('--automation-config',default=str(ROOT/'config'/'automation.json'),help='Ruta al JSON de trabajos automáticos')
    parser.add_argument('--export-static',metavar='DIR',nargs='?',const='dist',help='Genera la web pública estática (listado, fichas, imágenes autorizadas con crédito) en DIR sin publicarla')
    parser.add_argument('--publish',action='store_true',help='Exporta la web estática y la sube con el comando deploy_command del trabajo publicar-web (config/automation.json)')
    parser.add_argument('--install-launchd',action='store_true',help='Instala el motor como tarea local de macOS cada 15 minutos')
    parser.add_argument('--launchd-interval',type=int,default=900,help='Segundos entre activaciones de launchd (300–86400)')
    a=parser.parse_args()
    if not (1<=a.port<=65535):parser.error('Puerto inválido')
    if a.rebuild_snapshot:
        from src.pipeline import run
        run(out=DB.parent)
    bootstrap()
    if a.force_jobs and not a.run_jobs:
        parser.error('--force-jobs requiere --run-jobs')
    if a.install_launchd:
        from src.launchd import install
        print(json.dumps(install(ROOT,a.launchd_interval),ensure_ascii=False,indent=2))
        return 0
    if a.run_job:
        from src.automation import load_config, run_due
        config=load_config(Path(a.automation_config)); jobs=[j for j in config['jobs'] if j['name']==a.run_job]
        if not jobs: parser.error('No existe el trabajo %s; nombres: %s' % (a.run_job, ', '.join(j['name'] for j in config['jobs'])))
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn); print(json.dumps(run_due(conn,{**config,'jobs':jobs},ROOT/'data'/'media',force=True),ensure_ascii=False,indent=2))
        return 0
    if a.run_jobs or a.automation_status or a.readiness_report:
        from src.automation import load_config, run_due, status
        config=load_config(Path(a.automation_config))
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn)
            if a.automation_status: print(json.dumps(status(conn),ensure_ascii=False,indent=2))
            elif a.readiness_report:
                from src.readiness import report
                print(json.dumps(report(conn),ensure_ascii=False,indent=2))
            else: print(json.dumps(run_due(conn,config,ROOT/'data'/'media',force=a.force_jobs),ensure_ascii=False,indent=2))
        return 0
    if a.export_static or a.publish:
        from src.publish_static import export, publish
        from src.automation import load_config, initialize as init_automation
        with closing(catalog.connect(DB)) as conn:
            if a.publish:
                init_automation(conn)
                job=next((j for j in load_config(Path(a.automation_config))['jobs'] if j.get('kind')=='publish'),{'name':'publicar-web','out_dir':'dist'})
                result=publish(conn,{**job,'force':True},media_root=ROOT/'data'/'media')
            else:
                result=export(conn,ROOT/a.export_static,media_root=ROOT/'data'/'media')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='completed' else 2
    if a.match_candidates:
        from src.dedupe import refresh_match_candidates
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(refresh_match_candidates(conn),ensure_ascii=False,indent=2))
        return 0
    if a.venue_census:
        from src.venue_feeds import census
        result=census()
        print(json.dumps({'checked_at':result['checked_at'],'venues':result['venues'],'by_verdict':result['by_verdict'],'results':[{k:r.get(k) for k in ('slug','verdict','status','jsonld_events','ical','rss','final_url')} for r in result['results']]},ensure_ascii=False,indent=2))
        print('Informe completo en reports/venue_census.json')
        return 0
    if a.sync_venues:
        from src.venue_feeds import sync_enabled
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(sync_enabled(conn),ensure_ascii=False,indent=2))
        return 0
    if a.register_images:
        from src.sync import register_generalitat_images
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn); n=register_generalitat_images(conn); conn.commit()
            from src.media import apply_rights_policy; applied=apply_rights_policy(conn)
        print(json.dumps({'registered':n,'rights_applied':applied},ensure_ascii=False)); return 0
    if a.retry_failed_media:
        from src.media import retry_transient_download_failures
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn); n=retry_transient_download_failures(conn, older_than_days=0)
        print(json.dumps({'requeued':n},ensure_ascii=False)); return 0
    if a.rebuild_candidates:
        from src.sync import rebuild_candidates
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(rebuild_candidates(conn),ensure_ascii=False,indent=2))
        return 0
    if a.reclassify_guiabcn:
        from src.sync import reclassify_guiabcn
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(reclassify_guiabcn(conn),ensure_ascii=False,indent=2))
        return 0
    if a.enrich_guiabcn is not None:
        if not 1<=a.enrich_guiabcn<=100:parser.error('MAX debe estar entre 1 y 100')
        from src.guia_detail import enrich
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(enrich(conn,a.enrich_guiabcn),ensure_ascii=False,indent=2))
        return 0
    if a.enrich_details is not None:
        if not 1<=a.enrich_details<=500:parser.error('MAX debe estar entre 1 y 500')
        from src.guia_detail import enrich_sources
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(enrich_sources(conn,a.enrich_details),ensure_ascii=False,indent=2))
        return 0
    if a.enrich_event:
        if ':' not in a.enrich_event: parser.error('Formato de --enrich-event: SOURCE:ID')
        source,record_id=a.enrich_event.split(':',1)
        if not source or not record_id: parser.error('Formato de --enrich-event: SOURCE:ID')
        from src.guia_detail import enrich_sources
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn)
            print(json.dumps(enrich_sources(conn,1,sources=(source,),record_ids=(record_id,),refresh=True),ensure_ascii=False,indent=2))
        return 0
    if a.download_local_media is not None:
        if not 1<=a.download_local_media<=500:parser.error('MAX debe estar entre 1 y 500')
        from src.media import download_local_previews
        with closing(catalog.connect(DB)) as conn:
            catalog.initialize(conn)
            print(json.dumps(download_local_previews(conn,ROOT/'data'/'media',a.download_local_media,a.media_source),ensure_ascii=False,indent=2))
        return 0
    if a.sync_opendata:
        from src.opendata_bcn import sync as sync_opendata
        with closing(catalog.connect(DB)) as conn:
            result=sync_opendata(conn,file=Path(a.opendata_file) if a.opendata_file else None)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='completed' else 2
    if a.sync_web:
        from src.web_agendas import sync
        with closing(catalog.connect(DB)) as conn:
            print(json.dumps(sync(conn,a.sync_web),ensure_ascii=False,indent=2))
        return 0
    if a.sync:
        if not a.endpoint and a.sync!='guiabcn':
            parser.error('--endpoint HTTPS es obligatorio con --sync; no hay endpoint implícito ni scraping')
        from src.sync import GUIABCN_ENDPOINT, IncrementalSync
        with closing(catalog.connect(DB)) as conn:
            result=IncrementalSync(conn).run(a.sync,a.endpoint or GUIABCN_ENDPOINT,page_size=a.page_size,max_rows=a.max_rows,timeout_seconds=a.sync_timeout,organizers_endpoint=a.organizers_endpoint,since_days=a.since_days)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['status']=='completed' else 2
    warm_listing()
    server=ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(DB))
    print(f'Brollant local: http://127.0.0.1:{a.port}')
    print('Solo en este Mac. Las imágenes locales pueden estar pendientes de derechos. Ctrl+C para detenerlo.')
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':raise SystemExit(main() or 0)
