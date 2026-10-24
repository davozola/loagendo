import json
import sqlite3
import unittest

from src import ai_assist, official_translations as ot

CA_JAM = "Marissa Möller veu i composició · Jan Lammert teclats, composició i arranjaments · Lambert Windges bateria · Julian Schwiebert baix"
EN_JAM = "Marissa Möller vocals and composition · Jan Lammert keyboards, composition and arrangements · Lambert Windges drums · Julian Schwiebert bass. MOLASS is not your ordinary band; they are a movement"
ES_JAM = "Marissa Möller voz y composición · Jan Lammert teclados, composición y arreglos · Lambert Windges batería · Julian Schwiebert bajo. MOLASS no es una banda cualquiera; es un movimiento que"


def page(lang, og='', desc='', alts=()):
    links = ''.join(f'<link rel="alternate" hreflang="{l}" href="{u}">' for l, u in alts)
    return f'<html lang="{lang}"><head>{links}<meta property="og:description" content="{og}"><meta name="description" content="{desc}"></head><body></body></html>'


class OfficialTranslations(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript("""CREATE TABLE source_records(source TEXT,id TEXT,title TEXT,start_date TEXT,end_date TEXT,kind TEXT,eligibility TEXT,evidence_level TEXT,source_url TEXT,raw_sha256 TEXT,raw_json TEXT,PRIMARY KEY(source,id));
            CREATE TABLE source_enrichments(source TEXT,id TEXT,description TEXT);""")

    def add(self, source, rid, url, description='', enrichment=None):
        self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', (source, rid, 't', '2026-11-01', '2026-11-01', 'event', '', '', url, '', json.dumps({'loagendo': {'description': description}})))
        if enrichment is not None: self.conn.execute('INSERT INTO source_enrichments VALUES (?,?,?)', (source, rid, enrichment))

    def test_jamboree_and_language_check(self):
        self.add('venue_jamboree', 'j1', 'https://jamboreejazz.com/evento/molass/', CA_JAM)
        pages = {'https://jamboreejazz.com/en/evento/molass/': page('en-US', EN_JAM),
                 'https://jamboreejazz.com/es/evento/molass/': page('es-ES', CA_JAM)}  # versión /es/ con el texto en catalán: no vale
        fetch = lambda url, timeout: (200, url, pages[url]) if url in pages else (404, url, '')
        result = ot.run(self.conn, {}, fetcher=fetch, today='2026-10-24')
        self.assertEqual(result['paginas']['resultado'], {'ok': 1, 'igual_que_original': 1})
        self.assertEqual(ot.official_for(self.conn, 'venue_jamboree:j1', 'en')['text'], EN_JAM)
        self.assertIsNone(ot.official_for(self.conn, 'venue_jamboree:j1', 'es'))
        # no se vuelve a mirar hasta pasados unos días
        self.assertEqual(ot.run(self.conn, {}, fetcher=fetch, today='2026-10-24')['paginas']['actos'], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM official_translation_log').fetchone()[0], 2)

    def test_hreflang_pages(self):
        url = 'https://www.macba.cat/es/actividades/x/'
        es_text = 'Programa público, comisariado por hablarenarte junto con Marina Monsonís, que reúne a creadores de Cocinas Transhumantes.'
        en_text = 'Public programme, curated by hablarenarte together with Marina Monsonís, bringing together creators from Cocinas Transhumantes.'
        self.add('web_macba', 'm1', url, enrichment=es_text)
        alts = (('ca', 'https://www.macba.cat/ca/activitats/x/'), ('es', url), ('en', 'https://www.macba.cat/en/activities/x/'))
        pages = {url: page('es', desc=es_text, alts=alts), 'https://www.macba.cat/en/activities/x/': page('en', desc=en_text, alts=alts)}
        fetch = lambda u, timeout: (200, u, pages[u]) if u in pages else (404, u, '')
        result = ot.run(self.conn, {}, fetcher=fetch, today='2026-10-24')
        self.assertEqual(result['paginas']['resultado'], {'ok': 1, 'es_el_original': 1})
        self.assertEqual(ot.official_for(self.conn, 'web_macba:m1', 'en')['url'], 'https://www.macba.cat/en/activities/x/')

    def test_language_switch_without_hreflang(self):
        url = 'https://www.teatrelliure.com/es/epitap'
        es_text = 'Cerramos el aniversario en Gràcia con EPITAP. Un título que contiene un nombre. Xavier Bobés nos acompaña en este viaje.'
        en_text = 'We close the anniversary in Gràcia with EPITAP. A title that contains a name. Xavier Bobés accompanies us on this journey.'
        self.add('web_teatre_lliure', 'l1', url, enrichment=es_text)
        nav = '<a href="/ca/epitap">CAT</a><a href="https://www.teatrelliure.com/en/epitap">ENG</a>'
        pages = {url: page('es', desc=es_text).replace('<body>', '<body>' + nav), 'https://www.teatrelliure.com/en/epitap': page('en', desc=en_text)}
        fetch = lambda u, timeout: (200, u, pages[u]) if u in pages else (404, u, '')
        result = ot.run(self.conn, {}, fetcher=fetch, today='2026-10-24')
        self.assertEqual(result['paginas']['resultado'], {'ok': 1, 'es_el_original': 1})
        self.assertEqual(ot.official_for(self.conn, 'web_teatre_lliure:l1', 'en')['text'], en_text)

    def test_official_skips_machine_translation(self):
        ai_assist.initialize(self.conn); ai_assist._CACHE.update(stamp=None, map={})
        text = 'Concert de jazz amb el quartet de la ciutat i els seus convidats, per a tots els públics i amb entrada lliure.'
        ai_assist.queue_translations(self.conn, {'venue_jamboree:j1': text}, stamp='s')
        self.assertEqual(len(ai_assist.translation_candidates(self.conn, 'en')), 1)
        ot._save(self.conn, 'venue_jamboree', 'j1', 'en', 'https://x/en', 'Jazz concert with the city quartet and their guests, for all audiences, free entry.', 'ok', '<html>')
        self.assertEqual(ai_assist.translation_candidates(self.conn, 'en'), [])

    def test_palau_text(self):
        prod = {'subtitle': 'Opera staged in two acts', 'performers': '<p><span class="artist">Orquestra NovAria Filharmonia</span><br />Adolf Gassol, <span>musical direction</span></p>'}
        self.assertEqual(ot.palau_text(prod), 'Opera staged in two acts — Orquestra NovAria Filharmonia Adolf Gassol, musical direction')


if __name__ == '__main__':
    unittest.main()
