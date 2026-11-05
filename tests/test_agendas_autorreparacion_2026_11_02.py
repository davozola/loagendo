"""Autorreparación de las agendas leídas con IA (2-11-2026): City Hall, Zumzeig y Espai Texas."""
import datetime as dt
import sqlite3
import unittest

from src import ai_agenda as A

TODAY = dt.date(2026, 11, 2)


class MismoActo(unittest.TestCase):
    def test_titulos_de_city_hall(self):
        self.assertTrue(A.same_show('LUNES l DJ KHALI l SECRET ROOM l TECHNO / HARD TECHNO ALL NIGHT LONG', 'DJ KHALI ALL NIGHT LONG | SECRET ROOM | SALA 2'))
        self.assertTrue(A.same_show('MARTES l DJ MABEMUSIK l SECRET ROOM l HOUSE / TECH HOUSE ALL NIGHT LONG', 'MABEMUSIK ALL NIGHT LONG | SECRET ROOM | SALA 2'))
        self.assertTrue(A.same_show('TUESDAY l TINY RAVE l HARD BOUNCE · SCHRANZ · INDUSTRIAL', 'TINY RAVE | HARD BOUNCE · SCHRANZ · INDUSTRIAL'))
        self.assertTrue(A.same_show('MIÉRCOLES l NALGÓTIKA X SDK l DARK TECHNO / HARD TECHNO | MAIN ROOM', 'NALGÓTIKA X SDK | MAIN ROOM'))
        self.assertTrue(A.same_show('LUNES l MONDAY SHOT PERREO l TRIBUTO LA FACTORÍA l EL ALEFIIX l OLD SCHOOL REGGAETON l MAIN ROOM',
                                    'MONDAY PERREO | TRIBUTO AL REGGAETON OLD SCHOOL: LA FACTORÍA | MAIN ROOM'))

    def test_actos_distintos_no(self):
        self.assertFalse(A.same_show('DJ KHALI ALL NIGHT LONG | SECRET ROOM | SALA 2', 'VALENTINA ALL NIGHT LONG | SECRET ROOM | SALA 2'))
        self.assertFalse(A.same_show('MIÉRCOLES l NALGÓTIKA X SDK l DARK TECHNO', 'MIÉRCOLES VALENTINA l CITY HALL l TECHNO ALL NIGHT | SECRET ROOM'))
        self.assertFalse(A.same_show('Naza', 'La bola negra'))
        self.assertTrue(A.same_show('La deriva', 'La deriva'))

    def test_sigue_en_la_pagina(self):
        text = A.norm_text('Dl 02 ELS NENS ESTAN BÉ 16:00 LA INVASIÓ DELS BÀRBARS 16:00 BLUE HERON 18:15 Concert número 21')
        self.assertTrue(A.page_mentions(text, 'ELS NENS ESTAN BÉ')); self.assertTrue(A.page_mentions(text, 'Blue Heron'))
        self.assertFalse(A.page_mentions(text, 'RITA')); self.assertFalse(A.page_mentions(text, 'DONES MUNTANYA'))
        self.assertTrue(A.page_mentions(text, 'Concert número 21')); self.assertFalse(A.page_mentions(text, 'Concert número 23'))

    def test_ultimo_dia_visible(self):
        self.assertEqual(A.page_horizon([{'sesiones': [('2026-11-02', '16:00'), ('2026-11-08', '')]}, {'periodo': ('2026-11-01', '2026-11-30')}]), '2026-11-30')
        self.assertEqual(A.page_horizon([]), '')


