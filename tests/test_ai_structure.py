"""Fichas largas con IA: formato, categoría y sesiones con cita comprobada (2-11-2026, src/ai_structure.py)."""
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from mvp import catalog
from src import ai_assist, ai_structure
from src.pipeline import connect

TEXT = ("Una proposta que connecta espiritualitat, cos i danses afrodiaspòriques a través d'una instal·lació i una performance site-specific. "
        "La proposta es completa amb un taller-conversa amb Heidi Ramírez al voltant dels imaginaris de l'exposició.\n"
        "• Instal·lació: Del 22 d'octubre al 10 de novembre al vestíbul del Centre Cívic\n"
        "• Performance: Dijous 22 d'octubre a les 20.30 h\n"
        "• Taller-conversa amb Heidi Ramírez: Dimecres 4 de novembre a les 18 h")
TITLE = "By the stream D'aquí surten totes aquestes extravagàncies"
ANSWER = {'n': 0, 'formato': {'valor': 'exhibition', 'cita': "Instal·lació: Del 22 d'octubre al 10 de novembre al vestíbul del Centre Cívic"},
          'categoria': 'arte', 'confianza': 'alta', 'motivo': 'Instal·lació visitable en un periodo.',
          'sesiones': [{'tipo': 'performance', 'titulo': 'Performance', 'fecha': '2026-10-22', 'inicio': '20:30', 'cita': "Performance: Dijous 22 d'octubre a les 20.30 h"},
                       {'tipo': 'taller', 'titulo': 'Taller-conversa amb Heidi Ramírez', 'fecha': '2026-11-04', 'inicio': '18:00',
                        'cita': 'Taller-conversa amb Heidi Ramírez: Dimecres 4 de novembre a les 18 h'},
                       {'tipo': 'taller', 'titulo': 'Taller inventat', 'fecha': '2026-11-05', 'inicio': '19:00', 'cita': 'Dijous 5 de novembre a les 19 h'}]}
TODAY = '2026-11-02'


def _db(folder):
    conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn); ai_assist.initialize(conn)
    raw = {'name': TITLE, 'body': TEXT, 'addresses': [{'address_name': 'Centre Cívic Sagrada Família', 'district_name': 'Eixample',
                                                         'location': {'geometries': [{'coordinates': [2.1767, 41.4054]}]}}], 'loagendo': {}}
    conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '1', TITLE, '2026-10-22', '2026-11-10', 'program', 'review', 'x', '', 'h', json.dumps(raw)))
    conn.commit(); catalog.invalidate_cache()
    return conn


def _message(rows):
    return {'content': [{'type': 'tool_use', 'name': 'estructura', 'input': {'fichas': rows}}], 'usage': {'input_tokens': 10, 'output_tokens': 5}}


class VerifyTests(unittest.TestCase):
    def test_only_quoted_sessions_inside_the_dates_survive(self):
        pl = {'titulo': TITLE, 'fechas': ['2026-10-22', '2026-11-10'], 'texto': TEXT}
        got, dropped = ai_structure.verify(ANSWER, pl)
        self.assertEqual(got['format'], 'exhibition')
        self.assertEqual([(s['title'], s['date'], s['time']) for s in got['sessions']],
                         [(f'Performance · {TITLE}', '2026-10-22', '20:30'), ('Taller-conversa amb Heidi Ramírez', '2026-11-04', '18:00')])
        self.assertEqual(len(dropped), 1)   # el taller inventado: la cita no está en el texto

    def test_titles_lose_the_date_and_generic_ones_name_their_parent(self):
        t = ai_structure.session_title
        self.assertEqual(t("13 d'abril de 2026. Cants I–IV", 'charla', 'Curs'), 'Cants I–IV')
        self.assertEqual(t('Inauguració el divendres 6 de novembre a les 18.30 h', 'inauguracion', 'Exposició "Vides queer"'), 'Inauguració · Exposició "Vides queer"')
        self.assertEqual(t("Itinerari: 'Un passeig de dones al Cementiri de Sarrià'", 'visita', 'X'), "Itinerari: 'Un passeig de dones al Cementiri de Sarrià'")
        self.assertEqual(t('Taller-conversa amb Heidi Ramírez', 'taller', 'X'), 'Taller-conversa amb Heidi Ramírez')


