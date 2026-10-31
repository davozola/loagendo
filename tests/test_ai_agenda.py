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


class DateFormatTests(unittest.TestCase):
    def test_day_ranges_and_catalan_abbreviations(self):
        self.assertEqual(ai_agenda._date_from_quote('2026-10-22', '22-26 octubre 2026 - Hangar', TODAY), dt.date(2026, 10, 22))
        self.assertEqual(ai_agenda._date_from_quote('2026-10-26', '22-26 octubre 2026 - Hangar', TODAY), dt.date(2026, 10, 26))
        self.assertEqual(ai_agenda._date_from_quote('2027-02-13', '13 febr. - 16 març', TODAY), dt.date(2027, 2, 13))
        self.assertEqual(ai_agenda._date_from_quote('2027-03-16', '13 febr. - 16 març', TODAY), dt.date(2027, 3, 16))
        self.assertEqual(ai_agenda._date_from_quote('2026-10-21', '21-10-2026', TODAY), dt.date(2026, 10, 21))

    def test_own_venue_named_in_other_places_mode_is_the_agenda_venue(self):
        text, links = ai_agenda.clean('<p>Café-philo 20 octubre 19:00</p>', 'https://x.test/')
        act, _ = ai_agenda.verify({'titulo': 'Café-philo', 'sala': 'Institut français de Barcelona', 'sesiones': [{'fecha': '2026-10-20', 'cita_fecha': '20 octubre'}]},
                                  text, links, TODAY, None, True, 'Institut français de Barcelona')
        self.assertNotIn('sala', act)


class CabecerasDeMesTests(unittest.TestCase):
    """29-10-2026, Antic Teatre: listado de todo el año con cabeceras de mes y días «Dv. 03»."""
    PAGE = '\n'.join(['Programació', 'Juliol 2026'] + [f'Dv. {d:02d}\nObra de juliol {d}' for d in range(1, 30)]
                     + ['Novembre 2026', 'Dj. 26', 'DVOYE', 'Dv. 27', 'DVOYE'])

    def test_cada_trozo_empieza_con_la_cabecera_vigente(self):
        parts = ai_agenda.chunks(self.PAGE, size=120)
        self.assertGreater(len(parts), 2)
        for part in parts[1:]:
            self.assertRegex(part.split('\n')[0], r'^(Juliol|Novembre) 2026$')
        for part in parts:   # los días de noviembre siempre llevan delante su cabecera
            if 'DVOYE' in part: self.assertLess(part.find('Novembre 2026'), part.find('DVOYE')); self.assertGreaterEqual(part.find('Novembre 2026'), 0)

    def test_sin_cabeceras_los_trozos_no_cambian(self):
        text = '\n'.join(f'Línia {i}' for i in range(60))
        self.assertEqual(''.join(ai_agenda.chunks(text, size=100)), text + '\n')

    def test_dia_de_la_semana_abreviado_tiene_que_cuadrar(self):
        today = dt.date(2026, 10, 29)
        self.assertIsNone(ai_agenda._date_from_quote('2026-11-03', 'Dv. 03', today))          # el 3-11-2026 es martes
        self.assertEqual(ai_agenda._date_from_quote('2026-11-03', 'Dm. 03', today), dt.date(2026, 11, 3))
        self.assertEqual(ai_agenda._date_from_quote('2026-11-04', 'Dx. 04', today), dt.date(2026, 11, 4))
        self.assertEqual(ai_agenda._date_from_quote('2026-11-26', 'Dj. 26', today), dt.date(2026, 11, 26))
        self.assertEqual(ai_agenda._date_from_quote('2026-11-12', '12 novembre', today), dt.date(2026, 11, 12))  # sin abreviatura, como antes


