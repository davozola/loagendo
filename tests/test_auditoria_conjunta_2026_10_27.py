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


if __name__ == '__main__':
    unittest.main()
