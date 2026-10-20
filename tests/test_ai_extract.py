"""Extracción con IA con cita comprobada, franjas de edad y aplicación a la ficha (20-10-2026)."""
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import ai_assist, ai_extract
from src.pipeline import connect

TEXT = "Dissabte 24 d'octubre a les 19 h. Activitat gratuïta amb inscripció prèvia. Per a infants de 3 a 6 anys, a la plaça del Sol."


class VerifyTests(unittest.TestCase):
    def test_only_quoted_and_readable_facts_survive(self):
        answer = {'sesiones': [{'fecha': '2026-10-24', 'inicio': '19:00', 'cita': "Dissabte 24 d'octubre a les 19 h"},
                               {'fecha': '2026-10-25', 'inicio': '18:00', 'cita': 'diumenge 25 a les 18 h'},          # cita inventada
                               {'fecha': '2026-10-24', 'inicio': '20:00', 'cita': "Dissabte 24 d'octubre a les 19 h"}],  # hora que no está en la cita
                  'precio': {'gratis': True, 'cita': 'Activitat gratuïta'},
                  'inscripcion': {'requerida': True, 'cita': 'amb inscripció prèvia'},
                  'familia': {'es': True, 'cita': 'Per a infants de 3 a 6 anys'},
                  'aire_libre': {'es': True, 'cita': 'a la plaça del Sol'},
                  'edades': {'min': 3, 'max': 6, 'cita': 'de 3 a 6 anys'}}
        kept, dropped = ai_extract.verify(answer, TEXT, '2026-10-20', '2026-10-30')
        self.assertEqual([(s['date'], s['time']) for s in kept['sessions']], [('2026-10-24', '19:00')])
        self.assertEqual(len(dropped), 2)
        self.assertEqual((kept['price']['label'], kept['registration']['required'], kept['ages']['min'], kept['ages']['max']), ('Gratis', True, 3, 6))
        self.assertIn('family', kept); self.assertIn('outdoor', kept)
        # Precio que no aparece en la cita, y fecha fuera de la ficha.
        kept, _ = ai_extract.verify({'precio': {'min': 12, 'cita': 'Activitat gratuïta'}, 'sesiones': [{'fecha': '2026-11-24', 'inicio': '19:00', 'cita': "Dissabte 24 d'octubre a les 19 h"}]}, TEXT, '2026-10-20', '2026-10-30')
        self.assertEqual(kept, {})

    def test_times_and_ages_by_rule(self):
        self.assertEqual(ai_extract.times_in('De 10 a 13 h i de 16 a 19 h'), {'10:00', '13:00', '16:00', '19:00'})
        self.assertEqual(ai_extract.times_in("el 19 d'octubre"), set())
        self.assertEqual(ai_extract.ages_by_rule("Taller familiar (de 3 a 6 anys)")[:2], (3, 6))
        self.assertEqual(ai_extract.ages_by_rule('Concert', "una banda amb més de 30 anys d'història"), None)  # no es una edad de público
        self.assertEqual(ai_extract.ages_by_rule('Música per a nadons de 18 a 36 mesos')[:2], (0, 3))
        self.assertEqual(ai_extract.ages_by_rule('Concert +18')[:2], (18, None))

    def test_a_price_with_an_amount_is_not_free_even_if_it_mentions_free_entry(self):
        from mvp.catalog import is_free
        self.assertFalse(is_free('Preus: des de 10 € Les nenes i els nens menors de 2 anys tenen entrada gratuïta', ''))
        self.assertTrue(is_free('Activitat gratuïta', ''))
        self.assertTrue(is_free('', 'Sí'))


