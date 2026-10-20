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


class WeeklyTextTests(unittest.TestCase):
    def test_generalitat_weekly_text_gives_hours_per_day(self):
        from src.guia_schedule import weekly_rows, schedule_by_day
        text = 'Dimarts: 20.30 h Dimecres i dijous: 20 h Divendres i dissabtes: 17 h i 21 h Diumenges: 16.30 h Durada aproximada: 180 minuts'
        by_day = schedule_by_day(weekly_rows(text), '2026-10-19', '2026-10-25')
        self.assertNotIn('2026-10-19', by_day)                       # dilluns: no hi ha funció
        self.assertEqual(by_day['2026-10-20'], '20:30')
        self.assertEqual(by_day['2026-10-23'], '17:00 · 21:00')
        self.assertEqual(by_day['2026-10-25'], '16:30')

    def test_unclear_hours_are_not_asserted(self):
        from src.guia_schedule import weekly_rows, schedule_by_day
        by_day = schedule_by_day(weekly_rows('Dissabtes: 17 h Diumenges: 12 h o 17 h'), '2026-10-19', '2026-10-25')
        self.assertEqual(by_day, {'2026-10-24': '17:00', '2026-10-25': '12:00 · 17:00'})   # «o»: dos pases
        self.assertEqual(weekly_rows('Abans de res: dimarts 20 h'), [])

    def test_seasons(self):
        from src.guia_schedule import weekly_rows, schedule_by_day
        inline = "Dilluns: d'11 a 19.30 h (del 25 de setembre al 24 de juny) i de 10 a 20 h (del 25 de juny al 24 de setembre)"
        self.assertEqual(schedule_by_day(weekly_rows(inline), '2026-06-15', '2026-06-30'), {'2026-06-15': '11:00–19:30', '2026-06-22': '11:00–19:30', '2026-06-29': '10:00–20:00'})
        blocks = "Horari d'hivern (de l'1 de novembre al 31 de març): De dimarts a diumenges: de 10 a 18 h Horari d'estiu (de l'1 d'abril al 31 d'octubre): De dimarts a diumenges: de 10 a 20 h"
        by_day = schedule_by_day(weekly_rows(blocks), '2026-10-30', '2026-11-03')
        self.assertEqual(by_day, {'2026-10-30': '10:00–20:00', '2026-10-31': '10:00–20:00', '2026-11-01': '10:00–18:00', '2026-11-03': '10:00–18:00'})
        months = 'D’octubre a febrer: De dimarts a dissabtes: de 10 a 19 h De març a setembre: De dimarts a dissabtes: de 10 a 20 h'
        self.assertEqual(schedule_by_day(weekly_rows(months), '2027-02-26', '2027-03-02'), {'2027-02-26': '10:00–19:00', '2027-02-27': '10:00–19:00', '2027-03-02': '10:00–20:00'})

    def test_weekend_and_holidays(self):
        from src.guia_schedule import schedule_by_day, weekly_rows
        rows = [{'dies': 'Dissabte, diumenge i festius', 'hores': 'A les 10:30h (en castellà)'}, {'hores': 'A les 12:00 h (en català)'}]
        self.assertEqual(schedule_by_day(rows, '2026-10-19', '2026-10-25'), {'2026-10-24': '10:30 · 12:00', '2026-10-25': '10:30 · 12:00'})
        self.assertEqual(weekly_rows('De dimarts a dissabtes: de 10 a 19 h Dilluns tancat')[-1], {'dies': 'Dilluns', 'hores': 'tancat'})


