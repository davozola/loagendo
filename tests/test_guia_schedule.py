"""Horario de GuiaBCN por filas y por día (API `pg=detall`).

Casos reales del 18-10-2026: 99400788805 (rango distinto el último día),
99400300596 (sesiones por fechas), 99400320598 (grupos por días de la
semana), 99400369008 (curso con excepciones), 99400626822 (sesiones por día
de la semana)."""
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.guia_schedule import api_rows, parse_days, parse_hours, summary

FIXTURE = Path(__file__).parent / 'fixtures' / 'guiabcn_detall_99400788805.json'
LIVER_ROWS = [{'dies': '17 octubre, 18 octubre i 19 octubre', 'hores': 'de 09.00 h a 18.00 h', 'preu': 'Entrada Gratuïta'},
              {'dies': '20 octubre', 'hores': 'de 09.00 h a 12.00 h'}]
# La tabla tal como la pinta la página: el precio ocupa dos filas.
LIVER_PAGE = ('<div id="horari"><table><tr><td class="content-info"><div>17 octubre, <br/>18 octubre i <br/>19 octubre</div></td>'
              '<td class="content-info"><div>de 09.00 h a 18.00 h</div></td><td class="content-info" rowspan="2"><div>Entrada Gratuïta</div></td></tr>'
              '<tr><td class="content-info"><div>20 octubre</div></td><td class="content-info"><div>de 09.00 h a 12.00 h</div></td></tr></table></div>')


class ParseTests(unittest.TestCase):
    def test_api_rows_are_plain_text_per_row(self):
        self.assertEqual(api_rows(json.loads(FIXTURE.read_text())), LIVER_ROWS)
        self.assertIsNone(api_rows({'error': 'x'}))
        self.assertEqual(api_rows({'page': {'central': {'detall': {'item': {'entity_id': '1'}}}}}), [])

    def test_hours_distinguish_ranges_and_sessions(self):
        self.assertEqual(parse_hours('de 09.00 h a 18.00 h'), {'ranges': [('09:00', '18:00')], 'sessions': []})
        self.assertEqual(parse_hours('a les 17.30 h i a les 20.30 h'), {'ranges': [], 'sessions': ['17:30', '20:30']})
        self.assertEqual(parse_hours('de 10.00 h a 14.00 h i de 17.00 h a 20.00 h')['ranges'], [('10:00', '14:00'), ('17:00', '20:00')])
        # Texto que no es hora: mejor sin hora que una hora inventada.
        self.assertIsNone(parse_hours('portes a les 19 h'))
        self.assertIsNone(parse_hours('Consultar horaris'))

    def test_days_lists_ranges_and_weekdays(self):
        start, end = dt.date(2026, 10, 17), dt.date(2026, 11, 30)
        self.assertEqual(parse_days('17 octubre, 18 octubre i 19 octubre', start, end), {dt.date(2026, 10, d) for d in (17, 18, 19)})
        self.assertEqual(parse_days("12 i 19 de novembre", start, end), {dt.date(2026, 11, 12), dt.date(2026, 11, 19)})
        self.assertEqual(len(parse_days('del 3 al 7 de novembre', start, end)), 5)
        self.assertEqual({d.weekday() for d in parse_days('De dilluns a divendres', start, end)}, {0, 1, 2, 3, 4})
        self.assertEqual({d.weekday() for d in parse_days('Dissabte', start, end)}, {5})
        self.assertIsNone(parse_days('Dilluns, excepte festius', start, end))
        self.assertIsNone(parse_days('15 desembre', start, end))  # fuera del rango del evento


