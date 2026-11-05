"""Mejoras M1–M3 de la auditoría semanal del 3-11-2026 (reports/auditorias/2026-11-03.md)."""
import unittest

from mvp import catalog
from src import ai_agenda, ai_extract, taxonomy, weekly_audit
from src.venue_feeds import festival_category


class M1HorariosTests(unittest.TestCase):
    def test_la_auditoria_ve_todos_los_dias_y_no_solo_cuatro(self):
        hours = {f'2026-11-{d:02d}': '20:00' for d in range(1, 12)}
        view = weekly_audit._days_view(hours)
        self.assertEqual(len(view), 7); self.assertIn('11 en total', view['…']); self.assertIn('2026-11-11 20:00', view['…'])
        self.assertEqual(weekly_audit._days_view({'2026-11-01': '20:00'}), {'2026-11-01': '20:00'})

    def test_schema_de_una_sola_funcion_en_la_pagina_del_acto_se_lee_con_ia(self):
        node = {'startDate': '2026-11-21T19:30', 'endDate': '2026-11-22'}
        text = 'El Señor de los Anillos en Concierto. SÁB 21 NOV 19:30 h · DOM 22 NOV 17:00 h'
        self.assertTrue(ai_agenda._schema_misses_sessions([node], text))
        self.assertFalse(ai_agenda._schema_misses_sessions([node, dict(node)], text))   # cartelera: no se toca
        self.assertFalse(ai_agenda._schema_misses_sessions([{**node, 'endDate': '2026-11-21'}], text))   # un solo día
        self.assertFalse(ai_agenda._schema_misses_sessions([{**node, 'subEvent': [{}]}], text))
        self.assertFalse(ai_agenda._schema_misses_sessions([node], 'Sábado 21 a las 19:30 h'))


class M2DescripcionesTests(unittest.TestCase):
    def test_codigos_de_maquetador(self):
        cut = '[et_pb_section fb_built="1" module_class="mec-limited-width-section" _builder_version="4.27.4" custom_padding="0px||0px||false|false" da_dis'
        self.assertEqual(catalog.clean_description(cut), '')
        self.assertEqual(catalog.description_problem(None, 'venue_fest_dones_films_mifdb', cut, 'Dones en lluita'), 'codigo_de_maquetador')
        wrapped = '[et_pb_section fb_built="1"][et_pb_text]La directora Manal Tamimi presenta el seu documental sobre les dones de Palestina.[/et_pb_text][/et_pb_section]'
        self.assertEqual(catalog.clean_description(wrapped), 'La directora Manal Tamimi presenta el seu documental sobre les dones de Palestina.')
        self.assertEqual(catalog.description_problem(None, 'x', wrapped, 'Dones en lluita'), '')
        self.assertIn('[sic]', catalog.clean_description('Una obra con corchetes [sic] y texto normal que se queda tal cual.'))

    def test_frases_de_plantilla(self):
        for text, title in (('La Sra Tomasa at Razzmatazz at 2026-12-11', 'La Sra Tomasa'),
                            ('My New Band Believe actuará en la Sala Upload de Barcelona el 3 de noviembre de 2026. Entradas a la venta aquí.', 'My New Band Believe'),
                            ("Concierto de Th'Booty Hunters en La (2) de Apolo de Barcelona el 25 de diciembre 2026.", "Th'Booty Hunters")):
            self.assertEqual(catalog.description_problem(None, 'x', text, title), 'plantilla', text)
        real = ('La famosa orquesta sinfónica Lords of the Sound presenta en concierto El Señor de los Anillos en el Teatro Apolo de Barcelona. '
                'Un viaje musical en una inolvidable atmósfera de la Tierra Media.')
        self.assertEqual(catalog.description_problem(None, 'x', real, 'El Señor de los Anillos en Concierto'), '')
        self.assertEqual(catalog.description_problem(None, 'x', 'Concierto de Mocedades en el Teatre Apolo, una gira de despedida con sus grandes éxitos.', 'Mocedades'), '')

    def test_plantilla_con_palabras_cortas_en_el_titulo(self):
        a = catalog.description_skeleton('My New Band Believe actuará en la Sala Upload el 3 de noviembre', 'My New Band Believe')
        b = catalog.description_skeleton('Los Zigarros actuará en la Sala Upload el 9 de diciembre', 'Los Zigarros')
        self.assertEqual(a, b)

    def test_enlaces_de_lista_o_portada(self):
        for url in ('https://www.salarazzmatazz.com/', 'https://phenomena-experience.com/index?pag=cartelera', 'https://laut.es/concert', 'https://x.cat/es/agenda/'):
            self.assertTrue(catalog.listing_url(url), url)
        for url in ('https://sala-upload.com/conciertos/my-new-band-believe-barcelona-upload-2026/', 'https://site.com/?p=12',
                    'https://www.mostrafilmsdones.cat/programacio/dones-en-lluita/?occurrence=2026-11-24', ''):
            self.assertFalse(catalog.listing_url(url), url)
        from src.organizer_text import usable_link
        self.assertFalse(usable_link('https://laut.es/concert')); self.assertTrue(usable_link('https://laut.es/concert/mouse-on-mars'))


