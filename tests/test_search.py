"""Búsqueda por raíz de palabra (24-10-2026): «castellers sagrada» encuentra la
«Diada castellera» de la Sagrada Família. La web (public.js) y el servidor local
(mvp/catalog.py) tienen que responder igual."""
import json, shutil, subprocess, unittest
from pathlib import Path

from mvp import catalog

ROOT = Path(__file__).resolve().parents[1]
TITLE = '“Festes de Tardor de la Sagrada Família”: Diada castellera Marina (Provença - Mallorca)'
CASES = [
    ('castellers sagrada', True),     # el caso que falló: «castellers» → «castell»
    ('castells', True),
    ('sagrada familia', True),
    ('diada castellera', True),
    ('castellers sants', False),      # cada palabra sigue siendo obligatoria
    ('mar', True),                    # corta: exacta (está en «Marina»)
    ('sardanes', False),
]


class SearchStemTest(unittest.TestCase):
    def test_word_stem(self):
        self.assertEqual(catalog.word_stem('castellers')[0], 'castell')
        self.assertEqual(catalog.word_stem('exposiciones')[0], 'exposic')
        self.assertEqual(catalog.word_stem('teatro')[0], 'teatr')
        self.assertEqual(catalog.word_stem('jazz')[0], 'jazz')
        self.assertEqual(catalog.word_stem('museu')[0], 'museu')

    def test_no_false_friends(self):
        # Errores que daba un recorte simple de letras: apellido, nombre y palabra distinta.
        for q, text in [('castellers', 'biblioteca bon pastor josefina castellvi'), ('castellers', 'taller castella inicial'), ('castellers', 'carrer castello'), ('castellers', 'castell de torre baro'), ('mercat', 'amb mercedes gancedo'), ('sardanes', 'concert meghana sardar'), ('flamenco', "l'espai ateneu en flames")]:
            with self.subTest(q=q):
                self.assertFalse(catalog.query_matches(text, q))
        for q, text in [('exposiciones', 'exposicio de fotografia'), ('talleres', 'tallers de cuina'), ('visitas guiadas', 'visita guiada a la torre'), ('festes', 'festa major de gracia'), ('teatro', 'teatre lliure'), ('exposicion', 'exposicions temporals'), ('jugadores', 'jugador de escacs')]:
            with self.subTest(q=q):
                self.assertTrue(catalog.query_matches(text, q))

    def test_python_matches(self):
        text = catalog.clean(TITLE)
        for q, expected in CASES:
            with self.subTest(q=q):
                self.assertEqual(catalog.query_matches(text, catalog.clean(q)), expected)

    @unittest.skipUnless(shutil.which('node'), 'sin node')
    def test_js_matches_python(self):
        js = (ROOT / 'static' / 'public.js').read_text()
        start, end = js.index('const SYN = '), js.index('const iso = ')
        piece = js[start:end].replace('const searchText', 'const _st')
        fold = "const fold = s => String(s ?? '').toLowerCase().normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '').split(/\\s+/).filter(Boolean).join(' ');\n"
        script = fold + piece + f"\nconst cases = {json.dumps(CASES)};\nconsole.log(JSON.stringify(cases.map(([q]) => queryMatches(fold({json.dumps(TITLE)}), fold(q)))));"
        out = subprocess.run(['node', '-e', script], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [e for _, e in CASES])


if __name__ == '__main__':
    unittest.main()