class SummaryTests(unittest.TestCase):
    def test_love_your_liver_keeps_each_days_hours(self):
        result = summary(LIVER_ROWS, '2026-10-17', '2026-10-20')
        self.assertEqual(result['by_day'], {'2026-10-17': '09:00–18:00', '2026-10-18': '09:00–18:00', '2026-10-19': '09:00–18:00', '2026-10-20': '09:00–12:00'})
        self.assertEqual(result['schedule_time'], '')  # varía según el día: no se elige uno
        self.assertEqual(result['schedule_text'], '17 octubre, 18 octubre i 19 octubre: de 09.00 h a 18.00 h · 20 octubre: de 09.00 h a 12.00 h')
        self.assertEqual(result['facts']['price_text'], 'Entrada Gratuïta')
        self.assertNotIn('schedule_note', result['facts'])

    def test_sessions_by_date_and_by_weekday(self):
        rows = [{'dies': '12 desembre i 19 desembre', 'hores': 'a les 17.30 h i a les 20.30 h'}, {'dies': '13 desembre i 20 desembre', 'hores': 'a les 18.00 h'}]
        self.assertEqual(summary(rows, '2026-12-12', '2026-12-20')['by_day'], {'2026-12-12': '17:30 · 20:30', '2026-12-13': '18:00', '2026-12-19': '17:30 · 20:30', '2026-12-20': '18:00'})
        rows = [{'dies': 'Dimarts, dimecres, dijous, divendres i dissabte', 'hores': 'a les 19.00 h'}, {'dies': 'Diumenge', 'hores': 'a les 18.00 h'}]
        by_day = summary(rows, '2027-04-17', '2027-04-20')['by_day']
        self.assertEqual(by_day, {'2027-04-17': '19:00', '2027-04-18': '18:00', '2027-04-20': '19:00'})  # el lunes 19 no hay función

    def test_vague_exceptions_keep_the_weekday_and_show_the_note(self):
        rows = [{'periode': 'Curs escolar', 'dies': 'Divendres', 'hores': 'de 16.30 h a 19.30 h', 'observacions': 'Excepte vacances de Nadal i Setmana Santa'}]
        result = summary(rows, '2026-10-02', '2026-10-16')
        self.assertEqual(result['by_day'], {'2026-10-02': '16:30–19:30', '2026-10-09': '16:30–19:30', '2026-10-16': '16:30–19:30'})
        self.assertEqual(result['facts']['schedule_note'], 'Curs escolar · Excepte vacances de Nadal i Setmana Santa')

    def test_row_period_restricts_its_days(self):
        # 99400753159: «Del 14 octubre a l'11 novembre», Dimecres, de 17.15 h a 18.15 h; el registro llega hasta el 25-11.
        rows = [{'periode': "Del 14 octubre a l'11 novembre", 'dies': 'Dimecres', 'hores': 'de 17.15 h a 18.15 h', 'preu': 'Entrada Gratuïta'}]
        by_day = summary(rows, '2026-10-14', '2026-11-25')['by_day']
        self.assertEqual(sorted(by_day), ['2026-10-14', '2026-10-21', '2026-10-28', '2026-11-04', '2026-11-11'])
        self.assertEqual(set(by_day.values()), {'17:15–18:15'})

    def test_conflicting_rows_leave_the_day_without_hours(self):
        rows = [{'dies': 'Cada dia', 'hores': 'de 10.00 h a 20.00 h'}, {'dies': 'Dissabte', 'hores': 'de 10.00 h a 14.00 h'}]
        by_day = summary(rows, '2026-10-23', '2026-10-25')['by_day']
        self.assertEqual(by_day, {'2026-10-23': '10:00–20:00', '2026-10-24': '', '2026-10-25': '10:00–20:00'})  # hay actividad, hora sin afirmar


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        from src.pipeline import connect
        self.folder = tempfile.TemporaryDirectory(); self.conn = connect(Path(self.folder.name) / 't.sqlite3')
        self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility,source_url) VALUES('guiabcn','99400788805','Love Your Liver','2026-10-17','2026-10-20','{}','review','https://guia.barcelona.cat/ca/detall/x_99400788805.html')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.folder.cleanup()

    def enrich(self, api):
        from src.guia_detail import enrich_sources
        calls = []
        def fetcher(url, timeout):
            calls.append(url)
            if 'apinasia' in url:
                if isinstance(api, Exception): raise api
                return api
            return LIVER_PAGE
        result = enrich_sources(self.conn, 10, sources=('guiabcn',), fetcher=fetcher)
        facts = json.loads(self.conn.execute("SELECT facts_json FROM source_detail_facts").fetchone()[0])
        time, text = self.conn.execute("SELECT schedule_time,schedule_text FROM source_enrichments").fetchone()
        return result, calls, facts, time, text

    def test_schedule_comes_from_the_detail_api_with_evidence(self):
        result, calls, facts, time, text = self.enrich(FIXTURE.read_text())
        self.assertEqual(result['enriched'], 1)
        self.assertTrue(any('pg=detall' in u and 'id_doc=99400788805' in u for u in calls))
        self.assertEqual(facts['schedule_source'], 'guiabcn_api_detall')
        self.assertEqual(len(facts['schedule_api_sha256']), 64)
        self.assertEqual(facts['schedule_rows'], LIVER_ROWS)
        self.assertEqual(facts['hours_by_day']['2026-10-20'], '09:00–12:00')
        self.assertEqual(time, '')
        self.assertIn('20 octubre: de 09.00 h a 12.00 h', text)
        self.assertNotIn('schedule_note', facts)  # «20 octubre» ya no se toma por una nota

    def test_page_table_is_the_fallback_when_the_api_fails(self):
        _, _, facts, _, _ = self.enrich(OSError('down'))
        self.assertEqual(facts['schedule_source'], 'guiabcn_detail_page')
        self.assertEqual(facts['hours_by_day'], {'2026-10-17': '09:00–18:00', '2026-10-18': '09:00–18:00', '2026-10-19': '09:00–18:00', '2026-10-20': '09:00–12:00'})


