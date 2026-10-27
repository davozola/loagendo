"""Auditoría conjunta 27-10-2026: casos reales que no deben volver."""
import unittest

from mvp import catalog
from src import event_status, guia_detail


class Fase1Veracidad(unittest.TestCase):
    def test_inscripcion_negada(self):
        # Las seis frases reales de GuiaBCN que daban «Requiere inscripción»
        for note in ('Sense inscripció prèvia', 'No cal inscripció prèvia Places limitades', 'Sin inscripción previa',
                     'No és necessària la inscripció', 'No cal fer reserva', 'Places limitades'):
            self.assertFalse(guia_detail.registration_in(note, r'reserva|inscripci'), note)
        for note in ('Cal inscripció prèvia', 'Inscripció prèvia a la web', 'Activitat gratuïta. Cal reserva prèvia'):
            self.assertTrue(guia_detail.registration_in(note, r'reserva|inscripci'), note)

    def test_inscripcion_guardada_se_revisa(self):
        facts = {'registration_required': True, 'schedule_note': 'Sense inscripció prèvia'}
        self.assertFalse(catalog._registration(facts, {}, 'guiabcn'))
        self.assertTrue(catalog._registration({'registration_required': True, 'schedule_note': 'Cal inscripció prèvia'}, {}, 'guiabcn'))

    def test_cancelado_al_principio_del_titulo(self):
        for t in ('Concert Cancel·lat Oval presenta: Superfan', 'CANCELADO: Geordie Greep', 'Cancel·lat - Foo'):
            self.assertTrue(event_status.title_lead(t), t)
        for t in ('El día que todo se canceló', 'Cancelled Plans live', 'Show Patético', 'Concert per a piano'):
            self.assertFalse(event_status.title_lead(t), t)
        self.assertEqual(event_status.words('CANCELADO: Geordie Greep'), {'geordie', 'greep'})

    def test_precio_que_no_es_precio(self):
        for t in ('10% DE DESCOMPTE', 'Durant la presentació es poden adquirir exemplars', 'Per determinar'):
            self.assertIsNone(catalog.reliable_price(t), t)
        self.assertEqual(catalog.reliable_price('Entrada libre. · .fragment_90133 { }'), 'Entrada libre.')
        for t in ('Desde 14,10 €', 'De 10 € a 22 €', '0 € – 307,5 €', 'Gratis', '10/12€', 'Entrada general: 5 € (+ despeses de gestió)'):
            self.assertEqual(catalog.reliable_price(t), t)

    def test_horas_del_texto_de_la_ficha(self):
        self.assertEqual(catalog.own_text_hours('Dissabte 7: 11 h Diumnege 8: 11 h Durada aproximada: 55 minuts', '2026-11-07', '2026-11-08'),
                         {'2026-11-07': '11:00', '2026-11-08': '11:00'})
        self.assertEqual(catalog.own_text_hours('a les 16.30 h i a les 19.00 h', '2026-12-05', '2027-01-30'), {'*': '16:30 · 19:00'})
        self.assertEqual(catalog.own_text_hours('19.30 h Durada aproximada: 80 minuts', '2026-11-27', '2026-11-27'), {'*': '19:30'})
        self.assertEqual(catalog.own_text_hours('De 10 a 19 h', '2026-11-01', '2026-11-30'), {})   # apertura, no pases


