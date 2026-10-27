"""Calidad de datos tras la auditoría del 27-10-2026: hora de la próxima sesión, admisión de Eventbrite,
cine que también es teatro, textos de otro acto y pregunta a la IA en categorías de recinto."""
import collections
import datetime as dt
import unittest
from unittest import mock

from mvp import catalog
from src import ai_assist, organizer_text, taxonomy


def projection():
    return collections.defaultdict(lambda: None, {'url': ''})


class HoraDeLaProximaSesion(unittest.TestCase):
    def event(self):
        occ = [{'date': '2024-08-02', 'time': '21:00'}, {'date': '2026-11-06', 'time': '19:30'}, {'date': '2026-12-04', 'time': '19:30'}]
        return {'source': 'venue_ia_teatreneu', 'occurrences': occ, 'hours_by_day': {}, 'start': '2024-08-02', 'end': '2026-12-04',
                'kind': 'program', 'category': 'Artes escénicas', 'title': 'Última planta', 'format': 'program', 'family_audience': False}

    def test_cabecera_con_la_proxima_y_el_dia_pedido_intacto(self):
        with mock.patch.object(catalog, 'today', return_value=dt.date(2026, 10, 27)):
            self.assertEqual(catalog.public_fields(self.event(), projection())['time'], '19:30')
            self.assertEqual(catalog.public_fields(self.event(), projection(), requested_day='2024-08-02')['time'], '21:00')

    def test_sin_sesiones_futuras_con_hora_se_queda_la_primera(self):
        e = self.event(); e['occurrences'] = [{'date': '2024-08-02', 'time': '21:00'}, {'date': '2026-11-06', 'time': None}]
        with mock.patch.object(catalog, 'today', return_value=dt.date(2026, 10, 27)):
            self.assertEqual(catalog.public_fields(e, projection())['time'], '21:00')


class AdmisionEventbrite(unittest.TestCase):
    def ev(self, **kw):
        base = {'source': 'venue_eventbrite', 'title': 'Algo', 'start': '2026-10-29', 'end': '2026-10-29', 'category': None}
        base.update(kw); return base

    def test_formacion_profesional_fuera(self):
        r = taxonomy.classify(self.ev(title="CEO's Night Vol. V", hint_format='Seminar', hint_category='Business'))
        self.assertEqual((r['category'], r['method']), (taxonomy.EXCLUDED, 'ocio_social_o_profesional'))
        r = taxonomy.classify(self.ev(title='BSides Barcelona 2026', hint_format='Conference', hint_category='Science & Tech'))
        self.assertEqual(r['category'], taxonomy.EXCLUDED)

    def test_fiesta_o_funcion_no_se_excluye_por_la_categoria(self):
        r = taxonomy.classify(self.ev(title='Élégance Takeover', hint_format='Party', hint_category='Business'))
        self.assertNotEqual(r['method'], 'ocio_social_o_profesional')
        r = taxonomy.classify(self.ev(title='Concierto de jazz', hint_format='Performance', hint_category='Music'))
        self.assertNotEqual(r['category'], taxonomy.EXCLUDED)

    def test_producto_de_todo_el_ano(self):
        r = taxonomy.classify(self.ev(title='Paella & Tapas Cooking Class', start='2025-12-14', end='2026-12-15', hint_format='Class', hint_category='Food & Drink'))
        self.assertEqual((r['category'], r['method']), (taxonomy.EXCLUDED, 'producto_de_ticketera'))
        r = taxonomy.classify(self.ev(title='Taller de cerámica', start='2026-11-01', end='2026-11-15', hint_format='Class', hint_category='Arts'))
        self.assertNotEqual(r['category'], taxonomy.EXCLUDED)


class CineQueTambienEsTeatro(unittest.TestCase):
    def test_espai_texas(self):
        base = {'source': 'venue_ia_espai_texas', 'category': 'Artes escénicas', 'start': '2026-11-01', 'end': '2026-11-01'}
        teatro = taxonomy.classify({**base, 'title': 'Autónomos el Musical', 'description': "Compra les teves entrades per l'espectacle AUTÓNOMOS EL MUSICAL al teatre de l'Espai Texas"})
        cine = taxonomy.classify({**base, 'title': 'Els Nens Estan Bé', 'description': "Compra les teves entrades per la pel·lícula ELS NENS ESTAN BÉ al cine de l'Espai Texas"})
        self.assertNotEqual(teatro['category'], 'cine')
        self.assertEqual(cine['category'], 'cine')


class TextoDeOtroActo(unittest.TestCase):
    titles = [('venue_ia_institut_francais', 'a', '«Le grand tour en Italie» de Ferrante Ferranti'),
              ('venue_ia_institut_francais', 'b', 'Atelier théâtre d’octobre à juin à l’Institut Français de Barcelone'),
              ('venue_ia_balana', 'c', 'Mentes Peligrosas'), ('venue_ia_balana', 'd', 'Galder Varas'),
              ('venue_ia_institut_francais', 'e', 'Ciclo de cinema alemán | “Luisa” de Julia Röskau')]

    def test_texto_ajeno_fuera_y_los_demas_se_quedan(self):
        rows = [('venue_ia_institut_francais', 'a', 'Atelier théâtre d’octobre à juin à l’Institut Français de Barcelone, animé par Sandrine Guise.', ''),
                ('venue_ia_balana', 'c', 'La promoció més esbojarrada torna amb Galder Varas i companyia a l’escenari.', ''),
                ('venue_ia_institut_francais', 'e', 'La investigación sobre el embarazo de una joven que vive en una residencia.', '')]
        self.assertEqual(organizer_text.foreign(rows, self.titles), {('venue_ia_institut_francais', 'a')})


class PreguntaEnCategoriaDeRecinto(unittest.TestCase):
    def test_teatro_de_recinto_se_pregunta_y_sala_de_musica_no(self):
        base = {'rule_status': 'probable', 'rule_ambiguous': False, 'category_method': 'categoria_recinto', 'end': '2026-12-01',
                'title': 'X', 'category': 'Artes escénicas', 'summary': ''}
        events = [{**base, 'key': 'a:1', 'public_category': 'escena'}, {**base, 'key': 'b:1', 'public_category': 'musica'}]
        with mock.patch.object(ai_assist, 'suggestions', return_value={}), mock.patch.object(taxonomy, 'eligible', return_value=True):
            self.assertEqual([k for k, _ in ai_assist.category_candidates(None, events, '2026-10-27')], ['a:1'])


if __name__ == '__main__':
    unittest.main()