class PublicTimeTests(unittest.TestCase):
    def event(self, **extra):
        return {'source': 'guiabcn', 'start': '2026-10-17', 'end': '2026-10-20', 'occurrences': [], 'kind': 'program', 'category': '', 'title': 'x',
                'hours_by_day': {'2026-10-18': '09:00–18:00', '2026-10-20': '09:00–12:00'}, **extra}

    def test_each_day_shows_its_own_hours(self):
        from mvp.catalog import public_fields
        projection = {'price_label': None, 'is_free': True, 'url': None}
        self.assertEqual(public_fields(self.event(), projection, requested_day='2026-10-20')['time_label'], '09:00–12:00')
        self.assertEqual(public_fields(self.event(), projection, requested_day='2026-10-18')['time'], '09:00')
        # Sin día pedido no se escoge un horario que no vale para todos los días.
        self.assertIsNone(public_fields(self.event(), projection)['time'])


if __name__ == '__main__': unittest.main()


class RealRowsTests(unittest.TestCase):
    """Patrones frecuentes vistos en una muestra de 161 fichas (18-10-2026)."""

    def test_excepte_dates_are_removed(self):
        by_day = summary([{'dies': 'Dilluns excepte 12 octubre', 'hores': 'de 17.45 h a 19.15 h'}], '2026-10-05', '2026-10-19')['by_day']
        self.assertEqual(sorted(by_day), ['2026-10-05', '2026-10-19'])
        self.assertIsNone(parse_days('Dissabte, diumenge i festius', dt.date(2026, 10, 1), dt.date(2026, 10, 31)))

    def test_rows_without_days_continue_the_previous_row(self):
        rows = [{'dies': 'Dijous', 'hores': 'de 18.15 h a 19.30 h', 'observacions': 'Grup iniciació'}, {'hores': 'de 19.30 h a 20.45 h', 'observacions': 'Grup intermedi'}]
        self.assertEqual(summary(rows, '2026-10-01', '2026-10-08')['by_day'], {'2026-10-01': '18:15–19:30 · 19:30–20:45', '2026-10-08': '18:15–19:30 · 19:30–20:45'})


    def test_weekdays_plus_dates_and_language_notes(self):
        rows = [{'dies': 'Dijous i divendres i 31 octubre excepte 30 octubre', 'hores': 'a les 18.00 h'}]
        self.assertEqual(sorted(summary(rows, '2026-10-29', '2026-11-01')['by_day']), ['2026-10-29', '2026-10-31'])
        rows = [{'dies': 'Dissabte', 'hores': 'a les 10.30 h (anglès)'}, {'hores': 'a les 12.00 h (castellà)'}]
        self.assertEqual(summary(rows, '2026-10-24', '2026-10-24')['by_day'], {'2026-10-24': '10:30 · 12:00'})

    def test_row_without_hours_gives_no_hours(self):
        rows = [{'dies': 'Divendres', 'hores': 'a les 21.00 h'}, {'dies': 'Dissabte', 'observacions': 'Entrades exhaurides'}]
        self.assertEqual(summary(rows, '2026-10-23', '2026-10-24')['by_day'], {'2026-10-23': '21:00', '2026-10-24': ''})


