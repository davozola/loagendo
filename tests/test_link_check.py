import datetime as dt
import unittest

from src import link_check
from src.pipeline import connect


class LinkCheckTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); link_check.initialize(self.conn)

    def test_classify(self):
        self.assertEqual(link_check.classify(200), 'ok')
        self.assertEqual(link_check.classify(301), 'ok')
        self.assertEqual(link_check.classify(404), 'broken')
        self.assertEqual(link_check.classify(500), 'broken')
        self.assertEqual(link_check.classify(403), 'unverified')
        self.assertEqual(link_check.classify(429), 'unverified')
        self.assertEqual(link_check.classify(None, 'timeout'), 'unreachable')

    def test_http_error_hides_at_once_and_comes_back_when_fixed(self):
        url = 'https://graf.cat/events/event/x/'
        link_check.refresh(self.conn, [url], lambda u: (500, None))
        self.assertEqual(link_check.broken(self.conn, [url]), {url})
        # Rotos se recomprueban a las 6 horas; antes, no.
        self.assertEqual(link_check.refresh(self.conn, [url], lambda u: (200, None))['checked'], 0)
        self.conn.execute("UPDATE link_checks SET checked_at=?", ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=7)).isoformat(),))
        link_check.refresh(self.conn, [url], lambda u: (200, None))
        self.assertEqual(link_check.broken(self.conn, [url]), set())
        # Nada se borra: el historial guarda los dos estados.
        self.assertEqual([r[0] for r in self.conn.execute('SELECT state FROM link_check_log ORDER BY id')], ['broken', 'ok'])

    def test_no_response_needs_two_strikes_and_bot_blocks_are_published(self):
        a, b = 'https://caido.test/a', 'https://social.test/b'
        link_check.refresh(self.conn, [a, b], lambda u: (None, 'timeout') if u == a else (403, None))
        self.assertEqual(link_check.broken(self.conn), set())
        self.conn.execute("UPDATE link_checks SET checked_at=?", ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat(),))
        link_check.refresh(self.conn, [a, b], lambda u: (None, 'timeout') if u == a else (403, None))
        self.assertEqual(link_check.broken(self.conn), {a})

    def test_network_down_does_not_hide_anything(self):
        urls = [f'https://web{i}.test/' for i in range(20)]
        for _ in range(3):
            report = link_check.refresh(self.conn, urls, lambda u: (None, 'Tunnel connection failed'))
            self.conn.execute("UPDATE link_checks SET checked_at='2000-01-01T00:00:00+00:00'")
        self.assertTrue(report['network_down'])
        self.assertEqual(link_check.broken(self.conn), set())

    def test_budget_and_summary_by_source_and_host(self):
        urls = [f'https://graf.cat/e/{i}' for i in range(5)]
        report = link_check.refresh(self.conn, urls, lambda u: (500, None), max_checks=3)
        self.assertEqual(report['checked'], 3)
        link_check.record_usage(self.conn, [(u, 'opendatabcn_agenda', str(i), 'En GRAF') for i, u in enumerate(urls)])
        summary = link_check.summary(self.conn)
        self.assertEqual(summary['hidden_links'], 3)
        self.assertEqual(summary['by_source']['opendatabcn_agenda'], {'links': 5, 'broken': 3, 'unverified': 0, 'unchecked': 2})
        self.assertEqual(summary['by_host']['graf.cat']['http_status'], {'500': 3})


if __name__ == '__main__':
    unittest.main()


class LinkLabelTests(unittest.TestCase):
    def test_other_source_page_is_named_short(self):
        from mvp.catalog import readable_links, short_source
        self.assertEqual(short_source('GRAF · agenda de creació contemporània'), 'GRAF')
        links = readable_links([{'url': 'https://graf.cat/events/event/x/', 'label': 'Enlace · GRAF'},
                                {'url': 'https://guia.barcelona.cat/ca/detall/x.html', 'label': 'Enlace · GuiaBCN'}])
        self.assertEqual([l['label'] for l in links], ['En GRAF', 'Ficha en GuiaBCN'])


if __name__ == "__main__":
    unittest.main()
