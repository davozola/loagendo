"""Enlaces que las fuentes traen en sus datos (22-10-2026)."""
import unittest

from mvp.catalog import source_links


def labels(raw, source, url='https://fuente.example/acto'):
    return {(l['label'], l['url']) for l in source_links(raw, source, url)}


class SourceLinksTest(unittest.TestCase):
    def test_graf_gallery_page(self):
        got = labels({'item': {'event_web': 'https://www.h2o.es/#/ca/exposicion/438/x'}}, 'web_graf')
        self.assertIn(('Web del evento', 'https://www.h2o.es/#/ca/exposicion/438/x'), got)

    def test_generalitat_tickets_organizer_venue(self):
        raw = {'organizadores': [{'linkbotoentrades': 'https://tickets.example/1', 'url_organitzador': 'https://org.example/'}],
               'localizaciones': [{'url': 'https://sala.example/', 'linkbotoentrades': 'https://tickets.example/1'}]}
        got = labels(raw, 'generalitat')
        self.assertIn(('Entradas', 'https://tickets.example/1'), got)
        self.assertIn(('Web del organizador', 'https://org.example/'), got)
        self.assertIn(('Web de la sala', 'https://sala.example/'), got)
        self.assertEqual(sum(1 for l, _ in got if l == 'Entradas'), 1)  # el mismo enlace, una vez

    def test_diba_and_guiabcn(self):
        self.assertIn(('Inscripciones', 'https://s2.puntxarxa.org/x'), labels({'url_inscripcions': 'https://s2.puntxarxa.org/x'}, 'diba_bibliotecas'))
        self.assertIn(('Web del evento', 'https://olivera.org/a/'), labels({'url_general': 'https://olivera.org/a/'}, 'diba_turismo'))
        self.assertIn(('Web del evento', 'https://www.auditori.cat/ca/'), labels({'api_item': {'code_url': 'https://www.auditori.cat/ca/'}}, 'guiabcn'))

    def test_venue_schema_without_aggregators(self):
        raw = {'item': {'workPresented': {'@id': 'https://cines.example/pelicula'}, 'location': {'sameAs': 'https://sala.example/'}}}
        got = labels(raw, 'venue_verdi')
        self.assertIn(('Web del evento', 'https://cines.example/pelicula'), got)
        self.assertIn(('Web de la sala', 'https://sala.example/'), got)
        raw = {'item': {'location': {'url': 'https://dice.fm/venue/x'}}}
        self.assertNotIn('Web de la sala', {l for l, _ in labels(raw, 'venue_dice')})

    def test_ignores_non_urls(self):
        self.assertEqual(labels({'item': {'event_web': 'no es un enlace'}}, 'web_graf'), {('Página de la fuente', 'https://fuente.example/acto')})


if __name__ == '__main__':
    unittest.main()