class FichasTests(unittest.TestCase):
    """30-10-2026, MNAC: «solo_fichas», reintento de HTTP 0 y actos en línea."""
    LIST = '<html><body><div>31/10/2026 <a href="/es/actividades/taller-a">Taller A</a></div><div>07/11/2026 <a href="/es/actividades/conferencia-b">Conferencia B</a></div></body></html>'
    FICHA_A = '<html><body><h1>Taller A</h1><p>Sábado 7 de noviembre de 2026, a las 16 h</p><p>Lugar: Sala Oval</p></body></html>'
    FICHA_B = '<html><body><h1>Conferencia B</h1><p>Lunes 16 de noviembre de 2026, a las 18.30 h</p><p>Lugar: Actividad en línea</p></body></html>'
    AG = {'slug': 'museu', 'name': 'Museu', 'type': 'culture', 'urls': ['https://m.test/es/actividades'],
          'seguir': {'patron': r'^https://m\.test/es/actividades/[^/?#]+$', 'max': 5, 'ficha': True, 'solo_fichas': True}}

    def setUp(self):
        self.calls = []; self.old_pause = ai_agenda.RETRY_PAUSE; ai_agenda.RETRY_PAUSE = 0

    def tearDown(self): ai_agenda.RETRY_PAUSE = self.old_pause

    def fetch(self, url, timeout):
        self.calls.append(url)
        if url.endswith('/actividades'):
            return (0, url, 'timeout') if self.calls.count(url) == 1 else (200, url, self.LIST)   # primer intento sin respuesta
        return 200, url, self.FICHA_A if url.endswith('taller-a') else self.FICHA_B

    def test_solo_fichas_reintento_y_en_linea(self):
        seen_pages = []
        def ask(method, url, key, body=None, timeout=60, raw=False):
            text = body['messages'][0]['content'] if isinstance(body['messages'][0]['content'], str) else json.dumps(body['messages'][0]['content'])
            seen_pages.append(text)
            if 'Taller A' in text and 'Sala Oval' in text:
                items = [{'titulo': 'Taller A', 'sesiones': [{'fecha': '2026-11-07', 'cita_fecha': 'Sábado 7 de noviembre de 2026', 'hora': '16:00', 'cita_hora': 'a las 16 h'}]}]
            elif 'Conferencia B' in text and 'en línea' in text:
                items = [{'titulo': 'Conferencia B', 'sesiones': [{'fecha': '2026-11-16', 'cita_fecha': 'Lunes 16 de noviembre de 2026', 'hora': '18:30', 'cita_hora': 'a las 18.30 h'}]}]
            else: items = [{'titulo': 'Taller A', 'sesiones': [{'fecha': '2026-10-31', 'cita_fecha': '31/10/2026'}]}]
            return {'content': [{'type': 'tool_use', 'name': 'actos', 'input': {'actos': items}}], 'usage': {}}
        res = ai_agenda.read_agenda(self.AG, TODAY, 'k', fetcher=self.fetch, requester=ask)
        self.assertEqual(self.calls.count('https://m.test/es/actividades'), 2)                 # reintento tras HTTP 0
        self.assertFalse(any('31/10/2026' in p for p in seen_pages))                            # el listado no va a la IA
        self.assertEqual([(a['titulo'], a['sesiones'], a['url']) for a in res['accepted']],
                         [('Taller A', [('2026-11-07', '16:00')], 'https://m.test/es/actividades/taller-a')])
        self.assertIn('acto en línea según su ficha', [w for r in res['rejected'] for w in r['why']])


class FichaReglasTests(unittest.TestCase):
    def test_otro_municipio_y_precio_general(self):
        page = '<h1>Jujol en Sant Joan Despí</h1><p>Martes 3 de noviembre de 2026, a las 10.30 h</p><p>Lugar: Sant Joan Despí</p>'
        text, links = ai_agenda.clean(page, 'https://m.test/a')
        item = {'titulo': 'Jujol en Sant Joan Despí', 'sesiones': [{'fecha': '2026-11-03', 'cita_fecha': 'Martes 3 de noviembre de 2026'}]}
        self.assertEqual(ai_agenda.verify(item, text, links, TODAY, whole_page=True), (None, ['acto fuera de Barcelona según su ficha']))
        page = '<h1>Visita X</h1><p>Martes 3 de noviembre de 2026, a las 10.30 h</p><p>Lugar: Museu Nacional</p><p>Precios: Precio Amics: 25 € Precio No Amics: 35 €</p>'
        text, links = ai_agenda.clean(page, 'https://m.test/b')
        item = {'titulo': 'Visita X', 'sesiones': [{'fecha': '2026-11-03', 'cita_fecha': 'Martes 3 de noviembre de 2026'}], 'precio': '25 €', 'cita_precio': 'Precio Amics: 25 €'}
        act, why = ai_agenda.verify(item, text, links, TODAY, whole_page=True)
        self.assertEqual((act['precio'], act['quotes']['price']), ('35 €', 'Precio No Amics: 35 €'))
        self.assertEqual(ai_agenda.verify(item, text, links, TODAY)[0]['precio'], '25 €')   # en un listado no se toca


class AjaxLoadMoreTests(unittest.TestCase):
    def test_hoy_unix_y_json_con_html(self):
        ag = {'slug': 'p62', 'name': 'Sala', 'urls': ['https://s.test/admin-ajax.php?meta_value={hoy_unix}&x={lunes+1}']}
        url = ai_agenda.expand_urls(ag, dt.date(2026, 10, 30))[0]
        self.assertIn('meta_value=1793318400&', url)          # 2026-10-30 00:00 UTC
        self.assertTrue(url.endswith('x=2026-10-27'))
        html = '<article class="event"><p>31 octubre 2026 - Dissabte</p><p>17:30 H — <strong>Sala Gran</strong></p><h3>Festival BOCA</h3></article>'
        self.assertEqual(ai_agenda.unwrap_html(json.dumps({'html': html, 'meta': {'postcount': 1}})), html)
        self.assertEqual(ai_agenda.unwrap_html('<html>x</html>'), '<html>x</html>')
        self.assertEqual(ai_agenda.unwrap_html('{"a": 1}'), '{"a": 1}')
