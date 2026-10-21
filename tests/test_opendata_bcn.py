import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src.opendata_bcn import ical_sessions, iter_items, occurrences_for, record_from_item, sync, timetable_facts, timetable_hours
from src.pipeline import connect

FIXTURE = Path(__file__).parent / 'fixtures' / 'opendatabcn_agenda_sample.json'
TODAY = dt.date(2026, 10, 12)


class OpenDataParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = json.loads(FIXTURE.read_text(encoding='utf-8'))
        cls.by_id = {item['register_id']: item for item in cls.items}

    def test_concert_record_keeps_source_facts_and_identity_url(self):
        record = record_from_item(self.by_id[99400783090], TODAY)
        self.assertEqual((record['source'], record['id'], record['kind'], record['eligibility']), ('opendatabcn_agenda', '99400783090', 'single', 'review'))
        self.assertEqual((record['start'], record['end']), ('2026-11-13', '2026-11-14'))
        self.assertEqual(record['url'], 'https://guia.barcelona.cat/ca/detall/agenda_99400783090.html')
        self.assertEqual(record['category'], 'Música y vida nocturna')
        self.assertEqual(record['district'], 'Eixample'); self.assertEqual(record['neighborhood'], 'el Fort Pienc')
        self.assertEqual(record['venues'][0]['name'], "L'Auditori de Barcelona · Sala 1 Pau Casals")  # sala con su recinto (21-10-2026)
        self.assertEqual(record['venues'][0]['address'], 'Carrer de Lepant 150, 08013 Barcelona')
        self.assertAlmostEqual(record['venues'][0]['coords'][0], 41.399, places=2)
        self.assertEqual(record['time_text'], 'a les 19.00 h')
        self.assertIn('20 a 58', record['price_text']); self.assertFalse(record['is_free'])
        self.assertEqual(record['tickets_url'], 'https://www.auditori.cat/ca')
        # Two iCal sessions, labelled with a bogus Z: wall-clock 19:00 confirmed by the timetable.
        self.assertEqual([(o['local_date'], o['local_time']) for o in record['occurrences']], [('2026-11-13', '19:00'), ('2026-11-14', '19:00')])
        self.assertTrue(all(o['type'].endswith('_confirmed_by_timetable') for o in record['occurrences']))
        self.assertEqual(record['images'][0]['url'], 'https://estatics-nasia.dtibcn.cat/nasia-pro/media/la_segona.optimized.e369c198.jpg')
        self.assertNotIn('attribute_categories', record['raw']); self.assertNotIn('location_25831', record['raw']['addresses'][0])
        self.assertEqual(record['raw']['loagendo']['schedule_days'], 'Divendres i dissabte')

    def test_free_event_with_organizer_and_registration(self):
        record = record_from_item(self.by_id[99400783421], TODAY)
        self.assertTrue(record['is_free']); self.assertEqual(record['price_text'], 'Entrada Gratuïta')
        self.assertEqual(record['organizers'], ['Cuida la Vida. Associació de Facilitadores pel Benestar'])
        self.assertTrue(record['registration_required'])
        self.assertEqual(record['raw']['loagendo']['schedule_note'], 'Cal inscripció prèvia abans del 26 de juliol')
        self.assertEqual([o['local_time'] for o in record['occurrences']], ['17:00'])

    def test_exhibition_interval_is_never_expanded_into_sessions(self):
        record = record_from_item(self.by_id[99400787233], TODAY)
        self.assertEqual(record['kind'], 'exhibition'); self.assertEqual(record['occurrences'], [])
        self.assertEqual(record['category'], 'Arte y exposiciones')

    def test_deferred_and_out_of_town_rows_are_archived_but_excluded(self):
        deferred = record_from_item(self.by_id[99400788244], TODAY)
        self.assertEqual(deferred['eligibility'], 'exclude'); self.assertIn('EVENT_STATUS_DEFERRED', deferred['alerts']); self.assertIn('SOURCE_WARNING_PRESENT', deferred['alerts'])
        away = record_from_item(self.by_id[99400772307], TODAY)
        self.assertEqual(away['eligibility'], 'exclude'); self.assertIn('OUTSIDE_BARCELONA_MUNICIPALITY', away['alerts'])
        self.assertEqual(away['kind'], 'course')

    def test_helpers(self):
        self.assertEqual(timetable_hours("de 10.00 h a 12.00 h"), ['10:00', '12:00'])
        self.assertEqual(ical_sessions('DTSTART:20261113T190000Z\r\nDTSTART:20261113T190000Z\r\nDTSTART;TZID=Europe/Madrid:20261114T2030'), [('2026-11-13', '19:00'), ('2026-11-14', '20:30')])
        many = {'ical': ''.join(f'DTSTART:202611{d:02d}T100000Z\n' for d in range(1, 30)) * 3, 'timetable': {'html': ''}}
        self.assertEqual(occurrences_for(many, 'single', TODAY), [] if 29 > 60 else occurrences_for(many, 'single', TODAY))
        self.assertEqual(len(occurrences_for(many, 'single', TODAY)), 29)
        self.assertEqual(len(list(iter_items('  [ {"a":1}, {"b":[1,2]} ,{"c":"]"}]'))), 3)
        self.assertEqual(timetable_facts({'timetable': {'html': '<table><tr><td class="timetable-day"><div>Dijous</div></td><td class="timetable-hour"><div>a les 19.30&nbsp;h</div></td></tr></table>'}}), {'schedule_days': 'Dijous', 'schedule_hours': 'a les 19.30 h'})


