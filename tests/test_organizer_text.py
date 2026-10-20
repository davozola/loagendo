"""Texto de la web del organizador para fichas de GuiaBCN sin texto (src/organizer_text.py)."""
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import organizer_text
from src.pipeline import connect


class OrganizerTextTests(unittest.TestCase):
    def test_link_filter(self):
        self.assertTrue(organizer_text.usable_link('https://www.filmoteca.cat/web/ca/cicle/festival-de-cinema-jueu-2025'))
        self.assertFalse(organizer_text.usable_link('https://www.filmoteca.cat/'))
        self.assertFalse(organizer_text.usable_link('https://www.instagram.com/sala/'))
        self.assertFalse(organizer_text.usable_link('https://guia.barcelona.cat/ca/detall/x.html'))

    def test_reads_og_description_only_when_it_is_about_the_event(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            from src.guia_detail import initialize as init_enrich; init_enrich(conn)
            rows = [('1', 'Cicle "Festival de Cinema Jueu de Barcelona 2026"', 'https://filmoteca.test/cicle/festival-cinema-jueu'),
                    ('2', 'Futbol "F.C. Barcelona - Villarreal"', 'https://club.test/partits/villarreal'),
                    ('3', 'Concert de tardor', 'https://generic.test/agenda/concert')]
            for rid, title, url in rows:
                conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES('guiabcn',?,?,'2099-10-13','2099-10-28','program','review','x','u','h','{}')", (rid, title))
                conn.execute("INSERT INTO source_enrichments(source,id,fetched_at,source_url,description,links_json,raw_html_sha256) VALUES('guiabcn',?,'2026-10-20','u','',?,'h')", (rid, json.dumps([url])))
            pages = {'https://filmoteca.test/cicle/festival-cinema-jueu': '<meta property="og:description" content="El Festival de Cinema Jueu de Barcelona arriba a la seva edició amb pel·lícules inèdites i col·loquis.">',
                     'https://club.test/partits/villarreal': '<meta property="og:description" content="Curt">',
                     'https://generic.test/agenda/concert': '<meta property="og:description" content="La nostra entitat organitza activitats culturals per a tot el barri durant tot l\'any.">'}
            out = organizer_text.run(conn, fetcher=lambda u, t: (200, u, pages[u]))
            self.assertEqual(out['with_text'], 1)
            status = dict(conn.execute("SELECT id,status FROM organizer_texts"))
            self.assertEqual(status, {'1': 'ok', '2': 'corto', '3': 'no_es_del_acto'})
            self.assertTrue(catalog.organizer_description(conn, 'guiabcn', '1').startswith('El Festival de Cinema Jueu'))


if __name__ == '__main__':
    unittest.main()
