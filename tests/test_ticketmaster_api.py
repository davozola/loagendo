"""Conector de la Discovery API de Ticketmaster (sin red: respuestas simuladas)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src import ticketmaster_api as tm


def event(i, day, time='20:00:00', status='onsale', city='Barcelona', **extra):
    return {'name': f'Concierto {i}', 'type': 'event', 'id': f'Z{i}', 'url': f'https://www.ticketmaster.es/event/{i}', 'locale': 'es-es',
            'images': [{'ratio': '16_9', 'url': f'https://s1.ticketm.net/{i}_16_9_1024.jpg', 'width': 1024, 'height': 576, 'fallback': False},
                       {'ratio': '3_2', 'url': f'https://s1.ticketm.net/{i}_3_2.jpg', 'width': 640, 'height': 427, 'fallback': False},
                       {'ratio': '16_9', 'url': f'https://s1.ticketm.net/{i}_16_9_small.jpg', 'width': 205, 'height': 115, 'fallback': False}],
            'sales': {'public': {'startDateTime': '2026-06-01T08:00:00Z', 'endDateTime': '2026-12-01T19:00:00Z'}},
            'dates': {'start': {'localDate': day, 'localTime': time, 'timeTBA': False, 'noSpecificTime': False}, 'timezone': 'Europe/Madrid', 'status': {'code': status}},
            'classifications': [{'primary': True, 'segment': {'name': 'Music'}, 'genre': {'name': 'Rock'}, 'subGenre': {'name': 'Pop'}, 'family': False}],
            'promoter': {'id': '1', 'name': 'Live Nation'}, 'info': 'Apertura de puertas 19:00.', 'pleaseNote': 'Prohibido acceder con botellas.',
            'priceRanges': [{'type': 'standard', 'currency': 'EUR', 'min': 35.0, 'max': 60.0}],
            'ageRestrictions': {'legalAgeEnforced': False}, 'accessibility': {'info': 'Zona PMR'},
            '_embedded': {'venues': [{'name': 'Razzmatazz', 'id': 'V1', 'postalCode': '08018', 'city': {'name': city}, 'address': {'line1': 'Carrer dels Almogàvers, 122'},
                                      'location': {'longitude': '2.1913', 'latitude': '41.3977'}}],
                          'attractions': [{'name': 'Banda X', 'id': 'A1', 'url': 'https://www.ticketmaster.es/artist/1'}]}, **extra}


def page(events, total=None, pages=1):
    return {'_embedded': {'events': events}, 'page': {'size': 200, 'totalElements': len(events) if total is None else total, 'totalPages': pages, 'number': 0}}


VENUE = {'slug': 'ticketmaster_es', 'name': 'Ticketmaster España', 'type': 'ticketing'}


class RecordTests(unittest.TestCase):
    def test_event_keeps_time_venue_price_genre_and_extras(self):
        record = tm.record_from_event(event(1, '2026-11-02'), VENUE)
        self.assertEqual((record['source'], record['start'], record['time_text'], record['price_text']), ('venue_ticketmaster_es', '2026-11-02', '20:00', '35–60 EUR'))
        self.assertEqual(record['venues'][0]['name'], 'Razzmatazz'); self.assertEqual(record['venues'][0]['coords'], (41.3977, 2.1913))
        self.assertEqual(record['raw']['loagendo']['category'], 'Música y vida nocturna')
        self.assertIn('Apertura de puertas', record['raw']['loagendo']['description'])
        self.assertEqual(record['raw']['loagendo']['ticketmaster']['classification'], {'segment': 'Music', 'genre': 'Rock', 'subGenre': 'Pop'})
        self.assertEqual(record['raw']['loagendo']['performers'], ['Banda X'])
        self.assertEqual(record['organizers'], ['Live Nation'])
        self.assertEqual(record['raw']['api_event']['id'], 'Z1')
        self.assertIn('TICKETMASTER_DISCOVERY_API', record['alerts'])

    def test_spanish_names_still_classify(self):
        e = event(7, '2026-11-02'); e['classifications'] = [{'primary': True, 'segment': {'id': 'KZFzniwnSyZfZ7v7nJ', 'name': 'Música'}, 'genre': {'id': 'KnvZfZ7vAeA', 'name': 'Rock'}}]
        self.assertEqual(tm.record_from_event(e, VENUE)['raw']['loagendo']['category'], 'Música y vida nocturna')
        self.assertTrue(tm.NOT_AN_EVENT.search('Upgrade MEET&GREET Synthony')); self.assertFalse(tm.NOT_AN_EVENT.search('SYNTHONY'))

    def test_time_to_be_announced_has_no_time_and_cancelled_is_excluded(self):
        tba = event(2, '2026-11-03'); tba['dates']['start']['timeTBA'] = True
        self.assertEqual(tm.record_from_event(tba, VENUE)['time_text'], '')
        self.assertEqual(tm.record_from_event(event(3, '2026-11-04', status='cancelled'), VENUE)['eligibility'], 'exclude')
        self.assertIsNone(tm.record_from_event(event(4, '2026-11-05', city='Badalona'), VENUE))

    def test_images_one_per_ratio_largest_first(self):
        self.assertEqual(tm.images_of(event(5, '2026-11-02')), ['https://s1.ticketm.net/5_16_9_1024.jpg', 'https://s1.ticketm.net/5_3_2.jpg'])


class SlotTests(unittest.TestCase):
    def test_time_slot_products_become_one_record(self):
        slots = [event(100, f'2026-11-{d:02d}', time=t) for d in range(1, 8) for t in ('10:00:00', '12:00:00')]
        for s in slots: s['name'] = 'Museo X'
        out = tm.collapse_slots(slots + [event(1, '2026-11-02')])
        self.assertEqual(len(out), 2)
        museum = next(e for e in out if e['name'] == 'Museo X')
        record = tm.record_from_event(museum, VENUE)
        self.assertEqual((record['start'], record['end'], record['time_text']), ('2026-11-01', '2026-11-07', ''))
        self.assertIn('TIME_SLOT_PRODUCT_COLLAPSED', record['alerts'])


class FetchTests(unittest.TestCase):
    def test_window_with_more_than_1000_events_is_split(self):
        calls = []
        def getter(params):
            calls.append((params['startDateTime'], params['endDateTime'], params['page']))
            self.assertEqual((params['city'], params['countryCode']), ('Barcelona', 'ES'))
            if len(calls) == 1: return page([], total=1500, pages=8)
            return page([event(len(calls), '2026-11-02')])
        events, n = tm.fetch_window('k', dt.date(2026, 10, 18), dt.date(2026, 12, 18), getter, pause=0)
        self.assertEqual((len(events), n), (2, 3))
        self.assertEqual(calls[1][1], calls[2][0])  # dos mitades contiguas

    def test_pages_until_the_last(self):
        pages = [page([event(1, '2026-11-02')], total=3, pages=3), page([event(2, '2026-11-03')], total=3, pages=3), page([event(3, '2026-11-04')], total=3, pages=3)]
        events, n = tm.fetch_window('k', dt.date(2026, 10, 18), dt.date(2026, 12, 18), lambda p: pages[p['page']], pause=0)
        self.assertEqual((len(events), n), (3, 3))


class SyncTests(unittest.TestCase):
    def test_sync_without_key_is_skipped(self):
        self.assertEqual(tm.sync(None, key='')['status'], 'skipped')

    def test_sync_stores_events_and_deletes_past_ones(self):
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility) VALUES('venue_ticketmaster_es','old','Pasado','2026-10-01','2026-10-01','{}','review')")
            conn.execute("INSERT INTO source_venues(source,id,seq,venue,address,lat,lon) VALUES('venue_ticketmaster_es','old',0,'Sala','',NULL,NULL)")
            conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility) VALUES('opendatabcn_agenda','old','Otra fuente','2026-10-01','2026-10-01','{}','review')")
            conn.commit()
            result = tm.sync(conn, key='secret', getter=lambda p: page([event(1, '2026-11-02'), event(2, '2026-11-03')]), today=dt.date(2026, 10, 18), pause=0)
            self.assertEqual((result['status'], result['records'], result['past_events_deleted']), ('completed', 2, 1))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_ticketmaster_es'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_venues WHERE source='venue_ticketmaster_es' AND id='old'").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_records WHERE source='opendatabcn_agenda'").fetchone()[0], 1)  # solo Ticketmaster
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media_assets WHERE source='venue_ticketmaster_es'").fetchone()[0], 4)
            conn.close()

    def test_key_never_reaches_the_database(self):
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            def boom(params): raise RuntimeError('fallo con ' + params['apikey'])
            result = tm.sync(conn, key='secret-key', getter=boom, today=dt.date(2026, 10, 18), pause=0)
            self.assertEqual(result['status'], 'failed'); self.assertNotIn('secret-key', result['error'])
            self.assertNotIn('secret-key', conn.execute("SELECT error FROM sync_runs ORDER BY id DESC").fetchone()[0])
            conn.close()


if __name__ == '__main__': unittest.main()
