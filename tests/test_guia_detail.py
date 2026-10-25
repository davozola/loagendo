import sqlite3
import unittest

MENU = '<p>Per districte Selecciona el districte Ciutat Vella Eixample Sants-Montjuïc Les Corts Sarrià-Sant Gervasi Gràcia</p>'


class DescriptionTests(unittest.TestCase):
    def parse(self, body, meta='Quan: dissabte 17 d’octubre, a les 18.00 h'):
        from src.guia_detail import MetaParser
        parser = MetaParser(); parser.feed(f'<html><head><meta name="description" content="{meta}"></head><body>{body}</body></html>')
        return parser.description

    def test_district_menu_is_never_taken_as_description(self):
        self.assertEqual(self.parse(MENU), '')
        self.assertEqual(self.parse(MENU, meta=''), '')

    def test_prose_inside_the_content_block_is_kept(self):
        prose = 'Taller per a famílies on aprendrem a cosir estrelles de Nadal amb retalls de roba reciclada.'
        self.assertEqual(self.parse(MENU + f'<div class="cos"><p>{prose}</p></div>'), prose)

    def test_every_paragraph_of_the_content_block_is_kept(self):
        # 25-10-2026: Cinema català tot l'any salía cortado al primer párrafo.
        a = 'Primer párrafo con la presentación del ciclo de cine en catalán durante todo el año.'
        b = 'Segundo párrafo con las sesiones, los espacios y cómo conseguir las entradas del ciclo.'
        self.assertEqual(self.parse(f'<div class="cos"><p>{a}</p><p>{b}</p></div>', meta='Resumen corto de la ficha que no es la descripción completa'), a + '\n\n' + b)

    def test_archived_menu_text_is_ignored_when_read_but_not_deleted(self):
        from mvp import catalog
        from src.guia_detail import initialize, usable_description
        conn = sqlite3.connect(':memory:'); initialize(conn)
        menu_text = 'Per districte Selecciona el districte Ciutat Vella Eixample Sants-Montjuïc'
        conn.execute("INSERT INTO source_enrichments(source,id,fetched_at,source_url,description,links_json,raw_html_sha256) VALUES('guiabcn','1','t','u',?,'[]','h')", (menu_text,))
        self.assertEqual(catalog.enrichment(conn, 'guiabcn', '1')[0], '')
        self.assertEqual(conn.execute("SELECT description FROM source_enrichments").fetchone()[0], menu_text)
        self.assertFalse(usable_description(menu_text)); self.assertTrue(usable_description('Concert de jazz al pati del centre cívic.'))


if __name__ == '__main__': unittest.main()
