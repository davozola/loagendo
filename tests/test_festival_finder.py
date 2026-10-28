"""Buscador de programas de festival (src/festival_finder.py, 25-10-2026)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import festival_finder as ff
from src import festivals


def _conn(folder):
    from src.pipeline import connect
    conn = connect(Path(folder) / 't.sqlite3')
    return conn


def _rec(conn, source, rid, title, start, end, raw=None):
    conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,raw_json,eligibility,source_url) VALUES(?,?,?,?,?,?,?,?)",
                 (source, rid, title, start, end, json.dumps(raw or {}), 'review', ''))


HOME = '<html><title>Festival Panoràmic 2026</title><body><h1>Festival Panoràmic</h1><a href="/e/panoramic/page/schedule">Programa</a><a href="/about">Qui som</a></body></html>'
SCHEDULE = '<html><script src="https://apiv3.accelevents.com/x.js"></script><p>Sessions</p></html>'


class FinderTests(unittest.TestCase):
    def setUp(self):
        festivals._CACHE.update(key=None, obj=None)

    def test_umbrella_only_web_program_and_platform(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _conn(folder)
            _rec(conn, 'generalitat', '1', 'Festival Panoràmic', '2026-10-15', '2026-12-27', {'item': {'web': 'https://panoramic.example/'}})
            _rec(conn, 'guiabcn', '9', 'Mozilla Festival', '2026-10-28', '2026-10-30')
            _rec(conn, 'guiabcn', '2', 'Festival RBLS: Teatre "Bonobo"', '2026-11-13', '2026-11-13')
            _rec(conn, 'guiabcn', '3', 'Festival RBLS: Teatre "Ricard de 3r"', '2026-11-14', '2026-11-14')
            _rec(conn, 'guiabcn', '4', 'Festival de Teatre Jove RBLS', '2026-11-06', '2026-11-20')
            _rec(conn, 'opendatabcn_agenda', '5', 'Festival «Íntims»', '2026-10-28', '2026-11-28', {'item': {'url': 'https://ajuntament.barcelona.cat/x'}})
            conn.commit()
            cands = {c['name']: c for c in ff.candidates(conn, dt.date(2026, 10, 25))}
            self.assertIn('Festival Panoràmic', cands)
            # 28-10-2026: con 2 sesiones en 15 días, cobertura parcial: también se busca su programa.
            self.assertEqual(cands['Festival RBLS']['coverage'], 'parcial'); self.assertEqual(cands['Festival Panoràmic']['coverage'], 'sin_sesiones')
            pages = {'https://panoramic.example/': HOME, 'https://panoramic.example/e/panoramic/page/schedule': SCHEDULE}
            fetcher = lambda u, t: (200, u, pages[u]) if u in pages else (404, u, '')
            auto = Path(folder) / 'auto.json'
            r = ff.run(conn, {'buscar_web': False, 'auto_path': auto}, today=dt.date(2026, 10, 25), fetcher=fetcher, robots=lambda u: True, key='', out=Path(folder) / 'informe')
            row = dict(zip(('web', 'program_url', 'platform', 'reading', 'web_ok'),
                           conn.execute("SELECT web,program_url,platform,reading,web_ok FROM festival_programs WHERE name='Festival Panoràmic'").fetchone()))
            self.assertEqual(row, {'web': 'https://panoramic.example/', 'program_url': 'https://panoramic.example/e/panoramic/page/schedule',
                                   'platform': 'Accelevents', 'reading': 'api', 'web_ok': 1})
            self.assertIsNone(conn.execute("SELECT 1 FROM festival_programs WHERE name='Mozilla Festival'").fetchone())  # ya tiene conector
            intims = conn.execute("SELECT web, detail FROM festival_programs WHERE name LIKE '%ntims%'").fetchone()
            self.assertEqual(intims[0], '')   # el enlace del Ajuntament no es la web oficial
            self.assertTrue(Path(r['informe']).is_file())
            # 26-10-2026: sin extractores nuevos; por defecto no se conecta nada, solo se guarda el enlace al programa.
            self.assertEqual(r['conectados'], []); self.assertFalse(auto.exists())
            # Una semana sin volver a mirarlo.
            r2 = ff.run(conn, {'buscar_web': False, 'auto_path': auto}, today=dt.date(2026, 10, 25), fetcher=fetcher, robots=lambda u: True, key='', out=Path(folder) / 'informe')
            self.assertEqual(r2['revisados'], 0)

    def test_ai_search_only_proposes_and_is_checked(self):
        cand = {'name': 'Festival Panoràmic', 'start': '2026-10-15', 'end': '2026-12-27', 'texts': []}
        fetcher = lambda u, t: (200, u, '<h1>Una altra cosa</h1>')
        r = ff.probe(cand, fetcher, lambda u: True, key='k', ai=lambda *a: 'https://panoramic.example/')
        self.assertEqual(r['web'], '')                  # la página no nombra el festival: no se acepta
        self.assertIn('no nombra', r['detail'])


class FalsePositiveTests(unittest.TestCase):
    """Falsos positivos del informe del 25-10-2026."""
    def test_prodid_de_ics_py_no_es_la_web(self):
        texts = [{'ics': 'BEGIN:VCALENDAR PRODID:ics.py - http://git.io/lTJl https://github.com/ics-py/ics-py END:VCALENDAR', 'web': 'https://raval.example/'}]
        self.assertEqual(ff.official_links(texts), ['https://raval.example/'])

    def test_aviso_legal_no_es_el_programa(self):
        body = '<a href="/aviso-legal">Aviso legal</a><a href="/cookies">Política de cookies</a><a href="/programa-2026">Programa</a>'
        self.assertEqual(ff.program_links(body, 'https://lens.example/'), ['https://lens.example/programa-2026'])

    def test_prefiere_la_web_que_nombra_el_festival_y_no_conecta_la_dudosa(self):
        cand = {'slug': 'auto-x', 'name': 'Festival Panoràmic', 'start': '2026-10-15', 'end': '2026-12-27',
                'texts': [{'a': 'https://otra.example/', 'b': 'https://panoramic.example/'}]}
        pages = {'https://otra.example/': '<div class="tribe-events">Altres coses</div>',
                 'https://panoramic.example/': '<h1>Festival Panoràmic</h1><div class="tribe-events"></div>'}
        fetch = lambda u, t: (200, u, pages[u])
        r = ff.probe(cand, fetch, lambda u: True)
        self.assertEqual((r['web'], r['web_ok']), ('https://panoramic.example/', 1))
        only_bad = ff.probe({**cand, 'texts': [{'a': 'https://otra.example/'}]}, fetch, lambda u: True)
        self.assertEqual((only_bad['web'], only_bad['web_ok']), ('https://otra.example/', 0))
        self.assertIn('no nombra', only_bad['detail'])
        self.assertIsNone(ff.auto_connector(cand, only_bad))
        self.assertIsNotNone(ff.auto_connector(cand, r))
