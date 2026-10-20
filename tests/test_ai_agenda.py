"""Agendas de sala leídas con IA: nada entra sin cita comprobada (src/ai_agenda.py)."""
import datetime as dt
import json
import sqlite3
import unittest

from src import ai_agenda

TODAY = dt.date(2026, 10, 20)
PAGE = """<html><body><nav><a href="/">Inici</a> Agenda Sala</nav>
<div class="ev"><a href="/evento/offbeat-jam/">Offbeat Jam - Roy Ayers + Jam</a><span>20 octubre</span><span>21:00h</span><span>Entrada 8€</span></div>
<div class="ev"><a href="/evento/los-fulanos/">Especial 17 Aniversario Marula: Los Fulanos</a><span>24 octubre</span></div>
<div class="ev"><h3>Dimarts 27</h3><p>19:30 Cicle de cinema: Wakolda</p></div>
<footer>Carrer dels Escudellers 49</footer></body></html>"""
AGENDA = {'slug': 'prova', 'name': 'Marula Café', 'address': 'Carrer dels Escudellers 49, 08002 Barcelona', 'type': 'music', 'urls': ['https://sala.test/agenda/']}


def answer(items):
    return lambda method, url, key, body=None, timeout=60, raw=False: {
        'content': [{'type': 'tool_use', 'name': 'actos', 'input': {'actos': items}}], 'usage': {'input_tokens': 1000, 'output_tokens': 200}}


def fetcher(url, timeout):
    if url.endswith('/agenda/'): return 200, url, PAGE
    return 200, url, '<meta property="og:image" content="https://sala.test/img/%s.jpg">' % url.rstrip('/').split('/')[-1]


GOOD = [{'titulo': 'Offbeat Jam - Roy Ayers + Jam', 'enlace': 'L1', 'sesiones': [{'fecha': '2026-10-20', 'cita_fecha': '20 octubre', 'hora': '21:00', 'cita_hora': '21:00h'}],
         'precio': '8€', 'cita_precio': 'Entrada 8€'},
        {'titulo': 'Especial 17 Aniversario Marula: Los Fulanos', 'enlace': 'L2', 'sesiones': [{'fecha': '2026-10-24', 'cita_fecha': '24 octubre'}]},
        {'titulo': 'Cicle de cinema: Wakolda', 'sesiones': [{'fecha': '2026-10-27', 'cita_fecha': 'Dimarts 27', 'hora': '19:30', 'cita_hora': '19:30 Cicle de cinema'}]}]
