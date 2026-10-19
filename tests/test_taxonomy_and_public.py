import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src.pipeline import connect
from src.sync import _record_guiabcn, reclassify_guiabcn
from src.web_agendas import _iso


def guia_row(id, name, codes, city='Barcelona', begin='20/10/2026', end=None):
    return {'id': id, 'name': name, 'type': 'Agenda', 'begindate': begin, 'enddate': end or begin, 'city': city,
            'institutionname': 'Espai demo', 'address': 'Carrer demo 1', 'gmapx': '41.40', 'gmapy': '2.17',
            'code_prop': {'item': ['0062601', *codes]}, '@attributes': {'href': f'demo_{id}.html'}}


class TaxonomyTests(unittest.TestCase):
    def test_guiabcn_activity_codes_drive_category_and_family_audience(self):
        raw = {'api_item': guia_row('1', 'Concert familiar', ['0061901019', '0061901001'])}
        self.assertEqual(catalog.guiabcn_codes(raw), ['019', '001'])
        self.assertEqual(catalog.category_of(raw, 'guiabcn', 'single'), 'Música y vida nocturna')
        self.assertTrue(catalog.family_audience(raw, 'guiabcn', 'Concert familiar'))
        # A code without a confirmed label falls back to the title heuristic.
        raw = {'api_item': guia_row('2', "Taller 'Dibuix'", ['0061901011'])}
        self.assertEqual(catalog.category_of(raw, 'guiabcn', 'single'), 'Talleres y experiencias')
        self.assertFalse(catalog.family_audience(raw, 'guiabcn', "Taller 'Dibuix'"))

    def test_public_category_labels_generic_family_activities(self):
        self.assertEqual(catalog.public_category('Literatura y palabra', 'diba_bibliotecas', 'Hora del conte'), 'Barrio')
        raw = {'titol': 'Hora del conte', 'tipus': ['Hora del conte']}
        self.assertTrue(catalog.family_audience(raw, 'diba_bibliotecas', 'Hora del conte'))

    def test_exclusion_reasons_are_explicit_and_conservative(self):
        out_of_town = {'api_item': guia_row('3', 'Saló del vehicle', ['0061901010'], city='HOSPITALET LLOBREGAT')}
        self.assertEqual(catalog.guiabcn_exclusion(out_of_town, '2026-10-22', '2026-10-25'), 'OUTSIDE_BARCELONA_MUNICIPALITY')
        unknown_city = {'api_item': guia_row('4', 'Fira', ['0061901010'], city='')}
        self.assertIsNone(catalog.guiabcn_exclusion(unknown_city, '2026-10-22', '2026-10-25'))
        notice = {'api_item': guia_row('5', 'Festes locals a Barcelona 2027', ['0061901030'])}
        self.assertEqual(catalog.guiabcn_exclusion(notice, '2027-01-01', '2027-12-31'), 'CALENDAR_NOTICE_NOT_AN_EVENT')
        # A one-day workshop that only carries the calendar code is an event.
        self.assertIsNone(catalog.guiabcn_exclusion(notice, '2026-12-03', '2026-12-03'))

    def test_guiabcn_connector_flags_without_dropping_rows(self):
        records = _record_guiabcn([guia_row('6', 'Concert', ['0061901019'], city='Cornellà'), guia_row('7', 'Concert', ['0061901019'])])
        self.assertEqual([r['eligibility'] for r in records], ['exclude', 'review'])
        self.assertIn('OUTSIDE_BARCELONA_MUNICIPALITY', records[0]['alerts'])
        self.assertNotIn('OUTSIDE_BARCELONA_MUNICIPALITY', records[1]['alerts'])

    def test_reclassify_backfills_archived_rows_idempotently(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for id, city in (('a', 'Badalona'), ('b', 'Barcelona')):
                raw = {'api_item': guia_row(id, 'Concert', ['0061901019'], city=city)}
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('guiabcn', id, 'Concert', '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', 'h', json.dumps(raw)))
            conn.commit()
            first = reclassify_guiabcn(conn); second = reclassify_guiabcn(conn)
            self.assertEqual((first['newly_excluded'], second['newly_excluded']), (1, 0))
            self.assertEqual(dict(conn.execute("SELECT id,eligibility FROM source_records")), {'a': 'exclude', 'b': 'review'})
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_flags WHERE issue='OUTSIDE_BARCELONA_MUNICIPALITY'").fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM source_records').fetchone()[0], 2)
            conn.close()


class PublicListingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 't.sqlite3'
        self.conn = connect(self.db); catalog.initialize(self.conn)
        rows = [('guiabcn', 'ok', 'Concert', 'review', {'api_item': guia_row('ok', 'Concert', ['0061901019'])}),
                ('guiabcn', 'out', 'Concert', 'exclude', {'api_item': guia_row('out', 'Concert', ['0061901019'], city='Badalona')}),
                ('diba_turismo', 'svc', 'Tasta el vi', 'exclude', {'titol': 'Tasta el vi'}),
                ('guiabcn', 'kids', 'Contacontes', 'review', {'api_item': guia_row('kids', 'Contacontes', ['0061901001'])})]
        for source, id, title, eligibility, raw in rows:
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, id, title, '2026-10-20', '2026-10-20', 'single', eligibility, 'x', '', 'h', json.dumps(raw)))
        self.conn.execute("INSERT INTO editorial_reviews VALUES ('guiabcn','kids','excluded','duplicado','2026-10-12T00:00:00+00:00')")
        self.conn.commit()
        catalog.invalidate_cache()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def test_public_flag_hides_source_and_editorial_exclusions_but_admin_sees_all(self):
        everything = catalog.query_events(self.conn, day='2026-10-20')
        public = catalog.query_events(self.conn, day='2026-10-20', public=True)
        self.assertEqual((everything['total'], public['total']), (4, 1))
        self.assertEqual(public['items'][0]['id'], 'ok')
        self.assertEqual(public['items'][0]['public_category'], 'musica')

    def test_familia_filter_uses_audience_not_category(self):
        self.conn.execute("DELETE FROM editorial_reviews"); self.conn.commit(); catalog.invalidate_cache()
        out = catalog.query_events(self.conn, day='2026-10-20', public_category='Familia', public=True)
        self.assertEqual([e['id'] for e in out['items']], ['kids'])
        self.assertIn('familia', out['items'][0]['channels'])
        self.assertTrue(out['items'][0]['family_audience'])
        self.assertEqual([e['id'] for e in catalog.query_events(self.conn, day='2026-10-20', channel='familia', public=True)['items']], ['kids'])

    def test_listing_cache_refreshes_after_a_commit_and_never_leaks_request_state(self):
        first = catalog.query_events(self.conn, day='2026-10-20', featured=True)
        self.assertIn('featured_score', first['items'][0])
        again = catalog.query_events(self.conn, day='2026-10-20')
        self.assertNotIn('featured_score', again['items'][0])
        self.conn.execute("UPDATE source_records SET title='Concert renombrat' WHERE id='ok'"); self.conn.commit()
        stale = catalog.query_events(self.conn, day='2026-10-20', public=True)
        self.assertEqual(stale['items'][0]['title'], 'Concert')  # served from the debounced cache
        catalog._LISTING_CACHE['built_at'] -= catalog.REBUILD_MIN_INTERVAL_SECONDS + 1
        scheduled = catalog.query_events(self.conn, day='2026-10-20', public=True)  # still stale: refresh runs in the background
        self.assertEqual(scheduled['items'][0]['title'], 'Concert')
        import time
        for _ in range(200):
            if not catalog._REBUILD_STATE['running'] and catalog._LISTING_CACHE['events'][0]['title'] != 'Concert': break
            time.sleep(0.02)
        refreshed = catalog.query_events(self.conn, day='2026-10-20', public=True)
        self.assertEqual(refreshed['items'][0]['title'], 'Concert renombrat')

    def test_stats_report_derived_counts_without_fixed_dates(self):
        stats = catalog.stats(self.conn)
        self.assertEqual((stats['excluded_by_source'], stats['family_audience']), (2, 1))
        self.assertEqual((stats['source_date_start'], stats['source_date_end']), ('2026-10-20', '2026-10-20'))


class WebDateTests(unittest.TestCase):
    def test_compact_calendar_dates_parse_on_every_python(self):
        self.assertEqual(_iso('20261012T180000Z'), '2026-10-12')
        self.assertEqual(_iso('20261012T1800'), '2026-10-12')
        self.assertEqual(_iso('20261012'), '2026-10-12')
        self.assertEqual(_iso('2026-10-12T18:00:00+02:00'), '2026-10-12')
        self.assertEqual(_iso('garbage'), 'garbage')


if __name__ == '__main__':
    unittest.main()


