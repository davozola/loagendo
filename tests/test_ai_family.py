"""Recomendación automática «para ir en familia» de exposiciones (src/ai_family.py)."""
import json
import unittest

from src import ai_assist, ai_family, taxonomy

PAYLOAD = {'titulo': "Exposició 'Taurons. Els guardians de l’oceà'", 'sala': 'CosmoCaixa Barcelona',
           'texto': "Una exposició sobre els taurons, amb models a mida real i mòduls interactius per descobrir com viuen."}


class FamilyAiTests(unittest.TestCase):
    def test_yes_with_checked_reason_is_accepted(self):
        row = {'n': 0, 'valoracion': 'si', 'confianza': 0.92, 'motivo_es': 'Tiburones con modelos a tamaño real y módulos interactivos.',
               'motivo_ca': 'Taurons amb models a mida real i mòduls interactius.'}
        answer, conf, _ = ai_family.parse(row, PAYLOAD)
        self.assertTrue(ai_family.accepted(json.loads(answer), conf))

    def test_invented_name_or_low_confidence_or_doubt_is_not(self):
        invented = {'n': 0, 'valoracion': 'si', 'confianza': 0.95, 'motivo_es': 'Con la bióloga Marta Puig.', 'motivo_ca': 'Amb la biòloga Marta Puig.'}
        answer, conf, reason = ai_family.parse(invented, PAYLOAD)
        self.assertFalse(ai_family.accepted(json.loads(answer), conf)); self.assertIn('marta', reason)
        low = {**invented, 'confianza': 0.6, 'motivo_es': 'Tiburones.', 'motivo_ca': 'Taurons.'}
        self.assertFalse(ai_family.accepted(json.loads(ai_family.parse(low, PAYLOAD)[0]), 0.6))
        doubt = {**low, 'valoracion': 'dudoso', 'confianza': 0.9}
        self.assertFalse(ai_family.accepted(json.loads(ai_family.parse(doubt, PAYLOAD)[0]), 0.9))
        self.assertIsNone(ai_family.parse({**low, 'valoracion': 'quizá'}, PAYLOAD))

    def test_channel_says_it_is_an_automatic_recommendation(self):
        ev = {'title': PAYLOAD['titulo'], 'start': '2026-10-01', 'end': '2027-03-01', 'ai_family_rec': {'es': 'Tiburones con modelos a tamaño real.'}}
        self.assertEqual(taxonomy.channels(ev, 'arte')['familia'], 'Recomendación automática (IA): Tiburones con modelos a tamaño real.')

    def test_registered_as_a_task_with_its_tool(self):
        system, tool, field, parse = ai_assist._tasks()['familia']
        self.assertEqual((tool['name'], field), ('valorar_familia', 'fichas'))
        params = ai_assist._params('familia', [('k', PAYLOAD)], ai_assist.MODEL)
        self.assertEqual(params['tool_choice']['name'], 'valorar_familia')

    def test_only_exhibitions_not_already_in_familia(self):
        self.assertTrue(ai_family.needs({'format': 'exhibition', 'channels': ['galerias']}))
        self.assertFalse(ai_family.needs({'format': 'exhibition', 'channels': ['familia']}))
        self.assertFalse(ai_family.needs({'format': 'one_shot', 'channels': []}))


if __name__ == '__main__':
    unittest.main()


class FantasticTests(unittest.TestCase):
    def test_fantastic_as_genre_is_not_promotion(self):
        from src.ai_describe import check
        data = {'texto': 'Personatges de la mitologia catalana'}
        self.assertEqual(check('Personajes de la mitología catalana y criaturas fantásticas.', data), [])
        self.assertTrue(check('Un espectáculo fantástico sobre la mitología catalana.', data))


class PausedDescriptionsTests(unittest.TestCase):
    def test_descriptions_are_neither_requested_nor_published(self):
        import sqlite3
        from pathlib import Path
        from unittest import mock
        from src import ai_describe
        root = Path(__file__).resolve().parents[1]
        job = next(j for j in json.loads((root / 'config' / 'automation.json').read_text())['jobs'] if j['name'] == 'ia-asistente')
        conn = sqlite3.connect(':memory:'); ai_assist.initialize(conn); sent = []
        with mock.patch.object(ai_assist, 'load_key', return_value='k'), mock.patch.object(ai_assist, 'collect', return_value=(0, {})), \
             mock.patch.object(ai_assist, 'submit', side_effect=lambda c, k, t, i, m, r: sent.append(t)), \
             mock.patch('mvp.catalog.all_events', return_value=[]), mock.patch('src.ai_select.ensure', return_value=None):
            ai_assist.run(conn, job, today='2026-10-20')
        self.assertNotIn('descripcion', sent)
        self.assertFalse(ai_describe.public_enabled())
