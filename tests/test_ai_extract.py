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
