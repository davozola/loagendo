"""Imagen de la página del propio acto para fichas publicadas sin foto (1-11-2026, src/official_images.py)."""
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src import official_images

DETAIL = {'source': 'guiabcn', 'id': '1', 'title': 'Concert de Sílvia Pérez Cruz', 'start': '2026-11-06', 'media': [{'url': '/img/sala.jpg', 'fallback': True}],
          'links': [{'label': 'Ficha en GuiaBCN', 'url': 'https://guia.barcelona.cat/x'}, {'label': 'Web del evento', 'url': 'https://silvia.test/concert'},
                    {'label': 'Instagram', 'url': 'https://instagram.com/x'}], 'url': 'https://guia.barcelona.cat/x'}


class ImagenesDelActo(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); out = Path(self.folder.name)
        (out / 'data' / 'detail').mkdir(parents=True)
        (out / 'data' / 'detail' / '00.json').write_text(json.dumps({'guiabcn:1': DETAIL, 'guiabcn:2': {**DETAIL, 'id': '2', 'media': [{'url': '/img/own.jpg'}]}}))
        self.out = out
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE media_assets (asset_id INTEGER PRIMARY KEY, source TEXT, id TEXT, original_url TEXT, alt_text TEXT, credit TEXT, rights_status TEXT, UNIQUE(source,id,original_url))')

    def tearDown(self): self.folder.cleanup()

    def test_orden_de_paginas(self):
        self.assertEqual(official_images.candidates(DETAIL), ['https://silvia.test/concert'])   # GuiaBCN e Instagram, no

    def test_registra_la_imagen_de_la_web_del_evento(self):
        pages = {'https://silvia.test/concert': '<meta property="og:image" content="https://silvia.test/foto.jpg">'}
        out = official_images.run(self.conn, out_dir=self.out, fetcher=lambda u, t: (200, u, pages.get(u, '')), today=dt.date(2026, 11, 1))
        self.assertEqual(out['imagenes'], 1); self.assertEqual(out['fichas_sin_imagen'], 1)
        row = self.conn.execute('SELECT source,id,original_url,credit FROM media_assets').fetchone()
        self.assertEqual(row, ('guiabcn', '1', 'https://silvia.test/foto.jpg', 'silvia.test'))

    def test_imagen_generica_del_sitio_no(self):
        from src import ai_agenda
        ai_agenda.initialize(self.conn)
        for n in range(3): self.conn.execute('INSERT INTO ai_agenda_images VALUES (?,?,?)', (f'https://silvia.test/p{n}', 'https://silvia.test/img/casa.jpg', '2026-11-01T17:00:00+00:00'))
        pages = {'https://silvia.test/concert': '<meta property="og:image" content="https://silvia.test/img/casa.jpg">'}
        out = official_images.run(self.conn, out_dir=self.out, fetcher=lambda u, t: (200, u, pages.get(u, '')), today=dt.date(2026, 11, 1))
        self.assertEqual(out['imagenes'], 0); self.assertGreaterEqual(out['genericas'], 1)

    def test_logo_no(self):
        pages = {'https://silvia.test/concert': '<meta property="og:image" content="https://silvia.test/img/logo-silvia.png">'}
        out = official_images.run(self.conn, out_dir=self.out, fetcher=lambda u, t: (200, u, pages.get(u, '')), today=dt.date(2026, 11, 1))
        self.assertEqual(out['imagenes'], 0)


if __name__ == '__main__':
    unittest.main()
