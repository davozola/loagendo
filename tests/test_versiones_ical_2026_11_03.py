"""Historial sin versiones repetidas por el DTSTAMP de los iCal (3-11-2026, Open Data BCN)."""
import tempfile
import unittest
from pathlib import Path

from src import sync
from src.pipeline import connect

ICS = 'BEGIN:VCALENDAR\r\nPRODID:ics.py\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTAMP:%s\r\nDTSTART:20261108T120000\r\nSUMMARY:En Patufet\r\nEND:VEVENT\r\nEND:VCALENDAR'


def record(stamp, title='En Patufet'):
    return {'source': 'opendatabcn_agenda', 'id': '1', 'title': title, 'start': '2026-11-08', 'end': '2026-11-08', 'time_text': '12:00', 'price_text': '',
            'kind': 'single', 'eligibility': 'review', 'start_timestamp': '', 'frequency': '', 'raw': {'name': title, 'ical': ICS % stamp},
            'venues': [{'name': 'La Violeta', 'address': '', 'coords': None}], 'organizers': [], 'url': '', 'alerts': [], 'evidence_level': 'x'}


class VersionesIcal(unittest.TestCase):
    def test_el_sello_no_crea_version(self):
        self.assertEqual(sync.stable_raw({'a': [ICS % '20261102T133421Z']}), sync.stable_raw({'a': [ICS % '20261103T134124Z']}))
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); sync.initialize(conn)
            for n in (1, 2, 3): conn.execute("INSERT INTO sync_runs(id,source,started_at,status,cursor) VALUES(?,?,?,?,?)", (n, 'opendatabcn_agenda', '2026-11-03', 'running', '0'))
            versions = lambda: conn.execute("SELECT COUNT(*) FROM source_record_versions").fetchone()[0]
            sync._upsert_record(conn, 1, record('20261102T133421Z')); n = versions()
            self.assertEqual(sync._upsert_record(conn, 2, record('20261103T134124Z'))[0], False); self.assertEqual(versions(), n)
            sync._upsert_record(conn, 3, record('20261104T090000Z', 'En Patufet (nova data)')); self.assertEqual(versions(), n + 1)
            conn.close()

    def test_uid_orden_y_sesiones_pasadas(self):
        ev = lambda uid, d: f'BEGIN:VEVENT\r\nUID:{uid}@x.org\r\nDTSTART:{d}T100000Z\r\nDTEND:{d}T190000Z\r\nEND:VEVENT\r\n'
        cal = lambda *evs: 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + ''.join(evs) + 'END:VCALENDAR'
        hoy = sync.stable_raw({'i': cal(ev('a', '20261105'), ev('b', '20261106'))}, '20261105')
        self.assertEqual(sync.stable_raw({'i': cal(ev('c', '20261104'), ev('d', '20261106'), ev('e', '20261105'))}, '20261105'), hoy)
        self.assertNotEqual(sync.stable_raw({'i': cal(ev('a', '20261105'), ev('b', '20261107'))}, '20261105'), hoy)
        # sin fecha de corte, las sesiones pasadas sí cuentan
        self.assertNotEqual(sync.stable_raw({'i': cal(ev('c', '20261104'), ev('d', '20261106'), ev('e', '20261105'))}), sync.stable_raw({'i': cal(ev('a', '20261105'), ev('b', '20261106'))}))


if __name__ == '__main__':
    unittest.main()
