import importlib.util, json, sqlite3, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('compactar_historial', ROOT / 'scripts' / 'compactar_historial.py')
ch = importlib.util.module_from_spec(spec); spec.loader.exec_module(ch)


def ical(stamp, summary='Concert', days=()):
    ev = lambda d: f'BEGIN:VEVENT\r\nDTSTAMP:{stamp}\r\nUID:{stamp}{d}@x.org\r\nDTSTART:{d}T100000Z\r\nDTEND:{d}T190000Z\r\nSUMMARY:{summary}\r\nEND:VEVENT\r\n'
    body = ''.join(ev(d) for d in days) if days else f'BEGIN:VEVENT\r\nDTSTAMP:{stamp}\r\nUID:{stamp}@x.org\r\nSUMMARY:{summary}\r\nEND:VEVENT\r\n'
    return {'ical': 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\n' + body + 'END:VCALENDAR'}


class CompactarHistorial(unittest.TestCase):
    def make(self, versions, lock=False):
        d = tempfile.mkdtemp(); db = Path(d) / 'x.sqlite3'
        c = sqlite3.connect(db)
        c.execute('CREATE TABLE source_record_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, external_id TEXT, run_id INTEGER, raw_sha256 TEXT, normalized_sha256 TEXT, raw_json TEXT, changed_fields_json TEXT, observed_at TEXT)')
        c.execute('CREATE TABLE automation_locks (name TEXT PRIMARY KEY, held_at TEXT)')
        if lock: c.execute("INSERT INTO automation_locks VALUES ('engine','2026-11-03T10:00:00+00:00')")
        for n, (ext, raw) in enumerate(versions):
            c.execute('INSERT INTO source_record_versions(source,external_id,run_id,raw_sha256,normalized_sha256,raw_json,changed_fields_json,observed_at) VALUES (?,?,?,?,?,?,?,?)',
                      ('opendatabcn_agenda', ext, n, str(n), 'n', json.dumps(raw), '[]', f'2026-10-{n + 1:02d}'))
        c.commit(); c.close()
        return db

    def ids(self, db):
        c = sqlite3.connect(db); out = [r[0] for r in c.execute('SELECT id FROM source_record_versions ORDER BY id')]; c.close(); return out

    def test_keeps_first_real_changes_and_last(self):
        db = self.make([('a', ical('1')), ('a', ical('2')), ('a', ical('3')), ('a', ical('4', 'Otro')), ('a', ical('5', 'Otro')),
                        ('a', ical('6')), ('a', ical('7')), ('b', ical('1')), ('b', ical('2'))])
        self.assertEqual(ch.main(['--db', str(db), '--aplicar', '--sin-copia']), 0)
        # 1 primera, 4 cambio real, 6 vuelta al contenido de antes (cambio real), 7 última de «a»; 8 y 9 de «b» (primera y última)
        self.assertEqual(self.ids(db), [1, 4, 6, 7, 8, 9])
        c = sqlite3.connect(db); self.assertIsNone(c.execute("SELECT 1 FROM automation_locks").fetchone()); c.close()

    def test_sessions_that_passed_and_order_dont_count(self):
        # observed_at de la versión n: 2026-10-(n+1). La 2 (día 2) ya no trae la sesión del 1; la 3 cambia el orden;
        # la 4 añade una sesión nueva (cambio real); la 5 es la última.
        db = self.make([('a', ical('1', days=('20261001', '20261005', '20261006'))), ('a', ical('2', days=('20261005', '20261006'))),
                        ('a', ical('3', days=('20261006', '20261005'))), ('a', ical('4', days=('20261005', '20261006', '20261009'))),
                        ('a', ical('5', days=('20261005', '20261006', '20261009')))])
        ch.main(['--db', str(db), '--aplicar', '--sin-copia'])
        self.assertEqual(self.ids(db), [1, 4, 5])

    def test_preview_changes_nothing(self):
        db = self.make([('a', ical('1')), ('a', ical('2')), ('a', ical('3'))])
        self.assertEqual(ch.main(['--db', str(db)]), 0)
        self.assertEqual(self.ids(db), [1, 2, 3])

    def test_engine_running_leaves_its_lock(self):
        db = self.make([('a', ical('1')), ('a', ical('2')), ('a', ical('3'))], lock=True)
        self.assertEqual(ch.main(['--db', str(db), '--aplicar', '--sin-copia']), 2)
        self.assertEqual(self.ids(db), [1, 2, 3])
        c = sqlite3.connect(db); self.assertTrue(c.execute("SELECT 1 FROM automation_locks").fetchone()); c.close()

    def test_backup_copy(self):
        db = self.make([('a', ical('1')), ('a', ical('2')), ('a', ical('3'))])
        ch.main(['--db', str(db), '--aplicar'])
        copies = list(db.parent.glob('copia-antes-de-compactar-*.sqlite3'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(self.ids(copies[0]), [1, 2, 3])
        self.assertEqual(self.ids(db), [1, 3])


if __name__ == '__main__':
    unittest.main()
