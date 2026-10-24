import sqlite3
import unittest

from src import venue_text as vt

CA = ('Una oportunitat per conèixer i descobrir cançons, jocs i dites de tradició oral catalana i anglesa, amb instruments '
      'de joguina i molta complicitat entre els músics i les famílies que hi assisteixen.')
EN = ('An opportunity to get to know and discover songs, games and sayings from the Catalan and English oral tradition, with toy '
      'instruments and lots of complicity between the musicians and the families who attend.')


def palau(lang, text, alts=True):
    links = ('<link rel="alternate" hreflang="ca" href="https://www.palaumusica.cat/ca/twinkle_1">'
             '<link rel="alternate" hreflang="es" href="https://www.palaumusica.cat/es/twinkle_1">'
             '<link rel="alternate" hreflang="en" href="https://www.palaumusica.cat/en/twinkle_1">') if alts else ''
    return (f'<html lang="{lang}"><head>{links}</head><body><section class="production_notice"><p>Avís: un cop iniciada la funció, ja no es podrà accedir a la sala.</p></section>'
            f'<section class="production_description s s1"><div class="text_container"><p>{text}</p><p><a>Saber més</a></p></div></section>'
            '<section class="production_sidebar"><p>De dilluns a dissabte: de 8.30 a 21 h.</p></section></body></html>')


class VenueText(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute("CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT,PRIMARY KEY(source,id))")
        self.conn.execute("INSERT INTO source_records VALUES ('venue_palau_musica','p1','Twinkle','2026-11-01','2026-11-01','event','','', 'https://www.palaumusica.cat/ca/twinkle_1','','{}')")

    def test_block_only_and_official_versions(self):
        pages = {'https://www.palaumusica.cat/ca/twinkle_1': palau('ca', CA), 'https://www.palaumusica.cat/en/twinkle_1': palau('en', EN),
                 'https://www.palaumusica.cat/es/twinkle_1': palau('es', CA)}   # versión /es/ sin traducir: no vale
        fetch = lambda u, timeout: (200, u, pages[u]) if u in pages else (404, u, '')
        result = vt.run(self.conn, {}, fetcher=fetch, today='2026-10-25')
        self.assertEqual(result['resultado'], {'ok': 1, 'es:igual_que_original': 1, 'en:ok': 1})
        self.assertEqual(vt.text_for(self.conn, 'venue_palau_musica', 'p1')['text'], CA)   # sin aviso, taquilla ni «Saber més»
        self.assertEqual(vt.text_for(self.conn, 'venue_palau_musica', 'p1', 'en')['text'], EN)
        self.assertIsNone(vt.text_for(self.conn, 'venue_palau_musica', 'p1', 'es'))
        self.assertEqual(vt.run(self.conn, {}, fetcher=fetch, today='2026-10-25')['resultado'], {})   # hasta dentro de 3 días, nada

    def test_page_without_block(self):
        fetch = lambda u, timeout: (200, u, '<html lang="ca"><body><p>' + CA + '</p></body></html>')
        self.assertEqual(vt.run(self.conn, {}, fetcher=fetch, today='2026-10-25')['resultado'], {'sin_bloque': 1})
        self.assertIsNone(vt.text_for(self.conn, 'venue_palau_musica', 'p1'))

    def test_lliure_text_mode(self):
        page = '<div id="infoPlay-1" class="collapse"><div class="wrap"><p>Cerramos el aniversario en Gràcia con EPITAP.</p><br>los sueños<br>la palabra</div></div><div>otra cosa</div>'
        self.assertEqual(vt.extract('web_teatre_lliure', page), 'Cerramos el aniversario en Gràcia con EPITAP.\n\nlos sueños\nla palabra')


if __name__ == '__main__':
    unittest.main()
