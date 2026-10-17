import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src.pipeline import connect
from src.venue_feeds import census, jsonld_events, record_from_jsonld, sync_enabled, sync_venue

VENUE = {'slug': 'demo_hall', 'name': 'Demo Hall', 'type': 'music', 'url': 'https://demo-hall.test/agenda', 'enabled': True}
PAGE = '''<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"MusicEvent","name":"Strawberry Guy","startDate":"2026-11-05T21:00:00+01:00","endDate":"2026-11-05T23:00:00+01:00",
  "url":"/es/conciertos/strawberry-guy","image":{"@type":"ImageObject","url":"https://img.demo-hall.test/sg.jpg"},
  "location":{"@type":"MusicVenue","name":"Demo Hall · Sala 2","address":{"@type":"PostalAddress","streetAddress":"Carrer Nou de la Rambla, 113","postalCode":"08004","addressLocality":"Barcelona"},"geo":{"@type":"GeoCoordinates","latitude":41.374,"longitude":2.169}},
  "offers":{"@type":"Offer","price":"22","priceCurrency":"EUR","url":"https://tickets.test/sg"},"performer":[{"@type":"MusicGroup","name":"Strawberry Guy"}],
  "description":"<p>Pop de dormitori des de Liverpool.</p>"},
 {"@type":"MusicEvent","name":"Cancelada","startDate":"2026-11-06T21:00:00+01:00","eventStatus":"https://schema.org/EventCancelled","location":{"@type":"Place","name":"Demo Hall"}},
 {"@type":"Organization","name":"Demo Hall"}
]}</script></head><body><a href="https://demo-hall.test/agenda.ics">iCal</a></body></html>'''