class MismaFicha(unittest.TestCase):
    def test_reutiliza_la_clave(self):
        conn = sqlite3.connect(':memory:')
        conn.execute('CREATE TABLE source_records (source TEXT, id TEXT, title TEXT, start_date TEXT, end_date TEXT, eligibility TEXT)')
        conn.executemany('INSERT INTO source_records VALUES (?,?,?,?,?,?)', [
            ('venue_ia_city_hall', 'old1', 'LUNES l DJ KHALI l SECRET ROOM l TECHNO ALL NIGHT LONG', '2026-11-02', '2026-11-02', 'include'),
            ('venue_ia_city_hall', 'old2', 'MIÉRCOLES VALENTINA l CITY HALL l TECHNO ALL NIGHT | SECRET ROOM', '2026-11-04', '2026-11-04', 'include')])
        recs = [{'id': 'new1', 'title': 'DJ KHALI ALL NIGHT LONG | SECRET ROOM | SALA 2', 'start': '2026-11-02'},
                {'id': 'new2', 'title': 'NALGÓTIKA X SDK | MAIN ROOM', 'start': '2026-11-04'},
                {'id': 'new3', 'title': 'VALENTINA ALL NIGHT LONG | SECRET ROOM | SALA 2', 'start': '2026-11-04'}]
        self.assertEqual(A.reuse_ids(conn, 'venue_ia_city_hall', recs, TODAY), 2)
        self.assertEqual([r['id'] for r in recs], ['old1', 'new2', 'old2'])

    def test_alerta_solo_desde_la_segunda_lectura(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1] / 'src' / 'source_watch.py').read_text(encoding='utf-8')
        self.assertIn("(lectura 1 de", src.replace('\\\\', '\\'))


if __name__ == '__main__':
    unittest.main()


class LecturaCompleta(unittest.TestCase):
    """Con sync_agenda de verdad (página y respuestas de la IA simuladas)."""
    def setUp(self):
        import tempfile
        from pathlib import Path
        from mvp import catalog
        from src.pipeline import connect
        self.folder = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.folder.name) / 't.sqlite3'); catalog.initialize(self.conn)
        self.agenda = {'slug': 'club', 'name': 'Club Prova', 'address': 'Carrer 1, Barcelona', 'type': 'music', 'urls': ['https://club.test/']}

    def tearDown(self):
        self.conn.close(); self.folder.cleanup()

    def read(self, titles, page_titles, n):
        from tests.test_ai_agenda import answer
        html = '<html><body>%s<p>v%d</p></body></html>' % (''.join('<div><h3>%s</h3><p>%d octubre</p></div>' % (t, d) for t, d in page_titles), n)
        items = [{'titulo': t, 'sesiones': [{'fecha': '2026-10-%02d' % d, 'cita_fecha': '%d octubre' % d}]} for t, d in titles]
        return A.sync_agenda(self.conn, self.agenda, 'k', today=dt.date(2026, 10, 20), fetcher=lambda u, t: (200, u, html), requester=answer(items))

    def alive(self):
        return self.conn.execute("SELECT COUNT(*) FROM source_records WHERE source='venue_ia_club' AND eligibility<>'exclude'").fetchone()[0]

    def test_otro_titulo_misma_ficha_y_lo_no_visto_no_falta(self):
        first = [('LUNES l DJ KHALI l SECRET ROOM l TECHNO ALL NIGHT LONG', 21)] + [('Concierto de la banda %s' % c, 22 + i) for i, c in enumerate('ABCDEF')]
        self.assertEqual(self.read(first, first, 1)['rows_received'], 7)
        # Al día siguiente la IA titula distinto a DJ Khali y solo ve dos conciertos, aunque la página sigue con todos.
        page = [('DJ KHALI ALL NIGHT LONG | SECRET ROOM | SALA 2', 21)] + first[1:]
        out = self.read([page[0], first[1], first[2]], page, 2)
        self.assertEqual(out['status'], 'completed'); self.assertNotIn('held', out)
        self.assertEqual(self.alive(), 7)   # sin duplicado de DJ Khali ni retiradas
        misses = self.conn.execute("SELECT COUNT(*) FROM ai_agenda_misses WHERE source='venue_ia_club'").fetchone()[0]
        self.assertEqual(misses, 0)
        warn = self.conn.execute("SELECT warning_json FROM sync_runs WHERE source='venue_ia_club' ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertIn('1 reconocidos', warn); self.assertIn('4 siguen en la p', warn.encode().decode('unicode_escape'))
