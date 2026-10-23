"""Última hora conocida (23-10-2026): si una pasada pierde la hora, se muestra la que ya teníamos."""
import json
import sqlite3
import unittest

from mvp import catalog
from src import known_times
from src.pipeline import connect
from src.sync import _upsert_record, initialize as init_sync


def _record(time_text, rid='a1', start='2026-10-30'):
    return {'source': 'venue_prueba', 'id': rid, 'title': 'Concierto', 'start': start, 'end': start, 'time_text': time_text,
            'price_text': '', 'kind': 'single', 'eligibility': 'include', 'start_timestamp': '', 'frequency': '',
            'raw': {'loagendo': {}}, 'venues': [{'name': 'Sala', 'address': '', 'coords': None}], 'organizers': ['Sala'],
            'url': 'https://sala.example/concierto', 'alerts': [], 'evidence_level': 'x'}


class KnownTimesTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:')
        init_sync(self.conn); catalog.initialize(self.conn)
        self.run = self.conn.execute("INSERT INTO sync_runs(source,started_at,status,cursor) VALUES('venue_prueba','2026-10-20','running','0')").lastrowid

    def test_la_hora_perdida_en_una_pasada_se_conserva_marcada(self):
        _upsert_record(self.conn, self.run, _record('21:00'))
        _upsert_record(self.conn, self.run, _record(''))  # la sala quita la hora del listado
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM candidate_occurrences WHERE id='a1' AND local_time<>''").fetchone()[0], 0)
        occ = []
        filled = known_times.fill(occ, known_times.for_record(self.conn, 'venue_prueba', 'a1'), '2026-10-30', '2026-10-30')
        self.assertEqual(filled, ['2026-10-30'])
        self.assertEqual((occ[0]['time'], occ[0]['evidence_field']), ('21:00', 'ultima_hora_conocida'))

    def test_una_hora_nueva_manda_sobre_la_conocida(self):
        _upsert_record(self.conn, self.run, _record('21:00'))
        occ = [{'date': '2026-10-30', 'time': '22:00', 'evidence_field': 'listing_time', 'verified': False}]
        self.assertEqual(known_times.fill(occ, known_times.for_record(self.conn, 'venue_prueba', 'a1'), '2026-10-30', '2026-10-30'), [])
        self.assertEqual([o['time'] for o in occ], ['22:00'])

    def test_fuera_de_las_fechas_actuales_no_se_aplica(self):
        _upsert_record(self.conn, self.run, _record('21:00'))
        occ = []
        self.assertEqual(known_times.fill(occ, known_times.for_record(self.conn, 'venue_prueba', 'a1'), '2026-11-02', '2026-11-02'), [])

    def test_historial_anterior_se_recupera_sin_red(self):
        _upsert_record(self.conn, self.run, _record('20:30', rid='b2'))
        self.conn.execute('DELETE FROM known_times')  # como una base de antes de esta tabla
        res = known_times.backfill(self.conn)
        self.assertGreaterEqual(res['times_stored'], 1)
        self.assertEqual(known_times.for_record(self.conn, 'venue_prueba', 'b2')['2026-10-30'][0]['time'], '20:30')


if __name__ == '__main__':
    unittest.main()
