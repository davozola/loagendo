"""Selección con IA: variedad, sin relleno con reglas (30-10-2026), populares aparte y guardado."""
import json
from datetime import date as _date
import tempfile
import unittest
from pathlib import Path

from mvp import catalog
from src import ai_select
from src.pipeline import connect


def item(n, cat):
    return {'key': f's:{n}', 'title': f'Acto {n}', 'public_category': cat}


class PickTests(unittest.TestCase):
    def test_caps_categories_without_repeating(self):
        items = [item(i, c) for i, c in enumerate(['musica'] * 5 + ['escena', 'arte', 'cine', 'charlas', 'talleres'])]
        rows = [(0, 'seleccion', 'a'), (1, 'seleccion', 'b'), (2, 'seleccion', 'c'), (3, 'seleccion', 'x'), (5, 'seleccion', 'd'),
                (6, 'seleccion', 'e'), (99, 'seleccion', 'x'), (6, 'seleccion', 'dup')]
        out = ai_select.pick(rows, items)
        self.assertEqual([e['key'] for e, _, _ in out], ['s:0', 's:1', 's:2', 's:5', 's:6'])   # como mucho 3 de música, sin repetir

    def test_no_fill_with_rules_when_the_answer_is_short(self):
        items = [item(i, c) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte'])]
        out = ai_select.pick([(3, 'seleccion', 'raro')], items)
        self.assertEqual([e['key'] for e, _, _ in out], ['s:3'])   # 30-10-2026: mejor menos y mejores

    def test_no_repeated_venue_counting_inner_rooms(self):
        items = [dict(item(0, 'musica'), venue_names=['Palau de la Música Catalana']), dict(item(1, 'escena'), venue_names=['Palau de la Música Catalana · Sala Petit']),
                 dict(item(2, 'arte'), venue_names=['MACBA'])]
        out = ai_select.pick([(0, 'seleccion', 'a'), (1, 'seleccion', 'b'), (2, 'seleccion', 'c')], items)
        self.assertEqual([e['key'] for e, _, _ in out], ['s:0', 's:2'])

    def test_populars_accept_objects_and_strings(self):
        items = [item(i, 'musica') for i in range(4)]
        msg = {'content': [{'type': 'tool_use', 'input': {'elegidas': [{'n': 0, 'motivo': 'm'}], 'populares': [{'n': 1}, '2', 'x']}}]}
        chosen, pops = ai_select.parse(msg, items)
        self.assertEqual([e['key'] for e in pops], ['s:1', 's:2'])

    def test_populars_skip_chosen_and_repeated_works(self):
        items = [item(0, 'musica'), item(1, 'musica'), dict(item(2, 'escena'), series='queen'), dict(item(3, 'escena'), series='queen'), item(4, 'cine')]
        chosen = ai_select.pick([(0, 'seleccion', 'a')], items)
        self.assertEqual([e['key'] for e in ai_select.populars([0, 2, 3, 4, 77], items, chosen)], ['s:2', 's:4'])

    def test_no_two_of_the_same_festival_or_series(self):
        items = [dict(item(i, 'escena'), festival={'slug': 'salmon'}) for i in range(2)] + [dict(item(2, 'musica'), series='jam'), dict(item(3, 'musica'), series='jam'), item(4, 'cine')]
        out = ai_select.pick([(0, 'seleccion', 'a'), (1, 'seleccion', 'b'), (2, 'seleccion', 'c'), (3, 'seleccion', 'd'), (4, 'seleccion', 'e')], items)
        self.assertEqual([e['key'] for e, _, _ in out], ['s:0', 's:2', 's:4'])


class ExtraTests(unittest.TestCase):
    def test_mas_without_chosen_popular_or_repeats_and_capped_per_type(self):
        items = [item(i, 'musica') for i in range(10)] + [item(10, 'cine')]
        msg = {'content': [{'type': 'tool_use', 'input': {'elegidas': [{'n': 0, 'motivo': 'm'}], 'populares': [1], 'mas': [0, 1, 2, '3', {'n': 4}, 5, 6, 7, 8, 9, 10, 99]}}]}
        chosen, popular, extra = ai_select.parse(msg, items, with_extra=True)
        self.assertEqual([e['key'] for e in extra], ['s:2', 's:3', 's:4', 's:5', 's:6', 's:7', 's:10'])   # 6 de música como mucho


class PinnedTests(unittest.TestCase):
    def test_pinned_first_in_scope_and_not_popular(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = Path(folder) / 'manual.json'
            cfg.write_text(json.dumps({'fijadas': [{'ficha': 'op:mira', 'dias': ['2026-11-06', '2026-11-07']}]}))
            from unittest import mock
            with mock.patch.object(ai_select, 'MANUAL_PATH', cfg):
                self.assertEqual(ai_select.pinned_for('2026-11-06', 'day'), ['op:mira'])
                self.assertEqual(ai_select.pinned_for('2026-11-05', 'day'), [])
                self.assertEqual(ai_select.pinned_for('2026-10-31', 'week'), ['op:mira'])   # del 31-10 al 6-11
                self.assertEqual(ai_select.pinned_for('2026-10-30', 'week'), [])
                self.assertEqual(ai_select.pinned_day('op:mira', '2026-11-02', 'week'), '2026-11-06')
                conn = connect(Path(folder) / 't.sqlite3'); ai_select.initialize(conn)
                conn.execute("INSERT INTO ai_selection(day,scope,created_at,model,prompt_version,candidates_json,picks_json,popular_json) VALUES('2026-11-06','day','x','m','v','[]',?,?)",
                             (json.dumps([{'key': 's:1'}, {'key': 'op:mira'}]), json.dumps([{'key': 'op:mira'}, {'key': 's:9'}])))
                self.assertEqual(ai_select.picks_for(conn, '2026-11-06', 'day'), ['op:mira', 's:1'])
                self.assertEqual(ai_select.populars_for(conn, '2026-11-06', 'day'), ['s:9'])
                self.assertEqual(ai_select.picks_for(conn, '2026-11-05', 'day'), [])


class EnsureTests(unittest.TestCase):
    def test_one_call_per_day_and_stored_with_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            items = [dict(item(i, c), media=[1]) for i, c in enumerate(['musica', 'escena', 'arte', 'cine', 'charlas', 'talleres', 'fiestas', 'deporte', 'musica', 'escena', 'arte'])]
            calls = []
            def requester(method, url, key, body=None, timeout=60, raw=False):
                calls.append(body); return {'content': [{'type': 'tool_use', 'name': 'seleccionar', 'input': {'elegidas': [
                    {'n': i, 'motivo': 'm'} for i in range(9)], 'populares': [9, 10, 0]}}], 'usage': {'input_tokens': 10}}
            from unittest import mock
            with mock.patch.object(ai_select, 'candidates', lambda conn, day, scope='week': items), mock.patch.object(ai_select, '_payload', lambda n, e: {'n': n, 'titulo': e['title']}):
                out = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
                again = ai_select.ensure(conn, 'k', day='2026-10-20', requester=requester)
                today = ai_select.ensure(conn, 'k', day='2026-10-20', scope='day', requester=requester)
            self.assertEqual((out['status'], again['status'], today['status'], len(calls)), ('completed', 'already_done', 'completed', 2))
            self.assertIn('Selección Ontoca', calls[0]['system'][0]['text']); self.assertIn('solo el día', calls[1]['system'][0]['text'])
            self.assertEqual(ai_select.picks_for(conn, '2026-10-20'), [f's:{i}' for i in range(9)])
            self.assertEqual(ai_select.picks_for(conn, '2026-10-20', 'day'), [f's:{i}' for i in range(9)])
            self.assertEqual(ai_select.populars_for(conn, '2026-10-20'), ['s:9', 's:10'])   # sin las elegidas

    def test_ensure_ahead_covers_eight_days_in_both_scopes(self):
        from unittest import mock
        import datetime as _dt
        seen = []
        with mock.patch.object(ai_select, 'ensure', lambda conn, key, day=None, scope='week', model=None, requester=None, today=None: (seen.append((day, scope)) or {'status': 'completed', 'usage': {'input_tokens': 1}})):
            out = ai_select.ensure_ahead(None, 'k', today=_dt.date(2026, 10, 28))
        # 30-10-2026: hoy y 7 días en los dos alcances (16) y del día 8 al 30 solo «día» (23)
        self.assertEqual((out['calls'], len(seen), seen[0], seen[15], seen[-1]), (39, 39, ('2026-10-28', 'day'), ('2026-11-04', 'week'), ('2026-11-27', 'day')))

    def test_stale_far_days_and_days_entering_the_week(self):
        today = _date(2026, 10, 30)
        self.assertFalse(ai_select.stale('2026-10-29T10:00:00+00:00', '2026-11-20', today))   # lejano, hecho ayer
        self.assertTrue(ai_select.stale('2026-10-27T10:00:00+00:00', '2026-11-20', today))    # lejano, hace 3 días
        self.assertTrue(ai_select.stale('2026-10-25T10:00:00+00:00', '2026-11-04', today))    # ya en la semana, elegido desde lejos
        self.assertFalse(ai_select.stale('2026-10-29T10:00:00+00:00', '2026-11-04', today))


if __name__ == '__main__':
    unittest.main()
