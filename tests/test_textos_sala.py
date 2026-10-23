"""Texto, imagen y hora de la página propia del acto para las agendas de sala leídas con IA (23-10-2026)."""
import json
import unittest

from mvp import catalog
from src import organizer_text
from src.pipeline import connect
from src.sync import initialize as init_sync

URL = 'https://marulacafe.com/evento/bex-ay-trick/'
PAGE = ('<html><head><title>Bex + Ay Trick - Marula Café</title><meta property="og:image" content="https://marulacafe.com/img/bex.jpg">'
        '<meta property="og:description" content="BEX es una banda emergente de Barcelona.">'
        '<script type="application/ld+json">{"@context":"https://schema.org","@type":"MusicEvent","name":"Bex + Ay Trick","startDate":"2026-10-23T21:00:00+02:00",'
        '"description":"BEX es una de las bandas emergentes más electrizantes de Barcelona, fusionando Soul, Funk y Rock con una energía arrolladora en directo."}</script>'
        '</head><body></body></html>')


class TextosSalaTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES('venue_ia_marula','m1','Bex + Ay Trick','2026-10-23','2026-10-23','single','include','',?,'',?)",
                          (URL, json.dumps({'loagendo': {}})))
        self.conn.execute("INSERT INTO source_venues VALUES('venue_ia_marula','m1',0,'Marula Café','',NULL,NULL)")

    def test_toma_el_texto_mas_completo_y_la_imagen_de_la_pagina_del_acto(self):
        res = organizer_text.run(self.conn, fetcher=lambda u, t: (200, u, PAGE), today=__import__('datetime').date(2026, 10, 23))
        self.assertEqual((res['with_text'], res['images']), (1, 1))
        text, url = organizer_text.texts(self.conn)[('venue_ia_marula', 'm1')]
        self.assertTrue(text.startswith('BEX es una de las bandas emergentes más electrizantes'))
        self.assertEqual(self.conn.execute("SELECT original_url, credit FROM media_assets WHERE source='venue_ia_marula'").fetchone(), ('https://marulacafe.com/img/bex.jpg', 'Marula Café'))

    def test_misma_obra_varios_dias_no_es_texto_generico(self):
        for n in (2, 3):
            self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES('venue_ia_marula',?,'Bex + Ay Trick',?,?,'single','include','',?,'',?)",
                              ('m%d' % n, '2026-10-2%d' % (3 + n), '2026-10-2%d' % (3 + n), URL, json.dumps({'loagendo': {}})))
        organizer_text.run(self.conn, fetcher=lambda u, t: (200, u, PAGE), today=__import__('datetime').date(2026, 10, 23))
        self.assertEqual(len(organizer_text.texts(self.conn)), 3)


if __name__ == '__main__':
    unittest.main()
