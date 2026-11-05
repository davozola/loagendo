"""Cartelera por días (5-11-2026, Espai Texas): una fecha cerca del título pero en el bloque de otro día no es de ese acto."""
import datetime as dt
import unittest

from src import ai_agenda

TODAY = dt.date(2026, 11, 5)
GRID = ("Cartellera Teatre novembre Dl Dt Dc Dj Dv Ds Dg 01 Dl 02 Dt 03 Dc 04 Dj 05 Dv 06 nov. Dv 06 RITA 19:00 BIOPIC 21:30 "
        "Ds 07 nov. Ds 07 RITA 17:30 RITA 19:30 AUTÓNOMOS EL MUSICAL 22:15 Dg 08 nov. Dg 08 RITA 17:30 Dl 09 Dt 10 "
        "Ds 12 des. Ds 12 ACORAR 12:30 RITA 17:30 RITA 19:30 Dg 13 des. Dg 13 ACORAR 12:30 RITA 17:30 Dl 14 Dt 15 Dc 16 des. "
        "Dc 16 L'ESTIUEIG 20:00 Dj 17 des. Dj 17 L'ESTIUEIG 19:00 Dc 23 des. Dc 23 L'ESTIUEIG 20:00 Dj 24")


def ses(day, quote, hour=''):
    return {'fecha': day, 'cita_fecha': quote, **({'hora': hour, 'cita_hora': hour} if hour else {})}


class CarteleraPorDias(unittest.TestCase):
    def setUp(self): self.text, self.links = ai_agenda.clean(f'<p>{GRID}</p>', 'https://espaitexas.cat/teatre/')

    def test_funciones_de_otra_obra_no_pasan(self):
        item = {'titulo': 'RITA', 'sesiones': [ses('2026-11-06', 'Dv 06 nov.', '19:00'), ses('2026-11-07', 'Ds 07 nov.', '17:30'),
                                               ses('2026-12-13', 'Dg 13 des.', '17:30'), ses('2026-12-16', 'Dc 16 des.', '20:00'),
                                               ses('2026-12-23', 'Dc 23 des.', '20:00')]}
        act, why = ai_agenda.verify(item, self.text, self.links, TODAY)
        self.assertEqual([d for d, _ in act['sesiones']], ['2026-11-06', '2026-11-07', '2026-12-13'])
        self.assertTrue(any('otro día' in w for w in why))

    def test_varias_obras_el_mismo_dia(self):
        act, _ = ai_agenda.verify({'titulo': 'AUTÓNOMOS EL MUSICAL', 'sesiones': [ses('2026-11-07', 'Ds 07 nov.', '22:15')]}, self.text, self.links, TODAY)
        self.assertEqual(act['sesiones'], [('2026-11-07', '22:15')])
        act, _ = ai_agenda.verify({'titulo': "L'ESTIUEIG", 'sesiones': [ses('2026-12-16', 'Dc 16 des.', '20:00'), ses('2026-12-23', 'Dc 23 des.', '20:00')]}, self.text, self.links, TODAY)
        self.assertEqual([d for d, _ in act['sesiones']], ['2026-12-16', '2026-12-23'])

    def test_lista_de_dias_detras_del_titulo_sigue_valiendo(self):
        text, links = ai_agenda.clean('<p>Jazz a la fresca: dv 20, ds 21 i dg 22 de novembre</p>', 'https://x.test/')
        act, _ = ai_agenda.verify({'titulo': 'Jazz a la fresca', 'sesiones': [ses('2026-11-20', 'dv 20'), ses('2026-11-21', 'ds 21'), ses('2026-11-22', 'dg 22 de novembre')]}, text, links, TODAY)
        self.assertEqual(len(act['sesiones']), 3)


    def test_periodo_de_la_obra_siguiente_no_pasa(self):
        text, links = ai_agenda.clean("<p>RITA / UNA COMÈDIA DE MARTA BUCHACA Comprar 06/11/26 - 13/12/26 BIOPIC / NITS D'IMPRO BARCELONA Comprar 18/09/26 - 29/01/27</p>", 'https://espaitexas.cat/teatre/')
        bad, why = ai_agenda.verify({'titulo': 'RITA', 'periodo': {'inicio': '2026-09-18', 'fin': '2027-01-29', 'cita': '18/09/26 - 29/01/27'}}, text, links, TODAY)
        self.assertIsNone(bad)
        ok, _ = ai_agenda.verify({'titulo': 'RITA', 'periodo': {'inicio': '2026-11-06', 'fin': '2026-12-13', 'cita': '06/11/26 - 13/12/26'}}, text, links, TODAY)
        self.assertEqual(ok['periodo'], ('2026-11-06', '2026-12-13'))
        ok, _ = ai_agenda.verify({'titulo': 'BIOPIC', 'periodo': {'inicio': '2026-09-18', 'fin': '2027-01-29', 'cita': '18/09/26 - 29/01/27'}}, text, links, TODAY)
        self.assertEqual(ok['periodo'], ('2026-09-18', '2027-01-29'))


if __name__ == '__main__':
    unittest.main()