class RowNotesTests(unittest.TestCase):
    def test_each_day_keeps_its_own_activity(self):
        # 99400789129 (10è aniversari de Sinèrgics): cada día una actividad y una hora.
        from src.guia_schedule import summary
        rows = [{'dies': 'Dilluns', 'hores': 'de 17.00 h a 18.00 h', 'preu': 'Entrada Gratuïta', 'observacions': 'Passacarrers amb xaranga'},
                {'dies': 'Dimarts', 'hores': 'de 16.00 h a 18.00 h', 'observacions': 'Fira a Sinèrgics'},
                {'dies': 'Dijous', 'hores': 'de 12.00 h a 14.00 h', 'observacions': 'Vermut comunitari'}]
        out = summary(rows, '2026-10-19', '2026-10-23')
        self.assertEqual(out['by_day'], {'2026-10-19': '17:00–18:00', '2026-10-20': '16:00–18:00', '2026-10-22': '12:00–14:00'})
        self.assertTrue(out['schedule_text'].startswith('Dilluns: de 17.00 h a 18.00 h (Passacarrers amb xaranga) · Dimarts'))
        self.assertNotIn('schedule_note', out['facts'])
        self.assertNotIn('schedule_days', out['facts'])
        from src.guia_schedule import notes_by_day
        self.assertEqual(notes_by_day(rows, '2026-10-19', '2026-10-23'), {'2026-10-19': 'Passacarrers amb xaranga', '2026-10-20': 'Fira a Sinèrgics', '2026-10-22': 'Vermut comunitari'})
        self.assertEqual(notes_by_day([{'dies': 'Dilluns', 'hores': '17 h', 'observacions': 'Cal inscripció'}], '2026-10-19', '2026-10-23'), {})


class CentresCivicsTests(unittest.TestCase):
    def test_sessions_from_the_activity_page(self):
        from src.web_agendas import centres_sessions
        from mvp.catalog import project_raw, listed_dates
        page = ('<p>&nbsp;<br><a href="x">Julia Rodríguez</a><br><span style="color:#696969;">30/10 – 19.30 h</span><br>Amb <em>Hacia la vida</em>…</p>'
                '<p>&nbsp;<br><a href="y">Marc Vilajuana</a><br><span>06/11 – 19.30 h</span><br>Després de…</p><h2>Activitats relacionades</h2><p>Altres</p><p>01/12 – 18 h</p>')
        sessions = centres_sessions(page)
        self.assertEqual([(x['day'], x['month'], x['time'], x['title']) for x in sessions], [(30, 10, '19:30', 'Julia Rodríguez'), (6, 11, '19:30', 'Marc Vilajuana')])
        raw = {'item': {'when': '30/10, 06, 13, 20 i 27/11/2026', 'sessions': sessions}, 'normalized': {}}
        out = project_raw('web_centres_civics', 'a', 'Cinc concerts', '2026-10-30', '2026-11-27', 'program', '', raw)
        self.assertEqual(out['hours_by_day'], {'2026-10-30': '19:30', '2026-11-06': '19:30', '2026-11-13': '', '2026-11-20': '', '2026-11-27': ''})
        self.assertEqual(out['notes_by_day'], {'2026-10-30': 'Julia Rodríguez', '2026-11-06': 'Marc Vilajuana'})
        self.assertEqual(listed_dates('20/12, 10 i 17/01/2027'), ['2026-12-20', '2027-01-10', '2027-01-17'])
        self.assertEqual(listed_dates('Del 14/10/2026 al 25/02/2027'), [])


class DetailOutsideListingTests(unittest.TestCase):
    def test_dated_sessions_outside_the_listing_period(self):
        # 99400765397 «Cicle de titelles migratòries»: listado 17–23 oct.; detalle 16, 17, 23 y 24.
        from src.guia_schedule import dated_outside
        rows = [{'dies': '16 octubre i 24 octubre', 'hores': 'a les 17.30 h'}, {'dies': '17 octubre i 23 octubre', 'hores': 'a les 19.00 h'}]
        self.assertEqual(dated_outside(rows, '2026-10-17', '2026-10-23'), {'2026-10-16': '17:30', '2026-10-24': '17:30'})
        self.assertEqual(dated_outside([{'dies': 'Dissabte', 'hores': 'a les 12 h'}], '2026-10-17', '2026-10-23'), {})