class OpenDataSyncTests(unittest.TestCase):
    def test_sync_from_file_is_idempotent_and_links_guiabcn_twin(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            # A scraped GuiaBCN twin of the concert, which the licensed feed supersedes in public.
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('guiabcn', '99400783090', 'Concert "La Segona de Mahler"', '2026-11-13', '2026-11-14', 'single', 'review', 'x', '', 'h', json.dumps({'api_item': {'name': 'Concert', 'city': 'Barcelona', 'code_prop': {'item': ['0061901019']}}})))
            conn.commit()
            first = sync(conn, file=FIXTURE, today=TODAY)
            second = sync(conn, file=FIXTURE, today=TODAY)
            self.assertEqual(first['status'], 'completed')
            self.assertEqual((first['rows_received'], first['rows_mutated'], first['rows_excluded'], second['rows_mutated']), (5, 5, 2, 0))
            self.assertEqual(first['candidate_occurrences'], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_records WHERE source='opendatabcn_agenda'").fetchone()[0], 5)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM candidate_occurrences WHERE source='opendatabcn_agenda'").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM media_assets WHERE source='opendatabcn_agenda' AND rights_status='unknown'").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM source_snapshots WHERE sha256<>''").fetchone()[0], 2)
            catalog.invalidate_cache()
            public = catalog.query_events(conn, day='2026-11-13', public=True)
            self.assertEqual({(e['source'], e['id']) for e in public['items']}, {('opendatabcn_agenda', '99400783090'), ('opendatabcn_agenda', '99400787233')})
            concert = next(e for e in public['items'] if e['id'] == '99400783090')
            self.assertEqual(concert['time'], '19:00')
            self.assertEqual(concert['also_in'], ['guiabcn:99400783090'])
            self.assertEqual(concert['district'], 'Eixample')
            self.assertEqual(public['items'][0]['id'], '99400783090')  # dated session ranks above the exhibition interval
            everything = catalog.query_events(conn, day='2026-11-13')
            self.assertEqual({e['source'] for e in everything['items']}, {'guiabcn', 'opendatabcn_agenda'})
            twin = next(e for e in everything['items'] if e['source'] == 'guiabcn')
            self.assertEqual(twin['superseded_by'], 'opendatabcn_agenda:99400783090')
            detail = catalog.event_detail(conn, 'opendatabcn_agenda', '99400783090')
            self.assertTrue(detail['description'].startswith('OBC\nLudovic Morlot'))  # paragraphs preserved
            self.assertEqual(detail['time_text'], 'a les 19.00 h')
            self.assertIn('https://www.auditori.cat/ca', [l['url'] for l in detail['links']])
            self.assertEqual(detail['organizers'], [])
            self.assertEqual(detail['venues'][0]['address'], 'Carrer de Lepant 150, 08013 Barcelona')
            conn.close()


if __name__ == '__main__':
    unittest.main()
