"""Fichas de museos y centros leídas con IA (24-10-2026): texto, imagen, pases, categoría y «En familia».

Casos reales del 24-10-2026: «Soc lluna, sol i estrella» (Fundació Joan Miró) y «Ptitécouti» (Arts Santa
Mònica) salían como «Exposición», sin descripción, fuera de «En familia» y, la segunda, sin imagen y con un
solo pase de los tres.
"""
import datetime as dt
import json
import unittest

from mvp import catalog
from src import ai_agenda, official_dates, organizer_text, taxonomy
from src.pipeline import connect
from src.sync import initialize as init_sync
from src.venue_feeds import meta_tags, og_meta

TODAY = dt.date(2026, 10, 24)

# Estructura de la página de la Fundació Joan Miró (recortada): og:description con apóstrofos.
MIRO_URL = 'https://www.fmirobcn.org/ca/activitats/families/programacio/159/soc-lluna-sol-i-estrella'
MIRO = ('<html><head><title>Soc lluna, sol i estrella | Famílies | Fundació Joan Miró</title>'
        '<meta property="og:title" content="Soc lluna, sol i estrella | Famílies | Fundació Joan Miró">'
        '<meta name="description" content="Taller familiar d\'exploració de l\'obra de Joan Miró i de creació d\'un gran mural final entre totes les famílies.">'
        '<meta property="og:description" content="Taller familiar d\'exploració de l\'obra de Joan Miró i de creació d\'un gran mural final entre totes les famílies.">'
        '<meta property="og:image" content="https://www.fmirobcn.org/media/upload/cache/fmiro241027_046.jpg"></head><body>'
        '<header><img src="/media/img/logo.png"><nav><p>Visita · Col·lecció · Exposicions · Activitats · Famílies · Botiga i llibreria online</p></nav></header>'
        '<main><div id="main-content"><div class="header"><p class="ambit">Col·lecció Joan Miró</p><h1 class="b">Soc lluna, sol i estrella</h1>'
        '<p class="activitat">Taller d’arts plàstiques</p></div>'
        '<figure><img src="/media/upload/gif/fmiro241027-046_1730302105.jpg"></figure>'
        '<div class="act-left"><p>Què passaria si en lloc d\'observar una obra de Miró passessis a formar-ne part?&nbsp;Com et mouries si fossis un sol? I si fossis una lluna?&nbsp;</p>'
        '<p>Els elements del cel eren formes recurrents en l\'obra de Joan Miró: la lluna, el sol, les estrelles, igual que els colors primaris. '
        'Passejarem per les sales fixant-nos en aquests elements i després farem un mural entre totes les famílies!&nbsp;</p>'
        '<p>Una activitat creada i conduïda per <a href="#">Les Rupestres</a>.</p></div>'
        '<div class="act-right"><h2>Durada</h2><p>1 hora 30 minuts</p><h2>Dates</h2><p>25 d\'octubre, 1 de novembre i 6 de desembre de 2026, a les 11.30h</p>'
        '<h2>Edat recomanada</h2><p>Nens i nenes d\'entre 3 i 5 anys</p><h2>Preu</h2><p>5 €, 4 € carnet famílies, 3 € Amics FJM</p></div></div></main>'
        '<footer><p>Subscriu-te al butlletí per rebre la programació de la Fundació Joan Miró cada setmana al teu correu electrònic.</p></footer></body></html>')

