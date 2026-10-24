"""Páginas de entrada para buscadores (src/landings.py, 23-10-2026)."""
import datetime as dt
import json
import re
import unittest

from src import landings

INDEX = ('<!doctype html><html lang="es" data-static="1" data-skin="v2" data-theme="light"><head><title>Ontoca</title>'
         '<meta name="description" content="x"><meta property="og:title" content="x"><meta property="og:description" content="x">'
         '<link rel="canonical" href="https://ontoca.com/"></head><body><main><section id="agenda"></section></main><footer>pie</footer></body></html>')
MON = dt.date(2026, 10, 12)


class LandingsTest(unittest.TestCase):
    def test_weekend_is_friday_to_sunday_and_from_today_once_it_starts(self):
        self.assertEqual(landings.weekend(MON), (dt.date(2026, 10, 16), dt.date(2026, 10, 18)))
        self.assertEqual(landings.weekend(dt.date(2026, 10, 15)), (dt.date(2026, 10, 16), dt.date(2026, 10, 18)))   # jueves
        self.assertEqual(landings.weekend(dt.date(2026, 10, 17)), (dt.date(2026, 10, 17), dt.date(2026, 10, 18)))   # sábado
        self.assertEqual(landings.weekend(dt.date(2026, 10, 18)), (dt.date(2026, 10, 18), dt.date(2026, 10, 18)))   # domingo

    def test_pages_cover_days_topics_and_their_combinations(self):
        paths = [p['path'] for p in landings.pages(MON)]
        for path in ('/hoy', '/manana', '/fin-de-semana', '/dia/2026-10-12', '/con-ninos', '/con-ninos/fin-de-semana', '/conciertos/hoy', '/exposiciones'):
            self.assertIn(path, paths)
        self.assertEqual(sum(1 for p in paths if p.startswith('/dia/')), landings.DAY_PAGES)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(landings.file_for('/con-ninos/fin-de-semana'), 'con-ninos/fin-de-semana.html')

    def test_render_puts_title_canonical_filter_and_list_in_the_html(self):
        page = next(p for p in landings.pages(MON) if p['path'] == '/con-ninos/fin-de-semana')
        days = {'2026-10-17': {'items': [
            {'s': 'diba_bibliotecas', 'i': '7', 't': 'Hora del conte', 'a': '2026-10-17', 'b': '2026-10-17', 'kd': 'single', 'pc': 'escena', 'ch': ['familia'], 'tm': '11:00', 'v': ['Biblioteca Sant Antoni'], 'fr': 1},
            {'s': 'web_auditori', 'i': '9', 't': 'Concierto adulto', 'a': '2026-10-17', 'b': '2026-10-17', 'kd': 'single', 'pc': 'musica', 'ch': [], 'tm': '20:00', 'v': ["L'Auditori"]},
            {'s': 'x', 'i': '1', 't': 'Expo larga', 'a': '2026-09-01', 'b': '2027-01-01', 'kd': 'exhibition', 'pc': 'arte', 'ch': ['familia'], 'v': ['Museu']}]}}
        doc = landings.render(INDEX, page, days, 'https://ontoca.com')
        self.assertIn('<title>Planes con niños en Barcelona este fin de semana · Ontoca</title>', doc)
        self.assertEqual(doc.count('rel="canonical"'), 1); self.assertIn('<link rel="canonical" href="https://ontoca.com/con-ninos/fin-de-semana">', doc)
        landing = json.loads(re.search(r"data-landing='([^']*)'", doc).group(1).replace('&#39;', "'"))
        self.assertEqual(landing, {'chans': ['familia'], 'range': 'finde', 'path': '/con-ninos/fin-de-semana'})
        self.assertIn('<a href="/e/diba_bibliotecas/7"><b>11:00</b> Hora del conte</a>', doc)
        self.assertIn('Teatro y danza · Biblioteca Sant Antoni · Gratis', doc)
        self.assertNotIn('Concierto adulto', doc)   # no es para familias
        self.assertNotIn('Expo larga', doc)         # las exposiciones largas solo en las páginas de arte
        self.assertIn('<h2>Sábado 17 de octubre</h2>', doc)
        self.assertIn('<main><section id="seoLista"', doc)

    def test_nav_links_every_page_from_the_footer(self):
        nav = landings.nav_html()
        for path in ('/hoy', '/fin-de-semana', '/con-ninos', '/conciertos'):
            self.assertIn(f'href="{path}"', nav)


if __name__ == '__main__':
    unittest.main()
