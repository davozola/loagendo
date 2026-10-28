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
        self.assertEqual(len(out), 8)   # 10 fichas, 5 de música: como mucho 3 por categoría (28-10-2026)
        self.assertLessEqual(sum(1 for e, _, _ in out if e['public_category'] == 'musica'), 3)
        self.assertEqual(len({e['key'] for e, _, _ in out}), 8)                                # sin repetir
        self.assertEqual([k for _, k, _ in out][:7], ['popular'] * 5 + ['descubrimiento'] * 2)   # sin cuotas por tipo

    def test_fills_with_rules_when_the_answer_is_short(self):
        items = [item(i, c) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte'])]
        out = ai_select.pick([(3, 'descubrimiento', 'raro')], items)
        self.assertEqual((len(out), out[0][0]['key'], out[1][1]), (8, 's:3', 'reglas'))   # 8 candidatos: se completan todos

    def test_no_two_of_the_same_festival_or_series(self):
        items = [dict(item(i, 'escena'), festival={'slug': 'salmon'}) for i in range(2)] + [dict(item(2, 'musica'), series='jam'), dict(item(3, 'musica'), series='jam'), item(4, 'cine')]
        out = ai_select.pick([(0, 'popular', 'a'), (1, 'popular', 'b'), (2, 'popular', 'c'), (3, 'popular', 'd'), (4, 'popular', 'e')], items)
        self.assertEqual([e['key'] for e, _, _ in out], ['s:0', 's:2', 's:4'])


class EnsureTests(unittest.TestCase):
    def test_one_call_per_day_and_stored_with_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            items = [dict(item(i, c), media=[1]) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte', 'musica', 'escena', 'arte'])]
            calls = []
            def requester(method, url, key, body=None, timeout=60, raw=False):
                calls.append(body); return {'content': [{'type': 'tool_use', 'name': 'seleccionar', 'input': {'elegidas': [
                    {'n': i, 'tipo': 'popular' if i < 4 else 'descubrimiento', 'motivo': 'm'} for i in range(10)]}}], 'usage': {'input_tokens': 10}}
            from unittest import mock
            with mock.patch.object(ai_select, 'candidates', lambda conn, day, scope='week': items), mock.patch.object(ai_select, '_payload', lambda n, e: {'n': n, 'titulo': e['title']}):
                out = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
                again = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
                today = ai_select.ensure(conn, 'k', day='2026-10-20', scope='day', requester=requester)
            self.assertEqual((out['status'], again['status'], today['status'], len(calls)), ('completed', 'already_done', 'completed', 2))
            self.assertIn('Selección Ontoca', calls[0]['system'][0]['text']); self.assertIn('solo el día', calls[1]['system'][0]['text'])
            self.assertEqual(ai_select.picks_for(conn, '2026-10-20'), [f's:{i}' for i in range(10)])
            self.assertEqual(ai_select.picks_for(conn, '2026-10-20', 'day'), [f's:{i}' for i in range(10)])

    def test_ensure_ahead_covers_eight_days_in_both_scopes(self):
        from unittest import mock
        import datetime as _dt
        seen = []
        with mock.patch.object(ai_select, 'ensure', lambda conn, key, day=None, scope='week', model=None, requester=None: (seen.append((day, scope)) or {'status': 'completed', 'usage': {'input_tokens': 1}})):
            out = ai_select.ensure_ahead(None, 'k', today=_dt.date(2026, 10, 28))
        self.assertEqual((out['calls'], len(seen), seen[0], seen[-1]), (16, 16, ('2026-10-28', 'day'), ('2026-11-04', 'week')))


if __name__ == '__main__':
    unittest.main()