class VenueFeedTests(unittest.TestCase):
    def test_jsonld_events_are_found_inside_graph_and_normalised(self):
        events = jsonld_events(PAGE)
        self.assertEqual([e['name'] for e in events], ['Strawberry Guy', 'Cancelada'])
        record = record_from_jsonld(VENUE, events[0], 'https://demo-hall.test/agenda')
        self.assertEqual((record['source'], record['start'], record['end'], record['time_text'], record['kind']), ('venue_demo_hall', '2026-11-05', '2026-11-05', '21:00', 'single'))
        self.assertEqual(record['url'], 'https://demo-hall.test/es/conciertos/strawberry-guy')
        self.assertEqual(record['venues'][0], {'name': 'Demo Hall · Sala 2', 'address': 'Carrer Nou de la Rambla, 113, 08004, Barcelona', 'coords': (41.374, 2.169)})
        self.assertEqual((record['price_text'], record['raw']['loagendo']['tickets_url']), ('22 EUR', 'https://tickets.test/sg'))
        self.assertEqual(record['raw']['loagendo']['description'], 'Pop de dormitori des de Liverpool.')
        self.assertEqual(record['raw']['image'], 'https://img.demo-hall.test/sg.jpg')
        cancelled = record_from_jsonld(VENUE, events[1], 'https://demo-hall.test/agenda')
        self.assertEqual(cancelled['eligibility'], 'exclude'); self.assertIn('EVENT_STATUS_EVENTCANCELLED', cancelled['alerts'])

    def test_census_reports_what_each_venue_publishes(self):
        pages = {'https://demo-hall.test/agenda': (200, 'https://demo-hall.test/agenda', PAGE), 'https://old.test/': (404, 'https://old.test/', ''), 'https://plain.test/': (200, 'https://plain.test/', '<html><body>Programa</body></html>')}
        venues = [VENUE, {'slug': 'old', 'name': 'Old', 'url': 'https://old.test/'}, {'slug': 'plain', 'name': 'Plain', 'url': 'https://plain.test/'}]
        with tempfile.TemporaryDirectory() as folder:
            out = census(venues, fetcher=lambda url, timeout: pages[url], out_path=Path(folder) / 'census.json')
            self.assertEqual(out['by_verdict'], {'jsonld': 1, 'unreachable': 1, 'html_only': 1})
            first = out['results'][0]
            self.assertEqual((first['jsonld_events'], first['ical'], first['rss']), (2, ['https://demo-hall.test/agenda.ics'], ['https://demo-hall.test/feed.xml']))
            self.assertTrue((Path(folder) / 'census.json').exists())

    def test_census_discovers_the_programme_page_from_the_homepage_and_ignores_fake_ical_links(self):
        home = '<a href="/es/blog/musical-vertical">Blog musical</a><a href="/es/programacion/">Programación</a><a href="/es/contacto">Contacto</a>'
        pages = {'https://venue.test/es/agenda': (404, 'https://venue.test/es/agenda', ''), 'https://venue.test/': (200, 'https://venue.test/', home), 'https://venue.test/es/programacion/': (200, 'https://venue.test/es/programacion/', PAGE), 'https://venue.test/es/blog/musical-vertical': (200, 'https://venue.test/es/blog/musical-vertical', '<a href="/radical.html">x</a>')}
        calls = []
        def fetcher(url, timeout): calls.append(url); return pages.get(url, (404, url, ''))
        with tempfile.TemporaryDirectory() as folder:
            out = census([{'slug': 'v', 'name': 'V', 'type': 'music', 'url': 'https://venue.test/es/agenda'}], fetcher=fetcher, out_path=Path(folder) / 'c.json')
        entry = out['results'][0]
        self.assertEqual((entry['verdict'], entry['jsonld_events'], entry['suggested_url']), ('jsonld', 2, 'https://venue.test/es/programacion/'))
        self.assertEqual(calls[:3], ['https://venue.test/es/agenda', 'https://venue.test/', 'https://venue.test/es/programacion/'])
        from src.venue_feeds import feed_links
        self.assertEqual(feed_links('<a href="/musical-vertical.css">x</a><a href="/agenda.ics">y</a><a href="/ical/">z</a>', 'https://v.test/'), {'ical': ['https://v.test/agenda.ics', 'https://v.test/ical/'], 'rss': []})

    def test_sync_is_idempotent_and_feeds_public_listing_with_time_and_category(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            fetcher = lambda url, timeout: (200, url, PAGE)
            first = sync_venue(conn, VENUE, fetcher=fetcher); second = sync_enabled(conn, [VENUE], fetcher=fetcher)
            self.assertEqual((first['status'], first['rows_received'], first['rows_mutated'], second['rows_mutated']), ('completed', 2, 2, 0))
            self.assertEqual(conn.execute("SELECT local_time,evidence_field FROM candidate_occurrences WHERE source='venue_demo_hall'").fetchall(), [('21:00', 'schema.org/startDate')])
            self.assertEqual(conn.execute("SELECT rights_status FROM media_assets WHERE source='venue_demo_hall'").fetchone()[0], 'authorized')  # venue_* policy in the registry
            catalog.invalidate_cache()
            out = catalog.query_events(conn, day='2026-11-05', public=True)
            self.assertEqual(len(out['items']), 1)
            item = out['items'][0]
            self.assertEqual((item['time'], item['public_category'], item['category'], item['source_label']), ('21:00', 'Conciertos', 'Música y vida nocturna', 'Demo Hall · agenda del recinto'))
            self.assertEqual(catalog.query_events(conn, day='2026-11-06', public=True)['total'], 0)  # cancelled stays archived but hidden
            detail = catalog.event_detail(conn, 'venue_demo_hall', item['id'])
            self.assertEqual(detail['description'], 'Pop de dormitori des de Liverpool.')
            self.assertIn('https://tickets.test/sg', [l['url'] for l in detail['links']])
            catalog.invalidate_cache(); conn.close()


if __name__ == '__main__':
    unittest.main()


class TicketingTests(unittest.TestCase):
    def test_marketplace_events_classify_by_schema_type_and_stay_in_barcelona(self):
        shop = {'slug': 'shop', 'name': 'Shop', 'type': 'ticketing', 'url': 'https://shop.test/barcelona'}
        theatre = {'@type': 'TheaterEvent', 'name': 'Obra', 'startDate': '2026-11-20T20:30:00', 'url': 'https://shop.test/e/obra', 'location': {'@type': 'Place', 'name': 'Teatre X', 'address': {'@type': 'PostalAddress', 'addressLocality': 'Barcelona'}}, 'offers': {'@type': 'Offer', 'lowPrice': '18', 'highPrice': '32', 'priceCurrency': 'EUR', 'url': 'https://shop.test/buy/obra'}}
        away = {'@type': 'MusicEvent', 'name': 'Fuera', 'startDate': '2026-11-21T21:00:00', 'location': {'@type': 'Place', 'name': 'Sala', 'address': {'@type': 'PostalAddress', 'addressLocality': 'Girona'}}}
        record = record_from_jsonld(shop, theatre, 'https://shop.test/barcelona')
        self.assertEqual((record['raw']['loagendo']['category'], record['price_text'], record['raw']['loagendo']['source_label']), ('Artes escénicas', '18–32 EUR', 'Shop · ticketera'))
        self.assertIn('THIRD_PARTY_TICKETING_LISTING', record['alerts'])
        self.assertIsNone(record_from_jsonld(shop, away, 'https://shop.test/barcelona'))

    def test_robots_disallow_is_respected(self):
        from src import venue_feeds
        parser = venue_feeds.robotparser.RobotFileParser(); parser.parse(['User-agent: *', 'Disallow: /private/'])
        venue_feeds._ROBOTS['https://r.test'] = parser
        self.assertTrue(venue_feeds.robots_allows('https://r.test/events'))
        self.assertFalse(venue_feeds.robots_allows('https://r.test/private/list'))

    def test_fetch_reports_a_stalled_host_instead_of_raising(self):
        from src import venue_feeds
        original = venue_feeds.urlopen
        def stalled(*args, **kwargs): raise TimeoutError('The read operation timed out')
        venue_feeds.urlopen = stalled
        try: self.assertEqual(venue_feeds.fetch('https://slow.test/agenda', timeout=1)[:2], (0, 'https://slow.test/agenda'))
        finally: venue_feeds.urlopen = original


class DetailPageTests(unittest.TestCase):
    LISTING = '<html><body><a href="/es/conciertos/strawberry-guy">Strawberry Guy</a><a href="/es/conciertos/otro-show">Otro</a><a href="/es/contacto">Contacto</a><a href="/es/conciertos/poster.jpg">img</a></body></html>'
    def detail(self, name, date):
        return f'<script type="application/ld+json">{{"@type":"MusicEvent","name":"{name}","startDate":"{date}T21:00:00+01:00","url":"https://venue.test/es/conciertos/{name.lower()}","location":{{"@type":"Place","name":"Demo Hall","address":{{"addressLocality":"Barcelona"}}}}}}</script>'

    def test_event_links_rank_event_pages_and_skip_assets(self):
        from src.venue_feeds import event_links
        self.assertEqual(event_links(self.LISTING, 'https://venue.test/es/agenda'), ['https://venue.test/es/conciertos/otro-show', 'https://venue.test/es/conciertos/strawberry-guy'])

    def test_sync_follows_detail_pages_when_the_listing_has_no_jsonld(self):
        pages = {'https://venue.test/es/agenda': (200, 'https://venue.test/es/agenda', self.LISTING),
                 'https://venue.test/es/conciertos/strawberry-guy': (200, 'https://venue.test/es/conciertos/strawberry-guy', self.detail('Strawberry', '2026-11-05')),
                 'https://venue.test/es/conciertos/otro-show': (200, 'https://venue.test/es/conciertos/otro-show', self.detail('Otro', '2026-11-06'))}
        calls = []
        def fetcher(url, timeout): calls.append(url); return pages.get(url, (404, url, ''))
        venue = {'slug': 'v', 'name': 'V', 'type': 'music', 'url': 'https://venue.test/es/agenda', 'enabled': True}
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            result = sync_venue(conn, venue, fetcher=fetcher)
            self.assertEqual((result['status'], result['rows_received'], result['pages']), ('completed', 2, 3))
            self.assertEqual(sorted(calls), sorted(pages))
            limited = sync_venue(conn, {**venue, 'max_pages': 1}, fetcher=fetcher)
            self.assertEqual((limited['rows_received'], limited['pages']), (1, 2))
            off = sync_venue(conn, {**venue, 'follow_links': False}, fetcher=fetcher)
            self.assertEqual(off['status'], 'failed')
            catalog.invalidate_cache(); conn.close()

    def test_census_samples_detail_pages_and_reports_jsonld_detail(self):
        pages = {'https://venue.test/es/agenda': (200, 'https://venue.test/es/agenda', self.LISTING),
                 'https://venue.test/es/conciertos/strawberry-guy': (200, 'https://venue.test/es/conciertos/strawberry-guy', self.detail('Strawberry', '2026-11-05')),
                 'https://venue.test/es/conciertos/otro-show': (200, 'https://venue.test/es/conciertos/otro-show', '<html>no data</html>')}
        fetcher = lambda url, timeout: pages.get(url, (404, url, ''))
        with tempfile.TemporaryDirectory() as folder:
            out = census([{'slug': 'v', 'name': 'V', 'type': 'music', 'url': 'https://venue.test/es/agenda'}], fetcher=fetcher, out_path=Path(folder) / 'c.json')
        entry = out['results'][0]
        self.assertEqual((entry['verdict'], entry['jsonld_detail_events'], len(entry['detail_sampled'])), ('jsonld_detail', 1, 2))

    def test_calendar_html_pages_are_not_ical_feeds(self):
        from src.venue_feeds import feed_links
        page = '<a href="/es/calendar/">cal</a><link href="/css/calendar/calendar.css"><a href="webcal://calendar.google.com/x/public/basic.ics">ics</a><a href="/ical/">i</a>'
        self.assertEqual(feed_links(page, 'https://v.test/')['ical'], ['https://v.test/ical/', 'webcal://calendar.google.com/x/public/basic.ics'])


class DirectoryTitleTests(unittest.TestCase):
    def test_directory_titles_drop_the_hall_and_ids_survive_retitling(self):
        from src.venue_feeds import clean_title, migrate_record_ids, record_id
        self.assertEqual(clean_title('The Lemon Twigs @ Paral·lel 62'), 'The Lemon Twigs')
        self.assertEqual(clean_title('Deep Purple at Sant Jordi Club', 'Sant Jordi Club'), 'Deep Purple')
        self.assertEqual(clean_title('Tom @ Jerry'), 'Tom')
        self.assertEqual(record_id('songkick', 'https://sk.test/c/1', '2026-10-15', 'A'), record_id('songkick', 'https://sk.test/c/1', '2026-10-15', 'A @ Hall'))
        venue = {'slug': 'songkick', 'name': 'Songkick', 'type': 'aggregator', 'url': 'https://sk.test/'}
        node = {'@type': 'MusicEvent', 'name': 'The Lemon Twigs @ Paral·lel 62', 'startDate': '2026-10-15T19:00:00', 'url': 'https://sk.test/c/1?utm=x', 'location': {'@type': 'Place', 'name': 'Paral·lel 62', 'address': {'addressLocality': 'Barcelona'}}}
        rec = record_from_jsonld(venue, node, 'https://sk.test/')
        self.assertEqual((rec['title'], rec['id']), ('The Lemon Twigs', record_id('songkick', 'https://sk.test/c/1', '2026-10-15', '')))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('venue_songkick', 'oldid', 'The Lemon Twigs @ Paral·lel 62', '2026-10-15', '2026-10-15', 'single', 'review', 'x', 'https://sk.test/c/1?utm=x', 'h', '{}'))
            conn.execute("INSERT INTO candidate_occurrences VALUES ('venue_songkick','oldid','2026-10-15','19:00','single','schema.org/startDate')"); conn.commit()
            out = migrate_record_ids(conn, [venue])
            self.assertEqual(out, {'renamed': 1, 'excluded_duplicates': 0, 'retitled': 1})
            self.assertEqual(conn.execute("SELECT id,title FROM source_records").fetchone(), (rec['id'], 'The Lemon Twigs'))
            self.assertEqual(conn.execute("SELECT id FROM candidate_occurrences").fetchone()[0], rec['id'])
            self.assertEqual(migrate_record_ids(conn, [venue]), {'renamed': 0, 'excluded_duplicates': 0, 'retitled': 0})
            conn.close()


