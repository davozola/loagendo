"""Lectura guardada de las agendas con IA (5-11-2026): si cambia una página, las demás no vuelven a la IA."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from src import ai_agenda
from tests.test_ai_agenda import GOOD, PAGE, TODAY, answer

OTHER = '<html><body><div class="ev"><a href="/evento/x/">Nit de boleros</a><span>25 octubre</span><span>20:00h</span></div></body></html>'
AG = {'slug': 'dos', 'name': 'Marula Café', 'address': 'Carrer dels Escudellers 49, 08002 Barcelona', 'type': 'music', 'urls': ['https://sala.test/agenda/', 'https://sala.test/mes/']}
BOLERO = [{'titulo': 'Nit de boleros', 'enlace': 'L1', 'sesiones': [{'fecha': '2026-10-25', 'cita_fecha': '25 octubre', 'hora': '20:00', 'cita_hora': '20:00h'}]}]


class LecturaGuardada(unittest.TestCase):
    def setUp(self):
        from mvp import catalog
        from src.pipeline import connect
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name) / 't.sqlite3'); catalog.initialize(self.conn)
        self.other, self.calls = OTHER, []

    def tearDown(self): self.conn.close(); self.tmp.cleanup()

    def fetch(self, url, timeout):
        if url.endswith('/agenda/'): return 200, url, PAGE
        if url.endswith('/mes/'): return 200, url, self.other
        return 200, url, ''

    def ai(self, method, url, key, body=None, timeout=60, raw=False):
        text = body['messages'][0]['content']; self.calls.append(text)
        return answer(BOLERO if 'boleros' in text else GOOD)(method, url, key, body, timeout)

    def sync(self, today=TODAY, force=False):
        return ai_agenda.sync_agenda(self.conn, AG, 'k', today=today, fetcher=self.fetch, requester=self.ai, force=force)

    def test_solo_la_pagina_cambiada_va_a_la_ia(self):
        self.assertEqual(self.sync()['rows_received'], 4); self.assertEqual(len(self.calls), 2)
        self.other = OTHER.replace('20:00h', '20:30h').replace('</div>', '<p>Nova data</p></div>')
        out = self.sync()
        self.assertEqual(len(self.calls), 3)                       # solo /mes/
        self.assertIn('IA (lectura guardada)', out['via'])
        self.assertEqual(out['rows_received'], 4)                   # los actos de la página sin cambios siguen igual

    def test_caduca_y_las_relecturas_forzadas_no_la_usan(self):
        self.sync(); n = len(self.calls)
        self.sync(force=True); self.assertEqual(len(self.calls), n + 2)
        self.other = OTHER.replace('</body>', '<p>Aforament limitat</p></body>')
        self.sync(today=TODAY + dt.timedelta(days=ai_agenda.READ_CACHE_DAYS)); self.assertEqual(len(self.calls), n + 4)

    def test_otra_configuracion_no_la_usa(self):
        self.sync(); n = len(self.calls)
        AG2 = {**AG, 'salas': [{'name': 'Sala B'}]}
        self.other = OTHER.replace('</body>', '<p>Aforament limitat</p></body>')
        ai_agenda.sync_agenda(self.conn, AG2, 'k', today=TODAY, fetcher=self.fetch, requester=self.ai)
        self.assertEqual(len(self.calls), n + 2)


if __name__ == '__main__':
    unittest.main()
