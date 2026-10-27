"""Modelo de participación (David, 27-10-2026, aprobado 21:04): cursos completos, grupos y servicios estables y
atracciones permanentes fuera de la Agenda (reversible: una corrección editorial los devuelve); exposiciones de las
agendas generalistas por su enlace oficial; horario amplio arriba y patios escolares reunidos (public.js)."""
import unittest
from pathlib import Path
from src import taxonomy
from mvp import catalog

ROOT = Path(__file__).resolve().parents[1]


def ev(title, start='2026-09-28', end='2026-12-14', **kw):
    base = {'title': title, 'start': start, 'end': end, 'kind': 'course', 'format': 'workshop', 'source': 'opendatabcn_agenda',
            'category': 'Talleres y experiencias', 'venue_names': ['Centre Cívic Sant Andreu'], 'price_label': ''}
    return {**base, **kw}


class CursosTests(unittest.TestCase):
    def method(self, e, override=None): return taxonomy.classify(e, override)['method']

    def test_curso_de_trimestre_fuera(self):
        e = ev("Taller 'Pilates'", price_label='Entrada general: 37.66 € · Reducció i subvenció dels imports als cursos')
        self.assertEqual(self.method(e), 'curso_completo')
        self.assertEqual(self.method(ev("Taller 'Clown'", price_label='Entrada general: 60 € per trimestre')), 'curso_completo')

    def test_precio_de_curso_en_la_ficha_detallada(self):
        self.assertEqual(self.method(ev("Taller 'Zumba'", source='guiabcn', price_note='Preu: 45 € / trimestre')), 'curso_completo')

    def test_talleres_de_museo_gratis_o_por_sesion_se_quedan(self):
        self.assertNotEqual(self.method(ev("Taller 'Bèsties i bestioles'", venue_names=["Museu Nacional d'Art de Catalunya"], price_label='Entrada Gratuïta')), 'curso_completo')
        self.assertNotEqual(self.method(ev("Taller 'Creactivity. Autòmats'", venue_names=['CosmoCaixa Barcelona'], price_label='Entrada Gratuïta · Per entrar, cal adquirir entrada')), 'curso_completo')
        self.assertNotEqual(self.method(ev('Taller per a nadons', venue_names=["L'Auditori de Barcelona"], price_label='Entrada general: 9 € (+ despeses de gestió)')), 'curso_completo')
        self.assertNotEqual(self.method(ev('Tallers de dibuix i pintura', venue_names=['Associació Espai Random'], price_label='Entrada general de: 20 a 60 € · 1 classe: 20 € · Abonament 4 classes')), 'curso_completo')

    def test_umbral_solo_en_equipamientos_de_barrio(self):
        # Revisión 27-10-2026: sin frase de curso entero, el importe solo excluye en centres cívics, casals, ateneus…
        self.assertEqual(self.method(ev("Taller 'Ceràmica'", venue_names=["Ateneu L'Harmonia"], price_label='Entrada general: 90 € Preu reduït: 74 €')), 'curso_completo')
        self.assertNotEqual(self.method(ev("Taller infantil 'Arqueòlegs per un dia'", venue_names=['Campus Arqueològic'], price_label='Entrada general: 20 € Entrada club: 15 €')), 'curso_completo')
        self.assertEqual(self.method(ev("Taller 'Sevillanes'", venue_names=['Galeria X'], price_label='Entrada general: 31 € mensual')), 'curso_completo')

    def test_gratis_material_o_corto_se_quedan(self):
        self.assertNotEqual(self.method(ev("Taller 'Conversa en català'", price_label='Entrada Gratuïta + 3 € de material')), 'curso_completo')
        self.assertNotEqual(self.method(ev("Taller 'Ioga'", end='2026-10-02', price_label='Entrada general: 60 € per trimestre')), 'curso_completo')

    def test_inscripcion_abierta_se_queda(self):
        self.assertNotEqual(self.method(ev("Taller 'Pilates'", price_label='60 € per trimestre', open_enrollment='Inscripció oberta tot el curs')), 'curso_completo')

    def test_reversible_con_correccion_editorial(self):
        e = ev("Taller 'Pilates'", price_label='60 € per trimestre')
        out = taxonomy.classify(e, {'category': 'talleres', 'note': 'Lo queremos'})
        self.assertEqual((out['category'], out['status']), ('talleres', 'editorial'))


