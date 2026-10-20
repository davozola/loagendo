"""Ayuda de IA (Claude API por lotes): candidatos, lote, recogida, aplicación y trazabilidad."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mvp import catalog
from src import ai_assist, taxonomy
from src.pipeline import connect


def ev(title, **kw):
    return {'title': title, 'source': 'guiabcn', 'kind': 'single', 'format': 'one_shot', 'category': '', 'venue_names': [],
            'classification_paths': [], 'start': '2026-10-20', 'end': '2026-10-20', 'family_audience': False, 'lineup': [], **kw}


class ApplyTests(unittest.TestCase):
    def test_ai_only_decides_weak_cases_with_high_confidence(self):
        ai = {'answer': 'charlas', 'confidence': 0.9, 'reason': 'Conferencia del CCCB', 'model': 'm'}
        out = taxonomy.classify(ev('Grabada, escrita, pronunciada'), None, ai)
        self.assertEqual((out['category'], out['status'], out['method'], out['rule_status']), ('charlas', 'ia', 'ia', 'pendiente'))
        self.assertIn('Conferencia del CCCB', out['evidence'])
        self.assertEqual(taxonomy.classify(ev('Grabada'), None, {**ai, 'confidence': 0.6})['category'], 'pendiente')  # poca confianza
        self.assertEqual(taxonomy.classify(ev("Concert 'Trio'"), None, ai)['category'], 'musica')                    # regla fuerte
        weak = taxonomy.classify(ev('L.E.O. + CHICO JORGE', source='venue_songkick'), None, {**ai, 'answer': 'escena'})  # regla débil
        self.assertEqual(weak['category'], 'musica'); self.assertIn('escena', weak['ai_disagrees'])
        self.assertEqual(taxonomy.classify(ev('Grabada'), {'category': 'cine'}, ai)['category'], 'cine')              # editorial
        self.assertEqual(taxonomy.classify(ev('Campanya de donació de sang'), None, ai)['category'], 'excluida')       # exclusión por regla
        out = taxonomy.classify(ev('Singles?'), None, {**ai, 'answer': 'excluida'})
        self.assertEqual((out['category'], out['status']), ('excluida', 'excluida'))


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.conn = connect(Path(self.temp.name) / 't.sqlite3'); catalog.initialize(self.conn)
        raw = {'name': 'Grabada, escrita, pronunciada', 'addresses': [{'address_name': 'CCCB', 'district_name': 'Ciutat Vella'}], 'loagendo': {}}
        self.conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '1', raw['name'], '2026-10-20', '2026-10-20', 'single', 'review', 'x', '', 'h', json.dumps(raw)))
        self.conn.commit(); catalog.invalidate_cache()
        env = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'test-key'}); env.start(); self.addCleanup(env.stop)
        self.calls = []

    def tearDown(self):
        self.conn.close(); self.temp.cleanup(); catalog.invalidate_cache()

    def fake(self, ended=False):
        def requester(method, url, key, body=None, timeout=60, raw=False):
            self.calls.append((method, url, body)); assert key == 'test-key'
            if method == 'POST': return {'id': 'msgbatch_1', 'processing_status': 'in_progress'}
            if url.endswith('/msgbatch_1'): return {'processing_status': 'ended' if ended else 'in_progress', 'results_url': 'https://api.anthropic.com/results/1'}
            message = {'content': [{'type': 'tool_use', 'name': 'clasificar', 'input': {'fichas': [{'n': 0, 'categoria': 'charlas', 'confianza': 0.92, 'motivo': 'Ciclo de lecturas'}]}}],
                       'usage': {'input_tokens': 900, 'output_tokens': 40, 'cache_read_input_tokens': 800}}
            return json.dumps({'custom_id': 'cat-0', 'result': {'type': 'succeeded', 'message': message}}) + '\n'
        return requester

    def test_submit_collect_apply_and_no_resubmission(self):
        out = ai_assist.run(self.conn, {'duplicado': False}, requester=self.fake(), today='2026-10-19')
        self.assertEqual(out['submitted']['categoria']['items'], 1)
        body = self.calls[-1][2]['requests'][0]
        self.assertEqual(body['custom_id'], 'cat-0')
        self.assertEqual(body['params']['system'][0]['cache_control']['type'], 'ephemeral')
        self.assertEqual(body['params']['tool_choice'], {'type': 'tool', 'name': 'clasificar'})
        self.assertIn('Grabada', body['params']['messages'][0]['content'])
        self.assertIn('Instrucciones editoriales', body['params']['system'][0]['text'])  # config/ia_instrucciones.md
        # Mientras el lote está en curso no se vuelve a mandar la misma ficha.
        self.calls.clear(); out = ai_assist.run(self.conn, {'duplicado': False}, requester=self.fake(), today='2026-10-19')
        self.assertIsNone(out['submitted']['categoria'])
        # Lote terminado: se guarda, se aplica y queda trazado.
        out = ai_assist.run(self.conn, {'duplicado': False}, requester=self.fake(ended=True), today='2026-10-19')
        self.assertEqual((out['stored'], out['usage']['input_tokens']), (1, 900))
        catalog.invalidate_cache()
        item = catalog.query_events(self.conn, day='2026-10-20', public=True)['items'][0]
        self.assertEqual((item['public_category'], item['category_status'], item['category_method']), ('charlas', 'ia', 'ia'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM ai_suggestion_log').fetchone()[0], 1)
        self.assertIsNone(out['submitted']['categoria'])  # ya respondida: no se repite

    def test_without_key_does_nothing(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}), mock.patch.object(ai_assist, 'ROOT', Path(self.temp.name)):
            self.assertEqual(ai_assist.run(self.conn)['status'], 'skipped')


class DuplicateTests(unittest.TestCase):
    def test_high_confidence_same_pairs_join_groups(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn); ai_assist.initialize(conn)
            from src import dedupe
            dedupe.initialize(conn)
            conn.execute("INSERT INTO ai_suggestions VALUES ('duplicado','venue_dice:a|web_conciertos_club:b','h','m',?, 'mismo',0.95,'',NULL,'t')", (ai_assist.prompt_version('duplicado'),))
            conn.execute("INSERT INTO ai_suggestions VALUES ('duplicado','venue_dice:c|web_conciertos_club:d','h','m',?, 'mismo',0.6,'',NULL,'t')", (ai_assist.prompt_version('duplicado'),))
            conn.commit()
            groups = dedupe.canonical_groups(conn)
            self.assertEqual(len({groups.get('venue_dice:a', 'venue_dice:a'), groups.get('web_conciertos_club:b', 'web_conciertos_club:b')}), 1)
            self.assertNotIn('venue_dice:c', groups); self.assertNotIn('web_conciertos_club:d', groups)


if __name__ == '__main__':
    unittest.main()
