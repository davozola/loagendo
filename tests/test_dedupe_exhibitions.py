"""La misma exposición con fechas distintas en dos fuentes, y la ficha del propio centro manda (21-10-2026)."""
import sqlite3
import unittest
from unittest import mock

from src import dedupe
from src.opendata_bcn import place_name


def _db(rows):
    conn = sqlite3.connect(':memory:')
    conn.executescript("""CREATE TABLE source_records(source,id,title,start_date,end_date,kind,eligibility);
        CREATE TABLE source_venues(source,id,seq,venue,lat,lon);""")
    for src, rid, title, a, b, kind, venue, lat, lon in rows:
        conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?,?,'review')", (src, rid, title, a, b, kind))
        conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,?,?)", (src, rid, venue, lat, lon))
    return conn


class ExhibitionTests(unittest.TestCase):
    def test_perriand_in_two_sources_with_other_dates(self):
        conn = _db([('generalitat', 'g', 'Exposició "Charlotte Perriand. La llibertat de repensar el món"', '2099-10-09', '2100-02-28', 'exhibition', "Fundació Joan Miró - Centre d'Estudis", 41.36863, 2.15985),
                    ('opendatabcn_agenda', 'o', 'Exposició "Charlotte Perriand"', '2099-10-06', '2100-03-28', 'exhibition', 'Fundació Joan Miró', 41.36829, 2.16015),
                    ('guiabcn', 'v', 'Visita comentada a l\'exposició "Charlotte Perriand"', '2099-10-13', '2099-11-05', 'exhibition', 'Fundació Joan Miró', 41.36829, 2.16015)])
        pairs = dedupe.exhibition_pairs(conn)
        self.assertEqual({frozenset(p) for p in pairs}, {frozenset(('opendatabcn_agenda:o', 'generalitat:g'))})

    def test_name_only_title_in_two_shows_is_ambiguous(self):
        conn = _db([('generalitat', 'a', 'Aurèlia Muñoz', '2099-11-10', '2100-03-14', 'exhibition', 'X', 41.4, 2.18),
                    ('guiabcn', 'b', "Exposició 'Aurèlia Muñoz. El tèxtil com a pretext'", '2099-11-10', '2100-03-29', 'exhibition', 'X', 41.4, 2.18),
                    ('guiabcn', 'c', "Exposició 'Aurèlia Muñoz. Ens'", '2099-11-05', '2100-03-29', 'exhibition', 'X', 41.4, 2.18)])
        self.assertEqual(dedupe.exhibition_pairs(conn), [])

    def test_far_apart_is_not_the_same(self):
        conn = _db([('generalitat', 'a', 'Exposició "Un teatre lliure"', '2099-09-22', '2100-01-17', 'exhibition', 'A', 41.40, 2.18),
                    ('guiabcn', 'b', 'Exposició "Un teatre lliure"', '2099-09-21', '2100-01-17', 'exhibition', 'B', 41.37, 2.15)])
        self.assertEqual(dedupe.exhibition_pairs(conn), [])

    def test_first_party_source(self):
        with mock.patch('src.venue_directory.venue_type', side_effect=lambda slug: {'jamboree': 'music', 'songkick': 'aggregator'}.get(slug, '')):
            self.assertTrue(dedupe.first_party('venue_ia_fundacio_miro'))
            self.assertTrue(dedupe.first_party('venue_jamboree'))
            self.assertFalse(dedupe.first_party('venue_songkick'))
            self.assertFalse(dedupe.first_party('opendatabcn_agenda'))


class PlaceNameTests(unittest.TestCase):
    def test_section_of_a_building(self):
        self.assertEqual(place_name({'place': 'Museu', 'related_entity_data': {'is_section_of_name': 'Fundació Joan Miró'}}), 'Fundació Joan Miró')
        self.assertEqual(place_name({'place': 'Sala 1 Pau Casals', 'related_entity_data': {'is_section_of_name': "L'Auditori de Barcelona"}}), "L'Auditori de Barcelona · Sala 1 Pau Casals")
        self.assertEqual(place_name({'place': 'Auditori', 'related_entity_data': {'is_section_of_name': 'Museu Tàpies *Tancat temporalment'}}), 'Museu Tàpies · Auditori')
        self.assertEqual(place_name({'place': 'Museu Egipci de Barcelona', 'related_entity_data': {'is_section_of_name': 'Fundació Arqueològica Clos'}}), 'Museu Egipci de Barcelona')
        self.assertEqual(place_name({'place': 'Teatre Lliure'}), 'Teatre Lliure')


if __name__ == '__main__':
    unittest.main()
