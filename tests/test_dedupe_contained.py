"""La misma función con un título dentro del otro, mismo sitio y misma hora (dedupe.contained_pairs)."""
import json
import sqlite3
import unittest
from unittest import mock

from src import dedupe


class ContainedTests(unittest.TestCase):
    def test_calderada_twice_in_the_tnc(self):
        conn = sqlite3.connect(':memory:')
        conn.executescript("""CREATE TABLE source_records(source,id,title,start_date,end_date,eligibility,raw_json);
            CREATE TABLE source_venues(source,id,seq,venue,lat,lon);
            CREATE TABLE candidate_occurrences(source,id,local_date,local_time);""")
        rows = [('generalitat', 'a', 'Calderada', '2099-10-20', '2099-10-27', 'Dimarts 20: 19 h Dimarts 27: 19 h'),
                ('generalitat', 'b', '"Calderada". El meu clàssic: Pere Calders', '2099-10-20', '2099-10-20', '19 h'),
                ('generalitat', 'c', 'Calderada', '2099-10-21', '2099-10-21', '20 h')]          # otro día y hora: no
        for src, rid, title, a, b, t in rows:
            conn.execute("INSERT INTO source_records VALUES(?,?,?,?,?,'review',?)", (src, rid, title, a, b, json.dumps({'normalized': {'time_text': t}})))
            conn.execute("INSERT INTO source_venues VALUES(?,?,0,'TNC - Teatre Nacional de Catalunya',41.39994,2.18577)", (src, rid))
        conn.execute("INSERT INTO candidate_occurrences VALUES('generalitat','b','2099-10-20','19:00')")
        conn.execute("INSERT INTO candidate_occurrences VALUES('generalitat','c','2099-10-21','20:00')")
        pairs = dedupe.contained_pairs(conn)
        self.assertEqual(pairs, [('generalitat:a', 'generalitat:b')])


if __name__ == '__main__':
    unittest.main()