class ApplyTests(unittest.TestCase):
    def test_extracted_time_price_and_ages_fill_gaps_with_their_quotes(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn); ai_assist.initialize(conn)
            raw = {'name': 'Contes a la plaça', 'body': TEXT, 'addresses': [{'address_name': 'Plaça del Sol', 'district_name': 'Gràcia'}], 'loagendo': {}}
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '9', 'Contes a la plaça', '2026-10-24', '2026-10-24', 'single', 'review', 'x', '', 'h', json.dumps(raw)))
            conn.commit(); catalog.invalidate_cache()
            ev = catalog.event_detail(conn, 'opendatabcn_agenda', '9')
            self.assertEqual((ev['age_min'], ev['age_max'], ev['age_source']), (3, 6, 'fuente'))  # la regla la ve sin IA
            self.assertIn('familia', ev['channels'])
            self.assertIsNone(ev['time'])
            answer = {'sesiones': [{'fecha': '2026-10-24', 'inicio': '19:00', 'cita': "Dissabte 24 d'octubre a les 19 h"}], 'precio': {'gratis': True, 'cita': 'Activitat gratuïta'}}
            parsed = ai_assist._parse_datos(answer, ai_extract.payload(ev))
            ai_assist._store(conn, 'datos', [('opendatabcn_agenda:9', ai_extract.payload(ev))], [(0, *parsed)], 'm', 'b1')
            catalog.invalidate_cache()
            ev = catalog.event_detail(conn, 'opendatabcn_agenda', '9')
            self.assertEqual((ev['time'], ev['time_source'], ev['ai_quotes']['time']), ('19:00', 'ia_texto', "Dissabte 24 d'octubre a les 19 h"))
            self.assertTrue(ev['is_free'])


if __name__ == '__main__':
    unittest.main()


class DescribeTests(unittest.TestCase):
    def test_grounding_check_rejects_invented_names_numbers_and_promotion(self):
        from src import ai_describe
        p = {'titulo': "Concert 'Andrea Motis + Yamandu Costa'", 'categoria': 'Música y vida nocturna', 'sala': 'Palau de la Música Catalana', 'barrio': 'Ciutat Vella',
             'artistas': ['Andrea Motis', 'Yamandu Costa'], 'texto': 'La trompetista Andrea Motis comparteix escenari amb el guitarrista brasiler Yamandu Costa.'}
        self.assertEqual(ai_describe.check('La trompetista Andrea Motis comparte escenario con el guitarrista brasileño Yamandu Costa.', p), [])
        problems = ai_describe.check('Un concierto imprescindible de Andrea Motis con Hamilton de Holanda en 2026.', p)
        self.assertTrue(any('promocional' in x for x in problems) and any('2026' in x for x in problems) and any('hamilton' in x for x in problems))
        answer, confidence, _ = ai_describe.parse({'es': 'La trompetista Andrea Motis toca con Yamandu Costa.', 'ca': 'La trompetista Andrea Motis toca amb Yamandu Costa.'}, p)
        self.assertEqual((json.loads(answer)['ok'], confidence), (True, 1.0))
        answer, _, reason = ai_describe.parse({'es': 'Andrea Motis con Hamilton de Holanda.', 'ca': 'Andrea Motis amb Yamandu Costa.'}, p)
        self.assertFalse(json.loads(answer)['ok']); self.assertIn('hamilton', reason)

    def test_summary_is_hidden_from_the_public_site_until_enabled(self):
        from src import publish_static, ai_describe
        from unittest import mock
        detail = {'ai_summary': {'es': 'x', 'ca': 'y', 'model': 'm'}, 'media': [], 'links': [], 'hours_by_day': {}, 'notes_by_day': {}}
        with mock.patch.object(ai_describe, 'public_enabled', return_value=False):
            self.assertIsNone(publish_static.public_detail(detail, None)['ai_summary'])
        with mock.patch.object(ai_describe, 'public_enabled', return_value=True):
            self.assertEqual(publish_static.public_detail(detail, None)['ai_summary']['es'], 'x')


class NeedsTests(unittest.TestCase):
    def test_only_asks_what_the_source_lacks(self):
        from src.ai_extract import needs
        text = 'x' * 60
        one_day = {'start': '2026-10-22', 'end': '2026-10-22', 'source_text': text}
        self.assertTrue(needs(one_day))                                                         # sin hora ni precio
        self.assertFalse(needs({**one_day, 'time': '19:00', 'time_source': 'official_detail_page', 'price_label': '10 €'}))
        self.assertTrue(needs({**one_day, 'time': '19:00', 'time_source': 'ia_texto', 'price_label': '10 €'}))  # la hora la puso la IA: se mantiene
        expo = {'start': '2026-10-01', 'end': '2027-01-10', 'source_text': text, 'is_free': True}
        self.assertFalse(needs(expo))                                                           # exposición gratis: nada que pedir
        self.assertFalse(needs({**one_day, 'source_text': 'corto'}))
