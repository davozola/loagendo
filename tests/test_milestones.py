"""Inauguraciones y clausuras (22-10-2026)."""
import unittest

from src.milestones import link, milestone_of


class MilestoneTest(unittest.TestCase):
    def test_graf_url(self):
        m = milestone_of('¿Lo has visto? Lo vi, pero ya no estaba. Marian Brea', 'https://graf.cat/events/event/marian-brea-opening/', 'arte', '2026-10-22', '2026-10-22')
        self.assertEqual(m['kind'], 'opening'); self.assertEqual(m['evidence'], 'url')
        self.assertEqual(milestone_of('X', 'https://graf.cat/events/event/x-closing/', 'arte', '2026-11-13', '2026-11-13')['kind'], 'closing')

    def test_title_only_in_art(self):
        self.assertEqual(milestone_of("Inauguració de l'exposició 'Elles per elles'", '', 'arte', '2026-11-05', '2026-11-05')['kind'], 'opening')
        self.assertEqual(milestone_of("Finissage de l'exposició «És allà on vaig»", '', 'arte', '2026-11-13', '2026-11-13')['kind'], 'closing')
        self.assertIsNone(milestone_of('Espectacle "La inauguració"', '', 'escena', '2026-11-14', '2026-11-14'))
        self.assertIsNone(milestone_of('Varietés by Churros - Gran Opening', '', 'escena', '2026-11-06', '2026-11-06'))

    def test_only_single_day(self):
        self.assertIsNone(milestone_of('Inauguración de la exposición Aurèlia Muñoz', '', 'arte', '2026-11-05', '2027-05-02'))

    def test_no_false_positives(self):
        self.assertIsNone(milestone_of('Concert al Palau', 'https://example.com/opening-hours/', 'musica', '2026-10-22', '2026-10-22'))
        self.assertIsNone(milestone_of('Kintos. Fermín Sales', 'https://graf.cat/events/event/kintos/', 'arte', '2026-10-28', '2026-10-28'))

    def test_link_opening_with_exhibition(self):
        op = {'key': 'web_graf:a', 'title': 'Kintos. Fermín Sales', 'start': '2026-10-28', 'end': '2026-10-28', 'time': '19:00',
              'venue_names': ['Galeria Senda'], 'milestone': {'kind': 'opening'}}
        expo = {'key': 'web_graf:b', 'title': 'Kintos. Fermín Sales', 'start': '2026-10-28', 'end': '2027-01-10', 'venue_names': ['Galeria Senda']}
        other = {'key': 'web_graf:c', 'title': 'Kintos. Fermín Sales', 'start': '2026-10-28', 'end': '2027-01-10', 'venue_names': ['Otra galería']}
        late = {'key': 'web_graf:d', 'title': 'Kintos. Fermín Sales', 'start': '2027-02-01', 'end': '2027-03-10', 'venue_names': ['Galeria Senda']}
        to_expo, to_act = link([op, expo, other, late])
        self.assertEqual(to_expo, {'web_graf:a': {'key': 'web_graf:b', 'start': '2026-10-28', 'end': '2027-01-10'}})
        self.assertEqual(to_act['web_graf:b'], {'key': 'web_graf:a', 'date': '2026-10-28', 'time': '19:00', 'kind': 'opening'})

    def test_no_link_without_exhibition(self):
        op = {'key': 'k', 'title': '¿Lo has visto? Marian Brea', 'start': '2026-10-22', 'end': '2026-10-22', 'venue_names': ['Galeria H2O'], 'milestone': {'kind': 'opening'}}
        unrelated = {'key': 'u', 'title': 'Otra exposición distinta', 'start': '2026-10-01', 'end': '2026-11-30', 'venue_names': ['Galeria H2O']}
        self.assertEqual(link([op, unrelated]), ({}, {}))


if __name__ == '__main__':
    unittest.main()