class SampleReviewRulesTests(unittest.TestCase):
    """Reglas de la revisión de 20 fichas (19-10-2026)."""
    def test_first_weekend_of_the_month(self):
        from src.guia_schedule import schedule_by_day
        self.assertEqual(sorted(schedule_by_day([{'dies': '1r dissabte i diumenge del mes', 'hores': 'Per determinar'}], '2026-11-01', '2026-11-30')), ['2026-11-07', '2026-11-08'])

    def test_overnight_session_is_one_day(self):
        from src.venue_feeds import record_from_jsonld
        node = {'@type': 'MusicEvent', 'name': 'MUV: Anti-Mondays Jam', 'startDate': '2026-11-02T22:00:00+01:00', 'endDate': '2026-11-03T03:00:00+01:00',
                'url': 'https://dice.fm/event/x', 'location': {'@type': 'Place', 'name': 'Marula Café'}}
        record = record_from_jsonld({'slug': 'dice', 'name': 'DICE', 'type': 'ticketing'}, node, 'https://dice.fm/event/x')
        self.assertEqual((record['start'], record['end']), ('2026-11-02', '2026-11-02'))

    def test_online_and_policy_text(self):
        from mvp.catalog import ONLINE_VENUE, BOILER_POLICY, source_description
        self.assertTrue(ONLINE_VENUE.match('On-line')); self.assertFalse(ONLINE_VENUE.match('Online Club Barcelona'))
        self.assertTrue(BOILER_POLICY.match('Aplica una cuota de servicio de 2€ por transacción.'))
        self.assertEqual(source_description({'loagendo': {'description': '**MUV** en Marula \\+ DJ'}}, 'venue_dice'), 'MUV en Marula + DJ')


class SampleReview2Tests(unittest.TestCase):
    def test_price_parts_and_links(self):
        from mvp.catalog import split_price, readable_links
        self.assertEqual(split_price('Entrada general: 87.48 € · Reducció dels imports als cursos, · informeu-vos al centre · \ufeff Cal inscripció prèvia.'),
                         ('Entrada general: 87.48 € · Reducció dels imports als cursos, informeu-vos al centre', ['Cal inscripció prèvia.']))
        links = readable_links([{'label': 'Enlace detectado en la fuente · GuiaBCN', 'url': 'http://www.instagram.com/x/'},
                                {'label': 'Enlace detectado en la fuente', 'url': 'https://www.instagram.com/x'},
                                {'label': 'Enlace detectado en la fuente', 'url': 'http://www.cotxeres-casinet.org'}])
        self.assertEqual([l['label'] for l in links], ['Instagram', 'Web: cotxeres-casinet.org'])


class LastWeekdayTests(unittest.TestCase):
    def test_last_friday_without_accent(self):
        # 99400783039 «Verdaguer y Gaudí»: «Ultim divendres del mes» (sin acento en la fuente).
        from src.guia_schedule import schedule_by_day
        self.assertEqual(sorted(schedule_by_day([{'dies': 'Ultim divendres del mes', 'hores': 'de 10.30 h a 12.00 h'}], '2026-07-31', '2026-11-27')),
                         ['2026-07-31', '2026-08-28', '2026-09-25', '2026-10-30', '2026-11-27'])
        self.assertEqual(sorted(schedule_by_day([{'dies': 'último viernes de cada mes', 'hores': 'a las 19 h'}], '2026-10-01', '2026-11-30')), ['2026-10-30', '2026-11-27'])