class FreeLabelTests(unittest.TestCase):
    def test_a_negative_source_flag_is_not_free(self):
        self.assertFalse(catalog.is_free('', 'No')); self.assertFalse(catalog.is_free('De 20 a 58 €', 'No'))
        self.assertTrue(catalog.is_free('', 'Sí')); self.assertTrue(catalog.is_free('Gratuït', '')); self.assertTrue(catalog.is_free('Entrada lliure', ''))
        self.assertFalse(catalog.is_free('', ''))


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.conn = connect(Path(self.temp.name) / 't.sqlite3'); catalog.initialize(self.conn)
        rows = [('a', 'Concert Z', '2026-11-20', '2026-11-20', 'single'), ('b', 'Concert A', '2026-10-15', '2026-10-15', 'single'),
                ('c', 'Exposició', '2026-09-01', '2027-03-01', 'exhibition'), ('d', 'Cicle', '2026-10-01', '2026-12-31', 'program'), ('e', 'Fuera', '2027-02-01', '2027-02-01', 'single')]
        for id, title, start, end, kind in rows:
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('guiabcn', id, title, start, end, kind, 'review', 'x', '', 'h', json.dumps({'api_item': guia_row(id, title, ['0061901019'])})))
        self.conn.execute("INSERT INTO candidate_occurrences VALUES ('guiabcn','d','2026-10-14','20:00','x','f')")
        self.conn.commit(); catalog.invalidate_cache()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def test_window_orders_dated_acts_first_and_caps_at_six_months(self):
        out = catalog.query_events(self.conn, date_from='2026-10-12', date_to='2026-12-31', public=True)
        self.assertEqual([e['id'] for e in out['items']], ['d', 'b', 'a', 'c'])  # cycle session on the 14th, then the 15th and 20 Nov, exhibition last
        self.assertEqual((out['items'][0]['occurrence_date'], out['items'][0]['time']), ('2026-10-14', '20:00'))
        self.assertNotIn('e', [e['id'] for e in out['items']])
        with self.assertRaises(ValueError): catalog.query_events(self.conn, date_from='2026-10-12', date_to='2027-10-12')
        with self.assertRaises(ValueError): catalog.query_events(self.conn, day='2026-10-12', date_from='2026-10-12')
        searched = catalog.query_events(self.conn, query='concert', date_from='2026-10-12', public=True)
        self.assertEqual([e['id'] for e in searched['items']], ['b', 'a'])


class VenueLinkPolicyTests(unittest.TestCase):
    def test_discovered_concert_links_to_the_hall_and_hides_the_directory(self):
        import json, tempfile
        from pathlib import Path
        from src.pipeline import connect
        self.assertEqual(catalog.presentation_of('web_conciertos_club'), 'venue_link_only')
        self.assertEqual(catalog.presentation_of('venue_songkick'), 'venue_link_only')
        self.assertIsNone(catalog.presentation_of('venue_verdi'))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('web_conciertos_club', 'x', 'Banda', '2026-10-12', '2026-10-12', 'single', 'review', 'third_party_listing_unverified', 'https://conciertos.club/barcelona/x', 'h', json.dumps({'title': 'Banda', 'descripcio': 'texto del directorio'})))
            conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', ('web_conciertos_club', 'x', 0, 'Razzmatazz 2', 'Barcelona', None, None))
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('web_conciertos_club', 'y', 'Otra', '2026-10-12', '2026-10-12', 'single', 'review', 'third_party_listing_unverified', 'https://conciertos.club/barcelona/y', 'h', json.dumps({'title': 'Otra'})))
            conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', ('web_conciertos_club', 'y', 0, 'Bar desconocido', 'Barcelona', None, None))
            conn.commit(); catalog.invalidate_cache()
            public = catalog.query_events(conn, day='2026-10-12', public=True)
            by_id = {e['id']: e for e in public['items']}
            self.assertEqual((by_id['x']['url'], by_id['x']['link_label'], by_id['x']['source_label'], by_id['x']['media']), ('https://www.salarazzmatazz.com/', 'Web de la sala', 'Programación de salas', []))
            self.assertEqual((by_id['y']['url'], by_id['y']['link_label']), ('', ''))
            detail = catalog.event_detail(conn, 'web_conciertos_club', 'x')
            self.assertEqual(detail['description'], '')
            self.assertEqual(detail['provenance_url'], 'https://conciertos.club/barcelona/x')
            self.assertEqual([l['url'] for l in detail['links']], ['https://www.salarazzmatazz.com/'])
            self.assertEqual(detail['confirmations'], 1)
            catalog.invalidate_cache(); conn.close()


