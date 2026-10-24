import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src import ai_assist, ai_translate, publish_static

CA = ("Concert de l'Orquestra Simfònica amb obres de Händel i Mozart. Dues sessions, a les 19.00 h i a les 21.30 h. "
      "Entrada 12 €. També hi haurà una xerrada prèvia per a tot el públic.")
ES = ("Concierto de la Orquestra Simfònica con obras de Händel y Mozart. Dos sesiones, a las 19.00 h y a las 21.30 h. "
      "Entrada 12 €. También habrá una charla previa para todo el público.")


class GuessAndCheck(unittest.TestCase):
    def test_guess(self):
        self.assertEqual(ai_translate.guess_lang(CA), 'ca')
        self.assertEqual(ai_translate.guess_lang(ES), 'es')
        self.assertEqual(ai_translate.guess_lang('Hola'), '')

    def test_spanish_check(self):
        self.assertEqual(ai_translate.check_target(CA, ES, 'es'), (True, []))
        ok, problems = ai_translate.check_target(CA, ES.replace('12 €', '15 €'), 'es')
        self.assertFalse(ok); self.assertIn('números nuevos: 15', problems)

    def test_parser_skips_same_language(self):
        answer, conf, _ = ai_translate.parser_for('es')({'n': 0, 'source_lang': 'es', 'text': ES}, {'text': ES})
        self.assertEqual(conf, 0.0); self.assertEqual(json.loads(answer)['text'], '')
        self.assertIsNone(ai_translate.parser_for('es')({'n': 0, 'source_lang': 'ca', 'text': ''}, {'text': CA}))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:'); ai_assist.initialize(self.conn); ai_assist._CACHE.update(stamp=None, map={})

    def test_queue_candidates_and_publish(self):
        ai_assist.queue_translations(self.conn, {'a:1': CA, 'a:2': ES}, stamp='2026-10-24T00:00:00+00:00')
        self.assertEqual([k for k, _ in ai_assist.translation_candidates(self.conn, 'es')], ['a:1'])  # a:2 ya está en castellano
        self.assertEqual([k for k, _ in ai_assist.translation_candidates(self.conn, 'en')], ['a:1', 'a:2'])
        chunk = ai_assist.translation_candidates(self.conn, 'es')
        answers = ai_assist._answers('traduccion_es', {'content': [{'type': 'tool_use', 'name': 'traducir', 'input': {'items': [{'n': 0, 'source_lang': 'ca', 'text': ES}]}}]}, chunk)
        ai_assist._store(self.conn, 'traduccion_es', chunk, answers, 'claude-haiku-5-5', 'b1')
        self.assertEqual(ai_assist.translation_candidates(self.conn, 'es'), [])
        tr = ai_assist.translation_for(self.conn, 'a:1', CA, 'es')
        self.assertEqual(tr['text'], ES); self.assertEqual(tr['model'], 'claude-haiku-5-5')
        self.assertIsNone(ai_assist.translation_for(self.conn, 'a:1', CA + ' Canvi.', 'es'))  # el original cambió
        with tempfile.TemporaryDirectory() as tmp:
            shards = {publish_static.shard_of('a:1'): {'a:1': {'description': CA}}, publish_static.shard_of('a:2'): {'a:2': {'description': ES}}}
            report = publish_static.write_translations(self.conn, Path(tmp), shards)
            self.assertEqual(report['traducidas'], {'en': 0, 'en_oficiales': 0, 'es': 1, 'es_oficiales': 0})
            data = json.loads((Path(tmp) / 'data' / 'tr' / 'es' / f"{publish_static.shard_of('a:1')}.json").read_text())
            self.assertEqual(data['a:1']['t'], ES)
            self.assertTrue((Path(tmp) / 'data' / 'tr' / 'en' / f"{publish_static.shard_of('a:2')}.json").exists())

    def test_submit_uses_small_chunks(self):
        sent = {}
        def requester(method, url, key, body=None, **kw):
            sent['body'] = body; return {'id': 'batch-1'}
        items = [(f'a:{n}', {'text': CA}) for n in range(20)]
        info = ai_assist.submit(self.conn, 'k', 'traduccion_en', items, requester=requester)
        self.assertEqual(info['requests'], 3)
        self.assertEqual(sent['body']['requests'][0]['params']['max_tokens'], 200 + 1100 * 8)
        self.assertIn('Spanish', ai_assist._tasks()['traduccion_es'][0])


if __name__ == '__main__':
    unittest.main()
