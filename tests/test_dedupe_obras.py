"""La misma obra con título de programa y título de la sala (24-10-2026).

Casos de la revisión de la web: «Teatre "Alejandra", a càrrec de Martín Rechimuzzi» y «ALEJANDRA» (Poliorama),
«Espectacle "Viejóvenes", amb Raquel Ramos i Borja Calvo» y «Viejóvenes» (Teatreneu), «Espectacle "Manual para
follarse a un macho con vagina", de i amb Pablo Alamá» y el título en mayúsculas de la Sala Fènix.
"""
import datetime as dt
import unittest

from src import dedupe
from src.pipeline import connect
from src.sync import initialize as init_sync

D = lambda n: (dt.date.today() + dt.timedelta(days=n)).isoformat()


class ObrasTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn)
        rows = [('guiabcn', 'a1', 'Teatre "Alejandra", a càrrec de Martín Rechimuzzi', D(1), D(2), 'Teatre Poliorama'),
                ('venue_ia_poliorama', 'a2', 'ALEJANDRA', D(1), D(2), 'Teatre Poliorama'),
                ('guiabcn', 'v1', 'Espectacle "Viejóvenes", amb Raquel Ramos i Borja Calvo', D(1), D(60), 'Teatreneu Multisales - Sala Cafè Teatre'),
                ('venue_ia_teatreneu', 'v2', 'Viejóvenes', D(-400), D(60), 'Teatreneu'),
                ('guiabcn', 'm1', 'Espectacle "Manual para follarse a un macho con vagina", de i amb Pablo Alamá', D(1), D(10), 'Sala Fènix'),
                ('venue_ia_sala_fenix', 'm2', 'MANUAL PARA FOLLARSE A UN MACHO CON VAGINA', D(-1), D(10), 'Sala Fènix'),
                # Actividades de una fiesta mayor con el nombre de la fiesta entre comillas: no son la misma.
                ('guiabcn', 'f1', '"Festes de Tardor de la Sagrada Família": Correfoc', D(1), D(1), 'Plaça de la Sagrada Família'),
                ('guiabcn', 'f2', '"Festes de Tardor de la Sagrada Família": Ballada de sardanes', D(1), D(1), 'Plaça de la Sagrada Família'),
                # Misma obra en otra sala: no.
                ('venue_ia_balana', 'o1', 'Alejandra', D(1), D(2), 'Teatre Goya')]
        for s, i, t, a, b, v in rows:
            self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) "
                              "VALUES(?,?,?,?,?,'single','review','','',?,'{}')", (s, i, t, a, b, i))
            self.conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',NULL,NULL)", (s, i, v))

    def test_clave_de_la_obra(self):
        self.assertIn('alejandra', dedupe._title_keys('Teatre "Alejandra", a càrrec de Martín Rechimuzzi'))
        self.assertIn('viejovenes', dedupe._title_keys('Espectacle "Viejóvenes", amb Raquel Ramos i Borja Calvo'))
        self.assertNotIn('festes de tardor de la sagrada familia', dedupe._title_keys('"Festes de Tardor de la Sagrada Família": Correfoc'))

    def test_las_tres_obras_son_una_sola_ficha(self):
        groups = dedupe.canonical_groups(self.conn)
        self.assertEqual(groups.get('guiabcn:a1'), 'venue_ia_poliorama:a2')    # manda la ficha de la sala
        self.assertEqual(groups.get('guiabcn:v1'), 'venue_ia_teatreneu:v2')
        self.assertEqual(groups.get('guiabcn:m1'), 'venue_ia_sala_fenix:m2')
        for key in ('guiabcn:f1', 'guiabcn:f2', 'venue_ia_balana:o1'):
            self.assertNotIn(key, groups)


if __name__ == '__main__':
    unittest.main()
