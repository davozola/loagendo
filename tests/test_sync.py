import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.pipeline import connect
from src.sync import HttpResponse, IncrementalSync


def diba_row(title='Conte', venue='Biblioteca A', extra=None):
    row = {
        'acte_id': 'stable-1', 'titol': title, 'data_inici': '2026-10-20 18:00:00',
        'data_fi': '2026-10-20 19:00:00', 'observacions_horari': '18 h', 'preu': '',
        'descripcio': 'Descripció', 'acte_organitzadors': 'Entitat A', 'acte_url': 'https://example.test/a',
        'tipus': ['Hora del conte'], 'grup_adreca': {'adreca_nom': venue, 'adreca': 'Carrer 1', 'localitzacio': '41.4,2.1'},
        'rel_municipis': {'ine': '08019'},
    }
    row.update(extra or {})
    return row


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp.name) / 'sync.sqlite3')

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def sync(self, responses, **kwargs):
        calls = []
        def transport(url, params, timeout):
            calls.append({'url': url, **params})
            item = responses.pop(0)
            return item
        result = IncrementalSync(self.conn, transport=transport, sleeper=lambda _: None).run(
            'diba_bibliotecas', 'https://api.example.test/events', page_size=1, max_rows=5, **kwargs)
        return result, calls

    def test_pagination_and_three_identical_runs_are_idempotent(self):
        pages = lambda: [HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': []}, {})]
        first, calls = self.sync(pages())
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(first['rows_mutated'], 1)
        self.assertEqual([c['url'].split('/pag-ini/')[1].split('/')[0] for c in calls], ['1', '2'])
        self.assertTrue(all('/camp-rel_municipis/08019/ord-data_inici/desc' in c['url'] for c in calls))
        second, _ = self.sync(pages())
        third, _ = self.sync(pages())
        self.assertEqual((second['rows_mutated'], third['rows_mutated']), (0, 0))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_records').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_record_versions').fetchone()[0], 1)

    def test_update_invalidates_review_preserves_note_and_keeps_version_history(self):
        self.sync([HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': []}, {})])
        self.conn.execute("INSERT INTO editorial_reviews VALUES ('diba_bibliotecas','stable-1','reviewed','nota editorial','2026-10-10T00:00:00+00:00')")
        self.conn.commit()
        # The source also removed its direct URL; removals are recorded as a
        # field invalidation, never as removal of the whole record.
        result, _ = self.sync([HttpResponse(200, {'elements': [diba_row(title='Conte actualizado', venue='Biblioteca B', extra={'acte_url': ''})]}, {}), HttpResponse(200, {'elements': []}, {})])
        self.assertEqual(result['rows_mutated'], 1)
        self.assertEqual(self.conn.execute("SELECT status,note FROM editorial_reviews").fetchone(), ('needs_evidence', 'nota editorial'))
        self.assertGreaterEqual(self.conn.execute('SELECT count(*) FROM editorial_review_invalidations').fetchone()[0], 2)
        self.assertIn('url', [r[0] for r in self.conn.execute('SELECT field_name FROM editorial_review_invalidations')])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_record_versions').fetchone()[0], 2)
        self.assertEqual(self.conn.execute('SELECT venue FROM source_venues').fetchone()[0], 'Biblioteca B')
        # A source reverting its payload is a new, auditable version, not a deletion.
        self.sync([HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': []}, {})])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_record_versions').fetchone()[0], 3)

    def test_retries_429_then_success_and_partial_response_preserves_records(self):
        result, _ = self.sync([HttpResponse(429, None, {}), HttpResponse(500, None, {}), HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': []}, {})], max_retries=2)
        self.assertEqual(result['status'], 'completed')
        failed, _ = self.sync([HttpResponse(500, None, {}), HttpResponse(500, None, {}), HttpResponse(500, None, {})], max_retries=2)
        self.assertEqual(failed['status'], 'partial')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_records').fetchone()[0], 1)

    def test_rejects_non_barcelona_without_treating_it_as_a_removal(self):
        self.sync([HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': []}, {})])
        outside = diba_row(extra={'acte_id': 'outside', 'rel_municipis': {'ine': '99999'}})
        result, _ = self.sync([HttpResponse(200, {'elements': [outside]}, {}), HttpResponse(200, {'elements': []}, {})])
        self.assertEqual(result['rows_rejected'], 1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM source_records').fetchone()[0], 1)

    def test_generalitat_keeps_multi_venue_relations_split_between_pages(self):
        a = {'codi': 'g-1', 'denominaci': 'Concert', 'data_inici': '2026-10-20', 'data_fi': '2026-10-20', 'horari': '19 h', 'espai': 'Sala A', 'adre_a': 'A', 'latitud': '41.4', 'longitud': '2.1', 'municipi': 'agenda:ubicacions/barcelona/barcelones/barcelona'}
        b = dict(a, espai='Sala B', adre_a='B', latitud='41.5')
        responses = [HttpResponse(200, {'localizaciones': [a], 'organizadores': []}, {}), HttpResponse(200, {'localizaciones': [b], 'organizadores': [{'codi': 'g-1', 'nom_organitzador': 'Org'}]}, {}), HttpResponse(200, {'localizaciones': [], 'organizadores': []}, {})]
        def transport(url, params, timeout):
            return responses.pop(0)
        result = IncrementalSync(self.conn, transport=transport, sleeper=lambda _: None).run('generalitat', 'https://api.example.test/g', page_size=1, max_rows=5)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM source_venues WHERE source='generalitat' AND id='g-1'").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT name FROM source_organizers WHERE source='generalitat' AND id='g-1'").fetchone()[0], 'Org')


if __name__ == '__main__':
    unittest.main()


class LiveEndpointShapeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.temp.name) / 'sync.sqlite3')

    def tearDown(self):
        self.conn.close(); self.temp.cleanup()

    def test_generalitat_orders_pages_filters_by_end_date_and_loads_organizers_by_code(self):
        import datetime as dt
        calls = []
        location = {'codi': 'A1', 'denominaci': 'Concert', 'municipi': 'agenda:ubicacions/barcelona/barcelones/barcelona', 'data_inici': '2026-11-01T00:00:00.000', 'data_fi': '2026-11-01T00:00:00.000', 'horari': 'a les 20 h', 'espai': 'Sala', 'adre_a': 'Carrer 1', 'latitud': '41.4', 'longitud': '2.1', 'urlactivitat': 'https://example.test/a1'}
        responses = [HttpResponse(200, [location], {}), HttpResponse(200, [], {}), HttpResponse(200, [{'codi': 'A1', 'nom_organitzador': 'Entitat Z'}], {})]
        def transport(url, params, timeout):
            calls.append((url, dict(params))); return responses.pop(0)
        result = IncrementalSync(self.conn, transport=transport, sleeper=lambda _: None).run('generalitat', 'https://a.test/rhpv-yr4f.json', page_size=1, max_rows=5, organizers_endpoint='https://a.test/2n2k-gg9s.json', since_days=7, today=dt.date(2026, 10, 12))
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(calls[0][1]['$order'], 'codi')
        self.assertIn("data_fi >= '2026-10-05'", calls[0][1]['$where'])
        self.assertEqual(calls[2][0], 'https://a.test/2n2k-gg9s.json'); self.assertEqual(calls[2][1]['$where'], "codi in('A1')")
        self.assertEqual(self.conn.execute("SELECT name FROM source_organizers WHERE source='generalitat' AND id='A1'").fetchone()[0], 'Entitat Z')
        self.assertEqual(self.conn.execute("SELECT local_time FROM candidate_occurrences WHERE source='generalitat'").fetchone()[0], '20:00')

    def test_diputacio_stops_at_archived_pages_without_inferring_removals(self):
        import datetime as dt
        old = diba_row(extra={'acte_id': 'old-1', 'data_inici': '2024-01-01 10:00:00', 'data_fi': '2024-01-01 23:59:59'})
        responses = [HttpResponse(200, {'elements': [diba_row()]}, {}), HttpResponse(200, {'elements': [old]}, {}), HttpResponse(200, {'elements': [diba_row(extra={'acte_id': 'never'})]}, {})]
        def transport(url, params, timeout): return responses.pop(0)
        result = IncrementalSync(self.conn, transport=transport, sleeper=lambda _: None).run('diba_bibliotecas', 'https://do.diba.cat/api/dataset/actesbiblioteques_ca/format/json', page_size=1, max_rows=10, since_days=30, today=dt.date(2026, 10, 12))
        self.assertEqual(result['status'], 'completed'); self.assertEqual(result['pages'], 2)
        self.assertTrue(any(w.startswith('STOPPED_AT_ARCHIVED_ROWS') for w in result['warnings']))
        self.assertEqual(sorted(r[0] for r in self.conn.execute("SELECT id FROM source_records")), ['old-1', 'stable-1'])


class GeneralitatImagesTests(unittest.TestCase):
    def test_images_resolve_against_the_agenda_host_and_register_once(self):
        import json, tempfile
        from pathlib import Path
        from src.sync import generalitat_image_urls, register_generalitat_images
        from src.pipeline import connect
        from mvp import catalog
        raw = {'localizaciones': [{'imatges': '/content/dam/agenda/a/Visibles.jpg,/content/dam/agenda/a/Visibles (2).jpg', 'imgapp': '/content/dam/agenda/a/Visibles.jpg'}]}
        self.assertEqual(generalitat_image_urls(raw), ['https://agenda.cultura.gencat.cat/content/dam/agenda/a/Visibles.jpg', 'https://agenda.cultura.gencat.cat/content/dam/agenda/a/Visibles%20(2).jpg'])
        self.assertEqual(generalitat_image_urls({'localizaciones': [{}]}), [])
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('generalitat', 'g1', 'Visibles', '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', 'h', json.dumps(raw))); conn.commit()
            self.assertEqual(register_generalitat_images(conn), 2); register_generalitat_images(conn)
            self.assertEqual(conn.execute("SELECT COUNT(*), MIN(rights_status) FROM media_assets WHERE source='generalitat'").fetchone(), (2, 'authorized'))
            conn.close()


class TransientDownloadRetryTests(unittest.TestCase):
    def test_requeues_network_failures_but_keeps_404(self):
        import sqlite3, datetime as dt
        from src.media import retry_transient_download_failures
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE media_assets(asset_id INTEGER PRIMARY KEY, source TEXT, id TEXT, original_url TEXT, local_path TEXT, download_failed_at TEXT, download_error TEXT)")
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat(timespec='seconds')
        conn.executemany("INSERT INTO media_assets(source,id,original_url,download_failed_at,download_error) VALUES('generalitat',?,?,?,?)", [
            ('1', 'https://a/1.jpg', old, '<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] ...>'),
            ('2', 'https://a/2.jpg', old, 'HTTP Error 404: Not Found'),
            ('3', 'https://a/3.jpg', old, 'timed out')])
        self.assertEqual(retry_transient_download_failures(conn, older_than_days=1), 2)
        rows = dict(conn.execute("SELECT id, download_failed_at IS NULL FROM media_assets"))
        self.assertEqual(rows, {'1': 1, '2': 0, '3': 1})
