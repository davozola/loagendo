"""Recuperación de horas (28-10-2026, David, tras la auditoría de actividades sin hora)."""
import datetime as dt
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 10, 28)


class AgendaIATests(unittest.TestCase):
    def test_numeros_de_elementos_distintos_no_se_pegan(self):
        from src import ai_agenda
        text, _ = ai_agenda.clean('<div><span>02/11/2026</span><span>19:00 h</span></div><p><b>B</b>arcelona</p>', 'https://x.test/')
        self.assertIn('02/11/2026 19:00 h', text); self.assertIn('Barcelona', text)

    def test_hora_pegada_a_la_fecha_y_enlace_del_acto(self):
        from src import ai_agenda
        html = ('<a href="/cinema/films/animals-bestials/"><h2>Animals bestials</h2><div>Ds 7.11.26 <span>(17:00)</span></div></a>'
                '<a href="/cinema/films/krakatoa/"><h2>Krakatoa</h2><div>Carlos Casas</div><div>Ds 7.11.26 <span>(19:00)</span>*</div></a>')
        text, links = ai_agenda.clean(html, 'https://zumzeigcine.coop/cinema/sessions/')
        act, why = ai_agenda.verify({'titulo': 'Krakatoa', 'enlace': 'L1', 'sesiones': [{'fecha': '2026-11-07', 'cita_fecha': 'Ds 7.11.26'}]}, text, links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '19:00')])
        self.assertEqual(act['url'], 'https://zumzeigcine.coop/cinema/films/krakatoa/')
        self.assertIn('(19:00)', act['quotes']['time'])

    def test_hora_equivocada_de_la_ia_no_se_sustituye(self):
        from src import ai_agenda
        text, links = ai_agenda.clean('<p>Krakatoa</p><p>Ds 7.11.26 (19:00)</p>', 'https://x.test/')
        act, _ = ai_agenda.verify({'titulo': 'Krakatoa', 'sesiones': [{'fecha': '2026-11-07', 'cita_fecha': 'Ds 7.11.26', 'hora': '21:00', 'cita_hora': '21:00'}]}, text, links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '')])


class PaginaDelActoTests(unittest.TestCase):
    def page(self, body, title):
        return lambda u, t: (200, u, f'<html><title>{title}</title><body>{body}</body></html>')

    def test_una_franja_y_madrugada(self):
        from src.official_dates import read_page
        f = self.page('<h1>THE UPSESSIONS</h1><p>00</p><p>hores</p><p>Data</p><p>20:00 - 23:30</p>', 'THE UPSESSIONS')
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-25', '2026-11-25', f, 5)['times'], {'2026-11-25': '20:00'})
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-13', '2026-11-14', f, 5)['times'], {'2026-11-13': '20:00'})
        f2 = self.page('<h1>THE UPSESSIONS</h1><p>Portes 19:00</p><p>20:00 - 23:30</p>', 'THE UPSESSIONS')
        self.assertEqual(read_page('https://ladeskomunal.coop/agenda/the-upsessions/', 'THE UPSESSIONS', '2026-11-25', '2026-11-25', f2, 5)['times'], {})

    def test_horaris_tras_la_sinopsis_y_excepciones(self):
        from src.official_dates import read_page
        from src.guia_schedule import labeled_schedule
        f = self.page('<h1>Guillermotta</h1><p>' + 'sinopsi ' * 400 + '</p><p>HORARIS:</p><p>Dilluns a les 20h</p><p>(9 de novembre no hi ha funció)</p>', 'Guillermotta')
        ex = read_page('https://elmalda.cat/espectacle/guillermotta-5/', 'Guillermotta', '2026-10-19', '2026-11-23', f, 5)['excerpt']
        self.assertEqual(sorted(labeled_schedule(ex, '2026-10-19', '2026-11-23')), ['2026-10-19', '2026-10-26', '2026-11-02', '2026-11-16', '2026-11-23'])
        self.assertEqual(labeled_schedule("X\nHORARIS:\nDilluns a les 20h\nExcepte festius", '2026-10-19', '2026-11-23'), {})
        self.assertEqual(labeled_schedule("X\nHORARIS:\nDe dimarts a dissabte a les 20h.\nDiumenge a les 12h.", '2026-11-01', '2026-11-03'),
                         {'2026-11-01': '12:00', '2026-11-03': '20:00'})