# Estructura de la página de Arts Santa Mònica (recortada): sin og:description, sin og:image, sin schema.org.
SM_URL = 'https://www.santamonica.cat/ca/exposicions-i-activitats/activitats/2026/Ptitecouti'
SM = ('<html><head><title>Ptitécouti</title><meta name="keywords" content="Activitat"></head><body>'
      '<div class="header"><img src="/content/dam/aem-arts/icons/logo-santa-monica.svg"></div>'
      '<div class="cmp-headerdetail"><div class="cmp-title"><h1 class="cmp-title__text">Ptitécouti</h1></div>'
      '<div class="cmp-text"><h6>Concert familiar amb Ayako Okubo</h6></div>'
      '<div class="header-page-dates">24 octubre de 12h a 17:30h | Concert, performance | Sala Bar</div>'
      '<div class="cmp-richtext"><p><b>Tres passis: 12-12.30h / 16-16.30h / 17-17.30h</b></p><p>De 0 a 4 anys. Duració 30 minuts.&nbsp;</p>'
      '<p>Activitat gratuïta, amb inscripció prèvia</p><p>Idioma: sense idioma</p></div>'
      '<div class="image__wrapper"><img class="image" src="/content/dam/aem-arts/activitats/2026/24-octubre/ptitecouti.png"><p>Pauline Marfang</p></div></div>'
      '<div class="cmp-text"><p>Abans de les paraules, hi ha els sons. PTITÉCOUTI convida els nadons i infants de fins a 3 anys a descobrir un món de ressonàncies, '
      'llum, aigua i objectes sonors artesanals. A través de la respiració, el moviment i la vibració, es desplega gradualment un paisatge musical íntim '
      'que obre l\'oïda a noves maneres d\'escoltar.</p></div>'
      '<div class="cmp-text"><p>Vols rebre al teu correu la programació, les convocatòries obertes i les últimes novetats? Subscriu-te al nostre butlletí!</p></div>'
      '</body></html>')


def _db():
    conn = connect(':memory:'); init_sync(conn); catalog.initialize(conn)
    for source, rid, title, day, url in (('venue_ia_fundacio_miro', 'miro', 'Soc lluna, sol i estrella', '2026-11-01', MIRO_URL),
                                         ('venue_ia_santa_monica', 'sm', 'Ptitécouti', '2026-10-24', SM_URL)):
        conn.execute("INSERT INTO source_records(source,id,title,start_date,end_date,kind,eligibility,evidence_level,source_url,raw_sha256,raw_json) "
                     "VALUES(?,?,?,?,?,'single','include','',?,'',?)", (source, rid, title, day, day, url, json.dumps({'loagendo': {}})))
        conn.execute("INSERT INTO source_venues VALUES(?,?,0,?,'',NULL,NULL)", (source, rid, 'Fundació Joan Miró' if rid == 'miro' else 'Arts Santa Mònica'))
    return conn


def _fetch(url, timeout):
    return 200, url, (MIRO if 'fmirobcn' in url else SM)


class MetaTagsTest(unittest.TestCase):
    def test_el_apostrofo_no_corta_la_descripcion(self):
        # Antes: «Taller familiar d» (17 caracteres) y la ficha se quedaba sin texto por «corto».
        self.assertEqual(og_meta(MIRO)['og:description'], "Taller familiar d'exploració de l'obra de Joan Miró i de creació d'un gran mural final entre totes les famílies.")
        self.assertEqual(meta_tags(MIRO)['og:title'], 'Soc lluna, sol i estrella | Famílies | Fundació Joan Miró')

    def test_atributos_en_cualquier_orden_y_comillas_simples(self):
        page = "<meta content='Quote \"x\" dins' name='description'><meta content=\"https://a/b.jpg\" property=\"og:image\">"
        self.assertEqual(meta_tags(page)['description'], 'Quote "x" dins')
        self.assertEqual(og_meta(page), {'og:image': 'https://a/b.jpg'})


class BodyTextTest(unittest.TestCase):
    def test_parrafos_tras_el_titulo_y_su_foto(self):
        text, image = organizer_text.body_text(SM, 'Ptitécouti')
        self.assertTrue(text.startswith('Abans de les paraules, hi ha els sons.'))
        self.assertNotIn('butlletí', text)      # aviso del boletín: fuera
        self.assertNotIn('De 0 a 4 anys', text)  # líneas cortas: no son la descripción
        self.assertEqual(image, '/content/dam/aem-arts/activitats/2026/24-octubre/ptitecouti.png')  # no el logo

    def test_sin_encabezado_con_el_titulo_no_hay_texto(self):
        self.assertEqual(organizer_text.body_text(SM, 'Otro acto distinto'), ('', ''))

    def test_miro_menu_y_pie_fuera(self):
        text, image = organizer_text.body_text(MIRO, 'Soc lluna, sol i estrella')
        self.assertTrue(text.startswith("Què passaria si en lloc d'observar una obra de Miró"))
        self.assertNotIn('Botiga', text); self.assertNotIn('Subscriu', text)
        self.assertEqual(image, '/media/upload/gif/fmiro241027-046_1730302105.jpg')