class Fase2Clasificacion(unittest.TestCase):
    def test_exposicion_de_sala_por_su_pagina_o_titulo(self):
        raw = lambda u: {'normalized': {'url': u}}
        k = catalog.effective_kind
        self.assertEqual(k('venue_ia_mhc', raw('https://www.mhcat.cat/exposicions/exposicions_en_curs/casal_lambda'), 'program', 'Casal Lambda. 50 anys', '2026-10-03', '2026-11-08'), 'exhibition')
        self.assertEqual(k('web_cccb', raw('https://www.cccb.org/es/w/exposiciones/world-press-photo-2026'), 'program', 'World Press Photo 2026', '2026-11-06', '2026-12-13'), 'exhibition')
        self.assertEqual(k('venue_poblenou_urban_district', raw('https://x/agenda/unfunny-paintings/'), 'program', 'La Plataforma: Matti Schulz – Unfunny Paintings', '2026-09-17', '2026-10-30'), 'exhibition')
        # Actividades en la sección de exposiciones de Santa Mònica y visitas: no
        self.assertEqual(k('venue_ia_santa_monica', raw('https://www.santamonica.cat/ca/exposicions-i-activitats/dimecres-de-so-i-cos/2026/cercle'), 'single', 'Cercle trencat', '2026-12-02', '2026-12-02'), 'single')
        self.assertEqual(k('web_macba', raw('https://www.macba.cat/es/exposiciones/x'), 'program', 'Visita comentada a la exposición', '2026-10-01', '2026-12-01'), 'program')
        self.assertEqual(k('venue_ia_mhc', raw('https://www.mhcat.cat/exposicions/x'), 'single', 'Casal Lambda', '2026-10-03', '2026-10-05'), 'single')  # menos de una semana

    def test_cursos_del_cccb(self):
        self.assertEqual(catalog.effective_kind('web_cccb', {'item': {'discipline': 'Cursos y talleres'}}, 'single', 'La Divina comedia, III', '2026-11-09', '2026-11-09'), 'course')

    def test_curso_y_taller_palabra_entera(self):
        self.assertEqual(catalog.format_of('single', 'El Concurshow de Revival +', '2026-12-12', '2026-12-13'), catalog.format_of('single', 'El Show de Revival +', '2026-12-12', '2026-12-13'))
        self.assertEqual(catalog.format_of('single', '27a Vueling Cursa de Bombers', '2026-11-01', '2026-11-01'), 'one_shot')
        self.assertEqual(catalog.format_of('single', 'Curs de ceràmica', '2026-11-01', '2026-11-01'), 'course')

    def test_genero_del_titulo_en_salas_especializadas(self):
        from src import taxonomy as T
        def cat(src, c, title): return T._classify_rules({'source': src, 'category': c, 'title': title, 'kind': 'single', 'format': 'one_shot'})['category']
        self.assertEqual(cat('venue_ia_phenomena', 'Cine y audiovisual', 'ENTREVISTA CON EL VAMPIRO (Proyección en 35 mm y VOSE)'), 'cine')
        for src, title in (('web_conciertos_club', 'Ruta 61'), ('venue_palau_musica', 'La dansa del sabre'), ('web_auditori', 'Respighi: fiestas romanas'),
                           ('venue_ticketmaster_es', 'MNEK - THE!! BULLDOZER!! TOUR!!'), ('venue_dice', 'Carrera Blanca + Menta Poleo')):
            self.assertEqual(cat(src, 'Música y vida nocturna', title), 'musica', title)
        self.assertEqual(cat('web_auditori', 'Música y vida nocturna', 'Taller para familias: Pica-So'), 'talleres')
        self.assertEqual(cat('guiabcn', 'Música y vida nocturna', 'Visita guiada al Palau'), 'charlas')   # agregadora: manda el título

    def test_solo_escolar_y_eventbrite(self):
        from src import taxonomy as T
        def r(src, title, venues=(), summary=''): return T._classify_rules({'source': src, 'title': title, 'venue_names': list(venues), 'summary': summary, 'kind': 'single', 'format': 'one_shot', 'category': ''})['category']
        self.assertEqual(r('web_macba', 'Entrelazar y anudar con Aurèlia Muñoz Primaria (de 3º a 6º)'), T.EXCLUDED)
        self.assertEqual(r('venue_ia_filmoteca', "El Meu primer Festival amb l'escola: Arco"), T.EXCLUDED)
        self.assertNotEqual(r('guiabcn', 'Patis escolars oberts al barri - Escola Bressol Canigó'), T.EXCLUDED)
        self.assertNotEqual(r('guiabcn', 'Espectacle familiar per a escoles i famílies'), T.EXCLUDED)
        self.assertEqual(r('venue_eventbrite', 'Barcelona El Born and Gothic Quarter'), T.EXCLUDED)
        self.assertEqual(r('venue_eventbrite', 'Llegir i escriure', ['Col·legi de Logopedes de Catalunya']), T.EXCLUDED)
        self.assertNotEqual(r('venue_eventbrite', "Concert al Col·legi d'Arquitectes", ["Col·legi d'Arquitectes de Catalunya"]), T.EXCLUDED)

    def test_familia(self):
        from src import taxonomy as T
        self.assertEqual(T.channels({'title': 'Humor de madre', 'age_min': 14, 'ai_family': {'quote': 'per a gaudir amb tota la família'}, 'source': 'venue_ia_teatre_muntaner'}, 'escena'), {})
        self.assertIn('familia', T.channels({'title': 'Pica Pica – Operación Halloween', 'source_text': 'el nuevo espectáculo de Pica Pica el grupo infantil más querido', 'source': 'venue_ia_teatre_apolo'}, 'escena'))