class StartedCoursesTests(unittest.TestCase):
    def test_courses_begun_over_a_week_ago_are_hidden_unless_asked_and_window_is_chronological(self):
        import json, tempfile, datetime as dt
        from pathlib import Path
        from src.pipeline import connect
        today = catalog.today(); d = lambda n: (today + dt.timedelta(days=n)).isoformat()
        rows = [('old_course', 'Curs de ceràmica', d(-30), d(60), 'course'), ('new_course', 'Curs de dibuix', d(-3), d(60), 'course'),
                ('expo', 'Exposició', d(-200), d(90), 'exhibition'), ('act', 'Concert', d(2), d(2), 'single'), ('act0', 'Xerrada', d(0), d(0), 'single')]
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            for id, title, start, end, kind in rows:
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('generalitat', id, title, start, end, kind, 'review', 'x', '', 'h', json.dumps({'localizaciones': [{'denominaci': title}]})))
            conn.commit(); catalog.invalidate_cache()
            default = catalog.query_events(conn, day=d(0), public=True, include_started=False)
            self.assertEqual([e['id'] for e in default['items']], ['act0', 'expo', 'new_course'])  # today's act, then running items newest first
            everything = catalog.query_events(conn, day=d(0), public=True)
            self.assertEqual({e['id'] for e in everything['items']}, {'act0', 'expo', 'new_course', 'old_course'})
            window = catalog.query_events(conn, date_from=d(0), date_to=d(10), public=True, include_started=False)
            self.assertEqual([e['id'] for e in window['items']], ['act0', 'act', 'new_course', 'expo'])  # what starts in the period first, then running items newest first
            catalog.invalidate_cache(); conn.close()


class SubtypeTests(unittest.TestCase):
    def test_subtypes_come_from_official_paths_and_unclassified_keeps_every_record(self):
        import json, tempfile
        from pathlib import Path
        from src.pipeline import connect
        groups = catalog.subtype_groups()
        self.assertEqual(groups['Exposiciones'][-1], 'Sin clasificar'); self.assertIn('Jazz y blues', groups['Conciertos']); self.assertNotIn('Teatro', groups)
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            def od(id, name, paths, kind='single'):
                raw = {'name': name, 'register_id': id, 'secondary_filters_data': [{'full_path': p} for p in paths], 'classifications_data': [], 'addresses': [{'address_name': 'x', 'district_name': 'Eixample'}], 'loagendo': {'category': 'Música y vida nocturna' if kind == 'single' else 'Arte y exposiciones'}}
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', id, name, '2026-10-20', '2026-10-20' if kind == 'single' else '2026-12-20', kind, 'review', 'x', '', 'h', json.dumps(raw)))
            od('1', 'Concert de jazz', ['Agenda >> Música >> Jazz i blues'])
            od('2', 'Concert sense ruta', [])
            od('3', 'Exposició de fotos', ['Agenda >>  Exposicions >> Fotografia '], kind='exhibition')
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('web_conciertos_club', '4', 'Banda', '2026-10-20', '2026-10-20', 'single', 'review', 'x', 'https://conciertos.club/x', 'h', '{}'))
            conn.commit(); catalog.invalidate_cache()
            items = {e['id']: e for e in catalog.query_events(conn, day='2026-10-20', public=True)['items']}
            self.assertEqual((items['1']['public_category'], items['1']['legacy_category'], items['1']['subtype']), ('musica', 'Conciertos', 'Jazz y blues'))
            self.assertEqual(items['2']['subtype'], 'Sin clasificar'); self.assertEqual(items['4']['subtype'], 'Sin clasificar')
            self.assertEqual(items['3']['subtype'], 'Fotografía')
            jazz = catalog.query_events(conn, day='2026-10-20', public=True, public_category='Conciertos', subtype='Jazz y blues')
            rest = catalog.query_events(conn, day='2026-10-20', public=True, public_category='Conciertos', subtype='Sin clasificar')
            self.assertEqual(([e['id'] for e in jazz['items']], sorted(e['id'] for e in rest['items'])), (['1'], ['2', '4']))
            self.assertEqual(jazz['total'] + rest['total'], catalog.query_events(conn, day='2026-10-20', public=True, public_category='Conciertos')['total'])
            catalog.invalidate_cache(); conn.close()