class StaticExportTests(unittest.TestCase):
    def test_hours_by_day_are_packed_by_label(self):
        from src.publish_static import packed_hours
        event = {'start': '2026-10-17', 'hours_by_day': {'2026-10-17': '09:00–18:00', '2026-10-18': '09:00–18:00', '2026-10-19': '09:00–18:00', '2026-10-20': '09:00–12:00'}}
        self.assertEqual(packed_hours(event), {'09:00–18:00': [0, 1, 2], '09:00–12:00': [3]})
        self.assertIsNone(packed_hours({'start': '2026-10-17'}))


class OpenDataTimetableTests(unittest.TestCase):
    def test_rows_are_paired_and_price_spanning_rows_does_not_shift_cells(self):
        from src.opendata_bcn import schedule_for, timetable_rows
        html = ('<table class="timetable-table"><tr class="timetable-header"><th class="weekdays">Dies</th><th class="hours">Hores</th><th class="prices">Preus</th></tr>'
                '<tr><td class="timetable-day" rowspan=1><div>Divendres</div></td><td class="timetable-hour" rowspan=1><div>de 10.00&nbsp;h a 20.30&nbsp;h</div></td><td class="timetable-price" rowspan=3><div>Entrada Gratuïta</div></td></tr>'
                '<tr><td class="timetable-day" rowspan=1><div>Dissabte</div></td><td class="timetable-hour" rowspan=1><div>de 10.00&nbsp;h a 20.00&nbsp;h</div></td></tr>'
                '<tr><td class="timetable-day" rowspan=1><div>Diumenge</div></td><td class="timetable-hour" rowspan=1><div>de 10.00&nbsp;h a 19.30&nbsp;h</div></td></tr></table>')
        item = {'timetable': {'html': html}}
        self.assertEqual(timetable_rows(item), [{'dies': 'Divendres', 'hores': 'de 10.00 h a 20.30 h', 'preu': 'Entrada Gratuïta'},
                                                {'dies': 'Dissabte', 'hores': 'de 10.00 h a 20.00 h'}, {'dies': 'Diumenge', 'hores': 'de 10.00 h a 19.30 h'}])
        result = schedule_for(item, '2026-11-06', '2026-11-08')
        self.assertEqual(result['by_day'], {'2026-11-06': '10:00–20:30', '2026-11-07': '10:00–20:00', '2026-11-08': '10:00–19:30'})
        self.assertEqual(result['facts']['schedule_hours'], 'Divendres: de 10.00 h a 20.30 h · Dissabte: de 10.00 h a 20.00 h · Diumenge: de 10.00 h a 19.30 h')

    def test_day_cell_spanning_rows_is_one_day_with_two_groups(self):
        from src.opendata_bcn import schedule_for
        html = ('<table><tr><td class="timetable-day" rowspan=2><div>Divendres</div></td><td class="timetable-hour"><div>a les 20.00 h</div></td><td class="timetable-description"><div>Taller de danses</div></td></tr>'
                '<tr><td class="timetable-hour"><div>a les 21.00 h</div></td><td class="timetable-description"><div>Ball</div></td></tr></table>')
        result = schedule_for({'timetable': {'html': html}}, '2026-10-02', '2026-10-09')
        self.assertEqual(result['by_day'], {'2026-10-02': '20:00 · 21:00', '2026-10-09': '20:00 · 21:00'})


