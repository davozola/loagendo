"""Alerta cuando una fuente que daba horas deja de darlas (23-10-2026)."""
import datetime as dt
import unittest

from mvp import catalog
from src import time_health
from src.pipeline import connect
from src.sync import initialize as init_sync

TODAY = dt.date(2026, 10, 23)


class TimeHealthTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        self.sent = []

    def _acts(self, timed, day, total=20):
        self.conn.execute("DELETE FROM candidate_occurrences"); self.conn.execute("DELETE FROM source_records")
        for n in range(total):
            self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES('venue_x',?,?,?,?,'single','include','','','','{}')",
                              (str(n), 'Acto %d' % n, day, day))
            if n < timed: self.conn.execute("INSERT INTO candidate_occurrences VALUES('venue_x',?,?,'21:00','t','listing')", (str(n), day))

    def _day(self, offset, timed):
        today = TODAY + dt.timedelta(days=offset)
        self._acts(timed, (today + dt.timedelta(days=2)).isoformat())
        return time_health.check(self.conn, today=today, notify=lambda t, m: self.sent.append(t) or True)

    def test_caida_abre_alerta_avisa_y_se_cierra_al_recuperarse(self):
        for d in range(4): self.assertEqual(self._day(d, 18)['opened'], [])   # habitual: 90 % con hora
        res = self._day(4, 2)                                                  # de golpe, 10 %
        self.assertEqual([a['source'] for a in res['opened']], ['venue_x'])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self._day(5, 2)['still_open'], ['venue_x']); self.assertEqual(len(self.sent), 1)  # sin repetir el aviso
        self.assertEqual(self._day(6, 18)['resolved'], ['venue_x'])
        self.assertEqual(time_health.open_alerts(self.conn), [])

    def test_fuente_que_nunca_da_horas_no_alerta(self):
        for d in range(5): self.assertEqual(self._day(d, 1)['opened'], [])


if __name__ == '__main__':
    unittest.main()