class VenueUpcomingTests(unittest.TestCase):
    def test_detail_lists_other_public_records_at_the_same_hall_soonest_first(self):
        import json, tempfile, datetime as dt
        from pathlib import Path
        from src.pipeline import connect
        today = catalog.today(); d = lambda n: (today + dt.timedelta(days=n)).isoformat()
        rows = [('a', 'Concert A', d(0), d(0), 'single', 'Sala Apolo'), ('b', 'Concert B', d(3), d(3), 'single', 'Apolo'), ('c', 'Concert C', d(1), d(1), 'single', 'La [2] de Apolo'),
                ('past', 'Pasado', d(-2), d(-2), 'single', 'Sala Apolo'), ('other', 'En otra sala', d(1), d(1), 'single', 'Razzmatazz'), ('expo', 'Expo', d(-10), d(30), 'exhibition', 'Sala Apolo')]
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            for id, title, start, end, kind, venue in rows:
                conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('generalitat', id, title, start, end, kind, 'review', 'x', '', 'h', json.dumps({'localizaciones': [{'denominaci': title}]})))
                conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', ('generalitat', id, 0, venue, '', None, None))
                if kind == 'single': conn.execute('INSERT INTO candidate_occurrences VALUES (?,?,?,?,?,?)', ('generalitat', id, start, '21:00', 'single', 'x'))
            conn.commit(); catalog.invalidate_cache()
            detail = catalog.event_detail(conn, 'generalitat', 'a')
            self.assertEqual([(u['id'], u['date'], u['time']) for u in detail['venue_upcoming']], [('expo', d(0), None), ('c', d(1), '21:00'), ('b', d(3), '21:00')])
            catalog.invalidate_cache(); conn.close()


class FestivalTests(unittest.TestCase):
    def test_two_day_festival_with_hours_lists_with_its_time_and_ranks_with_dated_acts(self):
        import json, tempfile
        from pathlib import Path
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            festival = {'name': 'MIRA Festival 2026', 'register_id': 1, 'timetable': {'html': '<table><tr><td class="timetable-day"><div>Divendres i dissabte</div></td><td class="timetable-hour"><div>de 17.30 h a 05.30 h</div></td></tr></table>'}, 'addresses': [{'address_name': 'Fira', 'district_name': 'Sants-Montjuïc'}], 'secondary_filters_data': [{'full_path': 'Agenda >> Música >> Electrònica, techno i dance'}], 'loagendo': {'category': 'Música y vida nocturna', 'schedule_hours': 'de 17.30 h a 05.30 h'}}
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '1', 'MIRA Festival 2026', '2026-11-06', '2026-11-07', 'program', 'review', 'x', '', 'h', json.dumps(festival)))
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '2', 'Cicle llarg', '2026-10-01', '2026-12-20', 'program', 'review', 'x', '', 'h', json.dumps({'name': 'Cicle llarg', 'register_id': 2, 'addresses': [], 'loagendo': {'category': 'Música y vida nocturna', 'schedule_hours': 'a les 20.00 h'}})))
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '3', 'Concert', '2026-11-06', '2026-11-06', 'single', 'review', 'x', '', 'h', json.dumps({'name': 'Concert', 'register_id': 3, 'addresses': [], 'loagendo': {'category': 'Música y vida nocturna', 'schedule_hours': 'a les 19.00 h'}})))
            conn.commit(); catalog.invalidate_cache()
            out = catalog.query_events(conn, day='2026-11-07', public=True)
            mira = next(e for e in out['items'] if e['id'] == '1')
            # Horario oficial del día (18-10-2026): empieza a las 17:30 y la etiqueta dice también el cierre.
            self.assertEqual((mira['time'], mira['time_source'], mira['time_label']), ('17:30', 'official_schedule_by_day', '17:30–05:30'))
            self.assertTrue(catalog.is_festival(mira)); self.assertGreater(catalog.featured_score(mira, '2026-11-06')[0], catalog.featured_score(next(e for e in out['items'] if e['id'] == '2'), '2026-11-06')[0] + 30)
            both = catalog.query_events(conn, day='2026-11-06', public=True)
            self.assertEqual([e['id'] for e in both['items']], ['1', '3', '2'])  # timed acts by time, the long cycle last
            catalog.invalidate_cache(); conn.close()