class HigieneTests(unittest.TestCase):
    def test_prueba_y_fuera_de_barcelona(self):
        from src.taxonomy import hygiene_exclusion
        self.assertEqual(hygiene_exclusion({'title': 'Test 11068686 case', 'source': 'venue_ticketmaster_es'})['method'], 'ficha_de_prueba')
        self.assertEqual(hygiene_exclusion({'title': 'Castanyada Rock 2026', 'source': 'venue_songkick', 'venue_names': ['Montmeló, Spain']})['method'], 'fuera_de_barcelona')
        self.assertIsNone(hygiene_exclusion({'title': 'Allie X', 'source': 'venue_songkick', 'venue_names': ['La Nau']}))
        self.assertIsNone(hygiene_exclusion({'title': 'Testament en concert', 'source': 'venue_dice'}))

    def test_dj_repetido_de_songkick(self):
        from src.publish_static import songkick_repeats
        ev = lambda k, t, v, time=None: {'key': k, 'source': 'venue_songkick', 'title': t, 'venue_names': [v], 'occurrences': [{'date': '2026-11-03', 'time': time}], 'time': time}
        events = [ev('a', 'Hal9000', 'Jamboree'), ev('b', 'Hal9000', 'Safari'), ev('c', 'Hal9000', 'Arena'), ev('d', 'Hal9000', 'Monumental', '23:00'), ev('e', 'Allie X', 'La Nau')]
        self.assertEqual(songkick_repeats(events), {'a', 'b', 'c'})


class WebTests(unittest.TestCase):
    def test_horario_amplio_por_el_titulo_no_por_el_recinto(self):
        js = (ROOT / 'static' / 'public.js').read_text()
        self.assertNotIn('WIDE_SKIP_VENUE', js); self.assertIn("const WIDE_EVENT_WORD = ", js)
        self.assertNotIn("e.format !== 'course' && e.format !== 'workshop' && isDayPlan", js)

    def test_conflicto_resuelto_por_la_sala(self):
        src = (ROOT / 'mvp' / 'catalog.py').read_text()
        self.assertIn("same=lambda t:'00:00' if t=='23:59' else t", src); self.assertIn("o['evidence_field']='sala'", src)


class CodeticketsTests(unittest.TestCase):
    def test_sesiones_sin_packs_con_sala_y_precio(self):
        import json
        from src.venue_feeds import codetickets_nodes, record_from_jsonld
        ent = {'id': 814, 'canalId': 4011}
        evs = [{'nombre': 'Gracias Botero + Botero', 'fechaInicial': '2026-11-26T17:15:00.000+01:00', 'recinto': 'MOOBY Bosque - Sala 3', 'recintoDireccion': 'Rambla de Prat, 16, Gràcia, Barcelona',
                'precioDesde': 10, 'hayPrecios': True, 'urlSale': 'https://www.codetickets.com/portal/festivaldart/online/37952', 'sesiones': '[]'},
               {'nombre': 'Pack 4', 'fechaInicial': '2026-10-29T00:00:00.000+01:00', 'recinto': 'Festival In-Edit', 'sesiones': []},
               {'nombre': 'Out of the Picture (VOSC)', 'recinto': 'Centre Cívic Casa Elizalde', 'urlSale': 'u', 'precioDesde': 0,
                'sesiones': [{'fechaInicial': '2026-11-19T19:00:00.000+01:00', 'recinto': 'Centre Cívic Casa Elizalde'}]}]
        def fetcher(url, timeout):
            return 200, url, json.dumps(ent if '/entidad/' in url else evs)
        venue = {'slug': 'dart_festival', 'name': 'DART Festival', 'type': 'festival', 'category': 'Cine y audiovisual',
                 'feed': {'kind': 'codetickets', 'entidad': 'festivaldart', 'url': 'https://www.codetickets.com/portal/festivaldart/online', 'festival': {'slug': 'dart', 'name': 'DART Festival'}}}
        nodes, _ = codetickets_nodes(venue, fetcher)
        self.assertEqual([n['name'] for _, n in nodes], ['Gracias Botero + Botero', 'Out of the Picture (VOSC)'])
        n = nodes[0][1]
        self.assertEqual((n['startDate'], n['location']['name'], n['x_room'], n['offers']['price']), ('2026-11-26T17:15', 'MOOBY Bosque', 'MOOBY Bosque - Sala 3', '10'))
        rec = record_from_jsonld(venue, n, nodes[0][0])
        self.assertEqual((rec['start'], rec['time_text'], rec['eligibility'] != 'exclude'), ('2026-11-26', '17:15', True))
        self.assertEqual(rec['raw']['item']['x_festival']['slug'], 'dart')