class WpFullCalendarTests(unittest.TestCase):
    FEED = '[{"title":"El Micro Obert","color":"#a8d144","start":"2026-10-15T20:30:00","end":"2026-10-15T20:30:00","url":"https:\\/\\/www.helio.test\\/el-micro-obert\\/","post_id":6951},{"title":"Minova","start":"2026-10-16T20:30:00","end":"2026-10-16T20:30:00","url":"https:\\/\\/www.helio.test\\/minova\\/","post_id":6964}]'
    PAGE = '<html><head><meta property="og:image" content="https://www.helio.test/wp-content/uploads/minova.jpg" /><meta property="og:description" content="Concert de Minova a la sala." /></head><body></body></html>'

    def test_feed_items_become_records_with_the_page_image(self):
        calls = []
        def fetcher(url, timeout):
            calls.append(url)
            if url.startswith('https://www.helio.test/wp-admin/admin-ajax.php?action=WP_FullCalendar&start='): return 200, url, self.FEED
            if url == 'https://www.helio.test/minova/': return 200, url, self.PAGE
            return 200, url, '<html></html>'
        venue = {'slug': 'helio', 'name': 'Heliogàbal', 'type': 'music', 'url': 'https://www.helio.test/', 'enabled': True,
                 'feed': {'kind': 'wp_fullcalendar', 'url': 'https://www.helio.test/wp-admin/admin-ajax.php?action=WP_FullCalendar'}}
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            result = sync_venue(conn, venue, fetcher=fetcher)
            self.assertEqual((result['status'], result['rows_received'], result['pages']), ('completed', 2, 3))
            rows = {r[0]: r for r in conn.execute("SELECT title,start_date,source_url FROM source_records WHERE source='venue_helio'")}
            self.assertEqual(rows['Minova'][1:], ('2026-10-16', 'https://www.helio.test/minova/'))
            raw = json.loads(conn.execute("SELECT raw_json FROM source_records WHERE source='venue_helio' AND title='Minova'").fetchone()[0])
            self.assertEqual(raw['image'], 'https://www.helio.test/wp-content/uploads/minova.jpg')
            self.assertIn('20:30', json.dumps(raw))
            self.assertEqual(conn.execute("SELECT count(*) FROM media_assets WHERE source='venue_helio'").fetchone()[0], 1)
            catalog.invalidate_cache(); conn.close()


