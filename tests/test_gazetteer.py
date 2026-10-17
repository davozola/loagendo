import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import gazetteer as gz
from src.pipeline import connect


class GazetteerTests(unittest.TestCase):
    def _conn(self, folder):
        conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
        od = lambda district: json.dumps({'name': 'x', 'body': '', 'start_date': '2026-11-01', 'end_date': '2026-11-01', 'district': district})
        rows = [('opendatabcn_agenda', 'a', 'Gràcia', 'Centre Cívic La Sedeta', 41.4035, 2.1600), ('opendatabcn_agenda', 'b', 'Gràcia', 'Biblioteca Jaume Fuster', 41.4040, 2.1520),
                ('opendatabcn_agenda', 'c', 'Gràcia', 'Centre Cívic La Sedeta', 41.4036, 2.1601), ('opendatabcn_agenda', 'd', 'Ciutat Vella', 'Jamboree', 41.3797, 2.1752)]
        for source, rid, district, venue, lat, lon in rows:
            conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility) VALUES(?,?,?,?,?,?,'review')", (source, rid, venue, '2026-11-01', '2026-11-01', json.dumps({'loagendo': {'district': district}, 'name': venue}), ))
            conn.execute("INSERT INTO source_venues(source,id,seq,venue,address,lat,lon) VALUES(?,?,0,?,?,?,?)", (source, rid, venue, '', lat, lon))
        conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility) VALUES('generalitat','g1','Octubre a l''Heliogàbal','2026-10-01','2026-10-31','{}','review')")
        conn.execute("INSERT INTO source_venues(source,id,seq,venue,address,lat,lon) VALUES('generalitat','g1',0,'Heliogàbal','C. de Ramón y Cajal, 80',41.4035,2.1603)")
        conn.commit(); return conn

    def test_name_index_and_nearest_neighbours(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = self._conn(folder); gz.invalidate()
            g = gz.gazetteer(conn)
            self.assertEqual(g.for_name('Centre Cívic La Sedeta')['district'], 'Gràcia')
            self.assertEqual(g.resolve(['Heliogàbal'], None)[0], 'Gràcia')            # coordinates from the Generalitat, district from the neighbours
            self.assertEqual(g.resolve(['Heliogàbal'], None)[1]['lat'], 41.4035)
            self.assertEqual(g.resolve(['Sala Desconeguda'], {'lat': 41.3798, 'lon': 2.1750})[0], 'Ciutat Vella')
            self.assertEqual(g.resolve(['Sala Desconeguda'], {'lat': 41.5, 'lon': 2.3})[0], None)  # too far from anything labelled
            self.assertEqual(g.resolve(['Sala Desconeguda'], None)[0], None)
            conn.close(); gz.invalidate()


if __name__ == '__main__':
    unittest.main()
