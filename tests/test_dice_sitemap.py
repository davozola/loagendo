"""DICE desde su sitemap (sin red: páginas simuladas con la forma real del 18-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import dice_sitemap as ds

URL_BCN = 'https://dice.fm/event/pyr58w-no-te-va-gustar-29th-oct-razzmatazz-barcelona-tickets'
URL_OLD = 'https://dice.fm/event/aaa111-concierto-viejo-1st-oct-apolo-barcelona-tickets'
URL_LON = 'https://dice.fm/event/wwpd8g-nightmare-of-you-30th-jan-the-garage-london-london-tickets'
LONG = 'No Te Va Gustar ha ido consolidando su presencia en Europa a lo largo de los años. ' * 8


def page(url, start='2026-10-29T18:30:00+01:00', name='No Te Va Gustar'):
    node = {'@context': 'https://schema.org', '@type': 'MusicEvent', 'url': url, 'name': name, 'startDate': start, 'endDate': start[:11] + '23:30:00+01:00',
            'eventStatus': 'https://schema.org/EventScheduled', 'doorTime': start,
            'location': {'@type': 'Place', 'name': 'Razzmatazz', 'address': {'@type': 'PostalAddress', 'streetAddress': 'Carrer dels Almogàvers, 122, 08018 Barcelona, Spain', 'addressLocality': 'Barcelona', 'addressCountry': 'ES'},
                         'geo': {'latitude': 41.3977199, 'longitude': 2.1911055}},
            'image': ['https://dice-media.imgix.net/a.jpg?rect=0', 'https://dice-media.imgix.net/a.jpg?rect=1'], 'description': LONG,
            'offers': {'@type': 'AggregateOffer', 'priceCurrency': 'EUR', 'lowPrice': '40.60', 'highPrice': '40.60'},
            'performer': [{'@type': 'PerformingGroup', 'name': 'No Te Va Gustar', 'url': 'https://dice.fm/artist/x'}],
            'organizer': {'@type': 'Organization', 'name': 'CHARCO MUSICA', 'url': 'https://dice.fm/promoters/y'}}
    return '<html><script type="application/ld+json">' + json.dumps(node) + '</script></html>'


SITES = {ds.SITEMAP_INDEX: '<sitemapindex><sitemap><loc>https://dice.fm/sitemaps/sitemap2.xml</loc></sitemap></sitemapindex>',
         'https://dice.fm/sitemaps/sitemap2.xml': f'<urlset><url><loc>{URL_BCN}</loc></url><url><loc>{URL_OLD}</loc></url><url><loc>{URL_LON}</loc></url></urlset>',
         URL_BCN: page(URL_BCN), URL_OLD: page(URL_OLD, '2026-10-01T20:00:00+02:00', 'Concierto viejo')}
VENUE = {'slug': 'dice', 'name': 'DICE', 'type': 'ticketing'}


class DiceTests(unittest.TestCase):
    def test_record_keeps_doors_time_price_and_only_an_excerpt(self):
        record = ds.record_from_page(page(URL_BCN), URL_BCN, VENUE)
        self.assertEqual((record['source'], record['start'], record['time_text']), ('venue_dice', '2026-10-29', '18:30'))
        self.assertEqual(record['price_text'], '40.60 EUR')
        self.assertLessEqual(len(record['raw']['loagendo']['description']), ds.EXCERPT_CHARS + 1)
        self.assertTrue(record['raw']['loagendo']['dice']['description_truncated'])
        self.assertEqual(record['organizers'], ['CHARCO MUSICA'])
        self.assertEqual(record['raw']['loagendo']['tickets_url'], URL_BCN)

    def test_sync_reads_only_barcelona_pages_and_deletes_past_events(self):
        from src.pipeline import connect
        calls = []
        def fetcher(url, timeout):
            calls.append(url); return (200, url, SITES[url]) if url in SITES else (404, url, '')
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            result = ds.sync(conn, fetcher=fetcher, today=dt.date(2026, 10, 18), pause=0)
            self.assertEqual((result['status'], result['barcelona_urls'], result['records'], result['past_events_deleted']), ('completed', 2, 2, 1))
            self.assertNotIn(URL_LON, calls)
            self.assertEqual([r[0] for r in conn.execute("SELECT title FROM source_records WHERE source='venue_dice'")], ['No Te Va Gustar'])
            # Segunda pasada: nada nuevo ni caducado → no se vuelve a pedir ninguna ficha.
            calls.clear(); again = ds.sync(conn, fetcher=fetcher, today=dt.date(2026, 10, 18), pause=0)
            self.assertEqual(again['pages_fetched'], 0); self.assertNotIn(URL_BCN, calls)
            conn.close()


if __name__ == '__main__': unittest.main()
