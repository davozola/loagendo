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
            calls.append(dict(params))
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
        self.assertEqual([c['offset'] for c in calls], [0, 1])
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
