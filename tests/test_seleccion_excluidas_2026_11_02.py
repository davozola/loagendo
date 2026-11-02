"""City Hall nunca es Selección Ontoca (2-11-2026, David)."""
import unittest

from src.selection_rules import excluded


class NuncaSeleccion(unittest.TestCase):
    def test_city_hall(self):
        self.assertTrue(excluded({'source': 'venue_ia_city_hall', 'venue_names': ['City Hall']}))
        self.assertTrue(excluded({'source': 'xceed', 'venue_names': ['City Hall Club']}))
        self.assertTrue(excluded({'source': 'guiabcn', 'venues': [{'name': 'Sala City Hall'}]}))
        self.assertFalse(excluded({'source': 'guiabcn', 'venue_names': ['Sala Apolo']}))
        self.assertFalse(excluded({'source': 'x', 'venue_names': ['City Hallway Gallery']}))
        self.assertFalse(excluded(None))

    def test_aplicada_en_los_tres_sitios(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        self.assertIn('not excluded(e)', (root / 'src' / 'ai_select.py').read_text(encoding='utf-8'))
        self.assertIn('_never_selected(e)', (root / 'mvp' / 'catalog.py').read_text(encoding='utf-8'))
        self.assertIn('_never_selected(all_by_key.get(k))', (root / 'src' / 'publish_static.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