class DecideTests(unittest.TestCase):
    def ev(self, title, fmt='one_shot', cat='escena'):
        return {'title': title, 'structure_basis': {'format': fmt, 'category': cat}}

    def test_high_confidence_exhibition_with_its_quote_applies_format_and_category(self):
        d = ai_structure.decide({'format': 'exhibition', 'format_quote': "Instal·lació: Del 22 d'octubre", 'category': 'arte', 'confidence': 'alta'},
                                self.ev(TITLE), rule_status='confirmada')
        self.assertEqual((d['format'], d['category'], d['suggested']), ('exhibition', 'arte', {}))

    def test_a_title_that_names_the_activity_never_becomes_an_exhibition(self):
        d = ai_structure.decide({'format': 'exhibition', 'format_quote': "l'exposició temporal 'Trames'", 'category': 'arte', 'confidence': 'alta'},
                                self.ev("Visites guiades a l'exposició temporal 'Trames'", 'program', 'visitas'), rule_status='confirmada')
        self.assertEqual((d['format'], d['category']), (None, None))
        self.assertEqual(d['suggested'], {'format': 'exhibition', 'category': 'arte'})

    def test_medium_confidence_and_editorial_decisions_stay_as_suggestions(self):
        d = ai_structure.decide({'format': 'festival', 'format_quote': 'Mostra de Teatre', 'category': 'escena', 'confidence': 'media'}, self.ev('V Mostra de Teatre Amateur'))
        self.assertEqual((d['format'], d['suggested']), (None, {'format': 'festival'}))
        d = ai_structure.decide({'format': 'exhibition', 'format_quote': "Instal·lació: Del 22 d'octubre", 'category': 'arte', 'confidence': 'alta'},
                                self.ev(TITLE), rule_status='confirmada', editorial=True)
        self.assertEqual((d['format'], d['category'], d['suggested']), ('exhibition', None, {'category': 'arte'}))

    def test_category_alone_does_not_override_a_sure_rule(self):
        d = ai_structure.decide({'category': 'charlas', 'confidence': 'alta'}, self.ev('Curs', 'course', 'talleres'), rule_status='confirmada')
        self.assertEqual((d['category'], d['suggested']), (None, {'category': 'charlas'}))
        d = ai_structure.decide({'category': 'charlas', 'confidence': 'alta'}, self.ev('Curs', 'course', 'talleres'), rule_status='pendiente')
        self.assertEqual(d['category'], 'charlas')


class ApplyTests(unittest.TestCase):
    def test_the_answer_turns_the_card_into_an_exhibition_and_its_sessions_into_acts(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _db(folder)
            ev = catalog.event_detail(conn, 'opendatabcn_agenda', '1')
            self.assertTrue(ai_structure.needs(ev))
            before = (ev['format'], ev['public_category'])
            self.assertNotEqual(before, ('exhibition', 'arte'))
            events = catalog.all_events(conn)
            items = ai_assist.structure_candidates(conn, events, TODAY)
            self.assertEqual([k for k, _ in items], ['opendatabcn_agenda:1'])
            # Sonnet no admite forzar la herramienta: el primer intento da 400 y se reintenta en «auto».
            calls = []
            def requester(method, url, key, body=None, timeout=60, raw=False):
                calls.append(body.get('tool_choice'))
                if body['tool_choice']['type'] == 'tool':
                    raise urllib.error.HTTPError(url, 400, 'Bad Request', {}, io.BytesIO(b'{"error":"tool_choice"}'))
                return _message([ANSWER])
            out = ai_structure.run(conn, 'k', events, TODAY, requester)
            self.assertEqual((out['asked'], out['stored'], out['sessions']), (1, 1, 1))   # la performance ya pasó; el taller inventado no pasa
            self.assertEqual([c['type'] for c in calls], ['tool', 'auto'])
            catalog.invalidate_cache()
            ev = catalog.event_detail(conn, 'opendatabcn_agenda', '1')
            self.assertEqual((ev['format'], ev['kind'], ev['public_category'], ev['category_method']), ('exhibition', 'exhibition', 'arte', 'ia_estructura'))
            self.assertEqual(ai_assist.structure_candidates(conn, catalog.all_events(conn), TODAY), [])   # aplicar no cambia la huella: no se repregunta
            child = [e for e in catalog.all_events(conn) if e['source'] == ai_structure.SOURCE]
            self.assertEqual(len(child), 1)
            c = catalog.event_detail(conn, ai_structure.SOURCE, child[0]['id'])
            self.assertEqual((c['title'], c['start'], c['time'], c['part_of']), ('Taller-conversa amb Heidi Ramírez', '2026-11-04', '18:00', 'opendatabcn_agenda:1'))
            self.assertTrue(catalog.is_public(child[0]))
            self.assertIsNone(catalog.presentation_of(ai_structure.SOURCE))
            # La ficha madre cambia y la sesión deja de salir: se retira, no se borra.
            conn.execute("UPDATE source_records SET raw_json=?, raw_sha256='h2' WHERE source='opendatabcn_agenda' AND id='1'",
                         (json.dumps({'name': TITLE, 'body': TEXT.replace('Taller-conversa', 'Xerrada'), 'loagendo': {}}),))
            conn.commit(); catalog.invalidate_cache()
            res = ai_structure.sync_sessions(conn, catalog.all_events(conn), TODAY)
            self.assertEqual((res['sessions'], res['retired']), (0, 1))
            self.assertEqual(conn.execute('SELECT eligibility FROM source_records WHERE source=?', (ai_structure.SOURCE,)).fetchone()[0], 'exclude')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM source_record_retirements WHERE source=?', (ai_structure.SOURCE,)).fetchone()[0], 1)

    def test_a_session_already_published_by_its_source_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = _db(folder)
            raw = {'name': 'Taller-conversa amb Heidi Ramírez', 'body': 'Taller.', 'addresses': [{'address_name': 'Centre Cívic Sagrada Família', 'district_name': 'Eixample'}], 'loagendo': {}}
            conn.execute('INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?,?,?)', ('opendatabcn_agenda', '2', raw['name'], '2026-11-04', '2026-11-04', 'single', 'review', 'x', '', 'h', json.dumps(raw)))
            conn.commit(); catalog.invalidate_cache()
            events = catalog.all_events(conn)
            out = ai_structure.run(conn, 'k', events, TODAY, lambda *a, **k: _message([ANSWER]))
            self.assertEqual((out['sessions'], out['skipped']), (0, 1))


if __name__ == '__main__':
    unittest.main()
