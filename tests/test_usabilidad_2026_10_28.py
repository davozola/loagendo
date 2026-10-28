"""Auditoría de usabilidad en móvil (David, 28-10-2026): orden por relevancia y diversidad con 10 por hora, Selección
contextual, Expos, «Fin de semana», precio y edad en la fila, duplicados, reclamos de venta, créditos y traducciones."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src import dedupe, titles, ai_extract, publish_static

ROOT = Path(__file__).resolve().parents[1]


class TitulosTests(unittest.TestCase):
    def test_reclamos_de_venta_fuera_del_titulo(self):
        self.assertEqual(titles.display_title('MARTES / TUESDAY at City Hall Club || INSIDE 86|| DOWNLOAD YOUR FREE PASS', 'musica'), 'MARTES / TUESDAY at City Hall Club · INSIDE 86')
        self.assertEqual(titles.display_title('FREE GUEST LIST * HOUSY (26th floor W Barcelona)', 'musica'), 'HOUSY (26th floor W Barcelona)')
        self.assertTrue(titles.is_promo('FREE GUEST LIST * HOUSY')); self.assertFalse(titles.is_promo('Jungle'))


class EdadTests(unittest.TestCase):
    def test_de_0_hasta_5(self):
        self.assertEqual(ai_extract.ages_by_rule('Twinkle', 'Concierto para bebés i pequeños de 0 hasta 5 años')[:2], (0, 5))
        self.assertEqual(ai_extract.ages_by_rule('x', 'per a infants de 0 fins a 5 anys')[:2], (0, 5))


class CreditoTests(unittest.TestCase):
    def test_la_regla_del_registro_no_es_el_credito(self):
        self.assertEqual(publish_static.credit_name('venue_x', {'attribution': 'Nombre del recinto, con enlace a su página'}), 'Web de la sala')
        self.assertEqual(publish_static.credit_name('opendatabcn_agenda', {'attribution': 'Ajuntament de Barcelona'}), 'Ajuntament de Barcelona')


class DuplicadosTests(unittest.TestCase):
    def db(self, rows):
        folder = tempfile.mkdtemp(); conn = sqlite3.connect(Path(folder) / 't.sqlite3')
        conn.execute('CREATE TABLE source_records (source TEXT, id TEXT, title TEXT, start_date TEXT, end_date TEXT, eligibility TEXT, raw_json TEXT)')
        conn.execute('CREATE TABLE source_venues (source TEXT, id TEXT, seq INTEGER, venue TEXT, lat REAL, lon REAL, address TEXT)')
        for s, i, t, a, b, v, lat, lon in rows:
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?)', (s, i, t, a, b, 'review', '{}'))
            conn.execute('INSERT INTO source_venues VALUES (?,?,0,?,?,?,?)', (s, i, v, lat, lon, ''))
        return conn

    def test_titulo_contenido_mismo_sitio_y_fechas(self):
        conn = self.db([('opendatabcn_agenda', '1', 'Òpera "Carmen", de Georges Bizet', '2099-10-28', '2099-10-28', 'Teatre Apolo', 41.3748, 2.1703),
                        ('venue_ia_teatre_apolo', '2', 'Ópera – Carmen', '2099-10-28', '2099-10-28', 'Teatre Apolo', None, None),
                        ('guiabcn', '3', 'Monòleg "Esto No Es Una Prueba", amb Galder Varas', '2099-10-28', '2099-10-31', 'Teatre Borràs', 41.3889, 2.1736),
                        ('venue_ia_balana', '4', 'Galder Varas', '2099-10-28', '2099-11-01', 'Teatre Borràs', None, None)])
        pairs = {frozenset(p) for p in dedupe.nested_pairs(conn)}
        self.assertIn(frozenset({'opendatabcn_agenda:1', 'venue_ia_teatre_apolo:2'}), pairs)
        self.assertIn(frozenset({'guiabcn:3', 'venue_ia_balana:4'}), pairs)

    def test_actividad_sobre_la_obra_no(self):
        conn = self.db([('generalitat', '1', 'Exposició "Vuit"', '2099-07-11', '2099-11-01', 'La Virreina Centre de la Imatge', 41.3825, 2.1717),
                        ('opendatabcn_agenda', '2', "Presentació del catàleg 'VUIT', amb Frederic Amat", '2099-10-27', '2099-10-27', 'La Virreina Centre de la Imatge', 41.3825, 2.1717),
                        ('opendatabcn_agenda', '3', "Concert d’inauguració de l’exposició 'Colors de vida'", '2099-11-26', '2099-11-26', 'Casal X', 41.40, 2.10),
                        ('generalitat', '4', "Exposició: 'Colors de vida'", '2099-11-26', '2099-12-12', 'Casal X', 41.40, 2.10)])
        self.assertEqual(dedupe.nested_pairs(conn), [])


class FestivalGeneralTests(unittest.TestCase):
    """28-10-2026 (David): la ficha general del mismo festival en dos fuentes es una («Asian Film Festival Barcelona» de la
    Generalitat y «14è Asian Film Festival Barcelona» de GuiaBCN, 22 oct–1 nov); ediciones distintas no se juntan."""
    def test_edicion(self):
        from src.dedupe import _edition
        self.assertEqual(_edition('14è Asian Film Festival Barcelona'), 14); self.assertEqual(_edition('Asian Film Festival Barcelona'), 0)
        self.assertEqual(_edition('4t Lens Dans Festival'), 4); self.assertEqual(_edition('Lens Dans #3 Festival'), 3)
        self.assertEqual(_edition('XXXIV Festival Internacional de Carilló'), 34); self.assertEqual(_edition('Mostra 3 de novembre'), 0)

    def test_ficha_general_suelta_se_une(self):
        import sqlite3
        from src import dedupe, festivals
        conn = sqlite3.connect(':memory:'); dedupe.initialize(conn)
        conn.execute("CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT,PRIMARY KEY(source,id))")
        conn.execute("CREATE TABLE IF NOT EXISTS source_venues (source TEXT, id TEXT, seq INTEGER, venue TEXT, address TEXT, lat REAL, lon REAL)")
        rows = [('generalitat', 'g1', 'Asian Film Festival Barcelona', '2026-10-22', '2026-11-01', 'Cinemes Girona'),
                ('guiabcn', 'b1', '14è Asian Film Festival Barcelona', '2026-10-22', '2026-11-01', 'Fundació Institut Confuci'),
                ('generalitat', 'g2', '4t Lens Dans Festival', '2026-11-04', '2026-11-14', 'Zumzeig'),
                ('venue_x', 'x1', 'Lens Dans #3 Festival', '2025-11-13', '2026-11-13', 'Nau Bostik')]
        for source, rid, title, start, end, venue in rows:
            conn.execute("INSERT INTO source_records (source, id, title, start_date, end_date, kind, eligibility, evidence_level, source_url, raw_sha256, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (source, rid, title, start, end, 'program', 'review', 'x', '', '', '{}'))
            conn.execute("INSERT INTO source_venues VALUES (?,?,0,?,?,?,?)", (source, rid, venue, '', None, None))
        festivals._CACHE.update(key=None, obj=None)
        pairs = dedupe.umbrella_pairs(conn)
        self.assertIn(('generalitat:g1', 'guiabcn:b1'), pairs)
        self.assertFalse(any('g2' in a or 'g2' in b for a, b in pairs))


class InEditTests(unittest.TestCase):
    """Piloto In-Edit (28-10-2026, David): la web oficial se lee como agenda con IA (páginas por día → fichas de película);
    cada sesión queda como acto del festival; la agenda deja de leerse cuando acaba."""
    def test_sesiones_con_festival(self):
        from src import ai_agenda
        agenda = {'slug': 'in_edit', 'name': 'Cinema Mooby Aribau', 'address': "Carrer d'Aribau 8-10", 'type': 'cinema', 'festival': {'slug': 'in-edit', 'name': 'In-Edit Barcelona'}}
        act = {'titulo': 'Broken English', 'sesiones': [('2026-10-29', '21:00')], 'url': 'https://es.in-edit.org/ca/docs/broken-english-3/', 'quotes': {}}
        recs = ai_agenda.records_for(agenda, [act], 'https://es.in-edit.org/ca/dia-25/29o-26-ca/', 'h', 'm')
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]['raw']['item']['x_festival'], {'slug': 'in-edit', 'name': 'In-Edit Barcelona'})
        self.assertEqual(recs[0]['start'], '2026-10-29'); self.assertEqual(recs[0]['time_text'], '21:00')
        self.assertEqual(recs[0]['venues'][0]['name'], 'Cinema Mooby Aribau')

    def test_ficha_de_pelicula_sin_cercania(self):
        import datetime as dt
        from src import ai_agenda
        from src.ai_extract import times_in
        text = "BROKEN ENGLISH " + "sinopsi " * 300 + " 29 d'octubre, 19.30 h VOSC LP"
        item = {'titulo': 'Broken English', 'sesiones': [{'fecha': '2026-10-29', 'cita_fecha': "29 d'octubre", 'hora': '19:30', 'cita_hora': '19.30 h'}]}
        self.assertIsNone(ai_agenda.verify(item, text, [], dt.date(2026, 10, 28))[0])
        act, _ = ai_agenda.verify(item, text, [], dt.date(2026, 10, 28), whole_page=True)
        self.assertEqual(act['sesiones'], [('2026-10-29', '19:30')])
        self.assertIn('18:30', times_in('26 October, 6:30 p.m.'))

    def test_festival_en_la_proyeccion(self):
        from mvp import catalog
        pr = catalog.project_raw('venue_ia_in_edit', 'x', 'Broken English', '2026-10-29', '2026-10-29', 'single', '',
                                 {'item': {'@type': 'Event', 'name': 'Broken English', 'x_festival': {'slug': 'in-edit', 'name': 'In-Edit Barcelona'}}, 'loagendo': {}})
        self.assertEqual(pr['x_festival']['slug'], 'in-edit')

    def test_config(self):
        from src.ai_agenda import load_agendas
        a = next(x for x in load_agendas() if x['slug'] == 'in_edit')
        self.assertFalse(a['activa']); self.assertEqual(a['hasta'], '2026-11-08')  # 28-10 11:30: sustituida por Codetickets; self.assertEqual(len(a['urls']), 11)
        self.assertEqual(a['festival']['slug'], 'in-edit'); self.assertIn('/docs/', a['seguir']['patron']); self.assertTrue(a['seguir']['ficha'])


class WebTests(unittest.TestCase):
    def test_orden_por_hora_seleccion_y_periodos(self):
        js = (ROOT / 'static' / 'public.js').read_text(); html = (ROOT / 'static' / 'index.html').read_text()
        for text in ('HOUR_CAP = 10', 'function rankDiverse', 'data-hourfold', "L('Ver menos'", "pickRange: 'auto'", 'function priceShort', 'venue_tier: c.vt', 'seriesShort', 'expoScore'):
            self.assertIn(text, js)
        self.assertIn('data-period="finde"', html)

    def test_agenda_cronologica_sin_ahora_ni_horario_amplio(self):
        """28-10-2026 (David): sin grupo «Ahora»; hoy empieza en la hora actual con lo anterior plegado arriba; un horario de
        apertura no es una sesión (parades de castanyes fuera); total en cada cabecera de hora; etiqueta de festival pulsable
        con filtro que se mantiene al cambiar de día; el festival de abono sale a su hora de apertura, no a la de la primera sesión."""
        js = (ROOT / 'static' / 'public.js').read_text()
        for text in ("const hourKey = e => String(Math.floor(e._st.sort / 60))",
                     "${h} h`} · ${plans(n)}`", "function goFest(d)", "p.fest && base.festival?.slug !== p.fest",
                     "data-fest=\"${esc(slug)}\"", "program_days: c.pn || null", "if (state.fest) { p.set('fest', state.fest)"):
            self.assertIn(text, js)
        for text in ("=== 'now'", "id=\"ag-now\"", 'function openBlock', "const pf = e.program_first?.[day];\n  if (pf) return", "e._st.state === 'started' || e._st.state === 'open')) ? 'now'"):
            self.assertNotIn(text, js)
        self.assertNotIn("timeline = [...timeline, ...openList", js)
        py = (ROOT / 'src' / 'publish_static.py').read_text()
        self.assertIn("out['pn'] = days", py)

    def test_en_curso_y_durante_el_dia(self):
        """28-10-2026 (David, 08:28): lo empezado con hora de fin fiable que aún no ha llegado es «En curso», no anterior; un acto de
        un día con franja larga es una sesión a su hora; el horario amplio fechado (hasta 6 semanas) va a un bloque reducido
        «Durante el día» (5 filas); lo permanente o de meses sigue sin verse."""
        js = (ROOT / 'static' / 'public.js').read_text()
        for text in ("const DAY_PLAN_MAX = 42", "const isStrongWide = ", "const REMIND_AT = 15 * 60, REMIND_SHOW = 3", "const WIDE_EVENT = ", "WIDE_EVENT.test(t)",
                     "live && m.now.min >= REMIND_AT ? []", "e._st.state === 'open' && !isExhibit(e)",
                     "function remindLine(e)", "r.close - REMIND_AT >= 120", "(isWideRange(range) && isOpenFormat(e))", "e._st.state === 'past' || e._st.state === 'started')) s.past.push(e)"):
            self.assertIn(text, js)
        # 28-10-2026 (10:19, David): sin «Anteriores» ni bloque «Durante el día»; horario amplio fuerte a su hora de apertura
        # y recordatorio a las 15:00 que no cuenta ni ocupa sitio.
        for text in ('function dayBlock', "L('Anteriores: ya empezadas o acabadas hoy'", 'id="ag-dayblock"', 'id="ag-ongoing"', "state: 'ongoing'", "foldHtml('past'", 'REMIND_MAX'):
            self.assertNotIn(text, js)


class MonumentalTests(unittest.TestCase):
    """28-10-2026 (David): «Monumental Kids» (12–17 h) y «Monumental Club Halloween» (15–23 h) son dos propuestas."""
    def test_la_marca_de_la_fuente_no_decide_sola(self):
        from src import taxonomy
        base = {'title': 'Monumental Club Halloween', 'family_audience': True, 'age_max': None, 'venue_names': ['La Monumental'], 'source': 'opendatabcn_agenda'}
        self.assertNotIn('familia', taxonomy.channels({**base, 'source_text': "I a cabina, HAL9000, Síria DJ i Àsia Knox."}, 'musica'))
        self.assertIn('familia', taxonomy.channels({**base, 'title': "Taller 'Tastet de danses'", 'source_text': 'agenda octubre 2026 dl dt dc dj dv ds dg 1 2 3'}, 'talleres'))
        self.assertIn('familia', taxonomy.channels({**base, 'title': 'Monumental Kids Halloween', 'source_text': 'DJ per a nens'}, 'musica'))

    def test_sesion_infantil_y_sesion_de_club_no_se_juntan(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE source_records (source TEXT, id TEXT, title TEXT)')
        conn.executemany('INSERT INTO source_records VALUES (?,?,?)', [('a', '1', 'Monumental Club Halloween'), ('b', '2', 'Monumental Kids Halloween'),
                         ('c', '3', 'Espectacle infantil "Baila a lo loco"'), ('d', '4', 'Baila a lo loco – Tour'), ('e', '5', "'Tardes en família': Taller 'Fanalets'"), ('f', '6', "Taller 'Fanalets'")])
        self.assertTrue(dedupe._distinct_sessions(conn, 'a:1', 'b:2'))
        self.assertFalse(dedupe._distinct_sessions(conn, 'c:3', 'd:4'))
        self.assertFalse(dedupe._distinct_sessions(conn, 'e:5', 'f:6'))


class SeleccionPorTipoTests(unittest.TestCase):
    def test_por_categoria_tres_o_mas_una_por_obra_sin_promos(self):
        from unittest import mock
        ev = lambda i, cat, title, **kw: {'public_category': cat, 'title': title, 'series': '', 'media': [{'u': 'x'}], 'has_description': True, 'key': f's:{i}', **kw}
        items = [ev(1, 'musica', 'A'), ev(2, 'musica', 'B'), ev(3, 'musica', 'B'), ev(4, 'musica', 'C'), ev(5, 'musica', 'D', is_promo=True),
                 ev(6, 'cine', 'X'), ev(7, 'cine', 'Y'), ev(8, 'escena', 'Z', media=[], has_description=False)]
        with mock.patch.object(publish_static, 'compact', lambda e, images, hidden=frozenset(): e['key']):
            out = publish_static.picks_by_category(items, None)
        self.assertEqual(out, {'musica': ['s:1', 's:2', 's:4']})   # B repetida, D promoción; cine solo 2; escena sin imagen ni texto

    def test_selection_carrusel_y_tipos_en_la_web(self):
        js = (ROOT / 'static' / 'public.js').read_text(encoding='utf-8')
        html = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        self.assertIn('/data/picks/', js); self.assertIn('data-pickcat', js); self.assertNotIn("'pick-large'", js)
        self.assertIn('id="pickCats"', html); self.assertIn('id="pickNext"', html)

    def test_expos_del_ranking_una_por_espacio(self):
        from unittest import mock
        ev = lambda k, v, **kw: {'key': k, 'venue_names': [v], 'media': [{'u': 'x'}], 'has_description': True, **kw}
        by_key = {'a': ev('a', 'MACBA'), 'b': ev('b', 'MACBA'), 'c': ev('c', 'CCCB'), 'd': ev('d', 'Miró', media=[], has_description=False), 'e': ev('e', 'Fundació Tàpies')}
        ranks = {'a': 5, 'b': 4, 'c': 3, 'd': 2, 'e': 1}
        with mock.patch.object(publish_static, 'compact', lambda e, images, hidden=frozenset(): e['key']):
            self.assertEqual(publish_static.expo_picks(by_key, ranks, None), ['a', 'c', 'e'])