class TwinMergeTests(unittest.TestCase):
    def test_canonical_record_borrows_image_and_text_from_its_collapsed_twin_and_festival_format(self):
        import json, tempfile
        from pathlib import Path
        from src.pipeline import connect
        from src.dedupe import refresh_match_candidates
        from src import media as media_module
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            od = {'name': 'MIRA Festival 2026', 'register_id': 1, 'addresses': [{'address_name': 'Fira', 'district_name': 'Sants-Montjuïc'}], 'loagendo': {'category': 'Música y vida nocturna'}}
            gen = {'localizaciones': [{'denominaci': 'MIRA Digital Arts Festival', 'descripcio_html': '<p>Festival d\'arts digitals.</p><p>Tres escenaris.</p>', 'preu': '45 €'}]}
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '1', 'MIRA Festival 2026', '2026-11-06', '2026-11-07', 'program', 'review', 'x', 'https://guia.barcelona.cat/1', 'h', json.dumps(od)))
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('generalitat', 'g', 'MIRA Digital Arts Festival', '2026-11-06', '2026-11-07', 'program', 'review', 'x', 'https://mirafestival.com/', 'h', json.dumps(gen)))
            for s, i in (('opendatabcn_agenda', '1'), ('generalitat', 'g')): conn.execute('INSERT INTO source_venues VALUES (?,?,?,?,?,?,?)', (s, i, 0, 'Fira Barcelona', '', 41.3727, 2.1502))
            media_module.register(conn, 'generalitat', 'g', 'https://img.test/mira.jpg', rights_status='authorized'); conn.commit()
            refresh_match_candidates(conn, since='2026-10-01'); catalog.invalidate_cache()
            public = catalog.query_events(conn, day='2026-11-06', public=True)
            self.assertEqual([e['key'] for e in public['items']], ['opendatabcn_agenda:1'])
            card = public['items'][0]
            self.assertEqual((card['format'], card['format_label'], card['also_in']), ('festival', 'Festivales', ['generalitat:g']))
            self.assertEqual(card['media'][0]['borrowed_from'], 'generalitat:g')  # the municipal card shows the Generalitat image
            detail = catalog.event_detail(conn, 'opendatabcn_agenda', '1')
            self.assertEqual((detail['description'], detail['description_source'], detail['confirmations']), ("Festival d'arts digitals.\nTres escenaris.", 'generalitat:g', 2))
            self.assertIn('https://mirafestival.com/', [l['url'] for l in detail['links']])
            catalog.invalidate_cache(); conn.close()


class VenuePrestigeTests(unittest.TestCase):
    def test_tiers_and_disambiguation(self):
        from src.venue_prestige import venue_points, prestige
        self.assertEqual(venue_points("Gran Teatre del Liceu")[0], 12)
        self.assertEqual(venue_points("Centre Cívic Sagrada Família")[0], 3)   # civic centre, not the basilica
        self.assertEqual(venue_points("Biblioteca de Catalunya")[0], 8)        # national library, not the network
        self.assertEqual(venue_points("Espais Volart - Fundació Vila Casas")[0], 8)  # 'vol' must not match inside 'volart'
        self.assertEqual(venue_points("Galeria Desconeguda")[0], 0)
        self.assertEqual(prestige(["Galeria Desconeguda", "L'Auditori"])[0], 12)

    def test_featured_score_adds_prestige_and_rotates_ties(self):
        base = {'format': 'one_shot', 'start': '2026-10-13', 'end': '2026-10-13', 'time': '20:00', 'has_candidate': True, 'media': [], 'has_description': True, 'coordinates': None, 'source': 's', 'id': '1', 'title': 'a', 'confirmations': 1}
        plain = dict(base, venue_names=['Galeria Desconeguda'])
        liceu = dict(base, venue_names=['Gran Teatre del Liceu'], id='2')
        self.assertEqual(catalog.featured_score(liceu, '2026-10-13')[0] - catalog.featured_score(plain, '2026-10-13')[0], 12)
        twice = dict(plain, confirmations=3)
        self.assertEqual(catalog.featured_score(twice, '2026-10-13')[0] - catalog.featured_score(plain, '2026-10-13')[0], 10)
        a, b = catalog.featured_rotation(plain, '2026-10-13'), catalog.featured_rotation(liceu, '2026-10-13')
        self.assertNotEqual(a, b); self.assertNotEqual(a, catalog.featured_rotation(plain, '2026-10-14'))

    def test_spread_venues_keeps_order_but_alternates_halls(self):
        mk = lambda i, v: {'id': str(i), 'venue_names': [v]}
        ranked = [mk(1, 'CCCB'), mk(2, 'CCCB'), mk(3, 'CCCB'), mk(4, 'Liceu'), mk(5, 'Apolo'), mk(6, 'CCCB')]
        self.assertEqual([e['id'] for e in catalog.spread_venues(ranked)], ['1', '4', '5', '2', '3', '6'])
