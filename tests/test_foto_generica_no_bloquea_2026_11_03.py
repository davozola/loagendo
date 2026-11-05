"""Una foto genérica ya descargada no impide descargar la foto del acto (3-11-2026, Filmoteca: avatar de gencat)."""
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import media
from src.pipeline import connect


class FotoGenericaNoBloquea(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.conn = connect(self.root / 't.sqlite3'); catalog.initialize(self.conn)
        for rid in ('peli', 'otra'):
            self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('venue_ia_filmoteca', rid, 'Sekishunchô', '2026-11-04', '2099-11-04', 'single', 'include', 'x', '', 'h', '{}'))
        rows = ((1, 'peli', 'http://cultura.gencat.cat/web/resources/fwk/comuns/img/avatar.jpg', str(self.root / 'avatar.jpg')),
                (2, 'peli', 'https://www.filmoteca.cat/web/sites/default/files/2026-10/FAREWELL.jpg', None),
                (3, 'otra', 'https://www.filmoteca.cat/web/sites/default/files/2026-10/BUENA.jpg', str(self.root / 'buena.jpg')),
                (4, 'otra', 'https://www.filmoteca.cat/web/sites/default/files/2026-10/SEGUNDA.jpg', None))
        for aid, rid, url, path in rows:
            self.conn.execute("INSERT INTO media_assets(asset_id,source,id,original_url,rights_status,local_path) VALUES (?,?,?,?,?,?)", (aid, 'venue_ia_filmoteca', rid, url, 'authorized', path))
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def test_descarga_la_buena_aunque_haya_avatar(self):
        calls = []
        orig = media._download
        media._download = lambda conn, asset_id, directory: calls.append(asset_id)
        try: out = media.download_local_previews(self.conn, self.root)
        finally: media._download = orig
        self.assertEqual(calls, [2])  # la ficha con foto propia ya descargada no pide otra
        self.assertEqual(out['downloaded'], 1)


if __name__ == '__main__':
    unittest.main()
