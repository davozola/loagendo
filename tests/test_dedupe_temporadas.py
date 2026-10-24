"""Temporada, fines de semana y funciones del mismo acto en fuentes distintas (24-10-2026).

Casos de la web: «Concert per a nadons» en L'Auditori salía tres veces (Open Data la temporada, la Generalitat cada
fin de semana con sus pases y L'Auditori cada función, en castellano: «Concierto para bebés»); «Espectacle familiar
"La biblioteca secreta", de Màgia Kids» (GuiaBCN) y «Magia Kids: La biblioteca secreta» (Teatreneu). Y lo que no
debe unirse: una actividad sobre una exposición, dos actos en un mismo anuncio, una ficha de varios centros.
"""
import datetime as dt
import unittest
from unittest import mock

from mvp import catalog
from src import dedupe
from src.pipeline import connect
from src.sync import initialize as init_sync

TODAY = dt.date(2026, 10, 20)


class TemporadasTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(':memory:'); init_sync(self.conn); catalog.initialize(self.conn)
        self.n = 0

    def add(self, source, title, start, end, venue, address='', lat=None, lon=None, times=()):
        self.n += 1; rid = 'r%d' % self.n
        self.conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) "
                          "VALUES(?,?,?,?,?,'program','include','','',?,'{}')", (source, rid, title, start, end, rid))
        self.conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,?,?,?)", (source, rid, venue, address, lat, lon))
        for day, hour in times:
            self.conn.execute("INSERT INTO candidate_occurrences(source,id,local_date,local_time,evidence_field) VALUES(?,?,?,?,'test')", (source, rid, day, hour))
        return f'{source}:{rid}'

    def groups(self):
        fake = mock.Mock(wraps=dt.date); fake.today.return_value = TODAY; fake.fromisoformat = dt.date.fromisoformat
        with mock.patch.object(dt, 'date', fake):
            return dedupe.canonical_groups(self.conn)

    def nadons(self):
        season = self.add('opendatabcn_agenda', 'Concert per a nadons', '2026-10-24', '2027-05-09', "L'Auditori de Barcelona · Sala 3 Tete Montoliu",
                          'Lepant 150, 08013 BARCELONA', 41.39903, 2.18503)
        w1 = self.add('generalitat', 'Concert per a nadons', '2026-10-24', '2026-10-25', "L'Auditori", 'C. de Lepant, 150', 41.39863, 2.18530,
                      [('2026-10-24', '16:00'), ('2026-10-24', '17:15'), ('2026-10-25', '10:00'), ('2026-10-25', '11:15'), ('2026-10-25', '12:30')])
        w2 = self.add('generalitat', 'Concert per a nadons', '2027-03-06', '2027-03-07', "L'Auditori", 'C. de Lepant, 150', 41.39863, 2.18530,
                      [('2027-03-06', '16:00'), ('2027-03-07', '10:00')])
        s1 = self.add('web_auditori', 'Concierto para bebés', '2026-10-24', '2026-10-24', 'Sala 3 Tete Montoliu', 'Carrer de Lepant, 150, 08013 Barcelona',
                      times=[('2026-10-24', '16:00')])
        s2 = self.add('web_auditori', 'Concierto para bebés', '2026-10-25', '2026-10-25', 'Sala 3 Tete Montoliu', 'Carrer de Lepant, 150, 08013 Barcelona',
                      times=[('2026-10-25', '10:00')])
        return season, (w1, w2, s1, s2)

    def test_concert_per_a_nadons_una_sola_ficha_que_cubre_la_temporada(self):
        season, others = self.nadons()
        g = self.groups()
        for k in others: self.assertEqual(g.get(k), season, k)
        self.assertNotIn(season, g)

    def test_y_sale_solo_los_dias_con_funcion_con_sus_horas(self):
        season, _ = self.nadons()
        fake = mock.Mock(wraps=dt.date); fake.today.return_value = TODAY; fake.fromisoformat = dt.date.fromisoformat
        with mock.patch.object(dt, 'date', fake), mock.patch.object(catalog, '_collapse_groups', dedupe.canonical_groups):
            row = self.conn.execute("SELECT r.source,r.id,r.title,r.start_date,r.end_date,r.kind,r.eligibility,r.evidence_level,r.source_url,r.raw_json,NULL,NULL,NULL "
                                    "FROM source_records r WHERE source=? AND id=?", season.split(':', 1)).fetchone()
            e = catalog.row_to_event(self.conn, row, True, '')
        self.assertEqual(sorted(e['hours_by_day']), ['2026-10-24', '2026-10-25', '2027-03-06', '2027-03-07'])
        self.assertEqual(e['hours_by_day']['2026-10-25'], '10:00 · 11:15 · 12:30')

    def test_magia_kids_titulo_tras_los_dos_puntos(self):
        a = self.add('guiabcn', 'Espectacle familiar "La biblioteca secreta", de Màgia Kids', '2026-10-24', '2026-12-30', 'Teatreneu Multisales - Sala Xavier Fàbregas')
        b = self.add('venue_ia_teatreneu', 'Magia Kids: La biblioteca secreta', '2026-10-17', '2026-12-30', 'Teatreneu')
        self.assertEqual(self.groups().get(a), b)

    def test_funciones_del_liceu_dentro_del_periodo_de_la_generalitat(self):
        gen = self.add('generalitat', 'Miralls', '2026-11-21', '2026-11-22', 'Gran Teatre del Liceu')
        f1 = self.add('venue_liceu', 'Miralls', '2026-11-21', '2026-11-21', 'Gran Teatre del Liceu')
        f2 = self.add('venue_liceu', 'Miralls', '2026-11-22', '2026-11-22', 'Gran Teatre del Liceu')
        g = self.groups()
        self.assertEqual({g.get(f1), g.get(f2)}, {gen})   # la que cubre los dos días: no se pierde el 22

    def test_medianoche_de_la_ticketera(self):
        a = self.add('venue_dice', 'Irieix', '2027-03-05', '2027-03-06', 'Sala Upload')
        b = self.add('venue_ia_upload', 'Irieix', '2027-03-05', '2027-03-05', 'Sala Upload')
        self.assertEqual(self.groups().get(a), b)   # manda la sala: el día 6 de DICE es la madrugada

    def test_titulos_cortos_entre_comillas(self):
        a = self.add('guiabcn', 'Monòleg "Bien", a càrrec de David Puerto', '2026-11-14', '2026-11-14', 'Teatre Borràs')
        b = self.add('venue_ia_balana', 'Bien', '2026-11-14', '2026-11-14', 'Teatre Borràs')
        self.assertEqual(self.groups().get(a), b)

    def test_lo_que_no_se_une(self):
        expo = self.add('opendatabcn_agenda', "Exposició 'Juntes i Visibles'", '2026-11-05', '2026-11-26', 'Centre Cívic Drassanes')
        act = self.add('opendatabcn_agenda', "Activitat complementària a l´exposició: Juntes i visibles", '2026-11-12', '2026-11-12', 'Centre Cívic Drassanes')
        p1 = self.add('venue_dice', 'POGO: Mietze Conte · ideasforconversations · pogo djs', '2026-11-14', '2026-11-15', 'SALA APOLO')
        p2 = self.add('venue_dice', 'Palms Trax all night long / POGO: Mietze Conte · ideasforconversations · pogo djs', '2026-11-14', '2026-11-14', 'SALA APOLO')
        d1 = self.add('guiabcn', 'Cicle "El documental del mes": Projecció "Les culpables"', '2026-10-29', '2026-10-29', 'Centre Cívic Ateneu Fort Pienc')
        d2 = self.add('web_centres_civics', 'Documental del mes: Les culpables', '2026-10-29', '2026-10-29',
                      'CC La Casa Elizalde, Auditori Sant Martí, CC Vil·la Urània, CC Ateneu Fort Pienc i CC Tomasa Cuevas – Les Corts')
        g = self.groups()
        for k in (expo, act, p1, p2, d1, d2): self.assertNotIn(k, g, k)


if __name__ == '__main__':
    unittest.main()