class Fase3Fichas(unittest.TestCase):
    def test_descripcion_limpia(self):
        self.assertEqual(catalog.clean_description('15 novembre, 2026. MARIA JOVER<br/> Diumenge 15<br/> <br/> "Una obra"'), 'MARIA JOVER\nDiumenge 15\n\n"Una obra"')

    def test_descripcion_que_no_describe(self):
        p = lambda t, title: catalog.description_problem(None, 'x', t, title)
        self.assertEqual(p('JAM SESSION', 'Jam Session'), 'igual_al_titulo')
        casal = ("De dimarts a dissabte, de 10 a 19h Dimecres, de 10 a 20h Diumenges i festius, de 10 a 14.30h\n\nTANCAT: Dilluns no festius, 1 i 6 de gener"
                 "\n\nAutobusos V17, H14, D20, V15 Metro L4 (groga) Barceloneta.")
        self.assertEqual(p(casal, 'Casal Lambda. 50 anys creant referents positius'), 'datos_practicos')
        self.assertEqual(p('Fa cinquanta anys, obrir camí era un acte de supervivència. El Casal Lambda va néixer en un temps difícil.', 'Casal Lambda'), '')

    def test_plantilla_por_su_forma(self):
        a = catalog.description_skeleton('Charlotte Plank actuará en la Sala Upload de Barcelona el 11 de noviembre de 2026. Entradas ya a la venta aquí.', 'Charlotte Plank')
        b = catalog.description_skeleton('Kid Kapichi actuarán en la Sala Upload de Barcelona el 11 de diciembre de 2026. Entradas ya a la venta aquí.', 'Kid Kapichi')
        self.assertEqual(a.replace('actuara ', 'actuaran '), b)

    def test_salas_del_lliure(self):
        from src.web_agendas import lliure_room
        self.assertEqual(lliure_room('GRÀCIA'), ('Teatre Lliure - Sala Lliure de Gràcia', 'C Montseny 47'))
        self.assertEqual(lliure_room('MONTJUÏC. ESPAI LLIURE')[0], 'Teatre Lliure - Sala Espai Lliure')
        self.assertEqual(lliure_room('Sala Desconeguda'), ('Sala Desconeguda', ''))

    def test_dias_de_apertura(self):
        self.assertEqual(catalog.opening_weekdays('Dimarts a divendres: 11 a 19 h\naltres hores amb cita prèvia'), {'dias': [1, 2, 3, 4], 'cita': True})
        self.assertIsNone(catalog.opening_weekdays('De dijous a diumenge, de 10 a 19 h fins al mes d’octubre'))   # por temporadas: no se afirma
        self.assertIsNone(catalog.opening_weekdays('Horari variable'))

    def test_curso_semanal_y_dia_del_listado(self):
        self.assertEqual(catalog.weekly_day('Rejoignez-nous tous les mardis, d’octobre à juin'), 1)
        self.assertEqual(catalog.weekly_day('tots els diumenges'), 6)
        self.assertIsNone(catalog.weekly_day('un sol dia'))

    def test_sesion_de_biblioteca_de_un_dia(self):
        from src.dedupe import _end_of
        self.assertEqual(_end_of('diba_bibliotecas', '2026-12-18', '2026-12-19'), '2026-12-18')
        self.assertEqual(_end_of('diba_bibliotecas', '2026-12-18', '2026-12-21'), '2026-12-21')


class Fase4Series(unittest.TestCase):
    def _items(self, rows):
        return [{'key': f'{s}:{i}', 'source': s, 'id': i, 'title_key': t.lower(), 'full_title': t.lower(), 'day': d, 'venue': v, 'lat': 41.38, 'lon': 2.17,
                 'address': '', 'slots': set()} for s, i, t, d, v in rows]

    def test_misma_obra_dias_seguidos(self):
        from src import dedupe
        items = self._items([('venue_ia_antic_teatre', 'a', 'la concha de tu madre cabaret', '2026-10-28', 'Antic Teatre'),
                             ('venue_ia_antic_teatre', 'b', 'la concha de tu madre cabaret', '2026-10-29', 'Antic Teatre'),
                             ('venue_ia_antic_teatre', 'c', 'la concha de tu madre cabaret', '2026-12-20', 'Antic Teatre')])   # dos meses después: otra temporada
        self.assertEqual(dedupe.series_pairs(None, items), [('venue_ia_antic_teatre:a', 'venue_ia_antic_teatre:b')])

    def test_no_se_juntan_conciertos_distintos_ni_cine_ni_titulos_de_sala(self):
        from src import dedupe
        items = self._items([('venue_jamboree', 'a', 'cicle john coltrane bruce barth', '2026-11-11', 'Jamboree'),
                             ('venue_jamboree', 'b', 'cicle john coltrane dion hoorn', '2026-11-12', 'Jamboree'),
                             ('venue_ia_filmoteca', 'c', 'licorice pizza', '2026-10-28', 'Filmoteca'),
                             ('venue_ia_filmoteca', 'd', 'licorice pizza', '2026-10-31', 'Filmoteca'),
                             ('venue_songkick', 'e', 'jamboree jazz', '2026-10-31', 'Jamboree Jazz Club'),
                             ('venue_songkick', 'f', 'jamboree jazz', '2026-11-01', 'Jamboree Jazz Club')])
        self.assertEqual(dedupe.series_pairs(None, items), [])


if __name__ == '__main__':
    unittest.main()