class OnlineEventTests(unittest.TestCase):
    def test_online_detection(self):
        from src.venue_feeds import is_online_event
        self.assertTrue(is_online_event({'eventAttendanceMode': 'https://schema.org/OnlineEventAttendanceMode'}))
        self.assertTrue(is_online_event({'location': {'@type': 'VirtualLocation', 'url': 'https://zoom.us/x'}}))
        self.assertFalse(is_online_event({'eventAttendanceMode': 'https://schema.org/MixedEventAttendanceMode', 'location': [{'@type': 'Place'}, {'@type': 'VirtualLocation'}]}))
        self.assertFalse(is_online_event({'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode', 'location': {'@type': 'Place'}}))
        self.assertFalse(is_online_event(None))

    def test_archived_online_events_are_excluded_with_a_reason_and_never_deleted(self):
        import json, tempfile
        from pathlib import Path
        from src.pipeline import connect
        from mvp import catalog
        from src.venue_feeds import exclude_online_events, ONLINE_REASON
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 'o.sqlite3'); catalog.initialize(conn)
            rows = [('on', 'https://schema.org/OnlineEventAttendanceMode'), ('off', 'https://schema.org/OfflineEventAttendanceMode'), ('kept', 'https://schema.org/OnlineEventAttendanceMode')]
            for rid, mode in rows:
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('venue_eventbrite', rid, rid, '2026-11-01', '2026-11-01', 'single', 'review', 'x', '', 'h', json.dumps({'item': {'eventAttendanceMode': mode}})))
            conn.execute("INSERT INTO publication_decisions(source,id,status,decided_at) VALUES ('venue_eventbrite','kept','published','2026-10-17')")
            conn.commit()
            self.assertEqual(exclude_online_events(conn), {'newly_excluded': 1, 'flagged': 1})
            self.assertEqual(exclude_online_events(conn), {'newly_excluded': 0, 'flagged': 0})  # idempotente
            states = dict(conn.execute("SELECT id,eligibility FROM source_records"))
            self.assertEqual(states, {'on': 'exclude', 'off': 'review', 'kept': 'review'})
            self.assertEqual(conn.execute("SELECT issue FROM review_flags WHERE id='on'").fetchone()[0], ONLINE_REASON)
