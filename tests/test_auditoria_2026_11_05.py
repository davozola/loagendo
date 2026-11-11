"""Errores de la auditoría del 3-11 corregidos el 5-11-2026."""
import unittest

from src.venue_feeds import record_from_jsonld

NODE = {'@type': 'MusicEvent', 'name': 'Jacopo Mezzanotti Trio', 'startDate': '2026-12-10T20:00:00',
        'location': {'@type': 'Place', 'name': 'Aclam Club', 'address': {'streetAddress': 'Carrer del Consell de Cent, 201', 'addressLocality': 'Barcelona'}}}


class Organizador(unittest.TestCase):
    def test_la_ticketera_no_organiza(self):
        r = record_from_jsonld({'slug': 'ticketmaster_es', 'name': 'Ticketmaster España', 'type': 'ticketing'}, NODE, 'https://www.ticketmaster.es/')
        self.assertEqual(r['organizers'], [])

    def test_la_sala_si(self):
        r = record_from_jsonld({'slug': 'aclam', 'name': 'Aclam Club', 'type': 'music'}, NODE, 'https://aclam.test/')
        self.assertEqual(r['organizers'], ['Aclam Club'])

    def test_organizador_del_dato(self):
        r = record_from_jsonld({'slug': 'ticketmaster_es', 'name': 'Ticketmaster España', 'type': 'ticketing'}, {**NODE, 'organizer': {'@type': 'Organization', 'name': 'Jazz Barcelona'}}, 'https://www.ticketmaster.es/')
        self.assertEqual(r['organizers'], ['Jazz Barcelona'])


if __name__ == '__main__':
    unittest.main()


class Auditoria1011(unittest.TestCase):
    """Auditoría del 10-11-2026."""
    def test_parrafo_de_solo_fecha_y_pie_de_financiacion(self):
        from src.organizer_text import clean_text, date_only
        self.assertTrue(date_only('Dimarts 03 de novembre de 2026 - 18:30 h - Dimarts 03 de novembre de 2026 - 20:30 h'))
        self.assertFalse(date_only('El llibre analitza diversos casos de manipulació en relació amb la postveritat.'))
        text = ('El llibre analitza diversos casos de manipulació en relació amb la postveritat, la filosofia i els corrents de pensament actuals.\n\n'
                'Dimarts 03 de novembre de 2026 - 18:30 h - Dimarts 03 de novembre de 2026 - 20:30 h\n\n'
                'Ateneubcn.cat participa al Programa KIT DIGITAL, finançat per la Unió Europea-Next Generation EU.')
        self.assertEqual(clean_text(text), text.split('\n\n')[0])

    def test_festival_acabado_no_avisa_de_caida(self):
        from src import source_watch
        self.assertIn('venue_ia_festival_42', source_watch._festival_sources())


class OrganizadorEnLaFicha(unittest.TestCase):
    def test_no_repite_la_sala_ni_la_plataforma(self):
        from mvp.catalog import public_organizers as f
        self.assertEqual(f({'organizers': ['Espai Texas'], 'venue_names': ['Espai Texas']}), [])
        self.assertEqual(f({'organizers': ['Sala B'], 'venue_names': ['Luz de Gas · Sala B']}), [])
        self.assertEqual(f({'organizers': ['Organizado por: Jazz BCN', 'Eventbrite'], 'venue_names': ['Aclam']}), ['Jazz BCN'])
        self.assertEqual(f({'organizers': ['42 · Festival de Gèneres Fantàstics'], 'venue_names': ['Fabra i Coats']}), ['42 · Festival de Gèneres Fantàstics'])
