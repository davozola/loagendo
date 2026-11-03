"""Espacio (3-11-2026): fotos de la web que ya no usa nada, fuera de dist/img; con pocas referencias, no se toca nada."""
import json
import tempfile
import unittest
from pathlib import Path

from src import publish_static as ps


class Fotos(unittest.TestCase):
    def test_quita_las_que_no_usa_nada(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); (out / 'img').mkdir(); (out / 'data').mkdir()
            for n in range(10): (out / 'img' / f'{n}.jpg').write_bytes(b'x' * 100)
            (out / 'data' / 'day.json').write_text(json.dumps({'items': [{'i': f'/img/{n}.jpg'} for n in range(8)]}))
            (out / 'index.html').write_text('<img src="/img/8.jpg">')
            r = ps.prune_images(out)
            self.assertEqual(r['removed'], 1); self.assertFalse((out / 'img' / '9.jpg').exists()); self.assertTrue((out / 'img' / '8.jpg').exists())

    def test_con_pocas_referencias_no_toca_nada(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder); (out / 'img').mkdir()
            for n in range(10): (out / 'img' / f'{n}.jpg').write_bytes(b'x')
            (out / 'index.html').write_text('<img src="/img/1.jpg">')
            r = ps.prune_images(out)
            self.assertEqual(r['removed'], 0); self.assertIn('skipped', r); self.assertEqual(len(list((out / 'img').iterdir())), 10)


if __name__ == '__main__':
    unittest.main()
