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


class WebTests(unittest.TestCase):
    def test_orden_por_hora_seleccion_y_periodos(self):
        js = (ROOT / 'static' / 'public.js').read_text(); html = (ROOT / 'static' / 'index.html').read_text()
        for text in ('HOUR_CAP = 10', 'function rankDiverse', 'data-hourfold', "L('Ver menos'", "pickRange: 'auto'", 'function priceShort', 'venue_tier: c.vt', 'seriesShort', 'expoScore'):
            self.assertIn(text, js)
        self.assertIn('data-period="finde"', html)


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
