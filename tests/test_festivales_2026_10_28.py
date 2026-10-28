"""Circuito de programas de festival (28-10-2026, David): cobertura, venta, IA de último recurso y fichas."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CoberturaTests(unittest.TestCase):
    def test_sin_parcial_completa(self):
        from src.festival_finder import coverage
        self.assertEqual(coverage('2026-11-26', '2026-11-28', set(), 0), 'sin_sesiones')
        # DART: dos sesiones sueltas fuera de las jornadas centrales
        self.assertEqual(coverage('2026-11-26', '2026-11-28', {'2026-11-12', '2026-11-19'}, 2), 'parcial')
        self.assertEqual(coverage('2026-11-26', '2026-11-28', {'2026-11-26', '2026-11-27', '2026-11-28'}, 16), 'completa')
        self.assertEqual(coverage('2026-11-26', '2026-11-28', {'2026-11-26'}, 1, connected=True), 'completa')


class VentaTests(unittest.TestCase):
    def fetcher(self, entities):
        def f(url, timeout):
            slug = url.rsplit('/', 1)[-1]
            return (200, url, json.dumps(entities[slug])) if slug in entities else (404, url, '')
        return f

    def test_entidad_por_nombre_y_por_enlace(self):
        from src.festival_finder import codetickets_entity
        f = self.fetcher({'festivaldart': {'id': 814, 'canalId': 4011, 'nombre': 'FESTIVAL DART', 'slug': 'festivaldart'},
                          'festival-in-edit': {'id': 893, 'canalId': 4445, 'nombre': 'FESTIVAL IN-EDIT BARCELONA', 'slug': 'festival-in-edit'},
                          'otro': {'id': 1, 'canalId': 2, 'nombre': 'TEATRE QUALSEVOL', 'slug': 'otro'}})
        self.assertEqual(codetickets_entity({'name': 'DART Festival'}, f)['slug'], 'festivaldart')
        self.assertEqual(codetickets_entity({'name': 'In-Edit Barcelona'}, f, 'https://entradas.codetickets.com/entradas/id/32040/festival-in-edit/online')['slug'], 'festival-in-edit')
        self.assertIsNone(codetickets_entity({'name': 'Festival Inexistent'}, f, 'https://www.codetickets.com/portal/otro/online'))

    def test_conector_y_programa_con_ia(self):
        from src.festival_finder import auto_connector, auto_agenda
        cand = {'slug': 'dart', 'name': 'DART Festival', 'start': '2026-11-26', 'end': '2026-11-28'}
        a = auto_connector(cand, {'platform': 'Codetickets', 'program_url': 'https://www.codetickets.com/portal/festivaldart/online', 'web_ok': 1})
        self.assertEqual((a['feed']['kind'], a['feed']['entidad'], a['feed']['venta']), ('codetickets', 'festivaldart', 'por_acto'))
        g = auto_agenda({'slug': 'auto-festival-42', 'name': 'Festival 42', 'start': '2026-11-04', 'end': '2026-11-08'},
                        {'reading': 'ia', 'program_url': 'https://festival42.com/programa', 'web_ok': 1})
        self.assertEqual((g['festival']['slug'], g['hasta'], g['seguir_actos'], g['activa']), ('auto-festival-42', '2026-11-08', 40, True))
        self.assertIsNone(auto_agenda(cand, {'reading': 'ia', 'program_url': 'https://x', 'web_ok': 0}))   # web que no nombra el festival

    def test_agendas_automaticas_detras_de_las_configuradas(self):
        from src import ai_agenda
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'a.json'
            p.write_text(json.dumps({'agendas': [{'slug': 'fest_x', 'name': 'X', 'urls': ['https://x.test/'], 'activa': True},
                                                 {'slug': 'marula', 'name': 'otra', 'urls': [], 'activa': True}]}))
            got = ai_agenda.load_agendas(auto_path=p)
            self.assertEqual(sum(1 for a in got if a['slug'] == 'marula'), 1)
            self.assertTrue(any(a['slug'] == 'fest_x' for a in got))


class SeguirActosTests(unittest.TestCase):
    def test_la_ficha_del_acto_da_la_hora_y_sustituye_a_la_linea(self):
        from src import ai_agenda
        listing = '<h1>Programa</h1><p><a href="https://f.test/doc/botero/">Botero</a></p><p>26 de novembre</p>'
        page = '<h1>Botero</h1><p>' + 'sinopsi ' * 300 + '</p><p>26 de novembre, 17.15 h</p>'
        def fetcher(url, timeout):
            return 200, url, listing if url.endswith('/programa/') else page
        calls = []
        def requester(method, url, key, body, timeout=60):
            calls.append(1)
            if len(calls) == 1:
                items = [{'titulo': 'Botero', 'enlace': 'L1', 'sesiones': [{'fecha': '2026-11-26', 'cita_fecha': '26 de novembre'}]}]
            else:
                items = [{'titulo': 'Botero', 'sesiones': [{'fecha': '2026-11-26', 'cita_fecha': '26 de novembre', 'hora': '17:15', 'cita_hora': '17.15 h'}]}]
            return {'content': [{'type': 'tool_use', 'name': 'actos', 'input': {'actos': items}}], 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        agenda = {'slug': 'fest_t', 'name': 'T', 'urls': ['https://f.test/programa/'], 'seguir_actos': 5, 'otros_lugares': True}
        res = ai_agenda.read_agenda(agenda, dt.date(2026, 10, 28), 'k', fetcher=fetcher, requester=requester)
        self.assertEqual([a['sesiones'] for a in res['accepted']], [[('2026-11-26', '17:15')]])


class FichaTests(unittest.TestCase):
    def test_n_sesiones_ver_programa(self):
        js = (ROOT / 'static' / 'public.js').read_text()
        self.assertIn("sesiones · Ver programa", js); self.assertIn("L('Varias sesiones'", js)
