"""Originales de fotos de actos terminados hace más de una semana: se borra el archivo y se conserva la procedencia (3-11-2026)."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import media
from src.pipeline import connect


class OriginalesPasados(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.conn = connect(self.root / 't.sqlite3'); catalog.initialize(self.conn)
        self.today = dt.date(2026, 11, 3)
        for rid, end in (('viejo', '2026-09-01'), ('reciente', '2026-10-30'), ('vigente', '2026-12-01'), ('comparte', '2026-12-01'), ('viejo2', '2026-08-01')):
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('s', rid, 'Acte', '2026-08-01', end, 'single', 'include', 'x', '', 'h', '{}'))
        self.files = {}
        for n, (rid, name) in enumerate((('viejo', 'a'), ('reciente', 'b'), ('vigente', 'c'), ('viejo2', 'd'), ('comparte', 'd'))):
            f = self.root / f'{name}.jpg'; f.write_bytes(b'x' * 1000); self.files[rid] = f
            self.conn.execute("INSERT INTO media_assets(asset_id,source,id,original_url,rights_status,sha256,local_path,content_type) VALUES (?,?,?,?,?,?,?,?)",
                              (n + 1, 's', rid, f'https://img.test/{rid}.jpg', 'authorized', name, str(f), 'image/jpeg'))
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def test_solo_borra_lo_terminado_hace_mas_de_una_semana(self):
        out = media.prune_past_originals(self.conn, self.today)
        self.assertEqual(out['past_originals_removed'], 1)
        self.assertFalse(self.files['viejo'].exists())
        self.assertTrue(self.files['reciente'].exists() and self.files['vigente'].exists())
        self.assertTrue(self.files['viejo2'].exists())  # el archivo lo usa también una ficha vigente
        row = self.conn.execute("SELECT local_path,original_url,sha256,download_error FROM media_assets WHERE id='viejo'").fetchone()
        self.assertEqual(row[:3], (None, 'https://img.test/viejo.jpg', 'a'))
        self.assertEqual(row[3], media.PAST_ORIGINAL_MARK)

    def test_no_se_vuelve_a_descargar_y_revive_si_vuelve_a_tener_fechas(self):
        media.prune_past_originals(self.conn, self.today)
        calls = []
        orig = media._download
        media._download = lambda conn, asset_id, directory: calls.append(asset_id)
        try: media.download_local_previews(self.conn, self.root)
        finally: media._download = orig
        self.assertNotIn(1, calls)
        self.conn.execute("UPDATE source_records SET end_date='2027-01-01' WHERE id='viejo'"); self.conn.commit()
        self.assertEqual(media.prune_past_originals(self.conn, self.today)['past_originals_revived'], 1)
        self.assertIsNone(self.conn.execute("SELECT download_failed_at FROM media_assets WHERE id='viejo'").fetchone()[0])

    def test_fotos_de_equipamientos_no_se_tocan(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS place_images(place_id TEXT, local_path TEXT)")
        self.conn.execute("INSERT INTO place_images(place_id,local_path) VALUES ('p', ?)", (str(self.files['viejo']),)); self.conn.commit()
        self.assertEqual(media.prune_past_originals(self.conn, self.today)['past_originals_removed'], 0)
        self.assertTrue(self.files['viejo'].exists())


if __name__ == '__main__':
    unittest.main()