BAD = [{'titulo': 'Concierto inventado', 'sesiones': [{'fecha': '2026-10-25', 'cita_fecha': '24 octubre'}]},                       # título que no está
       {'titulo': 'Especial 17 Aniversario Marula: Los Fulanos', 'sesiones': [{'fecha': '2026-11-24', 'cita_fecha': '24 octubre'}]},  # mes cambiado
       {'titulo': 'Cicle de cinema: Wakolda', 'sesiones': [{'fecha': '2026-10-28', 'cita_fecha': 'Dimarts 27'}]},                    # día cambiado
       {'titulo': 'Offbeat Jam - Roy Ayers + Jam', 'sesiones': [{'fecha': '2026-10-20', 'cita_fecha': '20 octubre', 'hora': '22:00', 'cita_hora': '21:00h'}],
        'precio': '12€', 'cita_precio': 'Entrada 8€', 'enlace': 'L99'}]


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.text, self.links = ai_agenda.clean(PAGE, 'https://sala.test/agenda/')

    def test_clean_marks_links_and_drops_navigation(self):
        self.assertNotIn('Inici', self.text); self.assertIn('[L1]', self.text)
        self.assertEqual(self.links[0], 'https://sala.test/evento/offbeat-jam/')

    def test_good_items_pass_with_their_quotes(self):
        acts = [ai_agenda.verify(i, self.text, self.links, TODAY)[0] for i in GOOD]
        self.assertEqual(acts[0]['sesiones'], [('2026-10-20', '21:00')]); self.assertEqual(acts[0]['precio'], '8€')
        self.assertEqual(acts[0]['url'], 'https://sala.test/evento/offbeat-jam/')
        self.assertEqual(acts[1]['sesiones'], [('2026-10-24', '')])
        self.assertEqual(acts[2]['sesiones'], [('2026-10-27', '19:30')])

    def test_invented_or_shifted_data_is_dropped(self):
        self.assertIsNone(ai_agenda.verify(BAD[0], self.text, self.links, TODAY)[0])
        self.assertIsNone(ai_agenda.verify(BAD[1], self.text, self.links, TODAY)[0])
        self.assertIsNone(ai_agenda.verify(BAD[2], self.text, self.links, TODAY)[0])
        act, why = ai_agenda.verify(BAD[3], self.text, self.links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-10-20', '')]); self.assertNotIn('precio', act); self.assertNotIn('url', act)
        self.assertTrue(any('hora' in w for w in why) and any('precio' in w for w in why))

    def test_weekday_must_match(self):
        self.assertIsNone(ai_agenda._date_from_quote('2026-10-27', 'Dimecres 27', TODAY))
        self.assertEqual(ai_agenda._date_from_quote('2026-10-27', 'Dimarts 27', TODAY), dt.date(2026, 10, 27))
        self.assertEqual(ai_agenda._date_from_quote('2026-11-05', '05/11/2026', TODAY), dt.date(2026, 11, 5))
        self.assertIsNone(ai_agenda._date_from_quote('2026-10-05', '05/11/2026', TODAY))


class SyncTests(unittest.TestCase):
    def test_sync_stores_images_and_skips_unchanged_pages(self):
        from mvp import catalog
        from src.pipeline import connect
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            out = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=fetcher, requester=answer(GOOD + BAD))
            self.assertEqual((out['status'], out['rows_received']), ('completed', 3))
            rows = {r[0]: (r[1], json.loads(r[2])) for r in conn.execute("SELECT title,start_date,raw_json FROM source_records WHERE source='venue_ia_prova'")}
            self.assertEqual(rows['Offbeat Jam - Roy Ayers + Jam'][1]['loagendo']['source_label'], 'Datos de la sala')
            self.assertIn('quotes', rows['Offbeat Jam - Roy Ayers + Jam'][1]['ai_agenda'])
            assets = conn.execute("SELECT original_url, credit, rights_status FROM media_assets WHERE source='venue_ia_prova' ORDER BY original_url").fetchall()
            self.assertIn(('https://sala.test/img/offbeat-jam.jpg', 'Marula Café', 'authorized'), assets)
            calls = []
            def counting(*a, **k): calls.append(1); return answer(GOOD)(*a, **k)
            again = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=fetcher, requester=counting)
            self.assertTrue(again.get('unchanged')); self.assertEqual(calls, [])

    def test_multi_venue_agenda_keeps_only_configured_rooms(self):
        text, links = ai_agenda.clean('<p>Teatre Romea: La gavina, 22 octubre</p>', 'https://x.test/')
        agenda_salas = [{'name': 'Teatre Romea', 'address': 'C Hospital 51'}]
        ok, _ = ai_agenda.verify({'titulo': 'La gavina', 'sala': 'Teatre Romea', 'sesiones': [{'fecha': '2026-10-22', 'cita_fecha': '22 octubre'}]}, text, links, TODAY, agenda_salas)
        self.assertEqual(ok['sala']['name'], 'Teatre Romea')
        bad, _ = ai_agenda.verify({'titulo': 'La gavina', 'sala': 'Teatre Lliure', 'sesiones': [{'fecha': '2026-10-22', 'cita_fecha': '22 octubre'}]}, text, links, TODAY, agenda_salas)
        self.assertIsNone(bad)


if __name__ == '__main__':
    unittest.main()


class PeriodTests(unittest.TestCase):
    def test_running_show_and_future_period_pass(self):
        text, links = ai_agenda.clean('<article><header><h3>Impro Show</h3><p>Del dv. 19.04.24 al dc. 30.12.26</p></header></article>'
                                      '<article><header><h3>Gola</h3><p>Del 21/10/2026 al 15/11/2026</p></header></article>', 'https://x.test/')
        a, _ = ai_agenda.verify({'titulo': 'Impro Show', 'periodo': {'inicio': '2026-10-20', 'fin': '2026-12-30', 'cita': 'Del dv. 19.04.24 al dc. 30.12.26'}}, text, links, TODAY)
        self.assertEqual(a['periodo'], ('2024-04-19', '2026-12-30'))
        b, _ = ai_agenda.verify({'titulo': 'Gola', 'periodo': {'inicio': '2026-10-21', 'fin': '2026-11-15', 'cita': 'Del 21/10/2026 al 15/11/2026'}}, text, links, TODAY)
        self.assertEqual(b['periodo'], ('2026-10-21', '2026-11-15'))
        c, _ = ai_agenda.verify({'titulo': 'Gola', 'periodo': {'inicio': '2026-10-21', 'fin': '2026-12-15', 'cita': 'Del 21/10/2026 al 15/11/2026'}}, text, links, TODAY)
        self.assertIsNone(c)


class OtherPlaceTests(unittest.TestCase):
    def test_event_elsewhere_keeps_the_place_written_next_to_it(self):
        text, links = ai_agenda.clean('<p>Der Held vom Bahnhof Friedrichstraße</p><p>22.10.2026 | 20:00 Uhr</p><p>Institut français Barcelona, Barcelona</p>', 'https://x.test/')
        item = {'titulo': 'Der Held vom Bahnhof Friedrichstraße', 'sala': 'Institut français Barcelona', 'sesiones': [{'fecha': '2026-10-22', 'cita_fecha': '22.10.2026'}]}
        act, _ = ai_agenda.verify(item, text, links, TODAY, None, True)
        self.assertEqual(act['sala']['name'], 'Institut français Barcelona')
        self.assertIsNone(ai_agenda.verify({**item, 'sala': 'Cines Verdi'}, text, links, TODAY, None, True)[0])
        self.assertNotIn('sala', ai_agenda.verify(item, text, links, TODAY)[0])  # sin otros_lugares: la sala de la agenda