class EnrichmentSelectionTests(unittest.TestCase):
    def test_guiabcn_records_published_through_open_data_are_not_fetched(self):
        from src.pipeline import connect
        from src.guia_detail import enrich_sources
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3')
            for source, rid in (('guiabcn', '1'), ('guiabcn', '2'), ('opendatabcn_agenda', '2')):
                conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility,source_url) VALUES(?,?,'x','2026-10-20','2026-10-20','{}','review','https://guia.barcelona.cat/ca/detall/x_'||?||'.html')", (source, rid, rid))
            conn.commit(); calls = []
            enrich_sources(conn, 10, sources=('guiabcn',), fetcher=lambda url, timeout: calls.append(url) or '{}')
            self.assertTrue(calls and all('_1.html' in u or 'id_doc=1' in u for u in calls))
            # Pedido explícitamente, sí se consulta.
            enrich_sources(conn, 1, sources=('guiabcn',), record_ids=('2',), refresh=True, fetcher=lambda url, timeout: calls.append(url) or '{}')
            self.assertTrue(any('id_doc=2' in u for u in calls))
            conn.close()


class DetailApiTests(unittest.TestCase):
    def test_url_keeps_id_before_format_params(self):
        from src.guia_schedule import DETAIL_API
        url = DETAIL_API.format(id='1')
        self.assertLess(url.index('id_doc='), url.index('xout='))  # en otro orden el servidor responde 406

    def test_official_links_from_interestinfo(self):
        from src.guia_schedule import api_links
        detail = {'page': {'central': {'detall': {'item': {'interestinfo': {'item': {'interinfo': 'https://www.uesantandreu.cat/', 'label': 'Web'}}}}}}}
        self.assertEqual(api_links(detail), [{'label': 'Web del evento', 'url': 'https://www.uesantandreu.cat/'}])

    def test_page_fallback_keeps_the_price_of_the_first_row(self):
        from src.guia_detail import html_schedule_rows
        page = ('<div id="horari"><table><tr><td class="content-info"><div>Diumenge</div></td><td class="content-info"><div>a les 16.00 h</div></td>'
                '<td class="content-info"><p>Entrades només per socis</p></td></tr></table></div>')
        self.assertEqual(html_schedule_rows(page), [{'dies': 'Diumenge', 'hores': 'a les 16.00 h', 'preu': 'Entrades només per socis'}])


class ListingByDayTests(unittest.TestCase):
    def test_programme_only_listed_on_its_days(self):
        from mvp import catalog
        from src.pipeline import connect
        html = '<table><tr><td class="timetable-day"><div>Dimecres</div></td><td class="timetable-hour"><div>de 17.15 h a 18.15 h</div></td></tr></table>'
        raw = {'name': 'Espai moviment', 'register_id': 9, 'timetable': {'html': html}, 'addresses': [], 'loagendo': {'category': 'Talleres y experiencias', 'schedule_hours': 'de 17.15 h a 18.15 h'}}
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '9', 'Espai moviment', '2026-10-14', '2026-11-25', 'program', 'review', 'x', '', 'h', json.dumps(raw)))
            conn.commit(); catalog.invalidate_cache()
            wednesday = [e['id'] for e in catalog.query_events(conn, day='2026-10-21', public=True)['items']]
            thursday = [e['id'] for e in catalog.query_events(conn, day='2026-10-22', public=True)['items']]
            self.assertEqual((wednesday, thursday), (['9'], []))
            catalog.invalidate_cache(); conn.close()


class NotesTests(unittest.TestCase):
    def test_contacontes_keeps_exceptions_price_and_each_observation(self):
        # 99400770196 (Casa Orlandai), respuesta real de la API del 18-10-2026.
        detail = {'page': {'central': {'detall': {'item': {'timetable': {'horari': {
            'dies': '<div>Divendres excepte 25 setembre i 4 desembre</div>', 'hores': '<div>a les 17.30 h</div>', 'preu': '<div>Entrada Gratuïta</div>',
            'observacions': '<div><p style="margin:0">Cal inscripció prèvia</p><p style="margin:0">Places limitades</p></div>'}}}}}}}
        rows = api_rows(detail)
        self.assertEqual(rows[0]['observacions'], 'Cal inscripció prèvia · Places limitades')
        result = summary(rows, '2026-09-18', '2026-12-11')
        self.assertNotIn('2026-09-25', result['by_day']); self.assertNotIn('2026-12-04', result['by_day'])
        self.assertEqual(len(result['by_day']), 11)
        self.assertEqual((result['facts']['price_text'], result['facts']['schedule_note']), ('Entrada Gratuïta', 'Cal inscripció prèvia · Places limitades'))


