"""Recinto delante de la sala, solo con evidencia de otras fichas en la misma dirección."""
import unittest

from src.venue_rooms import Rooms, address_key

ROWS = [("L'Auditori de Barcelona - Sala 1 Pau Casals", 'C Lepant 150, 08013 BARCELONA'),
        ("L'Auditori de Barcelona - Sala 2 Oriol Martorell", 'C Lepant 150, 08013 BARCELONA'),
        ('Sala 1 Pau Casals', 'Carrer de Lepant, 150, 08013 Barcelona'),
        ('Sala Apolo', 'C Nou de la Rambla 113'), ('Sala Apolo', 'Carrer Nou de la Rambla, 113'), ('Sala Apolo', 'Nou de la Rambla 113'),
        ('La 2', 'C Nou de la Rambla 113, 08004 BARCELONA'),
        ('Centre de Cultura Contemporània de Barcelona - CCCB', 'C Montalegre 5'), ('CCCB', 'Carrer de Montalegre, 5'),
        ('Sala d\'Exposicions', 'C Desconeguda 9')]


class RoomsTests(unittest.TestCase):
    def setUp(self): self.rooms = Rooms(ROWS)

    def test_room_takes_the_building_written_elsewhere_at_the_same_address(self):
        self.assertEqual(address_key('C Lepant 150, 08013 BARCELONA'), address_key('Carrer de Lepant, 150, 08013 Barcelona'))
        self.assertEqual(self.rooms.full_name('Sala 1 Pau Casals', 'Carrer de Lepant, 150, 08013 Barcelona'), "L'Auditori de Barcelona · Sala 1 Pau Casals")
        self.assertEqual(self.rooms.full_name('Espai 5', 'Carrer de Lepant, 150'), "L'Auditori de Barcelona · Espai 5")
        self.assertEqual(self.rooms.full_name('La 2', 'C Nou de la Rambla 113, 08004 BARCELONA'), 'Sala Apolo · La 2')

    def test_without_evidence_or_for_a_venue_on_its_own_nothing_changes(self):
        self.assertEqual(self.rooms.full_name("Sala d'Exposicions", 'C Desconeguda 9'), "Sala d'Exposicions")
        self.assertEqual(self.rooms.full_name('CCCB', 'Carrer de Montalegre, 5'), 'CCCB')
        self.assertEqual(self.rooms.full_name('Sala 1 Pau Casals', ''), 'Sala 1 Pau Casals')


if __name__ == '__main__':
    unittest.main()
