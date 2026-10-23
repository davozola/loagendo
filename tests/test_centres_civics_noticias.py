"""Recopilatorios de la web de centres cívics y fichas «Fins al…» (23-10-2026)."""
import datetime as dt
import unittest
from unittest import mock


def _ev(title, venue, source='web_centres_civics'):
    return {'source': source, 'title': title, 'venue_names': [venue], 'start': '2026-10-23', 'end': '2026-12-31', 'kind': 'program'}


class RecopilatoriosTests(unittest.TestCase):
    def test_articulos_a_nombre_de_la_red_quedan_fuera_aunque_nombren_un_genero(self):
        from src.taxonomy import classify
        for title, venue in [('5 tallers per preparar-se pel nou Temporals', 'Xarxa de Centres Cívics de Barcelona'),
                             ('Inscripcions als tallers de tardor: tot comença al centre', 'Xarxa de Centres Cívics de Barcelona'),
                             ('10 visites i itineraris per explorar la ciutat abans no s’acabi l’octubre', 'Diversos centres civics')]:
            with self.subTest(title=title):
                out = classify(_ev(title, venue))
                self.assertEqual(out['status'], 'excluida')
                self.assertEqual(out['method'], 'resumen_de_programa')

    def test_un_taller_de_un_centre_civic_concreto_sigue_dentro(self):
        from src.taxonomy import classify
        self.assertNotEqual(classify(_ev('Taller de ceràmica per a adults', 'Centre Cívic Can Deu'))['status'], 'excluida')

    def test_la_red_en_otra_fuente_con_genero_no_se_excluye_por_esta_regla(self):
        from src.taxonomy import classify
        self.assertNotEqual(classify(_ev('Taller de ceràmica', 'Xarxa de Centres Cívics de Barcelona', source='opendatabcn_agenda'))['method'], 'resumen_de_programa')


class FinsAlIdTests(unittest.TestCase):
    def test_el_id_no_cambia_de_un_dia_a_otro(self):
        from src import web_agendas
        page = ('<li class="views-row vigent"><div class="views-field-title-field"><a href="/centrescivics/ca/activitat/x">Acte</a></div>'
                '<div class="views-field-field-activitat-on"><div class="field-content">Centre Cívic Can Deu</div></div>'
                '<div class="views-field-field-activitat-quan"><div class="field-content">Fins al 31/12/2026</div></div></li>')
        ids = []
        for day in (dt.date(2026, 10, 12), dt.date(2026, 10, 23)):
            fake = mock.Mock(wraps=dt.date); fake.today.return_value = day
            with mock.patch.object(web_agendas.dt, 'date', fake):
                ids.append(web_agendas.parse_centres_civics(page)[0]['id'])
        self.assertEqual(ids[0], ids[1])


if __name__ == '__main__':
    unittest.main()
