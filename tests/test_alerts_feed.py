"""Novedades para las alertas por correo (data/alertas/nuevos.json, 24-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.publish_static import write_alerts_feed

TODAY = dt.date(2026, 10, 24)


def ev(key, start='2026-10-30', end='2026-10-30', **kw):
    return {'key': key, 'title': key, 'start': start, 'end': end, 'time': '19:00', 'time_label': '19:00', 'venue_names': ['Sala'],
            'district': 'Gràcia', 'public_category': 'musica', 'channels': ['familia'], 'is_free': True, 'lineup': ['A'], **kw}


class AlertsFeedTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.out = Path(self.temp.name) / 'dist'; self.out.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def feed(self):
        return json.loads((self.out / 'data' / 'alertas' / 'nuevos.json').read_text(encoding='utf-8'))['items']

    def test_first_run_is_a_baseline_and_later_arrivals_are_new(self):
        self.assertEqual(write_alerts_feed(self.out, [ev('a:1'), ev('a:2')], TODAY, '2026-10-24T06:00:00+00:00'), 0)
        n = write_alerts_feed(self.out, [ev('a:1'), ev('a:2'), ev('a:3'), ev('a:4', start='2026-10-01', end='2026-10-20')], TODAY, '2026-10-24T09:00:00+00:00')
        self.assertEqual(n, 1)   # a:4 ya terminó
        item = self.feed()[0]
        self.assertEqual((item['k'], item['fs'], item['pc'], item['ch'], item['fr'], item['d']), ('a:3', '2026-10-24T09:00:00+00:00', 'musica', ['familia'], 1, 'Gràcia'))
        # La fecha de primera aparición no cambia en la siguiente publicación.
        write_alerts_feed(self.out, [ev('a:1'), ev('a:3')], TODAY, '2026-10-24T12:00:00+00:00')
        self.assertEqual(self.feed()[0]['fs'], '2026-10-24T09:00:00+00:00')

    def test_old_arrivals_leave_the_feed_after_two_weeks(self):
        write_alerts_feed(self.out, [], TODAY, '2026-10-01T06:00:00+00:00')
        write_alerts_feed(self.out, [ev('a:9', end='2026-12-31')], TODAY, '2026-10-02T06:00:00+00:00')
        write_alerts_feed(self.out, [ev('a:9', end='2026-12-31')], TODAY, '2026-10-24T06:00:00+00:00')
        self.assertEqual(self.feed(), [])


if __name__ == '__main__':
    unittest.main()