class M3CategoriaYFamiliaTests(unittest.TestCase):
    def test_categoria_del_festival_por_su_nombre(self):
        self.assertEqual(festival_category({'name': 'Mostra Internacional de Films de Dones de Barcelona - MIFDB', 'auto': True}, ['Event']), 'Cine y audiovisual')
        self.assertEqual(festival_category({'name': "Drap-Art 26 Festival Internacional d'Art Sostenible", 'auto': True}), 'Arte y exposiciones')
        self.assertIsNone(festival_category({'name': 'Festival Panoràmic', 'auto': True}, ['Event']))
        self.assertEqual(festival_category({'name': 'Festival Panoràmic', 'auto': True}, ['ScreeningEvent']), 'Cine y audiovisual')
        self.assertEqual(festival_category({'name': 'Primavera Sound'}), 'Música y vida nocturna')   # los de config/venues.json, como antes

    def test_en_concierto_en_un_teatro_es_musica(self):
        base = {'source': 'venue_ia_teatre_apolo', 'category': 'Artes escénicas', 'venue_names': ['Teatre Apolo'], 'kind': 'single', 'format': 'one_shot',
                'classification_paths': [], 'start': '2026-11-21', 'end': '2026-11-22'}
        self.assertEqual(taxonomy.classify({**base, 'title': 'El Señor de los Anillos en Concierto'})['category'], 'musica')
        self.assertEqual(taxonomy.classify({**base, 'title': 'Pica Pica – Operación Halloween'})['category'], 'escena')
        music = {**base, 'source': 'venue_sala_apolo', 'category': 'Música y vida nocturna', 'venue_names': ['Sala Apolo']}
        self.assertEqual(taxonomy.classify({**music, 'title': 'Love Actually en Concierto'})['category'], 'musica')

    def test_edad_de_la_conciliacion_no_es_la_del_publico(self):
        self.assertIsNone(ai_extract.ages_by_rule('XXII Fòrum Contra les Violències de Gènere',
                                                  'L’activitat disposa de servei de conciliació per a infants de 3 a 12 anys, amb reserva prèvia.'))
        self.assertEqual(ai_extract.ages_by_rule('Taller', 'Activitat per a infants de 3 a 12 anys.')[:2], (3, 12))


class ParteDel3Tests(unittest.TestCase):
    def test_la_relectura_cada_4_h_no_marca_el_ritmo_de_las_agendas(self):
        from src import daily_report
        self.assertEqual(daily_report._expected_minutes()[1]['ai_agenda'], 1440)

    def test_teatro_de_la_cartelera_de_teatro_del_espai_texas(self):
        base = {'source': 'venue_ia_espai_texas', 'category': 'Cine y audiovisual', 'venue_names': ['Espai Texas'], 'kind': 'single', 'format': 'one_shot',
                'classification_paths': [], 'start': '2026-11-06', 'end': '2026-11-06', 'title': 'Rita'}
        self.assertEqual(taxonomy.classify({**base, 'url': 'https://espaitexas.cat/teatre/'})['category'], 'escena')
        self.assertEqual(taxonomy.classify({**base, 'url': 'https://espaitexas.cat/cartellera-cinema/'})['category'], 'cine')

    def test_feria_de_orientacion_academica_fuera(self):
        ev = {'source': 'generalitat', 'category': '', 'venue_names': ['Universitat de Barcelona'], 'kind': 'single', 'format': 'one_shot',
              'classification_paths': [], 'start': '2026-11-20', 'end': '2026-11-20', 'title': '1a Fira de Graus UB'}
        self.assertEqual(taxonomy.classify(ev)['status'], 'excluida')


if __name__ == '__main__':
    unittest.main()
