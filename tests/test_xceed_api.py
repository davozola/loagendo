"""Conector de Xceed (respuestas simuladas con la forma real del 18-10-2026)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src import xceed_api as xc

CONFIG = xc.load_config()
VENUE = {'slug': 'xceed', 'name': 'Xceed', 'type': 'ticketing'}


def event(i, slug='razzmatazz', name='Fury Festival pres. Halloween Warehouse Indoor Rave', start=1793548800, end=1793570400):
    return {'id': f'id-{i}', 'legacyId': 221980 + i, 'name': name, 'slug': f'evento-{i}', 'startingTime': start, 'endingTime': end,
            'coverUrl': f'https://images.xceed.me/events/banners/{i}.jpg', 'venueIsSecret': False,
            'venue': {'name': slug.title(), 'slug': slug, 'address': 'Calle Pamplona, 88', 'coordinates': {'latitude': 41.397729, 'longitude': 2.191081},
                      'city': {'slug': 'barcelona', 'name': 'Barcelona'}},
            'lineup': [{'name': 'Revenja', 'isGeneric': False}, {'name': 'Miss K8', 'isGeneric': False}],
            'musicGenres': [{'name': 'Hard Techno'}]}


ADMISSIONS = {'ticket': [
    {'name': 'General Entrance - 7th Release', 'status': 'on_sale', 'price': {'amount': 33, 'currency': 'EUR'}, 'commissions': {'transactionFee': 2.25}, 'salesStatus': {'isSoldOut': False, 'isSalesClosed': False}},
    {'name': 'VIP', 'status': 'on_sale', 'price': {'amount': 43, 'currency': 'EUR'}, 'commissions': {}, 'salesStatus': {'isSoldOut': False, 'isSalesClosed': False}},
    {'name': '1st Release', 'status': 'sold_out', 'price': {'amount': 20, 'currency': 'EUR'}, 'salesStatus': {'isSoldOut': True}}]}
DETAIL = {'about': 'Tras el rotundo éxito de la primera edición en Razzmatazz, FURY Festival anuncia su regreso.', 'isFestival': False,
          'doorsOpening': 1793548800, 'agePolicy': '+18', 'company': {'name': 'Fury Events'}}


class FilterTests(unittest.TestCase):
    def test_strict_venue_list_and_title_patterns(self):
        self.assertTrue(xc.allowed(event(1, 'jamboree-jazz-club', 'Chico Pinheiro Quartet'), CONFIG)[0])
        self.assertFalse(xc.allowed(event(2, 'sauvage-swinger-club-1', 'Salsa y Bachata'), CONFIG)[0])
        self.assertFalse(xc.allowed(event(3, 'recinto-nuevo', 'Concierto'), CONFIG)[0])  # nuevo: fuera hasta revisarlo
        self.assertFalse(xc.allowed(event(4, 'city-hall', 'FREE GUEST LIST at City Hall'), CONFIG)[0])
        secret = event(5); secret['venueIsSecret'] = True
        self.assertFalse(xc.allowed(secret, CONFIG)[0])


class RecordTests(unittest.TestCase):
    def test_record_has_local_time_price_lineup_and_text(self):
        record = xc.record_from_event(event(1), VENUE, DETAIL, ADMISSIONS)
        self.assertEqual((record['source'], record['start'], record['end'], record['time_text']), ('venue_xceed', '2026-11-01', '2026-11-01', '17:00'))
        self.assertEqual(record['price_text'], '33–43 EUR')  # la tanda agotada no cuenta
        self.assertEqual(record['raw']['loagendo']['performers'], ['Revenja', 'Miss K8'])
        self.assertEqual(record['raw']['loagendo']['category'], 'Música y vida nocturna')
        self.assertIn('FURY Festival', record['raw']['loagendo']['description'])
        self.assertEqual(record['url'], 'https://xceed.me/es/barcelona/event/evento-1/221981')
        self.assertEqual(record['raw']['loagendo']['xceed']['genres'], ['Hard Techno'])
        self.assertEqual(record['organizers'], ['Fury Events'])

    def test_without_offers_there_is_no_price(self):
        record = xc.record_from_event(event(2), VENUE)
        self.assertEqual(record['price_text'], ''); self.assertIn('NO_PRICE_TEXT', record['alerts'])


class SyncTests(unittest.TestCase):
    def test_sync_filters_enriches_and_deletes_past(self):
        from src.pipeline import connect
        listing = [event(1), event(2, 'sauvage-swinger-club-1', 'The Ritual'), event(3, 'jamboree-jazz-club', 'Jam Session')]
        def getter(url, params=None):
            if url == xc.EVENTS: return {'success': True, 'data': listing if params['offset'] == 0 else []}
            if url.startswith(xc.EVENTS + '/'): return {'success': True, 'data': DETAIL}
            return {'success': True, 'data': ADMISSIONS}
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility) VALUES('venue_xceed','old','Pasado','2026-10-01','2026-10-01','{}','review')")
            conn.commit()
            result = xc.sync(conn, getter=getter, today=dt.date(2026, 10, 18), pause=0)
            self.assertEqual((result['status'], result['records'], result['past_events_deleted']), ('completed', 2, 1))
            self.assertEqual(result['rejected'], {'recinto no admitido: sauvage-swinger-club-1': 1})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_xceed'").fetchone()[0], 2)
            conn.close()


if __name__ == '__main__': unittest.main()
