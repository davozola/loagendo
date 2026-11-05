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
