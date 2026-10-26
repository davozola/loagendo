"""Parte diario con calidad del conjunto y auditoría semanal (26-10-2026)."""
import datetime as dt
import sqlite3
import unittest

from src import daily_report, weekly_audit

REPORT = """## P1. Horas de inicio repetidas en varios días
- Origen: REGLA
## P2. Congresos profesionales admitidos
### 2. Las tres mejoras prioritarias
1. Algo
### 3. Incidencias individuales graves
https://ontoca.com/e/guiabcn/123 | FUERA: congreso de empresa | quitar (evidencia: "congrés"; certeza: confirmado)
https://ontoca.com/e/venue_dice/ab-c | DUPLICADO: mismo concierto | duplicado de https://ontoca.com/e/x/1 (evidencia: "x"; certeza: sospecha)
Revisadas: 80 fichas · patrones: 2 · mejoras propuestas: 3 · incidencias individuales: 2
"""


class Auditoria(unittest.TestCase):
    def test_parse(self):
        patterns, top, serious = weekly_audit.parse(REPORT)
        self.assertEqual([p['title'] for p in patterns], ['Horas de inicio repetidas en varios días', 'Congresos profesionales admitidos'])
        self.assertEqual([(s['key'], s['type']) for s in serious], [('guiabcn:123', 'FUERA'), ('venue_dice:ab-c', 'DUPLICADO')])

    def test_render(self):
        patterns, _, serious = weekly_audit.parse(REPORT)
        subject, body, text = weekly_audit.render({'day': '2026-10-26', 'model': 'm', 'sample_size': 80, 'composition': {'azar': 40}, 'patterns': patterns,
                                                   'serious': serious, 'usage': {'input_tokens': 10, 'output_tokens': 5}}, REPORT)
        self.assertIn('2 errores graves', subject)
        self.assertLess(body.index('Errores graves'), body.index('Patrones'))


class Parte(unittest.TestCase):
    def data(self, **kw):
        base = {'today': '2026-10-26', 'alerts': [], 'resolved': [], 'sources': [], 'total_acts': 100, 'total_week_ago': None, 'runs': {}, 'failing': [],
                'publication': None, 'new': [('2026-10-25', 3)], 'traffic': None, 'festivals': None, 'ai': None, 'fest_watch': None,
                'freshness': [], 'coverage': {}, 'venues_lost': [], 'dups': [], 'corrections': None, 'audit': None}
        return {**base, **kw}

    def test_todo_en_orden(self):
        subject, body, _ = daily_report.render(self.data())
        self.assertIn('todo en orden', subject); self.assertIn('Nada. Todo en orden.', body)

    def test_atencion_arriba(self):
        fresh = [{'source': 'diba_bibliotecas', 'hours': 84, 'expected_hours': 6, 'last_ok': '', 'error': 'HTTP 500'}]
        audit = {'day': '2026-10-26', 'patterns': [{'title': 'P'}], 'serious': [{'key': 'a:1', 'title': 'T', 'problem': 'mal'}]}
        subject, body, _ = daily_report.render(self.data(freshness=fresh, audit=audit))
        self.assertIn('2 para revisar', subject)
        self.assertLess(body.index('diba_bibliotecas'), body.index('Indicadores'))
        self.assertIn('3 días', body)


class AgendasPorSala(unittest.TestCase):
    def test_una_sala_caida_no_es_el_trabajo(self):
        from src import source_watch
        conn = sqlite3.connect(':memory:'); source_watch.initialize(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS automation_runs (id INTEGER PRIMARY KEY, job_name TEXT, source TEXT, kind TEXT, started_at TEXT, finished_at TEXT, status TEXT, result_json TEXT, error TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS sync_runs (id INTEGER PRIMARY KEY, source TEXT, started_at TEXT, finished_at TEXT, status TEXT, error TEXT)")
        for n in range(3):
            conn.execute("INSERT INTO automation_runs(job_name,kind,started_at,status,error) VALUES('agendas-ia','ai_agenda',?, 'partial','1 falla')", ('2026-10-2%d' % n,))
        opened, resolved = [], []
        source_watch.check_jobs(conn, {'jobs': [{'name': 'agendas-ia', 'kind': 'ai_agenda'}]}, dt.datetime(2026, 10, 26, tzinfo=dt.timezone.utc), opened, resolved)
        self.assertFalse([a for a in opened if a.get('source') == 'agendas-ia'])


if __name__ == '__main__':
    unittest.main()
