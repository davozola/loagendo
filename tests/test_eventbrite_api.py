import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path


def api_event(start_local='2026-10-30T17:00:00', end_local='2026-10-30T20:00:00', tz='Europe/Madrid', is_free=False, low='10.00', high='10.00', utc=None):
    ev = {'start': {'local': start_local, 'timezone': tz, 'utc': utc}, 'end': {'local': end_local, 'timezone': tz}, 'is_free': is_free, 'status': 'live'}
    if low is not None:
        ev['ticket_availability'] = {'minimum_ticket_price': {'major_value': low, 'currency': 'EUR'}, 'maximum_ticket_price': {'major_value': high, 'currency': 'EUR'}}
    return ev


class FactsTests(unittest.TestCase):
    def test_time_and_single_price(self):
        from src.eventbrite_api import facts_from_event
        f = facts_from_event(api_event(), '2026-10-30')
        self.assertEqual((f['time'], f['time_text'], f['price_text']), ('17:00', '17:00–20:00', '10 €'))

    def test_price_range_free_and_cents(self):
        from src.eventbrite_api import facts_from_event
        self.assertEqual(facts_from_event(api_event(low='12.50', high='30.00'), '2026-10-30')['price_text'], 'Desde 12,50 €')
        self.assertEqual(facts_from_event(api_event(is_free=True, low=None), '2026-10-30')['price_text'], 'Gratis')
        self.assertEqual(facts_from_event(api_event(low=None), '2026-10-30')['price_text'], '')  # sin dato estructurado: nada

    def test_the_api_date_and_time_rule_when_the_listing_differs(self):
        # Desde el 19-10-2026 manda la API: el evento se publica el día y a la hora que ella dice.
        from src.eventbrite_api import facts_from_event
        f = facts_from_event(api_event(start_local='2026-11-06T20:00:00', end_local='2026-11-06T23:00:00'), '2026-10-30')
        self.assertFalse(f['date_matches'])
        self.assertEqual((f['api_start_date'], f['time'], f['time_text']), ('2026-11-06', '20:00', '20:00–23:00'))

    def test_after_midnight_end_is_not_a_same_day_range(self):
        from src.eventbrite_api import facts_from_event
        f = facts_from_event(api_event(start_local='2026-10-31T23:00:00', end_local='2026-11-01T05:00:00'), '2026-10-31')
        self.assertEqual((f['time'], f['time_text']), ('23:00', '23:00'))

    def test_other_timezone_is_converted_to_barcelona(self):
        from src.eventbrite_api import facts_from_event
        f = facts_from_event(api_event(start_local='2026-10-30T16:00:00', tz='Europe/London', utc='2026-10-30T16:00:00Z'), '2026-10-30')
        self.assertEqual(f['time'], '17:00')


    def test_event_id_from_every_url_shape(self):
        from src.eventbrite_api import event_id
        self.assertEqual(event_id('https://www.eventbrite.es/e/taller-tickets-2002113526453'), '2002113526453')
        self.assertEqual(event_id('https://www.eventbrite.com/e/dental-ce-event-oct-17-2026-registration-1999621721397'), '1999621721397')
        self.assertEqual(event_id('https://www.eventbrite.com/e/1986216550169?aff=ebdssbdestsearch'), '1986216550169')
        self.assertEqual(event_id('https://www.eventbrite.es/d/spain--barcelona/events/'), '')


class JobTests(unittest.TestCase):
    def test_job_fills_time_and_price_without_touching_the_imported_record(self):
        from mvp import catalog
        from src.eventbrite_api import enrich_eventbrite
        day = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        with tempfile.TemporaryDirectory() as folder:
            from src.pipeline import connect
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            url = 'https://www.eventbrite.es/e/taller-de-prova-tickets-2002113526453'
            raw = {'item': {'@type': 'Event', 'name': 'Taller de prova', 'startDate': day, 'endDate': day, 'url': url}, 'normalized': {'price_text': '', 'time_text': ''}, 'loagendo': {}}
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('venue_eventbrite', 'e1', 'Taller de prova', day, day, 'single', 'review', 'x', url, 'h', json.dumps(raw)))
            conn.commit()
            before = conn.execute("SELECT raw_json FROM source_records WHERE id='e1'").fetchone()[0]
            calls = []
            def fetcher(eid):
                calls.append(eid); return json.dumps(api_event(start_local=f'{day}T19:30:00', end_local=f'{day}T21:00:00', low='8.00', high='15.00'))
            out = enrich_eventbrite(conn, token='t', fetcher=fetcher)
            self.assertEqual((out['enriched'], out['with_time'], out['with_price']), (1, 1, 1)); self.assertEqual(calls, ['2002113526453'])
            self.assertEqual(conn.execute("SELECT raw_json FROM source_records WHERE id='e1'").fetchone()[0], before)
            detail = catalog.event_detail(conn, 'venue_eventbrite', 'e1')
            self.assertEqual(detail['time'], '19:30'); self.assertEqual(detail['price_text'], 'Desde 8 €')
            self.assertEqual(enrich_eventbrite(conn, token='t', fetcher=fetcher)['attempted'], 0)  # no se repite hasta RECHECK_DAYS

    def test_missing_token_skips_and_denied_token_stops(self):
        import sqlite3
        from src.eventbrite_api import AccessDenied, enrich_eventbrite
        from mvp import catalog
        from src.pipeline import connect
        folder = tempfile.mkdtemp(); conn = connect(Path(folder) / 'u.sqlite3'); catalog.initialize(conn)
        self.assertEqual(enrich_eventbrite(conn, token='')['status'], 'skipped')
        day = (dt.date.today() + dt.timedelta(days=5)).isoformat()
        conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('venue_eventbrite', 'e2', 'x', day, day, 'single', 'review', 'x', 'https://www.eventbrite.es/e/x-tickets-1986216550169', 'h', '{}'))
        def denied(eid): raise AccessDenied('API de Eventbrite: acceso denegado (401)')
        out = enrich_eventbrite(conn, token='t', fetcher=denied)
        self.assertEqual(out['status'], 'failed'); self.assertIn('401', out['error'])


if __name__ == '__main__': unittest.main()
