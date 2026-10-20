"""Selección de la semana con IA: reparto, variedad, relleno con reglas y guardado."""
import json
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import ai_select
from src.pipeline import connect


def item(n, cat):
    return {'key': f's:{n}', 'title': f'Acto {n}', 'public_category': cat}


class PickTests(unittest.TestCase):
    def test_balances_popular_and_discovery_and_caps_categories(self):
        items = [item(i, c) for i, c in enumerate(['musica'] * 5 + ['escena', 'arte', 'cine', 'charlas', 'talleres'])]
        rows = [(0, 'popular', 'a'), (1, 'popular', 'b'), (2, 'popular', 'c'), (5, 'popular', 'd'), (6, 'popular', 'e'),
                (7, 'descubrimiento', 'f'), (8, 'descubrimiento', 'g'), (99, 'popular', 'x'), (7, 'descubrimiento', 'dup')]
        out = ai_select.pick(rows, items)
        self.assertEqual(len(out), 7)
        self.assertLessEqual(sum(1 for e, _, _ in out if e['public_category'] == 'musica'), 2)  # máx. 2 por categoría
        self.assertEqual(len({e['key'] for e, _, _ in out}), 7)                                # sin repetir
        self.assertEqual(sum(1 for _, k, _ in out if k == 'popular'), 4)

    def test_fills_with_rules_when_the_answer_is_short(self):
        items = [item(i, c) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte'])]
        out = ai_select.pick([(3, 'descubrimiento', 'raro')], items)
        self.assertEqual((len(out), out[0][0]['key'], out[1][1]), (7, 's:3', 'reglas'))


class EnsureTests(unittest.TestCase):
    def test_one_call_per_day_and_stored_with_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            items = [dict(item(i, c), media=[1]) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte'])]
            calls = []
            def requester(method, url, key, body=None, timeout=60, raw=False):
                calls.append(body); return {'content': [{'type': 'tool_use', 'name': 'seleccionar', 'input': {'elegidas': [
                    {'n': i, 'tipo': 'popular' if i < 4 else 'descubrimiento', 'motivo': 'm'} for i in range(7)]}}], 'usage': {'input_tokens': 10}}
            from unittest import mock
            with mock.patch.object(ai_select, 'candidates', return_value=items), mock.patch.object(ai_select, '_payload', lambda n, e: {'n': n, 'titulo': e['title']}):
                out = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
                again = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
            self.assertEqual((out['status'], again['status'], len(calls)), ('completed', 'already_done', 1))
            self.assertIn('Selección de la semana', calls[0]['system'][0]['text'])
            self.assertEqual(ai_select.picks_for(conn, '2026-10-20'), [f's:{i}' for i in range(7)])


if __name__ == '__main__':
    unittest.main()
