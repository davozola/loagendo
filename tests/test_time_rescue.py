"""Rescate de horas (nivel 1, 23-10-2026)."""
import datetime as dt
import unittest

from mvp import catalog
from src import known_times, time_rescue
from src.pipeline import connect
from src.sync import initialize as init_sync

TODAY = dt.date(2026, 10, 23)
URL = 'https://jamboreejazz.com/evento/benzie/'


def page(body, title='Benziê - Jamboree'):
    return f'<html><head><title>{title}</title></head><body><h1>Benziê</h1>{body}</body></html>'


class RescueTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES('venue_jamboree','b1','Benziê','2026-10-24','2026-10-24','single','include','',?,'','{}')", (URL,))

    def _alert(self):
        from src.time_health import initialize
        initialize(self.conn)
        self.conn.execute("INSERT INTO source_alerts(source,kind,detail,first_seen_at,last_seen_at) VALUES('venue_jamboree','TIME_COVERAGE_DROP','x','2026-10-23','2026-10-23')")

    def test_sin_alerta_no_hace_nada(self):
        self.assertEqual(time_rescue.run(self.conn, {'ia': False}, fetcher=lambda u, t: (200, u, page('<p>23:00h</p>')), today=TODAY)['checked'], 0)

    def test_con_alerta_rescata_de_la_pagina_y_queda_trazado(self):
        self._alert()
        res = time_rescue.run(self.conn, {'ia': False}, fetcher=lambda u, t: (200, u, page('<p>Dissabte 24 oct.</p><p>23:00h</p>')), today=TODAY)
        self.assertEqual(res['rescued'], 1)
        occ = []; known_times.fill(occ, known_times.for_record(self.conn, 'venue_jamboree', 'b1'), '2026-10-24', '2026-10-24')
        self.assertEqual((occ[0]['time'], occ[0]['evidence_field']), ('23:00', 'rescate'))
        self.assertEqual(self.conn.execute("SELECT method,url FROM time_rescue").fetchone(), ('rescate_pagina', URL))

    def test_ia_solo_vale_con_cita_literal(self):
        self._alert()
        body = page('<p>Portes 22:30</p><p>Concert a les 23:00h</p>')
        good = lambda *a, **k: {'content': [{'type': 'tool_use', 'name': 'hora', 'input': {'hora': '23:00', 'cita_hora': 'Concert a les 23:00h'}}]}
        bad = lambda *a, **k: {'content': [{'type': 'tool_use', 'name': 'hora', 'input': {'hora': '21:00', 'cita_hora': 'Concert a les 21:00h'}}]}
        r = time_rescue.rescue_one('venue_jamboree', 'b1', 'Benziê', '2026-10-24', URL, lambda u, t: (200, u, body), 5, key='k', requester=bad)
        self.assertNotEqual(r['status'], 'ok')  # la cita no está en la página
        r = time_rescue.rescue_one('venue_jamboree', 'b1', 'Benziê', '2026-10-24', URL, lambda u, t: (200, u, body), 5, key='k', requester=good)
        self.assertEqual((r['status'], r['method'], r['time']), ('ok', 'rescate_ia', '23:00'))


if __name__ == '__main__':
    unittest.main()
