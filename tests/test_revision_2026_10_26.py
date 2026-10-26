"""Reglas de la revisión de contenido del 26-10-2026 (docs/revision/registro.md)."""
import unittest

from src import taxonomy as T
from src import dedupe as D
from src.publish_static import schedule_hint


def item(key, title, day, slots, venue='Marula Café', lat=41.3797, lon=2.1755):
    s, i = key.split(':')
    return {'key': key, 'source': s, 'id': i, 'title_key': D._title_key(title), 'day': day, 'venue': venue,
            'lat': lat, 'lon': lon, 'address': '', 'slots': set(slots)}


class Revision261026(unittest.TestCase):
    def test_espai_texas_es_cine(self):
        self.assertEqual(T._classify_rules({'source': 'venue_ia_espai_texas', 'title': 'ESCAPE ROOM 2'})['category'], 'cine')

    def test_refuerzo_escolar_fuera(self):
        self.assertEqual(T._classify_rules({'source': 'guiabcn', 'title': "Classes de 'Reforç educatiu ESO'"})['category'], T.EXCLUDED)

    def test_programa_del_mes_de_una_sala_fuera(self):
        self.assertEqual(T._classify_rules({'source': 'generalitat', 'title': 'Octubre al Marula Café'})['category'], T.EXCLUDED)
        self.assertNotEqual(T._classify_rules({'source': 'generalitat', 'title': "Concert d'octubre a la Sala Apolo"})['category'], T.EXCLUDED)

    def test_mismo_pase_con_otro_titulo(self):
        a = item('venue_songkick:1', 'MÜV', '2026-10-26', [('2026-10-26', '22:00')])
        b = item('venue_dice:2', 'MUV: Anti-Mondays Jam', '2026-10-26', [('2026-10-26', '22:00')])
        c = item('venue_dice:3', 'Otra cosa', '2026-10-26', [('2026-10-26', '22:00')])
        self.assertEqual(D.slot_pairs(None, [a, b, c]), [('venue_songkick:1', 'venue_dice:2')])

    def test_pases_de_la_misma_pelicula_son_una_ficha(self):
        a = item('venue_ia_espai_texas:1', 'Escape Room 2', '2026-10-26', [('2026-10-26', '16:00')], venue='Espai Texas')
        b = item('venue_ia_espai_texas:2', 'ESCAPE ROOM 2', '2026-10-26', [('2026-10-26', '18:15')], venue='Espai Texas')
        c = item('venue_ia_espai_texas:3', 'Escape Room 2', '2026-10-27', [('2026-10-27', '16:00')], venue='Espai Texas')
        self.assertEqual(D.session_pairs(None, [a, b, c]), [('venue_ia_espai_texas:1', 'venue_ia_espai_texas:2')])

    def test_texto_de_horario_sin_horas(self):
        self.assertEqual(schedule_hint('Horaris i preus segons establiment'), 'Horaris i preus segons establiment')
        self.assertEqual(schedule_hint("d'11.00 h a 13.00 h"), '')


if __name__ == '__main__':
    unittest.main()