class ParteTests(unittest.TestCase):
    def test_mismo_dia_mismo_sitio_titulos_distintos(self):
        import sqlite3
        from src import dedupe
        conn = sqlite3.connect(':memory:')
        conn.executescript("""CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT);
            CREATE TABLE source_venues(source TEXT,id TEXT,seq INTEGER,venue TEXT,address TEXT,lat REAL,lon REAL);
            CREATE TABLE candidate_occurrences(source TEXT,id TEXT,local_date TEXT,local_time TEXT);""")
        rows = [('opendatabcn_agenda', '1', "Concert \"Hermeto's Mothership'", 'Jamboree', '19:00'),
                ('venue_jamboree', '2', 'Hermeto’s Mothership – A 100% Hermeto Pascoal tribute by his band', 'Jamboree Jazz Club', '19:00'),
                ('web_centres_civics', '3', 'Documental del mes: Les culpables', 'CC La Casa Elizalde, Auditori Sant Martí, CC Vil·la Urània i CC Tomasa Cuevas', ''),
                ('guiabcn', '4', 'Documental "Les Culpables"', 'Centre Cívic Tomasa Cuevas - Les Corts', ''),
                ('guiabcn', '5', 'Concert "Jamboree Jazz"', 'Jamboree 3', '')]
        for s, i, t, v, h in rows:
            conn.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)", (s, i, t, '2026-11-01', '2026-11-01', 'single', 'review', '', '', '', '{}'))
            conn.execute("INSERT INTO source_venues VALUES (?,?,0,?,?,?,?)", (s, i, v, '', None, None))
            if h: conn.execute("INSERT INTO candidate_occurrences VALUES (?,?,?,?)", (s, i, '2026-11-01', h))
        import datetime as _dt
        pairs = dedupe.same_day_pairs(conn, _dt.date(2026, 10, 28))
        self.assertEqual(pairs, [('opendatabcn_agenda:1', 'venue_jamboree:2')])

    def test_mismo_dia_nombre_al_principio_y_fiesta_en_el_mismo_sitio(self):
        from src.dedupe import same_day_item, same_day_match
        a = same_day_item('venue_xceed', '1', 'NEO Elegance - Halloween: Afrobeats, Hip Hop, RnB, Afrohouse | Mua Mua', 'SEASEACLUB', 41.41371, 2.22914, '23:00')
        b = same_day_item('venue_dice', '2', 'NEO Elegance - Halloween Masquerade', 'SEASEACLUB', 41.4137558, 2.2292604, '23:00')
        self.assertTrue(same_day_match(a, b))
        c = same_day_item('venue_dice', '3', 'NEO Elegance - Halloween Masquerade', 'SEASEACLUB', 41.4137558, 2.2292604, '01:00')
        self.assertFalse(same_day_match(a, c))   # otra hora: otra sesión
        g = same_day_item('guiabcn', '4', 'Tots Sants 2026: Castanyada a la Sedeta', 'Centre Cívic La Sedeta', 41.4055765, 2.1676875, '')
        o = same_day_item('opendatabcn_agenda', '5', 'Festa de la Castanyada, a la Plaça La Sedeta', 'Plaça la Sedeta', 41.4055247, 2.1675071, '17:00')
        self.assertTrue(same_day_match(g, o))
        far = same_day_item('opendatabcn_agenda', '6', 'Castanyada', 'Plaça la Sedeta', 41.4065, 2.1690, '17:00')
        self.assertFalse(same_day_match(g, far))   # solo la fiesta en común: a menos de 50 m
        self.assertIsNone(same_day_item('guiabcn', '7', 'Tots Sants 2026: Castaween Beats', 'Ruta pels carrers del Guinardó', None, None, ''))

    def test_proceso_interrumpido_es_fallo_suelto(self):
        from src.daily_report import triage
        self.assertEqual(triage('JOB', 'Proceso interrumpido antes de finalizar')[0], 'suelto')

    def test_conector_solo_se_prueba_antes_de_conectar(self):
        from src import festival_finder as ff
        auto = {'slug': 'fest_x', 'feed': {'kind': 'tribe_rest', 'url': 'https://x.test/wp-json/tribe/events/v1/events',
                                           'festival': {'slug': 'x', 'name': 'X'}, 'desde': '2026-10-16', 'hasta': '2026-10-29'}}
        import unittest.mock as m
        with m.patch('src.venue_feeds.tribe_rest_nodes', return_value=([('u', {'startDate': '2026-12-01'})], 1)):
            self.assertFalse(ff.trial(auto, None))
        with m.patch('src.venue_feeds.tribe_rest_nodes', return_value=([('u', {'startDate': '2026-10-20T19:00'})], 1)):
            self.assertTrue(ff.trial(auto, None))
        self.assertTrue(ff.trial({'feed': {}}, None))

    def test_avisos_de_fecha_una_vez(self):
        import tempfile, datetime as _dt
        from src.daily_report import _mark_new_dates
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'f.json'; item = lambda: [{'source': 's', 'id': '1', 'quote': "dissabte 30 d'octubre"}]
            self.assertTrue(_mark_new_dates(item(), _dt.date(2026, 10, 28), p)[0]['new'])
            self.assertFalse(_mark_new_dates(item(), _dt.date(2026, 10, 29), p)[0]['new'])

    def test_pausa_y_descartadas_no_avisan(self):
        import json
        a = {x['slug']: x for x in json.loads((ROOT / 'config' / 'agendas_ia.json').read_text())['agendas']}
        self.assertTrue(a['23robadors']['descartada']); self.assertEqual(a['tradicionarius']['pausa_hasta'], '2026-11-04')
        v = {x['slug']: x for x in json.loads((ROOT / 'config' / 'venues.json').read_text())['venues']}
        self.assertFalse(v['cinemes_girona']['enabled']); self.assertFalse(v['verdi']['enabled'])

    def test_mismo_dia_titulo_en_dos_idiomas(self):
        from src.dedupe import same_day_item, same_day_match
        a = same_day_item('web_cccb', '1', 'Fotoescrituras', 'CCCB', 41.3837, 2.1668, '18:00')
        b = same_day_item('opendatabcn_agenda', '2', "Debat 'Fotoescriptures. Literatura i fotografia, 200 anys després'", 'Centre de Cultura Contemporània de Barcelona', 41.3838, 2.1667, '18:00')
        self.assertTrue(same_day_match(a, b))

    def test_mismo_ponente_formatos_distintos_no_se_funden(self):
        from src.dedupe import same_day_item, same_day_match
        sem = same_day_item('web_cccb', '1', 'Seminario con Bonnie Honig', 'CCCB', None, None, '10:00')
        conf = same_day_item('web_cccb', '2', 'Bonnie Honig', 'CCCB', None, None, '18:30')
        g_sem = same_day_item('guiabcn', '3', "Seminari 'Hipòlit, a la inversa', amb Bonnie Honig", 'Centre de Cultura Contemporània de Barcelona', 41.3838, 2.1667, '')
        g_conf = same_day_item('guiabcn', '4', "Conferència 'Riure davant del desastre', amb Bonnie Honig", 'Centre de Cultura Contemporània de Barcelona', 41.3838, 2.1667, '18:30')
        self.assertTrue(same_day_match(sem, g_sem)); self.assertTrue(same_day_match(conf, g_conf))
        self.assertFalse(same_day_match(sem, g_conf)); self.assertFalse(same_day_match(conf, g_sem))
