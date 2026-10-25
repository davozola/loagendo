import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import media
from src.automation import initialize as init_automation
from src.pipeline import connect
from src.publish_static import credits_html, export, publish, shard_of

TODAY = dt.date(2026, 10, 12)
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8ff9f0f000401007e9ce8e40000000049454e44ae426082')


class StaticExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        (self.root / 'media').mkdir(); (self.root / 'static' / 'vendor').mkdir(parents=True)
        (self.root / 'static' / 'index.html').write_text('<!DOCTYPE html><html lang="es" data-theme="dark"><head><link rel="stylesheet" href="/public.css"></head><body><script defer src="/public.js"></script></body></html>', encoding='utf-8')
        from src.publish_static import STATIC_FILES
        for name in STATIC_FILES: (self.root / 'static' / name).parent.mkdir(parents=True, exist_ok=True); (self.root / 'static' / name).write_text('/* x */', encoding='utf-8')
        self.registry = self.root / 'registry.json'
        self.registry.write_text(json.dumps({'opendatabcn_agenda': {'owner': 'Ajuntament de Barcelona', 'attribution': 'Ajuntament de Barcelona — Agenda cultural (Open Data BCN)', 'license_url': 'https://creativecommons.org/licenses/by/4.0/', 'data_reuse_status': 'cc_by_4_metadata', 'image_reuse_confirmed': True, 'image_reuse_basis': 'decisión editorial de prueba'},
                                            'web_cccb': {'owner': 'CCCB', 'attribution': 'CCCB', 'data_reuse_status': 'unconfirmed_for_bulk_ingestion', 'image_reuse_confirmed': False}}), encoding='utf-8')
        self.conn = connect(self.root / 't.sqlite3'); catalog.initialize(self.conn); init_automation(self.conn)
        rows = [('opendatabcn_agenda', '1', 'Concert al parc', '2026-10-12', '2026-10-12', 'single', 'review', {'name': 'Concert al parc', 'body': '<p>Un concert.</p><p>Segon paràgraf.</p>', 'loagendo': {'price_text': 'Gratuït', 'is_free': True}}),
                ('opendatabcn_agenda', '2', 'Exposició llarga', '2026-09-01', '2027-01-31', 'exhibition', 'review', {'name': 'Exposició llarga', 'loagendo': {}}),
                ('opendatabcn_agenda', '3', 'Fora de Barcelona', '2026-10-13', '2026-10-13', 'single', 'exclude', {'name': 'Fora', 'loagendo': {}}),
                ('web_cccb', '4', 'Debat', '2026-10-14', '2026-10-14', 'single', 'review', {'title': 'Debat', 'loagendo': {}})]
        for source, id, title, start, end, kind, elig, raw in rows:
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, id, title, start, end, kind, elig, 'x', 'https://example.test/' + id, 'h', json.dumps(raw)))
        self.conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', ('opendatabcn_agenda', '1', 0, 'Parc', 'Carrer 1', 41.4, 2.17))
        self.conn.execute("INSERT INTO candidate_occurrences VALUES ('opendatabcn_agenda','1','2026-10-12','19:00','single','ical')")
        self.conn.commit()
        for source, id, url, ok in (('opendatabcn_agenda', '1', 'https://img.test/a.png', True), ('opendatabcn_agenda', '2', 'https://img.test/b.png', True), ('web_cccb', '4', 'https://img.test/c.png', False)):
            media.register(self.conn, source, id, url, alt='Foto ' + id, rights_status='authorized' if ok else 'unknown')
            path = self.root / 'media' / f'{id}.png'; path.write_bytes(PNG)
            self.conn.execute('UPDATE media_assets SET local_path=?,content_type=?,sha256=? WHERE original_url=?', (str(path), 'image/png', 'sha' + id, url))
        self.conn.commit(); catalog.invalidate_cache()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def export(self, **kw):
        return export(self.conn, self.root / 'dist', media_root=self.root / 'media', static_dir=self.root / 'static', today=TODAY, registry_path=self.registry, thumbnailer=None, **kw)

    def test_export_writes_catalogue_days_details_images_and_credits(self):
        report = self.export(site_url='https://loagendo.example')
        dist = self.root / 'dist'
        self.assertEqual(report['counts']['events'], 3)  # the excluded row never leaves the archive
        self.assertEqual(report['counts']['images'], 2)
        self.assertEqual(report['images']['skipped_rights'], 1)
        cat = json.loads((dist / 'data' / 'catalog.json').read_text(encoding='utf-8'))
        keys = {c['s'] + ':' + c['i'] for c in cat['items']}
        self.assertEqual(keys, {'opendatabcn_agenda:1', 'opendatabcn_agenda:2', 'web_cccb:4'})
        concert = next(c for c in cat['items'] if c['i'] == '1')
        self.assertEqual((concert['tm'], concert['fr'], concert['o'], concert['g']), ('19:00', 1, [['2026-10-12', '19:00']], [41.4, 2.17]))
        self.assertNotIn('m', concert)  # images, summaries and links travel in the day files and detail shards
        # La versión 2 del estilo es la portada: misma app, hoja propia encima y solo modo claro;
        # /v2/ (la dirección de prueba) redirige a la portada.
        v2 = (dist / 'index.html').read_text(encoding='utf-8')
        self.assertIn('data-skin="v2"', v2); self.assertIn('data-theme="light"', v2)
        self.assertRegex(v2, r'href="/public\.css\?v=[0-9a-f]+"><link rel="stylesheet" href="/public-v2\.css\?v=[0-9a-f]+">')
        self.assertFalse((dist / 'v2' / 'index.html').exists())
        self.assertIn('/v2/ / 301', (dist / '_redirects').read_text(encoding='utf-8'))
        self.assertTrue((dist / 'fonts' / 'inter-tight-latin-400-normal.woff2').exists())
        self.assertTrue((dist / 'img' / '1.png').is_file()); self.assertFalse((dist / 'img' / '3.png').exists())
        day = json.loads((dist / 'data' / 'day' / '2026-10-12.json').read_text(encoding='utf-8'))
        self.assertEqual([c['i'] for c in day['items']], ['1', '2'])  # dated act ranks above the exhibition
        self.assertEqual(day['items'][0]['m'], [{'u': '/img/1.png', 'alt': 'Foto 1', 'cr': 'Ajuntament de Barcelona — Agenda cultural (Open Data BCN)'}])
        self.assertEqual(day['featured'][0]['i'], '1')
        self.assertTrue((dist / 'data' / 'day' / (TODAY + dt.timedelta(days=183)).isoformat()).with_suffix('.json').exists())
        shard = json.loads((dist / 'data' / 'detail' / (shard_of('opendatabcn_agenda:1') + '.json')).read_text(encoding='utf-8'))
        detail = shard['opendatabcn_agenda:1']
        self.assertEqual(detail['description'], 'Un concert.\nSegon paràgraf.')
        self.assertEqual(detail['media'][0]['credit']['original_url'], 'https://img.test/a.png')
        self.assertEqual(detail['media'][0]['credit']['license_url'], 'https://creativecommons.org/licenses/by/4.0/')
        for hidden in ('raw_sha256', 'verified_fields', 'possible_duplicates', 'status', 'review_note', 'alerts', 'publication_status'):
            self.assertNotIn(hidden, detail)
        index = (dist / 'index.html').read_text(encoding='utf-8')
        self.assertIn('data-static="1"', index); self.assertIn('rel="canonical" href="https://loagendo.example/"', index)
        credits = (dist / 'creditos.html').read_text(encoding='utf-8')
        self.assertIn('Ajuntament de Barcelona', credits); self.assertIn('CC BY 4.0', credits); self.assertNotIn('decisión editorial de prueba', credits)
        privacy = (dist / 'privacidad.html').read_text(encoding='utf-8'); legal = (dist / 'aviso-legal.html').read_text(encoding='utf-8')
        self.assertIn('Numhaus', privacy); self.assertIn('Brevo', privacy); self.assertIn('lang="en"', privacy); self.assertIn('Numhaus', legal)
        self.assertTrue((dist / 'legal.js').exists()); self.assertNotIn('seo-nav', index)
        self.assertRegex(index, r'href="/public\.css\?v=[0-9a-f]{10}"'); self.assertRegex(index, r'src="/public\.js\?v=[0-9a-f]{10}"')
        headers = (dist / '_headers').read_text(encoding='utf-8')
        self.assertIn("script-src 'self' https://autonomoclaro.com https://challenges.cloudflare.com", headers); self.assertIn('frame-src https://www.openstreetmap.org https://challenges.cloudflare.com', headers)
        self.assertIn('Cache-Control: public, max-age=2592000, immutable', headers); self.assertIn('/public.js\n  Cache-Control: public, max-age=0, must-revalidate', headers)
        self.assertIn('Sitemap: https://loagendo.example/sitemap.xml', (dist / 'robots.txt').read_text(encoding='utf-8'))
        # Sitemap por partes (23-10-2026): índice, páginas y fichas, siempre con el dominio completo,
        # con lastmod del día en que cambió la ficha y sin las direcciones ?day= (su canónica es la portada).
        index_xml = (dist / 'sitemap.xml').read_text(encoding='utf-8')
        self.assertIn('<sitemapindex', index_xml); self.assertIn('https://loagendo.example/sitemap-fichas-1.xml', index_xml)
        fichas = (dist / 'sitemap-fichas-1.xml').read_text(encoding='utf-8')
        self.assertIn(f'<loc>https://loagendo.example/e/opendatabcn_agenda/1</loc><lastmod>{TODAY.isoformat()}</lastmod>', fichas)
        self.assertNotIn('?day=', fichas + (dist / 'sitemap-paginas.xml').read_text(encoding='utf-8'))
        self.assertNotIn('<loc>/', fichas)
        # Páginas de entrada (src/landings.py): ficheros .html, en el sitemap y enlazadas desde el pie.
        for name in ('hoy.html', 'fin-de-semana.html', 'con-ninos/fin-de-semana.html', 'dia/2026-10-12.html'):
            self.assertTrue((dist / name).is_file(), name)
        self.assertIn('<loc>https://loagendo.example/con-ninos/fin-de-semana</loc>', (dist / 'sitemap-paginas.xml').read_text(encoding='utf-8'))
        self.assertIn('data-landing=', (dist / 'hoy.html').read_text(encoding='utf-8'))
        # Avisos por correo: apagados por defecto; /alertas/ y /api/ fuera de los buscadores.
        self.assertNotIn('data-alerts', (dist / 'index.html').read_text(encoding='utf-8'))
        self.assertIn('Disallow: /alertas/', (dist / 'robots.txt').read_text(encoding='utf-8'))
        self.assertTrue((dist / 'data' / 'alertas' / 'nuevos.json').is_file())
        self.export(site_url='https://loagendo.example', alerts={'enabled': True, 'turnstile_site_key': '0xPUBLICA'})
        self.assertIn('data-alerts="1" data-turnstile="0xPUBLICA"', (dist / 'con-ninos.html').read_text(encoding='utf-8'))
        state = json.loads((self.root / 'data' / 'sitemap_lastmod.json').read_text(encoding='utf-8'))
        self.assertEqual(state['opendatabcn_agenda:1'][1], TODAY.isoformat())
        meta = json.loads((dist / 'data' / 'meta.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['site_url'], 'https://loagendo.example')   # la canónica de /e/* (functions/e)
        self.assertEqual(meta['sources']['opendatabcn_agenda']['attribution'], 'Ajuntament de Barcelona — Agenda cultural (Open Data BCN)')
        # A thin catalogue is exported but blocked from deployment.
        self.assertEqual(report['status'], 'blocked'); self.assertTrue(any('mínimo' in b for b in report['blockers']))

    def test_broken_links_are_left_out_of_the_public_site_and_come_back(self):
        # 22-10-2026: graf.cat devolvía 500 en sus fichas; la web no debe enlazar una página rota.
        broken = 'https://example.test/1'
        report = self.export(link_fetcher=lambda u: (500, None) if u == broken else (200, None))
        self.assertEqual(report['links']['hidden'], 1)
        dist = self.root / 'dist'
        detail = json.loads((dist / 'data' / 'detail' / (shard_of('opendatabcn_agenda:1') + '.json')).read_text(encoding='utf-8'))['opendatabcn_agenda:1']
        day = json.loads((dist / 'data' / 'day' / '2026-10-12.json').read_text(encoding='utf-8'))
        self.assertEqual((detail['url'], day['items'][0]['u']), ('', ''))
        # El dato sigue en la fuente y el estado queda guardado, con su historial.
        self.assertEqual(self.conn.execute("SELECT source_url FROM source_records WHERE id='1'").fetchone()[0], broken)
        self.assertEqual(self.conn.execute('SELECT state,http_status FROM link_checks WHERE url=?', (broken,)).fetchone(), ('broken', 500))
        self.conn.execute("UPDATE link_checks SET checked_at='2000-01-01T00:00:00+00:00'"); self.conn.commit()
        again = self.export(link_fetcher=lambda u: (200, None))
        self.assertEqual(again['links']['hidden'], 0)
        detail = json.loads((dist / 'data' / 'detail' / (shard_of('opendatabcn_agenda:1') + '.json')).read_text(encoding='utf-8'))['opendatabcn_agenda:1']
        self.assertEqual(detail['url'], broken)
        from src.readiness import report as readiness
        self.assertEqual(readiness(self.conn, today=TODAY)['external_links']['hidden_links'], 0)

    def test_second_export_reuses_images_and_hash_is_stable(self):
        first = self.export(); second = self.export()
        self.assertEqual(first['content_hash'], second['content_hash'])
        self.assertEqual((second['images']['exported'], second['images']['reused']), (0, 2))

    def test_publish_runs_deploy_only_when_gate_passes_and_content_changed(self):
        calls = []
        def runner(command, **kw):
            calls.append(command)
            class R: returncode = 0; stdout = 'Deployment complete! https://abc.loagendo.pages.dev'; stderr = ''
            return R()
        job = {'name': 'publicar-web', 'out_dir': str((self.root / 'dist').relative_to(self.root)), 'deploy_command': 'echo deploy'}
        import src.publish_static as ps
        original_root, original_gate = ps.ROOT, ps.GATE_MIN_EVENTS_14_DAYS
        ps.ROOT = self.root; ps.GATE_MIN_EVENTS_14_DAYS = 1
        try:
            # The static dir and registry defaults point at ROOT, so patch export's inputs via a wrapper.
            original_export = ps.export
            ps.export = lambda conn, out_dir, **kw: original_export(conn, out_dir, media_root=self.root / 'media', static_dir=self.root / 'static', today=TODAY, registry_path=self.registry, thumbnailer=None)
            report = ps.publish(self.conn, job, runner=runner)
            self.assertEqual((report['status'], report['deploy']['status'], calls), ('completed', 'completed', ['echo deploy']))
            self.assertIn('pages.dev', report['deploy']['output_tail'])
            self.conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,finished_at,status,result_json) VALUES('publicar-web','','publish','t','t','completed',?)", (json.dumps(report),)); self.conn.commit()
            again = ps.publish(self.conn, job, runner=runner)
            self.assertEqual((again['deploy']['status'], len(calls)), ('skipped', 1))
            forced = ps.publish(self.conn, {**job, 'force': True}, runner=runner)
            self.assertEqual((forced['deploy']['status'], len(calls)), ('completed', 2))
            ps.GATE_MIN_EVENTS_14_DAYS = 999
            blocked = ps.publish(self.conn, {**job, 'force': True}, runner=runner)
            self.assertEqual((blocked['status'], blocked['deploy'], len(calls)), ('blocked', None, 2))
        finally:
            ps.ROOT, ps.GATE_MIN_EVENTS_14_DAYS, ps.export = original_root, original_gate, original_export

    def test_credits_page_is_minimal_and_trilingual(self):
        # 25-10-2026: Fuentes con lo mínimo que piden las licencias; no se publica el registro de fuentes.
        page = credits_html({'x': {'owner': 'Ticketera secreta', 'attribution': 'A & B'}})
        self.assertNotIn('Ticketera secreta', page); self.assertIn('Open Data BCN', page); self.assertIn('OpenStreetMap', page)
        for lang in ('es', 'ca', 'en'): self.assertIn(f'<section lang="{lang}">', page)


if __name__ == '__main__':
    unittest.main()