class OrganizerTextRunTest(unittest.TestCase):
    def test_las_dos_fichas_tienen_texto_y_la_de_santa_monica_imagen(self):
        conn = _db()
        res = organizer_text.run(conn, fetcher=_fetch, today=TODAY)
        self.assertEqual(res['with_text'], 2)
        texts = organizer_text.texts(conn)
        self.assertTrue(texts[('venue_ia_santa_monica', 'sm')][0].startswith('Abans de les paraules'))
        self.assertTrue(texts[('venue_ia_fundacio_miro', 'miro')][0].startswith("Què passaria si en lloc d'observar"))
        self.assertEqual(conn.execute("SELECT original_url, credit FROM media_assets WHERE source='venue_ia_santa_monica'").fetchone(),
                         ('https://www.santamonica.cat/content/dam/aem-arts/activitats/2026/24-octubre/ptitecouti.png', 'Arts Santa Mònica'))

    def test_lo_que_salio_corto_con_el_lector_anterior_se_vuelve_a_leer(self):
        conn = _db(); organizer_text.initialize(conn)
        conn.execute("INSERT INTO organizer_texts(source,id,url,text,page_title,status,fetched_at) VALUES('venue_ia_fundacio_miro','miro',?,'Taller familiar d','','corto','2026-10-24T00:34:57+00:00')", (MIRO_URL,))
        self.assertIn(('venue_ia_fundacio_miro', 'miro', 'Soc lluna, sol i estrella', MIRO_URL), organizer_text.candidates(conn, 10, TODAY))


class PassesTest(unittest.TestCase):
    def test_lista_de_pases(self):
        self.assertEqual(official_dates.passes_of('Tres passis: 12-12.30h / 16-16.30h / 17-17.30h'), ['12:00', '16:00', '17:00'])
        self.assertEqual(official_dates.passes_of('Sessions: 18:00, 20:30'), ['18:00', '20:30'])

    def test_no_son_pases(self):
        for text in ('Durada: 1 hora 30 minuts', 'Sessions: 3 i 4 de novembre', 'Funcions: dijous a les 20h',
                     "Dates: 25 d'octubre, 1 de novembre i 6 de desembre de 2026, a les 11.30h"):
            self.assertEqual(official_dates.passes_of(text), [], text)

    def test_la_pagina_del_acto_da_los_pases_y_la_edad(self):
        res = official_dates.read_page(SM_URL, 'Ptitécouti', '2026-10-24', '2026-10-24', _fetch, 5)
        self.assertEqual(res['sessions'], {'2026-10-24': ['12:00', '16:00', '17:00']})
        self.assertIn('De 0 a 4 anys', res['excerpt'])

    def test_se_leen_tambien_las_fichas_que_ya_tienen_hora(self):
        conn = _db()
        conn.execute("CREATE TABLE IF NOT EXISTS candidate_occurrences (source TEXT, id TEXT, local_date TEXT, local_time TEXT)")
        conn.execute("INSERT INTO candidate_occurrences(source,id,local_date,local_time) VALUES('venue_ia_santa_monica','sm','2026-10-24','12:00')")
        official_dates.initialize_pages(conn)
        got = {c[1] for c in official_dates.page_candidates(conn, 10, TODAY)}
        self.assertIn('sm', got)


