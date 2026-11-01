"""Freno a las retiradas masivas de las agendas leídas con IA (1-11-2026, Fundació Miró y Casa Amèrica: una lectura
a medias retiró la mayoría de sus actos vigentes) y diagnóstico de la página vacía (Laut)."""
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src import ai_agenda
from tests.test_ai_agenda import answer

TODAY = dt.date(2026, 10, 20)
AGENDA = {'slug': 'prova', 'name': 'Sala Prova', 'address': 'Carrer de Prova 1, 08001 Barcelona', 'type': 'music', 'urls': ['https://sala.test/agenda/']}
DAYS = list(range(21, 29))


def page(days, extra=''):
    return '<html><body>%s%s</body></html>' % (''.join('<div><h3>Concert número %d</h3><p>%d octubre</p></div>' % (d, d) for d in days), extra)


def items(days):
    return [{'titulo': 'Concert número %d' % d, 'sesiones': [{'fecha': '2026-10-%02d' % d, 'cita_fecha': '%d octubre' % d}]} for d in days]


def read(conn, days, n=0):
    html = page(days, '<p>v%d</p>' % n)   # la página cambia en cada lectura
    return ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=lambda url, timeout: (200, url, html), requester=answer(items(days)))


def alive(conn):
    return conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_ia_prova' AND eligibility<>'exclude'").fetchone()[0]


class FrenoRetiradas(unittest.TestCase):
    def setUp(self):
        from mvp import catalog
        from src.pipeline import connect
        self.folder = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.folder.name) / 't.sqlite3'); catalog.initialize(self.conn)
        self.assertEqual(read(self.conn, DAYS)['rows_received'], 8)

    def tearDown(self):
        self.conn.close(); self.folder.cleanup()

    def test_lectura_a_medias_no_retira_y_avisa(self):
        out = read(self.conn, DAYS[:2], 1)
        self.assertEqual(out['status'], 'completed'); self.assertIn('retirada frenada', out['held'])
        self.assertEqual(alive(self.conn), 8)
        warn = json.loads(self.conn.execute("SELECT warning_json FROM sync_runs WHERE source='venue_ia_prova' ORDER BY id DESC LIMIT 1").fetchone()[0])
        self.assertIn('6 de 8', warn[0]); self.assertIn('lectura 1 de 3', warn[0])

    def test_a_la_tercera_lectura_igual_se_retira_y_queda_anotado(self):
        read(self.conn, DAYS[:2], 1); read(self.conn, DAYS[:2], 2)
        self.assertEqual(alive(self.conn), 8)
        out = read(self.conn, DAYS[:2], 3)
        self.assertNotIn('held', out); self.assertEqual(alive(self.conn), 2)
        rows = self.conn.execute("SELECT previous_eligibility, reason FROM source_record_retirements WHERE source='venue_ia_prova'").fetchall()
        self.assertEqual(len(rows), 6); self.assertIn('3 lecturas seguidas', rows[0][1])

    def test_si_la_pagina_vuelve_entera_no_se_retira_nada(self):
        read(self.conn, DAYS[:2], 1)
        out = read(self.conn, DAYS, 2)
        self.assertNotIn('held', out); self.assertEqual(alive(self.conn), 8)

    def test_frenada_se_relee_aunque_la_pagina_no_cambie(self):
        read(self.conn, DAYS[:2], 1)
        out = read(self.conn, DAYS[:2], 1)   # misma página: sin el freno no se llamaría a la IA
        self.assertNotIn('unchanged', out); self.assertIn('lectura 2 de 3', out['held'])

    def test_un_acto_que_falta_se_retira_a_la_segunda_lectura(self):
        out = read(self.conn, DAYS[:-1], 1)
        self.assertNotIn('held', out); self.assertEqual(alive(self.conn), 8)
        read(self.conn, DAYS[:-1], 2)
        self.assertEqual(alive(self.conn), 7)
        reason = self.conn.execute("SELECT reason FROM source_record_retirements").fetchone()[0]
        self.assertEqual(reason, 'no sale en la página en 2 lecturas seguidas')

    def test_lecturas_que_oscilan_no_retiran(self):
        read(self.conn, DAYS[:-1], 1); read(self.conn, DAYS, 2); read(self.conn, DAYS[:-1], 3)
        self.assertEqual(alive(self.conn), 8)

    def test_alerta_retirada_frenada(self):
        from src import source_watch
        read(self.conn, DAYS[:2], 1)
        source_watch.initialize(self.conn)
        opened, resolved = [], []
        orig = ai_agenda.load_agendas
        ai_agenda.load_agendas = lambda: [dict(AGENDA, activa=True)]
        try: source_watch._check_agendas(self.conn, '2026-10-20T10:00:00', opened, resolved)
        finally: ai_agenda.load_agendas = orig
        kinds = [r[0] for r in self.conn.execute("SELECT kind FROM source_alerts WHERE source='venue_ia_prova' AND resolved_at IS NULL")] \
            if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='source_alerts'").fetchone() else [a.get('kind') for a in opened]
        self.assertIn('RETIRE_HELD', kinds)


class PaginaVaciaDiagnostico(unittest.TestCase):
    def test_el_error_dice_que_trae_la_pagina(self):
        from mvp import catalog
        from src.pipeline import connect
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            read(conn, DAYS)
            down = lambda url, timeout: (200, url, '<p>Estamos preparando la nueva web. Volvemos pronto.</p>')
            out = ai_agenda.sync_agenda(conn, AGENDA, 'k', today=TODAY, fetcher=down, requester=answer([]))
            self.assertEqual(out['status'], 'failed')
            self.assertIn('caracteres', out['error']); self.assertIn('Estamos preparando la nueva web', out['error'])


class EncargoDeRestauracion(unittest.TestCase):
    def test_el_motor_aplica_el_encargo_una_vez(self):
        import importlib.util
        from mvp import catalog
        from src.pipeline import connect
        spec = importlib.util.spec_from_file_location('rr', Path(__file__).resolve().parents[1] / 'scripts' / 'restaurar_retirados.py')
        rr = importlib.util.module_from_spec(spec); spec.loader.exec_module(rr)
        with tempfile.TemporaryDirectory() as folder:
            conn = connect(Path(folder) / 't.sqlite3'); catalog.initialize(conn)
            read(conn, DAYS); read(conn, DAYS[:-1], 1); read(conn, DAYS[:-1], 2)
            self.assertEqual(alive(conn), 7)
            rr.PENDING = Path(folder) / 'restauraciones_pendientes.json'
            rr.PENDING.write_text(json.dumps({'fuente': 'venue_ia_prova'}))
            rr.sources_for = lambda name: [name]
            orig = rr.dt.date
            class D(dt.date):
                @classmethod
                def today(cls): return TODAY
            rr.dt.date = D
            try: done = rr.run_pending(conn)
            finally: rr.dt.date = orig
            self.assertEqual(done['restaurados'], 1); self.assertEqual(alive(conn), 8)
            self.assertFalse(rr.PENDING.exists()); self.assertIsNone(rr.run_pending(conn))


if __name__ == '__main__':
    unittest.main()