class ShareCardTests(unittest.TestCase):
    def test_card_for_whatsapp_preview(self):
        import datetime as dt
        from src.publish_static import share_card
        card = share_card({'title': 'Bambi', 'start': '2026-10-23', 'end': '2026-10-23', 'time_label': '23:59', 'time': '23:59',
                           'venue_names': ['Moog'], 'summary': 'Sesión ' + 'muy larga ' * 30, 'media': [{'url': '/img/a.jpg'}], 'is_free': False}, dt.date(2026, 10, 19))
        self.assertEqual((card['t'], card['w'], card['v'], card['i']), ('Bambi', 'vie 23 oct · medianoche', 'Moog', '/img/a.jpg'))
        self.assertTrue(card['d'].endswith('…') and len(card['d']) <= 151)
        long = share_card({'title': 'Expo', 'start': '2026-09-01', 'end': '2026-11-08', 'time_label': 'Exposición', 'venue_names': ['MACBA']}, dt.date(2026, 10, 19))
        self.assertEqual(long['w'], 'Hasta el 8 nov')


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

    def test_row_without_hours_takes_the_hours_above(self):
        # En la web de GuiaBCN la celda de horas vacía es un rowspan de la fila anterior
        # (comprobado en 99400787152: «Dissabte / Diumenge: a les 10.30 h», 19-10-2026).
        rows = [{'dies': 'Divendres', 'hores': 'a les 21.00 h'}, {'dies': 'Dissabte', 'observacions': 'Entrades exhaurides'}]
        self.assertEqual(summary(rows, '2026-10-23', '2026-10-24')['by_day'], {'2026-10-23': '21:00', '2026-10-24': '21:00'})
        rows = [{'dies': 'Dijous', 'hores': 'a les 18.30 h'}, {'dies': 'Dissabte', 'hores': 'a les 10.30 h'}, {'dies': 'Diumenge', 'hores': ''}]
        self.assertEqual(summary(rows, '2026-10-22', '2026-10-25')['by_day'], {'2026-10-22': '18:30', '2026-10-24': '10:30', '2026-10-25': '10:30'})

    def test_more_day_formats(self):
        from src.guia_schedule import weekly_rows, schedule_by_day, parse_hours
        self.assertEqual(schedule_by_day(weekly_rows('Dimarts 20: 19 h Dimarts 27: 19 h'), '2026-10-20', '2026-10-27'), {'2026-10-20': '19:00', '2026-10-27': '19:00'})
        self.assertEqual(schedule_by_day(weekly_rows('els tercers dimecres de mes a les 20 h'), '2026-10-21', '2026-12-31'), {'2026-10-21': '20:00', '2026-11-18': '20:00', '2026-12-16': '20:00'})
        self.assertEqual(schedule_by_day([{'dies': '1r i 3r divendres del mes', 'hores': 'a les 11.00 h'}], '2026-10-01', '2026-10-31'), {'2026-10-02': '11:00', '2026-10-16': '11:00'})
        self.assertEqual(schedule_by_day([{'dies': 'Dijous excepte festius', 'hores': 'a les 16.30 h'}], '2026-10-19', '2026-10-25'), {'2026-10-22': '16:30'})
        self.assertEqual(parse_hours('A partir de les 10h i fins exhaurir existències')['sessions'], ['10:00'])


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


class LinesScheduleTests(unittest.TestCase):
    def test_theatre_page_lines_with_days_off_and_extra_shows(self):
        from src.guia_schedule import lines_schedule
        text = "De miércoles a viernes a las 19.30 h\nSábados a las 17.00 h y a las 20.30 h\nDomingos a las 18.30 h\n28/11 no hay función\nFunción escolar\n25/11 a las 10.30 h"
        hb = lines_schedule(text, '2026-11-19', '2026-12-13')
        self.assertEqual((hb['2026-11-21'], hb['2026-11-22'], hb['2026-11-25']), ('17:00 · 20:30', '18:30', '10:30 · 19:30'))
        self.assertNotIn('2026-11-28', hb); self.assertNotIn('2026-11-23', hb)  # sin función y lunes


class PageScheduleTests(unittest.TestCase):
    def test_lliure_diputacio_and_macba_pages(self):
        from src.guia_detail import page_schedule
        t, text, facts = page_schedule('web_teatre_lliure', '<h3 class="tit">Horario</h3> <p class="text">Domingos a las 18.30 h<br> 28/11 no hay función</p><h3 class="tit">Precio</h3> <p class="text">De 8 € a 32 €</p>')
        self.assertEqual((text, facts['price_text']), ('Domingos a las 18.30 h\n28/11 no hay función', 'De 8 € a 32 €'))
        self.assertEqual(page_schedule('diba_turismo', '<h4 class="mt-4">Quan?</h4> <p><b>22/10/2026</b></p> <p>18:30 - 20:00</p> <h4>On?</h4>', '2026-10-22', '2026-10-22')[:2], ('18:30', '22/10/2026 · 18:30 - 20:00'))
        self.assertEqual(page_schedule('web_macba', '<span class="macba-button button-secondary px-3">próximamente</span>')[1], 'Próximamente')