class GruposTests(unittest.TestCase):
    def method(self, title, **kw):
        return taxonomy.classify(ev(title, kind='program', format='program', source='guiabcn', category='Comunidad y encuentros', **kw))['method']

    def test_grupos_y_servicios_estables_fuera(self):
        for title in ('Grup de senderisme', "Espai 'Sala d’Informàtica'", "Aula oberta d'informàtica", 'Grup de conversa en català', 'Espai familiar de jocs', "Grup d'aprenentatge comunitari 'Amigurumis'"):
            self.assertEqual(self.method(title), 'grupo_o_servicio_estable', title)

    def test_lo_que_hace_un_grupo_se_queda(self):
        for title in ("Teatre 'Els Pastorets' a càrrec del Grup de Teatre Alisos", 'Trobada "Jam literària Calàbria 66"', "Rutes guiades d'Aparadors Artístics 2026",
                      "Taller 'Aula Oberta d'Informàtica'", "Cicle 'Espai Dona': Activitat 'Alimentació saludable'", "Visita guiada a l'Institut de Robòtica i Informàtica Industrial"):
            self.assertNotEqual(self.method(title), 'grupo_o_servicio_estable', title)

    def test_ofertas_permanentes(self):
        self.assertEqual(self.method("Podcast 'Eixample Barcelona Ràdio'"), 'grupo_o_servicio_estable')
        self.assertEqual(self.method("'El barri proposa': Grup obert de gimnàstica"), 'grupo_o_servicio_estable')
        self.assertNotEqual(self.method('Pòdcast "Media offline live", una Movide en directe'), 'grupo_o_servicio_estable')

    def test_un_solo_dia_se_queda(self):
        self.assertNotEqual(self.method('Grup de senderisme', end='2026-09-28'), 'grupo_o_servicio_estable')


class AtraccionTests(unittest.TestCase):
    def test_realidad_virtual_permanente_fuera_y_exposicion_inmersiva_se_queda(self):
        vr = ev("Gaudí: l'experiència de realitat virtual", start='2026-02-26', end='2026-12-31', kind='program', format='program', source='generalitat', category='Arte y exposiciones')
        self.assertEqual(taxonomy.classify(vr)['method'], 'atraccion_permanente')
        iniesta = {**vr, 'title': 'Experiència immersiva "Iniesta Experience: El Joc interior"', 'kind': 'exhibition', 'format': 'exhibition'}
        self.assertNotEqual(taxonomy.classify(iniesta)['status'], 'excluida')


class GemelasTests(unittest.TestCase):
    def test_titulo_de_otra_fuente_respalda_a_la_ia(self):
        ev_ = {'title': 'Victor Küppers Mentes Expertas', 'start': '2026-11-03', 'end': '2026-11-03', 'kind': 'single', 'format': 'one_shot',
               'source': 'venue_ia_balana', 'category': 'Artes escénicas', 'venue_names': ['Teatre Coliseum']}
        ai = {'answer': 'charlas', 'confidence': 0.85, 'model': 'm', 'reason': 'conferencia'}
        if taxonomy._classify_rules(ev_)['method'] != 'categoria_recinto': self.skipTest('fuente no marcada como recinto en esta configuración')
        self.assertEqual(taxonomy.classify(ev_, None, ai)['category'], 'escena')
        out = taxonomy.classify({**ev_, 'twin_titles': ['Conferència "Mentes expertas", a càrrec de Victor Küppers']}, None, ai)
        self.assertEqual((out['category'], out['method']), ('charlas', 'ia_con_senal'))


class ExposicionesTests(unittest.TestCase):
    def test_enlace_oficial_a_la_seccion_de_exposiciones(self):
        mater = {'api_item': {'code_url': 'https://www.dissenyhub.barcelona/ca/exposicio/mater-ultimate-punk-analogue-rhizome'}}
        self.assertEqual(catalog.effective_kind('guiabcn', mater, 'program', "Instal·lació col·lectiva 'Mater is the ultimate punk'", '2026-09-29', '2026-12-17'), 'exhibition')
        codi = {'localizaciones': [{'descripcio_html': '<a href="https://espai-imagina.com/exposicions/codi-gaudi-experiencia-inedita/">web</a>'}]}
        self.assertEqual(catalog.effective_kind('generalitat', codi, 'program', 'Codi Gaudí', '2026-09-22', '2027-01-31'), 'exhibition')

    def test_instalacio_o_mostra_solas_no_bastan(self):
        self.assertEqual(catalog.effective_kind('guiabcn', {'api_item': {'code_url': 'https://www.example.cat/'}}, 'program', "Instal·lació 'Llum'", '2026-09-29', '2026-12-17'), 'program')
        self.assertEqual(catalog.effective_kind('guiabcn', {'api_item': {'code_url': 'https://x.cat/exposicions/a'}}, 'program', "Taller a l'exposició", '2026-09-29', '2026-12-17'), 'program')


class WebTests(unittest.TestCase):
    def test_horario_amplio_arriba_y_patios_reunidos(self):
        js = (ROOT / 'static' / 'public.js').read_text()
        self.assertIn("html += openBlock(openList, live) + `<div class=\"ag-timeline\">", js)
        for text in ("'Abierto ahora'", "'Abre hoy'", "'Durante el día'", 'OPEN_FIRST = 5', "DAY_SERIES = new Set(['patis-escolars-oberts'])", "'inicio de curso'"):
            self.assertIn(text, js)
        self.assertNotIn('Horario amplio: ferias, mercados y espacios abiertos', js)


if __name__ == '__main__':
    unittest.main()