class CategoryTest(unittest.TestCase):
    def test_museo_solo_es_arte_en_su_seccion_de_exposiciones(self):
        miro = ai_agenda.agenda_for_source('venue_ia_fundacio_miro'); sm = ai_agenda.agenda_for_source('venue_ia_santa_monica')
        self.assertEqual(ai_agenda.venue_category(miro, 'https://www.fmirobcn.org/ca/totes-les-activitats/', MIRO_URL), '')
        self.assertEqual(ai_agenda.venue_category(miro, 'https://www.fmirobcn.org/ca/exposicions/', ''), 'Arte y exposiciones')
        self.assertEqual(ai_agenda.venue_category(sm, 'https://www.santamonica.cat/ca/exposicions-i-activitats', SM_URL), '')
        self.assertEqual(ai_agenda.venue_category(sm, '', 'https://www.santamonica.cat/ca/exposicions-i-activitats/exposicions/2026/x'), 'Arte y exposiciones')
        self.assertIsNone(ai_agenda.venue_category(ai_agenda.agenda_for_source('venue_ia_marula'), '', 'https://marulacafe.com/evento/x'))

    def test_category_of_ya_no_usa_el_tipo_de_sala(self):
        raw = {'source_page': 'https://www.santamonica.cat/ca/exposicions-i-activitats', 'item': {'url': SM_URL},
               'loagendo': {'category': 'Arte y exposiciones', 'schema_types': ['Event']}}
        self.assertNotEqual(catalog.category_of(raw, 'venue_ia_santa_monica', 'single'), 'Arte y exposiciones')
        self.assertEqual(catalog.category_of(raw, 'venue_ia_santa_monica', 'exhibition'), 'Arte y exposiciones')


class SubtitleTest(unittest.TestCase):
    def test_subtitulo_de_la_pagina_cuando_el_titulo_no_dice_nada(self):
        sm = {'title': 'Ptitécouti', 'source': 'venue_ia_santa_monica', 'venue_names': ['Arts Santa Mònica'],
              'source_text': 'Abans de les paraules…\n\n[Web oficial del acto] Ptitécouti\nConcert familiar amb Ayako Okubo\n24 octubre de 12h a 17:30h'}
        miro = {'title': 'Soc lluna, sol i estrella', 'source': 'venue_ia_fundacio_miro', 'venue_names': ['Fundació Joan Miró'],
                'source_text': "[Web oficial del acto] Soc lluna, sol i estrella\nTaller d’arts plàstiques\nQuè passaria si…"}
        self.assertEqual((taxonomy.classify(sm)['category'], taxonomy.classify(sm)['method']), ('musica', 'subtitulo_pagina'))
        self.assertEqual(taxonomy.classify(miro)['category'], 'talleres')
        self.assertEqual(taxonomy.classify(miro)['status'], 'probable')

    def test_sin_pagina_oficial_sigue_pendiente(self):
        self.assertEqual(taxonomy.classify({'title': 'Ptitécouti', 'source': 'venue_ia_santa_monica', 'source_text': 'Concert familiar'})['status'], 'pendiente')


class FamilyTest(unittest.TestCase):
    def test_seccion_de_familias_en_la_ruta(self):
        ch = taxonomy.channels({'source': 'venue_ia_fundacio_miro', 'title': 'Soc lluna, sol i estrella', 'url': MIRO_URL, 'venue_names': ['Fundació Joan Miró']}, 'talleres')
        self.assertIn('familia', ch); self.assertIn('/families/', ch['familia'])

    def test_el_formato_lo_dice(self):
        self.assertTrue(taxonomy.family_text('Concert familiar amb Ayako Okubo'))
        self.assertTrue(taxonomy.family_text("Taller familiar d'exploració de l'obra de Joan Miró"))
        self.assertFalse(taxonomy.family_text('Concert de la Banda Municipal'))

    def test_la_edad_de_la_pagina_del_acto(self):
        from src.ai_extract import ages_by_rule
        self.assertEqual(ages_by_rule('Ptitécouti', 'De 0 a 4 anys. Duració 30 minuts.')[:2], (0, 4))
        self.assertEqual(ages_by_rule('Soc lluna, sol i estrella', "Nens i nenes d'entre 3 i 5 anys")[:2], (3, 5))


if __name__ == '__main__':
    unittest.main()
