"""Misma obra o exposición en cartel con fechas que no coinciden del todo (23-10-2026)."""
import datetime as dt
import unittest
from unittest import mock

from src import dedupe
from src.pipeline import connect
from src.sync import initialize as init_sync
from mvp import catalog


class RunPairsTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        self.n = 0

    def add(self, source, title, start, end, venue):
        self.n += 1; rid = 'r%d' % self.n
        self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) VALUES(?,?,?,?,?,'program','include','','','','{}')",
                          (source, rid, title, start, end))
        self.conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',NULL,NULL)", (source, rid, venue))
        return f'{source}:{rid}'

    def pairs(self):
        fake = mock.Mock(wraps=dt.date); fake.today.return_value = dt.date(2026, 10, 23); fake.fromisoformat = dt.date.fromisoformat
        with mock.patch.object(dt, 'date', fake):
            return {frozenset(p) for p in dedupe.run_pairs(self.conn)}

    def test_temporadas_solapadas_en_la_misma_sala(self):
        a = self.add('generalitat', 'El Mago Pop', '2026-10-14', '2027-01-31', 'Teatre Victòria')
        b = self.add('venue_ia_teatre_victoria', 'Espectacle "El Mago Pop"', '2026-10-14', '2027-02-28', 'Teatre Victòria')
        self.assertIn(frozenset((a, b)), self.pairs())

    def test_funciones_sueltas_dentro_de_la_temporada(self):
        run = self.add('venue_ia_balana', 'Mamma Mia!', '2026-09-26', '2027-01-24', 'Teatre Tívoli')
        f1 = self.add('web_conciertos_club', 'Mamma Mia!', '2026-10-24', '2026-10-24', 'Teatre Tívoli')
        self.assertIn(frozenset((f1, run)), self.pairs())

    def test_dos_grupos_de_un_curso_de_la_misma_fuente_no(self):
        self.add('opendatabcn_agenda', 'Taller de ioga', '2026-10-01', '2026-12-15', 'Centre Cívic Can Deu')
        self.add('opendatabcn_agenda', 'Taller de ioga', '2026-10-06', '2026-12-20', 'Centre Cívic Can Deu')
        self.add('guiabcn', 'Taller de ioga', '2026-10-06', '2026-12-20', 'Centre Cívic Can Deu')  # talleres: fuera de esta regla
        self.assertEqual(self.pairs(), set())

    def test_mismo_titulo_en_otra_sala_o_sin_solape_no(self):
        self.add('generalitat', 'Mamma Mia!', '2026-09-26', '2026-12-20', 'Teatre Tívoli')
        self.add('guiabcn', 'Mamma Mia!', '2026-09-26', '2026-12-20', 'Teatre Coliseum')
        self.add('guiabcn', 'Mamma Mia!', '2027-03-01', '2027-05-01', 'Teatre Tívoli')
        self.assertEqual(self.pairs(), set())


if __name__ == '__main__':
    unittest.main()