class PeriodTableTests(unittest.TestCase):
    def test_open_data_periods_with_closed_month(self):
        # 99400784523 (exposició ELISAVA, Open Data 18-10-2026): tres periodos, agosto cerrado.
        from src.opendata_bcn import schedule_for
        html = ('<table class="timetable-table"><tr class="timetable-header"><th class="period">Període</th><th class="weekdays">Dies</th><th class="hours">Hores</th></tr>'
                '<tr><td class="timetable-period" rowspan=2><div>Del 4 juny al 2 agost</div></td><td class="timetable-day" rowspan=1><div><p style="margin:0">De dimarts a dissabte</p></div></td><td class="timetable-hour" rowspan=1><div>d\'11:00 h a 18:00 h</div></td><td class="timetable-description" rowspan=2><div><p>Tancat dilluns i festius</p></div></td></tr>'
                '<tr><td class="timetable-day" rowspan=1><div>Diumenge</div></td><td class="timetable-hour" rowspan=1><div>d\'11:00 h a 14:00 h</div></td></tr>'
                '<tr><td class="timetable-period" rowspan=1><div>Del 3 agost al 31 agost</div></td><td class="timetable-day" rowspan=1><div><p style="margin:0">Tots el dies</p></div></td><td class="timetable-hour" rowspan=1><div><p style="margin:0">Tancat</p></div></td><td rowspan=1><div></div></td></tr>'
                '<tr><td class="timetable-period current" rowspan=2><div>De l\'1 setembre al 31 maig</div></td><td class="timetable-day" rowspan=1><div>De dimarts a dissabte</div></td><td class="timetable-hour" rowspan=1><div>d\'11:00 h a 18:00 h</div></td></tr>'
                '<tr><td class="timetable-day" rowspan=1><div>Diumenge</div></td><td class="timetable-hour" rowspan=1><div>d\'11.00&nbsp;h a 14.00&nbsp;h</div></td></tr></table>')
        result = schedule_for({'timetable': {'html': html}}, '2026-06-04', '2027-05-31')
        by_day = result['by_day']
        self.assertEqual([by_day.get(d) for d in ('2026-07-05', '2026-08-10', '2026-10-18', '2026-10-19', '2026-10-20')],
                         ['11:00–14:00', None, '11:00–14:00', None, '11:00–18:00'])  # domingo, agosto cerrado, domingo, lunes cerrado, martes
        self.assertTrue(result['schedule_text'].startswith("Del 4 juny al 2 agost: De dimarts a dissabte d'11:00 h a 18:00 h; Diumenge"))
        self.assertEqual(result['facts']['schedule_note'], 'Tancat dilluns i festius')


class MusicRouteTests(unittest.TestCase):
    def test_municipal_music_goes_where_the_title_says(self):
        from mvp.catalog import public_category
        cat = 'Música y vida nocturna'
        self.assertEqual(public_category(cat, 'opendatabcn_agenda', 'Musical "Mamma Mia!"'), 'Teatro')
        self.assertEqual(public_category(cat, 'opendatabcn_agenda', "Taller 'Teatre musical'"), 'Talleres')
        self.assertEqual(public_category(cat, 'guiabcn', 'Tots Sants 2026: Castanyada a Can Portabella'), 'Barrio')
        self.assertEqual(public_category(cat, 'guiabcn', 'Barcelona Guitar Trio & Dance'), 'Conciertos')
        self.assertEqual(public_category(cat, 'guiabcn', "5è matí musical 'El Batec del Poblet'"), 'Conciertos')
